# HelioBench

A benchmark for **scientific agents in heliophysics**: can an agent find the right product
among tens of thousands, retrieve it, handle the fill values, and compute something a
physicist would accept?

Existing science-agent benchmarks stop short of that. The closest neighbour,
[*Reasoning With a Star*](https://arxiv.org/abs/2511.20694) (NeurIPS ML4PS 2025), is 158
closed-form textbook questions answered **without tools, without archives, without real
data**. HelioBench measures the part that was missing.

## The rule that shapes everything here

> **The harness runs and reports. It never grades.**

Every verdict comes from deterministic code — string comparison, unit-aware numeric
tolerance, arithmetic. No LLM judge decides whether an answer is right. Benchmarks scored by
a model get taken apart on position bias and self-preference; the ones that survive review
(SciCode, DS-1000, DABStep, Gravity-Bench) do not have a judge in the loop.

## Three tiers

| Tier | What it measures | Ground truth |
|---|---|---|
| **n1** retrieval | resolving a product out of ~83 000 | the speasy inventory itself |
| **n2** formulary | deterministic plasma physics from stated inputs | PlasmaPy |
| **n3** method | analysis with the method imposed, on real spacecraft data | vetted reference implementations |

Tier n3 always names the method ("by magnetic coplanarity, upstream window [t1,t2]"), because
a shock normal is a model output, not a measurement: coplanarity, mixed-mode and
Rankine-Hugoniot fits disagree on the same event. Without a specified method there is nothing
defensible to compare against.

Alongside correctness, every run records **process metrics**: numeric provenance, whether a
vetted method was used or reimplemented from memory, invented identifiers, tool efficiency,
cost per task, and `pass^k` over repeated runs — because a result you cannot get twice is not
a result.

## Status

v0.1 in development. Not yet released.

## Install

```bash
pip install -e ".[dev]"
heliobench list
```

## Licence

MIT. Task ground truth in v0.1 is derived entirely from open reference implementations and
the public speasy inventory; each task file carries its own `provenance` and `licence` field.
