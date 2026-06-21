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
from triage.llm import call_model


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
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    for _ in range(max_steps):
        response = call_model(messages, tools)
        message = response["choices"][0]["message"]
        messages.append(message)
        calls = parse_tool_calls(response)
        if not calls:
            messages.append({"role": "user",
                             "content": "Use a tool, or call finish with your result."})
            continue
        for call in calls:
            fn = call["function"]
            result, is_finish, payload = dispatch(fn["name"], fn.get("arguments"), registry)
            if is_finish:
                return payload
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    raise RuntimeError(f"Agent exceeded max_steps ({max_steps}) without calling finish")
