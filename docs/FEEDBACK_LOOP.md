# Automating the Feedback Loop — `kb improve`

`kb improve` is the conductor that closes the loop between **data → SFT →
fine-tune → eval → adopt**. It runs in a sandbox you control: every step is
inspectable, every iteration is persisted, and the loop halts the moment a
candidate stops beating the current best. The actual training is still out
of scope — the user runs the trainer externally and registers the model —
but everything around it (selection, evaluation, decision, recording) is
automated.

This chapter assumes you've already read
[`TRAINING_DATA_GENERATION.md`](TRAINING_DATA_GENERATION.md) and the
[`DESIGN.md`](DESIGN.md) entry on Phase 14.

---

## 1. The feedback loop in one picture

```
+-------------+   +-----------+   +-----------+   +----------+   +--------+
| kb sft      |→  | kb finetune|→  | kb models |→  | kb       |→  | kb     |
|  generates  |   |   submit   |   |   add     |   | evaluate |   | improve|
|  SFT pairs  |   |  (record)  |   | (register)|   | (measure)|   | (adopt)|
+-------------+   +-----------+   +-----------+   +----------+   +--------+
                                                              ↑            |
                                                              └────────────┘
                                                          flip active model
                                                         when target improves
```

The three steps on the left (`sft → finetune → add`) are the **human
bottleneck**: you have to actually wait for the training run. The two
steps on the right (`evaluate → improve`) are the part `kb improve`
automates. Most weeks, you run the human side once over the weekend,
then let `kb improve` decide whether the new model is worth promoting.

---

## 2. Manual mode (the legacy four-step path)

Before `kb improve` existed, the loop was driven by hand:

```bash
# 1. Generate SFT data from the corpus.
kb sft --concept retrieval-augmented-generation --pairs 5

# 2. Submit the training job (records to .kb/finetune/<job_id>/).
kb finetune submit \
  --output-model-id kb-rag-v2 \
  --base-model claude-opus-4-7 \
  --backend openai_ft

# 3. After training finishes, register the new model.
kb models add kb-rag-v2 \
  --base-model claude-opus-4-7 \
  --backend openai_ft \
  --from-job <job_id>

# 4. Evaluate it against the current baseline.
kb evaluate --baseline kb-rag-v1 --candidate kb-rag-v2
# → Read the metrics, eyeball the headline number, decide.

# 5. (If adopted) flip the active model.
kb models use kb-rag-v2
```

That works, but the "decide" step is where mistakes happen. Did the new
model beat the baseline by a real margin, or was the diff inside the
judge's noise floor? Did the candidate regress on a metric you weren't
watching? `kb improve` formalizes that decision and keeps the receipts.

---

## 3. Automated mode: `kb improve`

`kb improve` runs the **measure → compare → adopt** half of the loop.
You stay in charge of the actual training, but the orchestration is
scripted, deterministic, and re-runnable.

What it automates:

- Picks a baseline model (your choice, the active one, or the first
  registered).
- Picks candidates (your list, or all registered models minus the
  baseline).
- Calls `kb evaluate` once per iteration, round-robin through the
  candidate pool.
- Compares the candidate's target metric against the current best,
  applying a tolerance.
- Flips the active model (`kb models use <winner>`) when the candidate
  wins.
- Persists every iteration and a crash-safe `summary.json` to
  `.kb/improve/<run_id>/`.

What stays human:

- The actual training run (`kb finetune submit` is a record, not a
  trigger).
- The corpus growth (you still `kb add` / `kb ingest` new docs).
- Reading the run summary to decide whether to train another candidate
  or change the metric.

---

## 4. Setup checklist

Before you invoke `kb improve`, confirm the following. Each row also
links to the command that verifies it.

