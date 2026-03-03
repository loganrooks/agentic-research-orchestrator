from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProducerSummary:
    producer_id: str
    runner: str
    model: str
    reasoning_effort: str
    status: str
    elapsed_seconds: float | None
    token_usage: dict[str, Any]
    sources_count: int
    claims_count: int


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


def _safe_load_json_array(path: Path) -> list[Any]:
    obj = _load_json(path)
    if isinstance(obj, list):
        return obj
    raise ValueError(f"Expected JSON array: {path}")


def _safe_load_json_array_or_empty(path: Path) -> list[Any]:
    if not path.exists():
        return []
    try:
        return _safe_load_json_array(path)
    except Exception:
        return []


def _iter_task_dirs(run_dir: Path) -> list[Path]:
    root = run_dir / "20_WORK"
    if not root.exists():
        return []
    return sorted([p for p in root.iterdir() if p.is_dir()])


def _iter_producer_dirs(task_dir: Path) -> list[Path]:
    return sorted([p for p in task_dir.iterdir() if p.is_dir()])


def _normalize_text(v: object) -> str:
    if not isinstance(v, str):
        return ""
    return " ".join(v.split()).strip().lower()


def _source_dedupe_key(src: dict[str, Any]) -> str:
    url = src.get("url")
    if isinstance(url, str) and url.strip():
        return "url:" + url.strip()

    title = src.get("title")
    author = src.get("author")
    published_at = src.get("published_at")
    if isinstance(title, str) and title.strip():
        return (
            "title:"
            + _normalize_text(title)
            + "|author:"
            + _normalize_text(author)
            + "|published_at:"
            + _normalize_text(published_at)
        )

    try:
        return "json:" + json.dumps(src, ensure_ascii=True, sort_keys=True)
    except Exception:
        return "json:{}"


def _format_source_id(n: int) -> str:
    return f"S-{n:04d}"


def _format_claim_id(n: int) -> str:
    return f"C-{n:04d}"


def _summarize_producer(producer_dir: Path, *, allow_missing_registers: bool) -> ProducerSummary:
    prov_path = producer_dir / "PROVENANCE.json"
    prov = _load_json(prov_path)

    runner = str(prov.get("runner") or "")
    producer_id = str(prov.get("producer_id") or producer_dir.name)

    sources_count = 0
    claims_count = 0

    sources_path = producer_dir / "SOURCES.json"
    claims_path = producer_dir / "CLAIMS.json"

    if sources_path.exists():
        sources_count = len(_safe_load_json_array(sources_path))
    elif not allow_missing_registers:
        raise FileNotFoundError(str(sources_path))

    if claims_path.exists():
        claims_count = len(_safe_load_json_array(claims_path))
    elif not allow_missing_registers:
        raise FileNotFoundError(str(claims_path))

    return ProducerSummary(
        producer_id=producer_id,
        runner=runner,
        model=str(prov.get("model") or ""),
        reasoning_effort=str(prov.get("reasoning_effort") or ""),
        status=str(prov.get("status") or ""),
        elapsed_seconds=prov.get("elapsed_seconds"),
        token_usage=prov.get("token_usage") or {},
        sources_count=sources_count,
        claims_count=claims_count,
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _append_log(run_dir: Path, event: dict[str, Any]) -> None:
    log_path = run_dir / "LOG.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _atomic_write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _try_update_state(
    run_dir: Path,
    *,
    status: str | None = None,
    current_step: str | None = None,
    preserve_statuses: set[str] | None = None,
) -> None:
    state_path = run_dir / "STATE.json"
    if not state_path.exists():
        return
    try:
        state = _load_json(state_path)
    except Exception:
        return
    if not isinstance(state, dict):
        return
    if status is not None:
        if preserve_statuses and state.get("status") in preserve_statuses:
            pass
        else:
            state["status"] = status
    if current_step is not None:
        state["current_step"] = current_step
    try:
        _atomic_write_json(state_path, state)
    except Exception:
        return


