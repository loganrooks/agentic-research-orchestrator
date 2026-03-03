from __future__ import annotations

import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class CodexDefaults:
    model: str
    reasoning: str
    sandbox: str
    timeout_seconds: int
    max_workers: int


def _now_local() -> datetime:
    fixed = os.environ.get("AR_FIXED_NOW", "").strip()
    if fixed:
        # fromisoformat supports offsets like -05:00.
        dt = datetime.fromisoformat(fixed)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone()
    return datetime.now().astimezone()


def _fixed_run_id() -> str:
    fixed = os.environ.get("AR_FIXED_RUN_ID", "").strip()
    if fixed:
        return fixed
    # 10 hex chars by default (5 bytes).
    return secrets.token_hex(5)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "run"


def _derive_slug_from_goal(goal: str) -> str:
    goal = " ".join(goal.strip().split())
    if not goal:
        return "run"
    # Take the first ~8 words to avoid path spam.
    words = goal.split(" ")[:8]
    return _slugify(" ".join(words))[:60]


def _resolve_runs_root(arg_runs_root: str) -> Path:
    if arg_runs_root.strip():
        return Path(arg_runs_root).expanduser().resolve()
    env_root = os.environ.get("AR_RUNS_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return (Path.home() / ".ar" / "runs").resolve()


def _write_text(path: Path, text: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, obj: object, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _append_log(path: Path, event: dict[str, object], *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def run_scaffold(args: object) -> int:
    """
    Create a new run bundle.

    The args object is produced by argparse; we treat it as duck-typed.
    """

    runs_root = _resolve_runs_root(getattr(args, "runs_root", ""))
    goal = str(getattr(args, "goal", "")).strip()
    slug = str(getattr(args, "slug", "")).strip()
    dry_run = bool(getattr(args, "dry_run", False))
    rebuild = bool(getattr(args, "rebuild", False))

    if not slug and not goal:
        sys.stderr.write("[ERROR] scaffold requires --slug or --goal\n")
        return 2

    if not slug:
        slug = _derive_slug_from_goal(goal)
    slug = _slugify(slug)

    now = _now_local()
    date_dir = now.date().isoformat()
    ts = now.strftime("%Y%m%dT%H%M%S")
    run_id = _fixed_run_id()

    run_dir = runs_root / date_dir / f"{ts}__{slug}__{run_id}"

    if run_dir.exists():
        if not rebuild:
            sys.stderr.write(f"[ERROR] run dir exists (use --rebuild): {run_dir}\n")
            return 3
        if not dry_run:
            bak = run_dir.with_name(run_dir.name + f"__bak__{_now_local().strftime('%Y%m%dT%H%M%S')}")
            run_dir.rename(bak)

    # Runner plan defaults.
    required = list(getattr(args, "required_runner", []) or [])
    optional = list(getattr(args, "optional_runner", []) or [])
    if not required:
        required = ["codex"]
    if not optional:
        optional = ["claude_desktop", "cowork", "gemini_deep_research", "gemini_cli"]

    codex = CodexDefaults(
        model=str(getattr(args, "codex_model", "gpt-5.2")),
        reasoning=str(getattr(args, "codex_reasoning", "high")),
        sandbox=str(getattr(args, "codex_sandbox", "read-only")),
        timeout_seconds=int(getattr(args, "codex_timeout_seconds", 1800)),
        max_workers=int(getattr(args, "codex_max_workers", 3)),
    )

    targets_in = list(getattr(args, "targets", []) or [])
    targets = []
    for t in targets_in:
        if not t:
            continue
        p = Path(t).expanduser().resolve()
        targets.append({"path": str(p), "label": p.name})

    # Create structure.
    if not dry_run:
        (run_dir / "10_TASKS").mkdir(parents=True, exist_ok=True)
        (run_dir / "20_WORK").mkdir(parents=True, exist_ok=True)
        (run_dir / "30_MERGE").mkdir(parents=True, exist_ok=True)

    targets_md = "\n".join([f"- {x['path']}" for x in targets]) if targets else "- (none)"

    brief = f"""# Research Run Brief

## Decision / Goal
{goal or "<fill this in>"}

## Motivating context
<why are we doing this now; what is failing today?>

## Non-goals
- <explicitly list what this run will NOT attempt>

## Constraints
- time:
- cost:
- recency:
- allowed sources:

## Targets
{targets_md}

## Priors + what would change your mind
<state priors and what evidence would force revision>

## Output preferences
<depth, style, audience>
"""

    cfg = {
        "schemas_version": 1,
        "run_id": run_id,
        "created_at": now.isoformat(timespec="seconds"),
        "created_by": os.environ.get("USER", ""),
        "targets": targets,
        "runner_plan": {"required": required, "optional": optional},
        "codex": {
            "model_default": codex.model,
            "reasoning_default": codex.reasoning,
            "sandbox_default": codex.sandbox,
            "timeout_seconds": codex.timeout_seconds,
            "max_workers": codex.max_workers,
        },
        "quality_policy": {
            "preserve_conflicts": True,
            "require_residuals": True,
            "allow_exceptions": True,
            "citation_preference": "links_ok",
        },
    }

    state = {
        "status": "scaffolded",
        "current_step": "scaffold",
        "started_at": now.isoformat(timespec="seconds"),
        "finished_at": "",
        "tasks": [],
        "exceptions": [],
    }

    _write_text(run_dir / "00_BRIEF.md", brief, dry_run=dry_run)
    _write_json(run_dir / "01_CONFIG.json", cfg, dry_run=dry_run)
    _write_json(run_dir / "STATE.json", state, dry_run=dry_run)

    # Touch log file and write initial event.
    log_path = run_dir / "LOG.jsonl"
    if not dry_run:
        log_path.touch(exist_ok=True)
    _append_log(
        log_path,
        {
            "ts": now.isoformat(timespec="seconds"),
            "level": "info",
            "event": "scaffolded",
            "data": {"run_dir": str(run_dir)},
        },
        dry_run=dry_run,
    )

    # Emit run dir for operators.
    sys.stdout.write(str(run_dir) + "\n")
    return 0
