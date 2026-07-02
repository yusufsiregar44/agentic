import json
import pytest
from triage import llm


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status; self._payload = payload or {}
    def json(self): return self._payload
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


def test_call_model_returns_json(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    captured = {}
    def fake_post(url, headers, json, timeout):
        captured["url"] = url; captured["headers"] = headers; captured["body"] = json
        return _Resp(200, {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(llm.requests, "post", fake_post)
    out = llm.call_model([{"role": "user", "content": "hi"}], [])
    assert out["choices"][0]["message"]["content"] == "ok"
    assert captured["url"] == llm.API_URL
    assert captured["headers"]["Authorization"] == "Bearer t"
    assert captured["headers"]["X-GitHub-Api-Version"] == llm.API_VERSION


def test_call_model_retries_on_429(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = {"n": 0}
    def fake_post(url, headers, json, timeout):
        calls["n"] += 1
        return _Resp(429) if calls["n"] < 3 else _Resp(200, {"choices": []})
    monkeypatch.setattr(llm.requests, "post", fake_post)
    out = llm.call_model([], [])
    assert calls["n"] == 3 and out == {"choices": []}


def test_call_model_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm.requests, "post", lambda **k: _Resp(429))
    with pytest.raises(RuntimeError):
        llm.call_model([], [], max_retries=2)
