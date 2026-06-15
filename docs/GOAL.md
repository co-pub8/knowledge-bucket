# Git Knowledge Bucket — Goal Document

設計の詳細は [DESIGN.md](DESIGN.md) を参照。
この文書は「今、何を達成しようとしているか」だけを記す。達成済みの内容は git ログにある。

---

## ミッション

kb-tools は **自分の corpus で fine-tune したモデルで自分の分析品質を改善する** 自己強化型ナレッジ管理システム。

ユーザーは文書を inbox に置く。kb が SFT データを生成し、fine-tune を回し、ベースラインと品質を計測し、改善が見られれば採用する — を自動で繰り返す。人が週末に `kb improve` を一回叩くだけで、月曜には分析品質と検索精度が上がっている状態を目指す。

---

## 現在の標的 — `git clone` から 5 分でフィードバックループを体感できる状態

**目標**: 新しいユーザーがリポジトリを clone して README のコマンドを順番に叩くと、5 分以内に「kb sft → kb evaluate → kb improve」が自分の目で動くことを確認できる。デモは実在のドメイン（例: ある OSS ライブラリのドキュメント）を使い、`examples/demo-bucket/` に同梱する。

### 完了基準

1. `examples/demo-bucket/` に **実在ドメイン**（具体的なライブラリ・記事・論文）のサンプル doc が **10 件以上** 含まれる
2. `examples/demo-bucket/.kb/index.db` が pre-built で、`git clone` 直後から `kb search` が動く
3. `examples/demo.sh` が **1 コマンドで**「ingest → analyze → sft → evaluate → improve log」まで通しで実行できる（LLM 部分はモック可）
4. `examples/README.md` に「何のデモか」「各ファイルの役割」「再現手順」が簡潔にまとまっている
5. README.md の先頭に "Quick Demo" セクションがあり、`git clone && ./examples/demo.sh` で体験できる
6. CI (`.github/workflows/tests.yml`) で `examples/demo.sh --smoke` を実行し、demo が壊れていないことを毎日確認する
7. `docs/FEEDBACK_LOOP.md` §11 "Dogfooding notes" に、この demo を最初の事例としてリンクを貼る

### 範囲外 (今はやらない)

- PyPI 公開・blog・告知。ユーザーに届ける経路は Phase 15 以降で別途
- 実 fine-tune バックエンドの統合。demo は LLM をモックしてよい（実 LLM は任意の `--real-llm` フラグでのオプション）
- 動画・スクリーンキャスト・多言語ドキュメント

---

## 標的達成後

| 次 | 内容 | 着手条件 |
|---|---|---|
| **配布・採用拡大 (旧 Phase 15 後半)** | PyPI 公開、blog、告知。demo を landing page に貼る | demo が動く状態になってから |
| **規模化 (旧 Phase 8)** | 16 shard 分割、30 万文書 / 5 GB 対応 | ユーザー規模が要件を満たしたら |
| **Web UI 刷新** | Next.js / グラフ可視化 | CLI で詰まる具体的なユースケースが出てから |

---

## 設計原則

- **計測可能性 > 自動化**。改善が数字で見えない自動化は作らない
- **バックエンドの選択はユーザーに委ねる**。transformers / OpenAI / Ollama のどれを使うかはユーザーが決める
- **kb 自体のドッグフーディングを最優先**。新機能は kb 自身の corpus で先に動かす
- **後方互換性を壊す変更は明示**。メジャーバージョンアップと deprecation 期間を設ける
- **スコープを絞る**。完了基準 1 個でも 80% 達成ならリリース。100% を目指して 0 を出すより、60% を 5 回出す

---

## この文書の使い方

- マイルストーン完了時: 「完了基準」のチェックを更新する
- スコープ変更時: 「範囲外」と「標的達成後」を更新する
- 1 ヶ月に 1 回: 「現在の標的」をそのまま維持するか次に進めるか判断する
- 達成した内容はここに書かない。git log と `docs/FEEDBACK_LOOP.md` に書く
