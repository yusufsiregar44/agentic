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
.venv/bin/python -m pytest triage/tests -v          # 31 passed
```

## See it run locally, end to end

The fastest way to understand the flow is to watch it execute. `local_run.py` runs **both stages for real** against a tiny sample repo with a planted bug — narrated step by step:

```bash
.venv/bin/python local_run.py
```

**Only the model is faked** (a `ScriptedModel` returns a fixed sequence of tool-calls — that's the one thing that would otherwise hit the network). Everything else is the real code path: the agent loop, the real `read_file`/`grep`/`run_command` tools (it actually runs `pytest` on the planted bug and sees the `KeyError`), schema validation, the label allow-list (watch it drop an off-list `wontfix` label), the `verdict.json` handoff, and the route gate. GitHub writes run in **dry-run mode** (`TRIAGE_DRY_RUN=1`): `github_api` builds the real `gh` command and **logs** it instead of executing, so nothing touches a live repo.

What the trace shows you, in order:
1. **Idempotency check** — `gh issue view ... --json labels` (dry-run); not yet triaged, so proceed.
2. **Stage-1 loop** — `list_files → read_file → grep → finish`, with each step logging the model's request (full history re-sent) and the tool result.
3. **Label filtering + writes** — the dry-run `gh issue edit` applies only allow-listed labels (`bug`, `severity:high`, `triaged`); `wontfix` is dropped. A `gh issue comment` posts the triage note. `route=bug` is written to `GITHUB_OUTPUT`.
4. **Stage-2 loop** — route `bug` selects fix-it-man (with `run_command`), which reads the file, **runs the tests for real**, and posts an RCA.

This maps 1:1 onto what the GitHub Actions workflow does — the workflow just supplies real env vars, a real model, and a real `gh`. Artifacts land in the gitignored `.local-demo/` so you can inspect `verdict.json` and the sample repo afterward.

## Build status

**All 12 implementation tasks built and unit-tested — 30 tests green; the package byte-compiles cleanly.** Built TDD-style (red → green → commit) with one commit per task; the Ralph `prd.json` tracks each story (`passes: true`) and `progress.txt` is the run log. The live end-to-end battery (US-013) can't run inside this build (it needs a real repo + GitHub Models access) — it's captured as **[RUNBOOK.md](RUNBOOK.md)**.

### How to deploy

GitHub Actions only auto-triggers from `.github/` at the **repository root**, and the workflow runs `python -m triage.run_triage` (so `triage/` must be importable from the checkout root). This project lives under `agentic-first-try/` as a self-contained learning artifact. To actually run it, relocate `triage/` and `.github/` to the repo root — see **[RUNBOOK.md](RUNBOOK.md) §0**.

## Deviations from the plan (and why)

Two intentional changes were made to the plan's literal code; both are documented in-file and in `progress.txt`:

1. **Module-relative `load_persona` (`run_triage.py`, `run_worker.py`).** The plan loaded personas from a CWD-relative path (`triage/personas/{name}.md`). That's a latent bug: the plan's own entrypoint tests `chdir` into a temp dir, and `load_persona()` is evaluated for real to build the (mocked) `run_agent` argument — so the path wouldn't resolve and the happy-path tests would fail. Fix: resolve relative to the module file (`Path(__file__).resolve().parent / "personas"`), which also makes the CI runner robust to its working directory.
2. **Worker test return value (`test_run_worker.py`).** The plan's mock used `dict.setdefault(...) or {...}`; `setdefault` returns the stored (truthy) persona string, so `or` short-circuited and the mock returned the string instead of the intended `{"comment": ...}` dict — the test would `TypeError`. Fix: `dict.update(...) or {...}` (`update` returns `None`, so `or` reaches the dict). Same intent, correct behavior.

## Status / scope

This is **v1: read-only and advisory.** Stage 2 *describes* fixes and plans; it never writes code or opens PRs. The one execution capability (`run_command`) is timeout-bounded and gated behind author-association. v1.1 notes (carried from the plan): a code-writing stoic-developer behind a draft-PR + human-review gate; untrusted-input hardening to open triage to outside contributors; real sandboxing for `run_command`; severity-based worker gating and `area:*` routing labels.
