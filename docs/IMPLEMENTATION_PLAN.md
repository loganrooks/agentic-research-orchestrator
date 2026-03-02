# Agentic Research Orchestrator (Repo-Agnostic)
## Implementation Plan (v1, Compaction-Safe)

This document is intentionally long and explicit. It is written so a less capable agent (or a tired human) can execute it without “reading between the lines”.

Every major instruction includes a **Why** section to reduce misinterpretation.

## Read Order (so you don’t miss the important parts)
1. `docs/IMPLEMENTATION_PLAN.md` (this file): why + what we are building.
2. `docs/RUN_BUNDLE_SPEC.md`: canonical on-disk contract (source of truth for structure).
3. `docs/TASK_WRITING_GUIDE.md`: how to write tasks without over-determinism.
4. `docs/RUNNER_GUIDES/*`: runner-specific constraints and expectations.
5. `docs/CLI_SPEC.md`: exact CLI surface to implement (prevents drift).

---

## 1) Problem Statement

We want a research workflow that is:

1. **Repo-agnostic**: works for any repository or “no repo at all”.
2. **Compaction-safe**: critical state lives on disk, not only in chat context.
3. **Parallelizable**: can run multiple research threads concurrently.
4. **Epistemically rigorous**: explicitly handles contradictions, assumptions, and uncertainty.
5. **Non-dogmatic**: supports structured outputs *without forcing everything* into rigid schemas.

## 1.1 Requirements Recovered From Prior Discussion (so we don’t lose nuance)

These requirements are included explicitly because they are easy to “almost implement” incorrectly:

1. **Cowork should be treated as a research orchestrator**, not a single-thread writer.
   - Why: delegation reduces context bloat and improves thoroughness, but only if the orchestration protocol is explicit.
2. **Claude Desktop Research mode likely outputs a single report** (not multiple files), and we should not assume otherwise.
   - Why: incorrect assumptions about output format lead to missing registers and unusable synthesis.
3. **Avoid over-determinism and arbitrary numeric quotas** (e.g., “>= 25 claims”).
   - Why: quotas incentivize padding; we want epistemic reliability and decision clarity.
4. **Synthesis must not be mechanical concatenation**.
   - Why: concatenation hides conflicts/overlaps and produces “big but not useful” reports.
5. **Claims are not the only format**; they must be supplemented with residuals and narrative explanation.
   - Why: some insights are tensions, framings, or uncertainties that do not compress cleanly into claim objects.
6. **Reference designs** should be captured with their underlying assumptions and conditions, not copied blindly.
   - Why: reference designs only work under specific constraints; we need the constraints explicit to choose correctly.
7. **Codex does not provide true subagent parallelism inside one context**; parallelism comes from multiple processes.
   - Why: planning a “subagent system” inside one Codex run will silently fail and create false expectations.
8. **Parallel threads should be automatable and monitorable**; the supervisor should monitor exec processes.
   - Why: without monitoring, parallelism becomes “many failures faster.”
9. **Initial settings should be set intentionally** (model/reasoning/timeouts), and the first interaction should ask clarifying questions without being reductive.
   - Why: defaults can accidentally become extremely expensive (e.g., global `xhigh`) or too weak; we need intentional configuration.

---

## 2) Core Design Principles (and why)

### Principle A: Disk is the source of truth
**Instruction:** Everything needed to resume or audit a run must be written to a run directory on disk.

**Why:** Chat context gets compacted, sessions get interrupted, and parallel workers can’t share ephemeral memory safely.

### Principle A.1: Every rule needs a reason
**Instruction:** When the plan/tooling tells an agent to do something, we also record *why* (the failure mode it prevents, the tradeoff it makes).

**Why:** Without reasons, agents satisfy the letter of the instruction while violating intent. Most “mysterious failures” are really silent assumption drift.

### Principle B: Structure exists to support synthesis, not to reduce nuance
**Instruction:** Use structured registers (claims/sources) as *indexes*, but preserve “residuals” for insights that don’t fit.

**Why:** Over-structuring causes lossy compression: the system becomes “neat but wrong”, and future synthesis loses the important tensions.

