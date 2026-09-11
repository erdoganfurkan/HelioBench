# Plan — a domain-agnostic agent benchmark harness

**Status:** thinking document, written 2026-08-28. Nothing here is committed to. Companion to
`docs/plan-v0.2-hardening.md`, which is the concrete near-term work on HelioBench itself.

**The question:** HelioBench was built for one agent in one field. How much of it is actually
about heliophysics, and is the remainder worth building as a product?

---

## 1. What HelioBench already is, with the physics removed

Strip the domain and nine properties remain. None of them mention plasma.

1. **Verdicts come from deterministic code, never from a model.** String equality, unit-aware
   numeric tolerance, arithmetic. This is the whole foundation: benchmarks scored by an LLM
   judge get taken apart on position bias and self-preference, and the ones that survive review
   have programmatic graders.
2. **Answer keys are derived by script from frozen bytes**, never typed from memory. Adding a
   task means running a deriver, not writing a number.
3. **A task is defective when a defensible answer exists that its key rejects** — with a stated
   procedure for choosing between widening the key and hardening the prompt.
4. **One-method `Agent` protocol**, so a third party can plug a scaffold in without patching
   anything.
5. **`--agent-ref`**: pin the commit under test, build it in an isolated venv, record the SHA
   in the report. You benchmark the code you named, not whatever is installed.
6. **`task_set_digest`**: change a prompt and old scores stop comparing, loudly.
7. **A process channel beside correctness** — figures no computation produced, methods
   reimplemented from memory, invented identifiers, tool efficiency, cost.
8. **One process signal is a gate**: a run whose answer contradicts its own provenance ledger
   fails, however right the number looks.
9. **Statistics matched to the sample** — bootstrap over *events* rather than tasks, and paired
   McNemar for two arms over the same task set.

The three tiers generalise better than they look. **n1 is retrieval** — resolve a need to an
identifier in a large catalogue. **n2 is closed form** — one call, one formula, a floor that
must be unarguable. **n3 is method** — multi-step analysis over frozen inputs with the
procedure stated. Retrieval / closed-form / method is a shape that fits legal research,
clinical guideline application, financial reconciliation, or bioinformatics without deformation.

## 2. What is genuinely domain-specific

Less than it feels like: the task YAML contents, the fixtures, the recipe functions that derive
truth, and three imports (speasy, PlasmaPy, Chroma) that live behind the HelioAI adapter rather
than in the harness.

The graders, runner, statistics, report, digesting, agent-ref machinery and process metrics are
already domain-neutral. **The extraction is smaller than the rewrite people usually imagine** —
which is the main argument for doing it at all.

## 3. Why this is not already solved

| Existing thing | What it does | What it does not do |
|---|---|---|
| LangSmith, Langfuse, Braintrust | Tracing and observability; LLM-judge evals bolted on | Deterministic verdicts; statistics; pinning the agent commit |
| promptfoo, OpenAI Evals | Prompt-level assertions, mostly LLM-graded | Multi-step agent runs; process auditing |
| HELM, lm-eval-harness | Static QA over model outputs | Agents that call tools; tool-use provenance |
| SWE-bench, SWE-bench+ | Programmatic verdicts, one domain | Anything outside code; a provenance channel |
| τ-bench, AgentBench | Agent tasks, partly programmatic | Domain extensibility; per-run cost and rank metrics |

SWE-bench is the proof the model works — programmatic grading made it the field's reference
benchmark — and SWE-bench+ (arXiv:2410.06992, 31% weak tests) is the proof that key quality is
the thing that decays. HelioBench's answer to that is rule 2 and rule 3 above, which is
genuinely uncommon.

**The gap: no domain-agnostic harness gives deterministic verdicts, a process/provenance gate,
commit-pinned agents, and statistics honest about sample size.** Everyone else either judges
with a model or restricts to one domain.

## 4. Architecture, if extracted

Three layers, and the boundary is already roughly where it needs to be.

```
core/            domain-agnostic, becomes the product
  tasks.py       schema, loading, task_set_digest
  runner.py      execution, repetitions, --jobs, errored classification
  graders/       string, numeric-with-units, set-membership, tolerance, process
  stats.py       event-clustered bootstrap, paired McNemar
  report.py      score + process + cost tables
  agentsnapshot  --agent-ref: resolve, build, pin
  protocol.py    Agent: one method

packs/           one per domain, shipped separately
  heliophysics/  today's tasks, fixtures, recipes, key derivers
  <yours>/       task set + fixtures + truth derivers + licence per task

adapters/        one per agent scaffold
  helioai, claude-code, langgraph, bare-tool-llm, null
```

