from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


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


def test_scaffold_creates_required_structure(tmp_path: Path) -> None:
    fixed_now = "2026-03-02T12:34:56-05:00"
    fixed_run_id = "abcdef1234"

    r = _run_ar(
        [
            "run",
            "scaffold",
            "--runs-root",
            str(tmp_path),
            "--slug",
            "test-run",
            "--goal",
            "Test goal",
        ],
        env_extra={"AR_FIXED_NOW": fixed_now, "AR_FIXED_RUN_ID": fixed_run_id},
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    run_dir = tmp_path / "2026-03-02" / "20260302T123456__test-run__abcdef1234"
    assert run_dir.is_dir()

    for p in (
        run_dir / "00_BRIEF.md",
        run_dir / "01_CONFIG.json",
        run_dir / "STATE.json",
        run_dir / "LOG.jsonl",
        run_dir / "10_TASKS",
        run_dir / "20_WORK",
        run_dir / "30_MERGE",
    ):
        assert p.exists(), f"Missing {p}"

    cfg = json.loads((run_dir / "01_CONFIG.json").read_text(encoding="utf-8"))
    assert cfg["schemas_version"] == 1
    assert cfg["run_id"] == fixed_run_id
    assert cfg["runner_plan"]["required"] == ["codex"]
    assert "optional" in cfg["runner_plan"]


def test_scaffold_requires_slug_or_goal(tmp_path: Path) -> None:
    r = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path)],
        env_extra={"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"},
    )
    assert r.returncode == 2
    assert "requires --slug or --goal" in (r.stdout + r.stderr)
