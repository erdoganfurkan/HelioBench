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
pip install -e ".[dev]"          # the harness alone — no agent, no network
heliobench list
```

To benchmark HelioAI, add the agent and give it credentials **explicitly**:

```bash
pip install -e ".[dev,helioai]"
HELIOAI_LLM_PROVIDER=azure AZURE_OPENAI_API_KEY=... AZURE_OPENAI_ENDPOINT=... \
  heliobench verify --agent helioai --index-dir /path/to/chroma
heliobench run --agent helioai --runs 3
```

HelioBench does not inherit an agent's `.env`. HelioAI discovers one by walking up from the
working directory, which is convenient for a clone and wrong for a benchmark: a score that
depends on which directory it was launched from is not a score. Credentials are passed in,
and `verify` warns when a discoverable `.env` could still inject anything left unpinned.

`verify` before `run`, always. The invented-identifier check fails open — an unreachable
search index makes fabrication look flawless — and `verify` is what catches that.

A full run is 58 tasks x 3 repetitions = 174 agent runs against a paid provider. `--agent
null` and `--task <id>` are the cheap ways to exercise the machinery.

## From Claude Code

Clone it, run `claude` from the repository, and use `/heliobench`. The skill runs the
deterministic CLI and explains the report; it never decides whether an answer was right, and
it is pinned to Sonnet because reading a report does not need a larger model.

To reach it from any other project, install it as a plugin:

```bash
claude plugin marketplace add /path/to/HelioBench
claude plugin install heliobench@heliobench
export HELIOBENCH_PYTHON=/path/to/HelioBench/.venv/bin/python   # or pip install heliobench
```

An installed plugin is a **snapshot of one commit** — its tasks, its graders and its fixtures
all come from there, which is what makes a score attributable. The interpreter is the one
thing it borrows, and it borrows only the dependencies: the snapshot's own package still wins
on `sys.path`. Reports are written to the directory you invoked it from, never into the plugin
cache, which is erased on every reinstall.

Installing from a local path copies the whole working tree, `.venv` included — around 100 MB
per snapshot, and a new one per commit since the plugin is versioned by commit. Installing
from the GitHub source instead clones it, and does not.

## Licence

MIT. Task ground truth in v0.1 is derived entirely from open reference implementations and
the public speasy inventory; each task file carries its own `provenance` and `licence` field.
