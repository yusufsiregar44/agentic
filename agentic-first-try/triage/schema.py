"""Validation for the Stage-1 verdict (the Stage-1 → Stage-2 handoff contract).

What: validate_verdict() checks a dict against the required fields and enum values.
Why: the model can return malformed JSON; schema validation catches that before it propagates.
Fit: Stage 1 (run_triage) validates the agent's finish payload here before writing verdict.json.
Design: plain if-chain over a dict — no third-party schema library needed for this small contract.
"""

VALID_TYPES = {"bug", "enhancement", "question", "documentation", "duplicate", "invalid"}
VALID_SEVERITY = {"critical", "high", "medium", "low"}
VALID_ROUTES = {"bug", "enhancement", "none"}


def validate_verdict(v):
    errors = []
    if not isinstance(v, dict):
        return ["verdict is not a JSON object"]
    if v.get("type") not in VALID_TYPES:
        errors.append(f"invalid type: {v.get('type')!r}")
    if v.get("severity") not in VALID_SEVERITY:
        errors.append(f"invalid severity: {v.get('severity')!r}")
    if v.get("route") not in VALID_ROUTES:
        errors.append(f"invalid route: {v.get('route')!r}")
    comment = v.get("comment")
    if not isinstance(comment, str) or not comment.strip():
        errors.append("missing or empty comment")
    if not isinstance(v.get("labels"), list):
        errors.append("labels must be a list")
    return errors
