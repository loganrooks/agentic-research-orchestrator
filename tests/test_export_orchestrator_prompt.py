from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_ar(
    args: list[str],
    *,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
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


def _scaffold_run_dir(tmp_path: Path, *, env_fixed: dict[str, str]) -> Path:
    r = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    return Path(r.stdout.strip())


def test_export_orchestrator_prompt_normal_includes_comparison_md(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56", "AR_FIXED_RUN_ID": "abcdef1234"}
    run_dir = _scaffold_run_dir(tmp_path, env_fixed=env_fixed)

    (run_dir / "10_TASKS" / "T-0001__alpha.md").write_text("# Task T-0001: Alpha\n\nDo A.\n", encoding="utf-8")

    merge_dir = run_dir / "30_MERGE"
    (merge_dir / "COMPARISON.md").write_text("# Comparison\n\nProducer A vs Producer B\n", encoding="utf-8")
    (merge_dir / "COMPARISON.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "T-0001",
                        "divergences": [{"type": "contradiction", "summary": "A says X; B says not-X"}],
                    }
                ]
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    out_path = tmp_path / "orch_normal.md"
    r = _run_ar(
        [
            "run",
            "export-orchestrator-prompt",
            "--run-dir",
            str(run_dir),
            "--runner",
            "codex",
            "--profile",
            "normal",
            "--out-path",
            str(out_path),
        ],
        env_extra=env_fixed,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert Path(r.stdout.strip()) == out_path.resolve()

    prompt = out_path.read_text(encoding="utf-8")
    assert "# Orchestrator Prompt (runner=codex)" in prompt
    assert "## OrchestratorPlan schema v1 (example)" in prompt
    assert "### Divergences summary (`30_MERGE/COMPARISON.json`)" in prompt
    assert "#### 30_MERGE/COMPARISON.md" in prompt
    assert "- T-0001__alpha.md" in prompt


def test_export_orchestrator_prompt_guided_omits_comparison_md(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56", "AR_FIXED_RUN_ID": "abcdef1234"}
    run_dir = _scaffold_run_dir(tmp_path, env_fixed=env_fixed)

    merge_dir = run_dir / "30_MERGE"
    (merge_dir / "COMPARISON.md").write_text("# Comparison\n\nA vs B\n", encoding="utf-8")
    (merge_dir / "COMPARISON.json").write_text(
        json.dumps({"tasks": [{"task_id": "T-0001", "divergences": [{"type": "other", "summary": "diff"}]}]}),
        encoding="utf-8",
    )

    out_path = tmp_path / "orch_guided.md"
    r = _run_ar(
        [
            "run",
            "export-orchestrator-prompt",
            "--run-dir",
            str(run_dir),
            "--runner",
            "codex",
            "--profile",
            "guided",
            "--out-path",
            str(out_path),
        ],
        env_extra=env_fixed,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    prompt = out_path.read_text(encoding="utf-8")
    assert "## Workflow (guided)" in prompt
    assert "## Task markdown template (use this structure)" in prompt
    assert "## Plan self-check rubric" in prompt
    assert "### Divergences summary (`30_MERGE/COMPARISON.json`)" in prompt
    assert "#### 30_MERGE/COMPARISON.md" not in prompt


def test_export_orchestrator_prompt_rejects_invalid_profile(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56", "AR_FIXED_RUN_ID": "abcdef1234"}
    run_dir = _scaffold_run_dir(tmp_path, env_fixed=env_fixed)

    out_path = tmp_path / "orch_bad.md"
    r = _run_ar(
        [
            "run",
            "export-orchestrator-prompt",
            "--run-dir",
            str(run_dir),
            "--runner",
            "codex",
            "--profile",
            "nope",
            "--out-path",
            str(out_path),
        ],
        env_extra=env_fixed,
    )
    assert r.returncode == 2
    assert "invalid export-orchestrator-prompt args" in (r.stdout + r.stderr).lower()

