# Epistemic Grounding (v1): Philosophical + Technical Dialectic

This document makes the repo’s epistemic commitments explicit: *which philosophies of research we are borrowing from*, how they map to concrete technical decisions, and whether those decisions are **justified or not** (philosophically and technically).

The aim is not to “win philosophy”. The aim is **better research outcomes under real constraints** (compaction, cost, UI limitations, parallel processes, imperfect compliance).

Status: living document; revise when design changes.

---

## 1) What this repo is trying to optimize for

ARO is a research *orchestration substrate* that tries to maximize:
- **Resumability** (compaction survival; interrupted work is not wasted)
- **Auditability** (you can inspect why an output happened)
- **Epistemic reliability** (conflicts/assumptions surfaced; probes proposed)
- **Cross-runner comparability** (optional providers are “depth/breadth” + comparison)
- **Low-friction iteration** (tight loops: scaffold → produce → merge → validate → followups)

Non-goal (important): ARO is not a single “super-agent brain”. It is the **environment** in which different brains (Codex/Claude/Gemini/Cowork/humans) can operate without losing state or hiding disagreement.

---

## 2) The dialectical method we use for design decisions

For each major design decision, we treat this as a dialectic:

1) **Material constraint**: what the world/tooling/UI actually allows (cost, compaction, subprocesses, filesystem safety).
2) **Epistemic desideratum**: what a “good research process” should do (surface uncertainty, enable error correction, preserve disagreement).
3) **Design decision**: what we implement.
4) **Objections** (philosophical + technical): how this could fail or become performative.
5) **Mitigations**: guardrails, escape hatches, stop rules.
6) **Probes**: discriminating observations/experiments that would change our mind.

This keeps us from “philosophy as vibes” and from “engineering as default dogma”.

---

## 3) Philosophical lenses (selected) and how they translate into mechanics

This is a *curated* set that is directly actionable for research workflows. It is not an exhaustive survey.

### 3.1 Popper / critical rationalism: conjecture + refutation
Core idea: robust knowledge grows via **bold conjectures** and attempts to **refute** them, not via confirmation-only storybuilding. ([Popper1959])

Operational translation in ARO:
- tasks include **try-to-falsify procedures** and/or **probes**
- merge preserves **conflicts** instead of “averaging away” disagreement

Failure mode:
- “falsification” becomes a checkbox ritual; agents do not actually seek counterexamples.

Mitigation:
- require **counterexample/failure-mode sources** when possible
- treat “probes” as the operational minimum when strict falsification is unrealistic

### 3.2 Duhem–Quine holism: underdetermination and auxiliary hypotheses
Core idea: a hypothesis rarely faces the tribunal of experience alone; failures can be displaced onto background assumptions. ([Duhem1906], [Quine1951])

Operational translation in ARO:
- claims carry explicit **assumptions**
- conflicts are paired with **context-split candidates**
- residuals store “this depends” detail instead of forcing false precision

Failure mode:
- “everything depends” becomes an excuse for non-commitment.

Mitigation:
- require at least one **discriminating probe** for high-impact recommendations

### 3.3 Kuhn: paradigms, normal science, and revolutions
Core idea: inquiry is shaped by paradigms; anomaly handling is social/structural, not just logical. ([Kuhn1962])

Operational translation in ARO:
- don’t collapse disagreements prematurely; track them explicitly
- use comparisons across runners/models as a way to surface “anomalies” or blind spots

Failure mode:
- paralysis-by-paradigm: too much meta discussion, too little progress.

Mitigation:
- stop rules; task decomposition into smaller probes

### 3.4 Lakatos: research programmes (progressive vs degenerating)
Core idea: evaluate sequences of theories (programmes) by whether they produce novel, corroborated successes; keep the “hard core” + protective belt visible. ([Lakatos1970])

Operational translation in ARO:
- preserve competing “approach families” across claims instead of forcing one “answer”
- explicit residuals + followups let you judge whether a line of inquiry is progressive

Failure mode:
- the system becomes a museum of positions, not a decision support tool.

Mitigation:
- `RECOMMENDATIONS.md` emphasizes *actionable*, conditional guidance, not mere cataloguing

### 3.5 Peirce + pragmatism: abduction and inquiry as action
Core idea: inquiry includes **abduction** (hypothesis generation) and is oriented toward practical consequences. ([Peirce1877], [Peirce1878])

