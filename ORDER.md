# 長期計画 — kb-tools (knowledge-bucket)

> この文書は長期計画の**正本**（内容の正本）。到達点・現状との差・優先順・依存・出口条件・次の一手を管理する。
> 実行用の分解は [docs/MILESTONES.md](docs/MILESTONES.md)、現在の標的の原文は [docs/GOAL.md](docs/GOAL.md)。
> 作成: 2026-10-24（owner 指示 OI-20261024-28）。

## 既存目的との関係

- [SYSTEM_CONSTITUTION.md](SYSTEM_CONSTITUTION.md) が不変の設計原則と究極ゴール（変更不可）。本計画はそれを段階に落とした実現手順にすぎず、憲法に矛盾する段階は作らない。
- [docs/GOVERNANCE.md](docs/GOVERNANCE.md) が上位制約（完全プライベート・外部共有ゼロ・PyPI 公開禁止・計画経由のみ機能追加）。全段階はこの制約内で完結し、進行判定もリポ内証拠（テスト・run ログ）で行う。
- [docs/GOAL.md](docs/GOAL.md) は「今の標的」の実行文書（driver 管理の live 文書）。本計画は上位から参照するのみで置き換えない。
- [PURPOSE.md](PURPOSE.md) は構想期の文書で、現在の Python 実装（`src/kb` / pytest / ruff）と技術スタックが乖離している。全面更新は owner 作業とし、本計画では到達点の根拠に使わない。

## 到達点（2026-10-24 時点）

- v0.2.0（内部リリース、[CHANGELOG.md](CHANGELOG.md) 2026-06-16）: フィードバックループ基盤（Phase 13-15）が実装済み — `kb models` / `kb finetune prepare,submit` / `kb evaluate`（4 指標 + LLM judge）/ `kb improve run`（採用判定 + run ログ）。
- テスト: `python -m pytest tests/ -q` で 696 passed（2026-10-24 ローカル実行）。ただし `tests/test_demo.py` 8 件は後述のギャップで失敗。
- CI: `.github/workflows/tests.yml` に test（ruff + pytest、Python 3.11-3.13）/ demo-smoke / install-smoke を保持。
- Git: 136 コミット。GOVERNANCE 準拠（release.yml は削除済み、公開経路なし）。

## 現状との差（ギャップ）

1. **demo-bucket のサンプル doc が git に存在しない**: `.gitignore` のグローバルパターン `records/` `config/` `inbox/` が `examples/demo-bucket/` 配下にも一致し、12 件のサンプル doc と `config/kb.yml` が一度もコミットされていない（追加コミット皆無を `git log --all -- examples/demo-bucket/` で確認）。結果、`tests/test_demo.py` 8 件がローカルで失敗し、CI demo-smoke も同じ理由で落ち得る。
2. **実 corpus でのループ実走がゼロ**: GOAL.md 完了基準 1-7 のうち基準 1（`bin/build-self-corpus.sh`）と基準 7（`bin/self-dogfood.sh`）が未作成。[docs/FEEDBACK_LOOP.md](docs/FEEDBACK_LOOP.md) §11 に実 run の `run_id` 記録なし（現状はモックテストと demo のみ）。

つまり「基盤は完成、実走は未着手」が現在位置。

## 優先順

1. demo-bucket サンプル doc のリポ復元と test_demo.py の green 回復（MS-002）— 実走の前提であり現行 CI の赤。
2. 自己 corpus でフィードバックループ 1 サイクル完走（GOAL.md 基準 1-7、MS-003〜MS-009）。
3. 2 周目 dogfooding による改善継続性の証明（MS-010）。
4. corpus 拡大 → 規模化 → Web UI 刷新（MS-011〜MS-013、着手条件は GOAL.md「標的達成後」表のとおり）。

## 依存

- 基準 4（外部 fine-tune）は jinno が手元で学習を実行する前提（GOAL.md 範囲外: 自動 fine-tune はしない）。kb 側は `kb finetune submit` のジョブ記録まで。
- `--real-llm` 経路は外部 LLM プロキシ（ai-hub-agent-proxy 等）に依存。CI は LLM 経路 skip の smoke のみ。
- 外部公開は一切行わない（GOVERNANCE.md）。計画進行の判定はリポ内証拠のみで行う。

## 出口条件

- 第 1 段階（現在の標的）: GOAL.md 完了基準 1-7 がすべて確認コマンドで検証でき、§11 に `run_id` 付きの実 run 記録が存在すること。
- 第 2 段階: 2 周連続で `concept_jaccard_mean` 改善を e2e 証明。
- 全段階共通: `python -m pytest tests/ -q` green・`ruff check src/ tests/` clean を維持。

## 次の一手

- MS-002: `.gitignore` の除外パターンをリポルート固定（`/records/` 等）にして `examples/demo-bucket/` のサンプル doc と `config/kb.yml` を復元し、`python -m pytest tests/test_demo.py -q` を green にする（約 30 分の検証可能な作業）。

## 更新ルール

- マイルストーンの状態変更は [docs/MILESTONES.md](docs/MILESTONES.md) で行う。本文件は段落レベルの計画変更時のみ更新する。
- 達成記録は git log と [docs/FEEDBACK_LOOP.md](docs/FEEDBACK_LOOP.md) §11 に置き、本文件の「到達点」は要約として維持する。
- 本文件を変更したら `REPO_METADATA.json` の `long_term.source_hash` / `updated_at` を更新する。
