# Phase 2 Plan (2026-03-04): Epistemic + QoL Improvements

This plan is the “next iteration” after v1 is implemented. It uses the philosophical/epistemic grounding as an explicit constraint, not as a post-hoc story.

Inputs:
- `docs/EPISTEMIC_GROUNDING.md` (epistemic theories → operational commitments)
- `docs/CODEBASE_REVIEW_2026-03-04.md` (current-state review + concrete frictions)
- `docs/RUN_BUNDLE_SPEC.md` and `docs/CLI_SPEC.md` (v1 contracts)

Non-goal: rewrite the system into a “single super-agent”. The correct direction is: **better substrate + clearer agent interfaces + stronger quality gates**.

---

## 0) Execution protocol (git + gates)

Branching:
- Work happens on feature branches (prefix `codex/`).
- `main` stays green and releaseable.

Quality gates (run at the end of every phase):
1) Unit tests: `pytest -q`
2) Spec sanity:
   - `PYTHONPATH=src python3 -m ar --help`
   - `PYTHONPATH=src python3 -m ar run --help`
3) Smoke run (no external APIs required):
   - scaffold → apply-plan → export-prompts → import → merge → validate → status
4) Epistemic sanity (human check, 3–5 minutes):
   - read `30_MERGE/CONFLICTS.md` when conflicts exist
   - confirm residuals are not empty placeholders everywhere

Why these gates:
- Tests catch regressions.
- Help output catches CLI drift.
- Smoke run catches end-to-end breakage.
- The epistemic check catches “everything is syntactically valid but epistemically useless.”

### Status (as of 2026-03-04)
Completed:
- P0-A runner terminology disambiguation (support `claude_code` in `export-prompts` + docs)
- P0-B trustworthy `STATE.json.status` transitions (import + merge semantics)
- P1 conservative claim matching via optional `topic_key`

Pending / in-progress:
- P0-C rename “targets” → “context anchors” (terminology trap)
- P1 task lint quality gate (warnings)
- P2 installer QoL (only if gaps remain after core epistemic fixes)

---

## 1) Phase 2 goals (what “better” means)

We improve two things simultaneously:

1) **Reduce friction / confusion**
   - lower onboarding cost
   - make status trustworthy
   - remove terminology traps

2) **Increase epistemic reliability**
   - reduce false conflicts/agreements
   - make probes/assumptions more actionable
   - keep multi-runner comparison useful without hallucinating structure

---

## 2) Work items (prioritized, with philosophical + technical justification)

### P0-A) Disambiguate “runner” terminology (docs + skills + UX)
Problem:
- `--runner` refers to two different concepts:
  - execution runner (for `export-prompts`, `import`)
  - orchestrator client (for `export-orchestrator-prompt`, MCP prompt)

Risk:
- users pass `claude_code` to `export-prompts` (because it “feels right”) and hit an error.

Options:
1) **Support `claude_code` in `export-prompts`** (treat as “report-first runner” like Claude Desktop/Gemini).
2) **Remove `claude_code` from skill examples for `export-prompts`** and consistently use `claude_desktop`/`gemini_cli` etc.

Recommendation:
- Do (1) *and* clarify terminology in docs.

Epistemic grounding:
- reduce tool-induced error (bounded rationality): don’t punish reasonable user inferences. (`docs/EPISTEMIC_GROUNDING.md` §3.9)

Gate:
- update tests for `export-prompts` runner acceptance + ensure skills/docs examples work.

### P0-B) Make `STATE.json.status` transitions trustworthy
Problem:
- some commands set `status=running|merging` but don’t reliably set a post-condition status on success.

Recommendation:
- define explicit semantics for `STATE.json.status`:
  - `scaffolded`: run exists; no producer outputs yet
  - `running`: producer outputs exist and run is mid-iteration (not yet validated)
  - `partial`: failures/conflicts exist that require attention before “done”
  - `merging`: merge in progress
  - `validated`: validate passed and no “partial” condition is present
  - `failed`: validate failed or fatal supervisor errors
- ensure `spawn-codex` and `merge` set an appropriate post-condition status.

Epistemic grounding:
- auditability + error correction rely on *trustworthy state*. (`docs/EPISTEMIC_GROUNDING.md` §3.7, §3.8)

Gate:
- new unit tests for status transitions
- smoke run: status should not remain `merging` after merge completes

### P0-C) Rename “targets” → “context anchors” (docs + CLI alias)
Problem:
- “Targets” reads like research is “about a folder”, which is backwards: runs are about questions; a path is optional grounding context.

Recommendation:
- Rename user-facing terminology to **context anchors** (brief template, docs, CLI help).
- Keep backwards compatibility:
  - continue accepting `--targets` as an alias
  - keep on-disk schema stable (treat existing `01_CONFIG.json.targets` as “context anchors”)

Epistemic grounding:
- reduce avoidable confusion induced by tool vocabulary (bounded rationality). (`docs/EPISTEMIC_GROUNDING.md` §3.9)

Gate:
- test: scaffold accepts `--context-anchor` and `--targets`

### P1) Reduce false conflict/agreement detection in merge
Problem:
- conflict grouping uses `original_claim_id` (producer-local `claim_id`) which can collide across producers.

Design constraint:
- keep merge deterministic; do not introduce embedding calls or heuristic LLM classification in v1.x.

Options:
1) Add an optional `topic_key` field to claim schema (string) and prefer it for cross-producer grouping.
2) Compute a deterministic fingerprint from normalized `(area, recommendation)` and use it for agreement grouping; keep “conflict” conservative.

Recommendation:
- implement (1) first (prompt-level + merge-level support), keep (2) as a later enhancement.

Epistemic grounding:
- Duhem–Quine + severe testing: avoid overconfident conflict declarations; prefer discriminating probes. (`docs/EPISTEMIC_GROUNDING.md` §3.2, §3.6)

Gate:
- fixtures demonstrating two producers with `C-0001` but unrelated claims should not automatically create a “conflict”.

### P1) Add a “task lint” quality gate (optional command or validate warnings)
Problem:
- tasks can be syntactically present but epistemically weak (missing contradiction protocol, stop rules, etc.).

Recommendation:
- implement a lightweight task linter that checks for required headings (case-insensitive).
- surface as warnings in `ar run validate` *or* as a new `ar run lint-tasks` command (prefer warnings to avoid CLI drift).

Epistemic grounding:
- organized skepticism requires enforceable norms, not hope. (`docs/EPISTEMIC_GROUNDING.md` §3.7)

Gate:
- tests for missing headings produce warnings (not hard errors unless we explicitly choose to)

### P2) Installer QoL (after core epistemic fixes)
Ideas:
- `aro setup` verifies the configured python command can run `-m ar --help`.
- non-interactive `aro init` can optionally write backups (`--backup`).

Gate:
- installer tests (no network; temp dirs only)

---

## 3) Expected outputs (deliverables)

- Updated docs/skills clarifying runner terminology
- Stronger, less confusing `STATE.json` status semantics
- Merge logic with conservative conflict detection (less noise)
- (Optional) task lint warnings
- Updated tests and a repeatable smoke run script snippet

---

## 4) Release strategy

After merging Phase 2 to `main`:
- bump + tag `aro-installer` if any installer/skill payload changed
- consider a GitHub Release note pointing to:
  - `docs/EPISTEMIC_GROUNDING.md`
  - `docs/CODEBASE_REVIEW_2026-03-04.md`
  - this Phase 2 plan
