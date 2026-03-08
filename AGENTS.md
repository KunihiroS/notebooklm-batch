# NotebookLM コンテンツ生成エージェント指示書

このディレクトリでは、NotebookLMを使用してYouTube動画からコンテンツ（Podcast、画像、スライド、動画）を生成します。
README.md に記載の「指示書（YAML）→ バッチ生成 → ローカル保存」の運用を前提とします。

## 前提条件

- `notebooklm-py` が `pipx install "notebooklm-py[browser]"` でインストール済み
- `notebooklm login` で認証済み（`~/.notebooklm/storage_state.json` が存在）
- ログインが未実行、もしくは期限切れの場合、`notebooklm login` を実行し、ユーザーにブラウザ操作を依頼してログインを完了させる。
  - ユーザの操作はブラウザ上での認証手続きとloginコマンドを実行したターミナルのCLI操作。
  - もし `notebooklm login` 実行後、**ターミナルでENTERして保存が完了する前にブラウザを閉じると失敗する**ため、ユーザーには「ログインが終わったらターミナルに戻ってENTERを押すまでブラウザを閉じない」ことを伝える。

### 認証が期限切れしていた場合（環境をクリーンに保つ）

- 依存ツールは `pipx` で入れる（グローバルに `pip` で入れない）
- Playwright の Chromium を `pipx run` で導入する（pipx venv を汚さない）

```bash
pipx install "notebooklm-py[browser]"
pipx run --spec "notebooklm-py[browser]" python -m playwright install chromium
```

## 目的と管理対象

- 指示書: `./instructions/` 配下の YAML
- 生成物: `./files/` 配下（`{safe_title}__{source_hash}` 形式のサブディレクトリ）
- 実行ログ: `./log/` 配下

## バッチ実行の基本

### Step 1: ユーザーからの入力を受け取る

ユーザーは、`./instructions/` に指定フォーマットでYAML指示書を配置し、実行を依頼する。

**重要**: 
- 指示書（YAML）の仕様、出力規約、選べるオプション一覧は README.md を正とする。
- ユーザーが指示書の作成自体をAIに指示する場合は、以下を確認し指示書を作成する。

#### 指示書作成時の確認事項

| 項目 | 必須 | 説明 | 例 |
|------|------|------|------|
| **ソース** | ✅ | 処理対象（YouTube URL / Website URL / ファイルパス等、複数可） | `https://www.youtube.com/watch?v=XXXXX` |
| **タイトル** | ✅ | NotebookLM上の名前 & 出力ディレクトリ名のベース（YouTube のみ省略可、video_id にフォールバック） | `AI最新動向まとめ` |
| **コンテンツ種類** | ✅ | 生成したいコンテンツ | `podcast` / `image` / `slide` / `video` / `quiz` / `flashcards` / `report` / `data-table` |
| **プロンプト** | 推奨 | 生成時の指示（省略可但非推奨） | `日本語で楽しく解説して` |
| **オプション** | 任意 | README.md「オプション一覧」参照 | `format: deep-dive`, `length: long` |
| **言語設定** | 任意 | デフォルト `ja` | `en`, `ja` |
| **通知設定** | 任意 | GitHub Issue 通知（省略で無効）※ `gh` CLI のインストールとログインが必要 | `github_issue: 1` |

> ユーザーが「この動画でポッドキャスト作って」のように簡潔に依頼した場合、**プロンプトの希望**を確認する。  
> 省略された任意項目はデフォルト値を使用する。

補足: 指示書は `.yml` / `.yaml` を想定する。

### Step 2: バッチ実行

**バックグラウンド実行をデフォルトとする**（生成は数分〜十数分かかるため、ターミナルを占有しないバックグラウンド実行が推奨）

```bash
# バックグラウンド実行（推奨）
nohup python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml > log/nohup_output.log 2>&1 &

# フォアグラウンド実行（進捗確認用、Ctrl+C で中断可能）
python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml
```

- バックグラウンド: `settings.notify` と組み合わせて「投げて放置 → GitHub 通知が来る」UX
- フォアグラウンド: スピナーで進捗表示。長時間ターミナルを占有するため通常は非推奨
- 同じYAMLで再実行すると自動リジューム
- 詳細な挙動は README.md を参照

