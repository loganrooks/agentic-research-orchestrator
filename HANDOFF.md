# Handoff: Agentic Research Orchestrator (Repo-Agnostic)

Date: 2026-03-02

This handoff is written so a fresh Codex session (or another agent) can pick up the repo and continue without guessing.

## Repo
- Path: `/Users/rookslog/Development/agentic-research-orchestrator`
- Branch: `main`
- Status: tests passing, worktree clean at time of handoff

## What This Repo Is
This repo is building a **repo-agnostic research orchestration system**:
- compaction-safe disk run bundles
- parallelizable execution (Codex workers via `codex exec --json`)
- manual import paths for other providers (Claude Desktop, Cowork, Gemini DR/CLI)
- synthesis that preserves conflicts and residuals (avoid “over-determinism”)

Key nuance:
- Other providers are **optional depth/breadth**. A run must remain valid and usable even if they never return output.
- When optional providers *do* exist, the system should produce **comparisons** between models/runners.

## Primary Specs (read these first)
1. `/Users/rookslog/Development/agentic-research-orchestrator/docs/RUN_BUNDLE_SPEC.md`
   - Canonical run-bundle contract (wins on conflicts).
2. `/Users/rookslog/Development/agentic-research-orchestrator/docs/CLI_SPEC.md`
   - Exact CLI surface.
3. `/Users/rookslog/Development/agentic-research-orchestrator/docs/IMPLEMENTATION_PLAN.md`
   - “Why” + procedures + guardrails (anti-misinterpretation).
4. Runner guides:
   - `/Users/rookslog/Development/agentic-research-orchestrator/docs/RUNNER_GUIDES/CODEX.md`
   - `/Users/rookslog/Development/agentic-research-orchestrator/docs/RUNNER_GUIDES/CLAUDE_COWORK.md`
   - `/Users/rookslog/Development/agentic-research-orchestrator/docs/RUNNER_GUIDES/CLAUDE_DESKTOP_RESEARCH.md`
   - `/Users/rookslog/Development/agentic-research-orchestrator/docs/RUNNER_GUIDES/GEMINI_DEEP_RESEARCH.md`

## Implemented CLI Commands (working today)
Entry: `python -m ar ...` (the console script `ar` is declared in `pyproject.toml` but not installed in a venv yet).

Implemented:
1. `python -m ar --help`
2. `python -m ar run scaffold ...`
3. `python -m ar run import ...`
4. `python -m ar run validate --run-dir ...`
5. `python -m ar run status --run-dir ...`
6. `python -m ar run merge --run-dir ...`
   - NOTE: merge is currently a **comparison-first stub**:
     - writes `30_MERGE/COMPARISON.{md,json}`
     - writes placeholder synthesis files (empty SOURCES/CLAIMS, stub REPORT)
     - real synthesis (dedupe/cluster/conflicts) is still TODO

## Code Map
CLI wiring:
- `/Users/rookslog/Development/agentic-research-orchestrator/src/ar/cli.py`

Run commands:
- Scaffold: `/Users/rookslog/Development/agentic-research-orchestrator/src/ar/run/scaffold.py`
  - Test hooks: env `AR_FIXED_NOW`, `AR_FIXED_RUN_ID`
- Import: `/Users/rookslog/Development/agentic-research-orchestrator/src/ar/run/import_output.py`
- Validate: `/Users/rookslog/Development/agentic-research-orchestrator/src/ar/run/validate.py`
- Status: `/Users/rookslog/Development/agentic-research-orchestrator/src/ar/run/status.py`
- Merge (stub): `/Users/rookslog/Development/agentic-research-orchestrator/src/ar/run/merge.py`

Compaction recovery helper:
- Extract prior user messages from Codex session logs:
  - `/Users/rookslog/Development/agentic-research-orchestrator/tools/extract_codex_user_messages.py`
  - Output is written to `.artifacts/` (gitignored)

## Test Suite
Run:
```bash
cd /Users/rookslog/Development/agentic-research-orchestrator
pytest -q
```

