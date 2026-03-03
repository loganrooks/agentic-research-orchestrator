from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from collections import deque
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..run.apply_plan import run_apply_plan
from ..run.export_orchestrator_prompt import ExportOrchestratorPromptInputs, _render_prompt
from ..run.merge import run_merge
from ..run.propose_followups import run_propose_followups
from ..run.spawn_codex import run_spawn_codex
from ..run.validate import (
    ValidationFinding,
    _iter_producer_dirs,
    _validate_merge_outputs,
    _validate_producer_dir,
    _validate_required_runner_presence,
    _validate_run_structure,
)


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _resolved_within(base: Path, path: Path) -> bool:
    base_r = base.resolve()
    path_r = path.resolve()
    return path_r == base_r or base_r in path_r.parents


def _require_safe_subpath(run_dir: Path, rel: str) -> None:
    p = (run_dir / rel)
    if p.exists():
        # Hard fail on symlinks: a symlinked 10_TASKS -> /tmp/elsewhere would escape confinement.
        if p.is_symlink():
            raise ValueError(f"unsafe symlink path: {p}")
        if not _resolved_within(run_dir, p):
            raise ValueError(f"unsafe path escape: {p} resolves outside run_dir")


def _assert_run_dir_safe_for_writes(run_dir: Path) -> None:
    # These are the main write targets for v1 tools.
    for rel in ["10_TASKS", "20_WORK", "30_MERGE", "12_SUPERVISOR", "STATE.json", "LOG.jsonl"]:
        _require_safe_subpath(run_dir, rel)


def _tail_lines(path: Path, n: int) -> list[str]:
    if n <= 0:
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            buf = b""
            block = 4096
            while end > 0 and buf.count(b"\n") <= n:
                step = block if end >= block else end
                end -= step
                f.seek(end)
                buf = f.read(step) + buf
        lines = buf.splitlines()[-n:]
        return [ln.decode("utf-8", errors="replace") for ln in lines]
    except FileNotFoundError:
        return []


def _status_snapshot(run_dir: Path) -> str:
    state_path = run_dir / "STATE.json"
    cfg_path = run_dir / "01_CONFIG.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    cfg: dict[str, Any] = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    lines: list[str] = []
    lines.append(f"run_dir: {run_dir}")
    if cfg.get("run_id"):
        lines.append(f"run_id: {cfg.get('run_id')}")
    lines.append(f"status: {state.get('status')}")
    lines.append(f"current_step: {state.get('current_step')}")
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    lines.append(f"tasks: {len(tasks)}")
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = t.get("task_id", "")
        st = t.get("status", "")
        producers = t.get("producers", [])
        if not isinstance(producers, list):
            producers = []
        lines.append(f"- {tid} [{st}] producers={len(producers)}")
    tail = _tail_lines(run_dir / "LOG.jsonl", 10)
    if tail:
        lines.append("log_tail (last 10):")
        lines.extend([ln.rstrip("\n") for ln in tail])
    return "\n".join(lines).strip() + "\n"


def _validate_readonly(run_dir: Path) -> dict[str, Any]:
    findings: list[ValidationFinding] = []
    findings.extend(_validate_run_structure(run_dir))
    producers = _iter_producer_dirs(run_dir)
    for pdir in producers:
        findings.extend(_validate_producer_dir(pdir))
    findings.extend(_validate_required_runner_presence(run_dir))
    findings.extend(_validate_merge_outputs(run_dir, producers))
    ok = not any(f.severity == "error" for f in findings)
    return {
        "ok": ok,
        "findings": [{"severity": f.severity, "message": f.message, "path": f.path} for f in findings],
    }


