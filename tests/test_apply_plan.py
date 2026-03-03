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
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "ar", *args],
        env=env,
        input=stdin,
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


def test_apply_plan_creates_tasks_and_updates_state(tmp_path: Path) -> None:
    # Use a timezone-less fixed timestamp to avoid locale conversion differences.
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56", "AR_FIXED_RUN_ID": "abcdef1234"}
    run_dir = _scaffold_run_dir(tmp_path, env_fixed=env_fixed)

    plan = {
        "schema_version": 1,
        "generated_at": "2026-03-02T12:34:56",
        "orchestrator": {"runner": "codex"},
        "actions": [
            {
                "type": "create_task",
                "task_id": "T-0001",
                "slug": "alpha",
                "reason": "test",
                "task_markdown": "# Task T-0001: Alpha\n\nDo A.\n",
            },
            {
                "type": "create_task",
                "task_id": "T-0002",
                "slug": "beta",
                "reason": "test",
                "task_markdown": "# Task T-0002: Beta\n\nDo B.\n",
            },
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    r_apply = _run_ar(
        ["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(plan_path)],
        env_extra=env_fixed,
    )
    assert r_apply.returncode == 0, (r_apply.stdout, r_apply.stderr)

    tasks_dir = run_dir / "10_TASKS"
    expected_t1 = (tasks_dir / "T-0001__alpha.md").resolve()
    expected_t2 = (tasks_dir / "T-0002__beta.md").resolve()
    created_paths = [Path(x).resolve() for x in r_apply.stdout.splitlines() if x.strip()]
    assert created_paths == [expected_t1, expected_t2]

    assert expected_t1.read_text(encoding="utf-8") == "# Task T-0001: Alpha\n\nDo A.\n"
    assert expected_t2.read_text(encoding="utf-8") == "# Task T-0002: Beta\n\nDo B.\n"

    state = json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))
    assert state["current_step"] == "apply-plan"
    task_rows = {t["task_id"]: t for t in state["tasks"]}
    assert task_rows["T-0001"]["status"] == "pending"
    assert task_rows["T-0001"]["producers"] == []
    assert task_rows["T-0002"]["status"] == "pending"
    assert task_rows["T-0002"]["producers"] == []

    # Plan snapshot is stored for compaction-safe provenance.
    plan_snapshot = run_dir / "12_SUPERVISOR" / "PLANS" / "PLAN_20260302T123456__codex.json"
    assert plan_snapshot.exists()


def test_apply_plan_idempotent_apply_skips_identical(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56", "AR_FIXED_RUN_ID": "abcdef1234"}
    run_dir = _scaffold_run_dir(tmp_path, env_fixed=env_fixed)

    plan = {
        "schema_version": 1,
        "orchestrator": {"runner": "codex"},
        "actions": [
            {
                "type": "create_task",
                "task_id": "T-0001",
                "slug": "alpha",
                "reason": "",
                "task_markdown": "# Task T-0001: Alpha\n\nDo A.\n",
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    r1 = _run_ar(["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(plan_path)], env_extra=env_fixed)
    assert r1.returncode == 0, (r1.stdout, r1.stderr)
    r2 = _run_ar(["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(plan_path)], env_extra=env_fixed)
    assert r2.returncode == 0, (r2.stdout, r2.stderr)
    assert "[OK] no tasks created (idempotent apply)" in r2.stdout


def test_apply_plan_conflict_fails_without_partial_writes(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56", "AR_FIXED_RUN_ID": "abcdef1234"}
    run_dir = _scaffold_run_dir(tmp_path, env_fixed=env_fixed)

    tasks_dir = run_dir / "10_TASKS"
    existing = tasks_dir / "T-0001__already.md"
    existing.write_text("# Task T-0001: Already\n\nDifferent.\n", encoding="utf-8")

    plan = {
        "schema_version": 1,
        "orchestrator": {"runner": "codex"},
        "actions": [
            {
                "type": "create_task",
                "task_id": "T-0001",
                "slug": "alpha",
                "reason": "",
                "task_markdown": "# Task T-0001: Alpha\n\nDo A.\n",
            },
            {
                "type": "create_task",
                "task_id": "T-0002",
                "slug": "beta",
                "reason": "",
                "task_markdown": "# Task T-0002: Beta\n\nDo B.\n",
            },
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    r_apply = _run_ar(
        ["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(plan_path)],
        env_extra=env_fixed,
    )
    assert r_apply.returncode == 2
    assert "task already exists for T-0001" in (r_apply.stdout + r_apply.stderr)

    # No other tasks should have been written.
    assert not (tasks_dir / "T-0002__beta.md").exists()
    assert existing.read_text(encoding="utf-8") == "# Task T-0001: Already\n\nDifferent.\n"

    # STATE.json should not be mutated on failure.
    state = json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))
    assert state["tasks"] == []


def test_apply_plan_rejects_invalid_schema(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56", "AR_FIXED_RUN_ID": "abcdef1234"}
    run_dir = _scaffold_run_dir(tmp_path, env_fixed=env_fixed)

    bad_plan_path = tmp_path / "bad_plan.json"
    bad_plan_path.write_text(json.dumps({"schema_version": 2, "actions": []}) + "\n", encoding="utf-8")

    r_apply = _run_ar(
        ["run", "apply-plan", "--run-dir", str(run_dir), "--plan-path", str(bad_plan_path)],
        env_extra=env_fixed,
    )
    assert r_apply.returncode == 2
    assert "invalid plan" in (r_apply.stdout + r_apply.stderr).lower()

