# Claude Code (MCP) integration

This repo exposes an MCP server over stdio:

- Read-only: `python3 -m ar mcp serve --allow-run-dir-prefix <RUNS_ROOT>`
- Write-enabled: `python3 -m ar mcp serve --write-enabled --allow-run-dir-prefix <RUNS_ROOT>`

## Option A: Project config (`.mcp.json`)

Create a `.mcp.json` file in your project root:

```json
{
  "mcpServers": {
    "aro_ro": {
      "command": "python3",
      "args": ["-m", "ar", "mcp", "serve", "--allow-run-dir-prefix", "/ABS/PATH/TO/ar-runs"]
    },
    "aro_rw": {
      "command": "python3",
      "args": ["-m", "ar", "mcp", "serve", "--write-enabled", "--allow-run-dir-prefix", "/ABS/PATH/TO/ar-runs"]
    }
  }
}
```

## Option B: Install via CLI (`claude mcp add-json`)

Add a read-only server:

```bash
claude mcp add-json aro_ro '{"command":"python3","args":["-m","ar","mcp","serve","--allow-run-dir-prefix","/ABS/PATH/TO/ar-runs"]}'
```

Add a write-enabled server:

```bash
claude mcp add-json aro_rw '{"command":"python3","args":["-m","ar","mcp","serve","--write-enabled","--allow-run-dir-prefix","/ABS/PATH/TO/ar-runs"]}'
```

Notes:
- Use `--scope user|project|local` if you want to control where the server is stored.
- Prefer starting with `aro_ro` until you’re confident in the run-dir confinement policy.

## Using MCP prompts

This MCP server exposes a prompt named `orchestrator_prompt`.

In Claude Code, MCP prompts appear as slash commands:

```text
/mcp__aro_ro__orchestrator_prompt run_dir="/ABS/PATH/TO/run" runner="claude_code" profile="guided"
```

Arguments:
- `run_dir` (required): absolute path to the run bundle directory
- `runner` (optional): runner id for the orchestrator prompt template (e.g., `claude_code`, `gemini_cli`)
- `profile` (optional): `normal` or `guided`

