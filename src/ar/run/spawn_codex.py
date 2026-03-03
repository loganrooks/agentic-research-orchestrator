from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO


_STALL_SECONDS_DEFAULT = 5 * 60


@dataclass(frozen=True)
class TokenUsage:
    input: int | None
    cached_input: int | None
    output: int | None
    reasoning: int | None
    total: int | None


@dataclass
class _Heartbeat:
    lock: threading.Lock
    last_seen_monotonic: float
    last_event_timestamp: str
    token_usage: TokenUsage | None


@dataclass(frozen=True)
class SpawnCodexInputs:
    run_dir: Path
    tasks: list[str]
    max_workers: int
    timeout_seconds: int
    model: str
    reasoning: str
    sandbox: str
    resume: bool
    fail_fast: bool


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    producer_id: str
    status: str  # ok|failed|timeout|partial
    exit_code: int | None
    started_at: str
    finished_at: str
    elapsed_seconds: float
    token_usage: TokenUsage
    exceptions: list[dict[str, str]]


def _now_local() -> datetime:
    fixed = os.environ.get("AR_FIXED_NOW", "").strip()
    if fixed:
        dt = datetime.fromisoformat(fixed)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone()
    return datetime.now().astimezone()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_log(run_dir: Path, event: dict[str, object], *, lock: threading.Lock) -> None:
    line = json.dumps(event, ensure_ascii=True) + "\n"
    log_path = run_dir / "LOG.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)


def _task_id_from_filename(name: str) -> str | None:
    # Expected: T-0001__slug.md
    if not name.startswith("T-"):
        return None
    head = name.split("__", 1)[0]
    if len(head) < 3:
        return None
    return head


def _iter_task_files(run_dir: Path) -> list[Path]:
    tasks_dir = run_dir / "10_TASKS"
    if not tasks_dir.exists():
        return []
    out: list[Path] = []
    for p in sorted(tasks_dir.iterdir()):
        if not p.is_file() or not p.name.endswith(".md"):
            continue
        if _task_id_from_filename(p.name) is None:
            continue
        out.append(p)
    return out


def _load_config_defaults(run_dir: Path) -> dict[str, Any]:
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


def _build_inputs(args: object) -> SpawnCodexInputs:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()

    cfg_codex = _load_config_defaults(run_dir)

    tasks = [str(x).strip() for x in (getattr(args, "task", []) or []) if str(x).strip()]
    max_workers = int(getattr(args, "max_workers", 0) or 0) or int(cfg_codex.get("max_workers") or 0) or 3
    timeout_seconds = int(getattr(args, "timeout_seconds", 0) or 0) or int(cfg_codex.get("timeout_seconds") or 0) or 1800
    model = str(getattr(args, "model", "")).strip() or str(cfg_codex.get("model_default") or "gpt-5.2")
    reasoning = str(getattr(args, "reasoning", "")).strip() or str(cfg_codex.get("reasoning_default") or "high")
    sandbox = str(getattr(args, "sandbox", "")).strip() or str(cfg_codex.get("sandbox_default") or "read-only")
    resume = bool(getattr(args, "resume", True))
    fail_fast = bool(getattr(args, "fail_fast", False))

    return SpawnCodexInputs(
        run_dir=run_dir,
        tasks=tasks,
        max_workers=max_workers,
        timeout_seconds=timeout_seconds,
        model=model,
        reasoning=reasoning,
        sandbox=sandbox,
        resume=resume,
        fail_fast=fail_fast,
    )


