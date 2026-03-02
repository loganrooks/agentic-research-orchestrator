# Run Bundle Specification (v1)

This is the **canonical contract** for what goes on disk for a research run.

If something in `docs/IMPLEMENTATION_PLAN.md` conflicts with this file, **this file wins**.

The intention is compaction survival, resumability, and cross-runner compatibility.

---

## Design Goals (with reasons)

1. **Resumable**
   - Reason: runs get interrupted; re-running from scratch wastes tokens and time.
2. **Auditable**
   - Reason: we want to understand why outcomes differ (model settings, evidence, conflicts).
3. **Parallel-safe**
   - Reason: we want multi-process parallelism without file races.
4. **Runner-agnostic**
   - Reason: Claude/Gemini/Codex have different affordances; the bundle must accommodate all.

---

## Directory Naming

Run directory:
`$AR_RUNS_ROOT/YYYY-MM-DD/<timestamp>__<slug>__<run_id>/`

Where:
- `timestamp`: `YYYYMMDDTHHMMSS` (local time)
- `slug`: user-provided or derived from the goal (lowercase, hyphenated)
- `run_id`: 8–12 char random base32/hex

**Why:** Human scannable, stable sorting by date, and unique ids for programmatic references.

---

## Required Top-Level Files

1. `00_BRIEF.md`
2. `01_CONFIG.json`
3. `STATE.json`
4. `LOG.jsonl`
5. `10_TASKS/`
6. `20_WORK/`
7. `30_MERGE/`

### 00_BRIEF.md
Purpose: human intent anchor.

Minimum required sections:
- Decision / Goal
- Motivating context
- Non-goals
- Constraints
- Targets
- Priors + what would change your mind
- Output preferences

**Why:** Without this, research drifts into unbounded “interesting” territory.

### 01_CONFIG.json
Purpose: machine-readable configuration for reproducibility.

Must include:
- schema version
- runner plan
- codex defaults (model, reasoning, sandbox, timeout, worker count)
- quality policy flags

**Why:** Automation and validation need to run without guessing from prose.

### STATE.json
Purpose: resumability and concurrency control.

Rules:
- single-writer: supervisor only
- safe to rewrite atomically (write temp, rename)

**Why:** Without state, resuming becomes fragile and duplicative.

### LOG.jsonl
Purpose: append-only trace of decisions and failures.

Rules:
- append-only
- one JSON object per line
- must contain enough data to debug process control issues (timeouts, stalls, crashes)

**Why:** Parallel execution without logs is indistinguishable from random failure.

---

## Tasks: 10_TASKS/

One file per task:
`10_TASKS/T-0001__<slug>.md`

Task id (`T-0001`) is stable within a run.

**Why:** Task-level artifacts allow partial completion and targeted reruns.

---

## Work: 20_WORK/

Path:
`20_WORK/<task_id>/<producer_id>/`

Example:
`20_WORK/T-0003/codex:worker-02/`

Producer id format:
`<runner>:<instance>`

Examples:
- `codex:worker-01`
- `claude_desktop:manual-01`
- `cowork:agent-merge`
- `gemini_deep_research:manual-01`

**Why:** We need provenance and to avoid folder collisions.

Required files per producer:
- `PROVENANCE.json`
- `REPORT.md`
- `SOURCES.json`
- `CLAIMS.json`
- `RESIDUALS.md`

Codex optional:
- `EVENTS.jsonl`
- `LAST_MESSAGE.txt`
- `STDERR.log`

---

## Merge: 30_MERGE/

Required:
- `REPORT.md`
- `SOURCES.json`
- `CLAIMS.json`
- `CONFLICTS.md`
- `ASSUMPTIONS_AND_PROBES.md`
- `RESIDUALS.md`
- `RECOMMENDATIONS.md`

**Why:** We want a synthesis that is actionable and explicit about uncertainty, not a “summary blob.”

---

## Idempotency Rules

1. `scaffold` must not overwrite existing files unless `--rebuild` is set.
2. `import` must create a new producer folder if the target exists (suffix with `-02`, `-03`, etc.).
3. `merge` must be deterministic given the same inputs.
4. `validate` must be read-only (no mutations).

**Why:** Re-runs are normal. Idempotency prevents “mysterious corruption.”

---

## Concurrency Rules

1. Supervisor owns `STATE.json`.
2. Producers only write within their producer directory.
3. No producer writes to `30_MERGE/`.

**Why:** Prevents race conditions and ensures traceability.

