# Multi‑Orchestrator Supervisor Layer (v1) — Implementation Plan

Goal: allow **Codex**, **Claude (Code/Desktop/Cowork)**, and **Gemini (DR/CLI)** to act as the *orchestrator brain* for a research run, while `ar` remains the deterministic *on‑disk executor* (“hands”).

This plan is written to be:
- compaction-safe (decisions written down),
- explicit about tradeoffs,
- conservative about security and nondeterminism,
- aligned with `docs/RUN_BUNDLE_SPEC.md` + `docs/CLI_SPEC.md` + `docs/IMPLEMENTATION_PLAN.md`.

---

## 0) Current baseline (what exists today)

`ar` currently provides a **run-bundle substrate**:
- `ar run scaffold` creates the run bundle layout.
- You (a human) write canonical tasks in `10_TASKS/*.md`.
- Producers (“agents”) write normalized outputs under `20_WORK/<task>/<producer_id>/`:
  - automated: `ar run spawn-codex` (spawns `codex exec --json` workers)
  - manual: `ar run import` (imports Claude/Gemini/Cowork output)
- `ar run merge` synthesizes `30_MERGE/*` and produces `COMPARISON.{md,json}`.
- `ar run validate/status` provide structural checks and operator summaries.

What is missing (and why the system can feel “not agentic”):
- There is no supervisor loop that *generates tasks* from `00_BRIEF.md` / context anchors, *iterates*, and *spawns follow-ups* based on conflicts/gaps.

---

## 1) Design goals

### 1.1 Functional goals

1. **Any runner can be the orchestrator brain**
   - Codex, Claude Code, Cowork, Gemini CLI should be able to propose the next steps for a run.
2. **`ar` remains the single-writer executor**
   - Only `ar` mutates `STATE.json` and writes tasks to `10_TASKS/`.
3. **Two integration modes**
   - **Offline plan mode** (works everywhere): orchestrator emits a JSON “plan” → `ar` applies it.
   - **Tool mode** (optional): orchestrator uses MCP tools to call `ar` commands directly.
4. **Auditable + resumable**
   - Every orchestration decision is captured on disk (plan snapshots, logs).
5. **Graceful degradation**
   - Optional providers remain optional; runs remain valid/useful with Codex-only outputs.

### 1.2 Non-goals (v1)

- Building a general agent framework (memory store, vector DB, long-term persona, etc.).
- Managing provider authentication inside `ar` (no API keys stored in run bundles).
- Making synthesis “fully automatic and always correct.” Conflicts/residuals must remain visible.

---

## 2) Key architectural move: “brain vs hands”

### 2.1 The split

- **Brain (nondeterministic)**: decides what to do next, proposes tasks, probes, stop rules.
- **Hands (deterministic)**: writes files, spawns processes, merges outputs, validates structure, logs everything.

`ar` should be the **hands**.

### 2.2 Why this matters (second-order consequences)

If we let an LLM directly write arbitrary files / run arbitrary commands:
- we lose auditability (“what changed and why?”),
- we increase security risk (accidental repo mutation, secrets leakage),
- we get inconsistent run structure (format drift across runners).

If we force everything into rigid schemas:
- we incentivize “compliance theater”,
- we lose nuance/residuals (the over-determinism failure mode called out in `docs/IMPLEMENTATION_PLAN.md`).

So we keep the substrate deterministic, and let the brain be flexible—but only via **constrained interfaces**.

---

## 3) Orchestrator interface option A (recommended first): Offline plan → apply

### 3.1 Concept

Any orchestrator (Codex/Claude/Gemini) can output a single JSON object: an **Orchestrator Action Plan**.

`ar` then:
1) validates it (schema + safety),
2) stores it on disk,
3) applies allowed actions deterministically (usually: create/update tasks),
4) logs the reason (`task_generation` / `plan_applied`).

This mode works even when the orchestrator cannot call tools.

### 3.2 Where plans live on disk

Add an optional directory (does not change required bundle contract):

- `12_SUPERVISOR/`
  - `PLANS/PLAN_<ts>__<orchestrator>.json`
  - `PLANS/PLAN_<ts>__<orchestrator>.md` (optional “human readable” rendering)
  - `PROMPTS/…` (templates used, for audit)

### 3.3 Plan schema (v1)

File: `OrchestratorPlan` JSON.

