#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
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

function _truncate(s, maxLen) {
  const t = String(s || "");
  if (t.length <= maxLen) return t;
  return t.slice(0, maxLen).trimEnd() + "…";
}

function verifyPythonHasAr(pythonCmd) {
  const cmd = String(pythonCmd || "").trim() || "python3";
  const r = spawnSync(cmd, ["-m", "ar", "--help"], { encoding: "utf8" });
  if (r.error) {
    return { ok: false, cmd, reason: "spawn_error", error: String(r.error.message || r.error) };
  }
  if (r.status !== 0) {
    return {
      ok: false,
      cmd,
      reason: "nonzero_exit",
      status: r.status,
      stderr: _truncate(r.stderr || "", 1200),
      stdout: _truncate(r.stdout || "", 1200),
    };
  }
  return { ok: true, cmd };
}

function printHelp() {
  const help = `
aro-installer

Usage:
  aro --help

  aro install codex-skill [--name <skill>] [--dest <skills-root>] [--force]
  aro install claude-code-skill --scope <project|user|both> [--project-root <dir>] [--name <skill>] [--force]

  aro init claude-code --scope <project|user|both> [--project-root <dir>] [--runs-root <dir>] [--python <cmd>] [--mode <ro|rw|both>] [--server-name <base>] [--backup] [--verify-python]
  aro init gemini-cli --scope <project|user|both> [--project-root <dir>] [--runs-root <dir>] [--python <cmd>] [--mode <ro|rw|both>] [--server-name <base>] [--backup] [--verify-python]

  aro setup [--tier <profile|custom|advanced>] [--profile <safe|standard|global>]
             # interactive wizard (requires TTY)

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

function defaultClaudeSkillsRootUser() {
  return path.join(os.homedir(), ".claude", "skills");
}

function defaultClaudeSkillsRootProject(projectRoot) {
  return path.join(projectRoot, ".claude", "skills");
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

function makeAroServerDef({ pythonCmd, runsRootAbs, writeEnabled, maxCallsPerMinute }) {
  const args = ["-m", "ar", "mcp", "serve"];
  if (writeEnabled) args.push("--write-enabled");
  args.push("--allow-run-dir-prefix", runsRootAbs);
  const m = Number(maxCallsPerMinute || 0);
  if (Number.isFinite(m) && m > 0) {
    args.push("--max-calls-per-minute", String(Math.floor(m)));
  }
  return { command: pythonCmd, args };
}

function addServersToConfig({ config, baseName, pythonCmd, runsRootAbs, mode, maxCallsPerMinute }) {
  const mcpServers = ensureObjectField(config, "mcpServers", "<config>");
  if (mode === "ro" || mode === "both") {
    mcpServers[`${baseName}_ro`] = makeAroServerDef({ pythonCmd, runsRootAbs, writeEnabled: false, maxCallsPerMinute });
  }
  if (mode === "rw" || mode === "both") {
    mcpServers[`${baseName}_rw`] = makeAroServerDef({ pythonCmd, runsRootAbs, writeEnabled: true, maxCallsPerMinute });
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

function installClaudeCodeSkill({ skillName, scope, projectRoot, force }) {
  if (!["project", "user", "both"].includes(scope)) die("Invalid --scope. Expected: project | user | both");
  const scopes = scope === "both" ? ["user", "project"] : [scope];

  const installed = [];
  for (const sc of scopes) {
    const destRoot = sc === "user" ? defaultClaudeSkillsRootUser() : defaultClaudeSkillsRootProject(projectRoot);
    installed.push(installCodexSkill({ skillName, destRoot, force }));
  }
  return installed;
}

function _backupFileIfExists(p, ts) {
  if (!fs.existsSync(p)) return;
  const b = `${p}.bak.${ts}`;
  fs.copyFileSync(p, b);
}

function _backupTs() {
  // 20260303T203012Z
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z").replace("T", "T");
}

function initClient({ client, scope, projectRoot, runsRootAbs, pythonCmd, mode, baseName, maxCallsPerMinute, backupExisting }) {
  if (!["project", "user", "both"].includes(scope)) die("Invalid scope");
  if (!["ro", "rw", "both"].includes(mode)) die("Invalid mode");

  const scopes = scope === "both" ? ["user", "project"] : [scope];
  const configPaths = [];

  const ts = backupExisting ? _backupTs() : "";
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
    if (backupExisting) _backupFileIfExists(configPath, ts);
    const config = readJsonIfExists(configPath);
    if (config.mcpServers !== undefined) {
      ensureObjectField(config, "mcpServers", configPath);
    }
    addServersToConfig({ config, baseName, pythonCmd, runsRootAbs, mode, maxCallsPerMinute });
    writeJson(configPath, config);
  }
  return configPaths;
}

function cmdInstall(argv) {
  const { positionals, flags } = parseFlags(argv);
  const sub = positionals[0];
  if (sub !== "codex-skill" && sub !== "claude-code-skill") {
    die(`Unknown install target: ${sub || "<missing>"}`);
  }

  const skillName = String(flags.name || "agentic-research-orchestrator").trim();
  const force = flags.force === true || String(flags.force || "").toLowerCase() === "true";

  if (sub === "codex-skill") {
    const destRoot = expandHome(flags.dest || "") || defaultCodexSkillsRoot();
    const destSkill = installCodexSkill({ skillName, destRoot, force });
    process.stdout.write(`Installed Codex skill: ${destSkill}\n`);
    process.stdout.write("Restart Codex to pick up new skills.\n");
    return;
  }

  const scope = String(flags.scope || "").trim() || "project";
  if (!["project", "user", "both"].includes(scope)) die("Invalid --scope. Expected: project | user | both");
  const projectRoot = path.resolve(expandHome(flags["project-root"] || "") || process.cwd());
  const paths = installClaudeCodeSkill({ skillName, scope, projectRoot, force });
  for (const p of paths) {
    process.stdout.write(`Installed Claude Code skill: ${p}\n`);
  }
  process.stdout.write("Restart Claude Code if it does not pick up skills automatically.\n");
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
  const backupExisting = flags.backup === true || String(flags.backup || "").toLowerCase() === "true";
  const verifyPython = flags["verify-python"] === true || String(flags["verify-python"] || "").toLowerCase() === "true";

  if (!["ro", "rw", "both"].includes(mode)) die("Invalid --mode. Expected: ro | rw | both");

  if (verifyPython) {
    const check = verifyPythonHasAr(pythonCmd);
    if (!check.ok) {
      die(
        [
          `Python verification failed for '${check.cmd} -m ar --help'.`,
          "This tool does not install the Python package; install agentic-research-orchestrator into that Python environment, then re-run.",
          check.reason === "spawn_error" ? `error: ${check.error}` : `exit_status: ${check.status}`,
          check.stderr ? `stderr:\n${check.stderr}` : "",
        ]
          .filter(Boolean)
          .join("\n"),
      );
    }
  }

  const configPaths = initClient({
    client,
    scope,
    projectRoot,
    runsRootAbs,
    pythonCmd,
    mode,
    baseName,
    maxCallsPerMinute: 0,
    backupExisting,
  });
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

async function _pickOne(question, options, defId) {
  const idxDefault = Math.max(
    0,
    options.findIndex((o) => o.id === defId),
  );
  process.stdout.write(question + "\n");
  for (let i = 0; i < options.length; i++) {
    const o = options[i];
    const suffix = i === idxDefault ? " (default)" : "";
    process.stdout.write(`  ${i + 1}) ${o.label}${suffix}\n`);
  }
  const ans = (await _ask("Choice", String(idxDefault + 1))).trim();
  const t = ans.toLowerCase();
  const asNum = parseInt(t, 10);
  if (!Number.isNaN(asNum) && asNum >= 1 && asNum <= options.length) {
    return options[asNum - 1];
  }
  const byId = options.find((o) => o.id === t || o.id.startsWith(t));
  if (byId) return byId;
  return options[idxDefault];
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

function _defaultRunsRoot() {
  return path.join(os.homedir(), ".ar", "runs");
}

function _setupProfiles() {
  const base = {
    installSkill: true,
    installClaudeSkill: true,
    doClaude: true,
    doGemini: true,
    scope: "project",
    mode: "both",
    baseName: "aro",
    runsRootAbs: path.resolve(_defaultRunsRoot()),
    pythonCmd: "python3",
    maxCallsPerMinute: 60,
    backupExisting: true,
    skillDestRoot: defaultCodexSkillsRoot(),
    skillForce: false,
  };
  return [
    {
      id: "safe",
      label: "Safe (project, Claude Code, read-only)",
      defaults: { ...base, doGemini: false, scope: "project", mode: "ro" },
    },
    {
      id: "standard",
      label: "Standard (project, Claude+Gemini, ro+rw)",
      defaults: { ...base, scope: "project", mode: "both" },
    },
    {
      id: "global",
      label: "Everywhere (user+project, Claude+Gemini, ro+rw)",
      defaults: { ...base, scope: "both", mode: "both" },
    },
  ];
}

function _printSetupSummary(cfg, projectRoot) {
  const scopeText = cfg.scope === "both" ? "user + project" : cfg.scope;
  const servers = [];
  if (cfg.mode === "ro" || cfg.mode === "both") servers.push(`${cfg.baseName}_ro`);
  if (cfg.mode === "rw" || cfg.mode === "both") servers.push(`${cfg.baseName}_rw`);

  process.stdout.write("\nPlanned changes:\n");
  if (cfg.installSkill) {
    process.stdout.write(`- Codex skill -> ${path.join(cfg.skillDestRoot, "agentic-research-orchestrator")}\n`);
  }
  if (cfg.installClaudeSkill) {
    const scopes = cfg.scope === "both" ? ["user", "project"] : [cfg.scope];
    for (const sc of scopes) {
      const destRoot = sc === "user" ? defaultClaudeSkillsRootUser() : defaultClaudeSkillsRootProject(projectRoot);
      process.stdout.write(`- Claude Code skill (${sc}) -> ${path.join(destRoot, "agentic-research-orchestrator")}\n`);
    }
  }
  if (cfg.doClaude) {
    process.stdout.write(`- Claude Code MCP (${scopeText})\n`);
  }
  if (cfg.doGemini) {
    process.stdout.write(`- Gemini CLI MCP (${scopeText})\n`);
  }
  process.stdout.write(`- MCP servers: ${servers.join(", ") || "(none)"}\n`);
  process.stdout.write(`- Runs confinement: ${cfg.runsRootAbs}\n`);
  process.stdout.write(`- Command: ${cfg.pythonCmd} -m ar mcp serve ...\n`);
  if (cfg.maxCallsPerMinute) process.stdout.write(`- Rate limit: ${cfg.maxCallsPerMinute} calls/min\n`);
  if (cfg.scope !== "user") process.stdout.write(`- Project root: ${projectRoot}\n`);
  if (cfg.backupExisting) process.stdout.write("- Backups: enabled (.bak.<ts>)\n");
}

async function cmdSetup(argv) {
  _requireTty();

  const { flags } = parseFlags(argv || []);

  process.stdout.write("aro-installer setup (interactive)\n\n");

  const tierOpt = [
    { id: "profile", label: "Profile (no customization)" },
    { id: "custom", label: "Custom (some customization)" },
    { id: "advanced", label: "Advanced (full control)" },
  ];
  let tier = String(flags.tier || "").trim().toLowerCase();
  if (!tier) tier = (await _pickOne("Select setup tier:", tierOpt, "profile")).id;
  if (!["profile", "custom", "advanced"].includes(tier)) die("Invalid --tier. Expected: profile | custom | advanced");

  const profiles = _setupProfiles();
  let profileId = String(flags.profile || "").trim().toLowerCase();
  let profile = profiles.find((p) => p.id === profileId);
  if (!profile) {
    profile = await _pickOne("Select a base profile:", profiles.map((p) => ({ id: p.id, label: p.label })), "standard");
    profile = profiles.find((p) => p.id === profile.id) || profiles[0];
  }

  const cfg = { ...profile.defaults };
  let projectRoot = path.resolve(process.cwd());

  if (tier === "profile") {
    if (cfg.scope !== "user") {
      projectRoot = path.resolve(process.cwd());
    }
  } else if (tier === "custom") {
    cfg.installSkill = await _askYesNo("Install Codex skill?", cfg.installSkill);
    cfg.installClaudeSkill = await _askYesNo("Install Claude Code skill?", cfg.installClaudeSkill);
    cfg.doClaude = await _askYesNo("Configure Claude Code MCP?", cfg.doClaude);
    cfg.doGemini = await _askYesNo("Configure Gemini CLI MCP?", cfg.doGemini);

    cfg.scope = (await _ask("Install scope for MCP configs (project|user|both)", cfg.scope)).trim() || cfg.scope;
    if (!["project", "user", "both"].includes(cfg.scope)) die("Invalid scope; expected project|user|both");

    if (cfg.scope !== "user") {
      projectRoot = path.resolve(expandHome(await _ask("Project root (used for project scope)", process.cwd())));
    }
    cfg.runsRootAbs = path.resolve(expandHome(await _ask("Runs root (for --allow-run-dir-prefix)", cfg.runsRootAbs)));
    cfg.pythonCmd = (await _ask("Python command/path (must have agentic-research-orchestrator installed)", cfg.pythonCmd)).trim() || cfg.pythonCmd;
    cfg.mode = (await _ask("MCP server mode (ro|rw|both)", cfg.mode)).trim() || cfg.mode;
    if (!["ro", "rw", "both"].includes(cfg.mode)) die("Invalid mode; expected ro|rw|both");
    cfg.baseName = (await _ask("Server name base (prefix for *_ro/*_rw)", cfg.baseName)).trim() || cfg.baseName;
  } else {
    cfg.installSkill = await _askYesNo("Install Codex skill?", cfg.installSkill);
    cfg.skillDestRoot = path.resolve(expandHome(await _ask("Codex skills root", cfg.skillDestRoot)));
    cfg.skillForce = await _askYesNo("Overwrite Codex skill if it already exists?", cfg.skillForce);

    cfg.installClaudeSkill = await _askYesNo("Install Claude Code skill?", cfg.installClaudeSkill);
    cfg.doClaude = await _askYesNo("Configure Claude Code MCP?", cfg.doClaude);
    cfg.doGemini = await _askYesNo("Configure Gemini CLI MCP?", cfg.doGemini);

    cfg.scope = (await _ask("Install scope for MCP configs (project|user|both)", cfg.scope)).trim() || cfg.scope;
    if (!["project", "user", "both"].includes(cfg.scope)) die("Invalid scope; expected project|user|both");

    if (cfg.scope !== "user") {
      projectRoot = path.resolve(expandHome(await _ask("Project root (used for project scope)", process.cwd())));
    }
    cfg.runsRootAbs = path.resolve(expandHome(await _ask("Runs root (for --allow-run-dir-prefix)", cfg.runsRootAbs)));
    cfg.pythonCmd = (await _ask("Python command/path (must have agentic-research-orchestrator installed)", cfg.pythonCmd)).trim() || cfg.pythonCmd;
    cfg.mode = (await _ask("MCP server mode (ro|rw|both)", cfg.mode)).trim() || cfg.mode;
    if (!["ro", "rw", "both"].includes(cfg.mode)) die("Invalid mode; expected ro|rw|both");
    cfg.baseName = (await _ask("Server name base (prefix for *_ro/*_rw)", cfg.baseName)).trim() || cfg.baseName;

    cfg.maxCallsPerMinute = parseInt(await _ask("MCP max calls per minute (0 = default)", String(cfg.maxCallsPerMinute)), 10);
    if (Number.isNaN(cfg.maxCallsPerMinute) || cfg.maxCallsPerMinute < 0) die("Invalid max calls per minute");
    cfg.backupExisting = await _askYesNo("Backup existing MCP config files before editing?", cfg.backupExisting);
  }

  _printSetupSummary(cfg, projectRoot);
  let pythonCheck = null;
  if (cfg.doClaude || cfg.doGemini) {
    pythonCheck = verifyPythonHasAr(cfg.pythonCmd);
    if (pythonCheck.ok) {
      process.stdout.write("- Python check: OK (`-m ar --help`)\n");
    } else {
      process.stdout.write("- Python check: FAILED (`-m ar --help`)\n");
      if (pythonCheck.reason === "spawn_error") {
        process.stdout.write(`  - error: ${pythonCheck.error}\n`);
      } else {
        process.stdout.write(`  - exit_status: ${pythonCheck.status}\n`);
        if (pythonCheck.stderr) process.stdout.write(`  - stderr: ${_truncate(pythonCheck.stderr, 250)}\n`);
      }
      process.stdout.write(
        "  - Note: this tool does not install the Python package; install agentic-research-orchestrator into that environment.\n",
      );
    }
  }

  const proceedDefault = pythonCheck ? pythonCheck.ok : true;
  const ok = await _askYesNo("Proceed?", proceedDefault);
  if (!ok) {
    process.stdout.write("Aborted.\n");
    return;
  }

  if (cfg.installSkill) {
    const existing = path.join(cfg.skillDestRoot, "agentic-research-orchestrator");
    let force = cfg.skillForce;
    if (!force && fs.existsSync(existing)) {
      force = await _askYesNo(`Codex skill already exists at ${existing}. Overwrite?`, false);
    }
    if (!fs.existsSync(existing) || force) {
      const destSkill = installCodexSkill({ skillName: "agentic-research-orchestrator", destRoot: cfg.skillDestRoot, force });
      process.stdout.write(`\nInstalled Codex skill: ${destSkill}\nRestart Codex to pick up new skills.\n`);
    } else {
      process.stdout.write("\nSkipped Codex skill install.\n");
    }
  }

  if (cfg.installClaudeSkill) {
    const scopes = cfg.scope === "both" ? ["user", "project"] : [cfg.scope];
    const installed = [];
    for (const sc of scopes) {
      const destRoot = sc === "user" ? defaultClaudeSkillsRootUser() : defaultClaudeSkillsRootProject(projectRoot);
      const existing = path.join(destRoot, "agentic-research-orchestrator");
      let force = cfg.skillForce;
      if (!force && fs.existsSync(existing)) {
        force = await _askYesNo(`Claude Code skill already exists at ${existing}. Overwrite?`, false);
      }
      if (!fs.existsSync(existing) || force) {
        installed.push(installCodexSkill({ skillName: "agentic-research-orchestrator", destRoot, force }));
      } else {
        process.stdout.write(`\nSkipped Claude Code skill install for ${sc} scope.\n`);
      }
    }
    for (const p of installed) process.stdout.write(`\nInstalled Claude Code skill: ${p}\n`);
  }

  if (cfg.doClaude) {
    const paths = initClient({
      client: "claude-code",
      scope: cfg.scope,
      projectRoot,
      runsRootAbs: cfg.runsRootAbs,
      pythonCmd: cfg.pythonCmd,
      mode: cfg.mode,
      baseName: cfg.baseName,
      maxCallsPerMinute: cfg.maxCallsPerMinute,
      backupExisting: cfg.backupExisting,
    });
    for (const p of paths) process.stdout.write(`\nUpdated claude-code MCP config: ${p}\n`);
  }
  if (cfg.doGemini) {
    const paths = initClient({
      client: "gemini-cli",
      scope: cfg.scope,
      projectRoot,
      runsRootAbs: cfg.runsRootAbs,
      pythonCmd: cfg.pythonCmd,
      mode: cfg.mode,
      baseName: cfg.baseName,
      maxCallsPerMinute: cfg.maxCallsPerMinute,
      backupExisting: cfg.backupExisting,
    });
    for (const p of paths) process.stdout.write(`\nUpdated gemini-cli MCP config: ${p}\n`);
  }

  process.stdout.write(`\nRuns confinement: ${cfg.runsRootAbs}\n`);
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
