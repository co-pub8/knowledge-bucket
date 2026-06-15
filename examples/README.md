# Examples

`kb-tools` ships with a pre-populated demo bucket so you can exercise the
**full data → SFT → fine-tune → eval → adopt feedback loop** in under a
minute, on your laptop, without setting up a corpus. The demo domain is
**vector databases and embeddings** — concrete enough that you can eyeball
whether the extracted concepts and summaries are correct, and directly
relevant to the tool itself (kb-tools uses FTS5 + vector search under
the hood).

## How to run

```bash
# from the repo root, after `pip install -e ".[dev]"`:
./examples/demo.sh                # dry-run: shows each step, skips LLM calls
./examples/demo.sh --smoke        # CI mode: no LLM, ~2 seconds, exit 0
./examples/demo.sh --real-llm     # real run: needs KB_AGENT_PROXY
bash examples/demo.sh --help      # full flag reference
```

The script `cd`s into `examples/demo-bucket/` (which already has
`config/kb.yml` and 12 sample docs) and runs the seven pipeline steps in
order. By default the LLM-touching steps are **printed but not invoked**;
pass `--real-llm` to actually call the agent proxy. `--smoke` is what CI
runs — no LLM, idempotent, always exit 0.

## What it does

The seven steps correspond to the seven arrows in the feedback-loop
diagram in [`docs/FEEDBACK_LOOP.md`](../docs/FEEDBACK_LOOP.md):

1. **`kb ingest`** — pulls new items from `inbox/` into `records/doc/`. The
   demo bucket ships empty, so this is a no-op ("No files to ingest.").
2. **`kb index --sync`** — incrementally updates the SQLite FTS5 search
   index. Most docs are already indexed from when the bucket was
   created, so this is cheap.
3. **`kb analyze`** *(LLM)* — runs the analyzer prompt over every
   unanalyzed doc and writes `summary`, `concepts`, and `importance` back
   to front matter. The `--smoke` mode skips this; the demo bucket is
   intentionally unanalyzed so you can see the QC4 "unanalyzed" warning
   in `kb doctor` and watch it clear as this step runs.
4. **`kb sft`** *(LLM)* — generates instruction pairs from the analyzed
   docs, dedups across the corpus, deterministically shuffles, and
   writes `train.jsonl` / `val.jsonl` to `.kb/training/sft-dataset/`.
5. **`kb models add`** — registers `kb-rag-v1` (baseline) and
   `kb-rag-v2` (candidate) in `.kb/models/`. Both are `external` (no real
   fine-tune happened); they exist so `kb models list` is non-empty and
   `kb improve` has something to compare.
6. **`kb evaluate`** *(LLM)* — replays the analyzer prompt through each
   model and computes the four headline metrics
   (`concept_jaccard_mean`, `concept_f1_mean`, `importance_kl`,
   `judge_score_mean`). Persists the report to
   `.kb/models/eval/kb-rag-v2.json`.
7. **`kb improve run`** *(LLM)* — runs the self-iterating loop: pick a
   candidate, evaluate it, adopt it if it beats the current best on the
   target metric, persist `summary.json` and `iterations.jsonl` under
   `.kb/improve/<run_id>/`.

## Customizing

To run the demo against **your own corpus** instead of the bundled
vector-DB docs:

```bash
# 1. Make a fresh bucket somewhere on disk.
mkdir -p ~/my-bucket && cd ~/my-bucket
kb init .

# 2. Drop files into inbox/, or use the high-level adders:
kb add --title "My first doc" --content "..." --concepts demo
kb add-paper 2406.01234                 # arXiv id / DOI / title
kb add-repo  https://github.com/you/cool-project
kb add-pdf   /path/to/paper.pdf

# 3. Run the LLM half of the pipeline:
KB_AGENT_PROXY=~/ai-hub_agent_proxy/dist/cli.js \
  kb analyze --retry-failed -w 4
KB_AGENT_PROXY=~/ai-hub_agent_proxy/dist/cli.js \
  kb sft --concept my-topic -n 3

# 4. (After training) register the candidate and run the loop:
kb models add kb-my-v1 --base-model claude-opus-4-7 --backend openai_ft
kb models add kb-my-v2 --base-model claude-opus-4-7 --backend openai_ft \
    --from-job <job_id>
kb improve run -n 3 -m concept_jaccard_mean
```

The demo bucket is also a good **smoke fixture for CI**: it always has
12 docs, the FTS5 index is reproducible, and `kb models add --overwrite`
makes the script idempotent.

## See also

- [`README.md`](../README.md) — top-level project overview, install, quickstart.
- [`docs/FEEDBACK_LOOP.md`](../docs/FEEDBACK_LOOP.md) — full `kb improve`
  contract: target metrics, tolerance, abort playbook, cost notes.
- [`docs/TRAINING_DATA_GENERATION.md`](../docs/TRAINING_DATA_GENERATION.md) —
  the upstream half of the loop (`kb sft` / `kb generate`).
- [`examples/demo-bucket/README.md`](demo-bucket/README.md) — the bucket
  layout itself: which files ship pre-built and which the demo builds.
