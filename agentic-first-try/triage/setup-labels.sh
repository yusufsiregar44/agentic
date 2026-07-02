#!/usr/bin/env bash
# One-time (idempotent) creation of the triage label allow-list. Run locally once:
#   REPO=yusufsiregar44/agentic bash triage/setup-labels.sh
set -euo pipefail
REPO="${REPO:?set REPO=owner/name}"

create() { gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force; }

create "severity:critical" "b60205" "Data loss, security, or total breakage"
create "severity:high"     "d93f0b" "Major feature broken, no workaround"
create "severity:medium"   "fbca04" "Broken but has a workaround"
create "severity:low"      "0e8a16" "Minor or cosmetic"
create "regression"        "5319e7" "Previously worked, now broken"
create "triaged"           "0052cc" "Auto-triage completed"
create "needs-human-triage" "e11d21" "Auto-triage could not complete"
echo "labels ensured on $REPO"
