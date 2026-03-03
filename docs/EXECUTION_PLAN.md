# Execution Plan (v1) — 2026-03-03

This file captures the step-by-step plan for finishing the v1 CLI + run-bundle contract.
It is intentionally explicit to survive compaction / handoffs.

## Canonical references

- `docs/RUN_BUNDLE_SPEC.md` (on-disk contract)
- `docs/CLI_SPEC.md` (exact CLI surface)
- `docs/IMPLEMENTATION_PLAN.md` (procedures + guardrails)

## Scope

- Implement/finish: `export-prompts`, `spawn-codex`, real `merge` synthesis + comparisons, validation/status improvements.
- Preserve the core invariant: optional runners remain optional; runs remain valid/useful with Codex-only output.

## Current state (worktree snapshot)

Uncommitted changes exist (see `git status`).

Already implemented in code (verify via `pytest -q`):
- [x] `ar run export-prompts` (+ unit tests)
- [x] `ar run export-orchestrator-prompt` / `ar run apply-plan` (+ unit tests)
- [x] `ar run generate-tasks` / `ar run propose-followups` (+ unit tests)
- [x] `ar run spawn-codex` (+ token parsing tests + monitoring logs)
- [x] real `ar run merge` synthesis (non-destructive) + conflict preservation tests
- [x] conservative comparison divergences (`conflict`, `coverage_gap`)
- [x] `ar mcp serve` tool surface (write-gated) (+ unit tests)
- [x] `codex exec` override uses `model_reasoning_effort` (does not rely on global Codex config)
- [x] `LOG.jsonl` append parity added for `merge`, `validate`, `status` (and already present for others)

## Tasks (completed)

- [x] **Resolve the validate “read-only” wording**
   - Decision: treat `LOG.jsonl` and `STATE.json` as supervisor metadata.
   - Update `docs/RUN_BUNDLE_SPEC.md` to clarify: `validate` is read-only with respect to research artifacts (`20_WORK/` + `30_MERGE/`), but may write metadata (append to `LOG.jsonl`, update `STATE.json`).

- [x] **Update `STATE.json` during `merge`/`validate`**
   - Goal: keep `STATE.json.status` / `STATE.json.current_step` accurate so `ar run status` reflects phase transitions.

- [x] **`status`: log tail tests**
   - Requirement: `ar run status --run-dir ...` prints the last 10 `LOG.jsonl` lines (raw JSONL).
   - Add/adjust unit test(s) to assert tail output is present and ordered.

- [x] **`validate`: pre-merge warning when producers exist**
   - Requirement: if there are producer outputs under `20_WORK/` but merge artifacts are missing (e.g. `30_MERGE/COMPARISON.json` absent), print a `[WARN]` explaining merge hasn’t been run yet.
   - Exit code should remain `0` if the run is otherwise structurally valid.

- [x] **`merge`: add `counterexample_missed` divergences**
   - Requirement (conservative, evidence-based only): use per-producer `SOURCES.json` entries where `role` is `counterexample` or `failure_mode` (case-insensitive).
   - Emit a `counterexample_missed` divergence only when at least one producer has such sources and at least one producer does not.
   - Add unit test fixture to validate divergence appears (and does not appear when evidence is absent).

- [x] **`scaffold`: enforce required args**
   - Requirement: `ar run scaffold` must require `--slug` OR `--goal` (if `--goal` is provided, slug can be derived).
   - If both are absent, exit with code `2` and a clear error message.
   - Add unit test.

- [x] **Run the suite**
   - `pytest -q`
   - Fix only failures caused by the above changes (no scope creep).

## Review: potential gaps / second-order effects

- **Resolved direction:** treat `LOG.jsonl` and `STATE.json` as supervisor metadata. `validate` remains read-only with respect to research artifacts (`20_WORK/` + `30_MERGE/`), but may update metadata.

- **STATE.json freshness:** `merge`/`validate` should update `STATE.json` (`status` / `current_step`) so `ar run status` reflects phase transitions.

- **Validation semantics:** `validate` should clearly distinguish “structurally valid but incomplete” vs “invalid/corrupt”, and the new pre-merge warning must not flip exit codes.

- **Divergence heuristics:** keep `counterexample_missed` strictly evidence-based (structured fields), to avoid hallucinated “divergences”.

- **export-prompts drift risk:** current runner preambles are hardcoded. If we want templates to stay aligned with `docs/RUNNER_GUIDES/*`, consider sourcing/deriving the preamble text from those docs.

- **status UX:** status currently reports producer *counts* per task; consider listing producer ids too if “producers per task” is intended literally.

- **Local environment note:** this environment has `python3` but not `python`; docs and examples use `python -m ar`. Consider aligning docs or adding a note (if/when we touch docs).

## Test checklist

- [x] `status` prints log tail (10 lines)
- [x] `validate` warns pre-merge when producers exist
- [x] `merge` emits `counterexample_missed` divergence in the intended scenario
- [x] `scaffold` requires `--slug` or `--goal`
- [x] `pytest -q` passes (17 tests)
- [x] `pytest -q` passes (35 tests)
