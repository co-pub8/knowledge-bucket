# Git Knowledge Bucket — Goal Document

設計の詳細は [DESIGN.md](DESIGN.md) を参照。
この文書は「今、何を達成しようとしているか」だけを記す。達成済みの内容は git ログにある。

---

## ミッション

kb-tools は **自分の corpus で fine-tune したモデルで自分の分析品質を改善する** 自己強化型ナレッジ管理システム。

ユーザーは文書を inbox に置く。kb が SFT データを生成し、fine-tune を回し、ベースラインと品質を計測し、改善が見られれば採用する — を自動で繰り返す。人が週末に `kb improve` を一回叩くだけで、月曜には分析品質と検索精度が上がっている状態を目指す。

---

## 現在の標的 — kb が kb を改善する

**目標**: `kb improve` 一発で「baseline → 評価 → fine-tune → 評価 → 改善判定 → 採用 or 中断」のループが回る。改善が見えなくなったら自動で止まる。

### 完了基準

1. `kb improve --iterations N [--target-metric concept_jaccard_mean|judge_score_mean] [--tolerance T] [--baseline B]` が動作する
2. 各イテレーションは `kb evaluate` 相当の計測を走らせ、目標指標が改善したら `kb models add` で採用、しきい値を下回ったら前ラウンドの最良を採用
3. 連続 K イテレーション改善なし、またはメトリクスが前ラウンド最良を下回ったら自動中断する
4. 全ラウンドの状態（計測値・採用モデル・abort 理由）が `.kb/improve/<run_id>/` に永続化され、`kb improve log` で一覧できる
5. e2e テスト: モック call_agent で 3 イテレーションのうち少なくとも 1 回は概念 Jaccard または judge スコアが改善することを保証
6. `docs/FEEDBACK_LOOP.md` の "Automating the loop" 章に、手順・abort 条件・コスト注意・撤退基準を追記
7. README に「`kb improve` で実 corpus の分析が改善した」短い Example を 1 本掲載

### 範囲外 (今はやらない)

- fine-tune バックエンドの自動呼び出し。`kb finetune submit` までの記録で止め、実際の学習はユーザーか外部ツールに委譲
- Web UI / マルチバケット横断のオーケストレーション
- LLM コストの自動最適化（abort 条件で十分）

---

## 標的達成後

| 次 | 内容 | 着手条件 |
|---|---|---|
| **配布・採用拡大** | PyPI 公開、blog、demo。`kb improve` の Example で外向きに展開 | 上の 7 項目が達成されてから |
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
