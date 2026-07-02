"""
Local end-to-end runner — watch the whole triage pipeline execute, narrated step by step.

What this does: runs Stage 1 (run_triage) then Stage 2 (run_worker) against a tiny sample repo
  with a planted bug — exactly the code paths CI runs.
Two model modes:
  --real (default when config.json has a PAT): calls the REAL GitHub Models API. The model truly
        explores the repo, classifies, and decides — only the GitHub *writes* are stubbed.
  --scripted: no network. A ScriptedModel returns a fixed sequence of tool-calls, so you can read
        the flow offline and deterministically.
What's always real: the agent loop, the read_file/grep/run_command tools (run_command actually runs
  pytest on the planted bug), schema validation, the label allow-list, the verdict.json handoff,
  and the route gate.
What's never live: GitHub writes. TRIAGE_DRY_RUN=1 makes github_api build the real `gh` command and
  LOG it instead of executing — no repo/issue is touched (there is no real issue locally).

Auth: the PAT is read from config.json ({"pat": "...", "model": "optional/override"}); config.json
  is gitignored and never printed.

Run:  .venv/bin/python local_run.py              # real model (needs config.json)
      .venv/bin/python local_run.py --scripted   # offline, deterministic
      .venv/bin/python local_run.py --model openai/gpt-4o-mini
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Import the package BEFORE chdir so module-relative persona loading and imports resolve cleanly.
import triage.harness as harness
import triage.llm as llm
from triage import run_triage, run_worker
from triage.labels import validate_labels

HERE = Path(__file__).resolve().parent
WORKDIR = HERE / ".local-demo"          # gitignored scratch space
SAMPLE = WORKDIR / "sample_repo"        # the "repository" the agent investigates
CONFIG = HERE / "config.json"           # gitignored; holds the PAT (+ optional model)
# gpt-4o-mini: reliable tool-calling + friendlier free-tier rate limits, so a multi-step loop
# completes. deepseek/DeepSeek-V3-0324 also tool-calls, but the free tier rate-limits it hard
# (you'll see 429 backoffs) — set {"model": "deepseek/DeepSeek-V3-0324"} in config.json to use it.
DEFAULT_MODEL = "openai/gpt-4o-mini"


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(name)-18s │ %(message)s", stream=sys.stdout)


def banner(title):
    line = "═" * 80
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


# --- offline fake model: a scripted sequence of tool-calls (paths are relative to SAMPLE) --------
def _tc(cid, name, **args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _resp(*tool_calls):
    return {"choices": [{"message": {"content": None, "tool_calls": list(tool_calls)}}]}


class ScriptedModel:
    """Stands in for call_model(messages, tools): returns the next canned response, narrating both
    the history it 'receives' and the tool-calls it 'decides' on."""

    def __init__(self, logger_name, steps):
        self.log = logging.getLogger(logger_name)
        self.steps = steps
        self.i = 0

    def __call__(self, messages, tools):
        last = messages[-1]
        preview = " ".join(str(last.get("content") or last.get("tool_calls")).split())[:80]
        self.log.info("← receives %d msgs (last=%s): %s", len(messages), last.get("role", "assistant"), preview)
        resp = self.steps[self.i]
        self.i += 1
        names = [c["function"]["name"] for c in resp["choices"][0]["message"]["tool_calls"]]
        self.log.info("→ decides to call: %s", names)
        return resp


def _scripted_triage():
    return ScriptedModel("demo.triage-model", [
        _resp(_tc("c1", "list_files", directory=".")),
        _resp(_tc("c2", "read_file", path="login.py")),
        _resp(_tc("c3", "grep", pattern="password", directory=".")),
        _resp(_tc("c4", "finish",
                  type="bug", severity="high", route="bug",
                  is_duplicate={"likely": False, "of": None}, suspected_area="login.py",
                  findings="Read login.py; login() indexes USERS[username] with no membership "
                           "check -> KeyError for unknown users. Did not modify anything.",
                  comment="**Triage:** likely a bug in `login.py` — `USERS[username]` raises "
                          "KeyError for unknown usernames. Severity: high.",
                  labels=["bug", "severity:high", "wontfix"])),   # 'wontfix' is OFF the allow-list
    ])


def _scripted_worker():
    return ScriptedModel("demo.fixit-model", [
        _resp(_tc("w1", "read_file", path="login.py")),
        _resp(_tc("w2", "run_command", command=f"{sys.executable} -m pytest test_login.py -q")),
        _resp(_tc("w3", "finish",
                  comment="## RCA\n**Summary:** `login()` crashes for unknown usernames.\n"
                          "**Root Cause:** `USERS[username]` indexes with no membership check, "
                          "raising `KeyError`.\n**Evidence:** pytest shows "
                          "`test_unknown_user_returns_false` failing with `KeyError: 'bob'`.\n"
                          "**Recommended Fix:** use `USERS.get(username)` and return `False` when "
                          "absent.\n**Risk:** high.")),
    ])


def load_config():
    if CONFIG.is_file():
        try:
            return json.loads(CONFIG.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def main():
    parser = argparse.ArgumentParser(description="Local end-to-end triage demo.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--real", action="store_true", help="call the real GitHub Models API")
    mode.add_argument("--scripted", action="store_true", help="offline, deterministic fake model")
    parser.add_argument("--model", help="override the model id (e.g. openai/gpt-4o-mini)")
    args = parser.parse_args()

    cfg = load_config()
    pat = cfg.get("pat")
    # Default to real when a PAT is available; --scripted/--real force the choice.
    use_real = not args.scripted and (args.real or bool(pat))
    if use_real and not pat:
        sys.exit("ERROR: --real needs a PAT in config.json ({\"pat\": \"github_pat_...\"}).")
    model = args.model or cfg.get("model") or DEFAULT_MODEL

    _setup_logging()
    WORKDIR.mkdir(exist_ok=True)
    write_sample_repo()

    os.environ.update({
        "REPO": "local/demo",
        "ISSUE_NUMBER": "1",
        "ISSUE_TITLE": "login() crashes for unknown usernames",
        "ISSUE_BODY": "Calling login() with a username that isn't registered raises KeyError "
                      "instead of returning False. See login.py.",
        "TRIAGE_DRY_RUN": "1",                 # github_api logs the gh command, never executes it
        "GITHUB_OUTPUT": "github_output",      # run_triage appends route=... here (cwd-relative)
    })
    if use_real:
        os.environ["GITHUB_TOKEN"] = pat
        os.environ["GH_TOKEN"] = pat
        llm.MODEL = model                      # call_model reads this module global at call time
    else:
        os.environ.setdefault("GITHUB_TOKEN", "dummy-not-used")
        os.environ.setdefault("GH_TOKEN", "dummy-not-used")
    # Make run_command's `pytest`/`python` resolve to the venv interpreter.
    os.environ["PATH"] = f"{HERE / '.venv' / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"

    os.chdir(SAMPLE)                           # the agent explores from '.'; artifacts land here
    Path("github_output").write_text("")

    label = f"REAL GitHub Models API · model={model}" if use_real else "SCRIPTED (offline)"
    print(f"\n  Model mode: {label}")
    print(f"  Sample repo: {SAMPLE}")
    print("  GitHub writes: DRY-RUN (logged, not executed)")

    # ---- STAGE 1: triage --------------------------------------------------------------------------
    banner("STAGE 1 — TRIAGE   (real loop · real read-only tools · gh dry-run)")
    if not use_real:
        harness.call_model = _scripted_triage()
    run_triage.main()

    if not Path("verdict.json").exists():      # triage hit its failure backstop (no handoff written)
        print("\n  Stage 1 produced no verdict.json — triage hit its failure backstop (see above).")
        print("  The most common cause is the free GitHub Models tier rate-limiting a larger model.")
        print("  It applied 'needs-human-triage' + a fallback comment and set route=none.")
        print("  Try again, or use a friendlier model:  .venv/bin/python local_run.py --model openai/gpt-4o-mini")
        banner("DONE — stopped after Stage 1 backstop (this IS the 'never silent' path working)")
        return

    verdict = json.loads(Path("verdict.json").read_text())
    accepted, rejected = validate_labels(verdict.get("labels", []))
    print("\n  ── handoff artifact: verdict.json ───────────────────────────────")
    print("   " + json.dumps(verdict, indent=2).replace("\n", "\n   "))
    print(f"\n  proposed labels {verdict.get('labels')}  ->  allow-list accepted {accepted} (+ 'triaged')"
          + (f", dropped {rejected}" if rejected else ""))
    print(f"  route output: {Path('github_output').read_text().strip() or '(none)'}  "
          f"->  the gate the worker job keys off.")

    # ---- STAGE 2: worker --------------------------------------------------------------------------
    banner("STAGE 2 — WORKER   (route -> persona · fix-it-man gains the real run_command tool)")
    if not use_real:
        harness.call_model = _scripted_worker()
    run_worker.main()

    banner("DONE")
    print("  End to end, you just saw:")
    print("   • the agent loop re-sending full history each step (stateless model, stateful harness)")
    print("   • real tools: list_files / read_file / grep, then run_command actually running pytest")
    print("   • schema validation gating the verdict, and the label allow-list filtering")
    print("   • the Stage-1 -> Stage-2 handoff via verdict.json + the route gate")
    print("   • every GitHub write shown as the exact `gh` command (dry-run), nothing mutated")
    print(f"\n  Artifacts in {SAMPLE}/ : verdict.json, github_output")


if __name__ == "__main__":
    main()