Minimum structure:
```json
{
  "schema_version": 1,
  "generated_at": "ISO8601",
  "orchestrator": {
    "runner": "codex|claude_code|cowork|gemini_cli|claude_desktop|gemini_deep_research",
    "model": "string",
    "reasoning_effort": "string",
    "notes": ""
  },
  "assumptions": [
    {"id": "A1", "text": "...", "falsify": "..."}
  ],
  "stop_rules": [
    {"id": "S1", "text": "..."}
  ],
  "actions": [
    {
      "type": "create_task",
      "task_id": "T-0001",
      "slug": "kebab-case",
      "reason": "why this task exists (gap/conflict/probe)",
      "task_markdown": "# Task ... (full canonical task file body)"
    }
  ]
}
```

Rules:
- `actions[].type` initially supports only:
  - `create_task`
  - `update_task` (optional v1.1; see below)
- `task_id` must match `T-\\d{4}`.
- `slug` is used only for filename; `ar` owns the final filename format: `10_TASKS/<task_id>__<slug>.md`.

### 3.4 New CLI commands (offline mode)

1. `ar run export-orchestrator-prompt --run-dir ... --runner <runner>`
   - Writes a copy/paste prompt instructing the orchestrator to emit `OrchestratorPlan` JSON only.
   - Includes run brief + config + current status summary + merge summary (if present).

2. `ar run apply-plan --run-dir ... --plan-path <json>`
   - Validates plan schema.
   - Writes plan snapshot under `12_SUPERVISOR/PLANS/`.
   - Applies `create_task` actions by writing task files under `10_TASKS/`.
   - Appends `task_generation` (and/or `plan_applied`) to `LOG.jsonl`.
   - Updates `STATE.json.tasks` to include new tasks as `pending`.

### 3.5 Pros / cons

Pros:
- Works with *any* runner, even “single-response” UIs.
- Deterministic application and auditing.
- No need to expose tool execution surface (safer).

Cons:
- Requires a manual step (copy/paste plan JSON + apply).
- Orchestrator can’t “see” tool outputs except what we include in the prompt snapshot.

---

## 4) Orchestrator interface option B (optional): MCP tool mode

### 4.1 Concept

Run an MCP server that exposes `ar` operations as tools.
Claude Code (and other MCP clients) can become the orchestrator by calling tools:
- `scaffold`, `status`, `export_prompts`, `spawn_codex`, `merge`, `validate`, `import`, `apply_plan`, etc.

### 4.2 Security model (must be explicit)

Second-order risks:
- Tool mode grants a model a *write-capable interface* to your filesystem and process runner.
- Without guardrails, this becomes “remote code execution by prompt injection.”

Mitigations (v1 requirements if MCP is implemented):
- Server is **local only**.
- Every tool must require an explicit `run_dir` and must only read/write **inside that run dir**.
- No arbitrary shell execution tool.
- No secrets stored in run dir; no environment dumps.
- Consider a “write enabled” flag at server start: read-only MCP by default.

### 4.3 Pros / cons

Pros:
- True “agentic” feel: orchestrator can iterate quickly and react to outputs.
- Eliminates manual copy/paste steps for task creation and running.

Cons:
- Significantly higher security and UX complexity.
- Requires MCP client availability and setup.
- Harder to keep “no drift” behavior stable across clients.

Recommendation: implement offline plan mode first; add MCP once the plan schema is stable and tested.

---

## 5) Codex as orchestrator (automation path)

Even without MCP, Codex can be fully automated by having `ar` run Codex to produce an `OrchestratorPlan`.

### 5.1 New command: `ar run generate-tasks` (Codex-only v1)

`ar run generate-tasks --run-dir ... --model ... --reasoning ... --sandbox ...`
- Spawns a *single* Codex “supervisor” run (not per-task) that outputs an `OrchestratorPlan` JSON.
- `ar` extracts the JSON, saves it under `12_SUPERVISOR/PLANS/`, and runs `apply-plan`.
- Logs `task_generation` with the reason and orchestrator provenance.

Why Codex-only first:
- It already has an automated runner (`codex exec --json`) and telemetry.
- It keeps the “hands” in one place (the local CLI).

---

## 6) Make assumptions explicit + falsifiable (Popperian checks)

This system depends on assumptions that can be wrong. We should treat them as hypotheses and actively try to falsify them.

### 6.1 Assumption candidates (examples)

