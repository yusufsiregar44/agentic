"""
**Stage 1 — Triage.** Always runs (after the workflow's author gate).

What this stage does: Classifies a GitHub issue (type, severity, route) by running a
  read-only agent loop against the repository, then applies labels and posts a triage comment.

When it runs: Every time an issue is opened/reopened and the author passes the association gate.
  The idempotency guard (has_label "triaged") makes re-runs safe.

Side effects: Applies labels to the issue (including "triaged"), posts one comment, writes
  verdict.json (Stage-1 → Stage-2 handoff artifact), and appends route=<value> to GITHUB_OUTPUT.

Key design choice — idempotency: if "triaged" is already present, the agent is never invoked
  and route=none is emitted so the worker job is skipped. This prevents duplicate triage on
  workflow re-runs.

load_persona deviation: resolved relative to THIS module (not CWD) — see _PERSONA_DIR below.
"""
import json
import os
from pathlib import Path

from triage.harness import run_agent
from triage.schema import validate_verdict
from triage.labels import validate_labels
from triage.tools import READONLY_SCHEMAS, READONLY_REGISTRY, finish_schema
from triage.github_api import post_comment, add_labels, has_label

FALLBACK = "⚠️ Automated triage couldn't complete — flagging for human review."
TRIAGE_FINISH = finish_schema({
    "type": {"type": "string"}, "severity": {"type": "string"},
    "is_duplicate": {"type": "object"}, "suspected_area": {"type": "string"},
    "route": {"type": "string"}, "findings": {"type": "string"},
    "comment": {"type": "string"}, "labels": {"type": "array", "items": {"type": "string"}},
})

# Module-relative persona dir — works regardless of CWD (CI runner, tests, local)
_PERSONA_DIR = Path(__file__).resolve().parent / "personas"


def set_output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{name}={value}\n")


def load_persona(name):
    """Load a persona prompt by name. Resolved relative to THIS module (not CWD) so it
    works no matter where the process is launched from (CI runner, tests, etc.)."""
    return (_PERSONA_DIR / f"{name}.md").read_text()


def main():
    repo = os.environ["REPO"]
    issue = os.environ["ISSUE_NUMBER"]
    title = os.environ.get("ISSUE_TITLE", "")
    body = os.environ.get("ISSUE_BODY", "")

    if has_label(repo, issue, "triaged"):       # idempotency
        print("already triaged; skipping")
        set_output("route", "none")
        return

    try:
        verdict = run_agent(
            system_prompt=load_persona("triage"),
            user_prompt=f"#{issue} {title}\n\n{body}",
            tools=READONLY_SCHEMAS + [TRIAGE_FINISH],
            registry=READONLY_REGISTRY,
        )
        errors = validate_verdict(verdict)
        if errors:
            raise ValueError(f"invalid verdict: {errors}")

        accepted, _rejected = validate_labels(verdict["labels"])
        add_labels(repo, issue, accepted + ["triaged"])
        post_comment(repo, issue, verdict["comment"])

        verdict["issue"] = issue
        Path("verdict.json").write_text(json.dumps(verdict))
        set_output("route", verdict["route"])
        print(f"triaged #{issue}: type={verdict['type']} route={verdict['route']}")
    except Exception as e:                        # never silent
        print(f"triage failed: {e}")
        add_labels(repo, issue, ["needs-human-triage"])
        post_comment(repo, issue, FALLBACK)
        set_output("route", "none")


if __name__ == "__main__":
    main()
