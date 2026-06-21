import json
from triage import github_api


class _Proc:
    def __init__(self, stdout="", code=0): self.stdout = stdout; self.returncode = code


def test_add_labels_builds_gh_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(github_api.subprocess, "run",
                        lambda args, **k: seen.setdefault("args", args) or _Proc())
    github_api.add_labels("o/r", 7, ["bug", "severity:high"])
    assert seen["args"][:5] == ["gh", "issue", "edit", "7", "--repo"]
    assert "--add-label" in seen["args"] and "bug" in seen["args"]


def test_add_labels_noop_when_empty(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(github_api.subprocess, "run", lambda *a, **k: called.__setitem__("n", 1))
    github_api.add_labels("o/r", 7, [])
    assert called["n"] == 0


def test_has_label_parses_json(monkeypatch):
    payload = json.dumps({"labels": [{"name": "triaged"}, {"name": "bug"}]})
    monkeypatch.setattr(github_api.subprocess, "run", lambda args, **k: _Proc(stdout=payload))
    assert github_api.has_label("o/r", 7, "triaged") is True
    assert github_api.has_label("o/r", 7, "nope") is False
