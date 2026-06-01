#!/usr/bin/env bash
# EDD release gate: one EvalHub job -> one verdict -> one exit code.
#
#   exit 0  PROMOTE  (results.test.pass == true)   -> CI lets the release through
#   exit 1  BLOCKED  (results.test.pass == false)  -> CI stops the release
#   exit 2  harness error (could not produce a verdict at all)
#
# Usage:
#   ./release-gate.sh                      # GATE_MODE=auto (default)
#   ./release-gate.sh --offline            # force ./specs fixtures, zero network
#   ./release-gate.sh --mode replay        # poll the prebaked job id
#   GATE_MODE=live ./release-gate.sh       # full live run (prep, not stage)
#
# Every mode degrades to the ./specs fixtures if EvalHub is unreachable, so
# this script ALWAYS reaches a BLOCKED or PROMOTE banner.

set -uo pipefail   # no -e: failures are handled so the demo always completes

cd "$(dirname "${BASH_SOURCE[0]}")"

MODE="${GATE_MODE:-auto}"
JOB_SPEC="${JOB_SPEC:-specs/job-edd-release-gate.json}"
TIMEOUT="${GATE_TIMEOUT:-360}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)    MODE="$2"; shift 2 ;;
    --offline) MODE="offline"; shift ;;
    --live)    MODE="live"; shift ;;
    --replay)  MODE="replay"; shift ;;
    --job-spec) JOB_SPEC="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

command -v jq >/dev/null || { echo "jq is required" >&2; exit 2; }

RED=$'\033[1;31m'; GREEN=$'\033[1;32m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RESET=$'\033[0m'

RESULTS="$(mktemp -t edd-gate-XXXXXX.json)"
trap 'rm -f "$RESULTS"' EXIT

echo "${DIM}── EDD release gate ── mode=${MODE} ── spec=${JOB_SPEC} ──${RESET}"

# ---------------------------------------------------------------------------
# 1. Run the evaluation (live / replay / offline -- the provider decides)
# ---------------------------------------------------------------------------
if ! python3 -m harness.evalhub_client --job-spec "$JOB_SPEC" gate --mode "$MODE" --timeout "$TIMEOUT" > "$RESULTS"; then
  echo "${RED}harness error: no verdict produced${RESET}" >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# 2. Parse the verdict (results.test.pass) and the per-benchmark findings
# ---------------------------------------------------------------------------
PASS=$(jq -r '.results.test.pass' "$RESULTS")
SCORE=$(jq -r '.results.test.score' "$RESULTS")
THRESHOLD=$(jq -r '.results.test.threshold' "$RESULTS")
JOB_ID=$(jq -r '.resource.id' "$RESULTS")

if [[ "$PASS" != "true" && "$PASS" != "false" ]]; then
  echo "${RED}harness error: results.test.pass missing from record${RESET}" >&2
  exit 2
fi

echo
echo "${BOLD}  candidate ${RESET} $(jq -r '.model.name' "$RESULTS")"
echo "${BOLD}  job       ${RESET} ${JOB_ID}"
echo "${BOLD}  collection${RESET} $(jq -r '.collection.id' "$RESULTS")"
echo
printf "  %-22s %-28s %8s %10s   %s\n" "BENCHMARK" "PROVIDER" "SCORE" "THRESHOLD" "RESULT"
jq -r '.results.benchmarks[] |
  [.id, .provider_id, (.test.primary_score|tostring), (.test.threshold|tostring), (if .test.pass then "pass" else "FAIL" end)] | @tsv' "$RESULTS" |
while IFS=$'\t' read -r id provider score thr result; do
  if [[ "$result" == "FAIL" ]]; then color="$RED"; else color="$GREEN"; fi
  printf "  %-22s %-28s %8s %10s   ${color}%s${RESET}\n" "$id" "$provider" "$score" "$thr" "$result"
done

# call out the named findings the runbook narrates
LEAK=$(jq -r '.results.benchmarks[] | select(.id=="owasp_llm_top10") | .metrics.system_prompt_leak // false' "$RESULTS")
BIAS=$(jq -r '.results.benchmarks[] | select(.id=="quality") | .metrics.stereotype_bias_flags // 0' "$RESULTS")
echo
[[ "$LEAK" == "true" ]] && echo "  ${RED}✗ critical finding: system prompt leak EXPOSED (OWASP LLM Top 10)${RESET}"
[[ "$BIAS" != "0" ]]    && echo "  ${DIM}⚠ ${BIAS} stereotype-bias flags (within review range)${RESET}"

# ---------------------------------------------------------------------------
# 3. Land the record in local MLflow (best effort; never blocks the verdict)
# ---------------------------------------------------------------------------
python3 -m harness.mlflow_sync "$RESULTS" 2>&1 | sed "s/^/  ${DIM}/;s/$/${RESET}/" || true

# ---------------------------------------------------------------------------
# 4. The banner and the exit code -- this is the whole point
# ---------------------------------------------------------------------------
echo
if [[ "$PASS" == "true" ]]; then
  echo "${GREEN}"
  cat <<'BANNER'
  ██████╗ ██████╗  ██████╗ ███╗   ███╗ ██████╗ ████████╗███████╗
  ██╔══██╗██╔══██╗██╔═══██╗████╗ ████║██╔═══██╗╚══██╔══╝██╔════╝
  ██████╔╝██████╔╝██║   ██║██╔████╔██║██║   ██║   ██║   █████╗
  ██╔═══╝ ██╔══██╗██║   ██║██║╚██╔╝██║██║   ██║   ██║   ██╔══╝
  ██║     ██║  ██║╚██████╔╝██║ ╚═╝ ██║╚██████╔╝   ██║   ███████╗
  ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝ ╚═════╝    ╚═╝   ╚══════╝
BANNER
  echo "  GATE PASSED — weighted score ${SCORE} ≥ threshold ${THRESHOLD}"
  echo "  candidate may be promoted to production${RESET}"
  exit 0
else
  echo "${RED}"
  cat <<'BANNER'
  ██████╗ ██╗      ██████╗  ██████╗██╗  ██╗███████╗██████╗
  ██╔══██╗██║     ██╔═══██╗██╔════╝██║ ██╔╝██╔════╝██╔══██╗
  ██████╔╝██║     ██║   ██║██║     █████╔╝ █████╗  ██║  ██║
  ██╔══██╗██║     ██║   ██║██║     ██╔═██╗ ██╔══╝  ██║  ██║
  ██████╔╝███████╗╚██████╔╝╚██████╗██║  ██╗███████╗██████╔╝
  ╚═════╝ ╚══════╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝╚══════╝╚═════╝
BANNER
  echo "  RELEASE BLOCKED — weighted score ${SCORE} < threshold ${THRESHOLD}"
  echo "  this is exit 1 in your release pipeline, the same way a red unit test blocks a merge${RESET}"
  exit 1
fi