def _sanitize_for_log(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in ("plan", "plan_json"):
                if isinstance(v, dict):
                    out[k] = {
                        "schema_version": v.get("schema_version"),
                        "actions": len(v.get("actions") or []) if isinstance(v.get("actions"), list) else None,
                    }
                else:
                    out[k] = "<redacted>"
                continue
            out[k] = _sanitize_for_log(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_for_log(x) for x in obj[:50]]
    if isinstance(obj, str):
        s = obj
        if len(s) > 500:
            return s[:500] + "…"
        return s
    return obj


def _append_mcp_log(run_dir: Path, event: dict[str, Any]) -> None:
    # Intentionally separate from LOG.jsonl (operator run log).
    log_path = run_dir / "12_SUPERVISOR" / "MCP_LOG.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


_EVENT_PREFIX_RE = re.compile(r"[^a-z0-9_]+")


def _safe_event_name(s: str) -> str:
    s = s.strip().lower()
    s = _EVENT_PREFIX_RE.sub("_", s).strip("_")
    return s or "mcp"


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    write: bool
    handler: Callable[[dict[str, Any], bool], dict[str, Any]]


class ArMcpServer:
    def __init__(
        self,
        *,
        write_enabled: bool,
        allowed_run_dir_prefixes: list[Path] | None = None,
        max_calls_per_minute: int = 60,
    ) -> None:
        self.write_enabled = write_enabled
        self.allowed_run_dir_prefixes = [p.expanduser().resolve() for p in (allowed_run_dir_prefixes or []) if str(p).strip()]
        self._call_times: deque[float] = deque()
        self._max_calls_per_minute = max(1, int(max_calls_per_minute))

        self._tools: dict[str, McpTool] = {}
        self._register_tools()

    def _rate_limit(self) -> None:
        now = time.monotonic()
        window = 60.0
        while self._call_times and (now - self._call_times[0]) > window:
            self._call_times.popleft()
        if len(self._call_times) >= self._max_calls_per_minute:
            raise RuntimeError("rate limit exceeded")
        self._call_times.append(now)

    def _resolve_run_dir(self, run_dir_s: str) -> Path:
        run_dir = Path(run_dir_s).expanduser().resolve()
        if self.allowed_run_dir_prefixes:
            ok = any(_resolved_within(prefix, run_dir) for prefix in self.allowed_run_dir_prefixes)
            if not ok:
                raise ValueError("run_dir not allowed by server prefix policy")
        if not run_dir.exists():
            raise FileNotFoundError(str(run_dir))
        return run_dir

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in self._tools.values()
        ]

    def list_prompts(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "orchestrator_prompt",
                "title": "Orchestrator Prompt",
                "description": "Generate a runner-specific orchestrator prompt for a run bundle.",
                "arguments": [
                    {"name": "run_dir", "description": "Run directory path", "required": True},
                    {"name": "runner", "description": "Runner id (e.g., claude_code, gemini_cli)", "required": False},
                    {"name": "profile", "description": "Prompt profile (normal|guided)", "required": False},
                ],
            }
        ]

    def get_prompt(self, name: str, arguments: dict[str, str] | None) -> dict[str, Any]:
        name = name.strip()
        args = arguments or {}

        if name != "orchestrator_prompt":
            raise ValueError(f"unknown prompt: {name}")

        run_dir_s = str(args.get("run_dir") or "").strip()
        if not run_dir_s:
            raise ValueError("missing required argument: run_dir")
        run_dir = self._resolve_run_dir(run_dir_s)

        runner = str(args.get("runner") or "claude_code").strip() or "claude_code"
        profile = str(args.get("profile") or "guided").strip() or "guided"
        if profile not in ("normal", "guided"):
            raise ValueError("profile must be one of: normal, guided")

        inp = ExportOrchestratorPromptInputs(run_dir=run_dir, runner=runner, profile=profile, out_path=run_dir / "_")
        prompt_txt = _render_prompt(inp)
        return {
            "description": "Orchestrator prompt for producing an OrchestratorPlan JSON (schema v1).",
            "messages": [{"role": "user", "content": {"type": "text", "text": prompt_txt}}],
        }

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        self._rate_limit()
        tool = self._tools.get(name)
        if tool is None:
            return {"isError": True, "content": [{"type": "text", "text": f"unknown tool: {name}"}]}

        args = arguments or {}
        run_dir_s = str(args.get("run_dir") or "").strip()
        if not run_dir_s:
            return {"isError": True, "content": [{"type": "text", "text": "missing required argument: run_dir"}]}

        try:
            run_dir = self._resolve_run_dir(run_dir_s)
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"invalid run_dir: {e}"}]}

        event_name = _safe_event_name(name)
        ts = _now_local().isoformat(timespec="seconds")

        # Always log tool calls for auditability (constrained to run_dir).
        try:
            _require_safe_subpath(run_dir, "12_SUPERVISOR")
            _append_mcp_log(
                run_dir,
                {
                    "ts": ts,
                    "event": "mcp_tool_called",
                    "data": {
                        "tool": name,
                        "tool_event": event_name,
                        "write_enabled": self.write_enabled,
                        "args": _sanitize_for_log(args),
                    },
                },
            )
        except Exception:
            pass

        if tool.write and not self.write_enabled:
            return {
                "isError": True,
                "content": [{"type": "text", "text": "write-enabled tools are disabled (start server with --write-enabled)"}],
            }

        if tool.write:
            try:
                _assert_run_dir_safe_for_writes(run_dir)
            except Exception as e:
                return {"isError": True, "content": [{"type": "text", "text": f"unsafe run_dir for writes: {e}"}]}

        try:
            result_obj = tool.handler(args, self.write_enabled)
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"tool error: {e}"}]}

        # Allow handlers to return a full CallToolResult shape directly.
        if isinstance(result_obj, dict) and "content" in result_obj:
            return result_obj

        return {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(result_obj, ensure_ascii=True, indent=2)}],
        }

    def _register_tools(self) -> None:
        self._tools["ar.run.status"] = McpTool(
            name="ar.run.status",
            description="Read-only status snapshot of a run bundle (does not modify LOG.jsonl/STATE.json).",
            input_schema={"type": "object", "properties": {"run_dir": {"type": "string"}}, "required": ["run_dir"]},
            write=False,
            handler=self._tool_status,
        )
        self._tools["ar.run.validate"] = McpTool(
            name="ar.run.validate",
            description="Read-only validation of a run bundle (does not modify LOG.jsonl/STATE.json).",
            input_schema={"type": "object", "properties": {"run_dir": {"type": "string"}}, "required": ["run_dir"]},
            write=False,
            handler=self._tool_validate,
        )
        self._tools["ar.run.export_orchestrator_prompt"] = McpTool(
            name="ar.run.export_orchestrator_prompt",
            description="Return an orchestrator prompt (string) for a runner/profile; does not write files.",
            input_schema={
                "type": "object",
                "properties": {
                    "run_dir": {"type": "string"},
                    "runner": {"type": "string"},
                    "profile": {"type": "string", "enum": ["normal", "guided"]},
                },
                "required": ["run_dir", "runner"],
            },
            write=False,
            handler=self._tool_export_orchestrator_prompt,
        )

        # Write-enabled tools.
        self._tools["ar.run.apply_plan"] = McpTool(
            name="ar.run.apply_plan",
            description="Apply an OrchestratorPlan JSON object to create tasks (write-enabled only).",
            input_schema={
                "type": "object",
                "properties": {"run_dir": {"type": "string"}, "plan": {"type": "object"}, "dry_run": {"type": "boolean"}},
                "required": ["run_dir", "plan"],
            },
            write=True,
            handler=self._tool_apply_plan,
        )
        self._tools["ar.run.merge"] = McpTool(
            name="ar.run.merge",
            description="Run deterministic merge into 30_MERGE/ (write-enabled only).",
            input_schema={
                "type": "object",
                "properties": {"run_dir": {"type": "string"}, "allow_missing_registers": {"type": "boolean"}},
                "required": ["run_dir"],
            },
            write=True,
            handler=self._tool_merge,
        )
        self._tools["ar.run.spawn_codex"] = McpTool(
            name="ar.run.spawn_codex",
            description="Spawn Codex workers for tasks (write-enabled only).",
            input_schema={
                "type": "object",
                "properties": {
                    "run_dir": {"type": "string"},
                    "task": {"type": "array", "items": {"type": "string"}},
                    "max_workers": {"type": "integer"},
                    "timeout_seconds": {"type": "integer"},
                    "model": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "sandbox": {"type": "string"},
                    "resume": {"type": "boolean"},
                    "fail_fast": {"type": "boolean"},
                },
                "required": ["run_dir"],
            },
            write=True,
            handler=self._tool_spawn_codex,
        )
        self._tools["ar.run.propose_followups"] = McpTool(
            name="ar.run.propose_followups",
            description="Propose follow-up tasks via Codex supervisor (requires merge artifacts; write-enabled only).",
            input_schema={
                "type": "object",
                "properties": {
                    "run_dir": {"type": "string"},
                    "model": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "profile": {"type": "string", "enum": ["normal", "guided"]},
                    "sandbox": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "dry_run": {"type": "boolean"},
                },
                "required": ["run_dir"],
            },
            write=True,
            handler=self._tool_propose_followups,
        )

    def _tool_status(self, args: dict[str, Any], _write_enabled: bool) -> dict[str, Any]:
        run_dir = self._resolve_run_dir(str(args.get("run_dir") or ""))
        if not (run_dir / "STATE.json").exists():
            raise FileNotFoundError(str(run_dir / "STATE.json"))
        return {"isError": False, "content": [{"type": "text", "text": _status_snapshot(run_dir)}]}

    def _tool_validate(self, args: dict[str, Any], _write_enabled: bool) -> dict[str, Any]:
        run_dir = self._resolve_run_dir(str(args.get("run_dir") or ""))
        payload = _validate_readonly(run_dir)
        return {"isError": False, "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=True, indent=2)}]}

    def _tool_export_orchestrator_prompt(self, args: dict[str, Any], _write_enabled: bool) -> dict[str, Any]:
        run_dir = self._resolve_run_dir(str(args.get("run_dir") or ""))
        runner = str(args.get("runner") or "").strip()
        profile = str(args.get("profile") or "normal").strip() or "normal"
        if not runner:
            raise ValueError("runner is required")
        inp = ExportOrchestratorPromptInputs(run_dir=run_dir, runner=runner, profile=profile, out_path=run_dir / "_")
        return {"isError": False, "content": [{"type": "text", "text": _render_prompt(inp)}]}

    def _capture_run(self, fn: Callable[[object], int], args_obj: object) -> dict[str, Any]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(args_obj)
        return {"rc": rc, "stdout": out.getvalue(), "stderr": err.getvalue()}

    def _tool_apply_plan(self, args: dict[str, Any], _write_enabled: bool) -> dict[str, Any]:
        run_dir = self._resolve_run_dir(str(args.get("run_dir") or ""))
        plan = args.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("plan must be an object")
        dry_run = bool(args.get("dry_run", False))

        apply_args = type("ApplyArgs", (), {})()
        apply_args.run_dir = str(run_dir)
        apply_args.plan_path = "-"
        apply_args.dry_run = dry_run
        apply_args.source = "mcp:apply-plan"

        saved_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO(json.dumps(plan))
            return self._capture_run(run_apply_plan, apply_args)
        finally:
            sys.stdin = saved_stdin

    def _tool_merge(self, args: dict[str, Any], _write_enabled: bool) -> dict[str, Any]:
        run_dir = self._resolve_run_dir(str(args.get("run_dir") or ""))
        merge_args = type("MergeArgs", (), {})()
        merge_args.run_dir = str(run_dir)
        merge_args.allow_missing_registers = bool(args.get("allow_missing_registers", False))
        return self._capture_run(run_merge, merge_args)

    def _tool_spawn_codex(self, args: dict[str, Any], _write_enabled: bool) -> dict[str, Any]:
        run_dir = self._resolve_run_dir(str(args.get("run_dir") or ""))
        spawn_args = type("SpawnArgs", (), {})()
        spawn_args.run_dir = str(run_dir)
        spawn_args.task = list(args.get("task") or [])
        spawn_args.max_workers = int(args.get("max_workers") or 0)
        spawn_args.timeout_seconds = int(args.get("timeout_seconds") or 0)
        spawn_args.model = str(args.get("model") or "")
        spawn_args.reasoning = str(args.get("reasoning") or "")
        spawn_args.sandbox = str(args.get("sandbox") or "")
        spawn_args.resume = bool(args.get("resume", True))
        spawn_args.fail_fast = bool(args.get("fail_fast", False))
        return self._capture_run(run_spawn_codex, spawn_args)

    def _tool_propose_followups(self, args: dict[str, Any], _write_enabled: bool) -> dict[str, Any]:
        run_dir = self._resolve_run_dir(str(args.get("run_dir") or ""))
        pf_args = type("PfArgs", (), {})()
        pf_args.run_dir = str(run_dir)
        pf_args.model = str(args.get("model") or "")
        pf_args.reasoning = str(args.get("reasoning") or "")
        pf_args.profile = str(args.get("profile") or "guided")
        pf_args.sandbox = str(args.get("sandbox") or "")
        pf_args.timeout_seconds = int(args.get("timeout_seconds") or 0)
        pf_args.dry_run = bool(args.get("dry_run", False))
        return self._capture_run(run_propose_followups, pf_args)


def _json_rpc_response(result: Any, *, id: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _json_rpc_error(message: str, *, id: Any, code: int = -32000, data: Any | None = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": err}


def serve_stdio(server: ArMcpServer) -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if not isinstance(msg, dict):
            continue

        method = msg.get("method")
        if not isinstance(method, str):
            continue
        # Notifications have no id; ignore them.
        msg_id = msg.get("id")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

        if method in ("notifications/initialized", "initialized"):
            continue
        if method == "shutdown":
            if msg_id is not None:
                sys.stdout.write(json.dumps(_json_rpc_response(None, id=msg_id), ensure_ascii=True) + "\n")
                sys.stdout.flush()
            continue
        if method == "exit":
            return 0

        if msg_id is None:
            continue

        try:
            if method == "initialize":
                pv = str(params.get("protocolVersion") or "")
                instructions = (
                    "Tools in this server operate on an agentic research run bundle on disk.\n"
                    "- Prefer read-only tools (`ar.run.status`, `ar.run.validate`) for inspection.\n"
                    "- Write tools (apply/merge/spawn/propose) mutate the run bundle and may run subprocesses.\n"
                    "- Always pass an explicit `run_dir` and keep work confined to that run directory.\n"
                )
                result = {
                    "protocolVersion": pv or "unknown",
                    "serverInfo": {"name": "agentic-research-orchestrator", "version": "0.1.0"},
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "instructions": instructions,
                }
                resp = _json_rpc_response(result, id=msg_id)
            elif method == "tools/list":
                resp = _json_rpc_response({"tools": server.list_tools()}, id=msg_id)
            elif method == "tools/call":
                tool_name = str(params.get("name") or "").strip()
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                resp = _json_rpc_response(server.call_tool(tool_name, arguments), id=msg_id)
            elif method == "prompts/list":
                resp = _json_rpc_response({"prompts": server.list_prompts()}, id=msg_id)
            elif method == "prompts/get":
                prompt_name = str(params.get("name") or "").strip()
                arguments_raw = params.get("arguments")
                arguments: dict[str, str] = {}
                if isinstance(arguments_raw, dict):
                    for k, v in arguments_raw.items():
                        if isinstance(v, str):
                            arguments[str(k)] = v
                        else:
                            arguments[str(k)] = json.dumps(v, ensure_ascii=True)
                try:
                    resp = _json_rpc_response(server.get_prompt(prompt_name, arguments), id=msg_id)
                except ValueError as e:
                    resp = _json_rpc_error(str(e), id=msg_id, code=-32602)
            else:
                resp = _json_rpc_error(f"method not found: {method}", id=msg_id, code=-32601)
        except RuntimeError as e:
            resp = _json_rpc_error(str(e), id=msg_id, code=-32029)
        except Exception as e:
            resp = _json_rpc_error("internal error", id=msg_id, code=-32603, data=str(e))

        sys.stdout.write(json.dumps(resp, ensure_ascii=True) + "\n")
        sys.stdout.flush()

    return 0
