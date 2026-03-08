# Installation Guide

## Requirements

- Python 3.11+
- [pipx](https://pipx.pypa.io/) — for installing `notebooklm-py` in an isolated environment

## Step 1: Clone the repository

```bash
git clone https://github.com/KunihiroS/notebooklm-batch.git
cd notebooklm-batch
```

## Step 2: Install Python dependencies

```bash
pip install -r requirements.txt
```

## Step 3: Install notebooklm-py CLI

```bash
pipx install "notebooklm-py[browser]"
```

Install the Playwright browser (Chromium) for browser automation:

```bash
pipx run --spec "notebooklm-py[browser]" python -m playwright install chromium
```

## Step 4: Authenticate with NotebookLM

```bash
notebooklm login
```

This opens a browser for Google account login. **Important:** After logging in on the browser side, return to the terminal and press **ENTER** to save the session — do not close the browser beforehand or authentication will fail.

Your credentials are stored at `~/.notebooklm/storage_state.json`.

## Verifying the installation

```bash
notebooklm --version
python3 run_batch.py --help
```

## Usage

Create a YAML instruction file (see `instructions/instruction_simple.yaml.sample`) and run:

```bash
python3 run_batch.py ./instructions/my_task.yaml
```

For background execution (recommended for long jobs):

```bash
nohup python3 run_batch.py ./instructions/my_task.yaml > log/nohup_output.log 2>&1 &
echo "PID: $!"
```

See [README.md](README.md) for the full YAML schema and options.
