import os
from triage import tools


def test_read_file_truncates(tmp_path):
    p = tmp_path / "big.txt"; p.write_text("x" * (tools.MAX_OUTPUT + 100))
    out = tools.read_file(str(p))
    assert len(out) == tools.MAX_OUTPUT


def test_list_files_skips_hidden(tmp_path):
    (tmp_path / "a.py").write_text("a")
    hidden = tmp_path / ".git"; hidden.mkdir(); (hidden / "config").write_text("x")
    out = tools.list_files(str(tmp_path))
    assert "a.py" in out
    assert ".git" not in out


def test_grep_finds_line(tmp_path):
    (tmp_path / "m.py").write_text("def login():\n    return check(pw)\n")
    out = tools.grep("login", str(tmp_path))
    assert "m.py:1" in out and "def login" in out


def test_readonly_registry_has_no_run_command():
    assert "run_command" not in tools.READONLY_REGISTRY


def test_run_command_captures_output():
    out = tools.run_command("echo hello-rca")
    assert "hello-rca" in out


def test_run_command_times_out():
    out = tools.run_command("sleep 5", timeout=1)
    assert "timed out" in out.lower()


def test_fixit_registry_includes_run_command():
    assert "run_command" in tools.FIXIT_REGISTRY
    assert "read_file" in tools.FIXIT_REGISTRY
