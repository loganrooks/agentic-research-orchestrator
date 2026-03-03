# Skills + MCP installer plan (v1)

This plan covers “skills properly” for this repo:
- a Codex skill (so Codex can operate `ar` workflows consistently)
- an MCP-friendly “prompt surface” (so orchestrators can fetch a ready-to-use orchestrator prompt)
- an installer/config generator (so Claude Code / Gemini CLI can be configured at *project* or *user* scope)

It is written compaction-safe: it captures the research assumptions, decisions, and quality gates used during implementation.

---

## Goals

1. **Codex skill**: provide a lean skill that teaches the `ar` workflow + MCP usage.
2. **MCP prompts**: expose at least one MCP prompt (`orchestrator_prompt`) so orchestrators can fetch a copy/paste plan-emitting prompt without hunting docs.
3. **Project vs user install**: provide a deterministic way to configure MCP servers at:
   - project scope (checked into a repo)
   - user scope (global defaults)
4. **Low-friction**: a minimal installer that runs with stock Node (no deps).
5. **Safety**: keep defaults conservative; require explicit confinement (`--allow-run-dir-prefix`); clearly separate read-only vs write-enabled servers.

## Non-goals (for v1)

- Automatically install the Python package (the installer assumes the configured `command` points at a Python env where `agentic-research-orchestrator` is installed).
- Provide a Claude Desktop extension bundle (`.mcpb`) (candidate follow-up).
- Auto-detect “correct” Python executable across platforms (we default to `python3` and allow override).

---

## Grounding research (current best practices / canonical locations)

### Claude Code

Key findings:
- MCP server definitions live in:
  - project: `.mcp.json`
  - user: `~/.claude.json`
- Claude Code supports installing MCP servers via `claude mcp add-json ...` and supports MCP prompts as slash commands.

Primary reference:
- [Claude Code settings and MCP](https://docs.claude.com/en/docs/claude-code/settings)

### Gemini CLI

Key findings:
- MCP server definitions live in:
  - project: `.gemini/settings.json`
  - user: `~/.gemini/settings.json`
- Gemini CLI supports `gemini mcp add ...` and exposes MCP prompts as slash commands.

Primary references:
- [Gemini CLI MCP servers (Firebase docs)](https://firebase.google.com/docs/gemini-cli/tools/mcp-server)
- [Gemini CLI MCP server docs](https://google-gemini.github.io/gemini-cli/docs/tools/mcp-server.html)

---

## Implementation plan (what to build)

1. **Codex skill (source-controlled)**
   - Add `integrations/codex/skills/agentic-research-orchestrator/` with:
     - `SKILL.md` (lean workflow + MCP entrypoints)
     - `references/` for Claude Code + Gemini CLI config snippets and prompt invocation
   - Validate with the skill validator (`quick_validate.py`).

2. **MCP prompt surface**
   - Ensure MCP server advertises `capabilities.prompts` and implements:
     - `prompts/list`
     - `prompts/get`
   - Provide prompt `orchestrator_prompt` that returns the same content as `ar run export-orchestrator-prompt` (but as MCP prompt messages).

3. **Installer/config generator (Node, no deps)**
   - Add `integrations/npm/aro-installer/` with a small CLI:
     - `install codex-skill` → copy the skill into `~/.codex/skills` (or `$CODEX_HOME/skills`)
     - `init claude-code` → update `.mcp.json` (project) or `~/.claude.json` (user)
     - `init gemini-cli` → update `.gemini/settings.json` (project) or `~/.gemini/settings.json` (user)
   - Support safe “modes”:
     - `ro`: install `<base>_ro`
     - `rw`: install `<base>_rw` (write-enabled)
     - `both`: install both
   - Default confinement: `--runs-root ~/.ar/runs` (overrideable).

4. **Docs**
   - Update `docs/CLI_SPEC.md` to include MCP prompt support.
   - Add `docs/INTEGRATIONS.md` with:
     - Codex skill install command
     - MCP init commands for Claude Code + Gemini CLI

---

## Decision log (why these choices)

- **Node installer, no dependencies**: minimizes installation friction and avoids adding a JS toolchain to the Python core.
- **Don’t auto-install Python**: package install semantics vary (pipx/uv/venv/system python). For v1, config generation is still valuable without guessing the environment.
- **Read-only vs write-enabled split**: encourages least-privilege usage and makes it obvious when an orchestrator can mutate a run bundle.
- **Require `--allow-run-dir-prefix`**: prevents a misconfigured orchestrator from operating on arbitrary filesystem paths.
- **Keep the skill lean**: the skill should teach the *operational loop* and point to references, not duplicate the full specs.

---

## Quality gates

1. **Skill validity**: run `quick_validate.py` on the skill folder.
2. **Repo tests**: `pytest -q` must pass.
3. **Installer sanity** (manual):
   - Run `aro init ...` against a temp directory and inspect the generated JSON.
   - Run `aro install codex-skill --dest <temp>` and confirm expected files copied.

---

## Follow-ups (optional)

- Publish `aro-installer` as a real npm package (remove `"private": true`, add metadata, add a `files` allowlist).
- Add a `pipx`-first installation recipe (or `uv tool install`) so `ar` is reliably on PATH for MCP clients.
- Package a Claude Desktop extension (`.mcpb`) that bundles config + a server command in a UX-friendly way.

