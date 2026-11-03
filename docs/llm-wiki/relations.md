# Repository relations
Repository: knowledge-bucket

## github-actions-ci
- Status: confirmed
- Relationship: provider/consumer — GitHub Actions provides the merge gate and consumes the tracked files of this repository.
- Responsibility: this repo owns the shipped demo-bucket content and the ignore rules that decide what a fresh CI checkout receives; the workflow file only defines the gate.
- Canonical sources: knowledge-bucket `.github/workflows/tests.yml`, knowledge-bucket `examples/demo-bucket/config/kb.yml`
- Change rule: when `.gitignore` or `examples/demo-bucket/**` changes, run `pytest tests/test_demo.py -q` and `bash examples/demo.sh --smoke` before the change lands — the `test` job and the `demo-smoke` job read those paths from a fresh checkout, so an ignore-pattern change is a CI-visible change.
- Evidence: knowledge-bucket:.github/workflows/tests.yml sha256:310ad67b3d99d61be3205d56410a7965e29d86e99606ca5a1939fac18464025c
- Evidence: knowledge-bucket:.gitignore sha256:351678fe8eead5c412e53b720628a565263a9e90260a8c24d844238cf664e7d1
- Evidence: knowledge-bucket:examples/demo-bucket/config/kb.yml sha256:2e322797462762f884d9ef4c666d21240634bd99f41456faf5276c2c8e5113b7
- Observation: main run 40075305488 (2026-10-24) failed the `test` job with 8 assertions in `tests/test_demo.py` and the `demo-smoke` job with `[demo] ERROR: Demo bucket not initialized: .../examples/demo-bucket/config/kb.yml`.
- Observation: root cause was the unanchored `records/`, `config/`, `inbox/` patterns in `.gitignore` — they match at any depth, so commit 60cbdf4's shipped demo bucket was silently never tracked. The recorded intent (docs/llm-wiki/log.md, 2026-06-11 Phase 10.2) was repo-root-only blocking.
- Follow-up: [x] knowledge-bucket, `.gitignore` anchoring plus the demo-bucket content committed — completed: `config/kb.yml`, `inbox/.gitkeep` and the 12 sample docs are tracked and sha256-identical to the authoritative copies under `/Users/jinno/knowledge-bucket/examples/demo-bucket/`; `pytest tests/test_demo.py -q` -> 14 passed; `bash examples/demo.sh --smoke` -> exit 0.
- Follow-up: [ ] tas-autopilot, PR #1 stays stranded while origin/main CI is red — the fix must reach origin/main. Completion condition: origin/main CI green and PR #1 merged.

## ai-hub-chain
- Status: confirmed
- Relationship: provider/consumer — the ai-hub chain provides the run worktree and the landing (fast-forward merge into the managed checkout) that publishes this repo's chain changes.
- Responsibility: ai-hub owns landing validation and PR-first publication; this repo owns the fix content and the branch the fix sits on.
- Canonical sources: ai-hub `tools/harness/core/worktree_merge.py`, ai-hub `tools/harness/core/worktree_paths.py`
- Change rule: an agent run inside an ai-hub chain worktree must leave its fix commit reachable from the run's recorded `worktree_branch`; the landing rejects the worktree when HEAD points at a different branch, so a fix committed only on a side branch is never published.
- Evidence: ai-hub:tools/harness/core/worktree_merge.py sha256:f3ef0f40d6da04a9401098190e594e423a67822faa9c245e83eaca6a347ae724
- Evidence: ai-hub:tools/harness/core/worktree_paths.py sha256:b0bccec1c671c27501f3e27259cd24054c4bf0f74ffe1617080e86996265fc56
- Observation: the 2026-11-02 care run (branch `tas/auto-care/20261102`, commit `b79b909`) left HEAD on the care branch, so the landing ownership check (worktree HEAD must equal `meta.worktree_branch`) rejected it and the identical fix never reached origin/main; the 2026-10-24 care run (`875c555` on `tas/auto-care/20261024`) failed the same way.
- Follow-up: [x] ai-hub, fix commit placed on the run's chain branch as well as on the care branch — completed: `tas/auto-care/20261103` and `ai/knowledge-bucket/instruction-20261103-060017-585790` point at the same fix commit, so the harness landing can fast-forward it.
