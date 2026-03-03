# Integrations (Codex skills + MCP clients)

This repo supports two integration modes:

1. **Direct CLI** (`ar ...`): you run the CLI and it mutates/validates run bundles deterministically.
2. **MCP server** (`ar mcp serve`): an external orchestrator (Claude Code / Gemini CLI / etc.) drives the same deterministic operations via MCP tools and prompts.

---

## Quick start (interactive)

From the repo root (TTY required):

```bash
npx --yes ./integrations/npm/aro-installer setup
```

Once `aro-installer` is published to npm, you can also run:

```bash
npx --yes aro-installer setup
```

This can install the Codex skill and write MCP config for Claude Code and/or Gemini CLI.

---

## Codex skill

Skill source (in this repo):
- `integrations/codex/skills/agentic-research-orchestrator`

Install into Codex (writes to `~/.codex/skills` by default):

```bash
cd /path/to/agentic-research-orchestrator
npx --yes ./integrations/npm/aro-installer install codex-skill
```

Restart Codex after installing.

---

## Claude Code (project MCP)

Create `.mcp.json` in your project root with an `mcpServers` entry that runs:

```bash
python3 -m ar mcp serve --allow-run-dir-prefix ~/.ar/runs
```

Or generate/update config via the installer:

```bash
npx --yes ./integrations/npm/aro-installer init claude-code --scope project --runs-root ~/.ar/runs --mode both
```

Notes:
- `--mode both` installs two servers: `<base>_ro` and `<base>_rw` (write-enabled).
- `--scope both` writes both user + project config in one go.
- The server also exposes an MCP prompt named `orchestrator_prompt` (see `integrations/codex/skills/agentic-research-orchestrator/references/claude-code.md`).

---

## Gemini CLI (project MCP)

Gemini CLI reads MCP servers from `.gemini/settings.json` (project) or `~/.gemini/settings.json` (user).

Generate/update project config via the installer:

```bash
npx --yes ./integrations/npm/aro-installer init gemini-cli --scope project --runs-root ~/.ar/runs --mode ro
```

The MCP prompt name is the same (`orchestrator_prompt`) and appears as a slash command in Gemini CLI (see `integrations/codex/skills/agentic-research-orchestrator/references/gemini-cli.md`).
