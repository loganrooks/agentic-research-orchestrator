# Troubleshooting (v1)

This file exists because orchestration systems fail in predictable ways. A less-capable agent should not have to guess.

---

## Symptom: Merge fails with “missing required files”

Likely causes:
1. A producer directory is missing `PROVENANCE.json` or `RESIDUALS.md`.
2. A manual import only provided a report and omitted registers without leaving empty `[]` files.

What to do:
1. Run `ar run validate --run-dir ...` and read the listed missing paths.
2. If the producer truly has no claims/sources, create:
   - `SOURCES.json` = `[]`
   - `CLAIMS.json` = `[]`
   - `RESIDUALS.md` = explanation of what is missing and why.

Why:
- Empty-but-present artifacts are better than “missing”, because they are explicit and machine-mergeable.

---

## Symptom: Codex workers run, but token usage is missing

Likely causes:
1. `codex exec` was not invoked with `--json`, so no `token_count` event stream exists.
2. The supervisor did not capture stdout to `EVENTS.jsonl`.

What to do:
1. Confirm producer dir has `EVENTS.jsonl`.
2. If not, rerun the task with correct flags.

---

## Symptom: Codex worker stalls (no new events)

Likely causes:
1. Model is stuck on a long reasoning step.
2. Process is hung.
3. Output pipe backpressure if logs aren’t being drained.

What to do:
1. Supervisor should record `stalled_worker` in `LOG.jsonl`.
2. If still stalled past timeout, terminate and mark `timeout`.
3. Rerun with:
   - fewer tasks per worker
   - lower reasoning
   - or a narrower prompt

Why:
- “No timeouts” is not a solution; it makes the system unoperational. Long timeouts with monitoring is the correct compromise.

---

## Symptom: Manual runner output can’t produce JSON registers

Likely causes:
1. UI constraints (single report only).
2. Model compliance issues.

What to do:
1. Accept tables with stable IDs.
2. Import the report and registers as-is.
3. Convert tables to JSON later (separate utility; v2).

Why:
- Forcing JSON in an environment that can’t reliably produce it risks losing nuance and getting partial outputs.