### Principle C: Preserve conflicts rather than averaging them away
**Instruction:** If two producer outputs disagree, keep both and record the *conditions* that may explain the disagreement.

**Why:** “Averaging” conflicting advice produces brittle policies and hides key assumptions. We want disagreement to be *visible and actionable*.

### Principle D: “Falsification” is procedural, not a checkbox
**Instruction:** For each high-impact recommendation, explicitly attempt to find counterexamples or failure modes. Where strict falsification doesn’t apply, use discriminating probes/experiments.

**Why:** The goal is epistemic reliability. A mechanical “try to falsify” checklist without counterexample search is performative and misses failure modes.

### Principle D.1: Avoid over-determinism (protocols over quotas)
**Instruction:** Prefer procedures (loops, roles, stop rules, explicit quality review) over rigid numeric quotas (e.g., “>= 25 claims”).

**Why:** Quotas bias outputs toward padding. We want decision-ready guidance, which is qualitative and depends on evidence quality and contradiction handling, not volume.

### Principle E: Single-writer state; multi-writer work dirs
**Instruction:** Only the supervisor writes `STATE.json`. Workers only write inside their own producer directory.

**Why:** Prevents race conditions and corruption during parallel execution.

---

## 3) Glossary (terms we will use consistently)

### Run
A single research execution instance (scaffold → produce → merge → validate).

### Run bundle
The directory on disk that contains the run’s brief, tasks, outputs, logs, and synthesis.

### Runner
A platform producing research outputs. Examples:
- `codex` (automated via `codex exec`)
- `claude_desktop` (manual copy/paste import)
- `cowork` (manual import; may itself orchestrate subagents)
- `gemini_deep_research` (manual import)
- `gemini_cli` (manual import initially; automation optional later)

### Producer
A specific agent instance on a runner. Example: `codex:worker-01` or `gemini_deep_research:manual-01`.

### Claim
A structured, indexable “recommendation/hypothesis” object. Not all insights should be forced into claims.

### Residuals
Important information that does not compress well into claim schema:
- competing framings
- interpretive tensions
- anomalies/unknowns
- meta-level advice about *how to run* the research

### Probe (discriminating observation/experiment)
A small test or observation that differentiates between competing hypotheses/recommendations.

Examples:
- Run the same workflow on a repo with weak tests vs strong tests; compare rework rate and failures.
- Run the same research task at two reasoning levels; compare contradiction resolution quality vs tokens.

**Why:** Many strategic recommendations are conditional and not strictly “falsifiable” in a clean lab sense. Probes are the operational substitute.

### Non-goal
Explicitly not in scope for v1 (to prevent infinite expansion).

**Why this exists:** “Non-goals” reduce accidental scope creep. They do *not* mean “never do this”; they mean “this v1 is not responsible for solving it”.

---

## 4) Repo and Storage Layout (fixed defaults)

### 4.1 Repo
Create a standalone repo at:
- `/Users/rookslog/Development/agentic-research-orchestrator`

**Why:** We want this to be reusable across projects and not entangled with any one repo’s schemas.

### 4.2 Default runs root (outside repos)
Default:
- `~/.ar/runs` (expanded to `/Users/rookslog/.ar/runs` on this machine)

Overrides:
- CLI `--runs-root <path>`
- Env `AR_RUNS_ROOT=<path>`

**Why:** Avoids dirtying target repos and prevents “run artifacts” from becoming uncommitted noise in development trees.

---

## 5) Run Bundle Contract (hard requirements)

Run path:
`$AR_RUNS_ROOT/YYYY-MM-DD/<timestamp>__<slug>__<run_id>/`

Required top-level files/dirs:
1. `00_BRIEF.md`
2. `01_CONFIG.json`
3. `STATE.json`
4. `LOG.jsonl`
5. `10_TASKS/`
6. `20_WORK/`
7. `30_MERGE/`

### 5.1 `00_BRIEF.md` (human-facing)
Required sections:
1. **Decision / Goal**
2. **Motivating context** (why now; what’s failing today)
3. **Non-goals**
4. **Constraints** (time, cost, recency, allowed sources)
5. **Targets** (repos/products; can be “none”)
6. **Priors + what would change your mind**
7. **Output preferences** (depth, style, audience)