Operational translation in ARO:
- orchestrator plans generate tasks abductively, then test via probes
- recommendations include “what to do if false” (error-correcting action)

Failure mode:
- “pragmatism” becomes “whatever works” without evidential discipline.

Mitigation:
- provenance + sources + explicit assumptions keep “works” accountable

### 3.6 Severe testing / error-statistical thinking (Mayo)
Core idea: evidence is strong when a claim has passed a test that had a high chance of finding its flaws if it were false. ([Mayo1996])

Operational translation in ARO:
- probes should be framed as **high-discriminatory-power** checks
- “counterexample_missed” divergences push toward more severe tests

Failure mode:
- probes that are too vague or too underpowered to discriminate.

Mitigation:
- probe templates include expected outcomes and actions when falsified

### 3.7 Social epistemology: norms, critique, and distributed responsibility
Core idea: epistemic reliability depends on social norms like organized skepticism, communalism, and accountability. ([Merton1942], [Longino1990])

Operational translation in ARO:
- structured artifacts + logs enable critique and downstream correction
- comparison artifacts institutionalize “organized skepticism” across producers

Failure mode:
- capture of the process by a single “voice” (LLM or human), reducing real critique.

Mitigation:
- optional multi-runner execution; conflict preservation by default

### 3.8 Distributed cognition / extended mind
Core idea: cognition is often distributed across people, artifacts, and environments; memory and reasoning can be externalized. ([Hutchins1995], [ClarkChalmers1998])

Operational translation in ARO:
- run bundles on disk act as the system’s durable memory
- compaction-safe state is a core feature, not a convenience

Failure mode:
- over-externalization: too much structure and friction for small tasks.

Mitigation:
- allow scaffold-only runs; allow incomplete runs; keep optional runners optional

### 3.9 Bounded rationality and heuristics (Simon; Kahneman & Tversky)
Core idea: agents operate under constraints; heuristics are unavoidable; biases are systematic. ([Simon1969], [TverskyKahneman1974])

Operational translation in ARO:
- stop rules and budgets are explicit
- role-passes substitute for unavailable “true subagent contexts”
- monitoring/timeouts prevent infinite reasoning stalls

Failure mode:
- budget constraints cut off critical counterexample search.

Mitigation:
- follow-up generation from residuals/conflicts creates an explicit “return later” path

### 3.10 Goodhart/Campbell: metrics can destroy the thing measured
Core idea: when a measure becomes a target, it ceases to be a good measure; numeric quotas can corrupt epistemic behavior. ([Goodhart1975], [Campbell1976])

Operational translation in ARO:
- avoid quotas like “>= 25 claims”
- prefer protocols: conflicts + probes + residuals + stop rules

Failure mode:
- even protocols can become performative if agents optimize compliance text.

Mitigation:
- human review gates; compare producers; require concrete triggers for follow-up tasks

---

## 4) Design decisions (with philosophical + technical justifications, objections, and probes)

### D1) Disk-first run bundles are the source of truth
Material constraints:
- chat compaction and session loss are real
- parallel workers are separate processes; shared ephemeral memory is unreliable

Design decision:
- store run state as a run directory with required artifacts (`docs/RUN_BUNDLE_SPEC.md`)

Philosophical grounding:
- distributed cognition / extended mind: the run bundle is part of the cognitive system ([Hutchins1995], [ClarkChalmers1998])
- social epistemology: artifacts enable critique and accountability ([Merton1942], [Longino1990])

Objections:
- friction: writing files may slow early exploration

Mitigations:
- allow incomplete runs; minimal scaffold; optional providers optional

Probes:
- compare “chat-only orchestration” vs “run-bundle orchestration” for (a) restart cost after interruption, (b) ability to audit decisions, (c) ease of multi-runner comparison.

### D2) Deterministic merge/synthesis
Material constraints:
- multi-runner outputs differ in format/quality; humans need stable artifacts

Design decision:
- deterministic merge into `30_MERGE/` with non-destructive claim preservation

Philosophical grounding:
- reproducibility norms + severe testing: stable transforms are easier to audit and challenge ([Mayo1996])

Objections:
- “deterministic” can become “over-deterministic”: premature schema tyranny

Mitigations:
- residuals are first-class; claims are indexes, not the entire output

Probes:
- run the same producer outputs through two merge designs (deterministic vs freeform) and evaluate: conflict visibility, actionability, and “what got lost”.

### D3) Preserve conflicts instead of averaging
Material constraints:
- different models/tools will disagree; flattening hides assumptions

