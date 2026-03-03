from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_local() -> datetime:
    fixed = os.environ.get("AR_FIXED_NOW", "").strip()
    if fixed:
        dt = datetime.fromisoformat(fixed)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone()
    return datetime.now().astimezone()


def _append_log(run_dir: Path, event: dict[str, Any]) -> None:
    log_path = run_dir / "LOG.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _tail_lines(path: Path, n: int) -> list[str]:
    if n <= 0:
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            buf = b""
            block = 4096
            while end > 0 and buf.count(b"\n") <= n:
                step = block if end >= block else end
                end -= step
                f.seek(end)
                buf = f.read(step) + buf
        lines = buf.splitlines()[-n:]
        return [ln.decode("utf-8", errors="replace") for ln in lines]
    except FileNotFoundError:
        return []


def run_status(args: object) -> int:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()
    if not run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {run_dir}\n")
        return 2

    state_path = run_dir / "STATE.json"
    cfg_path = run_dir / "01_CONFIG.json"
    if not state_path.exists():
        sys.stderr.write(f"[ERROR] missing STATE.json: {state_path}\n")
        return 2

    _append_log(
        run_dir,
        {
            "ts": _now_local().isoformat(timespec="seconds"),
            "level": "info",
            "event": "status_called",
            "data": {},
        },
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    cfg: dict[str, Any] = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    sys.stdout.write(f"run_dir: {run_dir}\n")
    if cfg.get("run_id"):
        sys.stdout.write(f"run_id: {cfg.get('run_id')}\n")
    sys.stdout.write(f"status: {state.get('status')}\n")
    sys.stdout.write(f"current_step: {state.get('current_step')}\n")

    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    sys.stdout.write(f"tasks: {len(tasks)}\n")
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = t.get("task_id", "")
        st = t.get("status", "")
        producers = t.get("producers", [])
        if not isinstance(producers, list):
            producers = []
        sys.stdout.write(f"- {tid} [{st}] producers={len(producers)}\n")

    log_path = run_dir / "LOG.jsonl"
    tail = _tail_lines(log_path, 10)
    if tail:
        sys.stdout.write("log_tail (last 10):\n")
        for line in tail:
            sys.stdout.write(line.rstrip("\n") + "\n")
    return 0
