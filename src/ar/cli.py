from __future__ import annotations

import argparse
import sys

from .run.import_output import run_import
from .run.scaffold import run_scaffold
from .run.validate import run_validate


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ar", description="Agentic Research Orchestrator (repo-agnostic)")
    sub = p.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="Operate on run bundles")
    run_sub = run.add_subparsers(dest="run_cmd")

    scaffold = run_sub.add_parser("scaffold", help="Create a new run bundle")
    scaffold.add_argument("--runs-root", default="", help="Override runs root (default AR_RUNS_ROOT or ~/.ar/runs)")
    scaffold.add_argument("--slug", default="", help="Run slug (kebab-case). Optional if --goal is provided.")
    scaffold.add_argument("--goal", default="", help="Short statement of the decision/goal this run supports.")
    scaffold.add_argument("--targets", action="append", default=[], help="Target path (repeatable).")

    scaffold.add_argument(
        "--required-runner",
        action="append",
        default=[],
        help="Required runner (repeatable). Default: codex",
    )
    scaffold.add_argument(
        "--optional-runner",
        action="append",
        default=[],
        help="Optional runner (repeatable). Default: claude_desktop, cowork, gemini_deep_research, gemini_cli",
    )

    scaffold.add_argument("--codex-model", default="gpt-5.2", help="Default Codex model (e.g., gpt-5.2)")
    scaffold.add_argument(
        "--codex-reasoning",
        default="high",
        help="Default Codex reasoning effort (low|medium|high|xhigh)",
    )
    scaffold.add_argument(
        "--codex-sandbox",
        default="read-only",
        help="Default Codex sandbox mode (read-only|workspace-write|danger-full-access)",
    )
    scaffold.add_argument("--codex-timeout-seconds", type=int, default=1800, help="Default Codex timeout (seconds)")
    scaffold.add_argument("--codex-max-workers", type=int, default=3, help="Default Codex max workers")

    scaffold.add_argument("--dry-run", action="store_true", help="Print what would be done without writing files")
    scaffold.add_argument("--rebuild", action="store_true", help="Allow rebuilding if the target run directory exists")

    run_sub.add_parser("export-prompts", help="Export runner-specific prompts")
    run_sub.add_parser("spawn-codex", help="Spawn parallel Codex workers for tasks")

    imp = run_sub.add_parser("import", help="Import manual runner outputs into a run bundle")
    imp.add_argument("--run-dir", required=True, help="Run directory path")
    imp.add_argument("--task", required=True, help="Task id (e.g., T-0001)")
    imp.add_argument("--runner", required=True, help="Runner id (e.g., claude_desktop, gemini_deep_research)")
    imp.add_argument("--producer", default="", help="Producer id (default <runner>:manual-01)")
    imp.add_argument("--report-path", default="", help="Path to report markdown (if absent, read from stdin)")
    imp.add_argument("--sources-path", default="", help="Path to SOURCES.json (optional)")
    imp.add_argument("--claims-path", default="", help="Path to CLAIMS.json (optional)")
    imp.add_argument("--residuals-path", default="", help="Path to RESIDUALS.md (optional)")
    imp.add_argument("--model", default="", help="Model name (optional)")
    imp.add_argument("--reasoning", default="", help="Reasoning effort (optional)")

    run_sub.add_parser("merge", help="Merge producer outputs into canonical synthesis artifacts")

    val = run_sub.add_parser("validate", help="Validate run bundle structure and non-destructive synthesis")
    val.add_argument("--run-dir", required=True, help="Run directory path")

    run_sub.add_parser("status", help="Show run bundle status")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # `ar` with no args should show help (not error).
    if args.cmd is None:
        parser.print_help(sys.stdout)
        return 0

    if args.cmd == "run" and args.run_cmd is None:
        # `ar run` should show subcommand help.
        parser.parse_args(["run", "--help"])
        return 0

    if args.cmd == "run" and args.run_cmd == "scaffold":
        return run_scaffold(args)
    if args.cmd == "run" and args.run_cmd == "import":
        return run_import(args)
    if args.cmd == "run" and args.run_cmd == "validate":
        return run_validate(args)

    sys.stderr.write("Not implemented yet. See docs/CLI_SPEC.md for v1 contract.\n")
    return 2
