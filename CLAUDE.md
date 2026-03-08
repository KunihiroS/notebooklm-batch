# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NotebookLM Batch — YouTube動画・WebサイトURL・テキストファイル等のソースからNotebookLMを使ってコンテンツ（Podcast/画像/スライド/動画/Quiz/Flashcards/Report/Data Table）をバッチ生成するツール。`notebooklm-py` CLIをPythonでラップし、YAML指示書に基づいて逐次処理する。

## Commands

```bash
# バッチ実行
python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml

# dry-run（実際の生成を行わず処理対象を確認）
python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml --dry-run

# バックグラウンド実行
nohup python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml > log/nohup_output.log 2>&1 &

# 認証（初回/期限切れ時）
notebooklm login
```

テストフレームワークは未導入。lint/format ツールも未設定。

## Architecture

### Single-file design
全ロジックが `run_batch.py` に集約されている（約980行）。外部依存は `PyYAML` と `notebooklm-py` CLI のみ。

### Core flow
```
YAML指示書 → Task(source)ごとにループ:
  全成果物あり → スキップ（ノート作成なし）
  なければ → ノート作成 → ソース追加 → Content生成 → DL → [finally] ノート削除
```

### Key design principles
- **成果物ファイルが正**: `./files/<dir>/<type>_<hash>.<ext>` の存在でスキップ判定。NotebookLM側の状態には依存しない
- **アグレッシブ削除**: ノートブックはタスク完了後（成功/失敗/中断問わず）に常に削除。`try/finally` で削除漏れ防止
- **安定ハッシュ**: ファイル名は `source/type/prompt/options` のJSON化→SHA1先頭8文字で決定論的に生成
- **出力ディレクトリ**: `{safe_title}__{sha256(source)[:8]}` の固定形式。同じ source なら常に同じディレクトリ
- **自動リジューム**: 同一YAMLを再実行すると `log/run_*.json` から `instruction_file`（canonical path）一致で最新runを探し、未完了なら自動再開

### Content type mapping (`CONTENT_MAP`)
| YAML type   | CLI generate | CLI download | ext  | lang  | dl_force | dl_format |
|-------------|-------------|-------------|------|-------|----------|-----------|
| podcast     | audio       | audio       | mp3  | True  | True     | -         |
| image       | infographic | infographic | png  | True  | True     | -         |
| slide       | slide-deck  | slide-deck  | pdf  | True  | True     | pdf       |
| video       | video       | video       | mp4  | True  | True     | -         |
| quiz        | quiz        | quiz        | json | False | False    | json      |
| flashcards  | flashcards  | flashcards  | json | False | False    | json      |
| report      | report      | report      | md   | True  | True     | -         |
| data-table  | data-table  | data-table  | csv  | True  | True     | -         |

### Fatal vs non-fatal errors
- `AUTH_REQUIRED`, `RATE_LIMITED` → `blocked`、バッチ全体を停止（exit 3）
- その他のエラー → タスクをスキップして次のタスクへ続行

### Directory layout
- `instructions/` — YAML指示書
- `files/` — 生成成果物（`.gitignore`対象）
- `log/` — 進捗JSON `run_*.json`（`.gitignore`対象）

### AGENTS.md
`AGENTS.md` はAIエージェント向けの運用指示書。YAML指示書の作成ルール、バッチ実行手順、エラー対応が記載されている。README.mdの仕様を正として参照する。

## Important notes
- `notebooklm` CLIは `pipx install "notebooklm-py[browser]"` で導入
- 認証情報は `~/.notebooklm/storage_state.json`
- `notebooklm login` 時、ターミナルでENTER保存完了前にブラウザを閉じると失敗する
- YAML指示書の仕様（オプション値一覧等）は README.md を正とする
