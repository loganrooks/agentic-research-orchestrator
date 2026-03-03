---
name: agentic-research-orchestrator
description: Run-bundle based agentic research orchestration using the agentic-research-orchestrator (`ar`) CLI and its MCP server. Use when you need to scaffold/validate/status a run bundle, generate tasks via an OrchestratorPlan, export runner prompts, spawn parallel Codex workers, import external runner outputs, or deterministically merge outputs into synthesis artifacts while preserving conflicts and residuals. Also use when configuring MCP clients (Claude Code, Gemini CLI) to drive `ar` via tools and prompts.
---

# Agentic Research Orchestrator

## Overview

Operate the `agentic-research-orchestrator` system end-to-end: create compaction-safe run bundles on disk, run/collect multi-runner work, and deterministically merge results while preserving conflicts and residuals.

## Workflow

### 1) Create a run bundle

- Scaffold a run:
  - `python3 -m ar run scaffold --runs-root /tmp/ar-runs --slug demo --goal "Demo research run"`

### 2) Create tasks

Pick one:
- Manual: write canonical task files under `<run>/10_TASKS/` (see `docs/RUN_BUNDLE_SPEC.md` in this repo).
- Agentic: have a supervisor propose tasks, then apply the plan:
  - `python3 -m ar run generate-tasks --run-dir <RUN_DIR> --profile guided`

### 3) Execute tasks (Codex workers)

- Run parallel Codex workers:
  - `python3 -m ar run spawn-codex --run-dir <RUN_DIR>`

### 4) Execute tasks (other runners, optional)

- Export copy/paste prompts for a runner (one file per task):
  - `python3 -m ar run export-prompts --run-dir <RUN_DIR> --runner claude_code`
- After running a task elsewhere, import results into the run bundle:
  - `python3 -m ar run import --run-dir <RUN_DIR> --task T-0001 --runner claude_code --report-path /path/to/report.md`

### 5) Merge + validate

- Build deterministic synthesis outputs under `<run>/30_MERGE/`:
  - `python3 -m ar run merge --run-dir <RUN_DIR>`
- Validate structure + synthesis invariants:
  - `python3 -m ar run validate --run-dir <RUN_DIR>`
- Check status summary:
  - `python3 -m ar run status --run-dir <RUN_DIR>`

### 6) Iterate (optional)

- Propose follow-up tasks from merge artifacts:
  - `python3 -m ar run propose-followups --run-dir <RUN_DIR> --profile guided`

## MCP (orchestrator clients)

Use MCP when you want another tool (Claude Code / Gemini CLI / etc.) to act as the “brain”, while `ar` stays the deterministic “hands”.

- Start a read-only MCP server:
  - `python3 -m ar mcp serve --allow-run-dir-prefix <RUNS_ROOT>`
- Start a write-enabled MCP server (apply/merge/spawn/propose mutate the run bundle):
  - `python3 -m ar mcp serve --write-enabled --allow-run-dir-prefix <RUNS_ROOT>`

See `references/claude-code.md` and `references/gemini-cli.md` for config snippets and prompt invocation.

## Quality gates (recommended)

- After creating tasks: run `ar run validate` and ensure `<run>/10_TASKS/` matches intent.
- After execution/import: run `ar run status` and verify producers exist under `<run>/20_WORK/<task>/`.
- After merge: read `<run>/30_MERGE/REPORT.md` and re-run `ar run validate`.

## Troubleshooting

- If `python3 -m ar ...` fails to import `ar`, install this repo in the active environment:
  - `python3 -m pip install -e /path/to/agentic-research-orchestrator`
- If an MCP client can’t connect, verify the configured command points at a Python environment where `agentic-research-orchestrator` is installed.
