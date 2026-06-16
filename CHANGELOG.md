# Changelog

All notable changes to `kb-tools` are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-06-16

### Added
- **Phase 13.1** — `kb models` (model registry: `add` / `list` / `show` / `use`),
  `kb finetune prepare` / `submit` (dataset conversion to `hf` / `openai` / `alpaca`
  formats and job recording).
- **Phase 13.2** — `kb evaluate` with four metrics (`concept_jaccard_mean`,
  `concept_f1_mean`, `importance_kl`, `judge_score_mean`) plus an LLM-as-judge
  pass and an evaluation cache.
- **Phase 14** — `kb improve run` self-iterating feedback loop. Evaluates
  candidate models against the baseline, promotes any that exceed the
  configured tolerance on the target metric, and persists a per-run log
  accessible via `kb improve log` / `log list` / `log show`.
- **Phase 15** — `examples/demo-bucket/` (12 pre-populated sample docs on
  vector databases and embeddings) plus the end-to-end `examples/demo.sh`
  script (with `--smoke` CI mode and `--real-llm` full-pipeline mode).
- `install-smoke` CI job — builds the wheel and installs it into a fresh
  venv on Python 3.11 / 3.12 / 3.13, then exercises `kb --version` /
  `kb init` / `kb add` / `kb search` end-to-end. Catches sdist / wheel /
  metadata regressions that editable `pip install -e` would miss.
- **`docs/GOVERNANCE.md` + `CLAUDE.md`** — full-private policy and the
  AI-agent hook to read it on every session. See "Notes" below.

### Changed
- Bumped `pyproject.toml` version to `0.2.0` to reflect Phases 13-15.

### Notes
- **This release is internal only.** No PyPI publish, no public GitHub
  mirror, no external distribution channel of any kind. The version
  bump tracks the *code* state, not a release artifact. Per
  `docs/GOVERNANCE.md` §1-4, this is permanent policy.
- The install-smoke job replaces what would have been a public release
  workflow. It validates the wheel internally so we know the package
  shape is correct, without ever publishing.
- Previous commit (reverted in 694631f) had prepared a Trusted
  Publishing setup under Phase 16. That was rolled back in the
  `chore(kb): slim pyproject.toml — drop PyPI-only metadata` commit
  because the project is private.
- The `authors` block uses a name only (no email). Earlier Phase 16
  work added a placeholder email that has now been removed.

## [0.1.0] - 2026-XX-XX

Initial local-development release. Bundled the core
`kb` CLI, FTS5 + concept-graph + vectorize pipelines, and the
`kb ingest` / `kb sync` / `kb serve` workflows.
