import pytest
from triage import harness


def _msg(tool_calls=None, content=None):
    return {"choices": [{"message": {"content": content, "tool_calls": tool_calls}}]}


def _call(cid, name, args_json):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args_json}}


def test_loop_reads_then_finishes(monkeypatch):
    # Scripted "model": step 1 → read_file; step 2 → finish.
    scripted = [
        _msg(tool_calls=[_call("c1", "read_file", '{"path": "x.py"}')]),
        _msg(tool_calls=[_call("c2", "finish", '{"verdict": 42}')]),
    ]
    monkeypatch.setattr(harness, "call_model", lambda m, t: scripted.pop(0))
    reads = {}
    registry = {"read_file": lambda path: reads.setdefault("path", path) or "FILE BODY"}
    out = harness.run_agent("sys", "user", tools=[], registry=registry, max_steps=5)
    assert out == {"verdict": 42}
    assert reads["path"] == "x.py"


def test_unknown_tool_is_recoverable(monkeypatch):
    scripted = [
        _msg(tool_calls=[_call("c1", "nope", "{}")]),
        _msg(tool_calls=[_call("c2", "finish", '{"ok": true}')]),
    ]
    monkeypatch.setattr(harness, "call_model", lambda m, t: scripted.pop(0))
    out = harness.run_agent("sys", "user", tools=[], registry={}, max_steps=5)
    assert out == {"ok": True}  # did not crash on the bad tool name


def test_exceeding_max_steps_raises(monkeypatch):
    monkeypatch.setattr(harness, "call_model",
                        lambda m, t: _msg(tool_calls=[_call("c", "read_file", '{"path":"x"}')]))
    with pytest.raises(RuntimeError):
        harness.run_agent("sys", "user", tools=[], registry={"read_file": lambda path: "x"}, max_steps=3)
