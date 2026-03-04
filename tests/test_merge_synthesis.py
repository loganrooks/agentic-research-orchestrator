from __future__ import annotations

import json
import os
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


def test_merge_preserves_conflicts_and_emits_divergence(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    report_a = tmp_path / "a.md"
    report_a.write_text("# A\n", encoding="utf-8")
    report_b = tmp_path / "b.md"
    report_b.write_text("# B\n", encoding="utf-8")

    sources_a = tmp_path / "sources_a.json"
    sources_a.write_text(
        json.dumps([{"source_id": "S-0001", "title": "Example", "url": "https://example.com"}], indent=2) + "\n",
        encoding="utf-8",
    )
    sources_b = tmp_path / "sources_b.json"
    sources_b.write_text(
        json.dumps([{"source_id": "S-0001", "title": "Example 2", "url": "https://example.com"}], indent=2) + "\n",
        encoding="utf-8",
    )

    claims_a = tmp_path / "claims_a.json"
    claims_a.write_text(
        json.dumps(
            [
                {
                    "claim_id": "C-0001",
                    "area": "worktrees",
                    "claim": "Worktrees reduce integration friction for parallel work.",
                    "recommendation": "Use git worktrees for parallel feature work.",
                    "assumptions": ["Team uses git", "Multiple tasks in flight"],
                    "evidence_sources": ["S-0001"],
                }
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    claims_b = tmp_path / "claims_b.json"
    claims_b.write_text(
        json.dumps(
            [
                {
                    "claim_id": "C-0001",
                    "area": "worktrees",
                    "claim": "Worktrees increase entropy and slow small changes.",
                    "recommendation": "Avoid worktrees; use short-lived feature branches.",
                    "assumptions": ["Small changes dominate"],
                    "evidence_sources": ["S-0001"],
                }
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    residuals_a = tmp_path / "res_a.md"
    residuals_a.write_text("Residuals: none\n", encoding="utf-8")
    residuals_b = tmp_path / "res_b.md"
    residuals_b.write_text("Residuals: none\n", encoding="utf-8")

    r_imp_a = _run_ar(
        [
            "run",
            "import",
            "--run-dir",
            str(run_dir),
            "--task",
            "T-0001",
            "--runner",
            "claude_desktop",
            "--report-path",
            str(report_a),
            "--sources-path",
            str(sources_a),
            "--claims-path",
            str(claims_a),
            "--residuals-path",
            str(residuals_a),
        ]
    )
    assert r_imp_a.returncode == 0, (r_imp_a.stdout, r_imp_a.stderr)
    r_imp_b = _run_ar(
        [
            "run",
            "import",
            "--run-dir",
            str(run_dir),
            "--task",
            "T-0001",
            "--runner",
            "gemini_deep_research",
            "--report-path",
            str(report_b),
            "--sources-path",
            str(sources_b),
            "--claims-path",
            str(claims_b),
            "--residuals-path",
            str(residuals_b),
        ]
    )
    assert r_imp_b.returncode == 0, (r_imp_b.stdout, r_imp_b.stderr)

    r_merge = _run_ar(["run", "merge", "--run-dir", str(run_dir)])
    assert r_merge.returncode == 11, (r_merge.stdout, r_merge.stderr)

    state = json.loads((run_dir / "STATE.json").read_text(encoding="utf-8"))
    assert state.get("status") == "partial"

    merged_sources = json.loads((run_dir / "30_MERGE" / "SOURCES.json").read_text(encoding="utf-8"))
    assert len(merged_sources) == 1  # deduped by URL

    merged_claims = json.loads((run_dir / "30_MERGE" / "CLAIMS.json").read_text(encoding="utf-8"))
    assert len(merged_claims) == 2  # non-destructive
    recs = {c.get("recommendation") for c in merged_claims}
    assert "Use git worktrees for parallel feature work." in recs
    assert "Avoid worktrees; use short-lived feature branches." in recs

    # Conflict links should be present.
    c0 = merged_claims[0]
    assert c0.get("original_claim_id") == "C-0001"
    assert isinstance(c0.get("conflicts_with"), list)
    assert c0["conflicts_with"], "expected conflicts_with to be populated"

    comp = json.loads((run_dir / "30_MERGE" / "COMPARISON.json").read_text(encoding="utf-8"))
    t = next(t for t in comp["tasks"] if t["task_id"] == "T-0001")
    assert any(d.get("type") == "conflict" for d in t.get("divergences", []))


def test_merge_works_with_single_producer(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    report = tmp_path / "r.md"
    report.write_text("# R\n", encoding="utf-8")
    residuals = tmp_path / "res.md"
    residuals.write_text("none\n", encoding="utf-8")

    r_imp = _run_ar(
        [
            "run",
            "import",
            "--run-dir",
            str(run_dir),
            "--task",
            "T-0001",
            "--runner",
            "codex",
            "--producer",
            "codex:worker-01",
            "--report-path",
            str(report),
            "--residuals-path",
            str(residuals),
        ]
    )
    assert r_imp.returncode == 0, (r_imp.stdout, r_imp.stderr)

    r_merge = _run_ar(["run", "merge", "--run-dir", str(run_dir)])
    assert r_merge.returncode == 0, (r_merge.stdout, r_merge.stderr)

    assert (run_dir / "30_MERGE" / "REPORT.md").exists()
    assert (run_dir / "30_MERGE" / "CLAIMS.json").exists()
    assert (run_dir / "30_MERGE" / "SOURCES.json").exists()


def test_merge_emits_counterexample_missed_divergence(tmp_path: Path) -> None:
    env_fixed = {"AR_FIXED_NOW": "2026-03-02T12:34:56-05:00", "AR_FIXED_RUN_ID": "abcdef1234"}
    r_scaffold = _run_ar(
        ["run", "scaffold", "--runs-root", str(tmp_path), "--slug", "test-run", "--goal", "Test goal"],
        env_extra=env_fixed,
    )
    assert r_scaffold.returncode == 0, (r_scaffold.stdout, r_scaffold.stderr)
    run_dir = Path(r_scaffold.stdout.strip())

    report_a = tmp_path / "a.md"
    report_a.write_text("# A\n", encoding="utf-8")
    report_b = tmp_path / "b.md"
    report_b.write_text("# B\n", encoding="utf-8")

    sources_a = tmp_path / "sources_a.json"
    sources_a.write_text(
        json.dumps(
            [{"source_id": "S-0001", "title": "Counterexample", "url": "https://example.com/cx", "role": "counterexample"}],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    sources_b = tmp_path / "sources_b.json"
    sources_b.write_text(
        json.dumps([{"source_id": "S-0001", "title": "Same URL (no role)", "url": "https://example.com/cx"}], indent=2) + "\n",
        encoding="utf-8",
    )

    residuals = tmp_path / "res.md"
    residuals.write_text("none\n", encoding="utf-8")

    r_imp_a = _run_ar(
        [
            "run",
            "import",
            "--run-dir",
            str(run_dir),
            "--task",
            "T-0001",
            "--runner",
            "claude_desktop",
            "--report-path",
            str(report_a),
            "--sources-path",
            str(sources_a),
            "--residuals-path",
            str(residuals),
        ]
    )
    assert r_imp_a.returncode == 0, (r_imp_a.stdout, r_imp_a.stderr)
    r_imp_b = _run_ar(
        [
            "run",
            "import",
            "--run-dir",
            str(run_dir),
            "--task",
            "T-0001",
            "--runner",
            "gemini_deep_research",
            "--report-path",
            str(report_b),
            "--sources-path",
            str(sources_b),
            "--residuals-path",
            str(residuals),
        ]
    )
    assert r_imp_b.returncode == 0, (r_imp_b.stdout, r_imp_b.stderr)

    r_merge = _run_ar(["run", "merge", "--run-dir", str(run_dir)])
    assert r_merge.returncode == 0, (r_merge.stdout, r_merge.stderr)

    comp = json.loads((run_dir / "30_MERGE" / "COMPARISON.json").read_text(encoding="utf-8"))
    t = next(t for t in comp["tasks"] if t["task_id"] == "T-0001")
    assert any(d.get("type") == "counterexample_missed" for d in t.get("divergences", []))
