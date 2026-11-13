# CLAUDE.md

Claude Code / AI エージェントへの入口。毎セッション最初に読む前提。

## 最上位ルール

`docs/GOVERNANCE.md` を必ず最初に読む。GOVERNANCE.md はこのリポジトリの最高位ルール。
GOAL.md や個別の指示より優先する。**外部共有禁止・PyPI 公開禁止・計画経由のみ機能追加**。
判断に迷ったら GOVERNANCE.md を読み直す。

## このリポジトリの性格

- 名称: kb-tools
- 性格: **完全プライベート**。jinno のみがアクセスする
- 目的: 自己強化型ナレッジ管理システムの開発（詳細は `docs/GOAL.md`）
- 開発スタイル: 1 つの論理単位ずつ小さなコミット、テスト 100% green、lint clean
- 言語: 日本語のコメント / ドキュメントを許容。コード（identifier）は英語

## やってはいけないこと

- リポジトリの内容を **外部に共有する**（chat / blog / SNS / issue / PR / 別リポ）
- PyPI / コンテナレジストリ / docs サイト等に **公開する**
- 外部公開用の **release / publish ワークフロー**を書く
- `docs/GOAL.md` の「現在の標的」に書かれていない **新機能を追加する**
- 「現状ベース」の思考でドキュメントを書く（GOVERNANCE.md §1-2 を参照）

## やって良いこと

- jinno が明示的に指示した作業
- 既存コードの修正 / リファクタ / lint 修正
- 既存テストの追加 / 修正
- 内部ドキュメントの改善（GOAL.md / FEEDBACK_LOOP.md / README 等）
- ガバナンスに違反しない範囲での demo / example の追加

## コミット粒度

- 1 コミット = 1 つの論理的変更
- フォーマット: `<type>(<scope>): <description>`
- 詳細は既存ログ（`git log --oneline`）を参照

## テスト

- `python -m pytest tests/ -q` で全テスト
- `ruff check src/ tests/` で lint
- どちらも green であること

## 関連ファイル

- `docs/GOVERNANCE.md` — 最上位ルール
- `docs/GOAL.md` — 現在の標的とミッション
- `ORDER.md` — 長期計画の正本（到達点・現状との差・優先順・出口条件）
- `docs/MILESTONES.md` — マイルストーンの実行用分解（ORDER.md / GOAL.md を参照）
- `REPO_METADATA.json` — 計画メタデータの投影（schema_version=1）
- `docs/FEEDBACK_LOOP.md` — フィードバックループのプレイブック
- `docs/MEMO.txt` — セッション横断の共有ノート
- `docs/TRAINING_DATA_GENERATION.md` — SFT データ生成のプレイブック

## このファイルの位置づけ

GOVERNANCE.md の **AI エージェント向け要約**。GOVERNANCE.md が正。
本ファイルと GOVERNANCE.md が矛盾する場合は GOVERNANCE.md を優先。
本ファイルは GOVERNANCE.md を毎セッション確実にロードさせるための hook。