def _render_conflicts_md(conflicts: list[dict[str, Any]]) -> str:
    lines: list[str] = ["# Conflicts\n"]
    if not conflicts:
        lines.append("(none detected)\n")
        return "\n".join(lines).strip() + "\n"

    for c in conflicts:
        lines.append(f"## {c.get('task_id','')} / {c.get('original_claim_id','')}\n")
        lines.append(f"- Summary: {c.get('summary','')}")
        affected = c.get("affected_claim_ids") or []
        if isinstance(affected, list):
            lines.append(f"- Affected merged claims: {', '.join([str(x) for x in affected if str(x).strip()])}\n")
        for item in c.get("claims", []):
            if not isinstance(item, dict):
                continue
            lines.append(f"### {item.get('claim_id','')} ({item.get('producer_id','')})\n")
            rec = item.get("recommendation") or ""
            claim = item.get("claim") or ""
            if rec:
                lines.append(f"- recommendation: {rec}")
            if claim:
                lines.append(f"- claim: {claim}")
            assumptions = item.get("assumptions") or []
            if isinstance(assumptions, list) and assumptions:
                lines.append("- assumptions:")
                for a in assumptions:
                    if isinstance(a, str) and a.strip():
                        lines.append(f"  - {a.strip()}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_residuals_md(residuals: list[dict[str, str]]) -> str:
    lines: list[str] = ["# Residuals\n"]
    if not residuals:
        lines.append("(none)\n")
        return "\n".join(lines).strip() + "\n"
    for r in residuals:
        lines.append(f"## {r['task_id']} / {r['producer_id']}\n")
        txt = (r.get("text") or "").strip()
        lines.append(txt if txt else "none")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_assumptions_and_probes_md(claims: list[dict[str, Any]]) -> str:
    assumptions_set: dict[str, None] = {}
    probes: list[dict[str, str]] = []
    for c in claims:
        assumptions = c.get("assumptions")
        if isinstance(assumptions, list):
            for a in assumptions:
                if isinstance(a, str) and a.strip():
                    assumptions_set[a.strip()] = None
        pr = c.get("probes")
        if isinstance(pr, list):
            for p in pr:
                if not isinstance(p, dict):
                    continue
                test = p.get("test")
                if not isinstance(test, str) or not test.strip():
                    continue
                probes.append(
                    {
                        "test": test.strip(),
                        "expected_if_true": str(p.get("expected_if_true") or "").strip(),
                        "what_if_false": str(p.get("what_if_false") or "").strip(),
                        "claim_id": str(c.get("claim_id") or ""),
                    }
                )

    lines: list[str] = ["# Assumptions and Probes\n"]

    lines.append("## Assumptions\n")
    if not assumptions_set:
        lines.append("(none)\n")
    else:
        for a in sorted(assumptions_set.keys()):
            lines.append(f"- {a}")
        lines.append("")

    lines.append("## Probes\n")
    if not probes:
        lines.append("(none)\n")
    else:
        for p in probes:
            lines.append(f"- [{p['claim_id']}] {p['test']}")
            if p["expected_if_true"]:
                lines.append(f"  - expected_if_true: {p['expected_if_true']}")
            if p["what_if_false"]:
                lines.append(f"  - what_if_false: {p['what_if_false']}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _render_recommendations_md(claims: list[dict[str, Any]]) -> str:
    by_area: dict[str, list[dict[str, Any]]] = {}
    for c in claims:
        area = str(c.get("area") or "other")
        by_area.setdefault(area, []).append(c)

    lines: list[str] = ["# Recommendations\n"]
    for area in sorted(by_area.keys()):
        lines.append(f"## {area}\n")
        for c in by_area[area]:
            cid = str(c.get("claim_id") or "")
            prod = str(c.get("producer_id") or "")
            task = str(c.get("task_id") or "")
            rec = str(c.get("recommendation") or "").strip()
            if not rec:
                rec = str(c.get("claim") or "").strip()
            lines.append(f"- [{cid}] ({task} / {prod}) {rec}")
            cw = c.get("conflicts_with") or []
            if isinstance(cw, list) and cw:
                lines.append(f"  - conflicts_with: {', '.join([str(x) for x in cw if str(x).strip()])}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_report_md(
    *,
    tasks_count: int,
    producers_count: int,
    sources_count: int,
    claims_count: int,
    conflicts_count: int,
    agreements: list[dict[str, Any]],
    context_split_candidates: list[dict[str, Any]],
    composable_claim_ids: list[str],
) -> str:
    lines: list[str] = [
        "# Synthesis Report\n\n"
        "This report is generated deterministically from `20_WORK/`.\n\n"
        f"- tasks: {tasks_count}\n"
        f"- producers: {producers_count}\n"
        f"- sources (deduped): {sources_count}\n"
        f"- claims (non-destructive): {claims_count}\n"
        f"- conflicts: {conflicts_count}\n\n"
    ]

    lines.append("## Agreements\n")
    if not agreements:
        lines.append("(none)\n")
    else:
        for a in agreements:
            lines.append(
                f"- {a.get('task_id','')} / {a.get('original_claim_id','')}: {', '.join(a.get('claim_ids', []))}"
            )
        lines.append("")

    lines.append("## Conflicts\n")
    if conflicts_count == 0:
        lines.append("(none)\n")
    else:
        lines.append("See `CONFLICTS.md`.\n")

    lines.append("## Context Split Candidates\n")
    if not context_split_candidates:
        lines.append("(none)\n")
    else:
        for c in context_split_candidates:
            lines.append(
                f"- {c.get('task_id','')} / {c.get('original_claim_id','')}: {', '.join(c.get('claim_ids', []))}"
            )
        lines.append("")

    lines.append("## Composable Recommendation Candidates\n")
    lines.append(f"- count: {len(composable_claim_ids)}\n")

    lines.append("## Artifacts\n")
    lines.append("- `SOURCES.json`")
    lines.append("- `CLAIMS.json`")
    lines.append("- `CONFLICTS.md`")
    lines.append("- `ASSUMPTIONS_AND_PROBES.md`")
    lines.append("- `RECOMMENDATIONS.md`")
    lines.append("- `RESIDUALS.md`")

    return "\n".join(lines).strip() + "\n"


def run_merge(args: object) -> int:
    run_dir = Path(str(getattr(args, "run_dir", ""))).expanduser().resolve()
    allow_missing = bool(getattr(args, "allow_missing_registers", False))

    if not run_dir.exists():
        sys.stderr.write(f"[ERROR] run dir not found: {run_dir}\n")
        return 21

    work_root = run_dir / "20_WORK"
    merge_root = run_dir / "30_MERGE"
    if not work_root.exists():
        sys.stderr.write(f"[ERROR] missing 20_WORK/: {work_root}\n")
        return 21
    merge_root.mkdir(parents=True, exist_ok=True)

    now = _now_local()
    _try_update_state(run_dir, status="merging", current_step="merge", preserve_statuses={"partial"})
    _append_log(
        run_dir,
        {
            "ts": now.isoformat(timespec="seconds"),
            "level": "info",
            "event": "merge_started",
            "data": {"allow_missing_registers": allow_missing},
        },
    )

    comparison_tasks: list[dict[str, Any]] = []
    comparison_md_lines: list[str] = ["# Producer Comparison\n"]

    merged_sources: list[dict[str, Any]] = []
    source_key_to_id: dict[str, str] = {}
    source_key_to_index: dict[str, int] = {}
    source_map_by_producer: dict[tuple[str, str, str], str] = {}

    merged_claims: list[dict[str, Any]] = []
    claim_by_id: dict[str, dict[str, Any]] = {}

    residuals_out: list[dict[str, str]] = []
    conflicts_out: list[dict[str, Any]] = []

    conflicts_present = False
    agreements_out: list[dict[str, Any]] = []
    context_split_candidates_out: list[dict[str, Any]] = []

    for task_dir in _iter_task_dirs(run_dir):
        task_id = task_dir.name
        producers: list[dict[str, Any]] = []
        producer_has_counterexamples: dict[str, bool] = {}

        # Track claim collisions within this task by original claim_id.
        task_claim_groups: dict[str, list[str]] = {}

        comparison_md_lines.append(f"## {task_id}\n")
        comparison_md_lines.append("| producer_id | runner | model | reasoning | status | elapsed_s | tokens_total | sources | claims |")
        comparison_md_lines.append("|---|---|---|---|---|---:|---:|---:|---:|")

        for producer_dir in _iter_producer_dirs(task_dir):
            try:
                s = _summarize_producer(producer_dir, allow_missing_registers=allow_missing)
            except Exception as e:
                sys.stderr.write(f"[ERROR] failed to summarize {producer_dir}: {e}\n")
                return 21

            # Residuals are required by contract.
            res_path = producer_dir / "RESIDUALS.md"
            if not res_path.exists():
                sys.stderr.write(f"[ERROR] missing required producer artifact: {res_path}\n")
                return 21
            residuals_out.append({"task_id": task_id, "producer_id": s.producer_id, "text": res_path.read_text(encoding="utf-8")})

            sources_path = producer_dir / "SOURCES.json"
            sources_arr = _safe_load_json_array_or_empty(sources_path) if allow_missing else _safe_load_json_array(sources_path)
            has_counterexample = False
            for src in sources_arr:
                if not isinstance(src, dict):
                    continue
                role = src.get("role")
                if isinstance(role, str) and role.strip():
                    norm_role = role.strip().lower().replace("-", "_").replace(" ", "_")
                    if norm_role in ("counterexample", "failure_mode"):
                        has_counterexample = True
                key = _source_dedupe_key(src)
                if key not in source_key_to_id:
                    sid = _format_source_id(len(merged_sources) + 1)
                    source_key_to_id[key] = sid
                    source_key_to_index[key] = len(merged_sources)
                    out_src = dict(src)
                    out_src["source_id"] = sid
                    out_src["origins"] = []
                    merged_sources.append(out_src)
                mid = source_key_to_id[key]
                idx = source_key_to_index[key]
                origin = {"task_id": task_id, "producer_id": s.producer_id, "source_id": str(src.get("source_id") or "")}
                merged_sources[idx].setdefault("origins", []).append(origin)

                osid = src.get("source_id")
                if isinstance(osid, str) and osid.strip():
                    source_map_by_producer[(task_id, s.producer_id, osid.strip())] = mid

            producer_has_counterexamples[s.producer_id] = has_counterexample

            claims_path = producer_dir / "CLAIMS.json"
            claims_arr = _safe_load_json_array_or_empty(claims_path) if allow_missing else _safe_load_json_array(claims_path)
            for cl in claims_arr:
                if not isinstance(cl, dict):
                    continue
                original_claim_id = str(cl.get("claim_id") or "").strip()
                merged_id = _format_claim_id(len(merged_claims) + 1)

                out_claim = dict(cl)
                out_claim["claim_id"] = merged_id
                out_claim["task_id"] = task_id
                out_claim["producer_id"] = s.producer_id
                out_claim["original_claim_id"] = original_claim_id
                out_claim["conflicts_with"] = []

                ev = out_claim.get("evidence_sources")
                if isinstance(ev, list):
                    new_ev: list[str] = []
                    for sid in ev:
                        if not isinstance(sid, str):
                            continue
                        mapped = source_map_by_producer.get((task_id, s.producer_id, sid.strip()))
                        new_ev.append(mapped or sid.strip())
                    out_claim["evidence_sources"] = new_ev

                merged_claims.append(out_claim)
                claim_by_id[merged_id] = out_claim
                if original_claim_id:
                    task_claim_groups.setdefault(original_claim_id, []).append(merged_id)

            tu = s.token_usage or {}
            tokens_total = tu.get("total")
            producers.append(
                {
                    "producer_id": s.producer_id,
                    "runner": s.runner,
                    "model": s.model,
                    "reasoning_effort": s.reasoning_effort,
                    "status": s.status,
                    "elapsed_seconds": s.elapsed_seconds,
                    "token_usage": tu,
                    "counts": {"sources": s.sources_count, "claims": s.claims_count},
                    "notes": "",
                }
            )
            comparison_md_lines.append(
                f"| {s.producer_id} | {s.runner} | {s.model} | {s.reasoning_effort} | {s.status} | "
                f"{'' if s.elapsed_seconds is None else f'{s.elapsed_seconds:.1f}'} | "
                f"{'' if tokens_total is None else tokens_total} | {s.sources_count} | {s.claims_count} |"
            )

        divergences: list[dict[str, Any]] = []

        # Coverage gap: one producer found claims where another has none.
        if len(producers) >= 2:
            claim_counts = [int(p.get("counts", {}).get("claims") or 0) for p in producers]
            if min(claim_counts) == 0 and max(claim_counts) > 0:
                divergences.append(
                    {
                        "type": "coverage_gap",
                        "summary": "At least one producer reported 0 claims while another reported >0 claims.",
                        "affected_claim_ids": [],
                        "notes": "",
                    }
                )

            # Counterexample missed: some producers recorded counterexamples/failure modes, others did not.
            flags = [bool(producer_has_counterexamples.get(str(p.get("producer_id") or ""), False)) for p in producers]
            if any(flags) and not all(flags):
                has = [str(p.get("producer_id") or "") for p in producers if producer_has_counterexamples.get(str(p.get("producer_id") or ""), False)]
                missing = [str(p.get("producer_id") or "") for p in producers if not producer_has_counterexamples.get(str(p.get("producer_id") or ""), False)]
                divergences.append(
                    {
                        "type": "counterexample_missed",
                        "summary": "Producers differ in whether they recorded counterexamples/failure modes in sources.",
                        "affected_claim_ids": [],
                        "notes": f"has_counterexample={has}; missing={missing}",
                    }
                )

        # Conflicts: same original claim_id disagrees across producers.
        for ocid in sorted(task_claim_groups.keys()):
            mids = task_claim_groups[ocid]
            if len(mids) < 2:
                continue
            uniq = {_normalize_text(claim_by_id[mid].get("recommendation") or claim_by_id[mid].get("claim")) for mid in mids}
            uniq = {x for x in uniq if x}
            if len(uniq) <= 1:
                agreements_out.append({"task_id": task_id, "original_claim_id": ocid, "claim_ids": mids})
                continue

            conflicts_present = True
            divergences.append(
                {
                    "type": "conflict",
                    "summary": f"Producers disagree for original claim_id {ocid}.",
                    "affected_claim_ids": mids,
                    "notes": "",
                }
            )
            conflicts_out.append(
                {
                    "task_id": task_id,
                    "original_claim_id": ocid,
                    "summary": "Incompatible recommendations/claims for the same claim id.",
                    "affected_claim_ids": mids,
                    "claims": [claim_by_id[mid] for mid in mids],
                }
            )
            for mid in mids:
                claim_by_id[mid]["conflicts_with"] = [x for x in mids if x != mid]

            # Heuristic context-split candidate: no shared assumptions across claims.
            assumptions_sets: list[set[str]] = []
            for mid in mids:
                a = claim_by_id[mid].get("assumptions")
                if isinstance(a, list):
                    assumptions_sets.append({_normalize_text(x) for x in a if isinstance(x, str) and x.strip()})
                else:
                    assumptions_sets.append(set())
            if assumptions_sets and all(assumptions_sets) and set.intersection(*assumptions_sets) == set():
                context_split_candidates_out.append({"task_id": task_id, "original_claim_id": ocid, "claim_ids": mids})

        comparison_md_lines.append("")
        if divergences:
            comparison_md_lines.append("### Divergences\n")
            for d in divergences:
                comparison_md_lines.append(f"- ({d.get('type')}) {d.get('summary')}")
            comparison_md_lines.append("")

        comparison_tasks.append({"task_id": task_id, "producers": producers, "divergences": divergences})

    comp_json = {
        "schema_version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "tasks": comparison_tasks,
    }

    _write_json(merge_root / "COMPARISON.json", comp_json)
    _write_text(merge_root / "COMPARISON.md", "\n".join(comparison_md_lines).strip() + "\n")

    _write_json(merge_root / "SOURCES.json", merged_sources)
    _write_json(merge_root / "CLAIMS.json", merged_claims)
    _write_text(merge_root / "CONFLICTS.md", _render_conflicts_md(conflicts_out))
    _write_text(merge_root / "ASSUMPTIONS_AND_PROBES.md", _render_assumptions_and_probes_md(merged_claims))
    _write_text(merge_root / "RESIDUALS.md", _render_residuals_md(residuals_out))
    _write_text(merge_root / "RECOMMENDATIONS.md", _render_recommendations_md(merged_claims))
    _write_text(
        merge_root / "REPORT.md",
        _render_report_md(
            tasks_count=len(comparison_tasks),
            producers_count=sum(len(t.get("producers", []) or []) for t in comparison_tasks),
            sources_count=len(merged_sources),
            claims_count=len(merged_claims),
            conflicts_count=len(conflicts_out),
            agreements=agreements_out,
            context_split_candidates=context_split_candidates_out,
            composable_claim_ids=sorted([c["claim_id"] for c in merged_claims if not (c.get("conflicts_with") or [])]),
        ),
    )

    if conflicts_present:
        _append_log(
            run_dir,
            {
                "ts": _now_local().isoformat(timespec="seconds"),
                "level": "warn",
                "event": "merge_finished",
                "data": {
                    "status": "conflicts",
                    "tasks": len(comparison_tasks),
                    "producers": sum(len(t.get("producers", []) or []) for t in comparison_tasks),
                    "sources": len(merged_sources),
                    "claims": len(merged_claims),
                    "conflicts": len(conflicts_out),
                },
            },
        )
        sys.stdout.write("[WARN] merged (conflicts detected; see 30_MERGE/CONFLICTS.md)\n")
        return 11

    _append_log(
        run_dir,
        {
            "ts": _now_local().isoformat(timespec="seconds"),
            "level": "info",
            "event": "merge_finished",
            "data": {
                "status": "ok",
                "tasks": len(comparison_tasks),
                "producers": sum(len(t.get("producers", []) or []) for t in comparison_tasks),
                "sources": len(merged_sources),
                "claims": len(merged_claims),
                "conflicts": len(conflicts_out),
            },
        },
    )
    sys.stdout.write("[OK] merged\n")
    return 0
