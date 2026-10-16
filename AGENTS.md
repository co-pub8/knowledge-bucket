# AGENTS.md — knowledge-bucket

> このファイルは **tas-autopilot** が kind=`product`（product）向けに自動生成した**運用規約の種**です。
> 憲法・存在意義（`SYSTEM_CONSTITUTION.md` / `PURPOSE.md`）の**下位**。矛盾時は上位が優先され、本ファイルが修正されます。
> 生成後は自由に編集してください（**再生成は行われません** — AGENTS.md が存在すれば上書きしません）。
> 生成元: `tas_autopilot/templates/agents_md/product.md.j2`

優先順位: `SYSTEM_CONSTITUTION.md` > `PURPOSE.md` > `adr/ADR-*.md` > `AGENTS.md`。

---

## §1 最優先ルール —— 着手した作業は最後まで `main` まで届ける

作業ツリーと index は**共有資源**です。バックグラウンドの driver / make-run / subagent が**同時に commit し得る**前提で動きます。

1. **即 commit**。verify-done したら同ターンで commit。「path 指示を待つ」＝「放棄」。
2. **path 隔離 add**。`git add <自作業ファイル>` のみ。`git add -A` / `git add .` は**禁止**（他エージェントの in-flight 作業を巻き込む）。
3. **同ターン push**。commit → `git push` まで1ターンで完結。未 push の local commit は「届いていない」。
4. **「完了」の定義** = 検証緑 **かつ** `main` 反映済み。「実装したが commit していない」は**未完了**。

### sweep（`make-run`）の実態 —— 未 commit 放置は吸収される

バックグラウンドの `make-run` が未 commit 残差を定期的に一括回収します（例: `chore(make-run): commit N remaining change(s)`）。汎用 catch-all メッセージで**自作業と無関係のファイルも混載**され得ます。未 commit 放置 → 巻き込まれ → driver が上に commit を積む → 履歴書換不可、を防ぐため、**自分が手を入れたものは例外なく即 commit して main まで**。

---

## §2 フルオート同時開発環境の実態と協調

- **driver**: `goaldev` がゴールを選択・駆動し、`docs/GOAL.md` を更新します。
- **sweep**: `make-run` が未 commit 残差を回収（§1）。
- **subagent**: 個別 feature を担う実装エージェントが `subagent-<Role>-*` ブランチで稼働します。

### 協調エチケット

- **driver の live 管理ドキュメントを直接編集しない**（`docs/GOAL.md` / `docs/GOAL_PLAN.md` / `docs/MEMO.txt` は driver がサイクル中に書き換えます）。意思表示は signal 経由。
- **mid-edit 変更の再検出**。編集中にファイルが他エージェントに変更されたら、commit 直前に `git diff` / `git status` で検出。Edit が "file modified mid-edit" で失敗したら**再 Read してから再適用**（古い内容で上書きしない）。
- **役割分担**。並行 dev エージェントが個別 feature 実装を担い、あなたは全体計画・アーキテクチャ・横断修正・文書を担います。**自分が手を入れたものは例外なく main まで**。
- **driver 稼働ブランチから `checkout` で退避しない**。退避が必要なら `git worktree` で隔離。

---

## §3 検証ゲート

CI の有無・実コマンドは `README.md` / `Makefile` で確認してください（リポ固有）。標準的なゲート:

```bash
make test          # テスト本体（リポの実コマンドを README で確認）
make lint          # 静的解析（実コマンドを確認）
```

### 検証規律

- **e2e と lint/test は並行しない**（ブラウザ/プロセスが CPU 枯渇し timeout flake）。順次・分離。
- **全量回帰は serial**（`--workers=1` 相当）。
- **exit code を信じない**。"completed (exit code 0)" が実出力と乖離することがあります。**出力を必ず読み**、passed/failed 件数を確認。
- **fresh HEAD で再検証**。final review は commit 時の「緑」主張を現 invocation で独立再実行して裏取る。

---

## §4 runtime vs seed（何を commit するか）

`.gitignore` が runtime artifact を commit 対象から除外します。原則: **生成された構造情報・ソース・seed 設定は commit、実行ごとに変わる runtime 出力は commit しない**。詳細は `.gitignore` の tas-autopilot repo-standard 管理ブロックを参照（repo-standard 機能が維持）。

---

## §5 commit 規約

**Conventional Commits + scope**。実測の scope は `git log --oneline -20` で確認してください。1 commit = 1 關心事。

---

## §6 既知の落とし穴（リポ固有・追記せよ）

- この節は**空欄の種**です。リポジトリで実際に踏んだ gotcha（環境・依存・実行時の罠）を追記してください。
- `git add -A` 禁止（§1）。runtime artifact や他エージェントの in-flight を巻き込む。
- driver 管理ファイルを直接編集しない（§2）。

---

## §7 報告

- **日本語で**報告する。
- 完了基準を明示: 「何を変更したか・検証結果（件数）・`main` 反映状況・残課題」。
- 「実装したが未 commit」「push していない」は**未完了**として報告しない（§1）。
