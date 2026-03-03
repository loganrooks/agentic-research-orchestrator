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


def _install_fake_codex(bin_dir: Path, *, expect_model: str, expect_reasoning: str, expect_sandbox: str) -> Path:
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
        return 2
    out_last = _get_flag_value("--output-last-message")
    if not out_last:
        return 2

    model = _get_flag_value("--model")
    sandbox = _get_flag_value("--sandbox")
    if model != {expect_model!r}:
        return 2
    if sandbox != {expect_sandbox!r}:
        return 2

    expect_reason = 'model_reasoning_effort="{expect_reasoning}"'
    if expect_reason not in " ".join(argv):
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
                "slug": "followup",
                "reason": "merge conflict follow-up",
                "task_markdown": "# Task T-0001: Followup\\n\\n## Intent\\nTest.\\n"
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


def test_propose_followups_requires_merge_artifacts(tmp_path: Path) -> None:
    env_scaffold = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_scaffold,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    r_prop = _run_ar(["run", "propose-followups", "--run-dir", str(run_dir)])
    assert r_prop.returncode == 20
    assert "requires merge artifacts" in (r_prop.stdout + r_prop.stderr)


def test_propose_followups_runs_and_logs(tmp_path: Path) -> None:
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

    # Precondition for propose-followups.
    (run_dir / "30_MERGE" / "REPORT.md").write_text("# Report\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir, expect_model="gpt-test-model", expect_reasoning="high", expect_sandbox="read-only")
    env_prop = {
        "AR_FIXED_NOW": "2026-03-02T12:35:00-05:00",
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
    }
    r_prop = _run_ar(["run", "propose-followups", "--run-dir", str(run_dir)], env_extra=env_prop)
    assert r_prop.returncode == 0, (r_prop.stdout, r_prop.stderr)

    # Session dir naming makes this distinguishable from generate-tasks.
    sessions_root = run_dir / "12_SUPERVISOR" / "SESSIONS"
    sessions = sorted([p for p in sessions_root.iterdir() if p.is_dir()])
    assert len(sessions) == 1
    assert sessions[0].name.startswith("FOLLOWUPS_")

    prov = json.loads((sessions[0] / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert prov.get("profile") == "guided"

    events = _read_log_events(run_dir)
    assert any(e.get("event") == "propose_followups_started" for e in events)
    assert any(e.get("event") == "propose_followups_finished" for e in events)
    assert any(
        e.get("event") == "task_generation" and e.get("data", {}).get("source") == "propose-followups" for e in events
    )

