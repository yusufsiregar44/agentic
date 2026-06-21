# Agentic Issue-Triage Agent — Overview

> A learning-oriented walkthrough. Read this top-to-bottom to understand **what** we built, **why** it's shaped this way, and **how** each file plays its part. Smart-brevity: bold lead, then the detail.

## The big idea

**When a GitHub issue opens, an ephemeral agent reads the repo, classifies the issue, labels it, comments — then hands off to an advisory expert.** No servers, no databases, no external secrets. A GitHub Actions runner spins up, does the work, and disappears. The only credential is the workflow's built-in `GITHUB_TOKEN`.

The agent is **hand-rolled** — no LangChain, no agent framework. That's deliberate: the whole point is to *see* the loop. The LLM is stateless; our Python harness owns all state and re-sends the full conversation every step. If you understand this repo, you understand what every agent framework is doing under the hood.

## The two-stage pipeline

```
issue opened
   │
   ▼
┌─────────────────────────────────────────────┐
│ STAGE 1 — triage  (always; author-gated)     │
│ persona: triage.md                            │
│ tools: read-only (read_file, list_files, grep)│
│ → classify (type, severity) + decide route    │
│ → apply allow-listed labels + post comment    │
│ → emit verdict.json, set `route` output        │
└─────────────────────────────────────────────┘
   │  route = bug | enhancement | none
   ▼  (verdict.json passed as a build artifact)
┌─────────────────────────────────────────────┐
│ STAGE 2 — worker  (only if route ≠ none)      │
│ route=bug         → fix-it-man.md  (+run_command)
│ route=enhancement → stoic-developer.md (read-only)
│ → deep-dive using the distilled Stage-1 facts │
│ → post an RCA (bug) or implementation plan     │
└─────────────────────────────────────────────┘
```

**Why two stages?** Separation of concerns + cost control. Triage is cheap and runs on every issue. The expensive deep-dive only runs when triage decides it's worth it. Each stage is a *fresh* agent with a *distilled* handoff (`verdict.json`) — Stage 2 never inherits Stage 1's raw context, it gets the facts that matter. That's the same context-hygiene principle that makes multi-agent systems work.

## The core loop (the part worth understanding)

The model can't *do* anything — it can only emit text. We give it **tools** (JSON schemas) and parse its `tool_calls` ourselves:

1. Send `[system, user]` to the model.
2. Model replies with one or more `tool_calls` (e.g. `read_file("login.py")`).
3. Harness runs the tool, appends the result as a `tool` message.
4. **Re-send the entire history.** The model "remembers" only because we replay everything.
5. Repeat until the model calls `finish` (its structured exit) or we hit `max_steps`.

`parse_tool_calls()` is deliberately isolated: swap that one function to change the tool protocol (native `tool_calls` ↔ prompted-JSON) without touching the loop. Every dispatch branch is recoverable — a bad tool name or bad JSON becomes a message back to the model, not a crash.

## File map — what each piece does

| File | Step | Responsibility |
|------|------|----------------|
| `triage/labels.py` | US-001 | The fixed label vocabulary. The agent applies *from* this set; it never creates labels. |
| `triage/schema.py` | US-002 | Validates the Stage-1 → Stage-2 handoff contract (`verdict.json`). |
| `triage/tools.py` | US-003/004 | The tools an agent can call. **The registry you hand a persona = its blast radius.** Read-only for triage; `run_command` added only for fix-it-man. |
| `triage/llm.py` | US-005 | Thin raw-HTTP client for GitHub Models. Kept visible on purpose; handles 429 backoff. |
| `triage/harness.py` | US-006 | The agent loop. Stateless model, stateful harness. |
| `triage/github_api.py` | US-007 | Write side: comments + labels via the `gh` CLI. |
| `triage/personas/*.md` | US-008 | Model-agnostic system prompts with hard output contracts. Behaviour lives in prompts, not code. |
| `triage/run_triage.py` | US-009 | Stage-1 entrypoint. Idempotent (skips if already `triaged`); never silent on failure. |
| `triage/run_worker.py` | US-010 | Stage-2 entrypoint. Route → persona → tools. |
| `triage/setup-labels.sh` | US-011 | One-time idempotent label pre-creation. |
| `.github/workflows/issue-triage.yml` | US-012 | Wires it together: triggers, author gate, route gate, least-privilege permissions, artifact handoff. |

## Design principles you'll see repeated

- **Least privilege everywhere.** Permissions are `models:read, issues:write, contents:read`. Tools are scoped per persona. The label set is a closed allow-list.
- **Never silent.** Any failure → a fallback comment + `needs-human-triage` label. The maintainer always learns something happened.
- **Model-agnostic prompts.** Explicit structure, hard output schemas, no model-specific tricks — so the `TRIAGE_MODEL` env var is a real swappable knob.
- **Stateless model, stateful harness.** All durable state lives in our Python, never in the model.

## Running the tests

```bash
# from this directory (agentic-first-try/), with the local venv:
.venv/bin/python -m pytest triage/tests -v
```

## Status / scope

This is **v1: read-only and advisory.** Stage 2 *describes* fixes and plans; it never writes code or opens PRs. The one execution capability (`run_command`) is timeout-bounded and gated behind author-association. See the bottom of this doc (and the per-file headers) for the v1.1 hardening notes. The live end-to-end battery (US-013) is documented as a runbook — it requires pushing to a real repo with GitHub Models access, which can't run inside this build.
