# Phase 3 Plan (draft): Project‑Context Research + Multi‑Mode Runs

This phase expands `ar` from “run-bundle substrate + basic supervision” into a system that supports:
- **project-grounded** research (explicitly tied to a codebase / artifact set),
- **exploratory** research (not tied to any local project),
- an **extendable mode system** (more than `normal|guided`),
- and **multi-mode execution** using the *same* runner(s) (e.g., Codex-only).

Constraints remain unchanged:
- Keep the run bundle **deterministic** and **compaction-safe**.
- Keep runners **optional** (Codex-only runs must remain valid; Claude/Gemini are bonuses).
- Keep it **cross-platform** (Path handling, no mac-only assumptions).
- Avoid “LLM inference inside merge” (no embeddings/LLM clustering in the merger).

---

## 0) Terminology (what we mean)

### 0.1 Research is about questions, not folders
A run is anchored by:
- the **goal** (`00_BRIEF.md` + tasks), and
- optional **context anchors** (previously called “targets”): pointers to things the research should be grounded in (project repo, docs folder, design doc, etc.).

### 0.2 Context anchors (optional)
Context anchors are metadata pointers (paths today; possibly URLs later). They should:
- **not** be required for exploratory runs,
- but be easy to provide when research must be grounded in a project.

### 0.3 Context snapshots (optional, recommended for Codex automation)
A context snapshot is a **bounded, reproducible context pack** stored inside the run bundle.

Why it matters:
- Codex automation currently runs with `cwd=<run_dir>`. A snapshot makes project context available inside the run bundle without widening filesystem access.

### 0.4 Modes (extendable)
A mode is a research “lens” that biases:
- what evidence to prioritize,
- how to structure deliverables,
- what failure modes to actively hunt,
- and what quality gates apply.

Examples:
- `project_grounded` (use local context first; cite repo artifacts)
- `exploratory_landscape` (external scan; alternatives matrix; recency bias controlled)
- `adversarial_failure_modes` (counterexamples, threat model, “how could this be wrong?”)
- `implementation_ready` (turn claims into concrete next steps; risks + rollout plan)

Modes are not “rigid pipelines”. They are **prompt + policy presets** designed to reduce over-determinism without losing structure.

---

## 1) Why Phase 3 (problem statement)

Current v1.x strengths:
- Deterministic on-disk substrate.
- Multi-runner import/export.
- Deterministic merge + conservative conflict preservation.

Current v1.x gaps that affect research quality and UX:
1. **Project grounding is implicit** (you can write tasks “about a repo”, but automation doesn’t have a safe, reproducible way to see that repo).
2. “Modes” are currently under-specified (`normal|guided` only), so orchestrators tend to be either:
   - too free-form (inconsistent output), or
   - too schema-compliant (over-deterministic, shallow).
3. No first-class way to run **multiple modes in parallel** using the same runner(s) and then compare results cleanly.

---

## 2) Design decisions (with options + tradeoffs)

### 2.1 Where “mode” lives (task vs producer)
We want modes to work even when:
- only one runner exists,
- or the same runner executes multiple modes.

Options:
1) **Mode per task** (recommended baseline)
   - Orchestrator creates separate tasks for each mode variant (e.g., `T-0010__auth__project_grounded`, `T-0011__auth__adversarial`).
   - Pros: no new execution plumbing; parallelizable today.
   - Cons: cross-mode comparison is cross-task (merge currently compares within-task producers, not across tasks).

2) **Mode per producer output** (recommended enhancement)
   - Same task id, multiple producer outputs labeled with different modes.
   - Pros: mode comparison stays within the same task; merge comparison works naturally (especially with `topic_key`).
   - Cons: requires CLI/support changes (spawn/import need to record `mode` in provenance and/or producer id).

Phase 3 should implement (1) first and design for (2) without breaking compatibility.

### 2.2 How to make modes extendable (registry)
Options:
1) Built-in mode registry in code (fast, stable, but less user-configurable).
2) User-configurable registry file(s) loaded from:
   - run bundle config (`01_CONFIG.json`) and/or
   - a user-level location (cross-platform).

Recommendation:
- Start with a small set of built-in modes + a **simple registry file** override mechanism.
- Keep the “mode definition” format minimal: prompt addendum + required deliverables + quality gates.

### 2.3 Project grounding for Codex automation (snapshots)
Options:
1) **Snapshot** context anchors into the run bundle (recommended).
2) Run Codex with a wider filesystem sandbox and instruct it to read anchors in-place.

Recommendation:
- Prefer (1) because it is:
  - safer by default,
  - reproducible,
  - portable across machines/CI,
  - and aligned with “deterministic hands”.

