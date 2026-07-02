import json
from pathlib import Path
from triage import run_triage


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("REPO", "o/r"); monkeypatch.setenv("ISSUE_NUMBER", "7")
    monkeypatch.setenv("ISSUE_TITLE", "Login breaks"); monkeypatch.setenv("ISSUE_BODY", "boom")
    out = tmp_path / "gh_out"; out.write_text(""); monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.chdir(tmp_path)
    return out


def test_happy_path_labels_comments_and_routes(monkeypatch, tmp_path):
    out = _env(monkeypatch, tmp_path)
    verdict = {"type": "bug", "severity": "high", "route": "bug",
               "is_duplicate": {"likely": False, "of": None}, "suspected_area": "x.py",
               "findings": "f", "comment": "triage!", "labels": ["bug", "BOGUS"]}
    monkeypatch.setattr(run_triage, "has_label", lambda *a: False)
    monkeypatch.setattr(run_triage, "run_agent", lambda *a, **k: verdict)
    applied = {}; commented = {}
    monkeypatch.setattr(run_triage, "add_labels", lambda r, i, ls: applied.setdefault("labels", ls))
    monkeypatch.setattr(run_triage, "post_comment", lambda r, i, b: commented.setdefault("body", b))
    run_triage.main()
    assert "bug" in applied["labels"] and "triaged" in applied["labels"]
    assert "BOGUS" not in applied["labels"]           # off-list dropped
    assert commented["body"] == "triage!"
    assert "route=bug" in out.read_text()
    assert json.loads(Path("verdict.json").read_text())["route"] == "bug"


def test_already_triaged_is_noop(monkeypatch, tmp_path):
    out = _env(monkeypatch, tmp_path)
    monkeypatch.setattr(run_triage, "has_label", lambda *a: True)
    monkeypatch.setattr(run_triage, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")))
    run_triage.main()
    assert "route=none" in out.read_text()


def test_failure_backstop(monkeypatch, tmp_path):
    out = _env(monkeypatch, tmp_path)
    monkeypatch.setattr(run_triage, "has_label", lambda *a: False)
    monkeypatch.setattr(run_triage, "run_agent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model down")))
    applied = {}; commented = {}
    monkeypatch.setattr(run_triage, "add_labels", lambda r, i, ls: applied.setdefault("labels", ls))
    monkeypatch.setattr(run_triage, "post_comment", lambda r, i, b: commented.setdefault("body", b))
    run_triage.main()
    assert "needs-human-triage" in applied["labels"]
    assert "couldn't complete" in commented["body"].lower()
    assert "route=none" in out.read_text()
