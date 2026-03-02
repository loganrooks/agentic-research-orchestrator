#!/usr/bin/env python3
"""
Extract user messages from Codex session JSONL logs.

Limitations:
- This only reads ~/.codex/sessions/**/*.jsonl (Codex exec / rollout session logs).
- It does NOT have access to arbitrary chat history outside those logs.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ExtractedUserMessage:
    session_file: str
    timestamp: str
    text: str


def _iter_session_files(sessions_root: Path) -> Iterable[Path]:
    # Codex uses nested date dirs: ~/.codex/sessions/YYYY/MM/DD/*.jsonl
    yield from sorted(sessions_root.rglob("*.jsonl"))


def _safe_json_loads(line: str) -> Any | None:
    try:
        return json.loads(line)
    except Exception:
        return None


def _extract_text_from_content(content: Any) -> str:
    """
    payload.content is usually a list of items like:
      {"type":"input_text","text":"..."}
    We concatenate text items in order.
    """
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "input_text":
            t = item.get("text")
            if isinstance(t, str) and t.strip():
                parts.append(t)
    return "\n".join(parts).strip()


def extract_user_messages_from_file(path: Path) -> list[ExtractedUserMessage]:
    out: list[ExtractedUserMessage] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                obj = _safe_json_loads(raw)
                if not isinstance(obj, dict):
                    continue
                if obj.get("type") != "response_item":
                    continue
                payload = obj.get("payload")
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") != "message":
                    continue
                if payload.get("role") != "user":
                    continue

                text = _extract_text_from_content(payload.get("content"))
                if not text:
                    continue
                ts = obj.get("timestamp")
                if not isinstance(ts, str):
                    ts = ""
                out.append(
                    ExtractedUserMessage(
                        session_file=str(path),
                        timestamp=ts,
                        text=text,
                    )
                )
    except FileNotFoundError:
        return []
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract user messages from Codex session logs.")
    ap.add_argument(
        "--sessions-root",
        default=os.path.expanduser("~/.codex/sessions"),
        help="Root directory of Codex sessions (default: ~/.codex/sessions).",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="Output path (JSONL).",
    )
    ap.add_argument(
        "--contains",
        default="",
        help="Optional substring filter (case-insensitive) applied to extracted text.",
    )
    args = ap.parse_args()

    sessions_root = Path(args.sessions_root).expanduser()
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    needle = args.contains.strip().lower()

    count_in = 0
    count_out = 0
    with out_path.open("w", encoding="utf-8") as out_f:
        for sf in _iter_session_files(sessions_root):
            msgs = extract_user_messages_from_file(sf)
            for m in msgs:
                count_in += 1
                if needle and needle not in m.text.lower():
                    continue
                out_f.write(
                    json.dumps(
                        {
                            "session_file": m.session_file,
                            "timestamp": m.timestamp,
                            "text": m.text,
                        },
                        ensure_ascii=True,
                    )
                    + "\n"
                )
                count_out += 1

    print(f"Wrote {count_out} messages (scanned {count_in} user messages). -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

