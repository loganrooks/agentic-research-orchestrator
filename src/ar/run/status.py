from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


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
    return 0