A pack is: task files with `provenance` and `licence`, a fixture builder, a truth deriver, and
optionally domain graders. The contract for a pack is small enough to write in an afternoon,
which is the test of whether the boundary is in the right place.

## 5. The hard part: the provenance contract

Eight of the nine properties need nothing from the agent. **The process channel needs the agent
to emit a ledger** of what it computed — name, value, units, and where it came from. HelioAI
does this natively; an arbitrary agent does not.

Three levels, degrading gracefully, and the harness must report which level it got rather than
silently scoring a blank:

- **Level 0 — no ledger.** Correctness only. Process columns print `n/a`, and the gate is
  inactive. Honest, and still better than an LLM judge.
- **Level 1 — tool-call trace only.** Most frameworks emit this. Recoverable from it: tool
  efficiency, error rate, invented identifiers (check outputs against the catalogue), retrieval
  rank, cost. Not recoverable: whether a stated number came from a computation.
- **Level 2 — a provenance ledger.** Full process channel including the contradiction gate.
  Needs either a cooperating agent or a sandbox the harness owns, where an `export()`-style
  call is the only way to produce a number.

Level 2 through a harness-owned sandbox is the interesting move: it makes provenance a property
of the *environment* rather than of the agent's goodwill. It also fixes the flaw noted in
`plan-v0.2-hardening.md` §D2 — that today's gate reads a counter the candidate computes about
itself.

## 6. Product shape, and where the money actually is

Not "a benchmark". The recurring, painful question is narrower:

> **Did this change make my agent worse?**

Teams shipping domain agents currently answer it by eyeballing a few transcripts, or with an
LLM judge whose verdicts they do not fully trust. The wedge is **regression gating in CI**: a
paired comparison between two commits of the same agent, over the same task set, with a
deterministic verdict and a p-value — which is exactly what `--agent-ref` plus paired McNemar
already produce, and what we used this week to close a pull request on evidence rather than
opinion.

Three plausible shapes, cheapest first:

1. **Open-source harness, paid packs and hosting.** The core is the credibility; a domain pack
   with curated tasks and licensed ground truth is the thing worth paying for. Matches how
   scientific tooling actually gets adopted.
2. **CI service.** A GitHub Action running the sweep on a pull request and posting the paired
   comparison. Sells to teams already feeling the pain; needs the parallelism work in
   `plan-v0.2-hardening.md` §B to be affordable.
3. **Benchmark-as-evidence for regulated domains.** Deterministic verdicts and a provenance
   audit trail are exactly what an auditor asks for. Highest value, longest sale, most domain
   work per customer.

**The honest risks.** Evaluation tooling is a crowded, badly monetised space, and most teams
buy observability rather than grading. Curated task sets with derived keys are expensive to
produce — that is the moat and the cost at once. And the credibility argument depends on
independence: the benchmark's author currently wrote one of the agents it scores, which is the
first thing any reviewer says (`docs/roadmap-paper.md` §Independence).

The cheapest disproof: take one non-heliophysics domain and one external agent, and see whether
a pack really is an afternoon. If it is not, the boundary is in the wrong place and this is a
one-domain tool that should stay one.

## 7. A staged path that does not bet the farm

- **Stage 0 — earn the right.** Finish `plan-v0.2-hardening.md`, tag it, publish HelioAI's
  numbers. A generic harness with no published results is a library; one with results is
  evidence. Do not skip this to chase the product.
- **Stage 1 — prove the seam without moving anything.** Write a second adapter (`claude -p` is
  already mechanically verified) and score a non-HelioAI agent on the existing tasks. If the
  `Agent` protocol holds, the seam is real.
- **Stage 2 — extract `core/` in place.** Move domain content into `packs/heliophysics/` inside
  this repository. No new project, no new name. HelioBench keeps working throughout, which is
  the test.
- **Stage 3 — one foreign pack.** Pick a domain with open ground truth and a retrieval/method
  shape. Measure how long it takes. This is the go/no-go.
- **Stage 4 — only then** decide between library, CI service, or nothing, informed by how
  stage 3 actually went rather than by how it feels now.