H1: “LLM-generated tasks reduce operator overhead without lowering research quality.”
- Falsify by A/B testing:
  - A: human-written tasks
  - B: generated tasks via `generate-tasks`
  - Compare: conflict discovery rate, coverage gaps, number of follow-up tasks needed, time-to-usable `30_MERGE/REPORT.md`.

H2: “A single JSON plan schema is runner-agnostic enough for Codex/Claude/Gemini.”
- Falsify by running export prompt against each runner and measuring parse success + plan quality.
- If a runner fails to emit valid JSON reliably, we tighten the prompt template or add a “markdown plan” fallback with deterministic parsing rules.

H3: “Offline plan mode is sufficient for most workflows; MCP is optional.”
- Falsify by measuring operator friction:
  - number of copy/paste actions per iteration
  - rate of formatting/import errors
  - user time-to-next-iteration

### 6.2 What to log for falsification

For each run iteration:
- `task_generation` events with reason and counts
- which runner acted as orchestrator
- how many tasks created, how many executed, and which divergences/conflicts drove follow-ups

---

## 7) Implementation phases (recommended)

### Phase 1 — Offline plan primitives (runner-agnostic)

Deliverables:
- `OrchestratorPlan` schema doc (this file + a JSON schema if desired)
- `ar run export-orchestrator-prompt`
- `ar run apply-plan`
- Unit tests: schema validation, safe path enforcement, idempotency (no duplicate tasks), logging.

Acceptance criteria:
- A plan produced by any runner can create tasks deterministically under `10_TASKS/`.
- `STATE.json` and `LOG.jsonl` are updated correctly (single-writer).

#### Phase 1 quality gates (beyond unit tests)

Security / safety:
- `apply-plan` refuses to write outside `10_TASKS/` (path confinement).
- `apply-plan` is create-only by default (no silent edits to existing tasks).
- `apply-plan --dry-run` performs no mutations to `10_TASKS/`, `STATE.json`, or `LOG.jsonl`.

Auditability / compaction safety:
- Plan snapshots are saved under `12_SUPERVISOR/PLANS/` (unless `--dry-run`).
- `LOG.jsonl` records `task_generation` with a reason and orchestrator provenance.

Operator UX:
- Prompts exported by `export-orchestrator-prompt` are copy/paste-ready and request JSON-only output.

#### Phase 1 → Phase 2 go/no-go checklist (operator)

Preconditions:
- You can scaffold a run bundle.
- You can export a prompt and apply a plan without mutating anything unexpected.

Commands (copy/paste):
```bash
cd /path/to/agentic-research-orchestrator
AR="PYTHONPATH=src python3 -m ar"

RUN_DIR=$($AR run scaffold --runs-root /tmp/ar-runs --slug smoke --goal "smoke test")

# Export prompt (for any orchestrator UI)
$AR run export-orchestrator-prompt --run-dir "$RUN_DIR" --runner claude_code

# Apply a minimal plan (create-only) to ensure task writing + state/log updates work
cat > /tmp/plan.json <<'JSON'
{
  "schema_version": 1,
  "generated_at": "2026-03-03T00:00:00-05:00",
  "orchestrator": {"runner": "claude_code", "model": "", "reasoning_effort": "", "notes": ""},
  "assumptions": [{"id": "A1", "text": "The brief is correct.", "falsify": "Look for contradictions in sources."}],
  "stop_rules": [{"id": "S1", "text": "Stop after producing a usable synthesis with explicit conflicts."}],
  "actions": [
    {
      "type": "create_task",
      "task_id": "T-0001",
      "slug": "smoke",
      "reason": "smoke test task creation",
      "task_markdown": "# Task T-0001: Smoke\\n\\n## Intent\\nProve the pipeline can run end-to-end.\\n\\n## Assumptions & falsification probes\\n- Assumption: The run bundle contract is sufficient.\\n  - Falsify by: Identify missing required files for a producer output.\\n\\n## Deliverables (required)\\n- REPORT.md\\n- SOURCES.json\\n- CLAIMS.json\\n- RESIDUALS.md\\n"
    }
  ]
}
JSON
$AR run apply-plan --run-dir "$RUN_DIR" --plan-path /tmp/plan.json

$AR run validate --run-dir "$RUN_DIR"
$AR run status --run-dir "$RUN_DIR"
```

Go/no-go:
- GO if `10_TASKS/T-0001__smoke.md` exists, `STATE.json` lists `T-0001`, and `LOG.jsonl` includes `task_generation`.
- NO-GO if apply-plan writes outside `10_TASKS/`, mutates on `--dry-run`, or fails idempotency.

