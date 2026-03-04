from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationFinding:
    severity: str  # error|warn
    message: str
    path: str = ""


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _atomic_write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _try_update_state(
    run_dir: Path,
    *,
    status: str | None = None,
    current_step: str | None = None,
    preserve_statuses: set[str] | None = None,
) -> None:
    state_path = run_dir / "STATE.json"
    if not state_path.exists():
        return
    try:
        state = _load_json(state_path)
    except Exception:
        return
    if not isinstance(state, dict):
        return
    if status is not None:
        if preserve_statuses and state.get("status") in preserve_statuses:
            pass
        else:
            state["status"] = status
    if current_step is not None:
        state["current_step"] = current_step
    try:
        _atomic_write_json(state_path, state)
    except Exception:
        return


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


def _safe_load_json_array(path: Path) -> list[Any]:
    obj = _load_json(path)
    if isinstance(obj, list):
        return obj
    raise ValueError(f"Expected JSON array: {path}")

_MD_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*?)\s*$")
_HEADING_NORM_RE = re.compile(r"[^a-z0-9]+")


def _normalize_heading(s: str) -> str:
    s = s.strip().lower()
    s = _HEADING_NORM_RE.sub(" ", s).strip()
    return " ".join(s.split())


def _extract_markdown_headings(md: str) -> set[str]:
    out: set[str] = set()
    for line in md.splitlines():
        m = _MD_HEADING_RE.match(line)
        if not m:
            continue
        heading = m.group(2).strip()
        if not heading:
            continue
        out.add(_normalize_heading(heading))
    return out


def _has_heading_prefix(headings: set[str], prefixes: list[str]) -> bool:
    for h in headings:
        for pref in prefixes:
            if h == pref or h.startswith(pref + " "):
                return True
    return False


def _validate_tasks(run_dir: Path) -> list[ValidationFinding]:
    tasks_dir = run_dir / "10_TASKS"
    if not tasks_dir.exists():
        return []

    findings: list[ValidationFinding] = []

    required: list[tuple[str, list[str]]] = [
        ("Intent", ["intent"]),
        ("Deliverables", ["deliverables"]),
        ("Evidence posture", ["evidence posture", "evidence"]),
        ("Contradiction protocol", ["contradiction protocol", "conflict protocol", "contradictions"]),
        ("Try-to-falsify / probes", ["try to falsify", "assumptions falsification probes", "falsification probes", "probes"]),
        ("Output format", ["output format"]),
        ("Stop rules / constraints", ["stop rules", "constraints"]),
    ]

    for p in sorted([x for x in tasks_dir.iterdir() if x.is_file() and x.name.endswith(".md")]):
        try:
            md = p.read_text(encoding="utf-8")
        except Exception:
            findings.append(ValidationFinding("warn", "could not read task file for linting", str(p)))
            continue

        headings = _extract_markdown_headings(md)
        if not headings:
            findings.append(ValidationFinding("warn", "task appears to have no markdown headings", str(p)))
            continue

        missing: list[str] = []
        for label, prefixes in required:
            if not _has_heading_prefix(headings, prefixes):
                missing.append(label)

        if missing:
            findings.append(
                ValidationFinding(
                    "warn",
                    "task missing recommended headings: " + ", ".join(missing),
                    str(p),
                )
            )

    return findings


