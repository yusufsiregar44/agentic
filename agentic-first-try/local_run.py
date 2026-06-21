"""
Local end-to-end runner — watch the whole triage pipeline execute, with only the LLM faked.

What this does: runs Stage 1 (run_triage) then Stage 2 (run_worker) against a tiny sample repo
  that has a planted bug — exactly the code paths CI runs, narrated step by step.
Why: to *see* the flow. The model is stateless and only emits tool-calls; everything else (the
  agent loop, the real read_file/grep/run_command tools, schema validation, the label allow-list,
  the Stage-1 -> Stage-2 handoff via verdict.json, route dispatch) runs for real.
What's faked, and how:
  - The model     -> a ScriptedModel returns a fixed sequence of tool-calls (the ONE thing we stub,
                     because the model is what would otherwise hit the network). It logs each turn.
  - GitHub writes -> TRIAGE_DRY_RUN=1 makes github_api build the REAL `gh` command and LOG it
                     instead of executing, so nothing touches a live repo.
Run:  .venv/bin/python local_run.py        (from the agentic-first-try/ directory)
"""
import json
import logging
import os
import sys
from pathlib import Path

# --- import the package BEFORE we chdir into the scratch dir -------------------------------------
import triage.harness as harness
from triage import run_triage, run_worker

HERE = Path(__file__).resolve().parent
WORKDIR = HERE / ".local-demo"          # gitignored scratch space for this run's artifacts
SAMPLE = WORKDIR / "sample_repo"        # the "repository" the agent investigates


# --- logging: one clean line per event, so the flow reads top-to-bottom --------------------------
def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(name)-18s │ %(message)s", stream=sys.stdout)


def banner(title):
    line = "═" * 78
    print(f"\n{line}\n  {title}\n{line}")


