#!/usr/bin/env bash
# examples/demo.sh — end-to-end demo of the kb-tools feedback loop.
#
# Usage:
#   ./examples/demo.sh --help         # print this help
#   ./examples/demo.sh --smoke        # CI smoke test: no LLM calls, exits 0
#   ./examples/demo.sh               # real run: dry-prints each step
#   ./examples/demo.sh --real-llm    # real run: actually call LLM steps
#                                    #   (requires KB_AGENT_PROXY)
#
# This script is intentionally POSIX-ish. It uses bash only for ${var//}
# expansions and $((...)) arithmetic. It will not work under /bin/sh on
# systems where sh is dash, but it does work on macOS /bin/bash and
# GitHub Actions ubuntu-latest /bin/bash.
#
# Exit codes:
#   0  success
#   1  user error (bad flag, missing dependency, not in a bucket)
#   2  command failed (kb returned non-zero; check the log)

set -e

# ---- locate script and the demo bucket ------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUCKET_DIR="${SCRIPT_DIR}/demo-bucket"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---- defaults -------------------------------------------------------------
MODE="default"        # default | smoke | real-llm
DO_INGEST=1
DO_INDEX=1
DO_ANALYZE=0          # off by default (needs LLM)
DO_SFT=0              # off by default (needs LLM)
DO_MODELS=1           # register baseline + candidates (no LLM)
DO_EVALUATE=0         # off by default (needs LLM, analyzed docs)
DO_IMPROVE=0          # off by default (needs LLM, analyzed docs)
EVAL_LIMIT=12         # doc count cap; smoke uses 2