def _validate_merge_outputs(run_dir: Path, producers: list[Path]) -> list[ValidationFinding]:
    """
    Validate merge artifacts if a merge appears to have been executed.

    We treat the presence of 30_MERGE/COMPARISON.json as "merge ran".
    """
    merge_root = run_dir / "30_MERGE"
    comp_path = merge_root / "COMPARISON.json"
    if not comp_path.exists():
        if producers:
            return [
                ValidationFinding(
                    "warn",
                    "producer outputs exist but merge artifacts are missing (run `ar run merge`)",
                    str(comp_path),
                )
            ]
        return []

    findings: list[ValidationFinding] = []
    required = [
        "REPORT.md",
        "SOURCES.json",
        "CLAIMS.json",
        "CONFLICTS.md",
        "ASSUMPTIONS_AND_PROBES.md",
        "RESIDUALS.md",
        "RECOMMENDATIONS.md",
        "COMPARISON.md",
        "COMPARISON.json",
    ]
    for rel in required:
        p = merge_root / rel
        if not p.exists():
            findings.append(ValidationFinding("error", "missing required merge artifact", str(p)))

    # Non-destructive: merged claims count must be >= total producer claims.
    merged_claims_path = merge_root / "CLAIMS.json"
    if merged_claims_path.exists():
        try:
            merged_claims = _safe_load_json_array(merged_claims_path)
            merged_count = len(merged_claims)
        except Exception:
            merged_count = -1
        total_producer_claims = 0
        for pdir in producers:
            cp = pdir / "CLAIMS.json"
            if not cp.exists():
                continue
            try:
                total_producer_claims += len(_safe_load_json_array(cp))
            except Exception:
                continue
        if merged_count >= 0 and merged_count < total_producer_claims:
            findings.append(
                ValidationFinding(
                    "error",
                    "merge appears destructive (merged claims fewer than producer claims)",
                    str(merged_claims_path),
                )
            )

    # If conflicts were detected, CONFLICTS.md must not be an empty/none placeholder.
    conflicts_expected = False
    try:
        comp = _load_json(comp_path)
        tasks = comp.get("tasks")
        if isinstance(tasks, list):
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                divs = t.get("divergences")
                if not isinstance(divs, list):
                    continue
                for d in divs:
                    if isinstance(d, dict) and d.get("type") == "conflict":
                        conflicts_expected = True
                        break
                if conflicts_expected:
                    break
    except Exception:
        conflicts_expected = False

    conflicts_path = merge_root / "CONFLICTS.md"
    if conflicts_expected and conflicts_path.exists():
        try:
            txt = conflicts_path.read_text(encoding="utf-8").strip().lower()
        except Exception:
            txt = ""
        if not txt or "(none detected)" in txt:
            findings.append(
                ValidationFinding(
                    "error",
                    "conflicts detected but CONFLICTS.md appears empty",
                    str(conflicts_path),
                )
            )

    return findings

def run_validate(args: object) -> int:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()
    if not run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {run_dir}\n")
        return 30

    findings: list[ValidationFinding] = []
    findings.extend(_validate_run_structure(run_dir))
    findings.extend(_validate_tasks(run_dir))

    _try_update_state(run_dir, current_step="validate")

    _append_log(
        run_dir,
        {
            "ts": _now_local().isoformat(timespec="seconds"),
            "level": "info",
            "event": "validate_started",
            "data": {},
        },
    )

    producers = _iter_producer_dirs(run_dir)
    for pdir in producers:
        findings.extend(_validate_producer_dir(pdir))

    findings.extend(_validate_required_runner_presence(run_dir))
    findings.extend(_validate_merge_outputs(run_dir, producers))

    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]

    # Human-readable output; scripts can parse later if needed.
    if warns:
        for w in warns:
            sys.stdout.write(f"[WARN] {w.message}: {w.path}\n")

    if errors:
        for e in errors:
            sys.stderr.write(f"[ERROR] {e.message}: {e.path}\n")
        _append_log(
            run_dir,
            {
                "ts": _now_local().isoformat(timespec="seconds"),
                "level": "error",
                "event": "validate_finished",
                "data": {"errors": len(errors), "warns": len(warns)},
            },
        )
        _try_update_state(run_dir, status="failed")
        return 30

    # If there are no producer outputs, the run is structurally valid but incomplete.
    if not producers:
        sys.stdout.write("[INFO] structurally valid run bundle; no producer outputs yet (incomplete)\n")
    else:
        sys.stdout.write("[OK] structurally valid run bundle\n")
    _append_log(
        run_dir,
        {
            "ts": _now_local().isoformat(timespec="seconds"),
            "level": "info",
            "event": "validate_finished",
            "data": {"errors": 0, "warns": len(warns)},
        },
    )
    _try_update_state(run_dir, status="validated", preserve_statuses={"partial"})
    return 0
