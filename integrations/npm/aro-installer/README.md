# `aro-installer`

Minimal installer/config generator for:
- Codex skills (`~/.codex/skills/...`)
- MCP client config (Claude Code `.mcp.json` / `~/.claude.json`, Gemini CLI `.gemini/settings.json` / `~/.gemini/settings.json`)

## Usage

From this repo (recommended via `npx` from the repo root):

```bash
cd /path/to/agentic-research-orchestrator
npx --yes ./integrations/npm/aro-installer --help
```

Interactive setup (TTY required):

```bash
npx --yes ./integrations/npm/aro-installer setup
```

Non-interactive: install the Codex skill:

```bash
npx --yes ./integrations/npm/aro-installer install codex-skill
```

Non-interactive: initialize Claude Code MCP config (project scope):

```bash
npx --yes ./integrations/npm/aro-installer init claude-code --scope project --runs-root ~/.ar/runs --mode both
```

Non-interactive: initialize Gemini CLI MCP config (user scope):

```bash
npx --yes ./integrations/npm/aro-installer init gemini-cli --scope user --runs-root ~/.ar/runs --mode ro
```

Notes:
- This tool writes config files but does **not** install the Python package. Ensure the configured `command` resolves to a Python environment where `agentic-research-orchestrator` is installed.
