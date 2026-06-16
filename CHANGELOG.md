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
- **Phase 16** — first PyPI release. Trusted Publishing via
  `.github/workflows/release.yml` (no API token), and an `install-smoke`
  CI job that builds the wheel and installs it into a fresh venv on
  Python 3.11 / 3.12 / 3.13.

### Changed
- Bumped `pyproject.toml` version to `0.2.0`.
- `pyproject.toml` now declares `readme = "README.md"`, an expanded
  `keywords` list (12 entries), expanded `classifiers` (16 entries),
  a `[project.urls]` block with Homepage / Repository / Issues / Changelog,
  and a `[tool.setuptools]` block bundling `LICENSE` and prompt
  `*.md` files.
- `README.md` install section now leads with `pip install kb-tools`,
  documents the `embedding` and `all` extras, and adds a
  `kb --version` verification step.

### Notes
- This is the first release published to PyPI.
- The package remains Alpha (Development Status :: 3 - Alpha).
- Author email in `pyproject.toml` is the placeholder
  `jinno@example.com` — replace with a real address before tagging.

## [0.1.0] - 2026-XX-XX

Initial local-development release (pre-PyPI). Bundled the core
`kb` CLI, FTS5 + concept-graph + vectorize pipelines, and the
`kb ingest` / `kb sync` / `kb serve` workflows.