Design decision:
- keep incompatible claims and link them (`conflicts_with`), emit `CONFLICTS.md`

Philosophical grounding:
- Popperian critique + Kuhnian anomalies + Lakatosian programme competition ([Popper1959], [Kuhn1962], [Lakatos1970])

Objections:
- too many conflicts can overwhelm decision-making

Mitigations:
- context-split candidates; recommendations organized by area; follow-up tasks can resolve the highest-impact conflicts

Probes:
- measure: does explicit conflict preservation reduce downstream “rework tasks” vs. summary-only workflows?

### D4) Probes instead of pretending everything is strictly falsifiable
Material constraints:
- many strategic recommendations are conditional and not lab-falsifiable

Design decision:
- support probes as operational discriminators; allow falsification where helpful

Philosophical grounding:
- Popper (refutation) plus Duhem–Quine caution; Mayo’s “severe test” framing ([Popper1959], [Duhem1906], [Quine1951], [Mayo1996])

Objections:
- probes can be vague, low-power, or unexecuted

Mitigations:
- probe schema includes expected outcomes + what-if-false

Probes (meta):
- track whether probes are executed and whether they changed recommendations in subsequent runs.

### D5) Avoid numeric quotas; prefer process gates
Material constraints:
- LLMs optimize for the visible target; quotas invite padding

Design decision:
- avoid fixed counts; require conflict handling + probes + residuals + stop rules

Philosophical grounding:
- Goodhart/Campbell; also virtue epistemology emphasis on epistemic character over box-ticking ([Goodhart1975], [Campbell1976])

Objections:
- without quotas, outputs can be too thin

Mitigations:
- validate checks presence of required artifacts; comparison JSON captures coverage gaps; follow-ups can thicken evidence

Probes:
- compare thin-output incidence across (a) quota-based prompts vs (b) protocol-based prompts, using human scoring.

---

## 5) Decisions we should explicitly keep under doubt (and how we’d test them)

This section is a commitment to fallibilism: we expect some v1 choices to be wrong.

1) **Claim matching across producers**
   - doubt: grouping by `original_claim_id` is too brittle; it can create false conflicts.
   - test: compare conflict detection noise before/after adding a stable topic key or fingerprint.

2) **How much schema is “too much”**
   - doubt: registers could become the center of gravity and reduce nuance.
   - test: evaluate whether residuals meaningfully change follow-up task quality and final recommendations.

3) **Whether deterministic merge improves research quality**
   - doubt: it could add friction without real epistemic gains.
   - test: A/B within the same team across multiple runs; compare decision clarity + iteration time + correction rate.

---

## 6) References (starter bibliography)

- [Popper1959] Karl Popper, *The Logic of Scientific Discovery* (English ed. 1959; orig. 1934).
- [Duhem1906] Pierre Duhem, *The Aim and Structure of Physical Theory* (orig. 1906; Eng. trans. later).
- [Quine1951] W. V. O. Quine, “Two Dogmas of Empiricism” (1951).
- [Kuhn1962] Thomas S. Kuhn, *The Structure of Scientific Revolutions* (1962).
- [Lakatos1970] Imre Lakatos, “Falsification and the Methodology of Scientific Research Programmes” (1970).
- [Peirce1877] C. S. Peirce, “The Fixation of Belief” (1877).
- [Peirce1878] C. S. Peirce, “How to Make Our Ideas Clear” (1878).
- [Merton1942] Robert K. Merton, “The Normative Structure of Science” (1942).
- [Longino1990] Helen Longino, *Science as Social Knowledge* (1990).
- [Hutchins1995] Edwin Hutchins, *Cognition in the Wild* (1995).
- [ClarkChalmers1998] Andy Clark and David Chalmers, “The Extended Mind” (1998).
- [Simon1969] Herbert A. Simon, *The Sciences of the Artificial* (1969).
- [TverskyKahneman1974] Amos Tversky and Daniel Kahneman, “Judgment under Uncertainty: Heuristics and Biases” (1974).
- [Goodhart1975] Charles Goodhart, “Problems of Monetary Management: The U.K. Experience” (1975). (Goodhart’s law)
- [Campbell1976] Donald T. Campbell, “Assessing the Impact of Planned Social Change” (1976). (Campbell’s law)
- [Mayo1996] Deborah G. Mayo, *Error and the Growth of Experimental Knowledge* (1996).
