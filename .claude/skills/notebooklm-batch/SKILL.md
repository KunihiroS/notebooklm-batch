---
name: notebooklm-batch
description: >
  Use this skill whenever the user wants to generate content from YouTube videos
  or website URLs using NotebookLM — including podcasts, slide decks,
  infographics, videos, reports, quizzes, flashcards, or data tables.
  Auto-trigger on requests like "この動画でポッドキャスト作って",
  "このURLをレポートにまとめて", "YouTube動画からスライド生成して",
  "generate a podcast from this video", "summarize this article as a report",
  or any request that combines a URL/video with content generation.
  Also trigger when the user asks to batch-process multiple sources at once.
allowed-tools: Bash, Read, Write, Glob
---

# notebooklm-batch コンテンツ生成

notebooklm-batch は YouTube 動画や Web サイトから NotebookLM を使って
コンテンツ（Podcast・スライド・レポート等）をバッチ生成するツール。
YAML 指示書を作成して `run_batch.py` に渡すことで自動生成する。

詳細仕様: `README.md`（YAML スキーマ・オプション一覧）、`AGENTS.md`（認証・エラー対応）

## Step 0: 作業ディレクトリ確定

すべてのコマンドを実行する前に、リポジトリルートへ移動する。

```bash
cd $(git rev-parse --show-toplevel)
```

これによりハードコードされたパスを使わずにどこからでも動作する。

## Step 1: 認証確認

```bash
ls ~/.notebooklm/storage_state.json
```

ファイルが存在しない場合は処理を止め、ユーザーに以下を依頼する:

1. `notebooklm login` を実行
2. ブラウザで Google アカウントにログイン
3. **ログイン完了後、ターミナルに戻って ENTER を押すまでブラウザを閉じない**（ブラウザを先に閉じると `storage_state.json` の保存が失敗する）

## Step 2: パラメータ収集

会話のコンテキストからできるだけ読み取る。不明な項目のみ確認する。

| 項目 | 必須 | 備考 |
|------|------|------|
| **source** | ✅ | YouTube URL / Website URL / ファイルパス |
| **title** | ✅（YouTube 以外） | YouTube は省略可（video_id にフォールバック） |
| **コンテンツ種類** | ✅ | 下表参照 |
| **prompt** | 推奨 | 省略可だが、指示なしだと汎用的な内容になる。確認推奨 |
| **options** | 任意 | 省略時は AGENTS.md のデフォルト値が適用される |

### 対応コンテンツ種類

| type | 説明 | 主なオプション |
|------|------|----------------|
| `podcast` | 音声Podcast | `format`: deep-dive/brief/critique/debate, `length`: short/default/long |
| `slide` | スライドデッキ（PDF） | `format`: detailed/presenter, `length`: default/short |
| `image` | インフォグラフィック | `orientation`: landscape/portrait/square, `detail`: concise/standard/detailed |
| `video` | 動画 | `format`: explainer/brief, `style`: whiteboard/kawaii/anime 等 |
| `report` | レポート（Markdown） | `format`: briefing-doc/faq/study-guide/timeline 等 |
| `quiz` | クイズ（JSON） | `quantity`: standard/more/fewer, `difficulty`: easy/medium/hard |
| `flashcards` | フラッシュカード（JSON） | `quantity`: standard/more/fewer, `difficulty`: easy/medium/hard |
| `data-table` | データテーブル（CSV） | *(prompt 必須、options なし)* |

## Step 3: YAML 指示書の作成

`./instructions/` ディレクトリに YAML ファイルを作成する。

ファイル名: `{safe_title}_{YYYYMMDD}.yaml`（例: `ai_news_20240308.yaml`）

```yaml
settings:
  language: ja          # ja または en

tasks:
  - source: "<YouTube URL / Website URL / ファイルパス>"
    title: "<タイトル>"   # YouTube のみ省略可
    contents:
      - type: <TYPE>
        prompt: "<生成時の指示>"
        # options:       # 任意。省略時はデフォルト値が適用
        #   key: value
```

複数のコンテンツ種類を同時生成する場合は `contents` にエントリを追加する。
複数のソースを処理する場合は `tasks` にエントリを追加する。

## Step 4: ドライラン確認

実際の生成を行わず、処理対象と出力パスを確認する。

```bash
python3 ./run_batch.py ./instructions/<FILE>.yaml --dry-run
```

出力をユーザーに提示し、意図通りかを確認する。問題があれば YAML を修正して再度ドライランする。

## Step 5: バックグラウンド実行

生成には数分〜十数分かかるため、バックグラウンド実行がデフォルト。

```bash
nohup python3 ./run_batch.py ./instructions/<FILE>.yaml > log/nohup_output.log 2>&1 &
echo "PID: $!"
```

### 実行後にユーザーへ報告する情報

- **PID**: バックグラウンドプロセスの番号
- **成果物パス**: `./files/<safe_title>__<source_hash>/`（ドライラン出力に表示される）
- **ログ監視**: `tail -f log/nohup_output.log`
- **再開方法**: 中断しても同じ YAML で再実行すれば自動リジューム

## エラー対応

| エラー | 意味 | 対応 |
|--------|------|------|
| `AUTH_REQUIRED` | 認証切れ | `notebooklm login` を再実行 → 同じ YAML で再実行 |
| `RATE_LIMITED` | レート制限 | 時間をおいて再実行（バッチ全体が停止する） |
| その他 | タスクエラー | そのタスクをスキップして続行（正常動作） |

AUTH_REQUIRED / RATE_LIMITED は **バッチ全体が停止**する fatal エラー。
その他のエラーはタスク単位でスキップされ、バッチは続行する。

詳細は `AGENTS.md` の「エラー対応」セクション参照。
