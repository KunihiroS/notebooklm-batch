# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NotebookLM Batch — A batch content generation tool that uses NotebookLM to produce podcasts, infographics, slides, videos, quizzes, flashcards, reports, and data tables from YouTube videos, website URLs, text files, and other sources. Wraps the `notebooklm-py` CLI in Python and processes tasks sequentially based on YAML instruction files.

## Commands

```bash
# Run batch
python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml

# Dry-run (verify targets without actual generation)
python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml --dry-run

# Background execution
nohup python3 ./run_batch.py ./instructions/<INSTRUCTION>.yaml > log/nohup_output.log 2>&1 &

# Authentication (first time / session expired)
notebooklm login
```

No test framework configured. No lint/format tools set up.

## Architecture

### Single-file design
All logic is consolidated in `run_batch.py` (~980 lines). External dependencies are `PyYAML` and the `notebooklm-py` CLI only.

### Core flow
```
YAML instruction → Loop per Task (source):
  All outputs exist → Skip (no notebook creation)
  Otherwise → Create notebook → Add source → Generate content → Download → [finally] Delete notebook
```

### Key design principles
- **Output files are the source of truth**: Skip decision is based on existence of `./files/<dir>/<type>_<hash>.<ext>`. Does not depend on NotebookLM's server state.
- **Aggressive deletion**: Notebooks are always deleted after task completion (success/failure/interruption). `try/finally` prevents deletion leaks.
- **Stable hashing**: Filenames are deterministically generated from `source/type/prompt/options` JSON → SHA1 first 8 characters.
- **Output directory**: Fixed format `{safe_title}__{sha256(source)[:8]}`. Same source always maps to the same directory.
- **Auto-resume**: Re-running the same YAML searches `log/run_*.json` for matching `instruction_file` (canonical path) and resumes if incomplete.

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
- `AUTH_REQUIRED`, `RATE_LIMITED` → `blocked`, stops the entire batch (exit 3)
- Other errors → skip the task and continue to the next

### Directory layout
- `instructions/` — YAML instruction files
- `files/` — Generated outputs (`.gitignore`d)
- `log/` — Progress JSON `run_*.json` (`.gitignore`d)

### AGENTS.md
`AGENTS.md` is an operational guide for AI agents. It covers YAML instruction authoring rules, batch execution steps, and error handling. Treat README.md as the authoritative specification.

## Important notes
- Install `notebooklm` CLI with `pipx install "notebooklm-py[browser]"`
- Credentials are stored at `~/.notebooklm/storage_state.json`
- During `notebooklm login`, do not close the browser before pressing ENTER in the terminal to save the session — closing early causes authentication to fail
- For YAML instruction schema and option values, README.md is the authoritative reference
