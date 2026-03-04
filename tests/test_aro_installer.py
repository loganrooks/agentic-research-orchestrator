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


def test_aro_installer_init_claude_code_project_with_backup_writes_bak_file(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    runs_root = tmp_path / "ar-runs"

    orig = {"mcpServers": {"existing": {"command": "x", "args": []}}}
    cfg_path = proj / ".mcp.json"
    cfg_path.write_text(json.dumps(orig, indent=2) + "\n", encoding="utf-8")

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
            "ro",
            "--server-name",
            "t",
            "--python",
            sys.executable,
            "--backup",
        ],
        cwd=tmp_path,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    baks = list(proj.glob(".mcp.json.bak.*"))
    assert len(baks) == 1
    assert baks[0].read_text(encoding="utf-8") == json.dumps(orig, indent=2) + "\n"

    new_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "t_ro" in new_cfg["mcpServers"]


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


def test_aro_installer_install_claude_code_skill_user_scope_copies_skill(tmp_path: Path) -> None:
    r = _run_node(
        ["install", "claude-code-skill", "--scope", "user"],
        cwd=tmp_path,
        env_extra={"HOME": str(tmp_path)},
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    skill_dir = tmp_path / ".claude" / "skills" / "agentic-research-orchestrator"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "references" / "claude-code.md").exists()


def test_aro_installer_install_claude_code_skill_project_scope_copies_skill(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)

    r = _run_node(
        [
            "install",
            "claude-code-skill",
            "--scope",
            "project",
            "--project-root",
            str(proj),
        ],
        cwd=tmp_path,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    skill_dir = proj / ".claude" / "skills" / "agentic-research-orchestrator"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "references" / "claude-code.md").exists()


def test_aro_installer_init_verify_python_fails_for_missing_python_cmd(tmp_path: Path) -> None:
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
            "ro",
            "--server-name",
            "t",
            "--python",
            "definitely-not-a-python",
            "--verify-python",
        ],
        cwd=tmp_path,
    )
    assert r.returncode != 0
    assert "python verification failed" in (r.stdout + r.stderr).lower()


def test_aro_installer_init_verify_python_succeeds_with_pythonpath(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    runs_root = tmp_path / "ar-runs"

    repo_root = Path(__file__).resolve().parents[1]
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
            "--verify-python",
        ],
        cwd=tmp_path,
        env_extra={"PYTHONPATH": str(repo_root / "src")},
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
