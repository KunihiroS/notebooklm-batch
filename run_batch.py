import json
import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


CONTENT_MAP: dict[str, dict] = {
    "podcast":    {"generate": "audio",       "download": "audio",       "ext": "mp3", "lang": True,  "prompt": True,       "dl_force": True,  "dl_format": None},
    "image":      {"generate": "infographic", "download": "infographic", "ext": "png", "lang": True,  "prompt": True,       "dl_force": True,  "dl_format": None},
    "slide":      {"generate": "slide-deck",  "download": "slide-deck",  "ext": "pdf", "lang": True,  "prompt": True,       "dl_force": True,  "dl_format": "pdf"},
    "video":      {"generate": "video",       "download": "video",       "ext": "mp4", "lang": True,  "prompt": True,       "dl_force": True,  "dl_format": None},
    "quiz":       {"generate": "quiz",        "download": "quiz",        "ext": "json","lang": False, "prompt": True,       "dl_force": False, "dl_format": "json"},
    "flashcards": {"generate": "flashcards",  "download": "flashcards",  "ext": "json","lang": False, "prompt": True,       "dl_force": False, "dl_format": "json", "artifact_list_type": "flashcard"},
    "report":     {"generate": "report",      "download": "report",      "ext": "md",  "lang": True,  "prompt": True,       "dl_force": True,  "dl_format": None},
    "data-table": {"generate": "data-table",  "download": "data-table",  "ext": "csv", "lang": True,  "prompt": "required", "dl_force": True,  "dl_format": None},
}

# download_format -> file extension mapping (when format differs from default ext)
DL_FORMAT_EXT: dict[str, str] = {
    "pptx": "pptx",
    "markdown": "md",
    "html": "html",
}

# Errors that should stop the entire batch (all other errors skip the task and continue)
FATAL_CODES: set[str] = {"AUTH_REQUIRED", "RATE_LIMITED"}


@dataclass(frozen=True)
class CmdResult:
    returncode: int
    stdout: str
    stderr: str


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        vid = parsed.path.lstrip("/")
        return vid or "unknown"
    qs = parse_qs(parsed.query)
    return qs.get("v", ["unknown"])[0] or "unknown"


# Windows予約名（ファイル名に使用不可）
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def slugify(text: str, max_len: int = 50) -> str:
    """ファイルシステム安全な文字列に変換。
    
    注意: __ を _ に正規化するのは、build_output_dir_name() で
    __ をセパレータとして使うため、一意性を保つため。
    
    絵文字はそのまま許容（Linux/macOSでは問題なし。
    古いWindows/FAT32では使用不可の可能性あり）。
    """
    # 危険な文字を除去
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', text)
    # 日本語括弧等も除去
    safe = re.sub(r'[「」『』【】〈〉《》]', '', safe)
    # 連続スペース/アンダースコアを単一アンダースコアに
    safe = re.sub(r'[\s_]+', '_', safe)
    # ダブルアンダースコアを単一に（セパレータとの混同回避）
    safe = re.sub(r'__+', '_', safe)
    # 先頭のドット、末尾のドット/スペース/アンダースコアを除去
    safe = safe.lstrip('.').rstrip('._ ')
    # 長さ制限
    if len(safe) > max_len:
        safe = safe[:max_len].rstrip('_')
    # Windows予約名チェック
    if safe.upper() in WINDOWS_RESERVED:
        safe = f"_{safe}"
    return safe


def build_output_dir_name(title: str, source: str) -> str:
    """出力ディレクトリ名を生成。

    形式: {safe_title}__{sha256(source)[:8]}
    source が同じなら常に同じディレクトリ名（冪等性保証）。
    """
    safe_title = slugify(title)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
    if not safe_title:
        return source_hash
    return f"{safe_title}__{source_hash}"


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_cmd(argv: list[str], *, cwd: Path, timeout_sec: int | None = None) -> CmdResult:
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_sec,
    )
    return CmdResult(proc.returncode, proc.stdout or "", proc.stderr or "")


def run_cmd_json(argv: list[str], *, cwd: Path, timeout_sec: int | None = None) -> tuple[CmdResult, Any | None]:
    res = run_cmd(argv, cwd=cwd, timeout_sec=timeout_sec)
    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    text = out or err
    if not text:
        return res, None
    try:
        return res, json.loads(text)
    except Exception:
        return res, None


def ensure_notebooklm_exists(cwd: Path) -> None:
    res = run_cmd(["bash", "-lc", "command -v notebooklm"], cwd=cwd)
    if res.returncode != 0:
        raise RuntimeError("notebooklm command not found")


