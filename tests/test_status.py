from __future__ import annotations

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


def test_status_reports_scaffolded(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0
    run_dir = Path(r_scaffold.stdout.strip())

    r_status = _run_ar(["run", "status", "--run-dir", str(run_dir)])
    assert r_status.returncode == 0
    assert "status: scaffolded" in r_status.stdout
    assert "run_id: abcdef1234" in r_status.stdout


def test_status_includes_log_tail(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0
    run_dir = Path(r_scaffold.stdout.strip())

    r_status = _run_ar(["run", "status", "--run-dir", str(run_dir)])
    assert r_status.returncode == 0
    assert "log_tail (last 10):" in r_status.stdout
    i_scaffold = r_status.stdout.find('"event": "scaffolded"')
    i_status_called = r_status.stdout.find('"event": "status_called"')
    assert i_scaffold != -1 and i_status_called != -1 and i_scaffold < i_status_called
