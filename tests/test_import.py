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


def test_import_creates_producer_dir_and_updates_state(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
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
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())
    assert run_dir.is_dir()

    report_src = tmp_path / "report.md"
    report_src.write_text("# Report\n\nHello.\n", encoding="utf-8")

    r_import = _run_ar(
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
            str(report_src),
        ],
        env_extra={"AR_FIXED_NOW": "2026-03-02T12:35:00-05:00"},
    )
    assert r_import.returncode == 0, (r_import.stdout, r_import.stderr)

    producer_dir = run_dir / "20_WORK" / "T-0001" / "claude_desktop:manual-01"
    assert producer_dir.is_dir()
    assert (producer_dir / "PROVENANCE.json").exists()
    assert (producer_dir / "REPORT.md").read_text(encoding="utf-8").startswith("# Report")

    # Missing registers should be created as empty placeholders.
    assert json.loads((producer_dir / "SOURCES.json").read_text(encoding="utf-8")) == []
    assert json.loads((producer_dir / "CLAIMS.json").read_text(encoding="utf-8")) == []
    assert (producer_dir / "RESIDUALS.md").exists()

    state = json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))
    assert any(t["task_id"] == "T-0001" for t in state["tasks"])
    t = next(t for t in state["tasks"] if t["task_id"] == "T-0001")
    assert "claude_desktop:manual-01" in t["producers"]


def test_import_marks_existing_task_done(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "ISO8601",
                "orchestrator": {"runner": "codex", "model": "", "reasoning_effort": "", "notes": ""},
                "actions": [
                    {
                        "type": "create_task",
                        "task_id": "T-0001",
                        "slug": "alpha",
                        "reason": "test",
                        "task_markdown": "# Task T-0001: Alpha\n\n## Intent\nX\n",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    r_apply = _run_ar(["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(plan_path)])
    assert r_apply.returncode == 0, (r_apply.stdout, r_apply.stderr)

    report_src = tmp_path / "report.md"
    report_src.write_text("# Report\n\nHello.\n", encoding="utf-8")

    r_import = _run_ar(
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
            str(report_src),
        ],
    )
    assert r_import.returncode == 0, (r_import.stdout, r_import.stderr)

    state = json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))
    t = next(t for t in state["tasks"] if t["task_id"] == "T-0001")
    assert t.get("status") == "done"