| Requirement | How to check |
|---|---|
| Bucket is initialized | `kb --version` works and `config/kb.yml` exists |
| Corpus is analyzed | `kb doctor` (QC4 analysis coverage = all analyzed) |
| At least one baseline model | `kb models list` shows ≥ 1 row |
| At least one candidate model | `kb models list` shows ≥ 2 rows |
| Judge model is configured | `kb evaluate --help` shows `--judge-model`; env or `config/kb.yml` |
| (Recommended) prior eval report for the baseline | `.kb/models/eval/<baseline_id>.json` exists |

If the corpus is small (< ~30 docs), expect a noisy signal. Aim for
50+ analyzed docs before trusting the headline metric.

### Registering the candidate

Candidates must be **trained elsewhere** and registered with `kb
models add`. The loop does not call any training backend on its own.

```bash
# After your external trainer finishes a run:
kb models add kb-rag-v2 \
  --base-model claude-opus-4-7 \
  --backend openai_ft \
  --notes "trained on kb sft --concept retrieval-augmented-generation, v2"
```

For convenience, the loop will also auto-register a candidate on the
fly if it is mentioned by `--candidates` but missing from the registry.
That is meant for one-off experiments; for production candidates,
register explicitly so the notes and hyperparams are recorded.

---

## 5. Running `kb improve`

The most common invocation is:

```bash
kb improve run \
  --iterations 3 \
  --target-metric concept_jaccard_mean
```

Annotated:

| Flag | Meaning |
|---|---|
| `--iterations N` (`-n`) | How many candidates to evaluate (default 3). |
| `--target-metric M` (`-m`) | Which metric to optimize (see §6). |
| `--tolerance T` (`-t`) | Slack for adoption and regression (default 0.0). |
| `--baseline B` (`-b`) | Override the resolved baseline id. |
| `--candidates C1,C2` (`-c`) | Comma-separated candidate pool. Default = all registered. |
| `--judge-model J` (`-j`) | Forwarded to `kb evaluate`. |
| `--max-misses K` (`-k`) | Consecutive non-adoptions before abort (default 2). |
| `--limit L` (`-l`) | Cap docs per eval (default all analyzed). |
| `--no-cache` | Disable the eval cache. |
| `--json` | Emit the full summary as JSON. |

The run creates `.kb/improve/<run_id>/` with two artifacts:

```
.kb/improve/01JABCDEFGHJK/
├── summary.json       # canonical record (rewritten after every iteration)
└── iterations.jsonl   # append-only log, one JSON object per line
```

`summary.json` is what `kb improve log show` reads back. `iterations.jsonl`
is the streaming-friendly sidecar — `tail -f` it to watch a long run.

### Example: a typical 3-iteration pass

```
$ kb improve run -n 3 -m concept_jaccard_mean
=== kb improve: 01JABCDEFGHJK ===

Status:          completed
Target metric:   concept_jaccard_mean (higher-better)
Tolerance:       0.0
Baseline:        kb-rag-v1 (initial=0.42)
Iterations run:  3/3
Adopted:         1
Misses:          0
Final model:     kb-rag-v2
Started:         2026-06-15T10:00:00Z
Finished:        2026-06-15T10:15:00Z

--- Iterations ---
  ITER CANDIDATE             BASELINE              VALUE  DECISION
  0    kb-rag-v2             kb-rag-v1              0.4800  adopt
  1    kb-rag-v3             kb-rag-v2              0.4500  skip
  2    kb-rag-v4             kb-rag-v2              0.4900  adopt

Summary:  .kb/improve/01JABCDEFGHJK/summary.json
Log:      .kb/improve/01JABCDEFGHJK/iterations.jsonl
```

---

## 6. Choosing a target metric

`kb improve` accepts any metric in the direction table. The mapping lives
in `src/kb/improve.py` — `HIGHER_BETTER` and `LOWER_BETTER` — and is
verified against the canonical `kb evaluate` output.

