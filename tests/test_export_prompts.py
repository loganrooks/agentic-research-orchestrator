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


def test_export_prompts_writes_one_file_per_task(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    tasks_dir = run_dir / "10_TASKS"
    (tasks_dir / "T-0001__alpha.md").write_text("# Task T-0001: Alpha\n\nDo A.\n", encoding="utf-8")
    (tasks_dir / "T-0002__beta.md").write_text("# Task T-0002: Beta\n\nDo B.\n", encoding="utf-8")

    r_export = _run_ar(["run", "export-prompts", "--run-dir", str(run_dir), "--runner", "claude_desktop"])
    assert r_export.returncode == 0, (r_export.stdout, r_export.stderr)

    out_dir = run_dir / "11_EXPORT" / "claude_desktop"
    assert out_dir.is_dir()
    exported = sorted([p.name for p in out_dir.iterdir() if p.is_file()])
    assert exported == ["T-0001__alpha.md", "T-0002__beta.md"]

    t1 = (out_dir / "T-0001__alpha.md").read_text(encoding="utf-8")
    assert "runner=claude_desktop" in t1
    assert "Residuals / Open Questions" in t1
    assert "# Task T-0001: Alpha" in t1

