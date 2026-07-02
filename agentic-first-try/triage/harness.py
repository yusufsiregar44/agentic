"""The hand-rolled agent loop. Stateless model, stateful harness: full history re-sent each step.

What: run_agent() drives a tool-calling loop — build messages, call LLM, execute tools, repeat
      until the model calls finish() or max_steps is exceeded.
Why: keeping the loop explicit (rather than using an agent framework) makes the protocol visible
     and auditable — every step is a readable list of messages.
Fit: Stage 1 (run_triage) and Stage 2 (run_worker) both call run_agent() with different system
     prompts and tool registries; the loop itself is persona-agnostic.
Design: parse_tool_calls() is isolated so swapping the tool-call protocol (e.g. native
        tool_calls → prompted-JSON) requires touching exactly ONE function, not the loop.
"""
import json
import logging
from triage.llm import call_model

log = logging.getLogger(__name__)


def parse_tool_calls(response):
    """Isolated tool-call extraction. Swap THIS one function to change the tool protocol
    (e.g. native tool_calls -> prompted-JSON) without touching the loop."""
    message = response["choices"][0]["message"]
    return message.get("tool_calls") or []


def dispatch(name, raw_args, registry):
    """Returns (result_str, is_finish, finish_payload). Every branch is recoverable."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as e:
        return f"Error: arguments were not valid JSON: {e}", False, None
    if name == "finish":
        return "", True, args
    if name not in registry:
        return f"Error: no tool named {name!r}. Available: {sorted(registry)}", False, None
    try:
        return str(registry[name](**args)), False, None
    except Exception as e:                      # defensive: report, let the model adapt
        return f"Error running {name}: {e}", False, None


def run_agent(system_prompt, user_prompt, tools, registry, *, max_steps=12):
    # Logging is silent unless a handler is configured (off in CI/tests, on in local_run.py),
    # so these calls narrate the loop locally at zero cost in production.
    log.info("run_agent start: %d tool(s) available, max_steps=%d", len(tools), max_steps)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    for step in range(1, max_steps + 1):
        response = call_model(messages, tools)            # re-sends FULL history every step
        message = response["choices"][0]["message"]
        messages.append(message)
        calls = parse_tool_calls(response)
        if not calls:
            log.info("step %d: model returned no tool call — nudging it to use one", step)
            messages.append({"role": "user",
                             "content": "Use a tool, or call finish with your result."})
            continue
        log.info("step %d: model requested %s", step, [c["function"]["name"] for c in calls])
        for call in calls:
            fn = call["function"]
            result, is_finish, payload = dispatch(fn["name"], fn.get("arguments"), registry)
            if is_finish:
                log.info("step %d: finish() called — returning payload (keys=%s)",
                         step, sorted(payload) if isinstance(payload, dict) else type(payload).__name__)
                return payload
            log.info("step %d:   %s(%s) -> %s", step, fn["name"],
                     (fn.get("arguments") or "")[:120], _preview(result))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    raise RuntimeError(f"Agent exceeded max_steps ({max_steps}) without calling finish")


def _preview(text, limit=160):
    """One-line, length-bounded preview of a tool result for readable logs."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + " …"