# --- the planted sample repo: a real bug for the agent to find -----------------------------------
def write_sample_repo():
    if SAMPLE.exists():
        for p in sorted(SAMPLE.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        SAMPLE.rmdir()
    SAMPLE.mkdir(parents=True)
    (SAMPLE / "login.py").write_text(
        '"""Sample auth module with a planted bug (for the local triage demo)."""\n'
        'USERS = {"alice": {"password": "secret"}}\n\n'
        'def login(username, password):\n'
        '    user = USERS[username]            # BUG: KeyError when username is unknown\n'
        '    return user["password"] == password\n'
    )
    (SAMPLE / "test_login.py").write_text(
        "from login import login\n\n"
        "def test_known_user_logs_in():\n"
        '    assert login("alice", "secret") is True\n\n'
        "def test_unknown_user_returns_false():\n"
        '    assert login("bob", "nope") is False   # FAILS: raises KeyError (the planted bug)\n'
    )
    (SAMPLE / "README.md").write_text("# Sample app\nA toy login module used by the triage demo.\n")


# --- the fake model: a scripted sequence of tool-calls, logged like a real request/response ------
def _tc(cid, name, **args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _resp(*tool_calls):
    return {"choices": [{"message": {"content": None, "tool_calls": list(tool_calls)}}]}


class ScriptedModel:
    """Stands in for call_model(messages, tools). Returns the next canned response and narrates
    both sides: what history the 'model' receives, and which tool-calls it 'decides' to make."""

    def __init__(self, logger_name, steps):
        self.log = logging.getLogger(logger_name)
        self.steps = steps
        self.i = 0

    def __call__(self, messages, tools):
        last = messages[-1]
        preview = " ".join(str(last.get("content") or last.get("tool_calls")).split())[:90]
        self.log.info("← receives %d msgs (last role=%s): %s", len(messages), last.get("role", "assistant"), preview)
        resp = self.steps[self.i]
        self.i += 1
        names = [c["function"]["name"] for c in resp["choices"][0]["message"]["tool_calls"]]
        self.log.info("→ decides to call: %s", names)
        return resp


def main():
    _setup_logging()
    WORKDIR.mkdir(exist_ok=True)
    write_sample_repo()

    # Run everything against a known issue, fully local. The model is faked; gh is dry-run.
    os.environ.update({
        "REPO": "local/demo",
        "ISSUE_NUMBER": "1",
        "ISSUE_TITLE": "login() crashes for unknown usernames",
        "ISSUE_BODY": "Calling login() with a username that isn't registered raises KeyError "
                      "instead of returning False.",
        "TRIAGE_DRY_RUN": "1",                 # github_api logs the gh command, never executes it
        "GITHUB_TOKEN": "dummy-not-used",      # model is faked, so no real token is needed
        "GH_TOKEN": "dummy-not-used",
        "GITHUB_OUTPUT": "github_output",      # run_triage appends route=... here (relative to cwd)
    })
    os.chdir(WORKDIR)                          # contain verdict.json + github_output in .local-demo/
    Path("github_output").write_text("")

    # ---- STAGE 1: triage (classify + label + route) ----------------------------------------------
    banner("STAGE 1 — TRIAGE   (real loop · real read-only tools · model faked · gh dry-run)")
    triage_model = ScriptedModel("demo.triage-model", [
        _resp(_tc("c1", "list_files", directory=str(SAMPLE))),                 # 1. survey the repo
        _resp(_tc("c2", "read_file", path=str(SAMPLE / "login.py"))),         # 2. read the suspect file
        _resp(_tc("c3", "grep", pattern="password", directory=str(SAMPLE))),  # 3. confirm the area
        _resp(_tc("c4", "finish",                                             # 4. emit the verdict
                  type="bug", severity="high", route="bug",
                  is_duplicate={"likely": False, "of": None},
                  suspected_area="login.py",
                  findings="Read login.py; login() indexes USERS[username] with no membership "
                           "check -> KeyError for unknown users. Did not modify anything.",
                  comment="**Triage:** likely a bug in `login.py` — `USERS[username]` raises "
                          "KeyError for unknown usernames. Severity: high.",
                  # NOTE: 'wontfix' is OFF the allow-list and will be dropped (never created).
                  labels=["bug", "severity:high", "wontfix"])),
    ])
    harness.call_model = triage_model          # run_agent reads call_model from the harness module
    run_triage.main()

    verdict = json.loads(Path("verdict.json").read_text())
    print("\n  ── handoff artifact: verdict.json ───────────────────────────────")
    print("   " + json.dumps(verdict, indent=2).replace("\n", "\n   "))
    print(f"\n  proposed labels {verdict['labels']}  ->  allow-list kept only the known ones "
          f"(+ 'triaged'); 'wontfix' was dropped — see the dry-run `gh ... edit` line above.")
    print(f"  route output: {Path('github_output').read_text().strip() or '(none)'}  "
          f"->  this is the gate the worker job keys off.")

    # ---- STAGE 2: worker (advisory deep-dive for route=bug -> fix-it-man) -------------------------
    banner("STAGE 2 — WORKER   (route=bug -> fix-it-man · adds the real run_command tool)")
    worker_model = ScriptedModel("demo.fixit-model", [
        _resp(_tc("w1", "read_file", path=str(SAMPLE / "login.py"))),         # 1. re-read the code
        _resp(_tc("w2", "run_command",                                        # 2. RUN the tests (real!)
                  command=f"cd {SAMPLE} && {sys.executable} -m pytest test_login.py -q")),
        _resp(_tc("w3", "finish",                                             # 3. emit the RCA
                  comment="## RCA\n**Summary:** `login()` crashes for unknown usernames.\n"
                          "**Root Cause:** `USERS[username]` does a dict index with no membership "
                          "check, raising `KeyError`.\n**Evidence:** `pytest` shows "
                          "`test_unknown_user_returns_false` failing with `KeyError: 'bob'`.\n"
                          "**Recommended Fix:** use `USERS.get(username)` and return `False` when "
                          "absent.\n**Risk:** high — any unknown user crashes the call.")),
    ])
    harness.call_model = worker_model
    run_worker.main()

    banner("DONE")
    print("  What you just saw, end to end:")
    print("   • the agent loop re-sending full history each step (stateless model, stateful harness)")
    print("   • real tools: list_files / read_file / grep, then run_command actually running pytest")
    print("   • schema validation gating the verdict, and the label allow-list dropping 'wontfix'")
    print("   • the Stage-1 -> Stage-2 handoff via verdict.json + the route gate")
    print("   • every GitHub write shown as the exact `gh` command (dry-run), nothing mutated")
    print(f"\n  Artifacts left in {WORKDIR}/ : verdict.json, github_output, sample_repo/")


if __name__ == "__main__":
    main()
