# Git Knowledge Bucket — Goal Document

設計の詳細は [DESIGN.md](DESIGN.md) を参照。
この文書は `goal_driven_parallel_dev` の最高優先度ゴール。

---

## 現在の状況

Phase 1〜12完了。512テスト合格、lint clean。
Phase 8は文書数30万件/repo 5GBまで着手しない。

---

## Phase 6: 運用品質と堅牢性 ✅

### 6.1 エラーハンドリング強化 ✅

- [x] `parsers/paper.py`: arXiv API / CrossRef API のネットワークエラー時の graceful handling
- [x] `parsers/repo.py`: `gh api` 失敗時のエラーメッセージ改善
- [x] `parsers/pdf.py`: 破損PDFのハンドリング
- [x] `ingest.py`: 破損Markdownのスキップと警告出力
- [x] `index.py`: SQLiteロック競合時のリトライ

### 6.2 大量インポート最適化 ✅

- [x] `ingest.py` のバッチトランザクション最適化
- [x] `graph.py` のバッチグラフ構築
- [x] `index.py` のbulk insert

### 6.3 インデックスリカバリ ✅

- [x] `kb index --verify` コマンド
- [x] `kb index --repair` コマンド
- [x] stale HEADの自動検出と full rebuild フォールバック

---

## Phase 7: 機能拡張 ✅

### 7.1 動画入力対応 ✅

- [x] `parsers/video.py`: YouTube URLからのメタデータ取得
- [x] `kb add-video <url>` CLIコマンド
- [x] `source_type: video` の追加
- [x] `prompts/analyzer_video.md` の作成

### 7.2 Embedding-based vector search ✅

- [x] `src/kb/embeddings.py`: OpenAI / ローカルモデルのembedding生成
- [x] `kb vectorize --engine embedding` でembeddingベースのベクトルインデックス構築
- [x] `kb search --semantic` でembedding vectorを使った検索（TF-IDFフォールバック付き）
- [x] `.kb/embeddings.npz` 保存

### 7.3 S3 / R2 Rawデータ保存 ✅

- [x] `src/kb/storage.py`: S3互換ストレージへのアップロード
- [x] `kb add --save-raw` でS3/R2に保存、`raw_ref` 記録
- [x] `kb raw <doc_id>` でrawデータの取得・表示

---

## Phase 8: 大規模化（着手条件: 30万文書 / repo 5GB）

> 以下は文書数が30万件を超えるか、repo sizeが5GBを超えるまで着手しない。

- [ ] IDハッシュによる16 shard repo分割
- [ ] バッチ再分析パイプライン（既存文書の再分析を一括実行）
- [ ] 外部ツール連携（Obsidianプラグイン、モバイル入力UI）

---

## Phase 10: ツールとデータの分離 ✅

現在の `knowledge-bucket/` はツール（`src/kb/`）とデータ（`records/`、`config/`）が同一リポジトリにある。これを分離し、ツールをpip install可能なパッケージにする。

### 10.1 プロンプトのパッケージ内包 ✅

- [x] `prompts/` を `src/kb/prompts/` に移動し、パッケージデータとして配布可能にする
- [x] `pyproject.toml` に `[tool.setuptools.package-data]` で `prompts/*.md` を含める
- [x] `analyzer.py` の `_PROMPTS_DIR` を `importlib.resources` ベースに変更（pip install先でも動くように）
- [x] テスト: `pip install .` → 別ディレクトリで `kb init /tmp/test-kb && kb analyze` がプロンプトを読み込めること

**完了基準**: `pip install .` 後に `src/` リポジトリ配下でなく任意のディレクトリからプロンプトがロードできること。

### 10.2 リポジトリの分離 ✅

**ツールリポジトリ** `knowledge-bucket/`（本リポジトリ）:

