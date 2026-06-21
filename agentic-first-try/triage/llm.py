"""GitHub Models client — the only thing that talks to the LLM.

What: call_model(messages, tools) POSTs an OpenAI-compatible chat request, returns parsed JSON.
Why: a thin, visible raw-HTTP client (no SDK) so the tool-call protocol stays explicit and
     swappable; the full request/response cycle is readable in one screen.
Fit: the harness loop calls this once per step; auth is the workflow's built-in GITHUB_TOKEN,
     meaning zero external secrets are needed.
Design: retries on HTTP 429 with exponential backoff; every other non-2xx raises immediately.
"""
import logging
import os
import time
import requests

log = logging.getLogger(__name__)

API_URL = "https://models.github.ai/inference/chat/completions"
API_VERSION = "2026-03-10"
# Swappable knob. Confirm exact catalog id at build (publisher/name). DeepSeek-V3 class (NOT R1).
MODEL = os.environ.get("TRIAGE_MODEL", "deepseek/DeepSeek-V3-0324")


def _log_response(data):
    """Narrate what the model decided this turn (tool_calls or content). Defensive: never raises."""
    try:
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls")
        if calls:
            log.info("← model: tool_calls=%s", [c["function"]["name"] for c in calls])
        else:
            content = " ".join((msg.get("content") or "").split())
            log.info("← model: content=%r", content[:160])
    except (KeyError, IndexError, TypeError):
        log.info("← model: (no choices in response)")


def call_model(messages, tools, *, max_retries=4, timeout=60):
    token = os.environ["GITHUB_TOKEN"]
    headers = {
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
    }
    body = {"model": MODEL, "messages": messages, "tools": tools, "tool_choice": "auto"}
    log.info("→ POST %s  model=%s  msgs=%d  tools=%d", API_URL, MODEL, len(messages), len(tools))
    backoff = 2
    for attempt in range(max_retries):
        resp = requests.post(url=API_URL, headers=headers, json=body, timeout=timeout)
        if resp.status_code == 429:          # rate-limited — back off and retry
            log.info("429 rate-limited — backing off %ds (attempt %d/%d)", backoff, attempt + 1, max_retries)
            time.sleep(backoff); backoff *= 2
            continue
        resp.raise_for_status()
        data = resp.json()
        _log_response(data)
        return data
    raise RuntimeError("GitHub Models rate limit: retries exhausted")
