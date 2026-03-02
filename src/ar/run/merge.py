from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProducerSummary:
    producer_id: str
    runner: str
    model: str
    reasoning_effort: str
    status: str
    elapsed_seconds: float | None
    token_usage: dict[str, Any]
    sources_count: int
    claims_count: int


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_load_json_array(path: Path) -> list[Any]:
    obj = _load_json(path)
    if isinstance(obj, list):
        return obj
    raise ValueError(f"Expected JSON array: {path}")


def _iter_task_dirs(run_dir: Path) -> list[Path]:
    root = run_dir / "20_WORK"
    if not root.exists():
        return []
    return sorted([p for p in root.iterdir() if p.is_dir()])


def _iter_producer_dirs(task_dir: Path) -> list[Path]:
    return sorted([p for p in task_dir.iterdir() if p.is_dir()])


def _summarize_producer(producer_dir: Path, *, allow_missing_registers: bool) -> ProducerSummary:
    prov_path = producer_dir / "PROVENANCE.json"
    prov = _load_json(prov_path)

    runner = str(prov.get("runner") or "")
    producer_id = str(prov.get("producer_id") or producer_dir.name)

    sources_count = 0
    claims_count = 0

    sources_path = producer_dir / "SOURCES.json"
    claims_path = producer_dir / "CLAIMS.json"
    if sources_path.exists():
        sources_count = len(_safe_load_json_array(sources_path))
    elif not allow_missing_registers:
        raise FileNotFoundError(str(sources_path))

    if claims_path.exists():
        claims_count = len(_safe_load_json_array(claims_path))
    elif not allow_missing_registers:
        raise FileNotFoundError(str(claims_path))

    return ProducerSummary(
        producer_id=producer_id,
        runner=runner,
        model=str(prov.get("model") or ""),
        reasoning_effort=str(prov.get("reasoning_effort") or ""),
        status=str(prov.get("status") or ""),
        elapsed_seconds=prov.get("elapsed_seconds"),
        token_usage=prov.get("token_usage") or {},
        sources_count=sources_count,
        claims_count=claims_count,
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def run_merge(args: object) -> int:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()
    allow_missing = bool(getattr(args, "allow_missing_registers", False))

    if not run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {run_dir}\n")
        return 21

    work_root = run_dir / "20_WORK"
    merge_root = run_dir / "30_MERGE"
    if not work_root.exists():
        sys.stderr.write(f"[ERROR] missing 20_WORK/: {work_root}\n")
        return 21
    merge_root.mkdir(parents=True, exist_ok=True)

    now = _now_local()

    comparison_tasks: list[dict[str, Any]] = []
    comparison_md_lines: list[str] = ["# Producer Comparison\n"]

    for task_dir in _iter_task_dirs(run_dir):
        task_id = task_dir.name
        producers: list[dict[str, Any]] = []

        comparison_md_lines.append(f"## {task_id}\n")
        comparison_md_lines.append("| producer_id | runner | model | reasoning | status | elapsed_s | tokens_total | sources | claims |")
        comparison_md_lines.append("|---|---|---|---|---|---:|---:|---:|---:|")

        for producer_dir in _iter_producer_dirs(task_dir):
            try:
                s = _summarize_producer(producer_dir, allow_missing_registers=allow_missing)
            except Exception as e:
                sys.stderr.write(f"[ERROR] failed to summarize {producer_dir}: {e}\n")
                return 21

            tu = s.token_usage or {}
            tokens_total = tu.get("total")
            producers.append(
                {
                    "producer_id": s.producer_id,
                    "runner": s.runner,
                    "model": s.model,
                    "reasoning_effort": s.reasoning_effort,
                    "status": s.status,
                    "elapsed_seconds": s.elapsed_seconds,
                    "token_usage": tu,
                    "counts": {"sources": s.sources_count, "claims": s.claims_count},
                    "notes": "",
                }
            )
            comparison_md_lines.append(
                f"| {s.producer_id} | {s.runner} | {s.model} | {s.reasoning_effort} | {s.status} | "
                f"{'' if s.elapsed_seconds is None else f'{s.elapsed_seconds:.1f}'} | "
                f"{'' if tokens_total is None else tokens_total} | {s.sources_count} | {s.claims_count} |"
            )

        comparison_md_lines.append("")
        comparison_tasks.append({"task_id": task_id, "producers": producers, "divergences": []})

    comp_json = {
        "schema_version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "tasks": comparison_tasks,
    }

    _write_json(merge_root / "COMPARISON.json", comp_json)
    _write_text(merge_root / "COMPARISON.md", "\n".join(comparison_md_lines).strip() + "\n")

    # Minimal merge placeholders; richer synthesis implemented in later commits.
    _write_text(
        merge_root / "REPORT.md",
        "# Synthesis Report (stub)\n\nThis run has been merged for comparison artifacts.\n",
    )
    _write_json(merge_root / "SOURCES.json", [])
    _write_json(merge_root / "CLAIMS.json", [])
    _write_text(merge_root / "CONFLICTS.md", "# Conflicts\n\n(none detected by stub merge)\n")
    _write_text(merge_root / "ASSUMPTIONS_AND_PROBES.md", "# Assumptions and Probes\n\n(stub)\n")
    _write_text(merge_root / "RESIDUALS.md", "# Residuals\n\n(stub)\n")
    _write_text(merge_root / "RECOMMENDATIONS.md", "# Recommendations\n\n(stub)\n")

    sys.stdout.write("[OK] merged (comparison artifacts written)\n")
    return 0

