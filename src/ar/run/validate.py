from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationFinding:
    severity: str  # error|warn
    message: str
    path: str = ""


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_producer_dirs(run_dir: Path) -> list[Path]:
    root = run_dir / "20_WORK"
    if not root.exists():
        return []
    out: list[Path] = []
    for task_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
        for producer_dir in sorted([p for p in task_dir.iterdir() if p.is_dir()]):
            out.append(producer_dir)
    return out


def _validate_run_structure(run_dir: Path) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    required = [
        "00_BRIEF.md",
        "01_CONFIG.json",
        "STATE.json",
        "LOG.jsonl",
        "10_TASKS",
        "20_WORK",
        "30_MERGE",
    ]
    for rel in required:
        p = run_dir / rel
        if not p.exists():
            findings.append(ValidationFinding("error", "missing required run artifact", str(p)))
    return findings


def _validate_producer_dir(producer_dir: Path) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    required = ["PROVENANCE.json", "REPORT.md", "SOURCES.json", "CLAIMS.json", "RESIDUALS.md"]
    for rel in required:
        p = producer_dir / rel
        if not p.exists():
            findings.append(ValidationFinding("error", "missing required producer artifact", str(p)))
    return findings


def _validate_required_runner_presence(run_dir: Path) -> list[ValidationFinding]:
    """
    If config requires certain runners, and we have any producer outputs,
    warn when none of those required runners produced output.
    """
    cfg_path = run_dir / "01_CONFIG.json"
    if not cfg_path.exists():
        return []
    cfg = _load_json(cfg_path)
    runner_plan = cfg.get("runner_plan")
    if not isinstance(runner_plan, dict):
        return []
    required = runner_plan.get("required", [])
    if not isinstance(required, list) or not required:
        return []

    producers = _iter_producer_dirs(run_dir)
    if not producers:
        return []

    required_set = {str(x) for x in required if str(x).strip()}
    seen_required = False
    for pdir in producers:
        prov_path = pdir / "PROVENANCE.json"
        if not prov_path.exists():
            continue
        try:
            prov = _load_json(prov_path)
        except Exception:
            continue
        runner = prov.get("runner")
        if isinstance(runner, str) and runner in required_set:
            seen_required = True
            break
        # fallback: producer_id prefix
        pid = prov.get("producer_id")
        if isinstance(pid, str):
            prefix = pid.split(":", 1)[0]
            if prefix in required_set:
                seen_required = True
                break

    if not seen_required:
        return [
            ValidationFinding(
                "warn",
                "no outputs from required runners; run may be incomplete (optional runners are allowed)",
                str(cfg_path),
            )
        ]
    return []


def run_validate(args: object) -> int:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()
    if not run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {run_dir}\n")
        return 30

    findings: list[ValidationFinding] = []
    findings.extend(_validate_run_structure(run_dir))

    producers = _iter_producer_dirs(run_dir)
    for pdir in producers:
        findings.extend(_validate_producer_dir(pdir))

    findings.extend(_validate_required_runner_presence(run_dir))

    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]

    # Human-readable output; scripts can parse later if needed.
    if warns:
        for w in warns:
            sys.stdout.write(f"[WARN] {w.message}: {w.path}\n")

    if errors:
        for e in errors:
            sys.stderr.write(f"[ERROR] {e.message}: {e.path}\n")
        return 30

    # If there are no producer outputs, the run is structurally valid but incomplete.
    if not producers:
        sys.stdout.write("[INFO] structurally valid run bundle; no producer outputs yet (incomplete)\n")
    else:
        sys.stdout.write("[OK] structurally valid run bundle\n")
    return 0