def canonicalize_path(path: Path) -> Path:
    return path.expanduser().resolve()


def canonicalize_path_str(path_str: str, *, base_dir: Path) -> str:
    p = Path(path_str)
    if not p.is_absolute():
        p = base_dir / p
    return str(canonicalize_path(p))


def stable_content_hash(*, source: str, ctype: str, prompt: str, options: dict[str, Any]) -> str:
    payload = {
        "source": source,
        "type": ctype,
        "prompt": prompt,
        "options": options,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:8]


def slug_content_id(content: dict[str, Any], ordinal: int, *, task_source: str) -> str:
    """Generate stable content ID using hash (user-specified content_id is no longer supported)."""
    t = str(content.get("type", "content"))
    prompt = str(content.get("prompt") or "")
    options = content.get("options") or {}
    if not isinstance(options, dict):
        options = {}
    h = stable_content_hash(source=task_source, ctype=t, prompt=prompt, options=options)
    return f"{t}_{h}"


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def should_skip_output(output_path: Path) -> bool:
    return output_path.exists()


def parse_rate_limited(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("code") == "RATE_LIMITED":
        return True
    if obj.get("error") is True and obj.get("code") == "RATE_LIMITED":
        return True
    return False


def parse_auth_error(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("error") is True and isinstance(obj.get("message"), str):
        msg = obj["message"]
        if "Authentication expired" in msg or "Run 'notebooklm login'" in msg:
            return True
    return False


def err_payload(code: str, *, res: CmdResult, detail: Any | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "at": now_iso()}
    if res.stdout.strip():
        payload["stdout"] = res.stdout.strip()
    if res.stderr.strip():
        payload["stderr"] = res.stderr.strip()
    if detail is not None:
        payload["detail"] = detail
    return payload


def find_latest_run_file(cwd: Path, instruction_path: Path) -> Path | None:
    log_dir = cwd / "log"
    if not log_dir.exists():
        return None
    instruction_canonical = str(canonicalize_path(instruction_path))
    candidates: list[Path] = []
    for p in sorted(log_dir.glob("run_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = read_json(p)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        stored = data.get("instruction_file")
        if not isinstance(stored, str):
            continue
        if canonicalize_path_str(stored, base_dir=cwd) != instruction_canonical:
            continue
        candidates.append(p)
    return candidates[0] if candidates else None


def summarize_run(data: dict[str, Any]) -> tuple[int, int, int, int, int]:
    """Summarize run status: (total, completed, skipped, blocked, errored)"""
    total = 0
    completed = 0
    skipped = 0
    blocked = 0
    errored = 0
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return (0, 0, 0, 0, 0)
    for t in tasks:
        if not isinstance(t, dict):
            continue
        contents = t.get("contents")
        if not isinstance(contents, list):
            continue
        for c in contents:
            if not isinstance(c, dict):
                continue
            total += 1
            st = c.get("status")
            if st == "completed":
                completed += 1
            elif st == "skipped":
                skipped += 1
            elif st == "blocked":
                blocked += 1
            elif st == "error":
                errored += 1
    return (total, completed, skipped, blocked, errored)


def get_block_reason(data: dict[str, Any]) -> str | None:
    """Get the block/error reason code from run data (e.g., 'AUTH_REQUIRED', 'RATE_LIMITED')
    
    Prioritizes 'blocked' status over 'error' status to show the actual stopping reason.
    Prefers detail.code over top-level code for more specific error information.
    """
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return None

    def _extract_reason(t: dict) -> str | None:
        # Check task-level error
        err = t.get("error")
        if isinstance(err, dict):
            detail = err.get("detail")
            if isinstance(detail, dict) and detail.get("code"):
                return str(detail["code"])
            if err.get("code"):
                return str(err["code"])
        # Check content-level error
        contents = t.get("contents")
        if isinstance(contents, list):
            for c in contents:
                if not isinstance(c, dict):
                    continue
                if c.get("status") in ("blocked", "error"):
                    cerr = c.get("error")
                    if isinstance(cerr, dict):
                        detail = cerr.get("detail")
                        if isinstance(detail, dict) and detail.get("code"):
                            return str(detail["code"])
                        if cerr.get("code"):
                            return str(cerr["code"])
        return None

    # First pass: look for 'blocked' tasks (the actual stopping reason)
    for t in tasks:
        if isinstance(t, dict) and t.get("status") == "blocked":
            reason = _extract_reason(t)
            if reason:
                return reason

    # Second pass: fall back to 'error' tasks
    for t in tasks:
        if isinstance(t, dict) and t.get("status") == "error":
            reason = _extract_reason(t)
            if reason:
                return reason

    return None


def format_elapsed(seconds: float) -> str:
    """Format elapsed time as MM:SS or HH:MM:SS"""
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def spinner_thread(stop: threading.Event, run_file: Path, initial_done: int = 0, initial_total: int = 0) -> None:
    """Spinner thread with progress display.
    
    Args:
        stop: Event to signal thread termination
        run_file: Path to run state JSON file
        initial_done: Number of tasks already done at start (for resume progress)
        initial_total: Total number of tasks at start (for resume progress)
    """
    import time
    # Braille spinner (smoother animation)
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    status_icons = {
        "running": "🔄",
        "completed": "✅",
        "completed_with_errors": "⚠️",
        "blocked": "🚫",
        "aborted": "⏹️",
        "error": "❌",
    }
    i = 0
    last_line = ""
    start_time = time.time()
    
    def build_progress_bar(done: int, total: int) -> tuple[str, int]:
        if total > 0:
            bar_width = 20
            filled = int(bar_width * done / total)
            bar = "█" * filled + "░" * (bar_width - filled)
            pct = int(100 * done / total)
            return bar, pct
        return "░" * 20, 0

    while not stop.is_set():
        try:
            data = read_json(run_file)
            if isinstance(data, dict):
                total, completed, skipped, _, errored = summarize_run(data)
                done = completed + skipped
                status = data.get("status", "running")
                icon = status_icons.get(status, "⏳")
                bar, pct = build_progress_bar(done, total)
                elapsed = format_elapsed(time.time() - start_time)
                block_info = ""
                if status in ("blocked", "error", "completed_with_errors"):
                    reason = get_block_reason(data)
                    if reason:
                        block_info = f" [{reason}]"

                remaining = max(total - done, 0)
                if status == "running":
                    line = (
                        f"{frames[i % len(frames)]} {icon} [{bar}] {pct:3d}% "
                        f"{done}/{total} 完了 (残{remaining}) | TIME:{elapsed} | LOG:{run_file.name}"
                    )
                else:
                    err_part = f" (ERR:{errored})" if errored else ""
                    line = (
                        f"{frames[i % len(frames)]} {icon} [{bar}] {pct:3d}% "
                        f"{done}/{total} 完了{err_part} | TIME:{elapsed} | LOG:{run_file.name}{block_info}"
                    )
            else:
                elapsed = format_elapsed(time.time() - start_time)
                line = f"{frames[i % len(frames)]} ⏳ Initializing... | TIME:{elapsed} | LOG:{run_file.name}"
        except Exception:
            elapsed = format_elapsed(time.time() - start_time)
            line = f"{frames[i % len(frames)]} ⏳ Starting... | TIME:{elapsed} | LOG:{run_file.name}"

        if line != last_line:
            sys.stderr.write("\r" + line + " " * max(0, len(last_line) - len(line)))
            sys.stderr.flush()
            last_line = line

        i += 1
        stop.wait(0.2)  # Faster update for smoother animation
    
    # Print final status before exit
    try:
        data = read_json(run_file)
        if isinstance(data, dict):
            total, completed, skipped, _, errored = summarize_run(data)
            status = data.get("status", "unknown")
            icon = status_icons.get(status, "⏳")
            done = completed + skipped
            bar, pct = build_progress_bar(done, total)
            elapsed = format_elapsed(time.time() - start_time)
            block_info = ""
            if status in ("blocked", "error", "completed_with_errors"):
                reason = get_block_reason(data)
                if reason:
                    block_info = f" [{reason}]"

            err_part = f" (ERR:{errored})" if errored else ""
            final_line = (
                f"  {icon} [{bar}] {pct:3d}% {done}/{total} 完了{err_part} "
                f"| TIME:{elapsed} | LOG:{run_file.name}{block_info}"
            )
            sys.stderr.write("\r" + final_line + " " * max(0, len(last_line) - len(final_line)) + "\n")
            sys.stderr.flush()
    except Exception:
        if last_line:
            sys.stderr.write("\r" + " " * len(last_line) + "\r")
            sys.stderr.flush()


def install_termination_handlers() -> None:
    def _handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        threading.interrupt_main()

    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _handler)
        except Exception:
            continue


def latest_artifact_id(cwd: Path, notebook_id: str, artifact_type: str) -> str | None:
    res, data = run_cmd_json(
        ["notebooklm", "artifact", "list", "-n", notebook_id, "--type", artifact_type, "--json"],
        cwd=cwd,
        timeout_sec=60,
    )
    if res.returncode != 0 or data is None:
        return None
    artifacts = None
    if isinstance(data, dict):
        artifacts = data.get("artifacts")
    if artifacts is None:
        artifacts = data
    if not isinstance(artifacts, list) or not artifacts:
        return None

    def key(a: Any) -> str:
        if isinstance(a, dict):
            return str(a.get("created_at") or a.get("created") or a.get("createdAt") or "")
        return ""

    artifacts_sorted = sorted([a for a in artifacts if isinstance(a, dict) and a.get("id")], key=key)
    if not artifacts_sorted:
        return None
    return str(artifacts_sorted[-1]["id"])


def notify_github(issue: int, body: str, *, repo: str | None = None) -> None:
    """GitHub Issue にコメントを投稿（best-effort、失敗してもバッチは止めない）"""
    argv = ["gh", "issue", "comment", str(issue), "--body", body]
    if repo:
        argv.extend(["--repo", repo])
    try:
        subprocess.run(argv, capture_output=True, timeout=30)
    except Exception:
        pass


def delete_notebook(cwd: Path, notebook_id: str) -> bool:
    """Delete a notebook. Returns True on success, False on failure (best-effort)."""
    res = run_cmd(
        ["notebooklm", "delete", "-n", notebook_id, "-y"],
        cwd=cwd,
        timeout_sec=60,
    )
    return res.returncode == 0


def main(argv: list[str]) -> int:
    cwd = Path(__file__).resolve().parent
    ensure_notebooklm_exists(cwd)
    install_termination_handlers()
    if len(argv) < 2:
        print("Usage: python run_batch.py ./instructions/<INSTRUCTION>.yaml [--dry-run]", file=sys.stderr)
        return 2

    instruction_arg = Path(argv[1])
    if not instruction_arg.is_absolute():
        instruction_arg = Path.cwd() / instruction_arg
    instruction_path = canonicalize_path(instruction_arg)
    dry_run = "--dry-run" in argv[2:]

    if yaml is None:
        print("PyYAML is required (import yaml failed)", file=sys.stderr)
        return 2

    if not instruction_path.exists():
        print(f"Instruction not found: {instruction_path}", file=sys.stderr)
        return 2

    spec = yaml.safe_load(instruction_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        print("Invalid YAML: top-level must be mapping", file=sys.stderr)
        return 2

    settings = spec.get("settings") or {}
    tasks = spec.get("tasks") or []
    if not isinstance(tasks, list):
        print("Invalid YAML: tasks must be list", file=sys.stderr)
        return 2

    existing_run_file = find_latest_run_file(cwd, instruction_path)
    run_state: dict[str, Any]
    run_file: Path
    run_id: str

    if existing_run_file is not None:
        try:
            existing_state = read_json(existing_run_file)
        except Exception:
            existing_state = None
        if isinstance(existing_state, dict) and existing_state.get("status") not in ("completed",):
            run_state = existing_state
            run_file = existing_run_file
            run_id = str(run_state.get("run_id") or now_ts())
            run_state["instruction_file"] = str(instruction_path)
            run_state["resumed_at"] = now_iso()
            run_state["status"] = "running"
        else:
            run_id = now_ts()
            run_file = cwd / "log" / f"run_{run_id}.json"
            run_state = {
                "run_id": run_id,
                "instruction_file": str(instruction_path),
                "started_at": now_iso(),
                "status": "running",
                "tasks": [],
            }
    else:
        run_id = now_ts()
        run_file = cwd / "log" / f"run_{run_id}.json"
        run_state = {
            "run_id": run_id,
            "instruction_file": str(instruction_path),
            "started_at": now_iso(),
            "status": "running",
            "tasks": [],
        }

    if settings.get("output_dir_mode"):
        print("Warning: 'output_dir_mode' is deprecated and will be ignored. Output directory is now fixed to '{safe_title}__{source_hash}' format.", file=sys.stderr)

    if not run_state.get("tasks"):
        for t in tasks:
            if not isinstance(t, dict):
                continue
            # Backward compat: 'url' field is deprecated, use 'source' instead
            if "url" in t and "source" not in t:
                print(f"Warning: 'url' is deprecated, use 'source' instead: {str(t['url'])[:60]}", file=sys.stderr)
            source = str(t.get("source") or t.get("url") or "")
            if not source:
                continue

            title = str(t.get("title") or "")
            if not title:
                if "youtube.com" in source or "youtu.be" in source:
                    title = extract_video_id(source)
                else:
                    print(f"Warning: 'title' is required for non-YouTube sources, skipping: {source[:60]}", file=sys.stderr)
                    continue

            contents = t.get("contents") or []
            if not isinstance(contents, list):
                contents = []

            task_entry: dict[str, Any] = {
                "source": source,
                "title": title,
                "notebook_id": None,
                "source_id": None,
                "status": "pending",
                "contents": [],
            }

            ordinal = 0
            for c in contents:
                if not isinstance(c, dict) or "type" not in c:
                    continue
                ordinal += 1
                ctype = str(c["type"])
                if ctype not in CONTENT_MAP:
                    continue
                prompt_flag = CONTENT_MAP[ctype].get("prompt")
                if prompt_flag == "required" and not str(c.get("prompt") or "").strip():
                    print(f"Warning: type '{ctype}' requires a non-empty prompt, skipping", file=sys.stderr)
                    continue
                cid = slug_content_id(c, ordinal, task_source=source)
                ext = CONTENT_MAP[ctype]["ext"]
                dl_fmt = (c.get("options") or {}).get("download_format")
                if dl_fmt:
                    ext = DL_FORMAT_EXT.get(dl_fmt, dl_fmt)
                dir_name = build_output_dir_name(title, source)
                output_path = Path("./files") / dir_name / f"{cid}.{ext}"

                task_entry["contents"].append(
                    {
                        "content_id": cid,
                        "type": ctype,
                        "prompt": str(c.get("prompt") or ""),
                        "options": c.get("options") or {},
                        "output_path": str(output_path),
                        "task_id": None,
                        "artifact_id": None,
                        "status": "pending",
                    }
                )

            run_state["tasks"].append(task_entry)

    atomic_write_json(run_file, run_state)
    print(f"run: {run_file}", flush=True)

    if dry_run:
        print(f"DRY RUN: {run_file}")
        for i, t in enumerate(run_state["tasks"], 1):
            print(f"Task {i}: {t['source']}")
            for c in t["contents"]:
                op = (cwd / c["output_path"]).resolve()
                print(f"  - {c['type']} {c['content_id']} -> {op} skip={op.exists()}")
        return 0

    lang = str(settings.get("language") or "ja")

    # Notification setup
    notify_cfg = settings.get("notify") or {}
    notify_issue: int | None = notify_cfg.get("github_issue")
    notify_repo: str | None = notify_cfg.get("github_repo")

    def notify(msg: str) -> None:
        if notify_issue is not None:
            notify_github(notify_issue, msg, repo=notify_repo)

    instruction_name = instruction_path.name

    # Calculate initial progress for resume detection
    initial_total, initial_completed, initial_skipped, _, _ = summarize_run(run_state)
    initial_done = initial_completed + initial_skipped

    total_tasks = len(run_state["tasks"])
    total_contents = sum(len(t.get("contents", [])) for t in run_state["tasks"])
    notify(f"🔄 バッチ開始: {total_tasks}タスク / {total_contents}コンテンツ ({instruction_name})")

    start_time = time.time()
    stop = threading.Event()
    th = threading.Thread(target=spinner_thread, args=(stop, run_file, initial_done, initial_total), daemon=True)
    th.start()

    try:
        for ti, task in enumerate(run_state["tasks"]):
            # Phase 1: Skip task if all outputs already exist
            all_outputs_exist = all(
                should_skip_output((cwd / c["output_path"]).resolve())
                for c in task["contents"]
            )
            if all_outputs_exist:
                task["status"] = "skipped"
                for c in task["contents"]:
                    c["status"] = "skipped"
                atomic_write_json(run_file, run_state)
                notify(f"⏭️ [{ti+1}/{total_tasks}] 全成果物あり、スキップ ({task['title']})")
                continue  # No notebook creation needed

            try:
                task["status"] = "running"
                atomic_write_json(run_file, run_state)

                # Always create new notebook (aggressive delete policy)
                nb_res, nb_json = run_cmd_json(
                    ["notebooklm", "create", "--json", "--", task["title"]],
                    cwd=cwd,
                    timeout_sec=120,
                )
                if not isinstance(nb_json, dict):
                    task["status"] = "error"
                    task["error"] = err_payload("CREATE_FAILED", res=nb_res)
                    atomic_write_json(run_file, run_state)
                    notify(f"⚠️ スキップ: CREATE_FAILED ({task['title']})")
                    continue

                if parse_auth_error(nb_json):
                    task["status"] = "blocked"
                    task["error"] = err_payload("AUTH_REQUIRED", res=nb_res, detail=nb_json)
                    run_state["status"] = "blocked"
                    run_state["finished_at"] = now_iso()
                    atomic_write_json(run_file, run_state)
                    notify("🚫 AUTH_REQUIRED: 再認証が必要です (`notebooklm login`)")
                    return 3

                notebook_id = None
                nb = nb_json.get("notebook")
                if isinstance(nb, dict):
                    notebook_id = nb.get("id")
                if not notebook_id:
                    task["status"] = "error"
                    task["error"] = err_payload("CREATE_FAILED", res=nb_res, detail=nb_json)
                    atomic_write_json(run_file, run_state)
                    notify(f"⚠️ スキップ: CREATE_FAILED ({task['title']})")
                    continue

                task["notebook_id"] = str(notebook_id)
                atomic_write_json(run_file, run_state)

                # Always add source (aggressive delete policy)
                src_res, src_json = run_cmd_json(
                    ["notebooklm", "source", "add", "-n", task["notebook_id"], "--json", task["source"]],
                    cwd=cwd,
                    timeout_sec=180,
                )
                if not isinstance(src_json, dict):
                    task["status"] = "error"
                    task["error"] = err_payload("SOURCE_ADD_FAILED", res=src_res)
                    atomic_write_json(run_file, run_state)
                    notify(f"⚠️ スキップ: SOURCE_ADD_FAILED ({task['title']})")
                    continue

                if parse_auth_error(src_json):
                    task["status"] = "blocked"
                    task["error"] = err_payload("AUTH_REQUIRED", res=src_res, detail=src_json)
                    run_state["status"] = "blocked"
                    run_state["finished_at"] = now_iso()
                    atomic_write_json(run_file, run_state)
                    notify("🚫 AUTH_REQUIRED: 再認証が必要です (`notebooklm login`)")
                    return 3

                src_obj = src_json.get("source")
                source_id = src_obj.get("id") if isinstance(src_obj, dict) else None
                if not source_id:
                    task["status"] = "error"
                    task["error"] = err_payload("SOURCE_ADD_FAILED", res=src_res, detail=src_json)
                    atomic_write_json(run_file, run_state)
                    notify(f"⚠️ スキップ: SOURCE_ADD_FAILED ({task['title']})")
                    continue

                task["source_id"] = str(source_id)
                atomic_write_json(run_file, run_state)

                wait_res, wait_json = run_cmd_json(
                    ["notebooklm", "source", "wait", "-n", task["notebook_id"], task["source_id"], "--timeout", "600", "--json"],
                    cwd=cwd,
                    timeout_sec=700,
                )
                if wait_res.returncode != 0:
                    task["status"] = "error"
                    task["error"] = err_payload("SOURCE_WAIT_FAILED", res=wait_res, detail=wait_json)
                    atomic_write_json(run_file, run_state)
                    notify(f"⚠️ スキップ: SOURCE_WAIT_FAILED ({task['title']})")
                    continue
                if parse_auth_error(wait_json):
                    task["status"] = "blocked"
                    task["error"] = err_payload("AUTH_REQUIRED", res=wait_res, detail=wait_json)
                    run_state["status"] = "blocked"
                    run_state["finished_at"] = now_iso()
                    atomic_write_json(run_file, run_state)
                    notify("🚫 AUTH_REQUIRED: 再認証が必要です (`notebooklm login`)")
                    return 3
                if isinstance(wait_json, dict) and wait_json.get("status") != "ready":
                    task["status"] = "error"
                    task["error"] = err_payload("SOURCE_NOT_READY", res=wait_res, detail=wait_json)
                    atomic_write_json(run_file, run_state)
                    notify(f"⚠️ スキップ: SOURCE_NOT_READY ({task['title']})")
                    continue

                for ci, content in enumerate(task["contents"]):
                    output_path = (cwd / content["output_path"]).resolve()
                    if should_skip_output(output_path):
                        content["status"] = "skipped"
                        atomic_write_json(run_file, run_state)
                        notify(f"⏭️ [{ti+1}/{total_tasks}] {content['type']} スキップ（既存） ({task['title']})")
                        continue

                    # Phase 4: Removed artifact_id recovery path (notebook deleted, so cannot recover)

                    ctype = str(content["type"])
                    generate_kind = CONTENT_MAP[ctype]["generate"]
                    download_kind = CONTENT_MAP[ctype]["download"]
                    prompt = str(content.get("prompt") or "")
                    options = content.get("options") or {}
                    if not isinstance(options, dict):
                        options = {}

                    content_meta = CONTENT_MAP[ctype]
                    gen_argv = ["notebooklm", "generate", generate_kind, "-n", task["notebook_id"]]
                    if content_meta.get("lang", True):
                        gen_argv.extend(["--language", lang])
                    for k, v in options.items():
                        if v is None or k == "download_format":
                            continue
                        gen_argv.extend([f"--{k}", str(v)])
                    gen_argv.extend(["--json", "--", prompt])

                    gen_res, gen_json = run_cmd_json(gen_argv, cwd=cwd, timeout_sec=120)
                    if gen_res.returncode != 0:
                        # Check if the underlying cause is RATE_LIMITED (fatal)
                        detail_obj = gen_json if isinstance(gen_json, dict) else None
                        if detail_obj and parse_rate_limited(detail_obj.get("detail") if isinstance(detail_obj.get("detail"), dict) else detail_obj):
                            content["status"] = "blocked"
                            content["error"] = err_payload("RATE_LIMITED", res=gen_res, detail=gen_json)
                            task["status"] = "blocked"
                            task["error"] = content["error"]
                            run_state["status"] = "blocked"
                            run_state["finished_at"] = now_iso()
                            atomic_write_json(run_file, run_state)
                            total, completed, skipped, _, _ = summarize_run(run_state)
                            notify(f"🚫 RATE_LIMITED で停止 [{completed + skipped}/{total}完了]")
                            return 3
                        content["status"] = "error"
                        content["error"] = err_payload("GENERATE_FAILED", res=gen_res, detail=gen_json)
                        task["status"] = "error"
                        task["error"] = content["error"]
                        atomic_write_json(run_file, run_state)
                        notify(f"⚠️ スキップ: GENERATE_FAILED - {content['type']} ({task['title']})")
                        break

                    if parse_auth_error(gen_json):
                        content["status"] = "blocked"
                        content["error"] = err_payload("AUTH_REQUIRED", res=gen_res, detail=gen_json)
                        task["status"] = "blocked"
                        run_state["status"] = "blocked"
                        run_state["finished_at"] = now_iso()
                        atomic_write_json(run_file, run_state)
                        notify("🚫 AUTH_REQUIRED: 再認証が必要です (`notebooklm login`)")
                        return 3

                    if parse_rate_limited(gen_json):
                        content["status"] = "blocked"
                        content["error"] = err_payload("RATE_LIMITED", res=gen_res, detail=gen_json)
                        task["status"] = "blocked"
                        run_state["status"] = "blocked"
                        run_state["finished_at"] = now_iso()
                        atomic_write_json(run_file, run_state)
                        total, completed, skipped, _, _ = summarize_run(run_state)
                        notify(f"🚫 RATE_LIMITED で停止 [{completed + skipped}/{total}完了]")
                        return 3

                    artifact_id = None
                    if isinstance(gen_json, dict):
                        artifact = gen_json.get("artifact")
                        if isinstance(artifact, dict) and artifact.get("id"):
                            artifact_id = artifact.get("id")
                        if not artifact_id and gen_json.get("artifact_id"):
                            artifact_id = gen_json.get("artifact_id")
                        # Some types (e.g. flashcards) return task_id as the artifact id
                        if not artifact_id and gen_json.get("task_id"):
                            artifact_id = gen_json.get("task_id")

                    if not artifact_id:
                        # Use artifact_list_type if defined (e.g. flashcards -> flashcard)
                        # because artifact list --type uses different names than generate/download.
                        list_type = content_meta.get("artifact_list_type", generate_kind)
                        artifact_id = latest_artifact_id(cwd, task["notebook_id"], list_type)

                    if not artifact_id:
                        content["status"] = "error"
                        content["error"] = err_payload("ARTIFACT_NOT_FOUND", res=gen_res, detail=gen_json)
                        task["status"] = "error"
                        task["error"] = content["error"]
                        atomic_write_json(run_file, run_state)
                        notify(f"⚠️ スキップ: ARTIFACT_NOT_FOUND - {content['type']} ({task['title']})")
                        break

                    content["artifact_id"] = str(artifact_id)
                    content["status"] = "running"
                    atomic_write_json(run_file, run_state)

                    wait_a_res, wait_a_json = run_cmd_json(
                        ["notebooklm", "artifact", "wait", "-n", task["notebook_id"], content["artifact_id"], "--timeout", "86400", "--interval", "5", "--json"],
                        cwd=cwd,
                        timeout_sec=86500,
                    )
                    if wait_a_res.returncode != 0:
                        content["status"] = "error"
                        content["error"] = err_payload("ARTIFACT_WAIT_FAILED", res=wait_a_res, detail=wait_a_json)
                        task["status"] = "error"
                        task["error"] = content["error"]
                        atomic_write_json(run_file, run_state)
                        notify(f"⚠️ スキップ: ARTIFACT_WAIT_FAILED - {content['type']} ({task['title']})")
                        break
                    if parse_auth_error(wait_a_json):
                        content["status"] = "blocked"
                        content["error"] = err_payload("AUTH_REQUIRED", res=wait_a_res, detail=wait_a_json)
                        task["status"] = "blocked"
                        run_state["status"] = "blocked"
                        run_state["finished_at"] = now_iso()
                        atomic_write_json(run_file, run_state)
                        notify("🚫 AUTH_REQUIRED: 再認証が必要です (`notebooklm login`)")
                        return 3
                    if isinstance(wait_a_json, dict) and wait_a_json.get("status") == "failed":
                        content["status"] = "error"
                        content["error"] = err_payload("ARTIFACT_FAILED", res=wait_a_res, detail=wait_a_json)
                        task["status"] = "error"
                        task["error"] = content["error"]
                        atomic_write_json(run_file, run_state)
                        notify(f"⚠️ スキップ: ARTIFACT_FAILED - {content['type']} ({task['title']})")
                        break

                    ensure_parent_dir(output_path)
                    tmp_path = output_path.with_name(output_path.name + f".__tmp__{run_id}")
                    dl_argv = ["notebooklm", "download", download_kind, "-n", task["notebook_id"], "-a", content["artifact_id"], str(tmp_path)]
                    if content_meta.get("dl_force", True):
                        dl_argv.append("--force")
                    dl_format_default = content_meta.get("dl_format")
                    if dl_format_default is not None:
                        dl_format = str(options.get("download_format", dl_format_default))
                        dl_argv.extend(["--format", dl_format])
                    dl_res = run_cmd(dl_argv, cwd=cwd, timeout_sec=300)
                    if dl_res.returncode != 0:
                        content["status"] = "error"
                        content["error"] = err_payload("DOWNLOAD_FAILED", res=dl_res)
                        task["status"] = "error"
                        task["error"] = content["error"]
                        atomic_write_json(run_file, run_state)
                        notify(f"⚠️ スキップ: DOWNLOAD_FAILED - {content['type']} ({task['title']})")
                        break

                    os.replace(tmp_path, output_path)
                    content["status"] = "completed"
                    atomic_write_json(run_file, run_state)
                    notify(f"📦 [{ti+1}/{total_tasks}] {content['type']} 生成完了 ({task['title']})")

                if all(c.get("status") in ("completed", "skipped") for c in task["contents"]):
                    task["status"] = "completed"
                atomic_write_json(run_file, run_state)

            finally:
                # Aggressive delete: always delete notebook after task ends (success/error/blocked)
                if task.get("notebook_id"):
                    deleted = delete_notebook(cwd, task["notebook_id"])
                    if not deleted:
                        print(f"warning: notebook deletion failed: {task['notebook_id']}", file=sys.stderr, flush=True)

        # Run completion check (skipped/errored tasks count as processed)
        if all(t.get("status") in ("completed", "skipped", "error") for t in run_state["tasks"]):
            has_errors = any(t.get("status") == "error" for t in run_state["tasks"])
            run_state["status"] = "completed_with_errors" if has_errors else "completed"
        run_state["finished_at"] = now_iso()
        atomic_write_json(run_file, run_state)

        total, completed, skipped, _, errored = summarize_run(run_state)
        elapsed = format_elapsed(time.time() - start_time)
        err_part = f" ERR:{errored}" if errored else ""
        notify(f"✅ 完了: NEW:{completed} SKIP:{skipped}{err_part} / {elapsed}経過 ({instruction_name})")

        return 0
    except KeyboardInterrupt:
        run_state["status"] = "aborted"
        run_state["finished_at"] = now_iso()
        atomic_write_json(run_file, run_state)
        total, completed, skipped, _, _ = summarize_run(run_state)
        notify(f"⏹️ 中断: {completed + skipped}/{total}件完了 ({instruction_name})")
        print(f"aborted: {run_file}", file=sys.stderr, flush=True)
        return 130
    finally:
        stop.set()
        th.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