Current tests:
- `/Users/rookslog/Development/agentic-research-orchestrator/tests/test_cli_help.py`
- `/Users/rookslog/Development/agentic-research-orchestrator/tests/test_scaffold.py`
- `/Users/rookslog/Development/agentic-research-orchestrator/tests/test_import.py`
- `/Users/rookslog/Development/agentic-research-orchestrator/tests/test_validate.py`
- `/Users/rookslog/Development/agentic-research-orchestrator/tests/test_status.py`
- `/Users/rookslog/Development/agentic-research-orchestrator/tests/test_merge.py`

## Quick Verification Demo (manual)
```bash
cd /Users/rookslog/Development/agentic-research-orchestrator

# 1) Scaffold a run bundle under a temp runs root:
RUN_DIR=$(python -m ar run scaffold --runs-root /tmp/ar-runs --slug demo --goal "Demo research run")
echo "$RUN_DIR"

# 2) Import two “optional provider” outputs to simulate multi-runner comparison:
printf "# Report A\n" > /tmp/a.md
printf "# Report B\n" > /tmp/b.md
python -m ar run import --run-dir "$RUN_DIR" --task T-0001 --runner claude_desktop --report-path /tmp/a.md
python -m ar run import --run-dir "$RUN_DIR" --task T-0001 --runner gemini_deep_research --report-path /tmp/b.md

# 3) Merge (writes COMPARISON artifacts + stub synthesis)
python -m ar run merge --run-dir "$RUN_DIR"

# 4) Validate structure
python -m ar run validate --run-dir "$RUN_DIR"

# 5) Inspect:
ls -la "$RUN_DIR/30_MERGE"
cat "$RUN_DIR/30_MERGE/COMPARISON.md"
```

Expected:
- `COMPARISON.json` includes 2 producers for `T-0001`
- validate returns 0 (with “incomplete” message if no producers exist; but here producers exist)

## What Remains (priority order)

### P0: Implement `export-prompts`
Spec: `docs/CLI_SPEC.md` + runner guides.
Goal:
- create runner-specific, copy/paste-ready task prompts under `<run>/11_EXPORT/<runner>/`.
Why:
- avoids assuming Claude/Gemini output shapes; reduces format mismatch.

Acceptance:
- Unit test: `export-prompts` writes one file per task with correct runner preamble.

### P0: Implement `spawn-codex` (parallel workers + monitoring)
Goal:
- spawn multiple `codex exec --json` processes
- capture `EVENTS.jsonl`, parse `token_count` totals, write `PROVENANCE.json`
- write worker outputs into `20_WORK/<task>/codex:worker-XX/`

Key requirements:
- explicit model+reasoning overrides (do not rely on global Codex config)
- timeout handling + stalled worker detection (“monitoring”)
- resume support (skip tasks already completed)

Acceptance:
- integration-ish test that uses a mocked `EVENTS.jsonl` fixture for token parsing
- actual spawn can be gated/skipped in tests if codex isn’t available in CI

### P1: Replace merge stub with real synthesis
Currently `merge.py` writes comparison artifacts and placeholder files.
Need:
- dedupe sources
- cluster claims without deleting
- explicit conflicts + context splits + composable notes
- write `ASSUMPTIONS_AND_PROBES.md` and `RECOMMENDATIONS.md` from claims+residuals
- populate `SOURCES.json` and `CLAIMS.json` (merged)

Acceptance:
- tests for: “conflict preservation” (two incompatible claims both survive)
- tests for: “optional runner absence” (merge works with codex-only)

### P1: Comparison divergences
`COMPARISON.json` currently has empty `divergences`.
Need:
- simple heuristics:
  - different conclusions for same area
  - one producer has sources/claims where another has none
- keep it conservative; don’t hallucinate divergences

Acceptance:
- unit test that divergences appear when two producers disagree on a claim id (fixture).

## How To Start a New Codex Session Cleanly
Start in repo root:
- CWD: `/Users/rookslog/Development/agentic-research-orchestrator`

Minimal verification commands:
```bash
pytest -q
python -m ar --help
python -m ar run scaffold --runs-root /tmp/ar-runs --slug smoke --goal "smoke test"
```

