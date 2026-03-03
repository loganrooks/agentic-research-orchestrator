from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "src"))

from ar.run.spawn_codex import _build_codex_exec_cmd  # noqa: E402


def test_spawn_codex_builds_reasoning_override_cmd() -> None:
    cmd = _build_codex_exec_cmd(
        model="gpt-5.2",
        reasoning="high",
        sandbox="read-only",
        last_message_path=Path("/tmp/LAST_MESSAGE.txt"),
    )
    joined = " ".join(cmd)
    assert 'model_reasoning_effort="high"' in joined
    assert "reasoning.effort" not in joined