```text
knowledge-bucket/           # pip install可能なCLIパッケージ
  pyproject.toml
  README.md
  src/kb/
    __init__.py
    cli.py
    core.py
    index.py
    ingest.py
    graph.py
    related.py
    dedup.py
    health.py
    analyzer.py
    vectors.py
    embeddings.py
    storage.py
    export.py
    concepts.py
    sync.py
    web.py
    prompts/                # パッケージにバンドル
      analyzer_base.md
      analyzer_web.md
      analyzer_paper.md
      analyzer_repo.md
      analyzer_pdf.md
      analyzer_memo.md
      analyzer_video.md
    parsers/
      paper.py
      pdf.py
      repo.py
      video.py
  tests/
  docs/
    DESIGN.md
    GOAL.md
```

**データリポジトリ**（ユーザーが任意の場所に `kb init` で作成）:

```text
my-knowledge/               # ユーザーのナレッジデータ（Git管理）
  config/
    kb.yml
    aliases.yml
    stop_concepts.yml
    taxonomy.yml
  records/
    doc/
      ab/cd/01K2Z9....md
    concept/
      retrieval-augmented-generation.md
  inbox/
  .kb/                      # Git管理外
    index.db
    vectors.npz
    embeddings.npz
    exports/
    raw/
```

- [x] 現在の `knowledge-bucket/` から `records/`、`config/`、`inbox/`、`.kb/` を削除（`.gitignore` は残す）
- [x] `knowledge-bucket/` の `kb init .` はツール開発用テストデータとしてのみ使用
- [x] ユーザーは別ディレクトリで `kb init ~/my-knowledge` → そこで日常運用
- [x] `.gitignore` に `records/`、`config/`、`inbox/`、`.kb/` を追加（ツールリポジトリ側）

**完了基準**: `pip install -e .` 後、別ディレクトリで `kb init` → `kb add` → `kb search` が完動すること。ツールリポジトリにユーザーデータが混入しないこと。

### 10.3 pyproject.toml の配布設定 ✅

- [x] `name = "kb-tools"` にリネーム（`knowledge-bucket` はリポジトリ名として残す）
- [x] `version` を適切に管理（初期リリース `0.1.0`）
- [x] `[tool.setuptools.package-data]` で `kb/prompts/*.md` を含める
- [x] README.md にインストール方法と使い方を追記（`pip install` → `kb init` → `kb add` の流れ）

**完了基準**: 新しい環境で `pip install git+https://github.com/user/knowledge-bucket.git` → `kb init ~/kb` → `kb add --title "test" --content "hello"` が動くこと。

### 10.4 テストの分離対応 ✅

- [x] テストの `kb_root()` フィクスチャが一時ディレクトリを使うことを確認（既存テストがツールリポジトリ内のデータに依存しないこと）
- [x] `prompts/` の移動に伴うテストパス修正
- [x] `pip install .` 後のスモークテスト追加（`tests/test_install.py`）

**完了基準**: `pip install .` → 別ディレクトリでテストスイートが全件合格すること。

---

## Phase 9: 実運用と統合品質 ✅

### 9.1 Web UIの実用性向上 ✅

- [x] 検索結果のページネーション: 1ページ20件、`/recent?page=2` でページ遷移。200件登録時に全ページが正常表示されること
- [x] 文書一覧のソート: `?sort=date|importance|type` パラメータで並び替え。各ソートのテスト追加
- [x] 文書編集機能: `/doc/<id>/edit` ページでメモ・評価を追記しPOSTでfront matter更新。テストで編集→保存→再表示を確認
- [x] ダークモード: `prefers-color-scheme: media` またはトグルボタンで切替。CSS変数で色管理

**完了基準**: `kb serve` 起動後、200件ダミー文書を登録して全ページ（検索、一覧、詳細、編集）が正常動作すること。各機能のテスト追加。

### 9.2 AI分析パイプライン統合 ✅