Second-order consequences to explicitly manage:
- secrets leakage risk
- snapshot bloat
- staleness (snapshots can become outdated quickly)

---

## 3) Proposed CLI / artifact changes (non-breaking)

### 3.1 Rename “targets” → “context anchors” (Phase 2 closeout dependency)
- Keep accepting `--targets` as alias, but prefer `--context-anchor`.
- Keep on-disk `01_CONFIG.json.targets` stable for now (treat it as “context anchors” semantically).

### 3.2 New command: `ar run snapshot-anchors` (name TBD)
Purpose:
- Create bounded, reproducible context packs inside the run bundle for each context anchor path.

Outputs (example structure):
- `05_CONTEXT/`
  - `<anchor_label>/`
    - `MANIFEST.json`
    - `GIT.json` (if anchor is a git repo)
    - `TREE.txt`
    - `FILES/...` (curated copies)

Key flags (draft):
- `--run-dir <path>` (required)
- `--include <glob>` (repeatable; defaults to a safe minimal set)
- `--exclude <glob>` (repeatable; defaults to secret/bloat patterns)
- `--max-bytes <int>` and `--max-files <int>`
- `--redact <pattern>` (repeatable; optional)

### 3.3 Prompt exports become mode-aware
Add optional `--mode <mode_id>` to:
- `ar run export-prompts`
- `ar run export-orchestrator-prompt`

Behavior:
- Inject a mode-specific addendum into the prompt preamble:
  - priority of evidence
  - deliverable structure
  - explicit failure-mode search expectations
  - suggested `topic_key` slots if comparative synthesis is desired

### 3.4 Provenance becomes mode-aware (for comparisons)
Add optional `mode` to `PROVENANCE.json` (non-breaking).
- For manual imports, allow `ar run import --mode <mode_id>` (or store in `notes` if we want to avoid CLI expansion).
- For Codex spawn, record the mode used in the worker prompt.

---

## 4) Quality gates (beyond “tests pass”)

Between each sub-phase, run:
1) `pytest -q`
2) CLI help sanity:
   - `PYTHONPATH=src python3 -m ar --help`
   - `PYTHONPATH=src python3 -m ar run scaffold --help`
3) Smoke run (no external APIs):
   - scaffold → apply-plan → export-prompts → import → merge → validate → status
4) Snapshot safety sanity (human, 3–5 minutes):
   - confirm snapshot excludes `.env`, private keys, token files
   - confirm snapshot size is bounded and `MANIFEST.json` is present
5) Epistemic sanity (human, 3–5 minutes):
   - conflicts are not empty placeholders
   - residuals are not universally `none`
   - at least one probe exists for high-impact recommendations (when applicable)

---

## 5) Assumptions + Popperian probes (plan-level falsification)

Assumption A: “Context snapshots improve project-grounded research quality.”
- Probe: run the same task with and without snapshots (same runner/model), compare:
  - number of concrete repo-grounded citations
  - number of actionable recommendations
  - number of residuals that are actually discriminating (not generic)

Assumption B: “Modes reduce over-determinism without collapsing into free-form.”
- Probe: execute the same task across multiple modes; check whether:
  - outputs differ in *method* (evidence type, failure-mode coverage),
  - but still preserve required artifacts (registers + residuals).

Assumption C: “Mode-aware provenance improves comparisons.”
- Probe: evaluate `30_MERGE/COMPARISON.*` readability and whether divergences are more interpretable when `mode` is present.

---

## 6) Implementation steps (sequenced)

1) **Spec + doc updates**
   - Finalize terminology: “context anchors”, “context snapshots”, “modes”.
   - Document the non-breaking provenance `mode` field.

2) **Context snapshot command (minimal viable)**
   - Implement bounded copying + manifest + safe defaults.
   - Cross-platform path handling and size caps.

3) **Mode registry + prompt injection (minimal viable)**
   - Implement a small built-in set of modes.
   - Add `--mode` to prompt exports (or orchestrator prompt only first).

4) **Mode-aware provenance + comparisons**
   - Record mode in provenance where possible.
   - Show mode in `COMPARISON.md` table.

5) **(Optional) Mode-per-producer execution**
   - Allow one runner to execute the same task under multiple modes (stored as multiple producer outputs).
   - Ensure `topic_key` remains the conservative cross-output match key.

---

## 7) Open questions (need decisions before coding too far)

1) Should “context anchors” support non-path anchors (URLs) now, or later?
2) Where should the user-level mode registry live (cross-platform)?
3) Do we want mode selection to be:
   - explicit operator choice,
   - or orchestrator-selected after a “discovery discussion” phase,
   - or both?
4) How strict should snapshot redaction be by default (false positives vs leakage risk)?