### Phase 2 — Codex auto-orchestrator

Deliverables:
- `ar run generate-tasks` (Codex) that produces plan JSON and applies it.
- Tests gated when `codex` is unavailable (fixture-based parsing tests).

Acceptance criteria:
- End-to-end: scaffold → generate-tasks → spawn-codex → merge → validate works with no manual task writing.

#### Phase 2 quality gates (beyond unit tests)

Cost / configuration safety:
- `generate-tasks` must pass explicit model + reasoning overrides to `codex exec` (must not rely on global Codex config defaults).
- `generate-tasks` must default to `01_CONFIG.json` codex settings when flags are absent.

Observability:
- Supervisor session artifacts are saved (prompt, events, last message, provenance).
- `LOG.jsonl` records `generate_tasks_started`/`generate_tasks_finished` (or equivalent) and links to session paths.

Failure modes:
- Timeouts are handled deterministically (terminate/kill) and logged as `warn`/`error` with enough context to debug.
- If Codex output is non-JSON or malformed, the run fails loudly and stores raw output for inspection.

#### Phase 2 → Phase 3 go/no-go checklist (operator)

Preconditions:
- The `codex` binary exists (or you can run tests which use a fake `codex`).

Commands (real Codex):
```bash
cd /path/to/agentic-research-orchestrator
AR="PYTHONPATH=src python3 -m ar"

RUN_DIR=$($AR run scaffold --runs-root /tmp/ar-runs --slug demo --goal "Demo run")

# Supervisor generates tasks (writes session artifacts under 12_SUPERVISOR/SESSIONS/)
$AR run generate-tasks --run-dir "$RUN_DIR" --model gpt-5.2 --reasoning high --sandbox read-only

$AR run status --run-dir "$RUN_DIR"
```

Go/no-go:
- GO if `12_SUPERVISOR/SESSIONS/.../PROVENANCE.json` exists, the plan parses, and tasks are created + registered in `STATE.json`.
- NO-GO if generate-tasks relies on global Codex config (missing explicit override), fails to store raw output on error, or mutates tasks/state/log on `--dry-run`.

### Phase 3 — Iteration loop (still offline-plan compatible)

Deliverables:
- `ar run export-orchestrator-prompt` includes merge summaries + divergences.
- Optional: `ar run propose-followups` (brain) that emits new plan based on `30_MERGE/*`.
- (Recommended) Prompt profiles for capability:
  - “normal” (current): compact, assumes competent orchestrator
  - “guided/low-capability”: more step-by-step, includes fill-in templates + explicit checklists

Acceptance criteria:
- Operator can iterate: run tasks → merge → prompt orchestrator → apply-plan follow-ups.
- A “guided” prompt produces valid plans reliably (JSON-only, schema v1) on weaker models / less capable agents.

#### Phase 3 quality gates

Prompt quality (runner-agnostic):
- Orchestrator prompt includes: current `STATE.json`, task list, and a *bounded* merge summary (top conflicts + residuals + divergences).
- Prompt explicitly states: create-only tasks; JSON-only output; no markdown fences; no extra text.
- Prompt includes a “task spec template” (see below) so weaker agents don’t invent formats.

Loop discipline:
- Stop rules are explicit and recorded (avoid infinite “interesting” research).
- Follow-up tasks are always justified by a *specific* conflict/divergence/residual (no unbounded scope creep).

Task quality (for follow-up tasks):
- Each new task must include:
  - a one-sentence “why now” justification tied to a specific merge artifact (conflict id / divergence / residual)
  - at least one explicit falsification probe (counterexample hunt, alternative hypothesis test, or boundary check)
  - explicit deliverables (which files the producer must write; required headings/fields)
- “Search budget” (time/cost/recency) is either inherited from `00_BRIEF.md` constraints or restated in the task.

Non-destructiveness:
- Merge remains non-destructive across iterations (claims/sources only accumulate; conflicts remain visible).

Regression guard:
- A follow-up iteration must not reduce observability: logs, plan snapshots, and merge comparison artifacts remain present.

#### Phase 3 → Phase 4 go/no-go checklist (operator)

Commands (one full iteration loop):
```bash
cd /path/to/agentic-research-orchestrator
AR="PYTHONPATH=src python3 -m ar"

# After you have tasks and at least one producer output:
$AR run spawn-codex --run-dir "$RUN_DIR"
$AR run merge --run-dir "$RUN_DIR"
$AR run validate --run-dir "$RUN_DIR"

# Export a follow-up orchestrator prompt that includes merge context:
$AR run export-orchestrator-prompt --run-dir "$RUN_DIR" --runner gemini_cli
```

