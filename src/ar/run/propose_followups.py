from __future__ import annotations

import sys
from pathlib import Path

from .generate_tasks import run_generate_tasks


def run_propose_followups(args: object) -> int:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()
    if not run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {run_dir}\n")
        return 20

    merge_report = run_dir / "30_MERGE" / "REPORT.md"
    if not merge_report.exists():
        sys.stderr.write("[ERROR] propose-followups requires merge artifacts; run `ar run merge --run-dir ...` first\n")
        return 20

    # Default to guided prompting for follow-ups unless explicitly overridden.
    if not str(getattr(args, "profile", "") or "").strip():
        setattr(args, "profile", "guided")

    setattr(args, "event_prefix", "propose_followups")
    setattr(args, "apply_source", "propose-followups")
    setattr(args, "session_prefix", "FOLLOWUPS")
    setattr(args, "cmd_label", "propose-followups")

    return run_generate_tasks(args)

