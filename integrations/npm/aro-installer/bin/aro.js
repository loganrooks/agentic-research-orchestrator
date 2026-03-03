#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const readline = require("readline");

function die(message, code = 1) {
  process.stderr.write(String(message).trimEnd() + "\n");
  process.exit(code);
}

function expandHome(p) {
  const s = String(p || "").trim();
  if (s === "~") return os.homedir();
  if (s.startsWith("~/")) return path.join(os.homedir(), s.slice(2));
  return s;
}

function parseFlags(argv) {
  const positionals = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) {
      positionals.push(a);
      continue;
    }
    const eq = a.indexOf("=");
    if (eq !== -1) {
      const k = a.slice(2, eq).trim();
      const v = a.slice(eq + 1);
      flags[k] = v;
      continue;
    }
    const k = a.slice(2).trim();
    const next = argv[i + 1];
    if (next === undefined || next.startsWith("--")) {
      flags[k] = true;
      continue;
    }
    flags[k] = next;
    i++;
  }
  return { positionals, flags };
}

function printHelp() {
  const help = `
aro-installer

Usage:
  aro --help

  aro install codex-skill [--name <skill>] [--dest <skills-root>] [--force]

  aro init claude-code --scope <project|user|both> [--project-root <dir>] [--runs-root <dir>] [--python <cmd>] [--mode <ro|rw|both>] [--server-name <base>]
  aro init gemini-cli --scope <project|user|both> [--project-root <dir>] [--runs-root <dir>] [--python <cmd>] [--mode <ro|rw|both>] [--server-name <base>]

  aro setup   # interactive wizard (requires TTY)

Notes:
  - Default --runs-root is ~/.ar/runs
  - Default --python is python3
  - Mode:
      ro   => installs <base>_ro
      rw   => installs <base>_rw
      both => installs <base>_ro and <base>_rw
  - This writes MCP config files, but does not install the Python package.
`;
  process.stdout.write(help.trimStart());
  process.stdout.write("\n");
}

function defaultCodexSkillsRoot() {
  const codexHome = expandHome(process.env.CODEX_HOME || "");
  const base = codexHome ? codexHome : path.join(os.homedir(), ".codex");
  return path.join(base, "skills");
}

function readJsonIfExists(p) {
  if (!fs.existsSync(p)) return {};
  const raw = fs.readFileSync(p, "utf8");
  if (!raw.trim()) return {};
  try {
    const obj = JSON.parse(raw);
    if (obj && typeof obj === "object" && !Array.isArray(obj)) return obj;
    die(`Expected JSON object in ${p}`);
  } catch (e) {
    die(`Failed to parse JSON in ${p}: ${e.message}`);
  }
}

function writeJson(p, obj) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(obj, null, 2) + "\n", "utf8");
}

function ensureObjectField(obj, key, filePathForErrors) {
  if (obj[key] === undefined) obj[key] = {};
  if (!obj[key] || typeof obj[key] !== "object" || Array.isArray(obj[key])) {
    die(`Expected '${key}' to be an object in ${filePathForErrors}`);
  }
  return obj[key];
}

function makeAroServerDef({ pythonCmd, runsRootAbs, writeEnabled }) {
  const args = ["-m", "ar", "mcp", "serve"];
  if (writeEnabled) args.push("--write-enabled");
  args.push("--allow-run-dir-prefix", runsRootAbs);
  return { command: pythonCmd, args };
}

function addServersToConfig({ config, baseName, pythonCmd, runsRootAbs, mode }) {
  const mcpServers = ensureObjectField(config, "mcpServers", "<config>");
  if (mode === "ro" || mode === "both") {
    mcpServers[`${baseName}_ro`] = makeAroServerDef({ pythonCmd, runsRootAbs, writeEnabled: false });
  }
  if (mode === "rw" || mode === "both") {
    mcpServers[`${baseName}_rw`] = makeAroServerDef({ pythonCmd, runsRootAbs, writeEnabled: true });
  }
  return config;
}