- [x] `kb ingest --analyze` でLLM APIを呼び出し、分析結果（concepts, importance, summary）をfront matterに書き込む。`src/kb/analyzer.py` の `parse_analysis_response` を利用
- [x] APIキーは環境変数 `KB_LLM_API_KEY` から読み込み。未設定時は警告してスキップ
- [x] レート制限対応: API呼び出し間に0.5sスリープ、429エラー時にexponential backoff（最大3リトライ）
- [x] 分析失敗時はプレーンなfront matterで保存。`kb analyze --retry-failed` で `analysis.confidence` がない文書だけ再分析

**完了基準**: `KB_LLM_API_KEY=xxx kb ingest --analyze` でAI分析済みレコードが生成され、front matterにconcepts/summary/importanceが記録されること。APIモックテストで検証。

### 9.3 設計書の整合性更新 ✅

- [x] `docs/DESIGN.md` にvideo parser、embeddings、storage、index verify/repair、content_hashの記載があること
- [x] `docs/DESIGN.md` のCLI一覧（section 15）に全コマンド（add-video, raw, index --verify/--repair含む）が列挙されていること
- [x] README.mdのCLIコマンド一覧が現在の実装と一致していること

**完了基準**: `grep -c "kb add-video\|kb raw\|index --verify\|embeddings.py\|storage.py\|parsers/video.py" docs/DESIGN.md` で全項目がヒットすること。

---

## Phase 11: 公開・配布準備 ✅

### 11.1 CI/CD ✅

- [x] `.github/workflows/tests.yml`: push/PR時に `pytest` と `ruff check` を実行。Python 3.11, 3.12, 3.13でmatrix

**完了基準**: PR作成時にGitHub Actionsが自動実行され、テスト・lintが通ること。

### 11.2 プロジェクトメタデータ ✅

- [x] `LICENSE` ファイル追加（MIT）
- [x] `pyproject.toml` に `license`, `authors`, `classifiers`, `urls` 追記
- [x] README.md のGitHub URLを `nobu007/knowledge-bucket` に修正
- [x] `kb --version` コマンド追加（`click.version_option`）

**完了基準**: `pyproject.toml` にlicense・authorが設定され、`kb --version` がバージョン番号を返すこと。

### 11.3 未プッシュコミットの解消

- [x] 現在のmainブランチのコミットを `git push` でoriginに反映

**完了基準**: `git status` が `Your branch is up to date with 'origin/main'` であること。

---

## Phase 12: AI分析刷新・SFT生成基盤・自動運用 ✅

