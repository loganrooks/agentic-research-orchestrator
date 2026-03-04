from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ExportPromptsInputs:
    run_dir: Path
    runner: str
    out_dir: Path


def _now_local() -> datetime:
    fixed = os.environ.get("AR_FIXED_NOW", "").strip()
    if fixed:
        dt = datetime.fromisoformat(fixed)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone()
    return datetime.now().astimezone()


def _append_log(run_dir: Path, event: dict[str, object]) -> None:
    log_path = run_dir / "LOG.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _normalize_runner(runner: str) -> str:
    runner = runner.strip()
    if not runner:
        raise ValueError("runner is required")
    return runner


def _resolve_out_dir(run_dir: Path, runner: str, out_dir: str) -> Path:
    out_dir = out_dir.strip()
    if out_dir:
        return Path(out_dir).expanduser().resolve()
    return (run_dir / "11_EXPORT" / runner).resolve()


def _build_inputs(args: object) -> ExportPromptsInputs:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()
    runner = _normalize_runner(str(getattr(args, "runner", "")))
    out_dir = _resolve_out_dir(run_dir, runner, str(getattr(args, "out_dir", "")))
    return ExportPromptsInputs(run_dir=run_dir, runner=runner, out_dir=out_dir)


def _runner_preamble(runner: str) -> str:
    common = [
        "## Output requirements (report-first)\n",
        "- Produce one primary markdown report with citations/links where possible.",
        "- Include a `Residuals / Open Questions` section.",
        "- Prefer JSON registers in fenced code blocks; table fallback is acceptable.",
        "",
        "### Registers (if possible)\n",
        "Provide these as JSON arrays in fenced code blocks labeled exactly as follows:",
        "",
        "Notes for CLAIMS.json:",
        "- `claim_id` values are producer-local (often `C-0001`, `C-0002`, ...).",
        "- If you want cross-runner agreements/conflicts to be detected conservatively, include a stable `topic_key` (short string) per claim and keep it consistent within this task across producers.",
        "",
        "SOURCES.json:",
        "```json",
        "[]",
        "```",
        "",
        "CLAIMS.json:",
        "```json",
        "[]",
        "```",
        "",
    ]

    runner = runner.strip()
    if runner == "cowork":
        extra = [
            "## Cowork-specific guidance\n",
            "- Act as a research orchestrator: delegate to scoped subagents, then merge deterministically.",
            "- Preserve conflicts instead of averaging them away.",
            "",
        ]
    elif runner in ("claude_code", "claude_desktop", "gemini_deep_research", "gemini_cli"):
        extra = [
            "## Runner-specific guidance\n",
            "- Do not assume you can write multiple files; embed registers in your single report response.",
            "",
        ]
    elif runner == "codex":
        extra = [
            "## Codex-specific guidance\n",
            "- If you cannot write files, embed registers in your final response as shown above.",
            "",
        ]
    else:
        raise ValueError(f"unsupported runner: {runner}")

    lines = [f"# Exported Prompt (runner={runner})\n", *extra, *common, "---\n", "## Canonical task\n"]
    return "\n".join(lines)


def run_export_prompts(args: object) -> int:
    try:
        inp = _build_inputs(args)
    except Exception as e:
        sys.stderr.write(f"[ERROR] invalid export-prompts args: {e}\n")
        return 2

    if not inp.run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {inp.run_dir}\n")
        return 2

    tasks_dir = inp.run_dir / "10_TASKS"
    if not tasks_dir.exists():
        sys.stderr.write(f"[ERROR] missing 10_TASKS/: {tasks_dir}\n")
        return 2

    try:
        preamble = _runner_preamble(inp.runner)
    except Exception as e:
        sys.stderr.write(f"[ERROR] {e}\n")
        return 2

    task_paths = sorted([p for p in tasks_dir.iterdir() if p.is_file() and p.name.endswith(".md")])
    if not task_paths:
        sys.stdout.write("[INFO] no tasks found under 10_TASKS; nothing to export\n")
        return 0

    inp.out_dir.mkdir(parents=True, exist_ok=True)

    wrote: list[str] = []
    for task_path in task_paths:
        out_path = inp.out_dir / task_path.name
        task_text = task_path.read_text(encoding="utf-8").strip() + "\n"
        out_path.write_text(preamble + task_text, encoding="utf-8")
        wrote.append(str(out_path))

    now = _now_local()
    _append_log(
        inp.run_dir,
        {
            "ts": now.isoformat(timespec="seconds"),
            "level": "info",
            "event": "exported_prompts",
            "data": {"runner": inp.runner, "out_dir": str(inp.out_dir), "count": len(wrote)},
        },
    )

    for p in wrote:
        sys.stdout.write(p + "\n")
    return 0