function installCodexSkill({ skillName, destRoot, force }) {
  const srcSkill = path.join(__dirname, "..", "skills", skillName);
  if (!fs.existsSync(srcSkill)) die(`Skill not found in package: ${srcSkill}`);

  fs.mkdirSync(destRoot, { recursive: true });
  const destSkill = path.join(destRoot, skillName);
  if (fs.existsSync(destSkill)) {
    if (!force) die(`Destination exists: ${destSkill} (re-run with --force to overwrite)`);
    fs.rmSync(destSkill, { recursive: true, force: true });
  }
  fs.cpSync(srcSkill, destSkill, { recursive: true });
  return destSkill;
}

function initClient({ client, scope, projectRoot, runsRootAbs, pythonCmd, mode, baseName }) {
  if (!["project", "user", "both"].includes(scope)) die("Invalid scope");
  if (!["ro", "rw", "both"].includes(mode)) die("Invalid mode");

  const scopes = scope === "both" ? ["user", "project"] : [scope];
  const configPaths = [];

  for (const sc of scopes) {
    if (client === "claude-code") {
      configPaths.push(sc === "project" ? path.join(projectRoot, ".mcp.json") : path.join(os.homedir(), ".claude.json"));
      continue;
    }
    if (client === "gemini-cli") {
      configPaths.push(
        sc === "project" ? path.join(projectRoot, ".gemini", "settings.json") : path.join(os.homedir(), ".gemini", "settings.json"),
      );
      continue;
    }
    die(`Unknown client: ${client}`);
  }

  for (const configPath of configPaths) {
    const config = readJsonIfExists(configPath);
    if (config.mcpServers !== undefined) {
      ensureObjectField(config, "mcpServers", configPath);
    }
    addServersToConfig({ config, baseName, pythonCmd, runsRootAbs, mode });
    writeJson(configPath, config);
  }
  return configPaths;
}

function cmdInstall(argv) {
  const { positionals, flags } = parseFlags(argv);
  const sub = positionals[0];
  if (sub !== "codex-skill") die(`Unknown install target: ${sub || "<missing>"}`);

  const skillName = String(flags.name || "agentic-research-orchestrator").trim();
  const destRoot = expandHome(flags.dest || "") || defaultCodexSkillsRoot();
  const force = flags.force === true || String(flags.force || "").toLowerCase() === "true";

  const destSkill = installCodexSkill({ skillName, destRoot, force });
  process.stdout.write(`Installed Codex skill: ${destSkill}\n`);
  process.stdout.write("Restart Codex to pick up new skills.\n");
}

function cmdInit(argv) {
  const { positionals, flags } = parseFlags(argv);
  const client = positionals[0];
  if (!client) die("Missing client. Expected: claude-code | gemini-cli");

  const scope = String(flags.scope || "").trim() || "project";
  if (!["project", "user", "both"].includes(scope)) die("Invalid --scope. Expected: project | user | both");

  const projectRoot = path.resolve(expandHome(flags["project-root"] || "") || process.cwd());
  const runsRootAbs = path.resolve(expandHome(flags["runs-root"] || "") || path.join(os.homedir(), ".ar", "runs"));
  const pythonCmd = String(flags.python || "").trim() || "python3";
  const mode = String(flags.mode || "").trim() || "ro";
  const baseName = String(flags["server-name"] || "").trim() || "aro";

  if (!["ro", "rw", "both"].includes(mode)) die("Invalid --mode. Expected: ro | rw | both");

  const configPaths = initClient({ client, scope, projectRoot, runsRootAbs, pythonCmd, mode, baseName });
  for (const configPath of configPaths) {
    process.stdout.write(`Updated ${client} MCP config: ${configPath}\n`);
  }
  process.stdout.write(`Runs confinement: ${runsRootAbs}\n`);
}

function _requireTty() {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    die("This command requires a TTY. Use the non-interactive `init` / `install` commands instead.");
  }
}

