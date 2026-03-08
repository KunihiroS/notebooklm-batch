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
---

# notebooklm-batch Content Generation

notebooklm-batch is a tool that uses NotebookLM to batch-generate content
(podcasts, slides, reports, etc.) from YouTube videos and websites.
Create a YAML instruction file and pass it to `run_batch.py` for automated generation.

Full spec: `README.md` (YAML schema and option values), `AGENTS.md` (authentication and error handling)

## Step 0: Confirm working directory

Before running any commands, change to the repository root:

```bash
cd $(git rev-parse --show-toplevel)
```

This ensures correct paths regardless of where you invoke the skill from.

## Step 1: Check authentication

```bash
ls ~/.notebooklm/storage_state.json
```

If the file does not exist, stop and ask the user to:

1. Run `notebooklm login`
2. Log in to their Google account in the browser
3. **Return to the terminal and press ENTER after login completes — do not close the browser first** (closing before pressing ENTER causes `storage_state.json` to fail to save)

## Step 2: Gather parameters

Read as much as possible from the conversation context. Only ask about items that are unclear.

| Item | Required | Notes |
|------|----------|-------|
| **source** | ✅ | YouTube URL / Website URL / file path |
| **title** | ✅ (non-YouTube) | YouTube sources may omit (falls back to `video_id`) |
| **content type** | ✅ | See table below |
| **prompt** | Recommended | Optional, but generic without one — confirm if not provided |
| **options** | Optional | Defaults from AGENTS.md apply when omitted |

### Supported content types

| type | Description | Key options |
|------|-------------|-------------|
| `podcast` | Audio podcast | `format`: deep-dive/brief/critique/debate, `length`: short/default/long |
| `slide` | Slide deck (PDF) | `format`: detailed/presenter, `length`: default/short |
| `image` | Infographic (PNG) | `orientation`: landscape/portrait/square, `detail`: concise/standard/detailed |
| `video` | Explainer video (MP4) | `format`: explainer/brief, `style`: whiteboard/kawaii/anime etc. |
| `report` | Report (Markdown) | `format`: briefing-doc/faq/study-guide/timeline etc. |
| `quiz` | Quiz (JSON) | `quantity`: standard/more/fewer, `difficulty`: easy/medium/hard |
| `flashcards` | Flashcards (JSON) | `quantity`: standard/more/fewer, `difficulty`: easy/medium/hard |
| `data-table` | Data table (CSV) | *(prompt required, no options)* |

## Step 3: Create YAML instruction file

Create a YAML file in `./instructions/`.

File name: `{safe_title}_{YYYYMMDD}.yaml` (e.g., `ai_news_20240308.yaml`)

```yaml
settings:
  language: ja          # ja or en

tasks:
  - source: "<YouTube URL / Website URL / file path>"
    title: "<title>"    # optional for YouTube only
    contents:
      - type: <TYPE>
        prompt: "<generation instructions>"
        # options:       # optional; defaults apply when omitted
        #   key: value
```

Add entries to `contents` to generate multiple content types from one source.
Add entries to `tasks` to process multiple sources.

## Step 4: Dry-run verification

Verify targets and output paths without actually generating anything:

```bash
python3 ./run_batch.py ./instructions/<FILE>.yaml --dry-run
```

Show the output to the user and confirm it matches their intent. Fix the YAML and re-run dry-run if needed.

## Step 5: Background execution

Generation takes several minutes to tens of minutes — background execution is the default:

```bash
nohup python3 ./run_batch.py ./instructions/<FILE>.yaml > log/nohup_output.log 2>&1 &
echo "PID: $!"
```

### Report to the user after starting

- **PID**: Background process ID
- **Output path**: `./files/<safe_title>__<source_hash>/` (shown in dry-run output)
- **Monitor logs**: `tail -f log/nohup_output.log`
- **Resume**: Re-running the same YAML auto-resumes from where it stopped

## Error Handling

| Error | Meaning | Action |
|-------|---------|--------|
| `AUTH_REQUIRED` | Session expired | Re-run `notebooklm login` → re-run same YAML |
| `RATE_LIMITED` | Rate limit hit | Wait and retry (stops entire batch) |
| Other | Task-level error | That task is skipped; batch continues (normal behavior) |

`AUTH_REQUIRED` / `RATE_LIMITED` are **fatal errors that stop the entire batch**.
Other errors skip the individual task and the batch continues.

See the "Error Handling" section in `AGENTS.md` for details.
