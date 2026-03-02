from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ImportInputs:
    run_dir: Path
    task_id: str
    runner: str
    producer: str
    report_path: Path | None
    sources_path: Path | None
    claims_path: Path | None
    residuals_path: Path | None
    model: str
    reasoning: str


def _now_local() -> datetime:
    fixed = os.environ.get("AR_FIXED_NOW", "").strip()
    if fixed:
        dt = datetime.fromisoformat(fixed)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone()
    return datetime.now().astimezone()


def _safe_read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _safe_read_json_array(path: Path) -> list[Any]:
    obj = json.loads(_safe_read_text(path))
    if isinstance(obj, list):
        return obj
    raise ValueError(f"Expected JSON array in {path}")


def _pick_default_producer(run_dir: Path, task_id: str, runner: str) -> str:
    base = f"{runner}:manual-01"
    p = run_dir / "20_WORK" / task_id / base
    if not p.exists():
        return base
    i = 2
    while True:
        cand = f"{runner}:manual-{i:02d}"
        if not (run_dir / "20_WORK" / task_id / cand).exists():
            return cand
        i += 1


def _load_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_log(run_dir: Path, event: dict[str, Any]) -> None:
    log_path = run_dir / "LOG.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _normalize_task_id(task_id: str) -> str:
    task_id = task_id.strip()
    if not task_id:
        raise ValueError("task_id is required")
    return task_id


def _normalize_runner(runner: str) -> str:
    runner = runner.strip()
    if not runner:
        raise ValueError("runner is required")
    return runner


def _resolve_optional_path(p: str) -> Path | None:
    p = p.strip()
    if not p:
        return None
    return Path(p).expanduser().resolve()


def _build_import_inputs(args: object) -> ImportInputs:
    run_dir = Path(str(getattr(args, "run_dir"))).expanduser().resolve()
    task_id = _normalize_task_id(str(getattr(args, "task")))
    runner = _normalize_runner(str(getattr(args, "runner")))

    producer = str(getattr(args, "producer", "")).strip()
    if not producer:
        producer = _pick_default_producer(run_dir, task_id, runner)

    return ImportInputs(
        run_dir=run_dir,
        task_id=task_id,
        runner=runner,
        producer=producer,
        report_path=_resolve_optional_path(str(getattr(args, "report_path", ""))),
        sources_path=_resolve_optional_path(str(getattr(args, "sources_path", ""))),
        claims_path=_resolve_optional_path(str(getattr(args, "claims_path", ""))),
        residuals_path=_resolve_optional_path(str(getattr(args, "residuals_path", ""))),
        model=str(getattr(args, "model", "")).strip(),
        reasoning=str(getattr(args, "reasoning", "")).strip(),
    )


def run_import(args: object) -> int:
    try:
        inp = _build_import_inputs(args)
    except Exception as e:
        sys.stderr.write(f"[ERROR] invalid import args: {e}\n")
        return 2

    if not inp.run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {inp.run_dir}\n")
        return 2

    if not (inp.run_dir / "STATE.json").exists():
        sys.stderr.write(f"[ERROR] missing STATE.json: {inp.run_dir}\n")
        return 2

    now = _now_local()

    producer_dir = inp.run_dir / "20_WORK" / inp.task_id / inp.producer
    producer_dir.mkdir(parents=True, exist_ok=True)

    # REPORT.md
    if inp.report_path:
        report_text = _safe_read_text(inp.report_path)
    else:
        report_text = sys.stdin.read()
    (producer_dir / "REPORT.md").write_text(report_text, encoding="utf-8")

    # SOURCES.json / CLAIMS.json placeholders if missing.
    if inp.sources_path:
        sources = _safe_read_json_array(inp.sources_path)
        (producer_dir / "SOURCES.json").write_text(json.dumps(sources, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    else:
        (producer_dir / "SOURCES.json").write_text("[]\n", encoding="utf-8")

    if inp.claims_path:
        claims = _safe_read_json_array(inp.claims_path)
        (producer_dir / "CLAIMS.json").write_text(json.dumps(claims, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    else:
        (producer_dir / "CLAIMS.json").write_text("[]\n", encoding="utf-8")

    if inp.residuals_path:
        residuals = _safe_read_text(inp.residuals_path)
        (producer_dir / "RESIDUALS.md").write_text(residuals, encoding="utf-8")
    else:
        (producer_dir / "RESIDUALS.md").write_text("none\n", encoding="utf-8")

    prov = {
        "producer_id": inp.producer,
        "runner": inp.runner,
        "model": inp.model,
        "reasoning_effort": inp.reasoning,
        "started_at": now.isoformat(timespec="seconds"),
        "finished_at": now.isoformat(timespec="seconds"),
        "elapsed_seconds": 0.0,
        "status": "ok",
        "token_usage": {
            "input": None,
            "cached_input": None,
            "output": None,
            "reasoning": None,
            "total": None,
        },
        "exceptions": [],
        "notes": "",
    }
    _atomic_write_json(producer_dir / "PROVENANCE.json", prov)

    # Update STATE.json (single-writer behavior: command is supervisor).
    state_path = inp.run_dir / "STATE.json"
    state = _load_state(state_path)
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
        state["tasks"] = tasks

    task_row = None
    for t in tasks:
        if isinstance(t, dict) and t.get("task_id") == inp.task_id:
            task_row = t
            break

    if task_row is None:
        task_row = {"task_id": inp.task_id, "status": "done", "producers": []}
        tasks.append(task_row)

    producers = task_row.get("producers")
    if not isinstance(producers, list):
        producers = []
        task_row["producers"] = producers
    if inp.producer not in producers:
        producers.append(inp.producer)

    _atomic_write_json(state_path, state)

    _append_log(
        inp.run_dir,
        {
            "ts": now.isoformat(timespec="seconds"),
            "level": "info",
            "event": "imported_output",
            "data": {"task_id": inp.task_id, "producer_id": inp.producer, "runner": inp.runner},
        },
    )

    sys.stdout.write(str(producer_dir) + "\n")
    return 0

