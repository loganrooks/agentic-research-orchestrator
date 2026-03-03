from __future__ import annotations

import json
import os
import stat
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


def _install_fake_codex(
    bin_dir: Path, *, expect_model: str, expect_reasoning: str, expect_sandbox: str, plan_task_slug: str
) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    codex_path = bin_dir / "codex"
    code = f"""#!{sys.executable}
import json
import os
import sys

def _get_flag_value(flag: str) -> str:
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            return argv[i + 1]
    return ""

def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] != "exec":
        sys.stderr.write("expected: codex exec ...\\n")
        return 2
    if "--json" not in argv:
        sys.stderr.write("missing --json\\n")
        return 2

    model = _get_flag_value("--model")
    sandbox = _get_flag_value("--sandbox")
    out_last = _get_flag_value("--output-last-message")

    if model != {expect_model!r}:
        sys.stderr.write(f"unexpected --model: {{model}}\\n")
        return 2
    if sandbox != {expect_sandbox!r}:
        sys.stderr.write(f"unexpected --sandbox: {{sandbox}}\\n")
        return 2
    if not out_last:
        sys.stderr.write("missing --output-last-message\\n")
        return 2

    expect_reason = 'model_reasoning_effort="{expect_reasoning}"'
    if expect_reason not in " ".join(argv):
        sys.stderr.write("missing reasoning override (-c model_reasoning_effort=...)\\n")
        return 2

    _prompt = sys.stdin.read()

    event = {{
        "type": "event_msg",
        "payload": {{
            "type": "token_count",
            "info": {{
                "total_token_usage": {{
                    "input_tokens": 1,
                    "cached_input_tokens": 0,
                    "output_tokens": 1,
                    "reasoning_output_tokens": 0,
                    "total_tokens": 2
                }}
            }}
        }}
    }}
    sys.stdout.write(json.dumps(event) + "\\n")
    sys.stdout.flush()

    plan = {{
        "schema_version": 1,
        "generated_at": "ISO8601",
        "orchestrator": {{"runner": "codex", "model": "", "reasoning_effort": "", "notes": ""}},
        "actions": [
            {{
                "type": "create_task",
                "task_id": "T-0001",
                "slug": {plan_task_slug!r},
                "reason": "coverage gap",
                "task_markdown": "# Task T-0001: Alpha\\n\\n## Intent\\nTest.\\n"
            }}
        ]
    }}
    os.makedirs(os.path.dirname(out_last), exist_ok=True)
    with open(out_last, "w", encoding="utf-8") as f:
        f.write(json.dumps(plan))

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
"""
    codex_path.write_text(code, encoding="utf-8")
    codex_path.chmod(codex_path.stat().st_mode | stat.S_IEXEC)
    return codex_path


def test_generate_tasks_end_to_end_creates_tasks_and_session_artifacts(tmp_path: Path) -> None:
    env_scaffold = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
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
            "--codex-model",
            "gpt-test-model",
            "--codex-reasoning",
            "xhigh",
            "--codex-sandbox",
            "read-only",
        ],
        env_extra=env_scaffold,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    bin_dir = tmp_path / "bin"
    _install_fake_codex(
        bin_dir,
        expect_model="gpt-test-model",
        expect_reasoning="xhigh",
        expect_sandbox="read-only",
        plan_task_slug="alpha",
    )
    env_gen = {
        "AR_FIXED_NOW": "2026-03-02T12:35:00-05:00",
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
    }
    r_gen = _run_ar(["run", "generate-tasks", "--run-dir", str(run_dir)], env_extra=env_gen)
    assert r_gen.returncode == 0, (r_gen.stdout, r_gen.stderr)

    task_path = run_dir / "10_TASKS" / "T-0001__alpha.md"
    assert task_path.exists()
    assert "Task T-0001" in task_path.read_text(encoding="utf-8")

    state = json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))
    assert any(t.get("task_id") == "T-0001" for t in state.get("tasks", []))

    sessions_root = run_dir / "12_SUPERVISOR" / "SESSIONS"
    sessions = sorted([p for p in sessions_root.iterdir() if p.is_dir()])
    assert len(sessions) == 1
    session_dir = sessions[0]
    for name in ["PROMPT.md", "EVENTS.jsonl", "STDERR.log", "LAST_MESSAGE.txt", "PROVENANCE.json", "PLAN.json"]:
        assert (session_dir / name).exists()

    prov = json.loads((session_dir / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert prov.get("token_usage", {}).get("total") == 2

    events = _read_log_events(run_dir)
    assert any(e.get("event") == "generate_tasks_started" for e in events)
    assert any(e.get("event") == "task_generation" and e.get("data", {}).get("source") == "generate-tasks" for e in events)
    assert any(e.get("event") == "generate_tasks_finished" for e in events)


def test_generate_tasks_dry_run_does_not_mutate_tasks_state_or_log(tmp_path: Path) -> None:
    env_scaffold = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
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
            "--codex-model",
            "gpt-test-model",
            "--codex-reasoning",
            "high",
            "--codex-sandbox",
            "read-only",
        ],
        env_extra=env_scaffold,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    before_state = (run_dir / "STATE.json").read_text(encoding="utf-8")
    before_log = (run_dir / "LOG.jsonl").read_text(encoding="utf-8")

    bin_dir = tmp_path / "bin"
    _install_fake_codex(
        bin_dir,
        expect_model="gpt-test-model",
        expect_reasoning="high",
        expect_sandbox="read-only",
        plan_task_slug="beta",
    )
    env_gen = {
        "AR_FIXED_NOW": "2026-03-02T12:35:00-05:00",
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
    }
    r_gen = _run_ar(["run", "generate-tasks", "--run-dir", str(run_dir), "--dry-run"], env_extra=env_gen)
    assert r_gen.returncode == 0, (r_gen.stdout, r_gen.stderr)

    task_files = sorted([p for p in (run_dir / "10_TASKS").iterdir() if p.is_file() and p.name.endswith(".md")])
    assert task_files == []
    assert (run_dir / "STATE.json").read_text(encoding="utf-8") == before_state
    assert (run_dir / "LOG.jsonl").read_text(encoding="utf-8") == before_log

    sessions_root = run_dir / "12_SUPERVISOR" / "SESSIONS"
    sessions = sorted([p for p in sessions_root.iterdir() if p.is_dir()])
    assert len(sessions) == 1
