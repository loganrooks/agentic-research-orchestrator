from __future__ import annotations

import argparse
import sys

from .mcp.serve import run_mcp_serve
from .run.export_prompts import run_export_prompts
from .run.export_orchestrator_prompt import run_export_orchestrator_prompt
from .run.generate_tasks import run_generate_tasks
from .run.import_output import run_import
from .run.merge import run_merge
from .run.apply_plan import run_apply_plan
from .run.propose_followups import run_propose_followups
from .run.scaffold import run_scaffold
from .run.spawn_codex import run_spawn_codex
from .run.status import run_status
from .run.validate import run_validate


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ar", description="Agentic Research Orchestrator (repo-agnostic)")
    sub = p.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="Operate on run bundles")
    run_sub = run.add_subparsers(dest="run_cmd")

    mcp = sub.add_parser("mcp", help="Run MCP server (tool mode)")
    mcp_sub = mcp.add_subparsers(dest="mcp_cmd")
    mcp_serve = mcp_sub.add_parser("serve", help="Serve MCP tools over stdio")
    mcp_serve.add_argument("--write-enabled", action="store_true", help="Enable write-capable tools (default off)")
    mcp_serve.add_argument(
        "--allow-run-dir-prefix",
        action="append",
        default=[],
        help="Restrict tools to run_dir under this prefix (repeatable; recommended).",
    )
    mcp_serve.add_argument("--max-calls-per-minute", type=int, default=60, help="Simple rate limit (default 60)")

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

    export = run_sub.add_parser("export-prompts", help="Export runner-specific prompts")
    export.add_argument("--run-dir", required=True, help="Run directory path")
    export.add_argument("--runner", required=True, help="Runner id (e.g., claude_desktop, gemini_deep_research)")
    export.add_argument("--out-dir", default="", help="Output directory (default <run>/11_EXPORT/<runner>/)")

    export_orch = run_sub.add_parser("export-orchestrator-prompt", help="Export an orchestrator prompt for a runner")
    export_orch.add_argument("--run-dir", required=True, help="Run directory path")
    export_orch.add_argument("--runner", required=True, help="Runner id (e.g., claude_code, gemini_cli)")
    export_orch.add_argument(
        "--profile",
        default="normal",
        help="Prompt profile (normal|guided). Guided is more step-by-step for weaker orchestrators.",
    )
    export_orch.add_argument(
        "--out-path",
        default="",
        help="Output prompt path (default <run>/12_SUPERVISOR/PROMPTS/ORCHESTRATOR_PROMPT_<ts>__<runner>.md)",
    )

    apply_plan = run_sub.add_parser("apply-plan", help="Apply an orchestrator plan (JSON) to create tasks")
    apply_plan.add_argument("--run-dir", required=True, help="Run directory path")
    apply_plan.add_argument("--plan-path", required=True, help="Path to plan JSON, or '-' for stdin")
    apply_plan.add_argument("--dry-run", action="store_true", help="Validate and preview without writing")

    gen_tasks = run_sub.add_parser("generate-tasks", help="Generate tasks via a Codex supervisor (OrchestratorPlan)")
    gen_tasks.add_argument("--run-dir", required=True, help="Run directory path")
    gen_tasks.add_argument("--model", default="", help="Codex model override (default from config)")
    gen_tasks.add_argument("--reasoning", default="", help="Codex reasoning effort override (default from config)")
    gen_tasks.add_argument("--profile", default="normal", help="Supervisor prompt profile (normal|guided)")
    gen_tasks.add_argument(
        "--sandbox",
        default="",
        help="Codex sandbox override (read-only|workspace-write|danger-full-access; default from config)",
    )
    gen_tasks.add_argument("--timeout-seconds", type=int, default=0, help="Supervisor timeout (default from config)")
    gen_tasks.add_argument("--dry-run", action="store_true", help="Run supervisor and validate plan without creating tasks")

    followups = run_sub.add_parser("propose-followups", help="Propose follow-up tasks via Codex (requires merge artifacts)")
    followups.add_argument("--run-dir", required=True, help="Run directory path")
    followups.add_argument("--model", default="", help="Codex model override (default from config)")
    followups.add_argument("--reasoning", default="", help="Codex reasoning effort override (default from config)")
    followups.add_argument("--profile", default="guided", help="Supervisor prompt profile (normal|guided)")
    followups.add_argument(
        "--sandbox",
        default="",
        help="Codex sandbox override (read-only|workspace-write|danger-full-access; default from config)",
    )
    followups.add_argument("--timeout-seconds", type=int, default=0, help="Supervisor timeout (default from config)")
    followups.add_argument("--dry-run", action="store_true", help="Run supervisor and validate plan without creating tasks")

    spawn = run_sub.add_parser("spawn-codex", help="Spawn parallel Codex workers for tasks")
    spawn.add_argument("--run-dir", required=True, help="Run directory path")
    spawn.add_argument("--task", action="append", default=[], help="Task id (repeatable; default all)")
    spawn.add_argument("--max-workers", type=int, default=0, help="Max parallel workers (default from config)")
    spawn.add_argument("--timeout-seconds", type=int, default=0, help="Timeout per task (default from config)")
    spawn.add_argument("--model", default="", help="Codex model override (default from config)")
    spawn.add_argument("--reasoning", default="", help="Codex reasoning effort override (default from config)")
    spawn.add_argument(
        "--sandbox",
        default="",
        help="Codex sandbox override (read-only|workspace-write|danger-full-access; default from config)",
    )
    spawn.add_argument("--resume", dest="resume", action="store_true", help="Resume (skip completed tasks)")
    spawn.add_argument("--no-resume", dest="resume", action="store_false", help="Do not resume; always run")
    spawn.set_defaults(resume=True)
    spawn.add_argument("--fail-fast", action="store_true", help="Stop launching new tasks after a failure")

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

    merge = run_sub.add_parser("merge", help="Merge producer outputs into canonical synthesis artifacts")
    merge.add_argument("--run-dir", required=True, help="Run directory path")
    merge.add_argument(
        "--allow-missing-registers",
        action="store_true",
        help="Allow missing CLAIMS.json/SOURCES.json in producer dirs (not recommended)",
    )

    val = run_sub.add_parser("validate", help="Validate run bundle structure and non-destructive synthesis")
    val.add_argument("--run-dir", required=True, help="Run directory path")

    status = run_sub.add_parser("status", help="Show run bundle status")
    status.add_argument("--run-dir", required=True, help="Run directory path")

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
    if args.cmd == "mcp" and args.mcp_cmd is None:
        parser.parse_args(["mcp", "--help"])
        return 0

    if args.cmd == "run" and args.run_cmd == "scaffold":
        return run_scaffold(args)
    if args.cmd == "run" and args.run_cmd == "export-prompts":
        return run_export_prompts(args)
    if args.cmd == "run" and args.run_cmd == "export-orchestrator-prompt":
        return run_export_orchestrator_prompt(args)
    if args.cmd == "run" and args.run_cmd == "apply-plan":
        return run_apply_plan(args)
    if args.cmd == "run" and args.run_cmd == "generate-tasks":
        return run_generate_tasks(args)
    if args.cmd == "run" and args.run_cmd == "propose-followups":
        return run_propose_followups(args)
    if args.cmd == "run" and args.run_cmd == "spawn-codex":
        return run_spawn_codex(args)
    if args.cmd == "run" and args.run_cmd == "import":
        return run_import(args)
    if args.cmd == "run" and args.run_cmd == "validate":
        return run_validate(args)
    if args.cmd == "run" and args.run_cmd == "status":
        return run_status(args)
    if args.cmd == "run" and args.run_cmd == "merge":
        return run_merge(args)

    if args.cmd == "mcp" and args.mcp_cmd == "serve":
        return run_mcp_serve(args)

    sys.stderr.write("Not implemented yet. See docs/CLI_SPEC.md for v1 contract.\n")
    return 2
