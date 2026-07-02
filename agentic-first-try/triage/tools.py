"""Agent tools — filesystem read access plus the run_command escape hatch.

What: read_file/list_files/grep + optional run_command; registries and OpenAI-format schemas.
Why: the registry given to a persona defines its blast radius — read-only for triage/enhancement,
     plus run_command for fix-it-man so it can execute tests during RCA.
Fit: Stage 1 uses READONLY_REGISTRY; Stage 2 bug path uses FIXIT_REGISTRY (includes run_command).
Design: tool schemas follow OpenAI function-calling format so they drop straight into the API body.
"""
import os
import re

MAX_OUTPUT = 5000


def read_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()[:MAX_OUTPUT]


def list_files(directory="."):
    entries = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]  # skip hidden (.git, etc.)
        for name in files:
            entries.append(os.path.join(root, name))
            if len(entries) >= 200:
                return "\n".join(entries) + "\n... (truncated)"
    return "\n".join(entries) or "(empty)"


def grep(pattern, directory="."):
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"
    matches = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            p = os.path.join(root, name)
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append(f"{p}:{i}: {line.strip()}")
                            if len(matches) >= 100:
                                return "\n".join(matches) + "\n... (truncated)"
            except OSError:
                continue
    return "\n".join(matches) or "(no matches)"


def _schema(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


def finish_schema(properties):
    """The 'finish' tool — how a persona returns its structured result. Properties differ per stage."""
    return _schema("finish", "Emit your final structured result and end the task.",
                   properties, list(properties.keys()))


READONLY_SCHEMAS = [
    _schema("read_file", "Read a UTF-8 file from the repo (truncated).",
            {"path": {"type": "string"}}, ["path"]),
    _schema("list_files", "List files under a directory (hidden dirs skipped).",
            {"directory": {"type": "string"}}, []),
    _schema("grep", "Search file contents by regex; returns path:line: text.",
            {"pattern": {"type": "string"}, "directory": {"type": "string"}}, ["pattern"]),
]

READONLY_REGISTRY = {"read_file": read_file, "list_files": list_files, "grep": grep}


import subprocess


def run_command(command, timeout=30):
    """Run a shell command (read-only investigation, e.g. tests). Captures output, enforces a timeout.
    NOTE: not a true sandbox — v1 relies on author-gating. Hardened in v1.1."""
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    output = (proc.stdout + proc.stderr)[:MAX_OUTPUT]
    return f"exit={proc.returncode}\n{output}"


FIXIT_SCHEMAS = READONLY_SCHEMAS + [
    _schema("run_command", "Run a shell command (e.g. run tests) to investigate. Output is captured.",
            {"command": {"type": "string"}}, ["command"]),
]

FIXIT_REGISTRY = {**READONLY_REGISTRY, "run_command": run_command}