Phase 11 公開後、knowledge bucket の corpus を自社ドメイン特化 LLM の SFT 原料にするため、分析・embedding・生成の各層を強化した。OpenAI 依存を排して [ai-hub-agent-proxy](https://github.com/nobu007/ai-hub_agent_proxy) 経由に統一し、bge-m3 ローカル embedding を既定化、`kb generate` / `kb sft` で SFT データを生成、`kb watch` で運用を自動化した。

### 12.1 AI分析パイプライン刷新 (ai-hub-agent-proxy 統合) ✅

OpenAI API の直接呼び出しを撤廃し、ローカル CLI の [ai-hub-agent-proxy](https://github.com/nobu007/ai-hub_agent_proxy) 経由に統一。Claude Code プライマリ / OpenCode フォールバックのプロトコルで動作する。

- [x] `src/kb/analyzer.py` を ai-hub-agent-proxy 呼び出しに置換。`KB_AGENT_PROXY` 環境変数対応、未設定時は `~/ai-hub_agent_proxy/dist/cli.js` を自動検出
- [x] 並列分析ワーカー: `-w/--workers N` で proxy subprocess を N 並列起動し、バルク分析の wall-clock を約 N 分の 1 に短縮
- [x] front matter 解析の堅牢化: 壊れた YAML / 必須フィールド欠損を許容し、`analysis.confidence` 不在の文書だけ `--retry-failed` で再分析
- [x] analyze 後の自動 re-index: 概念付与後に FTS index を即時同期
- [x] `get_api_key()` を `KB_LLM_API_KEY` → `KB_AGENT_PROXY` 存在チェックに変更

**完了基準**: `KB_AGENT_PROXY=... kb ingest --analyze -w 4` で proxy 経由で並列分析され、front matter に concepts / summary / importance / confidence が書き込まれること。

### 12.2 ローカル embedding によるセマンティック検索 ✅

Embedding ベースの意味検索をクラウド API 依存から脱却し、sentence-transformers (bge-m3) を既定エンジン化。

- [x] `src/kb/embeddings.py`: `--engine embedding` で `BAAI/bge-m3` を使用（多言語 JA/EN・8192 トークン）。環境変数 `KB_EMBED_MODEL` でモデル切替可
- [x] query / doc embedding の整合性: 同じ `normalize_embeddings` 設定で生成、トランケーション長はモデル max_seq_length に揃える
- [x] `SentenceTransformerEngine` のシングルトンキャッシュ化: 重複ロードを排除し、起動コストを 1 回に圧縮
- [x] 警告抑制: progress bar / モデル重複ロード等の noisy warnings を整理
- [x] フォールバック: `--engine tfidf`（既定・デフォルト無依存） / `--engine openai`（旧 API） / `--engine local`（hash）

**完了基準**: `pip install -e ".[embedding]"` → `kb vectorize --engine embedding` → `kb search "query" --semantic` がローカルだけで完結し、外部 API キーを要求しないこと。

### 12.3 データ品質保証 ✅

corpus のスケールに伴う重複・破損・分析漏れを体系的に検知・防止する仕組みを整備。

- [x] `kb doctor` 品質チェックコマンド: QC1 物理配置 / QC2 front matter / QC3 重複 / QC4 分析カバレッジ / QC5 整合性。問題があれば非 0 終了
- [x] `add-*` コマンドの `source_key` ベース dedup: 同一ソース URL/参照の二重取り込みを `kb add` / `kb add-paper` / `kb add-pdf` / `kb add-repo` / `kb add-video` 横断で防止
- [x] 全 `add-*` コマンドに `content_hash` 付与: 同一本文の dedup と差分検知の基盤
- [x] front matter の concept / tag ラベル quoting: 値に `:` や `#` を含むラベルが YAML 解析で壊れないように保護
- [x] `tests/test_generate.py` をはじめとするテスト群で各 QC を担保

**完了基準**: `kb doctor` が `kb init` した直後の新規 bucket で 0 を返し、意図的に重複 / 破損 / 未分析の doc を混ぜた bucket では非 0 を返すこと。

### 12.4 パフォーマンス最適化 ✅

corpus スケール時のボトルネックを解消。

- [x] `build_concept_edges` の O(K²) SQL 自己結合を Python co-occurrence map に置換。概念数 K に対し概念ペア全列挙を廃し、`{concept_id: set(doc_ids)}` の単一パス + 共有 doc 数で重み付け。`df in [2, hub_threshold]` / `is_stop=0` / `min_cooccurrence` フィルタ・top_k-per-concept・双方向挿入・edges スキーマ・int 返り値をすべて維持
- [x] インクリメンタルグラフビルド: `kb graph build` が git diff で差分 doc のみ処理
- [x] N+1 クエリ問題の解消: graph / health / concepts 経路でバッチ取得に統一
- [x] analyzer hardening: 壊れた front matter / 空本文 / 巨大 front matter の境界ケースに対する防御
- [x] SQLite インデックス追加、bulk insert 化

**完了基準**: 1 万 doc の corpus で `kb graph build` が旧版より 1 桁以上速く完了し、生成される concept_edges の本数・重み・フィルタが旧版と一致すること（回帰テストで担保）。

### 12.5 自動メンテナンス ✅

常時運用のための「放っておいても壊れない」経路を整備。

- [x] `add` 後の即時インデックス: `kb add` 実行時にその場で `sync_index` を呼び、次の `kb search` で必ずヒットすることを保証
- [x] `kb watch`: 一定間隔（既定 300s）で `ingest → sync_index → build_graph (incremental) → build_embeddings` を回すフォアグラウンドデーモン。`--once` で cron からの 1 ショット実行、`--analyze` で取り込み後の並列分析もサイクルに組込み可能

**完了基準**: 別ターミナルから `echo ... > .kb/inbox/foo.md` → 次の `kb watch` サイクル（または `--once` 1 回）で grep 可能な doc として登録され、FTS index / 概念グラフ / embedding に反映されること。

### 12.6 ドメイン特化 SFT データ生成 ✅

knowledge bucket の corpus から SFT（Supervised Fine-Tuning）用の instruction-output ペアを生成する仕組み。`kb sft` を推奨エントリポイントとし、`kb generate` を細かい制御用のプリミティブとして位置づける。

- [x] `src/kb/generate.py`: `generate()` プリミティブ（単一 JSONL 出力）と `build_sft()`（dataset 全体ビルド）
- [x] `src/kb/prompts/training_data.md`: 「本文の事実に基づく・憶測禁止・未記載は正直に」を指示するプロンプト
- [x] `kb generate`: 単一ドメイン向け JSONL 出力。`--concept` / `--type`（AND 条件）で doc 絞り込み、`--pairs`（doc 1 件あたりの生成ペア数）、`--format openai|alpaca`、`--limit`、`-o`
- [x] `kb sft`: 全 doc 対応のワンコマンド。生成 → 全体 dedup → 決定的シャッフル → train/val split → 統計出力を 1 ステップで実行。`--pairs` / `--split` / `--seed` / `--concept` / `--type` / `--limit` / `--format` / `--output-dir` / `--no-resume`
- [x] resume 機構: `manifest.jsonl` に処理済み doc を記録し、再実行で skip。`all.jsonl`（真実・追記型）から `train.jsonl` / `val.jsonl` を毎回再導出（空で上書きしない）
- [x] 出力: `.kb/training/sft-dataset/{all,train,val}.jsonl` + `stats.json` + `manifest.jsonl`
- [x] 品質保証: grounding（本文事実ベース）/ 難易度分散（basic / intermediate / advanced を各 doc で混在）/ 横断 dedup（指示文の sha1 下位 12 桁）/ 空ペア破棄 / fenced-JSON 耐性
- [x] `docs/TRAINING_DATA_GENERATION.md` プレイブック: 前提（kb doctor / kb health）、ドメイン選定基準（df ≥ 3 推奨・狭すぎ広すぎ回避）、実行手順、検証スクリプト、ワークフロー、既知の制限、corpus への追加方法
- [x] モデル選択ガイダンス: 生成は品質最優先のため **Sonnet 級以上（既定）を必ず使用**。haiku 等の軽量モデルはスモークテスト専用。モデル切替は環境変数 `AIHUB_AGENT_PROXY_LLM_MODEL`（`-- --model` は proxy が prompt に混入するため使用不可）

**完了基準**: 任意の分析済み corpus に対し `kb sft --pairs 5 --split 0.9` が `all.jsonl` / `train.jsonl` / `val.jsonl` / `stats.json` を生成し、再実行で処理済み doc が skip され、`train` / `val` 件数が `all` 件の分割比と一致すること。

### 12.7 CLI ドキュメント同期 ✅

実装とドキュメントの乖離をゼロにする。

- [x] `README.md` の CLI コマンド一覧を実装と同期
- [x] `docs/DESIGN.md` の section 15 CLI 一覧に全コマンド（`kb add-video` / `kb raw` / `kb index --verify/--repair` / `kb doctor` / `kb watch` / `kb sft` / `kb generate` ほか）を列挙
- [x] `docs/TRAINING_DATA_GENERATION.md` の playbook で `kb sft` を推奨パスとして明示

**完了基準**: `grep -E "kb (add-video|raw|doctor|watch|sft|generate|index --verify|index --repair)" README.md docs/DESIGN.md` が全ヒットすること。