| Metric | Direction | Computed from | When to use |
|---|---|---|---|
| `concept_jaccard_mean` | higher | overlap of predicted vs. actual concept sets | Default. Stable, no judge, fast. |
| `concept_f1_mean` | higher | precision/recall on concepts | When false positives matter as much as misses. |
| `concept_precision_mean` | higher | TP / (TP + FP) on concepts | When you want narrower concept lists. |
| `concept_recall_mean` | higher | TP / (TP + FN) on concepts | When you hate missing a real concept. |
| `judge_score_mean` | higher | LLM-as-judge 1-5 | End-to-end quality (closest to "user satisfaction"). |
| `importance_kl` | lower | KL divergence on importance distribution | When the importance score distribution is the goal. |
| `importance_js` | lower | JS divergence (symmetric) | Same use as KL, symmetric. |
| `baseline_failure_rate` | lower | fraction of failed runs | Reduce the absolute failure count. |
| `candidate_failure_rate` | lower | fraction of failed runs | Same as above, candidate-side. |

**Defaults that work for most corpora:**

- `concept_jaccard_mean` — the all-purpose choice. Stable across judges,
  cheap to compute, and doesn't require a judge model. Use this when in
  doubt.
- `judge_score_mean` — when you want the model to score well on a
  downstream quality judgment (e.g. "is this summary actually useful?").
  Slower, costs more, and noisier; pass a deterministic judge model.

**Avoid mixing direction targets.** Don't compare a run that adopted on
`judge_score_mean` to one that adopted on `importance_kl`. The semantics
of "winner" differ.

---

## 7. Tuning tolerance

Tolerance (`--tolerance`) is the slack band around the current best.
Differences within `±tolerance` are treated as **ties and adopted** (the
loop is lenient on purpose: the user asked for slack, so use it).

- `tolerance=0.0` (default): adopt only on strict improvement. Best
  when your eval is deterministic (no judge) and you want a clear
  signal.
- `tolerance=0.01` to `0.05` on `concept_jaccard_mean`: a reasonable
  band to absorb the judge's noise. Adopts on a tie or a tiny edge.
- `tolerance` does not gate regression checks. A regression abort
  fires when the candidate is *worse* than the *initial* baseline by
  more than `tolerance`. So a larger tolerance makes the loop both
  *more eager to adopt* and *more lenient about regressions*. Tune
  with care.

If your judge is very noisy (temperature > 0, model updates
mid-experiment), consider raising tolerance. If your eval is
deterministic (cached concept Jaccard), keep it at 0.

---

## 8. Reading `kb improve log`

`kb improve log` (alias: `kb improve log list`) lists recent runs
sorted by `started_at` descending:

```
  RUN_ID                       STARTED                STATUS                     METRIC                FINAL_MODEL          ITER
  01JABCDEFGHJK                2026-06-15T10:00:00Z   completed                  concept_jaccard_mean  kb-rag-v2            3
  01JAAAA00000000BBBBB         2026-06-14T09:00:00Z   aborted_no_improvement     concept_jaccard_mean  kb-rag-v1            5
  01J99990000000000ZZZZ        2026-06-13T22:00:00Z   aborted_regression         judge_score_mean      kb-rag-v0            1
```

`kb improve log show <run_id>` prints the full record — every
iteration, every decision, the reason string from `_decide_adoption`,
and the timestamp. Pass `--json` to dump the raw dict for grep/jq.

### Status taxonomy

| Status | What it means | What to do |
|---|---|---|
| `completed` | Loop ran to the requested number of iterations. | Read the final model. Adopt? Re-evaluate? |
| `aborted_no_improvement` | `max_misses` consecutive candidates failed to beat the current best. | The corpus/model is at a local optimum. Add more training data or change `--target-metric`. |
| `aborted_regression` | A candidate was so much worse than the initial baseline that it tripped the regression guard. | Inspect the candidate — it may be broken, misregistered, or the wrong base. |
| `aborted_no_candidates` | Resolution found no candidates after filtering out the baseline. | Register more models with `kb models add`. |
| `running` | The previous run was interrupted (Ctrl-C, crash). | Inspect the partial summary, then start a fresh run with a new ULID. |
| `aborted_max_iterations` | Safety fallback; not written by the orchestrator today. | If you see this, it's a bug. File an issue with the summary. |