def parse_token_usage_from_codex_events(events_path: Path) -> TokenUsage:
    """
    Extract total token usage from a Codex `--json` events stream.

    Returns TokenUsage with all fields possibly None if no token_count event exists.
    """

    last: TokenUsage | None = None
    try:
        with events_path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue

                # Common shape:
                # {"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{...}}}}
                payload = obj.get("payload")
                if obj.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
                    info = payload.get("info")
                    if not isinstance(info, dict):
                        continue
                    tu = info.get("total_token_usage") or info.get("last_token_usage")
                    if isinstance(tu, dict):
                        last = TokenUsage(
                            input=_as_int_or_none(tu.get("input_tokens")),
                            cached_input=_as_int_or_none(tu.get("cached_input_tokens")),
                            output=_as_int_or_none(tu.get("output_tokens")),
                            reasoning=_as_int_or_none(tu.get("reasoning_output_tokens")),
                            total=_as_int_or_none(tu.get("total_tokens")),
                        )
                        continue

                # Alternative possible shape: {"type":"token_count","token_usage":{...}}
                if obj.get("type") == "token_count":
                    tu = obj.get("token_usage") or obj.get("total_token_usage")
                    if isinstance(tu, dict):
                        last = TokenUsage(
                            input=_as_int_or_none(tu.get("input") or tu.get("input_tokens")),
                            cached_input=_as_int_or_none(tu.get("cached_input") or tu.get("cached_input_tokens")),
                            output=_as_int_or_none(tu.get("output") or tu.get("output_tokens")),
                            reasoning=_as_int_or_none(tu.get("reasoning") or tu.get("reasoning_output_tokens")),
                            total=_as_int_or_none(tu.get("total") or tu.get("total_tokens")),
                        )
                        continue
    except FileNotFoundError:
        last = None

    return last or TokenUsage(input=None, cached_input=None, output=None, reasoning=None, total=None)


def _as_int_or_none(v: object) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return int(s)
        except Exception:
            return None
    return None


def _load_state(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))


def _update_state_for_task(
    run_dir: Path,
    task_id: str,
    *,
    status: str | None = None,
    add_producer: str | None = None,
    lock: threading.Lock,
) -> None:
    with lock:
        state = _load_state(run_dir)
        tasks = state.get("tasks")
        if not isinstance(tasks, list):
            tasks = []
            state["tasks"] = tasks

        row = None
        for t in tasks:
            if isinstance(t, dict) and t.get("task_id") == task_id:
                row = t
                break

        if row is None:
            row = {"task_id": task_id, "status": "pending", "producers": []}
            tasks.append(row)

        if status:
            row["status"] = status

        producers = row.get("producers")
        if not isinstance(producers, list):
            producers = []
            row["producers"] = producers
        if add_producer and add_producer not in producers:
            producers.append(add_producer)

        _atomic_write_json(run_dir / "STATE.json", state)


def _set_state_run_status(run_dir: Path, *, status: str, current_step: str, lock: threading.Lock) -> None:
    with lock:
        state = _load_state(run_dir)
        state["status"] = status
        state["current_step"] = current_step
        _atomic_write_json(run_dir / "STATE.json", state)


def _iter_codex_producer_dirs(task_dir: Path) -> list[Path]:
    if not task_dir.exists():
        return []
    out: list[Path] = []
    for p in sorted([x for x in task_dir.iterdir() if x.is_dir()]):
        if p.name.startswith("codex:"):
            out.append(p)
    return out


