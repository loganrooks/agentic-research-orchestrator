from __future__ import annotations

import sys
from pathlib import Path

from .server import ArMcpServer, serve_stdio


def run_mcp_serve(args: object) -> int:
    write_enabled = bool(getattr(args, "write_enabled", False))
    max_calls_per_minute = int(getattr(args, "max_calls_per_minute", 60) or 60)
    prefixes = [Path(p) for p in (getattr(args, "allow_run_dir_prefix", []) or []) if str(p).strip()]
    server = ArMcpServer(write_enabled=write_enabled, allowed_run_dir_prefixes=prefixes, max_calls_per_minute=max_calls_per_minute)
    try:
        return serve_stdio(server)
    except KeyboardInterrupt:
        sys.stderr.write("[INFO] MCP server stopped\n")
        return 0

