# Git Knowledge Bucket — Goal Document

設計の詳細は [DESIGN.md](DESIGN.md) を参照。
この文書は「今、何を達成しようとしているか」だけを記す。達成済みの内容は git ログにある。

---

## ミッション

kb-tools は **自分の corpus で fine-tune したモデルで自分の分析品質を改善する** 自己強化型ナレッジ管理システム。

ユーザーは文書を inbox に置く。kb が SFT データを生成し、fine-tune を回し、ベースラインと品質を計測し、改善が見られれば採用する — を自動で繰り返す。人が週末に `kb improve` を一回叩くだけで、月曜には分析品質と検索精度が上がっている状態を目指す。

---

## 現在の標的 — kb-tools 自身の corpus でフィードバックループを完走させる

**目標**: 自分のリポジトリ（`README.md` / `docs/*.md` / `DESIGN.md` / `FEEDBACK_LOOP.md` / `GOAL.md` / `CLAUDE.md` 等の合計数十件）を 1 つのナレッジ bucket として `kb init` し、`kb sft` → 外部で fine-tune → `kb models add` → `kb evaluate` → `kb improve --real-llm` を **1 サイクル完走** させる。結果（採用されたモデル、metrics、`run_id`、abort したか）を `docs/FEEDBACK_LOOP.md` §11 に貼って、`kb 自体のドッグフーディングを最優先` の原則を **実績ベース** で証明する。

### 完了基準

1. kb-tools 自身の md / txt 系ファイルを列挙して `~/kb-self-corpus` に `kb init` する `bin/build-self-corpus.sh` を作る（idempotent、差分のみ ingest）
2. 同 corpus に対して `kb analyze --retry-failed -w 4` が完走し、QC4 (analysis coverage) が 100% になる
3. `kb sft --pairs 5 --split 0.9` で N 件の SFT ペアを生成
4. **外部で fine-tune** したモデルを `kb models add kb-self-v1 --base-model ... --from-job <job_id>` で登録
5. `kb evaluate --baseline <現 active> --candidate kb-self-v1 --limit 50` を実行し、4 指標のレポートを `.kb/models/eval/kb-self-v1.json` に保存
6. `kb improve run -n 3 -m concept_jaccard_mean` を実行し、ログを `docs/FEEDBACK_LOOP.md` §11 に **run_id 付きで** 貼る
7. 上記一連の手順を `bin/self-dogfood.sh` にまとめて、CI で `--smoke` モード（LLM 経路 skip）が走ることを確認

### 範囲外 (今はやらない)

- **PyPI 公開・外部配布**。完全プライベート運用のため（`docs/GOVERNANCE.md` §1-3 参照）
- 新規 parser / 新規 source_type の追加。corpus 範囲は既存の README / docs だけで十分
- 複数 corpus の並列管理。1 リポ = 1 bucket
- `kb serve` (Web UI) 経由の dogfooding 可視化。CLI ログで十分
- 自動 fine-tune。`kb finetune submit` でジョブ記録までで止め、学習は jinno が手元で回す

---

## 設計原則

- **計測可能性 > 自動化**。改善が数字で見えない自動化は作らない
- **バックエンドの選択はユーザーに委ねる**。transformers / OpenAI / Ollama のどれを使うかはユーザーが決める
- **kb 自体のドッグフーディングを最優先**。新機能は kb 自身の corpus で先に動かす
- **後方互換性を壊す変更は明示**。メジャーバージョンアップと deprecation 期間を設ける
- **スコープを絞る**。完了基準 1 個でも 80% 達成ならリリース。100% を目指して 0 を出すより、60% を 5 回出す

---

## 標的達成後

| 次 | 内容 | 着手条件 |
|---|---|---|
| **2 周目の dogfooding** | 1 周目で採用されたモデルをベースに fine-tune をもう一段回し、2 周連続で `concept_jaccard_mean` が改善することを e2e で証明する | 1 周目が完走してから |
| **corpus 拡大** | 開発中に書いた `MEMO.txt` / 作業ログ / PR description / issue 内容も corpus に取り込み、`kb sft` のデータ量を増やす | corpus が今より質・量ともに不足してきた時 |
| **規模化 (旧 Phase 8)** | 16 shard 分割、30 万文書 / 5 GB 対応 | ユーザー規模が要件を満たしたら（当面 jinno 個人の運用では来ない） |
| **Web UI 刷新** | Next.js / グラフ可視化 | CLI ログで dogfooding の iteration 履歴を追うのが辛くなった時 |

---

## この文書の使い方

- マイルストーン完了時: 「完了基準」のチェックを更新する
- スコープ変更時: 「範囲外」と「標的達成後」を更新する
- 1 ヶ月に 1 回: 「現在の標的」をそのまま維持するか次に進めるか判断する
- 達成した内容はここに書かない。git log と `docs/FEEDBACK_LOOP.md` に書く
