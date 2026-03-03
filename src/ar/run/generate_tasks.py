from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .apply_plan import run_apply_plan
from .export_orchestrator_prompt import ExportOrchestratorPromptInputs, _render_prompt, _slugify
from .spawn_codex import TokenUsage, parse_token_usage_from_codex_events


@dataclass(frozen=True)
class GenerateTasksInputs:
    run_dir: Path
    model: str
    reasoning: str
    profile: str
    sandbox: str
    timeout_seconds: int
    dry_run: bool


def _now_local() -> datetime:
    fixed = os.environ.get("AR_FIXED_NOW", "").strip()
    if fixed:
        dt = datetime.fromisoformat(fixed)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone()
    return datetime.now().astimezone()


def _append_log(run_dir: Path, event: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    log_path = run_dir / "LOG.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _atomic_write_json(path: Path, obj: object, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_codex_defaults(run_dir: Path) -> dict[str, Any]:
    cfg_path = run_dir / "01_CONFIG.json"
    if not cfg_path.exists():
        return {}
    try:
        cfg = _load_json(cfg_path)
    except Exception:
        return {}
    codex = cfg.get("codex")
    if not isinstance(codex, dict):
        return {}
    return codex


def _build_inputs(args: object) -> GenerateTasksInputs:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()

    cfg_codex = _load_codex_defaults(run_dir)

    model = str(getattr(args, "model", "")).strip() or str(cfg_codex.get("model_default") or "gpt-5.2")
    reasoning = str(getattr(args, "reasoning", "")).strip() or str(cfg_codex.get("reasoning_default") or "high")
    profile = str(getattr(args, "profile", "")).strip() or "normal"
    if profile not in ("normal", "guided"):
        raise ValueError("--profile must be one of: normal, guided")
    sandbox = str(getattr(args, "sandbox", "")).strip() or str(cfg_codex.get("sandbox_default") or "read-only")
    timeout_seconds = int(getattr(args, "timeout_seconds", 0) or 0) or int(cfg_codex.get("timeout_seconds") or 0) or 1800
    dry_run = bool(getattr(args, "dry_run", False))

    return GenerateTasksInputs(
        run_dir=run_dir,
        model=model,
        reasoning=reasoning,
        profile=profile,
        sandbox=sandbox,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
    )


def _pick_unique_dir(base: Path) -> Path:
    if not base.exists():
        return base
    n = 2
    while True:
        cand = Path(str(base) + f"__{n:02d}")
        if not cand.exists():
            return cand
        n += 1


def _build_codex_exec_cmd(*, model: str, reasoning: str, sandbox: str, last_message_path: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--model",
        model,
        "--sandbox",
        sandbox,
        "--output-last-message",
        str(last_message_path),
        "-c",
        f'model_reasoning_effort="{reasoning}"',
        "-",
    ]


def _drain_stream_to_file(stream: Any, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as out_f:
        for raw in stream:
            out_f.write(raw)
            out_f.flush()


def _extract_json_object(text: str) -> dict[str, Any]:
    s = text.strip()
    if not s:
        raise ValueError("empty output")
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    decoder = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(s, i)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("could not parse a JSON object from output")


def _augment_plan(plan: dict[str, Any], *, runner: str, model: str, reasoning: str, notes_append: str) -> dict[str, Any]:
    out = dict(plan)
    orch = out.get("orchestrator")
    if not isinstance(orch, dict):
        orch = {}
        out["orchestrator"] = orch
    orch = dict(orch)
    orch["runner"] = runner
    orch["model"] = model
    orch["reasoning_effort"] = reasoning
    prior_notes = str(orch.get("notes") or "").strip()
    combined = (prior_notes + "\n" + notes_append).strip() if prior_notes else notes_append.strip()
    orch["notes"] = combined
    out["orchestrator"] = orch
    if str(out.get("generated_at") or "").strip() in ("", "ISO8601"):
        out["generated_at"] = _now_local().isoformat(timespec="seconds")
    return out


def run_generate_tasks(args: object) -> int:
    event_prefix = str(getattr(args, "event_prefix", "generate_tasks") or "generate_tasks").strip() or "generate_tasks"
    apply_source = str(getattr(args, "apply_source", "generate-tasks") or "generate-tasks").strip() or "generate-tasks"
    session_prefix = str(getattr(args, "session_prefix", "SUPERVISOR") or "SUPERVISOR").strip() or "SUPERVISOR"
    cmd_label = str(getattr(args, "cmd_label", "generate-tasks") or "generate-tasks").strip() or "generate-tasks"

    try:
        inp = _build_inputs(args)
    except Exception as e:
        sys.stderr.write(f"[ERROR] invalid {cmd_label} args: {e}\n")
        return 20

    if not inp.run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {inp.run_dir}\n")
        return 20
    if not (inp.run_dir / "10_TASKS").exists():
        sys.stderr.write(f"[ERROR] missing 10_TASKS/: {inp.run_dir / '10_TASKS'}\n")
        return 20

    now = _now_local()
    ts = now.strftime("%Y%m%dT%H%M%S")
    sessions_root = inp.run_dir / "12_SUPERVISOR" / "SESSIONS"
    session_dir = _pick_unique_dir(sessions_root / f"{session_prefix}_{ts}__codex")

    prompt_path = session_dir / "PROMPT.md"
    events_path = session_dir / "EVENTS.jsonl"
    stderr_path = session_dir / "STDERR.log"
    last_message_path = session_dir / "LAST_MESSAGE.txt"
    provenance_path = session_dir / "PROVENANCE.json"
    plan_path = session_dir / "PLAN.json"

    session_dir.mkdir(parents=True, exist_ok=True)

    prompt = _render_prompt(
        ExportOrchestratorPromptInputs(run_dir=inp.run_dir, runner="codex", profile=inp.profile, out_path=prompt_path)
    )
    prompt_path.write_text(prompt, encoding="utf-8")

    started_dt = _now_local()
    started_at = started_dt.isoformat(timespec="seconds")
    started_m = time.monotonic()

    _append_log(
        inp.run_dir,
        {
            "ts": started_at,
            "level": "info",
            "event": f"{event_prefix}_started",
            "data": {
                "session_dir": str(session_dir),
                "model": inp.model,
                "reasoning_effort": inp.reasoning,
                "profile": inp.profile,
                "sandbox": inp.sandbox,
                "timeout_seconds": inp.timeout_seconds,
                "dry_run": inp.dry_run,
            },
        },
        dry_run=inp.dry_run,
    )

    proc: subprocess.Popen[str] | None = None
    out_thread: threading.Thread | None = None
    err_thread: threading.Thread | None = None
    exit_code: int | None = None
    status = "failed"
    exceptions: list[dict[str, str]] = []
    try:
        cmd = _build_codex_exec_cmd(
            model=inp.model, reasoning=inp.reasoning, sandbox=inp.sandbox, last_message_path=last_message_path
        )
        proc = subprocess.Popen(
            cmd,
            cwd=inp.run_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

        out_thread = threading.Thread(target=_drain_stream_to_file, args=(proc.stdout, events_path), daemon=True)
        err_thread = threading.Thread(target=_drain_stream_to_file, args=(proc.stderr, stderr_path), daemon=True)
        out_thread.start()
        err_thread.start()

        proc.stdin.write(prompt)
        proc.stdin.close()

        try:
            exit_code = proc.wait(timeout=float(inp.timeout_seconds))
        except subprocess.TimeoutExpired:
            exceptions.append(
                {"what": "timeout", "why": f"exceeded {inp.timeout_seconds}s", "impact": "supervisor marked timeout"}
            )
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                exit_code = proc.wait(timeout=5.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
                exit_code = None
            status = "timeout"
        else:
            status = "ok" if exit_code == 0 else "failed"
    except FileNotFoundError:
        exceptions.append({"what": "codex_not_found", "why": "codex executable missing", "impact": "generate-tasks failed"})
        status = "failed"
    except Exception as e:
        exceptions.append({"what": "spawn_error", "why": str(e), "impact": "generate-tasks failed"})
        status = "failed"
    finally:
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        if out_thread:
            out_thread.join(timeout=2.0)
        if err_thread:
            err_thread.join(timeout=2.0)

    finished_dt = _now_local()
    finished_at = finished_dt.isoformat(timespec="seconds")
    elapsed_seconds = float(time.monotonic() - started_m)

    # Ensure expected artifacts exist.
    if not events_path.exists():
        events_path.write_text("", encoding="utf-8")
    if not stderr_path.exists():
        stderr_path.write_text("", encoding="utf-8")
    if not last_message_path.exists():
        last_message_path.write_text("", encoding="utf-8")

    token_usage: TokenUsage = parse_token_usage_from_codex_events(events_path)
    prov = {
        "runner": "codex",
        "model": inp.model,
        "reasoning_effort": inp.reasoning,
        "profile": inp.profile,
        "sandbox": inp.sandbox,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "status": status,
        "exit_code": exit_code,
        "token_usage": {
            "input": token_usage.input,
            "cached_input": token_usage.cached_input,
            "output": token_usage.output,
            "reasoning": token_usage.reasoning,
            "total": token_usage.total,
        },
        "exceptions": exceptions,
        "notes": "",
    }
    _atomic_write_json(provenance_path, prov, dry_run=False)

    if status != "ok":
        _append_log(
            inp.run_dir,
            {
                "ts": finished_at,
                "level": "error",
                "event": f"{event_prefix}_finished",
                "data": {"status": status, "session_dir": str(session_dir)},
            },
            dry_run=inp.dry_run,
        )
        sys.stderr.write(f"[ERROR] {cmd_label} failed (status={status}; session_dir={session_dir})\n")
        return 20

    raw = last_message_path.read_text(encoding="utf-8")
    try:
        plan = _extract_json_object(raw)
    except Exception as e:
        _append_log(
            inp.run_dir,
            {
                "ts": finished_at,
                "level": "error",
                "event": f"{event_prefix}_finished",
                "data": {"status": "invalid_plan", "session_dir": str(session_dir), "error": str(e)},
            },
            dry_run=inp.dry_run,
        )
        sys.stderr.write(f"[ERROR] codex output did not contain a valid JSON plan: {e}\n")
        sys.stderr.write(f"[INFO] see raw output: {last_message_path}\n")
        return 20

    plan = _augment_plan(
        plan,
        runner="codex",
        model=inp.model,
        reasoning=inp.reasoning,
        notes_append=f"supervisor_session_dir={session_dir}",
    )
    plan_path.write_text(json.dumps(plan, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    # Apply via apply-plan using stdin to avoid redundant temp files.
    apply_args = type("ApplyArgs", (), {})()
    apply_args.run_dir = str(inp.run_dir)
    apply_args.plan_path = "-"
    apply_args.dry_run = inp.dry_run
    apply_args.source = apply_source

    saved_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps(plan))
        rc = run_apply_plan(apply_args)
    finally:
        sys.stdin = saved_stdin

    level = "info" if rc == 0 else "error"
    _append_log(
        inp.run_dir,
        {
            "ts": _now_local().isoformat(timespec="seconds"),
            "level": level,
            "event": f"{event_prefix}_finished",
            "data": {"status": "ok" if rc == 0 else "apply_failed", "session_dir": str(session_dir), "apply_rc": rc},
        },
        dry_run=inp.dry_run,
    )

    if rc != 0:
        sys.stderr.write(f"[ERROR] apply-plan failed (rc={rc}); session_dir={session_dir}\n")
        return 20

    sys.stdout.write(f"[OK] {cmd_label} complete (session_dir={session_dir})\n")
    return 0
