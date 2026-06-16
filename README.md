# Git Knowledge Bucket

Web記事、GitHubリポジトリ、論文、メモ、PDF、動画をGitに蓄積し、FTS5検索・概念グラフ・Embeddingベクトル検索で再利用するローカル知識管理システム。

## インストール

このリポジトリは **完全プライベート** で運用しています（[`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) 参照）。
PyPI 公開も `pip install kb-tools` でのインストールもできません。共同開発者は以下から始めます。

```bash
git clone <内部 Git ホスト>/nobu007/knowledge-bucket.git
cd knowledge-bucket

# 開発モード（リポジトリを clone している場合）
pip install -e ".[dev]"

# Embedding ベースのセマンティック検索を使う場合
pip install -e ".[embedding]"
```

インストール後は `kb --version` で確認できます。

```bash
kb --version    # 例: kb, version 0.2.0
```

インストール後は、続けて [Quick Demo](#quick-demo) を試してみてください。

## クイックスタート

```bash
# データ用ディレクトリを初期化
kb init ~/my-knowledge

# 文書を追加
cd ~/my-knowledge
kb add --title "test" --content "hello"

# インデックス構築
kb index --sync

# 検索
kb search "hello"
```

## Quick Demo

A pre-populated demo bucket ships in `examples/demo-bucket/` with 12
sample docs on **vector databases and embeddings**. The script runs the
full feedback loop (ingest → index → analyze → sft → models add →
evaluate → improve) end-to-end:

```bash
git clone https://github.com/nobu007/knowledge-bucket.git
cd knowledge-bucket
pip install -e ".[dev]"
./examples/demo.sh --smoke    # CI mode, no LLM, ~2 seconds
./examples/demo.sh --real-llm # full pipeline (needs KB_AGENT_PROXY)
```

See [`examples/README.md`](examples/README.md) for the step-by-step
walkthrough, the `--help` flag reference, and how to swap in your own
corpus.

## CLIコマンド

### 基本

| コマンド | 説明 |
|---|---|
| `kb init` | ディレクトリ構造と設定ファイルを初期化 |
| `kb add <url-or-text>` | ドキュメントを追加（`--title`, `--source`, `--content`, `--type`, `--concepts`, `--save-raw`） |
| `kb ingest` | inbox内の未処理アイテムを処理（`--analyze` でLLM分析も同時実行） |
| `kb search "<query>"` | FTS5検索（`--limit`, `--semantic` でベクトル検索） |
| `kb show <doc_id>` | 文書メタデータと本文表示（`--full`） |
| `kb related <doc_id>` | 関連文書表示（`--limit`） |
| `kb sync` | Git同期パイプライン（pull → ingest → index → commit → push） |

### インデックス

| コマンド | 説明 |
|---|---|
| `kb index --sync` | 差分インデックス更新 |
| `kb index --rebuild` | 全件インデックス再構築 |
| `kb index --verify` | FTSインデックス整合性チェック |
| `kb index --repair` | 欠損エントリ再構築・ゴミエントリ削除 |
| `kb vectorize` | vector index構築（`--engine tfidf\|embedding\|local\|openai`） |

### 専用入力

| コマンド | 説明 |
|---|---|
| `kb add-paper <arxiv-or-doi>` | 論文をarXiv URL/ID、DOI、またはタイトルで追加 |
| `kb add-pdf <file>` | PDFをテキスト抽出して追加 |
| `kb add-repo <github-url>` | GitHubリポジトリをメタデータ取得して追加 |
| `kb add-video <url>` | YouTube等の動画をメタデータ取得して追加 |

### 分析・グラフ

| コマンド | 説明 |
|---|---|
| `kb analyze` | 文書のLLM分析（`--retry-failed` で未分析文書を再分析、`-w/--workers N` でN並列） |
| `kb graph build` | 概念グラフを構築（`--full` で全件再構築） |
| `kb doctor` | データ品質チェック（非0終了で問題あり） |
| `kb concepts suggest` | concept noteの昇格候補を提案・生成 |
| `kb health` | グラフ品質メトリクス表示（`--json`） |
| `kb concept <concept_id>` | 概念メタデータ・関連文書・共起概念表示 |
| `kb watch` | 自動メンテナンスタイマー（ingest→index→graph→vectors を定期実行。`--interval` 秒、`--once` で1ショット、`--analyze` で並列分析も組込み） |

### エクスポート・ストレージ

| コマンド | 説明 |
|---|---|
| `kb export parquet` | グラフデータをParquetでエクスポート |
| `kb raw <doc_id>` | rawデータの取得・表示（S3/R2/ローカル） |
| `kb collections` | 仮想コレクション一覧表示 |

### 学習データ生成

| コマンド | 説明 |
|---|---|
| `kb generate` | 単一 JSONL 出力。`--concept` / `--type`（AND 条件）で doc 絞り込み、`--pairs`、`--format openai\|alpaca`、`--limit`、`-o` |
| `kb sft` | ワンコマンド SFT データセットビルド（生成→全体 dedup→シャッフル→train/val split→統計、resume 対応）。`--pairs` / `--split` / `--seed` / `--concept` / `--type` / `--limit` / `--format` / `--output-dir` / `--no-resume` |

詳細は [`docs/TRAINING_DATA_GENERATION.md`](docs/TRAINING_DATA_GENERATION.md) を参照。

### 自己改善ループ

| コマンド | 説明 |
|---|---|
| `kb finetune prepare\|submit` | 学習データ変換 (`hf`/`openai`/`alpaca`) とジョブ記録 |
| `kb models add\|list\|show\|use` | モデル登録・一覧・切替 |
| `kb evaluate` | 候補 vs ベースラインで concept Jaccard / F1 / importance KL / judge スコアを計測 |
| `kb improve run` | 自動ループ: 候補を順に評価し、改善したものを active model に昇格。`--iterations` / `--target-metric` / `--tolerance` / `--baseline` / `--candidates` / `--max-misses` / `--limit` |
| `kb improve log\|log list\|log show` | 過去 run の一覧・詳細表示 |

```bash
# 1. SFT データを生成
kb sft --concept retrieval-augmented-generation --pairs 5

# 2. 外部で fine-tune、結果を登録
kb models add kb-rag-v2 --base-model claude-opus-4-7 --backend openai_ft

# 3. kb improve が候補を評価し、改善したものを自動採用
kb improve run -n 3 -m concept_jaccard_mean

# 4. 結果を確認
kb improve log
kb improve log show 01JABCDEFGHJK
```

詳細は [`docs/FEEDBACK_LOOP.md`](docs/FEEDBACK_LOOP.md) を参照。

### Web UI

| コマンド | 説明 |
|---|---|
| `kb serve` | ローカルWeb UI起動（`--host`, `--port`, `--debug`） |

## LLM分析パイプライン

LLM分析は直接のAPI呼び出しではなく、ローカルの [ai-hub-agent-proxy](https://github.com/nobu007/ai-hub_agent_proxy) 経由で実行する（Claude Code プライマリ / OpenCode フォールバック）。proxyは `KB_AGENT_PROXY` 環境変数で指定、未設定時は `~/ai-hub_agent_proxy/dist/cli.js` を自動検出する。

```bash
export KB_AGENT_PROXY=~/ai-hub_agent_proxy/dist/cli.js
kb ingest --analyze -w 4        # インポート時に分析（4並列）
kb analyze --retry-failed -w 4  # 未分析文書を再分析（4並列）
kb doctor                       # 分析カバレッジ等のデータ品質チェック
```

`-w/--workers N` は複数のproxy subprocessを並列起動し、バルク分析のwall-clockを約N分の1に短縮する。

## セマンティック検索（Embedding）

Embeddingベースのセマンティック検索を使うには `[embedding]` extraをインストールする。

```bash
pip install -e ".[embedding]"
kb vectorize --engine embedding         # BAAI/bge-m3 でベクトル化（デフォルト）
kb search "query" --semantic            # embedding indexが優先される
```

モデルは環境変数 `KB_EMBED_MODEL` で変更可能（デフォルト `BAAI/bge-m3`、多言語JA/EN・8192トークン）。他のエンジン: `--engine openai`（OpenAI API）、`--engine local`（sentence-transformers）、`--engine tfidf`（TF-IDF、デフォルト）。

## テスト

```bash
python -m pytest tests/ -v
```
