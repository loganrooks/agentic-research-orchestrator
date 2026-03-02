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


def test_validate_ok_on_scaffolded_run(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0
    run_dir = Path(r_scaffold.stdout.strip())

    r_val = _run_ar(["run", "validate", "--run-dir", str(run_dir)])
    assert r_val.returncode == 0, (r_val.stdout, r_val.stderr)


def test_validate_fails_on_missing_producer_files(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0
    run_dir = Path(r_scaffold.stdout.strip())

    # Create an incomplete producer output dir (missing PROVENANCE.json).
    producer_dir = run_dir / "20_WORK" / "T-0001" / "codex:worker-01"
    producer_dir.mkdir(parents=True, exist_ok=True)
    (producer_dir / "REPORT.md").write_text("hi\n", encoding="utf-8")
    (producer_dir / "SOURCES.json").write_text("[]\n", encoding="utf-8")
    (producer_dir / "CLAIMS.json").write_text("[]\n", encoding="utf-8")
    (producer_dir / "RESIDUALS.md").write_text("none\n", encoding="utf-8")

    r_val = _run_ar(["run", "validate", "--run-dir", str(run_dir)])
    assert r_val.returncode == 30
    assert "PROVENANCE.json" in (r_val.stdout + r_val.stderr)