**Why:** The brief is what prevents the run from drifting into unrelated “interesting” research.

### 5.2 `01_CONFIG.json` (machine)
Required keys (v1):
- `schemas_version` (int, start at 1)
- `run_id` (string)
- `created_at` (ISO8601)
- `created_by` (string; may be empty)
- `targets` (list of `{path,label}`)
- `runner_plan` (list of runner ids)
- `codex`:
  - `model_default` (default `gpt-5.2`)
  - `reasoning_default` (default `high`)
  - `sandbox_default` (default `read-only`)
  - `max_workers` (default `3`)
  - `timeout_seconds` (default `1800`)
- `quality_policy`:
  - `preserve_conflicts` (true)
  - `require_residuals` (true)
  - `allow_exceptions` (true)
  - `citation_preference` (`links_ok|no_links|mixed`)

**Why:** This file makes the run reproducible and lets automated tooling (merge/validate) make decisions without guessing.

### 5.3 `STATE.json` (single-writer; supervisor only)
Required keys:
- `status` (`scaffolded|running|merging|validated|failed|partial`)
- `current_step` (string)
- `started_at`, `finished_at` (ISO8601 or empty)
- `tasks` (list):
  - `task_id`
  - `status` (`pending|running|done|failed|skipped`)
  - `producers` (list of producer ids)
- `exceptions` (list of supervisor-level exceptions)

**Why:** Enables safe resume and prevents duplicate work after interruption.

### 5.4 `LOG.jsonl` (append-only)
Each line is a JSON object with:
- `ts` (ISO8601)
- `level` (`info|warn|error`)
- `event` (string)
- `data` (object)

**Why:** Debugging parallel systems without logs is guesswork. This is the minimal trace.

---

## 6) Task Files (`10_TASKS/…`) — format and “try to falsify”

Task file name:
`10_TASKS/T-0001__<slug>.md`

Required sections:
1. **Task intent (what question this task answers)**
2. **Boundaries (what to ignore)**
3. **Deliverables**
4. **Evidence posture**
   - What counts as “good evidence” for this task?
   - What sources are likely to be misleading?
5. **Contradiction protocol**
   - If you find conflicting claims, you must:
     - state both
     - state implied assumptions
     - search at least once more targeting the contradiction
6. **Try-to-falsify procedure**
   - Not a list of boxes; it is a mini-method:
     1. State the strongest recommendation/hypothesis.
     2. State the null/negation (“this won’t generalize / fails under X”).
     3. Actively look for counterexamples or failure reports.
     4. If none found, list plausible failure modes anyway.
     5. Propose a discriminating probe (small experiment) that would force revision.
7. **Output contract**
   - Prefer JSON registers (`SOURCES.json`, `CLAIMS.json`)
   - If the runner cannot output JSON, allow markdown tables + narrative.
8. **Stop rules**
   - Limit searches
   - Record deferred queries instead of infinite searching

**Why:** This structure prevents “summary dumps” and produces artifacts that can be merged without losing uncertainty.

### 6.1 What “try to falsify” looks like (concrete examples)

These examples are here because “try to falsify” is easy to misinterpret as performative ritual.

**Example A: Policy recommendation**
- Hypothesis: “Use worktrees for parallel work.”
- Null: “Worktrees increase entropy for small changes and slow integration.”
- Counterexample search: find incidents where worktrees created orphaned dirs, duplicated deps, and merge confusion.
- Probe: adopt a conditional policy for 1 week: “worktrees only for tasks expected > 1 day”; measure (a) cycle time, (b) lost-work incidents, (c) unmerged branches.
- If null supported: refine to conditional worktree policy rather than blanket.

**Example B: Model default**
- Hypothesis: “Default research workers to `gpt-5.2` at reasoning `high`.”
- Null: “`medium` yields comparable research quality at lower cost; `high` is waste.”
- Probe: run the same task twice (medium vs high). Compare:
  - contradiction detection rate
  - number of follow-up fix tasks needed
  - token usage and elapsed time

**Example C: Structure vs nuance**
- Hypothesis: “Claims register is enough to capture results.”
- Null: “Forcing everything into claims strips crucial nuance and produces brittle decisions.”
- Probe: ask a producer to output both claims and a residuals section; see what would have been lost.

