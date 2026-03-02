from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ar", description="Agentic Research Orchestrator (repo-agnostic)")
    sub = p.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="Operate on run bundles")
    run_sub = run.add_subparsers(dest="run_cmd")

    # Skeleton only; implemented in later commits.
    run_sub.add_parser("scaffold", help="Create a new run bundle")
    run_sub.add_parser("export-prompts", help="Export runner-specific prompts")
    run_sub.add_parser("spawn-codex", help="Spawn parallel Codex workers for tasks")
    run_sub.add_parser("import", help="Import manual runner outputs into a run bundle")
    run_sub.add_parser("merge", help="Merge producer outputs into canonical synthesis artifacts")
    run_sub.add_parser("validate", help="Validate run bundle structure and non-destructive synthesis")
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

    # Placeholder behavior until subcommands are implemented.
    sys.stderr.write("Not implemented yet. See docs/CLI_SPEC.md for v1 contract.\n")
    return 2

