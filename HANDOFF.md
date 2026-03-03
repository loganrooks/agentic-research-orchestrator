# Handoff: Agentic Research Orchestrator (Repo-Agnostic)

Date: 2026-03-03

This handoff is written so a fresh Codex session (or another agent) can pick up the repo and verify it end-to-end without guessing.

## Repo
- Path: `/Users/rookslog/Development/agentic-research-orchestrator`
- Default branch: `main`
- Branch naming convention: `codex/*` for work-in-progress branches

## What This Repo Is
This repo implements a **repo-agnostic research control plane**:
- compaction-safe, disk-backed run bundles
- parallelizable execution (Codex workers via `codex exec --json`)
- manual import paths for other providers (Claude Desktop, Cowork, Gemini Deep Research/CLI)
- synthesis that preserves conflicts + residuals (avoid “over-determinism”)

Invariants (by design):
- Other providers are **optional depth/breadth**. A run remains structurally valid even if they never return output.
- When multiple producers exist, the system emits explicit **comparisons** (it does not “average away” disagreement).

## Primary Specs (read these first)
1. `/Users/rookslog/Development/agentic-research-orchestrator/docs/RUN_BUNDLE_SPEC.md`
2. `/Users/rookslog/Development/agentic-research-orchestrator/docs/CLI_SPEC.md`
3. `/Users/rookslog/Development/agentic-research-orchestrator/docs/TASK_WRITING_GUIDE.md`
4. Runner guides: `/Users/rookslog/Development/agentic-research-orchestrator/docs/RUNNER_GUIDES/*`

## How To Run The CLI (dev mode)
This repo may not be installed into a venv. The reliable pattern is:
```bash
cd /Users/rookslog/Development/agentic-research-orchestrator
PYTHONPATH=src python3 -m ar --help
```

If you do want an installed `ar` console script:
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
ar --help
```

Note: `python` is not guaranteed to exist on this machine; use `python3`.

## Implemented CLI Commands
Entry: `PYTHONPATH=src python3 -m ar run ...`

Run-bundle lifecycle:
1. `scaffold` (create a run bundle)
2. `export-prompts` (export per-runner task prompts)
3. `export-orchestrator-prompt` (export supervisor/orchestrator prompt for a runner)
4. `generate-tasks` (Codex supervisor proposes tasks -> produces an OrchestratorPlan JSON)
5. `apply-plan` (apply a plan JSON to create `10_TASKS/*.md`)
6. `spawn-codex` (parallel task execution via `codex exec`)
7. `import` (import manual provider outputs into `20_WORK/<task>/<producer>/`)
8. `merge` (produce `30_MERGE/*` canonical synthesis + comparisons)
9. `validate` (structural validation + non-destructive checks)
10. `status` (operator-oriented summary)

MCP mode:
- `PYTHONPATH=src python3 -m ar mcp serve ...`

## Code Map (entrypoints)
- CLI wiring: `/Users/rookslog/Development/agentic-research-orchestrator/src/ar/cli.py`
- Run commands: `/Users/rookslog/Development/agentic-research-orchestrator/src/ar/run/`
- MCP server: `/Users/rookslog/Development/agentic-research-orchestrator/src/ar/mcp/`
- Utilities: `/Users/rookslog/Development/agentic-research-orchestrator/tools/`

Compaction recovery helper:
- Extract prior user messages from Codex session logs:
  - `/Users/rookslog/Development/agentic-research-orchestrator/tools/extract_codex_user_messages.py`
  - Output is written to `.artifacts/` (gitignored)

## Test Suite (fast)
```bash
cd /Users/rookslog/Development/agentic-research-orchestrator
pytest -q
```

## Quick Verification Demo (manual import path; no Codex required)
```bash
cd /Users/rookslog/Development/agentic-research-orchestrator

RUN_DIR=$(
  PYTHONPATH=src python3 -m ar run scaffold \
    --runs-root /tmp/ar-runs \
    --slug demo \
    --goal "Demo research run"
)
echo "$RUN_DIR"

# Create a task (simulates supervisor/apply-plan output)
cat > "$RUN_DIR/10_TASKS/T-0001__demo.md" <<'EOF'
# Task T-0001: Demo

## Intent
Confirm comparison + merge + validate all work with manual imports.
EOF

# Import two runner outputs to create a multi-producer comparison
printf "# Report A\n" > /tmp/a.md
printf "# Report B\n" > /tmp/b.md
PYTHONPATH=src python3 -m ar run import --run-dir "$RUN_DIR" --task T-0001 --runner claude_desktop --report-path /tmp/a.md
PYTHONPATH=src python3 -m ar run import --run-dir "$RUN_DIR" --task T-0001 --runner gemini_deep_research --report-path /tmp/b.md

# Merge + validate
PYTHONPATH=src python3 -m ar run merge --run-dir "$RUN_DIR"
PYTHONPATH=src python3 -m ar run validate --run-dir "$RUN_DIR"

ls -la "$RUN_DIR/30_MERGE"
```

Expected:
- `30_MERGE/COMPARISON.{md,json}` exists
- `30_MERGE/REPORT.md`, `30_MERGE/CONFLICTS.md`, `30_MERGE/RESIDUALS.md` exist (even if sparse)
- validate exits 0

## Debug Checklist
1. Inspect run state and log:
   - `STATE.json`
   - `LOG.jsonl`
2. Inspect per-producer provenance:
   - `20_WORK/<task>/<producer>/PROVENANCE.json`
3. Inspect merge outputs:
   - `30_MERGE/*`

