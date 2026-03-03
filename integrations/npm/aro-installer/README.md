# `aro-installer`

Minimal installer/config generator for:
- Codex skills (`~/.codex/skills/...`)
- MCP client config (Claude Code `.mcp.json` / `~/.claude.json`, Gemini CLI `.gemini/settings.json` / `~/.gemini/settings.json`)

## Usage

From this repo:

```bash
cd integrations/npm/aro-installer
node bin/aro.js --help
```

Install the Codex skill:

```bash
node bin/aro.js install codex-skill
```

Initialize Claude Code MCP config (project scope, in the current directory):

```bash
node bin/aro.js init claude-code --scope project --runs-root ~/.ar/runs --mode both
```

Initialize Gemini CLI MCP config (user scope):

```bash
node bin/aro.js init gemini-cli --scope user --runs-root ~/.ar/runs --mode ro
```

Notes:
- This tool writes config files but does **not** install the Python package. Ensure the configured `command` resolves to a Python environment where `agentic-research-orchestrator` is installed.

