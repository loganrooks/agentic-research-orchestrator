# Task Writing Guide (v1)

This guide explains how to write tasks that:
- don’t waste tokens,
- don’t force everything into rigid schemas,
- and produce outputs that can be merged across runners.

---

## 1) Why tasks need structure

Without a task contract, research agents tend to:
- over-summarize,
- skip contradictions,
- omit assumptions,
- or “sound confident” without proving anything.

The structure below exists to prevent those failures, not to constrain judgment.

---

## 2) Role-Passes (what they are)

“Role-passes” means asking *one* agent to do multiple sequential passes with different intent.

Example passes inside one run:
1. **Collector pass**: gather sources and concrete claims.
2. **Contradiction pass**: find conflicts and dig deeper.
3. **Falsifier pass**: try to break the best recommendations.
4. **Synthesis pass**: write the report with residuals preserved.

**Why this matters:** Codex does not provide subagent contexts inside a single run; role-passes are a way to get depth without pretending we have parallel subagents.

---

## 3) Canonical task template

Copy/paste this into `10_TASKS/T-XXXX__slug.md`:

```markdown
# Task T-XXXX: <short title>

## Intent
What question this task answers.

## Boundaries (what to ignore)
- …

## Deliverables
- REPORT.md sections to cover
- SOURCES register expectations
- CLAIMS register expectations (if applicable)
- RESIDUALS expectations

## Evidence posture
What counts as strong evidence for this task?
What sources are likely to be misleading?

## Contradiction protocol
If you find conflicting claims:
1. state both claims precisely
2. infer the implied assumptions/context
3. do at least one additional targeted search to resolve/sharpen the contradiction
4. if unresolved, propose a probe that would resolve it

## Try-to-falsify (procedure)
1. Pick the top 1–3 recommendations you think matter most.
2. State the null/negation for each.
3. Search for counterexamples/failure modes.
4. If you can’t find any, list plausible failure modes anyway.
5. Propose a discriminating probe (what observation/experiment would change your mind).

## Output format
- Prefer JSON registers in fenced code blocks.
- If you cannot output JSON, use tables with stable IDs.
- If you want cross-runner comparisons, include a stable `topic_key` per claim (short string kept consistent within the task across producers).

## Stop rules
- Max N searches OR stop when diminishing returns, but record deferred queries.
```

---

## 4) How to avoid “over-determinism”

Do not demand:
- a fixed number of claims,
- every insight expressed as a claim,
- or perfect falsifiability.

Instead demand:
- explicit uncertainty,
- explicit contradictions,
- and explicit probes.

**Why:** The point is epistemic reliability, not “compliance with a schema.”
