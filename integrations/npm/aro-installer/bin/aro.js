#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");

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

  aro init claude-code --scope <project|user> [--project-root <dir>] [--runs-root <dir>] [--python <cmd>] [--mode <ro|rw|both>] [--server-name <base>]
  aro init gemini-cli --scope <project|user> [--project-root <dir>] [--runs-root <dir>] [--python <cmd>] [--mode <ro|rw|both>] [--server-name <base>]

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

function cmdInstall(argv) {
  const { positionals, flags } = parseFlags(argv);
  const sub = positionals[0];
  if (sub !== "codex-skill") die(`Unknown install target: ${sub || "<missing>"}`);

  const skillName = String(flags.name || "agentic-research-orchestrator").trim();
  const destRoot = expandHome(flags.dest || "") || defaultCodexSkillsRoot();
  const force = flags.force === true || String(flags.force || "").toLowerCase() === "true";

  const srcSkill = path.join(__dirname, "..", "skills", skillName);
  if (!fs.existsSync(srcSkill)) die(`Skill not found in package: ${srcSkill}`);

  fs.mkdirSync(destRoot, { recursive: true });
  const destSkill = path.join(destRoot, skillName);
  if (fs.existsSync(destSkill)) {
    if (!force) die(`Destination exists: ${destSkill} (re-run with --force to overwrite)`);
    fs.rmSync(destSkill, { recursive: true, force: true });
  }
  fs.cpSync(srcSkill, destSkill, { recursive: true });
  process.stdout.write(`Installed Codex skill: ${destSkill}\n`);
  process.stdout.write("Restart Codex to pick up new skills.\n");
}

function cmdInit(argv) {
  const { positionals, flags } = parseFlags(argv);
  const client = positionals[0];
  if (!client) die("Missing client. Expected: claude-code | gemini-cli");

  const scope = String(flags.scope || "").trim() || "project";
  if (!["project", "user"].includes(scope)) die("Invalid --scope. Expected: project | user");

  const projectRoot = path.resolve(expandHome(flags["project-root"] || "") || process.cwd());
  const runsRootAbs = path.resolve(expandHome(flags["runs-root"] || "") || path.join(os.homedir(), ".ar", "runs"));
  const pythonCmd = String(flags.python || "").trim() || "python3";
  const mode = String(flags.mode || "").trim() || "ro";
  const baseName = String(flags["server-name"] || "").trim() || "aro";

  if (!["ro", "rw", "both"].includes(mode)) die("Invalid --mode. Expected: ro | rw | both");

  let configPath;
  if (client === "claude-code") {
    configPath = scope === "project" ? path.join(projectRoot, ".mcp.json") : path.join(os.homedir(), ".claude.json");
  } else if (client === "gemini-cli") {
    configPath =
      scope === "project"
        ? path.join(projectRoot, ".gemini", "settings.json")
        : path.join(os.homedir(), ".gemini", "settings.json");
  } else {
    die(`Unknown client: ${client}`);
  }

  const config = readJsonIfExists(configPath);
  if (config.mcpServers !== undefined) {
    ensureObjectField(config, "mcpServers", configPath);
  }
  addServersToConfig({ config, baseName, pythonCmd, runsRootAbs, mode });
  writeJson(configPath, config);
  process.stdout.write(`Updated ${client} MCP config: ${configPath}\n`);
  process.stdout.write(`Runs confinement: ${runsRootAbs}\n`);
}

function main() {
  const argv = process.argv.slice(2);
  if (argv.length === 0 || argv.includes("--help") || argv.includes("-h")) {
    printHelp();
    return;
  }

  const cmd = argv[0];
  const rest = argv.slice(1);

  if (cmd === "install") return cmdInstall(rest);
  if (cmd === "init") return cmdInit(rest);
  die(`Unknown command: ${cmd}`);
}

main();

