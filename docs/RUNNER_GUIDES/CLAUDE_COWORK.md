# Runner Guide: Claude Cowork (v1)

## Intended operating mode
Cowork should act as a **research orchestrator**:
- delegate subtasks to subagents
- keep subagents scoped (no recursion)
- require structured outputs per subagent
- perform a deterministic merge that preserves conflicts

## Why this matters
Cowork’s advantage is delegation (parallelism + reduced context bloat). If it behaves like a single writer, it loses its comparative advantage.

## Output contract expectation
Even if Cowork can write files, don’t assume it will perfectly follow multi-file contracts without explicit instructions.

Require at minimum:
- a report
- a sources register (JSON preferred, table fallback)
- a claims register (JSON preferred, table fallback)
- a residuals section