---

## 9. Cost notes

A `kb improve` run's bill is roughly:

```
cost ≈ N_iterations × N_docs × (
    1 baseline eval
  + 1 candidate eval
  + 1 judge call          # only if --judge-model is set / judge_score_mean
)
```

Concrete example (the headline case from `GOAL.md`):

- 3 iterations × 50 docs × (1 + 1) = **300 LLM calls** without a judge
- 3 iterations × 50 docs × (1 + 1 + 1) = **450 LLM calls** with a judge

The eval cache makes this cheaper in practice: re-running the loop
against an unchanged corpus reuses `.kb/models/eval/cache/<model>/`
and drops the analyze phase. Pass `--no-cache` only when you suspect
the cached analyses are stale (e.g. the model is identical to a prior
eval and you want to re-verify).

When cost matters, narrow the scope:

```bash
# Quick triage run on a 20-doc slice:
kb improve run -n 3 -l 20 --target-metric concept_jaccard_mean

# Full pass on the whole corpus:
kb improve run -n 5 -l 200 --target-metric concept_jaccard_mean
```

---

## 10. Abort playbook

When a run aborts, the question is always **why** and **what next**.
The action map:

### `aborted_no_improvement`

You've hit a local optimum. Three options, in order of cost:

1. **Train more candidates.** The simplest fix: more rounds of SFT
   data, longer training, or different hyperparams. Re-run
   `kb improve` after each.
2. **Re-examine the metric.** Are you optimizing the right thing? If
   `concept_jaccard_mean` is stuck at 0.5, maybe `judge_score_mean`
   has more headroom (or vice versa).
3. **Grow the corpus.** More analyzed docs give the eval more
   statistical power. `kb ingest` + `kb analyze` before retrying.

### `aborted_regression`

The candidate was so much worse than the initial baseline that the
loop bailed. This is the "something is broken" signal.

1. Open the run's `iterations.jsonl` and find the regression row.
2. Run `kb evaluate --baseline <initial> --candidate <regressor>`
   manually to confirm the metric.
3. Check that the candidate was registered with the right `base_model`
   and `backend`. A misregistered "external" model that points at the
   wrong upstream id will silently underperform.
4. If the regression is real and not a bug, the model is genuinely
   worse — don't adopt. Train a different one.

### `aborted_no_candidates`

You didn't register a candidate. `kb models add` one or two before
re-running.

### `running` after the fact

A run was killed mid-loop. Open `summary.json` — it will have
`status=running` and a partial `iterations` list. The fix is to
inspect the partial state, learn what you can, and start a fresh run.
A `kb improve` crash does not corrupt any prior runs.

---

## 11. Dogfooding notes

`kb improve` is exercised end-to-end by
[`tests/test_improve.py::TestE2E::test_three_iterations_at_least_one_adopt`](../tests/test_improve.py).
The test registers a baseline plus three candidates, mocks
`kb.improve.evaluate.run_eval` to return trending-up `concept_jaccard_mean`
values, and asserts that the strongest candidate becomes the final
active model. No real LLM calls happen; the test runs in well under
a second.

A live dogfooding run on the kb-tools corpus itself is tracked in
[`GOAL.md`](GOAL.md) Phase 14. Once a real candidate model is trained
and registered, the run will be linked here with its `run_id` and the
delta it produced on the headline metric.

---

## 12. Related chapters

- [`TRAINING_DATA_GENERATION.md`](TRAINING_DATA_GENERATION.md) — the
  upstream half of the loop. `kb sft` produces the data that trains
  the candidates `kb improve` will eventually adopt.
- [`GOAL.md`](GOAL.md) — the current target and the seven completion
  criteria for Phase 14. Once those are checked off, this chapter
  becomes the canonical how-to.
- [`DESIGN.md`](DESIGN.md) — the full design contract for `kb improve`
  (state schema, abort rules, direction table, public API).
