# Milestones — kb-tools

長期計画の正本は [ORDER.md](../ORDER.md)。現在の標的と完了基準の原文は [GOAL.md](GOAL.md)、ループ実走の証跡は [FEEDBACK_LOOP.md](FEEDBACK_LOOP.md) §11。
本文件は実行用の分解であり、完了基準を重複管理しない（MS 番号 → 既存文書の該当節を参照で保持する）。
各項目の `Status` は planned / in_progress / verifying / achieved / blocked。達成判定は Evidence の確認コマンドで行う。

## MS-001: フィードバックループ基盤の実装（Phase 13-15）

Outcome: `kb models` / `kb finetune` / `kb evaluate` / `kb improve run` と demo パイプラインにより、ループの全工程がローカルで動作する
Acceptance: `python -m pytest tests/test_improve.py -q` が green（モック E2E で 3 iteration 中最良候補が採用される）であり、CHANGELOG.md 0.2.0 に Phases 13-15 の記載があること
Evidence: CHANGELOG.md [0.2.0]（Phases 13-15、2026-06-16） / pytest tests/test_improve.py 全パス（2026-10-24 ローカル実行、全体 696 passed）
Status: achieved
依存: なし（基盤完了済み）
次の作業: なし（MS-002 以降へ）

## MS-002: demo-bucket サンプル doc のリポ復元（test_demo.py green 回復）

Outcome: `examples/demo-bucket/` のサンプル doc 12 件と `config/kb.yml` が git で追跡され、demo 関連テストと CI demo-smoke が再び信頼できる状態になる
Acceptance: `python -m pytest tests/test_demo.py -q` が green であること。`git ls-files examples/demo-bucket | wc -l` が README のみ（1）より多いこと
Evidence: pending — 現状は `.gitignore` のグローバル `records/` `config/` `inbox/` パターンにより未コミット（`git log --all -- examples/demo-bucket/` に追加コミットなし、2026-10-24 確認）
Status: planned
依存: なし（最優先の着手項目）
次の作業: `.gitignore` 該当パターンをリポルート固定（`/records/` 等）にして実ファイルを `git add` し、上記 Acceptance で検証する（約 30 分）

## MS-003: 自己 corpus 構築スクリプトの作成（GOAL.md 完了基準 1）

Outcome: kb-tools 自身の md/txt を `~/kb-self-corpus` へ idempotent に `kb init` / ingest できる
Acceptance: `bash bin/build-self-corpus.sh` を 2 回連続実行し、2 回目の ingest 差分が 0 件で終了コード 0 になること
Evidence: pending
Status: planned
依存: なし（MS-002 と並行可）
次の作業: `bin/build-self-corpus.sh` を新設する（GOAL.md 完了基準 1 の原文に従う）

## MS-004: 自己 corpus の分析完走と QC4 100%（GOAL.md 完了基準 2）

Outcome: `~/kb-self-corpus` に対する `kb analyze --retry-failed -w 4` が完走し analysis coverage が 100% になる
Acceptance: `kb analyze --retry-failed -w 4` の終了コード 0 かつ coverage 指示が 100% を示すこと（実行ログを残す）
Evidence: pending
Status: planned
依存: MS-003
次の作業: MS-003 の corpus に対して分析を実行する

## MS-005: SFT ペア生成（GOAL.md 完了基準 3）

Outcome: 自己 corpus から `kb sft --pairs 5 --split 0.9` で SFT ペアが生成される
Acceptance: `kb sft --pairs 5 --split 0.9` が終了コード 0 で、生成ペア数が 5 以上であること
Evidence: pending
Status: planned
依存: MS-004
次の作業: 生成コマンドの実行とデータ確認

## MS-006: 外部 fine-tune モデルの登録（GOAL.md 完了基準 4）

Outcome: jinno が外部で fine-tune したモデルが `kb models add kb-self-v1 --base-model ... --from-job <job_id>` で登録される
Acceptance: `kb models show kb-self-v1` が登録内容（base model / job_id）を表示すること
Evidence: pending
Status: planned
依存: MS-005 と owner（jinno）による学習実行 — kb 側は `kb finetune submit` のジョブ記録まで（GOAL.md 範囲外: 自動 fine-tune はしない）
次の作業: 学習完了後に登録コマンドを実行する（owner 作業待ち）

