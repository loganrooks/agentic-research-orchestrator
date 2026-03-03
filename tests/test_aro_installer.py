from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _node() -> str | None:
    return shutil.which("node")


def _aro_js() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "integrations" / "npm" / "aro-installer" / "bin" / "aro.js"


def _run_node(
    args: list[str], *, cwd: Path, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    node = _node()
    if not node:
        pytest.skip("node not available")
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [node, str(_aro_js()), *args],
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
    )


def test_aro_installer_init_claude_code_project_writes_mcp_json(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    runs_root = tmp_path / "ar-runs"

    r = _run_node(
        [
            "init",
            "claude-code",
            "--scope",
            "project",
            "--project-root",
            str(proj),
            "--runs-root",
            str(runs_root),
            "--mode",
            "both",
            "--server-name",
            "t",
            "--python",
            sys.executable,
        ],
        cwd=tmp_path,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    cfg = json.loads((proj / ".mcp.json").read_text(encoding="utf-8"))
    assert "mcpServers" in cfg
    servers = cfg["mcpServers"]
    assert "t_ro" in servers
    assert "t_rw" in servers
    assert servers["t_ro"]["command"] == sys.executable
    assert "--write-enabled" not in servers["t_ro"]["args"]
    assert servers["t_rw"]["command"] == sys.executable
    assert "--write-enabled" in servers["t_rw"]["args"]

def test_aro_installer_init_claude_code_scope_both_writes_project_and_user(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    runs_root = tmp_path / "ar-runs"

    r = _run_node(
        [
            "init",
            "claude-code",
            "--scope",
            "both",
            "--project-root",
            str(proj),
            "--runs-root",
            str(runs_root),
            "--mode",
            "ro",
            "--server-name",
            "t",
            "--python",
            sys.executable,
        ],
        cwd=tmp_path,
        env_extra={"HOME": str(tmp_path)},
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    proj_cfg = json.loads((proj / ".mcp.json").read_text(encoding="utf-8"))
    assert "t_ro" in proj_cfg["mcpServers"]

    user_cfg = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
    assert "t_ro" in user_cfg["mcpServers"]


def test_aro_installer_init_gemini_cli_project_writes_settings_json(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    runs_root = tmp_path / "ar-runs"

    r = _run_node(
        [
            "init",
            "gemini-cli",
            "--scope",
            "project",
            "--project-root",
            str(proj),
            "--runs-root",
            str(runs_root),
            "--mode",
            "ro",
            "--server-name",
            "t",
            "--python",
            sys.executable,
        ],
        cwd=tmp_path,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    cfg = json.loads((proj / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert "mcpServers" in cfg
    servers = cfg["mcpServers"]
    assert "t_ro" in servers
    assert servers["t_ro"]["command"] == sys.executable


def test_aro_installer_install_codex_skill_copies_skill_folder(tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    dest.mkdir(parents=True, exist_ok=True)

    r = _run_node(["install", "codex-skill", "--dest", str(dest)], cwd=tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)

    skill_dir = dest / "agentic-research-orchestrator"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "agents" / "openai.yaml").exists()
