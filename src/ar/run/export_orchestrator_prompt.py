from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TASK_ID_FROM_FILENAME_RE = re.compile(r"^(T-\\d{4})__")


@dataclass(frozen=True)
class ExportOrchestratorPromptInputs:
    run_dir: Path
    runner: str
    profile: str
    out_path: Path


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
    return s or "runner"


def _append_log(run_dir: Path, event: dict[str, Any]) -> None:
    log_path = run_dir / "LOG.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _read_text_limited(path: Path, *, max_chars: int) -> str:
    try:
        txt = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    if len(txt) <= max_chars:
        return txt
    return txt[:max_chars].rstrip() + "\n\n[TRUNCATED]\n"


def _first_heading(md: str) -> str:
    for line in md.splitlines():
        if line.strip().startswith("#"):
            return line.strip()
    return ""


def _task_id_from_filename(name: str) -> str | None:
    m = _TASK_ID_FROM_FILENAME_RE.match(name)
    if not m:
        return None
    return m.group(1)


def _suggest_next_task_ids(existing_task_ids: list[str], *, count: int = 5) -> list[str]:
    nums: list[int] = []
    for tid in existing_task_ids:
        try:
            nums.append(int(tid.split("-", 1)[1]))
        except Exception:
            continue
    start = (max(nums) if nums else 0) + 1
    return [f"T-{start + i:04d}" for i in range(count)]

def _resolve_out_path(run_dir: Path, runner: str, out_path: str) -> Path:
    out_path = out_path.strip()
    if out_path:
        return Path(out_path).expanduser().resolve()
    ts = _now_local().strftime("%Y%m%dT%H%M%S")
    return (run_dir / "12_SUPERVISOR" / "PROMPTS" / f"ORCHESTRATOR_PROMPT_{ts}__{_slugify(runner)}.md").resolve()


def _build_inputs(args: object) -> ExportOrchestratorPromptInputs:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()
    runner = str(getattr(args, "runner", "")).strip()
    profile = str(getattr(args, "profile", "")).strip() or "normal"
    if profile not in ("normal", "guided"):
        raise ValueError("--profile must be one of: normal, guided")
    out_path = _resolve_out_path(run_dir, runner, str(getattr(args, "out_path", "")))
    if not runner:
        raise ValueError("--runner is required")
    return ExportOrchestratorPromptInputs(run_dir=run_dir, runner=runner, profile=profile, out_path=out_path)


def _plan_skeleton(runner: str) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "generated_at": "ISO8601",
            "orchestrator": {"runner": runner, "model": "", "reasoning_effort": "", "notes": ""},
            "assumptions": [{"id": "A1", "text": "", "falsify": ""}],
            "stop_rules": [{"id": "S1", "text": ""}],
            "actions": [
                {
                    "type": "create_task",
                    "task_id": "T-0001",
                    "slug": "example",
                    "reason": "",
                    "task_markdown": "# Task T-0001: Example\\n\\n## Intent\\n...\\n",
                }
            ],
        },
        ensure_ascii=True,
        indent=2,
    )


def _guided_task_markdown_template() -> str:
    return (
        "# Task T-XXXX: <short title>\n\n"
        "## Intent\n"
        "<one paragraph: what is the question and why it matters>\n\n"
        "## Why now (tie to evidence)\n"
        "- Trigger: <conflict/divergence/residual id or filename>\n"
        "- Explanation: <why this task resolves uncertainty>\n\n"
        "## Assumptions & falsification probes\n"
        "- Assumption: <A?>\n"
        "  - Falsify by: <probe that could prove it wrong>\n\n"
        "## Constraints / budget\n"
        "- Time:\n"
        "- Cost:\n"
        "- Recency:\n"
        "- Allowed sources:\n\n"
        "## Deliverables (required)\n"
        "- REPORT.md: <required sections>\n"
        "- SOURCES.json: <required fields>\n"
        "- CLAIMS.json: <required fields>\n"
        "- RESIDUALS.md: <what to put here>\n\n"
        "## Notes\n"
        "<optional>\n"
    )


