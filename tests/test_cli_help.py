from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run_ar(args: list[str]) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    return subprocess.run(
        [sys.executable, "-m", "ar", *args],
        env=env,
        text=True,
        capture_output=True,
    )


def test_ar_help_includes_run() -> None:
    r = _run_ar(["--help"])
    assert r.returncode == 0
    assert "run" in r.stdout


def test_ar_run_help_includes_subcommands() -> None:
    r = _run_ar(["run", "--help"])
    assert r.returncode == 0
    for sub in (
        "scaffold",
        "export-prompts",
        "spawn-codex",
        "import",
        "merge",
        "validate",
        "status",
    ):
        assert sub in r.stdout