## MS-007: baseline との評価レポート作成（GOAL.md 完了基準 5）

Outcome: `kb evaluate --baseline <現 active> --candidate kb-self-v1 --limit 50` の 4 指標レポートが `.kb/models/eval/kb-self-v1.json` に保存される
Acceptance: 上記コマンドが終了コード 0 で、レポート JSON に 4 指標が含まれること
Evidence: pending
Status: planned
依存: MS-006
次の作業: 評価コマンドの実行とレポート確認

## MS-008: kb improve 実 run と §11 記録（GOAL.md 完了基準 6）

Outcome: `kb improve run -n 3 -m concept_jaccard_mean` の結果が run_id 付きで `docs/FEEDBACK_LOOP.md` §11 に記録される
Acceptance: `kb improve log show <run_id>` が実行記録を表示し、§11 に同じ run_id が記載されていること
Evidence: pending
Status: planned
依存: MS-007
次の作業: improve run の実行（`--real-llm` 経路は外部プロキシ依存）と §11 への記載

## MS-009: 手順の自己完結化と CI smoke（GOAL.md 完了基準 7）

Outcome: 一連の手順が `bin/self-dogfood.sh` にまとまり、CI で `--smoke` モード（LLM 経路 skip）が走る
Acceptance: `bash bin/self-dogfood.sh --smoke` が終了コード 0 であること。CI ワークフローに smoke 実行ステップが存在すること
Evidence: pending
Status: planned
依存: MS-003（smoke は LLM 経路 skip のため先行着手可）。完走確認は MS-008 後
次の作業: スクリプト新設と `.github/workflows/tests.yml` へのステップ追加

## MS-010: 2 周目 dogfooding による継続改善の証明（GOAL.md「標的達成後」）

Outcome: 1 周目で採用されたモデルをベースにさらに fine-tune し、2 周連続で `concept_jaccard_mean` 改善を e2e 証明する
Acceptance: 2 周目の evaluate レポートと improve ログ（run_id 2 件）で指標が連続改善していることを確認できること
Evidence: pending
Status: planned
依存: MS-008, MS-009（1 周目の完走）
次の作業: 1 周目完走後に 2 周目の計画へ分解する

## MS-011: corpus 拡大（GOAL.md「標的達成後」）

Outcome: MEMO.txt / 作業ログ / PR description / issue 内容を corpus に取り込み、`kb sft` のデータ量を増やす
Acceptance: 追加ソースを含む corpus で `kb sft` が成功し、ペア数が増加していること
Evidence: pending
Status: planned
依存: 着手条件は GOAL.md のとおり「corpus が質・量ともに不足してきた時」。技術的には MS-003 のスクリプト拡張
次の作業: 着手条件の成立を観測した時点で範囲を定義する

## MS-012: 規模化（16 shard 分割 / 30 万文書・5 GB）（GOAL.md「標的達成後」旧 Phase 8）

Outcome: 大規模 corpus でも検索・グラフ再生成が破綻しない
Acceptance: 16 shard 構成での load / search / rebuild が合格すること（具体的閾値は着手時に定義）
Evidence: pending
Status: planned
依存: 着手条件は「ユーザー規模が要件を満たしたら（当面 jinno 個人の運用では来ない）」
次の作業: 着手条件の成立を待つ（着手時点で分解する）

## MS-013: Web UI 刷新（GOAL.md「標的達成後」）

Outcome: 検索・仮想ビュー・詳細表示・関係可視化を行えるローカル Web UI が dogfooding の iteration 履歴を追える形で提供される
Acceptance: UI から検索・グラフ表示ができ、既存 CLI と同じデータを参照すること（具体的受入は着手時に定義）
Evidence: pending
Status: planned
依存: 着手条件は「CLI ログで dogfooding の iteration 履歴を追うのが辛くなった時」。新機能は GOVERNANCE.md のとおり計画経由でのみ追加可
次の作業: 着手条件の成立を待つ（着手時点で分解する）
