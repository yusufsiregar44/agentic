"""Write-side helpers via the gh CLI (pre-installed on runners; auth via GH_TOKEN env).

What: post_comment(), add_labels(), has_label() — the three write operations the triage pipeline
      needs to interact with GitHub Issues.
Why: the gh CLI handles auth (GH_TOKEN), retry, and API versioning — no raw HTTP needed here;
     subprocess calls are concise and auditable.
Fit: run_triage.py calls all three; run_worker.py calls post_comment. Both stages stay read-only
     with respect to the repository — only issue metadata is mutated.
Design: _gh() centralises the subprocess invocation so the three public functions stay DRY and
        testable (monkeypatch subprocess.run, not shell commands).
Dry-run: set TRIAGE_DRY_RUN=1 and _gh() builds the REAL gh argv but LOGS it instead of executing
         — lets you run the whole pipeline locally (see local_run.py) without mutating a repo.
"""
import json
import logging
import os
import subprocess

log = logging.getLogger(__name__)


def _gh(args):
    """Run a gh subcommand. In TRIAGE_DRY_RUN mode, log the exact command and skip execution
    (returning an empty success) so no live GitHub state is touched."""
    if os.environ.get("TRIAGE_DRY_RUN"):
        log.info("[dry-run] would run: gh %s", " ".join(args))
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True)


def post_comment(repo, issue, body):
    _gh(["issue", "comment", str(issue), "--repo", repo, "--body", body])


def add_labels(repo, issue, labels):
    if not labels:
        return
    args = ["issue", "edit", str(issue), "--repo", repo]
    for label in labels:
        args += ["--add-label", label]
    _gh(args)


def has_label(repo, issue, label):
    proc = _gh(["issue", "view", str(issue), "--repo", repo, "--json", "labels"])
    data = json.loads(proc.stdout or '{"labels": []}')
    return any(l["name"] == label for l in data.get("labels", []))
