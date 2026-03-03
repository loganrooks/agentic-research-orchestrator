# Agentic Research Orchestrator (ARO)

[![CI](https://github.com/loganrooks/agentic-research-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/loganrooks/agentic-research-orchestrator/actions/workflows/ci.yml)
[![aro-installer (npm)](https://img.shields.io/npm/v/aro-installer.svg)](https://www.npmjs.com/package/aro-installer)

Repo-agnostic research orchestration using **compaction-safe run bundles** on disk.

Two ways to drive it:
- **Deterministic CLI** (`python -m ar ...` / `ar ...`): scaffold/validate/status/merge run bundles.
- **MCP server** (`python -m ar mcp serve ...`): Claude Code / Gemini CLI / etc. act as the “brain” while ARO is the deterministic “hands”.

## What you get

- A **run bundle** directory format for long-running, multi-agent research that survives compaction and tool churn.
- A deterministic **merge/synthesis step** that preserves conflicts and residuals (instead of “averaging away” disagreements).
- Optional parallel execution via **Codex workers** (`spawn-codex`) plus import paths for other runners.
- MCP integration so other tools can orchestrate while ARO handles safe filesystem mutation.

## Quick start

### 1) Install the Python package

Local/dev (editable):

```bash
python3 -m pip install -e .
python3 -m ar --help
```

### 2) Scaffold a run bundle

```bash
RUN_DIR=$(python3 -m ar run scaffold --runs-root /tmp/ar-runs --slug demo --goal "Demo research run")
echo "$RUN_DIR"
```

### 3) Configure Codex/MCP integrations (optional)

If you have Node 18+:

```bash
npx --yes aro-installer setup
```

This can:
- install the Codex skill to `~/.codex/skills/agentic-research-orchestrator/`
- write MCP client config for Claude Code and/or Gemini CLI (project/user/both)

## Typical workflow

1) Scaffold: `ar run scaffold ...`
2) Create tasks: write files under `<run>/10_TASKS/` (or use `ar run generate-tasks`)
3) Execute:
   - Codex: `ar run spawn-codex --run-dir <run>`
   - Other runners: `ar run export-prompts ...` then `ar run import ...`
4) Merge: `ar run merge --run-dir <run>`
5) Validate: `ar run validate --run-dir <run>`

## Security model (MCP)

- `--allow-run-dir-prefix <runs-root>` confines the server to a known directory tree.
- `_ro` servers cannot mutate run bundles; `_rw` servers can (explicit opt-in).

## Docs

- Run bundle contract: `docs/RUN_BUNDLE_SPEC.md`
- CLI surface: `docs/CLI_SPEC.md`
- Design rationale / guardrails: `docs/IMPLEMENTATION_PLAN.md`
- Integrations (Codex skill + MCP): `docs/INTEGRATIONS.md`

## Development

```bash
pytest -q
```
