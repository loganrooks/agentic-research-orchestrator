from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


_TASK_ID_RE = re.compile(r"^T-\d{4}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class _CreateTaskAction:
    task_id: str
    slug: str
    reason: str
    task_markdown: str


def _now_local() -> datetime:
    fixed = os.environ.get("AR_FIXED_NOW", "").strip()
    if fixed:
        dt = datetime.fromisoformat(fixed)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone()
    return datetime.now().astimezone()


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "task"


def _append_log(run_dir: Path, event: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    log_path = run_dir / "LOG.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _atomic_write_json(path: Path, obj: object, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_plan_json(plan_path: str) -> Any:
    plan_path = plan_path.strip()
    if plan_path == "-":
        raw = sys.stdin.read()
        return json.loads(raw)
    return json.loads(Path(plan_path).expanduser().resolve().read_text(encoding="utf-8"))


def _validate_task_id(task_id: str) -> str:
    task_id = task_id.strip()
    if not _TASK_ID_RE.match(task_id):
        raise ValueError(f"invalid task_id: {task_id!r} (expected T-0001 style)")
    return task_id


def _validate_plan_schema(obj: Any) -> tuple[dict[str, Any], list[_CreateTaskAction]]:
    if not isinstance(obj, dict):
        raise ValueError("plan must be a JSON object")

    sv = obj.get("schema_version")
    if sv != 1:
        raise ValueError("plan.schema_version must be 1")

    actions = obj.get("actions")
    if not isinstance(actions, list):
        raise ValueError("plan.actions must be a list")

    out_actions: list[_CreateTaskAction] = []
    seen: set[str] = set()
    for a in actions:
        if not isinstance(a, dict):
            raise ValueError("plan.actions items must be objects")
        typ = str(a.get("type") or "").strip()
        if typ != "create_task":
            raise ValueError(f"unsupported action type: {typ!r} (only create_task is supported)")

        task_id = _validate_task_id(str(a.get("task_id") or ""))
        if task_id in seen:
            raise ValueError(f"duplicate task_id in plan: {task_id}")
        seen.add(task_id)

        slug = _slugify(str(a.get("slug") or ""))
        reason = str(a.get("reason") or "").strip()
        task_markdown = str(a.get("task_markdown") or "")
        if not task_markdown.strip():
            raise ValueError(f"task_markdown is required for {task_id}")

        out_actions.append(_CreateTaskAction(task_id=task_id, slug=slug, reason=reason, task_markdown=task_markdown))

    return obj, out_actions


def _find_existing_task_files(tasks_dir: Path, task_id: str) -> list[Path]:
    if not tasks_dir.exists():
        return []
    out: list[Path] = []
    prefix = f"{task_id}__"
    for p in sorted(tasks_dir.iterdir()):
        if not p.is_file() or not p.name.endswith(".md"):
            continue
        if p.name.startswith(prefix):
            out.append(p)
    return out


def _safe_write_task(tasks_dir: Path, action: _CreateTaskAction, *, dry_run: bool) -> tuple[Path, str]:
    """
    Returns (path, status) where status is one of: created|skipped.
    """
    task_id = action.task_id
    out_path = (tasks_dir / f"{task_id}__{action.slug}.md").resolve()
    tasks_root = tasks_dir.resolve()
    if tasks_root not in out_path.parents:
        raise ValueError(f"refusing to write outside 10_TASKS/: {out_path}")

    desired = action.task_markdown.strip() + "\n"

    existing = _find_existing_task_files(tasks_dir, task_id)
    if existing:
        # Idempotency: if an identical file already exists, skip.
        for p in existing:
            try:
                if p.read_text(encoding="utf-8") == desired:
                    return p, "skipped"
            except Exception:
                continue
        raise ValueError(f"task already exists for {task_id}: {', '.join([str(p) for p in existing])}")

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(desired, encoding="utf-8")
    return out_path, "created"


def _update_state_tasks(run_dir: Path, task_ids: list[str], *, dry_run: bool) -> None:
    state_path = run_dir / "STATE.json"
    if not state_path.exists():
        raise FileNotFoundError(str(state_path))
    state = _load_json(state_path)
    if not isinstance(state, dict):
        raise ValueError("STATE.json must be an object")

    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
        state["tasks"] = tasks

    seen = {t.get("task_id") for t in tasks if isinstance(t, dict)}
    for tid in task_ids:
        if tid in seen:
            continue
        tasks.append({"task_id": tid, "status": "pending", "producers": []})
        seen.add(tid)

    state["current_step"] = "apply-plan"
    _atomic_write_json(state_path, state, dry_run=dry_run)


def run_apply_plan(args: object) -> int:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()
    plan_path = str(getattr(args, "plan_path", "")).strip()
    dry_run = bool(getattr(args, "dry_run", False))
    source = str(getattr(args, "source", "apply-plan") or "apply-plan").strip() or "apply-plan"

    if not run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {run_dir}\n")
        return 2
    if not plan_path:
        sys.stderr.write("[ERROR] missing --plan-path\n")
        return 2

    try:
        plan_obj = _read_plan_json(plan_path)
        plan_obj, actions = _validate_plan_schema(plan_obj)
    except Exception as e:
        sys.stderr.write(f"[ERROR] invalid plan: {e}\n")
        return 2

    tasks_dir = run_dir / "10_TASKS"
    if not tasks_dir.exists():
        sys.stderr.write(f"[ERROR] missing 10_TASKS/: {tasks_dir}\n")
        return 2

    now = _now_local()
    orch = plan_obj.get("orchestrator") if isinstance(plan_obj.get("orchestrator"), dict) else {}
    orch_runner = str((orch or {}).get("runner") or "unknown").strip() or "unknown"

    plan_store_dir = run_dir / "12_SUPERVISOR" / "PLANS"
    plan_store_path = plan_store_dir / f"PLAN_{now.strftime('%Y%m%dT%H%M%S')}__{_slugify(orch_runner)}.json"
    if not dry_run:
        plan_store_dir.mkdir(parents=True, exist_ok=True)
        plan_store_path.write_text(json.dumps(plan_obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    created: list[str] = []
    skipped: list[str] = []
    reasons: dict[str, str] = {}
    try:
        # Preflight: ensure no action will fail before writing anything (except plan snapshot).
        for a in actions:
            _safe_write_task(tasks_dir, a, dry_run=True)

        # Apply writes.
        for a in actions:
            out_path, status = _safe_write_task(tasks_dir, a, dry_run=dry_run)
            reasons[a.task_id] = a.reason
            if status == "created":
                created.append(str(out_path))
            else:
                skipped.append(str(out_path))

        _update_state_tasks(run_dir, [a.task_id for a in actions], dry_run=dry_run)
    except Exception as e:
        _append_log(
            run_dir,
            {
                "ts": _now_local().isoformat(timespec="seconds"),
                "level": "error",
                "event": "plan_apply_failed",
                "data": {"source": source, "plan_snapshot": str(plan_store_path), "error": str(e)},
            },
            dry_run=dry_run,
        )
        sys.stderr.write(f"[ERROR] apply failed: {e}\n")
        return 2

    _append_log(
        run_dir,
        {
            "ts": _now_local().isoformat(timespec="seconds"),
            "level": "info",
            "event": "task_generation",
            "data": {
                "source": source,
                "plan_snapshot": str(plan_store_path),
                "orchestrator_runner": orch_runner,
                "tasks_created": [Path(p).name for p in created],
                "tasks_skipped": [Path(p).name for p in skipped],
                "reasons": reasons,
            },
        },
        dry_run=dry_run,
    )

    for p in created:
        sys.stdout.write(p + "\n")
    if not created:
        sys.stdout.write("[OK] no tasks created (idempotent apply)\n")
    return 0
