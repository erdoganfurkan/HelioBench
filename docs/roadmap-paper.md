# What v0.1 is not yet, and what it would take

v0.1 is a working instrument with a small task set. Publishing it as a benchmark paper needs
more, and the gaps are known rather than hoped away.

## Scale

47 tasks over 18 event clusters. At a success rate near 35%, a 100-task benchmark cannot distinguish
an agent at 35% from one at 45% in an unpaired comparison. Archival venues expect roughly
**250 tasks over ≥100 independent events**. Everything in the harness — event clustering,
bootstrap intervals, paired McNemar — is already built for that number; only the tasks are
missing.

Report only the comparisons the sample supports. Two arms over the same tasks compare with
McNemar; two independent numbers with overlapping intervals do not compare at all.

## Independence

The benchmark's author wrote one of the agents it scores. That is the first thing a reviewer
will say, and it is correct. Three mitigations, in order of weight:

1. **Task authors who are not the agent's author.** The PyHC community is the natural pool,
   and co-authorship is the honest way to ask.
2. **At least three external scaffolds evaluated** beside HelioAI — a bare tool-using LLM,
   Claude Code, and one general agent framework. The `Agent` protocol exists for this and has
   one method precisely so a third party can implement it in an afternoon.
3. **Publish the benchmark separately from the agent.** Two papers, not one.

## Ground truth beyond this repository

v0.1 derives everything from open reference implementations and frozen NASA/CDAWeb data, so
nothing here is redistributed without a licence that allows it. Scaling means external
catalogues, and their terms differ sharply:

| Source | Licence | Usable how |
|---|---|---|
| NASA SPDF / CDAWeb / OMNI | CC0 | ship it |
| Kp (GFZ, doi:10.5880/Kp.0001) | CC BY 4.0 | ship it, cite it |
| HELIO4CAST ICMECAT | CC BY | ship it, cite it |
| IPShocks (Helsinki), CfA shocks | no open licence | pointer + checksum + fetch script |
| WDC Kyoto (Dst, SYM-H) | terms, not a licence | use the OMNI mirror instead |
| SuperMAG | asks for co-authorship when central | not usable at benchmark scale |

The default distribution model for anything without an open licence is **pointer + SHA-256 +
fetch script + hashed answer key**. It respects the terms, and it keeps the answer key off the
open web, which is also the cheapest contamination defence available.

## The ground truth that is itself a model output

θ_Bn, shock normals, substorm onsets and ICME boundaries are all method-dependent, and
published catalogues disagree with each other on the same events. Three responses, all of
which v0.1 already starts:

1. **State the method in the task.** Done — every n3 prompt names its windows and its formula.
2. **Use inter-catalogue disagreement as the tolerance band**, and publish that distribution.
   This turns the weakness into a contribution: nobody has quantified it for this domain.
3. **Score the pipeline, not only the scalar** — whether the right intervals were identified,
   whether the jump conditions were applied — which is what the process metrics already do.

## Contamination

Not yet addressed. The cheap probes, in order of value: perturb a task's inputs and check the
answer moves; hold out a private split; and check whether an agent reproduces a published
value it was never given the data for.

## Reporting

For a datasets-and-benchmarks venue: Croissant metadata with the Responsible AI fields, a
completed datasheet (`datasheet.md`, outline already in place), per-task licence and
provenance (already in every task file), grader false-accept rate measured against
human-checked answers, an error taxonomy with an agreement statistic, and cost per task
(already reported).

## Candidate venues

NeurIPS Evaluations & Datasets · *Scientific Data* · *Astronomy & Computing* — with JOSS
reserved for the agent, not for this.
