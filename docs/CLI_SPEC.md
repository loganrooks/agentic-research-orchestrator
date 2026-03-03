# CLI Specification (v1)

This specifies the **exact CLI surface** to implement. It is intentionally explicit to prevent “CLI drift”.

CLI name: `ar`

---

## Global Conventions (and why)

1. **No implicit run discovery**
   - Every command that operates on an existing run requires `--run-dir`.
   - Why: guessing the “latest run” is convenient but dangerous and causes accidental corruption.

2. **Logs are written for real runs**
   - All non-`--dry-run` commands append to `LOG.jsonl` (if `--run-dir` is provided).
   - Why: debugging requires traces; silent runs create mystery failures.

3. **Dry-run where it matters**
   - Use `--dry-run` for commands that would create/overwrite artifacts.
   - Why: lets you inspect intent before mutation.

---

## `ar mcp serve`

Purpose:
- Serve a minimal MCP (Model Context Protocol) tool surface over stdio so an external orchestrator (e.g., Claude Code) can operate run bundles without copy/paste.

Inputs:
- `--write-enabled` (optional; default false)
- `--allow-run-dir-prefix <path>` (repeatable; optional but recommended)
- `--max-calls-per-minute <int>` (optional; default 60)

Behavior:
- Stdio JSON-RPC server with support for:
  - `initialize`
  - `tools/list`
  - `tools/call`
  - `prompts/list`
  - `prompts/get`
- Every tool call requires an explicit `run_dir` argument.
- Write-capable tools are rejected unless `--write-enabled` is set.
- Tool calls are appended to `12_SUPERVISOR/MCP_LOG.jsonl` for auditability.
- Write tools enforce basic symlink/escape checks on key run bundle paths.

Prompts:
- The server exposes an `orchestrator_prompt` MCP prompt that returns a runner-specific copy/paste prompt for producing an `OrchestratorPlan` JSON.
- Prompt args:
  - `run_dir` (required)
  - `runner` (optional; default `claude_code`)
  - `profile` (optional; default `guided`)

Exit codes:
- `0` clean shutdown / EOF

---

## `ar run scaffold`

Purpose:
- Create a new run directory and minimal required files.

Required inputs:
- `--slug <slug>` OR `--goal <text>` (if goal is provided and slug absent, slug is derived).

Optional inputs:
- `--runs-root <path>` (default `AR_RUNS_ROOT` or `~/.ar/runs`)
- `--targets <path>` (repeatable)
- Runner plan:
  - `--required-runner <runner>` (repeatable; default: `codex`)
  - `--optional-runner <runner>` (repeatable; default: `claude_desktop`, `cowork`, `gemini_deep_research`, `gemini_cli`)
- Codex defaults overrides:
  - `--codex-model <model>` (default `gpt-5.2`)
  - `--codex-reasoning <low|medium|high|xhigh>` (default `high`)
  - `--codex-sandbox <read-only|workspace-write|danger-full-access>` (default `read-only`)
  - `--codex-timeout-seconds <int>` (default `1800`)
  - `--codex-max-workers <int>` (default `3`)
- `--dry-run`
- `--rebuild` (overwrite an existing run dir if present; default false)

Outputs:
- Run directory with required structure:
  - `00_BRIEF.md`, `01_CONFIG.json`, `STATE.json`, `LOG.jsonl`, `10_TASKS/`, `20_WORK/`, `30_MERGE/`

Notes:
- Optional runners are treated as “depth/breadth bonuses”. The system must remain usable if they never produce outputs.

Exit codes:
- `0` success
- `2` invalid args
- `3` path exists and `--rebuild` not set

---

## `ar run export-prompts`

Purpose:
- Produce runner-specific, copy/paste-ready prompts from canonical task files.

Inputs:
- `--run-dir <path>` (required)
- `--runner <runner>` (required; one at a time)
- `--out-dir <path>` (optional; default: `<run>/11_EXPORT/<runner>/`)

Behavior:
- Reads `10_TASKS/*.md`
- Wraps them in runner-specific preambles/templates (from `docs/RUNNER_GUIDES/*`)
- Writes one `.md` file per task under output dir

Why:
- Different runners have different output affordances. Exported prompts reduce “format mismatch” errors.

---

## `ar run export-orchestrator-prompt`

Purpose:
- Produce a runner-specific copy/paste prompt for an *orchestrator brain* (Codex/Claude/Gemini/etc) to emit an `OrchestratorPlan` JSON.

Inputs:
- `--run-dir <path>` (required)
- `--runner <runner>` (required)
- `--profile <normal|guided>` (optional; default `normal`)
- `--out-path <path>` (optional; default: `<run>/12_SUPERVISOR/PROMPTS/ORCHESTRATOR_PROMPT_<ts>__<runner>.md`)

Outputs:
- Writes a single prompt markdown file (for copy/paste) under `12_SUPERVISOR/PROMPTS/` by default.

Notes:
- Orchestrator prompts must request **JSON-only** output (no markdown fences), so the plan can be applied deterministically.

---

## `ar run apply-plan`

Purpose:
- Apply an `OrchestratorPlan` (JSON) to create canonical task files under `10_TASKS/` and register them in `STATE.json`.

Inputs:
- `--run-dir <path>` (required)
- `--plan-path <path|->` (required; `-` reads JSON from stdin)
- `--dry-run` (optional; validate/preview without writing)

Outputs:
- Writes a plan snapshot under `12_SUPERVISOR/PLANS/`
- Creates new `10_TASKS/T-XXXX__<slug>.md` files (create-only; no updates in v1)
- Appends a `task_generation` event to `LOG.jsonl`
- Updates `STATE.json.tasks` with new tasks as `pending`

