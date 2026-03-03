# Agentic Research Orchestrator (ARO)

Repo-agnostic research orchestration using **compaction-safe run bundles** on disk.

Two ways to drive it:
- **Deterministic CLI** (`python -m ar ...` / `ar ...`): scaffold/validate/status/merge run bundles.
- **MCP server** (`python -m ar mcp serve ...`): Claude Code / Gemini CLI / etc. act as the “brain” while ARO is the deterministic “hands”.

## Quick start

### 1) Install (editable)

```bash
python3 -m pip install -e .
python3 -m ar --help
```

### 2) Scaffold a run bundle

```bash
RUN_DIR=$(python3 -m ar run scaffold --runs-root /tmp/ar-runs --slug demo --goal "Demo research run")
echo "$RUN_DIR"
```

### 3) Optional: install the Codex skill + configure MCP clients

If you have Node 18+:

```bash
npx --yes aro-installer setup
```

## Docs

- Run bundle contract: `docs/RUN_BUNDLE_SPEC.md`
- CLI surface: `docs/CLI_SPEC.md`
- Design rationale / guardrails: `docs/IMPLEMENTATION_PLAN.md`
- Integrations (Codex skill + MCP): `docs/INTEGRATIONS.md`