**Why:** Without examples, agents will often write “falsification: none” and stop, which is exactly the failure we’re trying to prevent.

### 6.2 Iterative task creation is allowed (but must be logged)

**Instruction:** It is valid to start with a small task set, run them, then create additional tasks to resolve contradictions or fill coverage gaps. When doing this, the supervisor must:
1. Append a `task_generation` event to `LOG.jsonl` with the reason.
2. Write new task files under `10_TASKS/`.
3. Update `STATE.json` task list.

**Why:** One-shot decomposition fails under uncertainty. We want an explicit, audited loop rather than uncontrolled scope creep.

---

## 7) Producer Output Contract (`20_WORK/…`)

Worker directory:
`20_WORK/<task_id>/<producer_id>/`

Required files:
1. `PROVENANCE.json`
2. `REPORT.md`
3. `SOURCES.json` (array; may be empty)
4. `CLAIMS.json` (array; may be empty)
5. `RESIDUALS.md` (must exist even if “none”)

### 7.1 PROVENANCE.json schema (v1)
Required keys:
- `producer_id`
- `runner`
- `model` (string; empty allowed)
- `reasoning_effort` (string; empty allowed)
- `started_at`, `finished_at` (ISO8601 or empty)
- `elapsed_seconds` (number or null)
- `status` (`ok|partial|failed|timeout`)
- `token_usage`:
  - `input`, `cached_input`, `output`, `reasoning`, `total` (numbers or null)
- `exceptions` (list of `{what,why,impact}`)
- `notes` (string)

**Why:** Without provenance you can’t update priors (what works) or debug why outcomes differ.

## 7.2 Registers (`SOURCES.json`, `CLAIMS.json`) — schemas and rationale

The registers are not the whole research output. They are a structured *index* that supports:
- synthesis across runners
- longitudinal comparison across runs
- easier contradiction tracking

Anything that does not fit the schemas should go into `RESIDUALS.md` and `REPORT.md`.

### 7.2.1 `SOURCES.json` schema (v1)
Each source object:
```json
{
  "source_id": "S-0001",
  "title": "Source title",
  "author": "Name or org",
  "published_at": "YYYY-MM-DD or empty",
  "url": "https://...",
  "type": "official|maintainer|practitioner|community|paper|repo|other",
  "role": "ground_truth|implementation|pattern|counterexample|failure_mode|benchmark|historical_context|other",
  "format": "docs|repo|paper|blog|talk|video|issue|postmortem|thread|other",
  "credibility": {
    "authority": 0,
    "recency": 0,
    "evidence": 0,
    "relevance": 0,
    "total": 0,
    "justification": "1-2 sentences"
  },
  "key_takeaways": ["..."],
  "limitations": ["..."]
}
```

**Why these fields exist:**
- `role` prevents synthesis from treating all sources as interchangeable. A postmortem is not the same as official docs.
- `credibility` makes weighting traceable. It does not magically “decide truth”; it exposes judgment and assumptions.

### 7.2.2 `CLAIMS.json` schema (v1)
Each claim object:
```json
{
  "claim_id": "C-0001",
  "area": "worktrees|pr_workflow|quality_gates|tdd_and_alternatives|observability|self_improvement|min_human_intervention|other",
  "claim": "A specific statement (falsifiable where helpful; otherwise probe-driven).",
  "recommendation": "What to do.",
  "mechanism": "Why this would work; what is doing the work.",
  "assumptions": ["Assumption A", "Assumption B"],
  "probes": [
    {
      "test": "A discriminating probe/experiment.",
      "expected_if_true": "What you expect if the claim holds.",
      "what_if_false": "What you do if it fails."
    }
  ],
  "alternatives": [
    {
      "option": "Alternative approach.",
      "when_better": "Conditions that make it better."
    }
  ],
  "conflicts_with": ["C-0012"],
  "evidence_sources": ["S-0007", "S-0011"],
  "notes": ""
}
```

**Why “probes” instead of mandatory falsification fields:**
Some recommendations are strategic and context-dependent. Probes are the operational way to “test” them without pretending everything is cleanly falsifiable.

---

