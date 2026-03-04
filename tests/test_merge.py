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


def test_merge_writes_comparison_artifacts(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0
    run_dir = Path(r_scaffold.stdout.strip())

    report_a = tmp_path / "a.md"
    report_a.write_text("# A\n", encoding="utf-8")
    report_b = tmp_path / "b.md"
    report_b.write_text("# B\n", encoding="utf-8")

    r_imp_a = _run_ar(
        [
            "run",
            "import",
            "--run-dir",
            str(run_dir),
            "--task",
            "T-0001",
            "--runner",
            "claude_desktop",
            "--report-path",
            str(report_a),
        ]
    )
    assert r_imp_a.returncode == 0
    r_imp_b = _run_ar(
        [
            "run",
            "import",
            "--run-dir",
            str(run_dir),
            "--task",
            "T-0001",
            "--runner",
            "gemini_deep_research",
            "--report-path",
            str(report_b),
        ]
    )
    assert r_imp_b.returncode == 0

    r_merge = _run_ar(["run", "merge", "--run-dir", str(run_dir)])
    assert r_merge.returncode == 0, (r_merge.stdout, r_merge.stderr)

    comp_json = run_dir / "30_MERGE" / "COMPARISON.json"
    assert comp_json.exists()
    data = json.loads(comp_json.read_text(encoding="utf-8"))
    t = next(t for t in data["tasks"] if t["task_id"] == "T-0001")
    assert len(t["producers"]) == 2

    state = json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))
    assert state.get("status") == "running"