Exit codes:
- `0` success (including idempotent re-apply)
- `2` invalid args / invalid plan / unsafe operation

---

## `ar run generate-tasks`

Purpose:
- Run a single Codex “supervisor” to emit an `OrchestratorPlan` JSON and apply it to create tasks.

Inputs:
- `--run-dir <path>` (required)
- `--model <model>` (optional; default from config)
- `--reasoning <effort>` (optional; default from config)
- `--profile <normal|guided>` (optional; default `normal`)
- `--sandbox <mode>` (optional; default from config)
- `--timeout-seconds <int>` (optional; default from config)
- `--dry-run` (optional; runs supervisor + validates plan, but does not create tasks or mutate `STATE.json`/`LOG.jsonl`)

Behavior:
- Exports a Codex orchestrator prompt into a supervisor session directory.
- Runs `codex exec --json` with explicit model + reasoning overrides.
- Captures supervisor artifacts (events, last message, stderr, provenance).
- Extracts the plan JSON and applies it via `ar run apply-plan`.

Outputs:
- Supervisor session artifacts under `12_SUPERVISOR/SESSIONS/...`
- Task files under `10_TASKS/` (unless `--dry-run`)
- Plan snapshot under `12_SUPERVISOR/PLANS/` (unless `--dry-run`)
- `LOG.jsonl` events:
  - `generate_tasks_started` / `generate_tasks_finished` (unless `--dry-run`)
  - `task_generation` (unless `--dry-run`)

Exit codes:
- `0` success
- `20` fatal (Codex missing/timeout, invalid plan output, apply failed)

---

## `ar run propose-followups`

Purpose:
- Propose *follow-up* tasks via a Codex supervisor, using existing merge artifacts as context.

Precondition:
- `ar run merge` has been run (requires `30_MERGE/REPORT.md` to exist).

Inputs:
- `--run-dir <path>` (required)
- `--model <model>` (optional; default from config)
- `--reasoning <effort>` (optional; default from config)
- `--profile <normal|guided>` (optional; default `guided`)
- `--sandbox <mode>` (optional; default from config)
- `--timeout-seconds <int>` (optional; default from config)
- `--dry-run` (optional; runs supervisor + validates plan, but does not create tasks or mutate `STATE.json`/`LOG.jsonl`)

Outputs:
- Supervisor session artifacts under `12_SUPERVISOR/SESSIONS/FOLLOWUPS_<ts>__codex/`
- Task files under `10_TASKS/` (unless `--dry-run`)
- Plan snapshot under `12_SUPERVISOR/PLANS/` (unless `--dry-run`)
- `LOG.jsonl` events:
  - `propose_followups_started` / `propose_followups_finished` (unless `--dry-run`)
  - `task_generation` with `source=propose-followups` (unless `--dry-run`)

Exit codes:
- `0` success
- `20` fatal (missing merge artifacts, Codex missing/timeout, invalid plan output, apply failed)

---

## `ar run spawn-codex`

Purpose:
- Spawn parallel Codex workers for tasks and capture telemetry.

Inputs:
- `--run-dir <path>` (required)
- `--task <T-XXXX>` (repeatable; default: all tasks)
- `--max-workers <int>` (default from config)
- `--timeout-seconds <int>` (default from config)
- `--model <model>` (default from config)
- `--reasoning <effort>` (default from config)
- `--sandbox <mode>` (default from config)
- `--resume` / `--no-resume` (default resume)
- `--fail-fast` (optional; default false)

Outputs (per producer):
- `20_WORK/<task>/codex:worker-XX/PROVENANCE.json`
- `REPORT.md` (from last message)
- `EVENTS.jsonl`
- `LAST_MESSAGE.txt`

Exit codes:
- `0` all requested tasks completed successfully
- `10` partial (some failed/timeouts)
- `20` fatal supervisor error (could not spawn/parse)

---

## `ar run import`

Purpose:
- Import a manual runner output into a producer directory.

Inputs:
- `--run-dir <path>` (required)
- `--task <T-XXXX>` (required)
- `--runner <runner>` (required)
- `--producer <id>` (optional; default `<runner>:manual-01`, with suffix if exists)
- `--report-path <path>` (optional; if absent, read report from stdin)
- `--sources-path <path>` (optional)
- `--claims-path <path>` (optional)
- `--residuals-path <path>` (optional)
- `--model <string>` (optional)
- `--reasoning <string>` (optional)

Behavior:
- Copies provided files into producer dir as canonical names.
- Creates `PROVENANCE.json`.
- Updates `STATE.json` to link producer to task.

Why:
- Manual runners won’t write to our folders directly; import normalizes their output.

---

## `ar run merge`

Purpose:
- Build `30_MERGE/` outputs deterministically from `20_WORK/`.

Inputs:
- `--run-dir <path>` (required)
- `--allow-missing-registers` (optional; default false)

Behavior:
- Dedup sources
- Cluster claims without deleting them
- Write conflicts, assumptions/probes, recommendations, residuals

Exit codes:
- `0` success
- `11` merge completed but conflicts unresolved (still success; recorded in conflicts)
- `21` fatal (missing required files)

---

## `ar run validate`

Purpose:
- Read-only validation that run artifacts are structurally sound and synthesis is non-destructive.

Inputs:
- `--run-dir <path>` (required)

Checks:
- required files present
- provenance present per producer
- residuals present
- if multiple producers: conflicts file present and non-empty when conflicts detected

Exit codes:
- `0` valid
- `30` invalid (structural errors listed)

---

## `ar run status`

Purpose:
- Print a concise status summary for a run.

Inputs:
- `--run-dir <path>`

Outputs:
- current step
- tasks and statuses
- producers per task
- last log events (tail)