Go/no-go:
- GO if merge+validate are deterministic across re-runs, conflicts remain visible (not “resolved away”), and follow-up tasks can be justified by specific merge artifacts.
- NO-GO if iteration silently edits prior tasks, deletes claims/sources, or loses conflict/residual visibility.

### Phase 4 — MCP server (optional)

Deliverables:
- `ar mcp serve` exposing safe tools.
- Strict run-dir confinement + write gating.

Acceptance criteria:
- Claude Code can act as orchestrator without manual copy/paste.

#### Phase 4 quality gates

Threat model / safety review (required):
- Server is local-only; no remote listening by default.
- Every tool is confined to a provided `run_dir` and rejects writes outside it.
- No “arbitrary shell” tool is exposed.
- Write-capable tools are gated behind an explicit enable flag (read-only default).
- Symlink escape is prevented (reject paths that resolve outside `run_dir`, even if the textual path is inside).
- Tool calls are rate-limited and have timeouts (prevent runaway loops).
- Tool input is treated as untrusted (prompt-injection hardened): validate schemas; never execute arbitrary code or templates.

Operator trust:
- All tool calls are logged (who/what/when), and failures are actionable.
- Provide a clear “audit trail” location (e.g., `12_SUPERVISOR/MCP_LOG.jsonl`) separate from `LOG.jsonl` if needed.

---

## Appendix A — Guided prompting for low-capability orchestrators (recommended)

Some orchestrators (or “agent wrappers”) struggle with:
- strict JSON-only outputs,
- consistent task formatting,
- tying follow-ups to concrete conflicts/residuals.

Mitigation: export a more guided prompt variant that includes a fill-in template and a self-check rubric.

### A.1 Minimal “task spec template” (include verbatim in the prompt)

Each `actions[].task_markdown` should follow this structure:
```md
# Task T-XXXX: <short title>

## Intent
<one paragraph: what is the question and why it matters>

## Why now (tie to evidence)
- Trigger: <conflict/divergence/residual id or filename>
- Explanation: <why this task resolves uncertainty>

## Assumptions & falsification probes
- Assumption: <A?>
  - Falsify by: <probe that could prove it wrong>

## Constraints / budget
- Time:
- Cost:
- Recency:
- Allowed sources:

## Deliverables (required)
- REPORT.md: <required sections>
- SOURCES.json: <required fields>
- CLAIMS.json: <required fields>
- RESIDUALS.md: <what to put here>

## Notes
<optional>
```

### A.2 Plan self-check rubric (include in prompt)

Before emitting the final JSON plan, the orchestrator must verify:
1) Output is a single JSON object (no prose, no fences).
2) `schema_version=1`.
3) Each action is `create_task` and uses a fresh `T-XXXX`.
4) Every task has at least one falsification probe.
5) Every task has explicit deliverables and constraints.

---

## Appendix B — Few-shot OrchestratorPlan examples (copy/edit)

These examples are intentionally small and conservative. They are designed to “teach” weaker orchestrators the expected shape and discipline.

### B.1 Example: Bootstrap a run with two tasks