## 8) Merge/Synthesis (`30_MERGE/`) — rules, not vibes

Required outputs:
1. `REPORT.md` (final narrative)
2. `SOURCES.json` (deduped)
3. `CLAIMS.json` (clustered; not destructive)
4. `CONFLICTS.md` (explicit)
5. `ASSUMPTIONS_AND_PROBES.md`
6. `RESIDUALS.md` (merged; preserved)
7. `RECOMMENDATIONS.md` (actionable + alternatives + conditions)

### 8.1 Merge must preserve conflicts
**Instruction:** If multiple producers disagree on a recommendation, the merge must:
- keep both claims
- record the conflict link
- annotate the implied context differences

**Why:** This avoids false consensus and makes it possible to choose policies later based on conditions.

### 8.2 Merge must be more than concatenation
**Instruction:** The merger must explicitly label:
- **Agreements** (same rec/assumptions)
- **Conflicts** (incompatible recommendations without context split)
- **Context splits** (both can be true under different assumptions)
- **Composable recommendations** (can be combined safely)

**Why:** Concatenation produces a big file without increasing decision clarity. Labeling these categories is what makes synthesis actionable.

---

## 9) Codex Automation (parallel workers)

### 9.1 How we achieve parallelism in Codex
Codex does not give “subagent contexts” inside a single session. Parallelism is achieved by spawning multiple independent `codex exec` processes.

**Why:** Separate processes ensure separate contexts, clean logs, and no accidental cross-contamination of instruction state.

### 9.2 Codex runner requirements
The supervisor must use:
- `codex exec --json` to capture structured telemetry
- `--output-last-message` to capture the final assistant output for debugging

Observed telemetry includes a `token_count` event (with totals), which we will parse and store in provenance.

**Why:** Token estimates are too weak to optimize. We need real token counts where possible.

### 9.3 Default model settings
Default:
- `gpt-5.2` + reasoning `high`

Escalation policy (v1):
- escalate to `xhigh` only when validation flags unresolved contradictions or coverage gaps

**Why:** Defaulting to `xhigh` is expensive and encourages unbounded runs. Escalation should be targeted.

### 9.4 Supervisor monitoring (what “monitoring” means operationally)
**Instruction:** The supervisor must record, per worker process:
- spawn time
- last-seen event timestamp (heartbeat)
- elapsed time
- exit code / termination reason
- token usage totals (if available)
- the worker’s final message (for quick debugging)

If a worker produces no new events for N minutes (default N=5):
- supervisor writes `stalled_worker` event to `LOG.jsonl`
- supervisor continues waiting until timeout unless configured to “fail fast”

**Why:** Without attempt-level traces, “it took too long / it failed” is not diagnosable. Monitoring is what makes the system improvable.

---

## 10) CLI Surface (exact commands to implement)

Implement a single CLI entrypoint: `ar`

Commands:
1. `ar run scaffold ...`
2. `ar run spawn-codex ...`
3. `ar run import ...`
4. `ar run merge ...`
5. `ar run validate ...`
6. `ar run status ...`

Each command must:
- accept `--run-dir` explicitly (no guessing)
- support `--dry-run` where it makes sense
- write to `LOG.jsonl`

**Why:** This keeps operations composable and supports partial/iterative runs.

## 10.1 Runner-specific constraints (avoid bad assumptions)

Different runners have different output affordances. The system must not assume capabilities that don’t exist.

### Claude Desktop (Research mode)
Typical behavior: returns one markdown research report with citations.

Policy:
- Expect `REPORT.md` as the primary artifact.
- Ask for JSON registers only as *optional* (if the UI allows).
- Always accept a table fallback.

**Why:** If we require multiple files/JSON unconditionally, we’ll get fragile partial outputs and lose nuance.

### Claude Cowork
Cowork can delegate to subagents and may write multiple artifacts.

Policy:
- Instruct Cowork to act as a **research orchestrator**.
- Require per-subagent outputs + a merge procedure (Cowork performs its own internal synthesis).

**Why:** Delegation is Cowork’s advantage: it reduces context bloat and improves breadth, but only if the orchestration protocol is explicit.

### Gemini Deep Research (chat)
Typical behavior: report-first output. Register output (JSON) may be inconsistent.