### Step 3: 結果確認

- 成果物: `./files/<safe_title>__<source_hash>/<type>_<hash>.<ext>`
- 進捗ファイル: `./log/run_*.json`

## 設計原則（アグレッシブ削除方針）

`run_batch.py` は以下の原則で動作する：

1. **成果物ファイルが正**: ローカルにファイルがあればスキップ、なければ生成
2. **ノートブックは使い捨て**: タスク完了後（成功/失敗/中断問わず）に自動削除される
3. **毎回新規作成**: 再実行時は `notebook_id` / `source_id` を引き継がず、常に新規ノートブック作成から開始

この設計により：
- NotebookLM上にノートブックが蓄積しない
- 復旧・状態管理がシンプル（ファイルの有無だけで判定）
- YouTubeソース追加は高速（数秒〜十数秒）なので再作成コストは軽微

## 実行フロー（詳細）

```
タスク開始
  ├── 全成果物が既に存在? → Yes → タスクスキップ（ノート作成なし）
  │                        └── No  ↓
  ├── ノートブック作成
  ├── ソース追加・待機
  ├── 各content処理:
  │     ├── ファイル存在? → Yes → スキップ
  │     │                 └── No  ↓
  │     └── 生成 → 待機 → ダウンロード
  └── [finally] ノートブック削除（成功/失敗/中断問わず）
```

## デフォルト設定

ユーザーが指定しない場合のデフォルト：

| 項目 | デフォルト値 |
|------|-------------|
| 言語 | `ja`（日本語） |
| Podcast format | `deep-dive` |
| Podcast length | `default` |
| Infographic orientation | `landscape` |
| Infographic detail | `standard` |
| Slide format | `presenter` |
| Slide length | `default` |
| Slide download_format | `pdf` |
| Video format | `explainer` |
| Video style | `whiteboard` |
| Quiz quantity | `standard` |
| Quiz difficulty | `medium` |
| Quiz download_format | `json` |
| Flashcards quantity | `standard` |
| Flashcards difficulty | `medium` |
| Flashcards download_format | `json` |
| Report format | `briefing-doc` |
| Data Table | *(オプションなし、prompt 必須)* |

## エラー対応

- **AUTH_REQUIRED（認証エラー）**: `notebooklm login` を再実行 → 同じYAMLで再実行
- **RATE_LIMITED（レート制限）**: 時間をおいて再実行、または別アカウントで実行
- **ソース追加失敗**: YouTubeの文字起こしが利用可能か確認

### `notebooklm login` の注意

- `notebooklm login` は、ブラウザ操作（Googleログイン）とターミナル操作（ENTERで保存）が別で進む。
- ブラウザ側でログインが完了しても、**ターミナルでENTERして `storage_state.json` の保存が完了する前にブラウザを閉じると**、`storage_state` の保存に失敗して再認証が必要になる場合がある。
- もし閉じてしまった場合は、`notebooklm login` を再実行してやり直す。

## 注意事項

- 生成には時間がかかる場合がある（特に動画は数分〜）
- **ノートブックは処理完了後に自動削除される**（NotebookLM上に残らない）
- 成果物ファイルを削除すると、次回実行時に再生成される

## 参考: CLIコマンド（手動操作用）

`run_batch.py` が内部で使用するコマンド。通常は直接使用しない。

```bash
# ノートブック作成
notebooklm create --json -- "<TITLE>"

# ソース追加・待機
notebooklm source add -n <NOTEBOOK_ID> --json "<YOUTUBE_URL>"
notebooklm source wait -n <NOTEBOOK_ID> <SOURCE_ID> --timeout 600 --json

# コンテンツ生成
notebooklm generate <TYPE> -n <NOTEBOOK_ID> --language ja --json -- "<PROMPT>"

# 成果物待機・ダウンロード
notebooklm artifact wait -n <NOTEBOOK_ID> <ARTIFACT_ID> --timeout 86400 --interval 5 --json
notebooklm download <TYPE> -n <NOTEBOOK_ID> -a <ARTIFACT_ID> <OUTPUT_PATH> --force

# ノートブック削除
notebooklm delete -n <NOTEBOOK_ID> -y
```