function _yesNoDefault(s, defVal) {
  const t = String(s || "").trim().toLowerCase();
  if (!t) return defVal;
  if (["y", "yes", "true", "1"].includes(t)) return true;
  if (["n", "no", "false", "0"].includes(t)) return false;
  return defVal;
}

function _rl() {
  return readline.createInterface({ input: process.stdin, output: process.stdout });
}

async function _ask(question, defVal = "") {
  const rl = _rl();
  const q = defVal ? `${question} (${defVal}): ` : `${question}: `;
  return await new Promise((resolve) => {
    rl.question(q, (ans) => {
      rl.close();
      const out = String(ans || "").trim();
      resolve(out || defVal);
    });
  });
}

async function _askYesNo(question, defVal) {
  const suffix = defVal ? " [Y/n]" : " [y/N]";
  const ans = await _ask(question + suffix, "");
  return _yesNoDefault(ans, defVal);
}

async function cmdSetup() {
  _requireTty();

  process.stdout.write("aro-installer setup (interactive)\n\n");

  const installSkill = await _askYesNo("Install Codex skill to ~/.codex/skills?", true);
  const doClaude = await _askYesNo("Configure Claude Code MCP?", true);
  const doGemini = await _askYesNo("Configure Gemini CLI MCP?", true);

  const scope = (await _ask("Install scope for MCP configs (project|user|both)", "project")).trim() || "project";
  if (!["project", "user", "both"].includes(scope)) die("Invalid scope; expected project|user|both");

  const projectRoot = path.resolve(expandHome(await _ask("Project root (used for project scope)", process.cwd())));
  const runsRootAbs = path.resolve(expandHome(await _ask("Runs root (for --allow-run-dir-prefix)", path.join(os.homedir(), ".ar", "runs"))));
  const pythonCmd = (await _ask("Python command/path (must have agentic-research-orchestrator installed)", "python3")).trim() || "python3";
  const mode = (await _ask("MCP server mode (ro|rw|both)", "ro")).trim() || "ro";
  if (!["ro", "rw", "both"].includes(mode)) die("Invalid mode; expected ro|rw|both");
  const baseName = (await _ask("Server name base (prefix for *_ro/*_rw)", "aro")).trim() || "aro";

  if (installSkill) {
    const destRoot = defaultCodexSkillsRoot();
    const existing = path.join(destRoot, "agentic-research-orchestrator");
    const force = fs.existsSync(existing)
      ? await _askYesNo(`Codex skill already exists at ${existing}. Overwrite?`, false)
      : false;
    if (!fs.existsSync(existing) || force) {
      const destSkill = installCodexSkill({ skillName: "agentic-research-orchestrator", destRoot, force });
      process.stdout.write(`\nInstalled Codex skill: ${destSkill}\nRestart Codex to pick up new skills.\n`);
    } else {
      process.stdout.write("\nSkipped Codex skill install.\n");
    }
  }

  if (doClaude) {
    const paths = initClient({ client: "claude-code", scope, projectRoot, runsRootAbs, pythonCmd, mode, baseName });
    for (const p of paths) process.stdout.write(`\nUpdated claude-code MCP config: ${p}\n`);
  }
  if (doGemini) {
    const paths = initClient({ client: "gemini-cli", scope, projectRoot, runsRootAbs, pythonCmd, mode, baseName });
    for (const p of paths) process.stdout.write(`\nUpdated gemini-cli MCP config: ${p}\n`);
  }

  process.stdout.write(`\nRuns confinement: ${runsRootAbs}\n`);
  process.stdout.write("Done.\n");
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.length === 0 || argv.includes("--help") || argv.includes("-h")) {
    printHelp();
    return;
  }

  const cmd = argv[0];
  const rest = argv.slice(1);

  if (cmd === "install") return cmdInstall(rest);
  if (cmd === "init") return cmdInit(rest);
  if (cmd === "setup") return await cmdSetup(rest);
  die(`Unknown command: ${cmd}`);
}

main().catch((e) => die(e?.message || String(e)));
