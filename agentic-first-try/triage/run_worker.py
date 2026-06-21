"""
**Stage 2 — Advisory Worker.** Runs only when Stage 1 routed bug or enhancement.

What this stage does: Loads the Stage-1 verdict from verdict.json, selects an advisory persona
  (fix-it-man for bugs, stoic-developer for enhancements), runs a second agent loop, and posts
  the result as a comment on the issue.

When it runs: Conditionally — the workflow gates this job on Stage 1 emitting route=bug or
  route=enhancement. If Stage 1 routes to "none", this job is skipped entirely.

Side effects: Posts exactly one comment on the issue (or a fallback comment on failure).
  No labels are applied in Stage 2; no new output variables are set.

Key design choice — route→persona dispatch: PERSONA_BY_ROUTE maps each valid route to a
  (persona_name, tool_schemas, tool_registry) triple, so adding a new route (e.g. "security")
  requires one entry and a persona file — no other code changes.

load_persona deviation: resolved relative to THIS module (not CWD) — see _PERSONA_DIR below.
"""
import json
import os
from pathlib import Path

from triage.harness import run_agent
from triage.tools import (READONLY_SCHEMAS, READONLY_REGISTRY,
                          FIXIT_SCHEMAS, FIXIT_REGISTRY, finish_schema)
from triage.github_api import post_comment

FALLBACK = "⚠️ Automated investigation couldn't complete — flagging for human review."
WORKER_FINISH = finish_schema({"comment": {"type": "string"}})

# Module-relative persona dir — works regardless of CWD (CI runner, tests, local)
_PERSONA_DIR = Path(__file__).resolve().parent / "personas"

# route -> (persona file, tool schemas, tool registry)
PERSONA_BY_ROUTE = {
    "bug": ("fix-it-man", FIXIT_SCHEMAS, FIXIT_REGISTRY),
    "enhancement": ("stoic-developer", READONLY_SCHEMAS, READONLY_REGISTRY),
}


def load_persona(name):
    """Load a persona prompt by name. Resolved relative to THIS module (not CWD) so it
    works no matter where the process is launched from (CI runner, tests, etc.)."""
    return (_PERSONA_DIR / f"{name}.md").read_text()


def main():
    repo = os.environ["REPO"]
    issue = os.environ["ISSUE_NUMBER"]
    title = os.environ.get("ISSUE_TITLE", "")
    body = os.environ.get("ISSUE_BODY", "")
    verdict = json.loads(Path("verdict.json").read_text())
    route = verdict.get("route")

    if route not in PERSONA_BY_ROUTE:
        print(f"no worker for route={route}; nothing to do")
        return

    persona_name, schemas, registry = PERSONA_BY_ROUTE[route]
    seed = (f"#{issue} {title}\n\n{body}\n\n"
            f"--- Stage-1 facts (verify, may be wrong) ---\n"
            f"suspected_area: {verdict.get('suspected_area')}\n"
            f"findings: {verdict.get('findings')}")
    try:
        result = run_agent(system_prompt=load_persona(persona_name), user_prompt=seed,
                           tools=schemas + [WORKER_FINISH], registry=registry)
        post_comment(repo, issue, result["comment"])
        print(f"{persona_name} commented on #{issue}")
    except Exception as e:                        # never silent
        print(f"worker failed: {e}")
        post_comment(repo, issue, FALLBACK)


if __name__ == "__main__":
    main()
