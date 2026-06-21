# Runbook — Deploy & Verify the Issue-Triage Agent

> Everything in this repo is **built and unit-tested** (30 tests green). The steps below are the
> *live* operations that need a real GitHub repo + GitHub Models access, so they can't run inside
> the build. Do them in order. Smart-brevity: the command, then what to expect.

## 0. Prerequisite — relocate to the repo root (one-time)

This project was built self-contained under `agentic-first-try/` for learning. GitHub Actions only
auto-triggers from `.github/` at the **repository root**, and the workflow runs `python -m triage.run_triage`
(so `triage/` must be importable from the checkout root). To deploy on `yusufsiregar44/agentic`:

```bash
# from the repo root
git mv agentic-first-try/triage triage
git mv agentic-first-try/.github .github   # merges the workflow into the repo-root .github/
```

Then the workflow's `pip install -r triage/requirements.txt` and `python -m triage.run_triage` resolve as-is.

## 1. Confirm the model id (Task 12 §3)

The model is a swappable env knob (`TRIAGE_MODEL`, default `deepseek/DeepSeek-V3-0324`). Confirm the
exact catalog id against the live catalog before the first run:

```bash
gh api -H "X-GitHub-Api-Version: 2026-03-10" /catalog/models --jq '.[].id' 2>/dev/null | grep -i deepseek
```

If the real id differs, set repo **variable** `TRIAGE_MODEL` (Settings → Secrets and variables →
Actions → Variables) and add `TRIAGE_MODEL: ${{ vars.TRIAGE_MODEL }}` to both `env:` blocks. Confirm
the chosen model supports tool-calling.

## 2. Pre-create the labels (Task 11)

```bash
REPO=yusufsiregar44/agentic bash triage/setup-labels.sh
gh label list --repo yusufsiregar44/agentic    # expect the 7 new labels
```

Idempotent — safe to re-run. (`--force` updates existing labels in place.)

## 3. Push and enable

```bash
git push -u origin ralph/agentic-issue-triage   # then open a PR / merge to the default branch
```

The workflow triggers on `issues: [opened, reopened]` once it's on the default branch.

## 4. Eval battery (Task 13) — the acceptance tests

| # | Action | Expected |
|---|--------|----------|
| 1 | `gh issue create --title "read_file crashes on missing file" --body "..."` | `bug` + `severity:*` + `triaged` labels; a **triage comment**; **and** a fix-it-man RCA comment. Both `triage` and `worker` jobs green. |
| 2 | `gh issue create --title "Add a --dry-run flag to setup-labels.sh" --body "..."` | `enhancement` + `severity:*` + `triaged`; triage comment; **and** a stoic-developer implementation-plan comment. |
| 3 | `gh issue create --title "How does the harness handle 429s?" --body "..."` | `question` + `triaged`; triage comment **only**; the `worker` job is **skipped** (route=none). |
| 4 | Re-run the bug issue's workflow (Actions → Re-run all jobs) | Triage logs `already triaged; skipping`; **no duplicate comment**; worker skipped. (Idempotency.) |
| 5 | *(optional)* Set `TRIAGE_MODEL` to a bogus id, file an issue | `needs-human-triage` label + fallback comment appear; **no crash**. Then restore `TRIAGE_MODEL`. (Failure backstop.) |
| 6 | Settings → Secrets and variables → Actions | **No repository secrets** required for the happy path (only the optional `TRIAGE_MODEL` *variable*). (Zero-secrets.) |

## What each check proves

- **#1/#2** — the full two-stage pipeline: classify → route → advisory deep-dive.
- **#3** — the route gate: cheap triage runs always; the expensive worker only when it's worth it.
- **#4** — idempotency: re-runs never double-post.
- **#5** — *never silent*: failures surface as a label + comment, not a silent drop.
- **#6** — the security posture: nothing but the built-in `GITHUB_TOKEN`.
