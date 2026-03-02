# Runner Guide: Codex (v1)

## What Codex is good for
- Automated parallel workers (`codex exec` processes)
- Deterministic file writing (run bundle artifacts)
- Real telemetry (`--json` events include token totals)

## Known constraints
- No “subagent contexts” inside a single run; parallelism is multi-process.

## Required flags for automation
- `--json` (capture events)
- `--output-last-message <path>` (capture final output)
- explicit model + reasoning overrides (do not rely on global config)

## Why explicit overrides matter
If user’s global Codex config defaults to expensive reasoning (e.g., `xhigh`), an automated supervisor that doesn’t override will silently burn cost.

## Sandbox guidance
Default automation should use `--sandbox read-only` unless the task explicitly needs writes.

Reason: research tasks can accidentally mutate repos otherwise.