Policy:
- Report-first; registers optional but preferred.
- If registers are not valid JSON, require stable IDs in tables so they can be converted later.

**Why:** Over-constraining output format can cause the model to comply poorly and drop important deliberation.

### Gemini CLI (later automation)
V1: manual import only.

Policy:
- Treat as “chat runner” until we verify CLI guarantees (files, skills, connectors).

**Why:** Don’t assume tool affordances we haven’t empirically verified.

### Codex
Tool-capable runner; supports `codex exec --json` telemetry.

Policy:
- Use Codex for automated parallel workers first.
- Use provenance + token telemetry to improve model policies over time.

**Why:** Codex is the easiest place to add rigorous observability and automation without speculative integration assumptions.

---

## 11) Git Hygiene (policy to avoid entropy)

### 11.1 Small commits
Make commits in small, reviewable units:
- doc contract
- scaffold script
- runner script
- merge script
- validate script

**Why:** Smaller diffs are easier to verify, and failures are easier to bisect.

### 11.2 Worktrees and branches
Policy:
- One worktree per branch when doing parallel feature work.
- Merge via PR-like review even locally (self-review is fine, but must be explicit).

**Why:** Prevents “mystery directory” confusion and makes integration deliberate.

---

## 12) Testing Strategy (TDD where it matters)

### What to test first (highest leverage)
1. Run scaffold produces correct structure.
2. Merge preserves conflicts (doesn’t erase disagreements).
3. Validate catches missing residuals/provenance.
4. Codex events parsing extracts token usage.

**Why:** These are the core failure modes in orchestration systems.

### What not to over-test in v1
- Deep fuzzy clustering correctness (start deterministic + simple; improve later)

**Why:** Premature sophistication tends to become a time sink without real-world data.

---

## 13) Execution Checklist (for a less capable agent)

### Step 1: repo initialization
1. Create repo directory and `git init`.
2. Add `.gitignore`.
3. Add this plan under `docs/IMPLEMENTATION_PLAN.md`.
4. Commit: `docs: add implementation plan`

Expected result:
- `git status` clean.

### Step 2: write run bundle spec (docs)
1. Create `docs/RUN_BUNDLE_SPEC.md`:
   - copy the contract sections (5–8) into a formal spec
2. Commit.

### Step 3: implement CLI skeleton
1. Add python package with `ar` console script.
2. Implement no-op commands that only print help.
3. Add tests verifying CLI help works.
4. Commit.

### Step 4: implement scaffold
1. Implement `ar run scaffold`.
2. Add unit tests for required files/dirs.
3. Commit.

### Step 5: implement import
1. Implement `ar run import --runner ... --report-path ...`.
2. Tests: creates producer dir + provenance + copies report.
3. Commit.

### Step 6: implement merge + validate
1. Merge: dedupe sources, cluster claims, preserve conflicts, produce merge artifacts.
2. Validate: ensure required artifacts exist and conflicts are not silently erased.
3. Tests.
4. Commit.

### Step 7: implement codex spawning
1. Implement `ar run spawn-codex` with worker pool, timeouts, event capture.
2. Tests with fixture `EVENTS.jsonl`.
3. Commit.

---

## 14) Known Pitfalls and Guardrails

1. **Over-structuring**: claim schema becomes a straitjacket.
   - Guardrail: `RESIDUALS.md` required everywhere.
2. **Conflict erasure**: synthesis “resolves” by averaging.
   - Guardrail: `CONFLICTS.md` required if multiple producers.
3. **Run directory races**: workers clobber each other.
   - Guardrail: single-writer `STATE.json`, per-producer dirs.
4. **Model cost runaway**: xhigh everywhere by default.
   - Guardrail: explicit default `high`, escalate only with recorded reason.

---

## 15) Open Questions (explicit, not hidden)

These are deferred v2 decisions:
1. Automatic integration with Claude/Gemini CLIs (beyond manual import).
2. More advanced clustering + semantic dedupe.
3. Cost estimation with pricing tables (requires maintained pricing config).
4. Automated “research question decomposition” (task generation) vs user-authored tasks.

**Why:** Declaring open questions prevents accidental partial implementations from being treated as complete.