# ---- helpers --------------------------------------------------------------
log()  { printf '[demo] %s\n' "$*"; }
fail() { printf '[demo] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<USAGE
examples/demo.sh — end-to-end demo of the kb-tools feedback loop.

MODES
  (default)      Print the commands the demo would run, but do not invoke
                 the LLM-touching ones. Use this to inspect the flow.
  --smoke        CI mode. Skip every step that would call an LLM. Adds a
                 baseline model and a candidate so 'kb models list' is
                 non-empty. Always exits 0.
  --real-llm     Actually run \`kb sft\`, \`kb analyze\`, \`kb evaluate\`, and
                 \`kb improve run\`. Requires KB_AGENT_PROXY to point at a
                 working ai-hub-agent-proxy. Use this when you have a
                 trained candidate to evaluate.

OPTIONS
  --help         Show this help and exit.
  --no-ingest    Skip the 'kb ingest' step (the demo bucket has no inbox
                 contents, so ingest is a no-op by default anyway).
  --no-models    Skip 'kb models add'. Useful if you want to drive the
                 model registry yourself.

EXAMPLES
  # 1. Watch what the demo plans to do, without running LLM steps:
  ./examples/demo.sh

  # 2. Run the full pipeline against a real agent proxy:
  KB_AGENT_PROXY=~/ai-hub_agent_proxy/dist/cli.js \\
      ./examples/demo.sh --real-llm

  # 3. CI smoke test (no LLM, fast, deterministic):
  ./examples/demo.sh --smoke
USAGE
}

# ---- arg parsing ----------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h)        usage; exit 0 ;;
    --smoke)          MODE="smoke" ;;
    --real-llm)       MODE="real-llm" ;;
    --no-ingest)      DO_INGEST=0 ;;
    --no-models)      DO_MODELS=0 ;;
    *)                fail "Unknown flag: $1 (try --help)" ;;
  esac
  shift
done

# ---- preconditions --------------------------------------------------------
command -v kb >/dev/null 2>&1 || fail "kb CLI not found on PATH (pip install -e .)"

[ -d "${BUCKET_DIR}" ]           || fail "Demo bucket missing: ${BUCKET_DIR}"
[ -f "${BUCKET_DIR}/config/kb.yml" ] \
  || fail "Demo bucket not initialized: ${BUCKET_DIR}/config/kb.yml"

cd "${BUCKET_DIR}"
log "Working directory: $(pwd)"
log "Mode:              ${MODE}"
if [ "${MODE}" = "real-llm" ]; then
  if [ -z "${KB_AGENT_PROXY:-}" ] && [ ! -x "${HOME}/ai-hub_agent_proxy/dist/cli.js" ]; then
    fail "--real-llm requires KB_AGENT_PROXY or ~/ai-hub_agent_proxy/dist/cli.js"
  fi
  DO_ANALYZE=1
  DO_SFT=1
  DO_EVALUATE=1
  DO_IMPROVE=1
elif [ "${MODE}" = "smoke" ]; then
  EVAL_LIMIT=2
fi

# ---- step 1: ingest (no-op if inbox empty) -------------------------------
step() { printf '\n[demo] === step %s: %s ===\n' "$1" "$2"; }

step 1 "ingest inbox"
if [ "${DO_INGEST}" = "1" ]; then
  # The demo bucket ships with an empty inbox. `kb ingest` is idempotent
  # and prints "No files to ingest." when there is nothing to do.
  kb ingest || true
else
  log "skipped (--no-ingest)"
fi

# ---- step 2: build the FTS5 index ----------------------------------------
step 2 "build FTS5 index"
if [ "${DO_INDEX}" = "1" ]; then
  # `kb add` writes to the index on each call, so most of the demo bucket
  # is already indexed. --sync is cheap; --rebuild is the heavy hammer.
  kb index --sync
fi

# ---- step 3: analyze (real LLM) ------------------------------------------
step 3 "analyze docs"
if [ "${DO_ANALYZE}" = "1" ]; then
  # Analyze the whole bucket once. Pass --retry-failed to top up
  # documents whose analysis was incomplete.
  kb analyze --retry-failed -w 4 || \
    log "analyze: continuing (some failures are expected in --real-llm mode)"
else
  log "skipped (set --real-llm, or run 'kb analyze --retry-failed' manually)"
  log "  -> QC4 will report 'unanalyzed' until you do; that is expected."
fi

# ---- step 4: sft dataset build (real LLM) --------------------------------
step 4 "build SFT dataset"
if [ "${DO_SFT}" = "1" ]; then
  # `kb sft` is the one-command path: generate -> dedup -> shuffle -> split.
  # Use --concept to focus on a slice; --limit to cap cost.
  kb sft --concept "vector-database" --limit "${EVAL_LIMIT}" -n 2 || \
    log "sft: continuing (no analyzed docs yet?)"
else
  log "skipped (set --real-llm to enable; this step needs analyzed docs)"
fi

# ---- step 5: register baseline + candidate models ------------------------
step 5 "register baseline + candidate models"
if [ "${DO_MODELS}" = "1" ]; then
  # The demo's two models are both 'external' (no real fine-tune happened);
  # they exist so `kb models list` is non-empty and `kb improve` can pick a
  # candidate. --overwrite makes the script idempotent.
  kb models add kb-rag-v1 \
    --base-model claude-opus-4-7 \
    --backend external \
    --notes "demo baseline (v1)" \
    --tag demo --tag baseline \
    --overwrite || true
  kb models add kb-rag-v2 \
    --base-model claude-opus-4-7 \
    --backend external \
    --notes "demo candidate (v2)" \
    --tag demo --tag candidate \
    --overwrite || true
  if [ "${MODE}" = "smoke" ]; then
    log "smoke: skipping 'kb models use' to leave the active model untouched"
  else
    kb models use kb-rag-v1 || true
  fi
else
  log "skipped (--no-models)"
fi

# ---- step 6: evaluate (real LLM) -----------------------------------------
step 6 "evaluate candidate vs baseline"
if [ "${DO_EVALUATE}" = "1" ]; then
  # Compares kb-rag-v2 (candidate) against kb-rag-v1 (baseline) on the
  # analyzed docs. --limit keeps the demo's runtime small. The report
  # is persisted at .kb/models/eval/kb-rag-v2.json.
  kb evaluate \
    --baseline kb-rag-v1 \
    --candidate kb-rag-v2 \
    --limit "${EVAL_LIMIT}" || \
    log "evaluate: continuing (no analyzed docs?)"
else
  log "skipped (set --real-llm to enable; needs analyzed docs + KB_AGENT_PROXY)"
fi

# ---- step 7: improve run (real LLM) --------------------------------------
step 7 "self-iterating improve loop"
if [ "${DO_IMPROVE}" = "1" ]; then
  # The loop runs `kb evaluate` once per iteration and adopts any
  # candidate that beats the current best on the target metric.
  # --max-misses 1 keeps the demo short; in production, default is 2.
  kb improve run -n 1 -k 1 -m concept_jaccard_mean || \
    log "improve: continuing (no analyzed docs?)"
else
  log "skipped (set --real-llm to enable; needs analyzed docs + KB_AGENT_PROXY)"
fi

# ---- wrap up --------------------------------------------------------------
printf '\n[demo] Done. Next steps:\n'
cat <<'NEXT'
  cd examples/demo-bucket
  kb search "HNSW"                # FTS5 search
  kb doctor                       # data-quality summary
  kb models list                  # registered models
  kb improve log                  # past runs
  kb improve log show <run_id>    # detail
NEXT
log "Inspect .kb/improve/ for run artifacts (summary.json + iterations.jsonl)."
log "Exit 0."
