# Gemini CLI (MCP) integration

Gemini CLI supports MCP servers configured at either:
- User scope: `~/.gemini/settings.json`
- Project scope: `.gemini/settings.json`

This repo exposes an MCP server over stdio:

- Read-only: `python3 -m ar mcp serve --allow-run-dir-prefix <RUNS_ROOT>`
- Write-enabled: `python3 -m ar mcp serve --write-enabled --allow-run-dir-prefix <RUNS_ROOT>`

## Option A: Edit settings (`mcpServers`)

Add one or both servers:

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

## Option B: Install via CLI (`gemini mcp add`)

Read-only:

```bash
gemini mcp add --name aro_ro --command python3 --args "-m ar mcp serve --allow-run-dir-prefix /ABS/PATH/TO/ar-runs"
```

Write-enabled:

```bash
gemini mcp add --name aro_rw --command python3 --args "-m ar mcp serve --write-enabled --allow-run-dir-prefix /ABS/PATH/TO/ar-runs"
```

Notes:
- Use `--scope user|project` if you want to control where Gemini stores the server.
- Prefer starting with `aro_ro` until you’re confident in the run-dir confinement policy.

## Using MCP prompts

This MCP server exposes a prompt named `orchestrator_prompt`.

In Gemini CLI, MCP prompts show up as slash commands (same name as the prompt):

```text
/orchestrator_prompt --run_dir="/ABS/PATH/TO/run" --runner="gemini_cli" --profile="guided"
```

