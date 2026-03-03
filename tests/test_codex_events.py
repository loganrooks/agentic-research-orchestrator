from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "src"))

from ar.run.spawn_codex import TokenUsage, parse_token_usage_from_codex_events  # noqa: E402


def test_parse_token_usage_from_codex_events_fixture() -> None:
    events_path = repo_root / "tests" / "fixtures" / "codex_EVENTS_token_count.jsonl"
    tu = parse_token_usage_from_codex_events(events_path)
    assert tu == TokenUsage(input=10, cached_input=2, output=3, reasoning=4, total=19)