```json
{
  "schema_version": 1,
  "generated_at": "2026-03-03T00:00:00-05:00",
  "orchestrator": {
    "runner": "codex",
    "model": "gpt-5.2",
    "reasoning_effort": "high",
    "notes": "Bootstrap: map source landscape + probe for counterexamples."
  },
  "assumptions": [
    {
      "id": "A1",
      "text": "The brief’s goal is well-scoped and has a finite stopping point.",
      "falsify": "Identify at least one plausible alternative framing and show how it changes task choice."
    }
  ],
  "stop_rules": [
    {
      "id": "S1",
      "text": "Stop after (a) at least one producer has completed each task and (b) merge lists explicit conflicts + residuals."
    }
  ],
  "actions": [
    {
      "type": "create_task",
      "task_id": "T-0001",
      "slug": "source-landscape",
      "reason": "Need a concrete evidence base before conclusions.",
      "task_markdown": "# Task T-0001: Source landscape\\n\\n## Intent\\nBuild a minimal, high-signal source set that directly bears on the run goal.\\n\\n## Assumptions & falsification probes\\n- Assumption: Authoritative sources exist.\\n  - Falsify by: If sources are scarce/low-quality, document why and what substitutes are acceptable.\\n\\n## Constraints / budget\\n- Recency: follow 00_BRIEF.md\\n- Allowed sources: follow 00_BRIEF.md\\n\\n## Deliverables (required)\\n- REPORT.md: include \"What we looked for\" and \"What we found\"\\n- SOURCES.json: include at least 5 sources with short annotations\\n- CLAIMS.json: only claims explicitly supported by sources\\n- RESIDUALS.md: unanswered questions + proposed probes\\n"
    },
    {
      "type": "create_task",
      "task_id": "T-0002",
      "slug": "counterexamples",
      "reason": "Prevent over-determinism by actively searching for disconfirming cases.",
      "task_markdown": "# Task T-0002: Counterexamples and failure modes\\n\\n## Intent\\nTry to disconfirm the dominant hypothesis emerging from T-0001.\\n\\n## Assumptions & falsification probes\\n- Assumption: The main hypothesis could be wrong in at least one realistic scenario.\\n  - Falsify by: Find a credible counterexample or show why none is plausible under the constraints.\\n\\n## Deliverables (required)\\n- REPORT.md: include \"Best counterexample\" and \"What would change our mind\"\\n- SOURCES.json: include counterexample sources with role=counterexample when applicable\\n- CLAIMS.json: include incompatible claims (do not resolve them)\\n- RESIDUALS.md: list remaining probes\\n"
    }
  ]
}
```

### B.2 Example: Follow-up plan tied to a merge conflict

```json
{
  "schema_version": 1,
  "generated_at": "2026-03-03T00:00:00-05:00",
  "orchestrator": {
    "runner": "gemini_cli",
    "model": "",
    "reasoning_effort": "",
    "notes": "Follow-up: resolve a specific conflict by narrowing scope + testing boundary conditions."
  },
  "assumptions": [
    {
      "id": "A1",
      "text": "The conflict is resolvable by defining terms and checking a boundary case.",
      "falsify": "If term definitions still allow both claims, document why the conflict is irreducible."
    }
  ],
  "stop_rules": [
    {
      "id": "S1",
      "text": "Stop once the conflict is either (a) resolved with evidence or (b) promoted to an explicit, irreducible conflict with clear decision implications."
    }
  ],
  "actions": [
    {
      "type": "create_task",
      "task_id": "T-0003",
      "slug": "conflict-boundary-test",
      "reason": "30_MERGE/CONFLICTS.md indicates incompatible claims; we need a targeted boundary test.",
      "task_markdown": "# Task T-0003: Conflict boundary test\\n\\n## Intent\\nInvestigate one explicit conflict from 30_MERGE/CONFLICTS.md by (1) defining terms, then (2) testing a boundary case.\\n\\n## Why now (tie to evidence)\\n- Trigger: 30_MERGE/CONFLICTS.md\\n- Explanation: A narrow test can clarify whether the conflict is real or due to scope mismatch.\\n\\n## Assumptions & falsification probes\\n- Assumption: The conflict depends on an implicit scope condition.\\n  - Falsify by: Find a source that states the scope condition explicitly (or contradicts it).\\n\\n## Deliverables (required)\\n- REPORT.md: include \"Term definitions\" and \"Boundary case\"\\n- SOURCES.json\\n- CLAIMS.json: preserve both incompatible claims if still incompatible\\n- RESIDUALS.md\\n"
    }
  ]
}
```

---

## 8) Open decisions (explicit)

1. Should `apply-plan` support `update_task` in v1?
   - Pro: easier refinement; Con: accidental edits; Mitigation: require explicit `--allow-updates`.
2. Should we include a JSON Schema file for `OrchestratorPlan`?
   - Pro: validation, editor support; Con: upkeep; Recommendation: yes (small, stable).
3. Should we store orchestrator provenance in `STATE.json`?
   - Pro: quick status; Con: state churn; Recommendation: store in plan snapshot + `LOG.jsonl`, keep `STATE.json` minimal.

---

## 9) Summary recommendation

Start with **offline plan mode** (export prompt → plan JSON → apply-plan) because it is:
- runner-agnostic,
- compaction-safe,
- auditable,
- and low-risk.

Then add:
- Codex `generate-tasks` for automation,
- iteration helpers,
- and only then MCP tool mode if/when you want Claude Code (or Gemini CLI) to orchestrate via tool calls.