def _has_ok_provenance(producer_dir: Path) -> bool:
    prov = producer_dir / "PROVENANCE.json"
    if not prov.exists():
        return False
    try:
        obj = json.loads(prov.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    return obj.get("status") == "ok"


def _pick_next_worker_id(task_dir: Path) -> str:
    # codex:worker-01, codex:worker-02, ...
    existing = _iter_codex_producer_dirs(task_dir)
    n = 1
    if existing:
        for p in existing:
            if not p.name.startswith("codex:worker-"):
                continue
            tail = p.name.split("codex:worker-", 1)[1]
            try:
                num = int(tail)
            except Exception:
                continue
            n = max(n, num + 1)
    return f"codex:worker-{n:02d}"


def _build_codex_prompt(task_id: str, task_text: str) -> str:
    return (
        f"# Codex Worker Task ({task_id})\n\n"
        "You are a research worker producing artifacts for a run bundle on disk.\n\n"
        "## Output requirements\n"
        "- Output one primary markdown report (with citations/links where possible).\n"
        "- Include a `Residuals / Open Questions` section.\n"
        "- Prefer JSON registers in fenced code blocks; table fallback is acceptable.\n\n"
        "SOURCES.json:\n"
        "```json\n"
        "[]\n"
        "```\n\n"
        "CLAIMS.json:\n"
        "```json\n"
        "[]\n"
        "```\n\n"
        "---\n\n"
        "## Canonical task\n\n"
        f"{task_text.strip()}\n"
    )


def _build_codex_exec_cmd(*, model: str, reasoning: str, sandbox: str, last_message_path: Path) -> list[str]:
    # Use explicit overrides to avoid relying on ~/.codex/config.toml.
    # NOTE: Codex config uses `model_reasoning_effort` (see ~/.codex/config.toml).
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


def _drain_stream_to_file(
    stream: TextIO,
    out_path: Path,
    *,
    heartbeat: _Heartbeat | None = None,
    also_parse_tokens: bool = False,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as out_f:
        for raw in stream:
            out_f.write(raw)
            out_f.flush()
            if heartbeat is None:
                continue
            now_m = time.monotonic()
            with heartbeat.lock:
                heartbeat.last_seen_monotonic = now_m
            if not also_parse_tokens:
                continue
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            ts = obj.get("timestamp")
            if isinstance(ts, str) and ts:
                with heartbeat.lock:
                    heartbeat.last_event_timestamp = ts
            payload = obj.get("payload")
            if obj.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
                info = payload.get("info")
                if not isinstance(info, dict):
                    continue
                tu = info.get("total_token_usage") or info.get("last_token_usage")
                if not isinstance(tu, dict):
                    continue
                usage = TokenUsage(
                    input=_as_int_or_none(tu.get("input_tokens")),
                    cached_input=_as_int_or_none(tu.get("cached_input_tokens")),
                    output=_as_int_or_none(tu.get("output_tokens")),
                    reasoning=_as_int_or_none(tu.get("reasoning_output_tokens")),
                    total=_as_int_or_none(tu.get("total_tokens")),
                )
                with heartbeat.lock:
                    heartbeat.token_usage = usage


def _extract_labeled_json_array(text: str, label: str) -> list[Any] | None:
    lines = text.splitlines()
    want = label.strip()
    for i, line in enumerate(lines):
        if line.strip() != want:
            continue
        # Find next fenced code block
        j = i + 1
        while j < len(lines) and not lines[j].lstrip().startswith("```"):
            j += 1
        if j >= len(lines):
            return None
        if lines[j].strip() not in ("```json", "```JSON", "```jsonc", "```JSONC"):
            return None
        k = j + 1
        buf: list[str] = []
        while k < len(lines) and lines[k].strip() != "```":
            buf.append(lines[k])
            k += 1
        if k >= len(lines):
            return None
        raw_json = "\n".join(buf).strip()
        try:
            obj = json.loads(raw_json)
        except Exception:
            return None
        if isinstance(obj, list):
            return obj
        return None
    return None


def _extract_residuals_section(md: str) -> str | None:
    lines = md.splitlines()
    start = None
    for i, line in enumerate(lines):
        s = line.strip().lower()
        if s.startswith("#") and ("residual" in s or "open question" in s):
            start = i
            break
    if start is None:
        return None
    out: list[str] = []
    for line in lines[start:]:
        if out and line.strip().startswith("#"):
            break
        out.append(line)
    text = "\n".join(out).strip()
    return (text + "\n") if text else None


def _write_placeholder_registers(producer_dir: Path) -> None:
    for rel in ("SOURCES.json", "CLAIMS.json"):
        p = producer_dir / rel
        if not p.exists():
            p.write_text("[]\n", encoding="utf-8")
    rp = producer_dir / "RESIDUALS.md"
    if not rp.exists():
        rp.write_text("none\n", encoding="utf-8")


def _run_one_task(
    run_dir: Path,
    task_id: str,
    task_file: Path,
    *,
    model: str,
    reasoning: str,
    sandbox: str,
    timeout_seconds: int,
    log_lock: threading.Lock,
) -> TaskResult:
    started_dt = _now_local()
    started_at = started_dt.isoformat(timespec="seconds")
    started_m = time.monotonic()

    task_dir = run_dir / "20_WORK" / task_id
    producer_id = _pick_next_worker_id(task_dir)
    producer_dir = task_dir / producer_id
    producer_dir.mkdir(parents=True, exist_ok=True)

    events_path = producer_dir / "EVENTS.jsonl"
    stderr_path = producer_dir / "STDERR.log"
    last_message_path = producer_dir / "LAST_MESSAGE.txt"

    hb = _Heartbeat(lock=threading.Lock(), last_seen_monotonic=time.monotonic(), last_event_timestamp="", token_usage=None)

    exceptions: list[dict[str, str]] = []
    status = "failed"
    exit_code: int | None = None

    prompt = _build_codex_prompt(task_id, task_file.read_text(encoding="utf-8"))

    cmd = _build_codex_exec_cmd(model=model, reasoning=reasoning, sandbox=sandbox, last_message_path=last_message_path)

    proc: subprocess.Popen[str] | None = None
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=run_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None

        proc.stdin.write(prompt)
        proc.stdin.close()

        stdout_thread = threading.Thread(
            target=_drain_stream_to_file,
            args=(proc.stdout, events_path),
            kwargs={"heartbeat": hb, "also_parse_tokens": True},
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_drain_stream_to_file,
            args=(proc.stderr, stderr_path),
            kwargs={},
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        stalled_logged = False
        while True:
            try:
                exit_code = proc.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                pass

            elapsed = time.monotonic() - started_m
            if elapsed > float(timeout_seconds):
                exceptions.append(
                    {"what": "timeout", "why": f"exceeded {timeout_seconds}s", "impact": "task marked timeout"}
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
                break

            with hb.lock:
                idle = time.monotonic() - hb.last_seen_monotonic
                last_ts = hb.last_event_timestamp
            if idle > _STALL_SECONDS_DEFAULT and not stalled_logged:
                _append_log(
                    run_dir,
                    {
                        "ts": _now_local().isoformat(timespec="seconds"),
                        "level": "warn",
                        "event": "stalled_worker",
                        "data": {"task_id": task_id, "producer_id": producer_id, "idle_seconds": int(idle), "last_event_ts": last_ts},
                    },
                    lock=log_lock,
                )
                stalled_logged = True

        if status != "timeout":
            status = "ok" if exit_code == 0 else "failed"
    except FileNotFoundError:
        exceptions.append({"what": "codex_not_found", "why": "codex executable missing", "impact": "task failed"})
        status = "failed"
    except Exception as e:
        exceptions.append({"what": "spawn_error", "why": str(e), "impact": "task failed"})
        status = "failed"
    finally:
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        if stdout_thread:
            stdout_thread.join(timeout=2.0)
        if stderr_thread:
            stderr_thread.join(timeout=2.0)

    finished_dt = _now_local()
    finished_at = finished_dt.isoformat(timespec="seconds")
    elapsed_seconds = float(time.monotonic() - started_m)

    # Write REPORT.md and registers derived from the last message (when possible).
    report_path = producer_dir / "REPORT.md"
    last_message = ""
    if last_message_path.exists():
        try:
            last_message = last_message_path.read_text(encoding="utf-8")
        except Exception as e:
            exceptions.append({"what": "read_last_message_failed", "why": str(e), "impact": "report may be missing"})

    if not last_message:
        # Ensure required artifacts exist even on failures/timeouts.
        last_message = f"(no last message captured; status={status}; exit_code={exit_code})\n"
        if not last_message_path.exists():
            last_message_path.write_text(last_message, encoding="utf-8")

    report_path.write_text(last_message, encoding="utf-8")

    # Ensure optional debug artifacts exist.
    if not events_path.exists():
        events_path.write_text("", encoding="utf-8")
    if not stderr_path.exists():
        stderr_path.write_text("", encoding="utf-8")

    if last_message:
        if not (producer_dir / "SOURCES.json").exists():
            sources = _extract_labeled_json_array(last_message, "SOURCES.json:")
            if sources is not None:
                (producer_dir / "SOURCES.json").write_text(
                    json.dumps(sources, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
                )
            else:
                exceptions.append(
                    {"what": "sources_parse_failed", "why": "missing or invalid SOURCES.json block", "impact": "empty sources"}
                )
                (producer_dir / "SOURCES.json").write_text("[]\n", encoding="utf-8")

        if not (producer_dir / "CLAIMS.json").exists():
            claims = _extract_labeled_json_array(last_message, "CLAIMS.json:")
            if claims is not None:
                (producer_dir / "CLAIMS.json").write_text(
                    json.dumps(claims, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
                )
            else:
                exceptions.append(
                    {"what": "claims_parse_failed", "why": "missing or invalid CLAIMS.json block", "impact": "empty claims"}
                )
                (producer_dir / "CLAIMS.json").write_text("[]\n", encoding="utf-8")

        if not (producer_dir / "RESIDUALS.md").exists():
            residuals = _extract_residuals_section(last_message)
            if residuals:
                (producer_dir / "RESIDUALS.md").write_text(residuals, encoding="utf-8")
            else:
                exceptions.append(
                    {"what": "residuals_extract_failed", "why": "no residuals heading found", "impact": "residuals placeholder"}
                )
                (producer_dir / "RESIDUALS.md").write_text("none\n", encoding="utf-8")

    _write_placeholder_registers(producer_dir)

    token_usage = hb.token_usage or parse_token_usage_from_codex_events(events_path)
    if token_usage is None:
        token_usage = TokenUsage(input=None, cached_input=None, output=None, reasoning=None, total=None)

    prov = {
        "producer_id": producer_id,
        "runner": "codex",
        "model": model,
        "reasoning_effort": reasoning,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "status": status,
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
    _atomic_write_json(producer_dir / "PROVENANCE.json", prov)

    return TaskResult(
        task_id=task_id,
        producer_id=producer_id,
        status=status,
        exit_code=exit_code,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_seconds=elapsed_seconds,
        token_usage=token_usage,
        exceptions=exceptions,
    )


def run_spawn_codex(args: object) -> int:
    try:
        inp = _build_inputs(args)
    except Exception as e:
        sys.stderr.write(f"[ERROR] invalid spawn-codex args: {e}\n")
        return 20

    if not inp.run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {inp.run_dir}\n")
        return 20

    if not (inp.run_dir / "STATE.json").exists():
        sys.stderr.write(f"[ERROR] missing STATE.json: {inp.run_dir}\n")
        return 20

    if shutil.which("codex") is None:
        sys.stderr.write("[ERROR] codex executable not found on PATH\n")
        return 20

    task_files = _iter_task_files(inp.run_dir)
    if not task_files:
        sys.stderr.write(f"[ERROR] no tasks found under {inp.run_dir / '10_TASKS'}\n")
        return 20

    tasks_by_id: dict[str, Path] = {}
    for p in task_files:
        tid = _task_id_from_filename(p.name)
        if tid:
            tasks_by_id[tid] = p

    selected: list[str]
    if inp.tasks:
        selected = []
        for t in inp.tasks:
            if t not in tasks_by_id:
                sys.stderr.write(f"[ERROR] requested task not found: {t}\n")
                return 20
            selected.append(t)
    else:
        selected = sorted(tasks_by_id.keys())

    state_lock = threading.Lock()
    log_lock = threading.Lock()

    # Resume: skip tasks that already have an ok codex producer.
    if inp.resume:
        keep: list[str] = []
        for tid in selected:
            task_dir = inp.run_dir / "20_WORK" / tid
            ok_found = False
            ok_pid = ""
            for pdir in _iter_codex_producer_dirs(task_dir):
                if _has_ok_provenance(pdir):
                    ok_found = True
                    ok_pid = pdir.name
                    break
            if ok_found:
                sys.stdout.write(f"[SKIP] {tid} (already has ok codex output)\n")
                _update_state_for_task(inp.run_dir, tid, status="done", add_producer=ok_pid, lock=state_lock)
                continue
            keep.append(tid)
        selected = keep

    if not selected:
        sys.stdout.write("[OK] nothing to do\n")
        return 0

    _set_state_run_status(inp.run_dir, status="running", current_step="spawn-codex", lock=state_lock)

    now = _now_local()
    _append_log(
        inp.run_dir,
        {
            "ts": now.isoformat(timespec="seconds"),
            "level": "info",
            "event": "spawn_codex_started",
            "data": {
                "tasks": selected,
                "max_workers": inp.max_workers,
                "timeout_seconds": inp.timeout_seconds,
                "model": inp.model,
                "reasoning_effort": inp.reasoning,
                "sandbox": inp.sandbox,
                "resume": inp.resume,
                "fail_fast": inp.fail_fast,
            },
        },
        lock=log_lock,
    )

    results: list[TaskResult] = []
    failure_seen = False

    # Simple worker pool using threads (each task spawns its own `codex exec` process).
    pending = list(selected)
    active: list[threading.Thread] = []
    active_results: list[TaskResult | None] = []

    def _thread_target(idx: int, task_id: str) -> None:
        nonlocal active_results
        task_file = tasks_by_id[task_id]
        _update_state_for_task(inp.run_dir, task_id, status="running", lock=state_lock)
        r = _run_one_task(
            inp.run_dir,
            task_id,
            task_file,
            model=inp.model,
            reasoning=inp.reasoning,
            sandbox=inp.sandbox,
            timeout_seconds=inp.timeout_seconds,
            log_lock=log_lock,
        )
        _update_state_for_task(inp.run_dir, task_id, status="done" if r.status == "ok" else "failed", add_producer=r.producer_id, lock=state_lock)
        active_results[idx] = r

    while pending or active:
        while pending and len(active) < inp.max_workers and not (inp.fail_fast and failure_seen):
            tid = pending.pop(0)
            active_results.append(None)
            idx = len(active_results) - 1
            t = threading.Thread(target=_thread_target, args=(idx, tid), daemon=True)
            active.append(t)
            t.start()

        # Poll for completed threads.
        still_active: list[threading.Thread] = []
        for t in active:
            t.join(timeout=0.1)
            if t.is_alive():
                still_active.append(t)
        active = still_active

        # Collect finished results.
        done_now: list[int] = []
        for i, r in enumerate(active_results):
            if r is not None:
                done_now.append(i)
        for i in sorted(done_now, reverse=True):
            r = active_results.pop(i)
            assert r is not None
            results.append(r)
            if r.status != "ok":
                failure_seen = True
                if inp.fail_fast:
                    pending.clear()

    # Final log + exit code.
    ok = [r for r in results if r.status == "ok"]
    bad = [r for r in results if r.status != "ok"]
    _append_log(
        inp.run_dir,
        {
            "ts": _now_local().isoformat(timespec="seconds"),
            "level": "info" if not bad else "warn",
            "event": "spawn_codex_finished",
            "data": {"ok": len(ok), "failed": len(bad)},
        },
        lock=log_lock,
    )

    if bad:
        _set_state_run_status(inp.run_dir, status="partial", current_step="spawn-codex", lock=state_lock)
        sys.stdout.write(f"[WARN] spawn complete: ok={len(ok)} failed={len(bad)}\n")
        return 10

    sys.stdout.write(f"[OK] spawn complete: ok={len(ok)}\n")
    return 0
