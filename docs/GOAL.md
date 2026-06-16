# Git Knowledge Bucket — Goal Document

設計の詳細は [DESIGN.md](DESIGN.md) を参照。
この文書は「今、何を達成しようとしているか」だけを記す。達成済みの内容は git ログにある。

---

## ミッション

kb-tools は **自分の corpus で fine-tune したモデルで自分の分析品質を改善する** 自己強化型ナレッジ管理システム。

ユーザーは文書を inbox に置く。kb が SFT データを生成し、fine-tune を回し、ベースラインと品質を計測し、改善が見られれば採用する — を自動で繰り返す。人が週末に `kb improve` を一回叩くだけで、月曜には分析品質と検索精度が上がっている状態を目指す。

---

## 現在の標的 — `pip install kb-tools` で誰でもインストールできる最初のリリース

**目標**: 新しいユーザーが Python 3.11+ の venv を作り、`pip install kb-tools` だけで kb コマンドが手に入り、`kb init ~/my-knowledge && kb add --title t --content c && kb search t` が 1 分以内に動く。GitHub にリリースタグを打てば PyPI に自動公開され、API キーを手元に置かなくてよい。

### 完了基準

1. `pyproject.toml` が PyPI 公開に必要な全フィールドを備える: `description`, `readme`, `requires-python`, `license`, `authors`, `keywords`, `classifiers`, `urls` (Homepage / Repository / Issues / Changelog)
2. `.github/workflows/release.yml`: `v*.*.*` タグ push で sdist + wheel を build、Trusted Publishing (OIDC) で PyPI に publish。API キーはリポジトリに保存しない
3. Trusted Publishing を PyPI 側で設定 (GitHub Actions からのみ publish 許可)
4. 初回リリースタグ `v0.2.0` を打ち、PyPI 上に `kb-tools` パッケージが出現
5. 空の venv から `pip install kb-tools` が Python 3.11 / 3.12 / 3.13 すべてで成功し、`kb --version` がバージョン番号を返す
6. CI ジョブ `install-smoke`: ビルド済み wheel を別 venv に install → `kb init` → `kb add` → `kb search` の smoke を matrix で毎日実行
7. README.md のインストール手順が `pip install kb-tools` を **最上位** に据え、`pip install git+...` は dev 用の二次オプションに降格

### 範囲外 (今はやらない)

- 複数パッケージ分割 (`kb-tools-core` / `kb-tools-cli` 等)。単一パッケージのまま
- Conda / Homebrew / apt。PyPI のみ
- 自動バージョン bump / release-drafter の細かい自動化。タグは当面手で打つ
- マーケティングサイト / blog 記事 / SNS 告知。それらは「最初のリリース」が手元に出てから別 workstream で
- ユーザーテレメトリ・匿名の利用統計。何も送らない

---

## 標的達成後

| 次 | 内容 | 着手条件 |
|---|---|---|
| **blog / 告知 / PyPI バッジ** | 初回リリースの announcement、ハンドラ、バッジ。`examples/demo-bucket/` を landing に | 上の 7 項目が達成されてから |
| **実 dogfooding** | `kb improve --real-llm` を kb-tools 自身の corpus で走らせ、`docs/FEEDBACK_LOOP.md` §11 に run_id を貼る | PyPI リリースが落ち着いた後 |
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
