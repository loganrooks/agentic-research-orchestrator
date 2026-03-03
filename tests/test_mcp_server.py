from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _run_ar(args: list[str], *, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "ar", *args],
        env=env,
        text=True,
        capture_output=True,
    )


def _scaffold_run(tmp_path: Path) -> Path:
    env_scaffold = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_scaffold,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    return Path(r.stdout.strip())


def _tool_json(tool_result: dict[str, object]) -> dict[str, object]:
    assert tool_result.get("content")
    content = tool_result["content"]
    assert isinstance(content, list) and content
    txt = content[0]["text"]
    return json.loads(txt)


def test_mcp_server_lists_tools_and_blocks_writes_when_disabled(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from ar.mcp.server import ArMcpServer  # noqa: E402

    run_dir = _scaffold_run(tmp_path)

    server = ArMcpServer(write_enabled=False)
    tools = server.list_tools()
    names = {t["name"] for t in tools}
    assert "ar.run.status" in names
    assert "ar.run.apply_plan" in names

    res = server.call_tool("ar.run.apply_plan", {"run_dir": str(run_dir), "plan": {"schema_version": 1, "actions": []}})
    assert res["isError"] is True
    assert "write-enabled tools are disabled" in res["content"][0]["text"]


def test_mcp_server_lists_prompts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from ar.mcp.server import ArMcpServer  # noqa: E402

    _ = _scaffold_run(tmp_path)
    server = ArMcpServer(write_enabled=False)
    prompts = server.list_prompts()
    assert isinstance(prompts, list) and prompts
    names = {p["name"] for p in prompts}
    assert "orchestrator_prompt" in names

    p0 = next(p for p in prompts if p["name"] == "orchestrator_prompt")
    args = {a["name"]: a for a in p0.get("arguments", [])}
    assert args["run_dir"]["required"] is True


def test_mcp_server_get_prompt_orchestrator_prompt(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from ar.mcp.server import ArMcpServer  # noqa: E402

    run_dir = _scaffold_run(tmp_path)
    server = ArMcpServer(write_enabled=False)

    got = server.get_prompt("orchestrator_prompt", {"run_dir": str(run_dir)})
    assert got.get("messages")
    msgs = got["messages"]
    assert isinstance(msgs, list) and msgs
    m0 = msgs[0]
    assert m0["role"] == "user"
    content = m0["content"]
    assert content["type"] == "text"
    txt = content["text"]
    assert "Output rules (STRICT)" in txt
    assert '"schema_version": 1' in txt

    with pytest.raises(ValueError):
        server.get_prompt("orchestrator_prompt", {"run_dir": str(run_dir), "profile": "invalid"})


def test_mcp_server_can_apply_plan_when_write_enabled(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from ar.mcp.server import ArMcpServer  # noqa: E402

    run_dir = _scaffold_run(tmp_path)
    server = ArMcpServer(write_enabled=True)

    plan = {
        "schema_version": 1,
        "generated_at": "2026-03-02T12:40:00-05:00",
        "orchestrator": {"runner": "mcp", "model": "", "reasoning_effort": "", "notes": ""},
        "actions": [
            {
                "type": "create_task",
                "task_id": "T-0001",
                "slug": "alpha",
                "reason": "test",
                "task_markdown": "# Task T-0001: Alpha\n\n## Intent\nTest.\n",
            }
        ],
    }
    res = server.call_tool("ar.run.apply_plan", {"run_dir": str(run_dir), "plan": plan})
    assert res["isError"] is False
    payload = _tool_json(res)
    assert payload["rc"] == 0
    assert (run_dir / "10_TASKS" / "T-0001__alpha.md").exists()


def test_mcp_server_rejects_symlink_escape_on_write_tools(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from ar.mcp.server import ArMcpServer  # noqa: E402

    run_dir = _scaffold_run(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)

    tasks_dir = run_dir / "10_TASKS"
    shutil.rmtree(tasks_dir)
    try:
        os.symlink(str(outside), str(tasks_dir))
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"symlink not supported: {e}")

    server = ArMcpServer(write_enabled=True)
    res = server.call_tool("ar.run.merge", {"run_dir": str(run_dir)})
    assert res["isError"] is True
    assert "unsafe run_dir for writes" in res["content"][0]["text"]