def _guided_plan_self_check_rubric() -> list[str]:
    return [
        "Output is a single JSON object (no prose, no fences).",
        "`schema_version=1`.",
        "Each action is `create_task` and uses a fresh `T-XXXX`.",
        "Every task has at least one falsification probe.",
        "Every task has explicit deliverables and constraints.",
    ]


def _summarize_comparison_json(path: Path, *, max_tasks: int = 8, max_divergences_per_task: int = 6) -> str:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(obj, dict):
        return ""
    tasks = obj.get("tasks")
    if not isinstance(tasks, list):
        return ""

    lines: list[str] = []
    lines.append("### Divergences summary (`30_MERGE/COMPARISON.json`)\n")
    emitted_tasks = 0
    for t in tasks:
        if emitted_tasks >= max_tasks:
            break
        if not isinstance(t, dict):
            continue
        task_id = str(t.get("task_id") or "").strip()
        divs = t.get("divergences")
        if not isinstance(divs, list) or not divs:
            continue

        emitted_tasks += 1
        # Compact first line (types only).
        types: list[str] = []
        for d in divs:
            if isinstance(d, dict):
                typ = str(d.get("type") or "").strip()
                if typ:
                    types.append(typ)
        uniq_types = sorted({x for x in types if x})
        lines.append(f"- {task_id}: {', '.join(uniq_types) if uniq_types else 'divergences'}")

        n = 0
        for d in divs:
            if n >= max_divergences_per_task:
                lines.append("  - (…more)")
                break
            if not isinstance(d, dict):
                continue
            typ = str(d.get("type") or "").strip()
            summary = str(d.get("summary") or "").strip()
            if not (typ or summary):
                continue
            lines.append(f"  - ({typ or 'other'}) {summary}".rstrip())
            n += 1

    if emitted_tasks == 0:
        lines.append("- (none)\n")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_prompt(inp: ExportOrchestratorPromptInputs) -> str:
    run_dir = inp.run_dir
    now = _now_local().isoformat(timespec="seconds")

    brief = _read_text_limited(run_dir / "00_BRIEF.md", max_chars=40_000).strip()
    cfg_txt = _read_text_limited(run_dir / "01_CONFIG.json", max_chars=40_000).strip()
    state_txt = _read_text_limited(run_dir / "STATE.json", max_chars=40_000).strip()

    tasks_dir = run_dir / "10_TASKS"
    task_lines: list[str] = []
    task_ids: list[str] = []
    if tasks_dir.exists():
        for p in sorted([p for p in tasks_dir.iterdir() if p.is_file() and p.name.endswith(".md")]):
            head = _first_heading(_read_text_limited(p, max_chars=8_000))
            task_lines.append(f"- {p.name}" + (f" — {head}" if head else ""))
            tid = _task_id_from_filename(p.name)
            if tid:
                task_ids.append(tid)
    if not task_lines:
        task_lines = ["- (none)"]
    next_task_ids = _suggest_next_task_ids(task_ids, count=5)

    merge_report = _read_text_limited(run_dir / "30_MERGE" / "REPORT.md", max_chars=20_000).strip()
    conflicts_md = _read_text_limited(run_dir / "30_MERGE" / "CONFLICTS.md", max_chars=20_000).strip()
    residuals_md = _read_text_limited(run_dir / "30_MERGE" / "RESIDUALS.md", max_chars=20_000).strip()
    comparison_json_path = run_dir / "30_MERGE" / "COMPARISON.json"
    comparison_summary = _summarize_comparison_json(comparison_json_path) if comparison_json_path.exists() else ""
    comparison_md = ""
    if inp.profile == "normal":
        comparison_md = _read_text_limited(run_dir / "30_MERGE" / "COMPARISON.md", max_chars=20_000).strip()

    lines: list[str] = []
    lines.append(f"# Orchestrator Prompt (runner={inp.runner})\n")
    lines.append(f"profile: {inp.profile}\n")
    lines.append(f"generated_at: {now}\n")
    lines.append("You are the *orchestrator brain* for a research run bundle.\n")
    lines.append("Your job: propose the next tasks to run, in a way that preserves uncertainty and avoids over-determinism.\n")
    lines.append("## Output rules (STRICT)\n")
    lines.append("- Output **ONLY** one JSON object matching `OrchestratorPlan` schema v1.")
    lines.append("- Do not wrap JSON in markdown fences. Do not add commentary before or after.")
    lines.append("- Only use actions of type `create_task` (no updates, no deletes).")
    lines.append("- Each task must include explicit assumptions and at least one falsification probe.\n")

    if inp.profile == "guided":
        lines.append("## Workflow (guided)\n")
        lines.append("1) Read the context and identify the *top uncertainty drivers*: conflicts, divergences, residuals, missing evidence.")
        lines.append("2) Propose 1–3 follow-up tasks only. Prefer narrow probes over broad re-search.")
        lines.append("3) Tie each task to a concrete trigger: a conflict/divergence/residual/file in `30_MERGE/`.\n")

    lines.append("## OrchestratorPlan schema v1 (example)\n")
    lines.append(_plan_skeleton(inp.runner))
    lines.append("")

    if inp.profile == "guided":
        lines.append("## Task markdown template (use this structure)\n")
        lines.append(_guided_task_markdown_template())
        lines.append("")
        lines.append("## Plan self-check rubric\n")
        for i, item in enumerate(_guided_plan_self_check_rubric(), start=1):
            lines.append(f"{i}) {item}")
        lines.append("")

    lines.append("---\n")
    lines.append("## Context\n")

    lines.append("### Run brief (`00_BRIEF.md`)\n")
    lines.append(brief or "(missing)")
    lines.append("")

    lines.append("### Config (`01_CONFIG.json`)\n")
    lines.append(cfg_txt or "(missing)")
    lines.append("")

    lines.append("### State (`STATE.json`)\n")
    lines.append(state_txt or "(missing)")
    lines.append("")

    lines.append("### Existing tasks (`10_TASKS/*.md`)\n")
    lines.extend(task_lines)
    lines.append("")
    lines.append("### Suggested next task ids\n")
    lines.append("- Use fresh ids (do not reuse existing). Suggested: " + ", ".join(next_task_ids))
    lines.append("")

    if merge_report or conflicts_md or residuals_md or comparison_summary or comparison_md:
        lines.append("### Latest merge artifacts (bounded)\n")
        if merge_report:
            lines.append("#### 30_MERGE/REPORT.md\n")
            lines.append(merge_report)
            lines.append("")
        if comparison_summary:
            lines.append(comparison_summary.strip())
            lines.append("")
        if conflicts_md:
            lines.append("#### 30_MERGE/CONFLICTS.md\n")
            lines.append(conflicts_md)
            lines.append("")
        if residuals_md:
            lines.append("#### 30_MERGE/RESIDUALS.md\n")
            lines.append(residuals_md)
            lines.append("")
        if comparison_md:
            lines.append("#### 30_MERGE/COMPARISON.md\n")
            lines.append(comparison_md)
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def run_export_orchestrator_prompt(args: object) -> int:
    try:
        inp = _build_inputs(args)
    except Exception as e:
        sys.stderr.write(f"[ERROR] invalid export-orchestrator-prompt args: {e}\n")
        return 2

    if not inp.run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {inp.run_dir}\n")
        return 2

    prompt = _render_prompt(inp)
    inp.out_path.parent.mkdir(parents=True, exist_ok=True)
    inp.out_path.write_text(prompt, encoding="utf-8")

    _append_log(
        inp.run_dir,
        {
            "ts": _now_local().isoformat(timespec="seconds"),
            "level": "info",
            "event": "exported_orchestrator_prompt",
            "data": {"runner": inp.runner, "profile": inp.profile, "out_path": str(inp.out_path)},
        },
    )

    sys.stdout.write(str(inp.out_path) + "\n")
    return 0
