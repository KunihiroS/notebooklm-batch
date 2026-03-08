# NotebookLM Content Generation Agent Guide

This repository uses NotebookLM to generate content (podcasts, images, slides, videos, etc.) from YouTube videos, website URLs, and other sources. Operations follow the "YAML instruction → batch generation → local save" workflow described in README.md.

## Prerequisites

- `notebooklm-py` installed via `pipx install "notebooklm-py[browser]"`
- Authenticated via `notebooklm login` (`~/.notebooklm/storage_state.json` exists)
- If not authenticated or session expired, run `notebooklm login` and ask the user to complete browser-based Google login.
  - The user must complete login in the browser **and then press ENTER in the terminal** — closing the browser before pressing ENTER causes `storage_state.json` to fail to save.

### Re-authentication (keeping the environment clean)

Install dependencies via `pipx` (not global `pip`):

```bash
pipx install "notebooklm-py[browser]"
pipx run --spec "notebooklm-py[browser]" python -m playwright install chromium
```

## Scope

- Instructions: YAML files under `./instructions/`
- Outputs: Files under `./files/` (`{safe_title}__{source_hash}` subdirectories)
- Run logs: Files under `./log/`

## Batch Execution

### Step 1: Gather input from the user

The user places a YAML instruction file under `./instructions/` and requests execution.

**Important**:
- The authoritative YAML schema, output conventions, and option values are in README.md.
- If the user asks the agent to create the instruction file, confirm the following:

#### Items to confirm when creating an instruction file

| Item | Required | Description | Example |
|------|----------|-------------|---------|
| **source** | ✅ | Target URL or file path (YouTube URL / Website URL / file path, multiple allowed) | `https://www.youtube.com/watch?v=XXXXX` |
| **title** | ✅ | Notebook name on NotebookLM & output directory base (optional for YouTube — falls back to `video_id`) | `AI Weekly Digest` |
| **content type** | ✅ | Type of content to generate | `podcast` / `image` / `slide` / `video` / `quiz` / `flashcards` / `report` / `data-table` |
| **prompt** | Recommended | Generation instructions (optional but recommended) | `Summarize in an engaging tone` |
| **options** | Optional | See "Options" in README.md | `format: deep-dive`, `length: long` |
| **language** | Optional | Default: `ja` | `en`, `ja` |
| **notify** | Optional | GitHub Issue notification (requires `gh` CLI) | `github_issue: 1` |

> If the user gives a brief request like "make a podcast from this video", confirm the desired **prompt**.
> Omitted optional items use default values.

Note: Instruction files use `.yml` / `.yaml` extension.

### Step 2: Execute batch

**Background execution is the default** (generation takes several minutes to tens of minutes, so non-blocking background execution is preferred):

```bash
# Background execution (recommended)
nohup python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml > log/nohup_output.log 2>&1 &

# Foreground execution (shows progress spinner, Ctrl+C to abort)
python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml
```

- Background: pair with `settings.notify` for "fire and forget → GitHub notification" UX
- Foreground: shows progress spinner, but blocks the terminal — not recommended for long jobs
- Re-running the same YAML auto-resumes from where it left off
- See README.md for detailed behavior

### Step 3: Check results

- Outputs: `./files/<safe_title>__<source_hash>/<type>_<hash>.<ext>`
- Progress file: `./log/run_*.json`

## Design Principles (Aggressive Deletion)

`run_batch.py` operates on these principles:

1. **Output files are the source of truth**: If a file exists locally, skip it; if not, generate it.
2. **Notebooks are disposable**: Automatically deleted after task completion (success/failure/interruption).
3. **Always start fresh**: On re-run, never reuse `notebook_id` / `source_id` — always create a new notebook.

This design ensures:
- No notebook accumulation on NotebookLM
- Simple recovery/state management (only file existence matters)
- YouTube source addition is fast (seconds to tens of seconds), so re-creation cost is negligible

## Execution Flow (Detail)

```
Task start
  ├── All outputs already exist? → Yes → Skip task (no notebook creation)
  │                               └── No  ↓
  ├── Create notebook
  ├── Add source and wait
  ├── For each content:
  │     ├── File exists? → Yes → Skip
  │     │                └── No  ↓
  │     └── Generate → Wait → Download
  └── [finally] Delete notebook (regardless of success/failure/interruption)
```

## Default Values

When the user does not specify options:

| Item | Default |
|------|---------|
| Language | `ja` |
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
| Data Table | *(no options; prompt is required)* |

## Error Handling

- **AUTH_REQUIRED**: Re-run `notebooklm login` → re-run the same YAML
- **RATE_LIMITED**: Wait and retry, or switch to a different account
- **Source add failure**: Check if the YouTube video has transcripts available

### Notes on `notebooklm login`

- `notebooklm login` involves two separate steps: browser-side Google login and terminal-side ENTER to save.
- Even if browser login completes, **closing the browser before pressing ENTER in the terminal** causes `storage_state.json` to fail to save and requires re-authentication.
- If that happens, just re-run `notebooklm login`.

## Notes

- Generation can take time (video in particular can take several minutes or more)
- **Notebooks are automatically deleted after processing** (they do not remain on NotebookLM)
- Deleting an output file causes it to be regenerated on the next run

## Reference: CLI Commands (for manual use)

Commands used internally by `run_batch.py`. Normally you do not need to run these directly.

```bash
# Create notebook
notebooklm create --json -- "<TITLE>"

# Add source and wait
notebooklm source add -n <NOTEBOOK_ID> --json "<SOURCE_URL>"
notebooklm source wait -n <NOTEBOOK_ID> <SOURCE_ID> --timeout 600 --json

# Generate content
notebooklm generate <TYPE> -n <NOTEBOOK_ID> --language ja --json -- "<PROMPT>"

# Wait for artifact and download
notebooklm artifact wait -n <NOTEBOOK_ID> <ARTIFACT_ID> --timeout 86400 --interval 5 --json
notebooklm download <TYPE> -n <NOTEBOOK_ID> -a <ARTIFACT_ID> <OUTPUT_PATH> --force

# Delete notebook
notebooklm delete -n <NOTEBOOK_ID> -y
```
