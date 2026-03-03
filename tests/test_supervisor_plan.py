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


def _read_log_events(run_dir: Path) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for raw in (run_dir / "LOG.jsonl").read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        out.append(json.loads(raw))
    return out


def test_export_orchestrator_prompt_writes_file_and_logs(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    r_export = _run_ar(
        ["run", "export-orchestrator-prompt", "--run-dir", str(run_dir), "--runner", "gemini_cli"],
        env_extra={"AR_FIXED_NOW": "2026-03-02T12:35:00-05:00"},
    )
    assert r_export.returncode == 0, (r_export.stdout, r_export.stderr)
    out_path = Path(r_export.stdout.strip())
    assert out_path.exists()
    txt = out_path.read_text(encoding="utf-8")
    assert "OrchestratorPlan" in txt
    assert "Output **ONLY** one JSON object" in txt

    events = _read_log_events(run_dir)
    assert any(e.get("event") == "exported_orchestrator_prompt" for e in events)


def test_export_orchestrator_prompt_guided_includes_template_and_rubric(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    r_export = _run_ar(
        [
            "run",
            "export-orchestrator-prompt",
            "--run-dir",
            str(run_dir),
            "--runner",
            "claude_code",
            "--profile",
            "guided",
        ],
        env_extra={"AR_FIXED_NOW": "2026-03-02T12:35:00-05:00"},
    )
    assert r_export.returncode == 0, (r_export.stdout, r_export.stderr)
    out_path = Path(r_export.stdout.strip())
    txt = out_path.read_text(encoding="utf-8")
    assert "## Task markdown template" in txt
    assert "## Plan self-check rubric" in txt
    assert "Suggested next task ids" in txt


def test_export_orchestrator_prompt_includes_divergence_summary_when_present(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    comp = {
        "schema_version": 1,
        "generated_at": "2026-03-02T12:40:00-05:00",
        "tasks": [
            {
                "task_id": "T-0001",
                "producers": [],
                "divergences": [
                    {
                        "type": "coverage_gap",
                        "summary": "One producer reported no claims while another reported claims.",
                        "affected_claim_ids": [],
                        "notes": "",
                    }
                ],
            }
        ],
    }
    (run_dir / "30_MERGE" / "COMPARISON.json").write_text(json.dumps(comp, indent=2) + "\n", encoding="utf-8")
    (run_dir / "30_MERGE" / "RESIDUALS.md").write_text("# Residuals\n\n## T-0001 / codex:worker-01\n\nnone\n", encoding="utf-8")

    r_export = _run_ar(
        ["run", "export-orchestrator-prompt", "--run-dir", str(run_dir), "--runner", "gemini_cli"],
        env_extra={"AR_FIXED_NOW": "2026-03-02T12:41:00-05:00"},
    )
    assert r_export.returncode == 0, (r_export.stdout, r_export.stderr)
    out_path = Path(r_export.stdout.strip())
    txt = out_path.read_text(encoding="utf-8")
    assert "Divergences summary" in txt
    assert "coverage_gap" in txt


def test_apply_plan_creates_tasks_updates_state_and_logs(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    plan = {
        "schema_version": 1,
        "generated_at": "2026-03-02T12:40:00-05:00",
        "orchestrator": {"runner": "claude_code", "model": "x", "reasoning_effort": "y", "notes": ""},
        "assumptions": [{"id": "A1", "text": "Assume X", "falsify": "Try Y"}],
        "stop_rules": [{"id": "S1", "text": "Stop after diminishing returns"}],
        "actions": [
            {
                "type": "create_task",
                "task_id": "T-0001",
                "slug": "alpha",
                "reason": "coverage gap",
                "task_markdown": "# Task T-0001: Alpha\n\n## Intent\nTest.\n",
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    r_apply = _run_ar(
        ["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(plan_path)],
        env_extra={"AR_FIXED_NOW": "2026-03-02T12:40:00-05:00"},
    )
    assert r_apply.returncode == 0, (r_apply.stdout, r_apply.stderr)

    task_files = sorted([p for p in (run_dir / "10_TASKS").iterdir() if p.is_file() and p.name.startswith("T-0001__")])
    assert len(task_files) == 1
    assert "Alpha" in task_files[0].read_text(encoding="utf-8")

    state = json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))
    t = next(t for t in state["tasks"] if t["task_id"] == "T-0001")
    assert t["status"] == "pending"
    assert t["producers"] == []

    plan_snap_dir = run_dir / "12_SUPERVISOR" / "PLANS"
    assert plan_snap_dir.exists()
    snaps = sorted([p for p in plan_snap_dir.iterdir() if p.is_file() and p.name.endswith(".json")])
    assert snaps, "expected plan snapshot to be saved"

    events = _read_log_events(run_dir)
    assert any(e.get("event") == "task_generation" for e in events)


def test_apply_plan_is_idempotent_when_reapplied(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    plan = {
        "schema_version": 1,
        "generated_at": "2026-03-02T12:40:00-05:00",
        "orchestrator": {"runner": "gemini_cli", "model": "", "reasoning_effort": "", "notes": ""},
        "actions": [
            {
                "type": "create_task",
                "task_id": "T-0001",
                "slug": "alpha",
                "reason": "",
                "task_markdown": "# Task T-0001: Alpha\n\n## Intent\nTest.\n",
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    r_apply_1 = _run_ar(
        ["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(plan_path)],
        env_extra={"AR_FIXED_NOW": "2026-03-02T12:40:00-05:00"},
    )
    assert r_apply_1.returncode == 0, (r_apply_1.stdout, r_apply_1.stderr)

    r_apply_2 = _run_ar(
        ["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(plan_path)],
        env_extra={"AR_FIXED_NOW": "2026-03-02T12:41:00-05:00"},
    )
    assert r_apply_2.returncode == 0, (r_apply_2.stdout, r_apply_2.stderr)
    assert "idempotent" in r_apply_2.stdout

    task_files = sorted([p for p in (run_dir / "10_TASKS").iterdir() if p.is_file() and p.name.startswith("T-0001__")])
    assert len(task_files) == 1

    state = json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))
    assert len([t for t in state["tasks"] if t.get("task_id") == "T-0001"]) == 1


def test_apply_plan_rejects_conflicting_existing_task(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    existing = run_dir / "10_TASKS" / "T-0001__existing.md"
    existing.write_text("# Task T-0001: Existing\n\nDifferent.\n", encoding="utf-8")

    plan = {
        "schema_version": 1,
        "generated_at": "2026-03-02T12:40:00-05:00",
        "orchestrator": {"runner": "claude_code", "model": "", "reasoning_effort": "", "notes": ""},
        "actions": [
            {
                "type": "create_task",
                "task_id": "T-0001",
                "slug": "alpha",
                "reason": "",
                "task_markdown": "# Task T-0001: Alpha\n\n## Intent\nTest.\n",
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    r_apply = _run_ar(
        ["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(plan_path)],
        env_extra={"AR_FIXED_NOW": "2026-03-02T12:40:00-05:00"},
    )
    assert r_apply.returncode == 2
    assert "task already exists" in (r_apply.stdout + r_apply.stderr)
