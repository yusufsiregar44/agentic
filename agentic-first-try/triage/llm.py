"""GitHub Models client — the only thing that talks to the LLM.

What: call_model(messages, tools) POSTs an OpenAI-compatible chat request, returns parsed JSON.
Why: a thin, visible raw-HTTP client (no SDK) so the tool-call protocol stays explicit and
     swappable; the full request/response cycle is readable in one screen.
Fit: the harness loop calls this once per step; auth is the workflow's built-in GITHUB_TOKEN,
     meaning zero external secrets are needed.
Design: retries on HTTP 429 with exponential backoff; every other non-2xx raises immediately.
"""
import os
import time
import requests

API_URL = "https://models.github.ai/inference/chat/completions"
API_VERSION = "2026-03-10"
# Swappable knob. Confirm exact catalog id at build (publisher/name). DeepSeek-V3 class (NOT R1).
MODEL = os.environ.get("TRIAGE_MODEL", "deepseek/DeepSeek-V3-0324")


def call_model(messages, tools, *, max_retries=4, timeout=60):
    token = os.environ["GITHUB_TOKEN"]
    headers = {
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
    }
    body = {"model": MODEL, "messages": messages, "tools": tools, "tool_choice": "auto"}
    backoff = 2
    for attempt in range(max_retries):
        resp = requests.post(url=API_URL, headers=headers, json=body, timeout=timeout)
        if resp.status_code == 429:          # rate-limited — back off and retry
            time.sleep(backoff); backoff *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("GitHub Models rate limit: retries exhausted")
