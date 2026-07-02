"""Label vocabulary — the closed set the agent is allowed to apply.

What: ALLOWED + validate_labels() split proposed labels into (accepted, rejected).
Why: triage must never INVENT labels; an allow-list makes that structurally impossible.
Fit: Stage 1 (run_triage) filters the model's proposed labels through this before applying.
Design: a plain set — the cheapest possible guardrail, no config, no I/O.
"""

SEVERITY = {"severity:critical", "severity:high", "severity:medium", "severity:low"}
TYPES = {"bug", "enhancement", "question", "documentation", "duplicate", "regression"}
STATUS = {"triaged", "needs-human-triage"}

ALLOWED = SEVERITY | TYPES | STATUS


def validate_labels(labels):
    """Split proposed labels into (accepted, rejected). Off-list labels are dropped, never created."""
    accepted, rejected = [], []
    for label in labels:
        (accepted if label in ALLOWED else rejected).append(label)
    return accepted, rejected
