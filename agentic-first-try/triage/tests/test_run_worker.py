import json
from pathlib import Path
from triage import run_worker


def _setup(monkeypatch, tmp_path, route):
    monkeypatch.setenv("REPO", "o/r"); monkeypatch.setenv("ISSUE_NUMBER", "7")
    monkeypatch.setenv("ISSUE_TITLE", "t"); monkeypatch.setenv("ISSUE_BODY", "b")
    monkeypatch.chdir(tmp_path)
    Path("verdict.json").write_text(json.dumps(
        {"route": route, "suspected_area": "x.py", "findings": "f", "issue": "7"}))


def test_bug_route_uses_fixit_and_comments(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, "bug")
    seen = {}
    monkeypatch.setattr(run_worker, "run_agent",
                        lambda system_prompt, **k: seen.update({"sys": system_prompt}) or {"comment": "RCA here"})
    posted = {}
    monkeypatch.setattr(run_worker, "post_comment", lambda r, i, b: posted.setdefault("body", b))
    run_worker.main()
    assert "fix-it man" in seen["sys"].lower() or "rca" in seen["sys"].lower()
    assert posted["body"] == "RCA here"


def test_failure_backstop_comments(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, "enhancement")
    monkeypatch.setattr(run_worker, "run_agent",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("down")))
    posted = {}
    monkeypatch.setattr(run_worker, "post_comment", lambda r, i, b: posted.setdefault("body", b))
    run_worker.main()
    assert "couldn't complete" in posted["body"].lower()
