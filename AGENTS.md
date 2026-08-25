# AGENTS.md — HelioBench

A benchmark for scientific agents in heliophysics. You are here to **change the harness**,
not to run the benchmark. A real run costs the maintainer's API quota and produces
non-deterministic scores; do not start one.

`CLAUDE.md` in this repo is written for an assistant whose job is to *run* the benchmark.
Read it for the domain rules below, but this file governs what you do.

## The rule that overrides everything else

**You never decide whether an answer was right.** Verdicts come from `heliobench/graders/`,
deterministic code with no model in the loop. Benchmarks scored by a language model get taken
apart on position bias and self-preference; the ones that survive review have programmatic
graders.

If a grader gives a verdict you disagree with, fix the grader and add a test. Do not overrule
it in prose, and do not add a model to the scoring path.

## How to verify your change

Everything below runs offline, with no API key and no network to data providers:

```bash
python -m pytest              # the suite audits that every shipped task is solvable,
ruff format --check .         # rejects silence, and rejects an answer off by half
ruff check .
python -m heliobench.cli run --agent null  # exercises loading, grading, statistics and reporting
```

If you touched anything under `heliobench/graders/`, `heliobench/stats.py`,
`heliobench/report.py` or `tasks/`, also regrade a stored run and **paste the before/after
scores into the pull request**.

`--regrade` **rewrites `meta.json` and `results.json` inside the run directory**, so copy the
run first and regrade the copy. Never regrade a run in place:

```bash
cp -r results/<a stored run> /tmp/regrade && \
  python -m heliobench.cli report /tmp/regrade --regrade
```

`--regrade` re-scores stored traces with today's graders. It costs nothing: graders read
traces, never the agent. Stored runs live under `results/` and `heliobench-results/`.

A pull request that changes scoring without a `--regrade` comparison will be rejected.

## Off limits

- **Never run `heliobench run --agent helioai`.** It spends real API quota. `--agent null` is
  the only arm you may run.
- `fixtures/`, `results/` and `heliobench-results/` are frozen evidence. Never regenerate or
  edit them, and never commit a modification to one — regrade a copy instead (see above).
- Do not add dependencies. The runtime set is `pyyaml` and `numpy`, and the comment above it
  in `pyproject.toml` explains why that is a deliberate floor rather than an accident.
- Do not touch `docs/what-this-measures.md` conclusions without the measurement behind them.

## Ground rules for changing the benchmark

- **A task's answer key is measured, never remembered.** `scripts/build_fixture.py` freezes
  the data; `scripts/reference_values.py` derives the truth from the frozen bytes;
  `scripts/n1_key_candidates.py` enumerates accepted identifiers out of the search index.
  Adding a task means running those, not typing a number.
- **A task is defective when a defensible answer exists that its key rejects.** Widen the key
  or harden the prompt — `docs/what-this-measures.md` says which, and why hardening leaves old
  runs unscored rather than re-scored.
- **Every task declares its `provenance` and `licence`.** No third-party catalogue is
  redistributed here without an open licence.
- **Editing a prompt changes `task_set_digest`**, and scores across digests are not
  comparable. That is intentional — say so in the pull request when you do it.

## Repo conventions

- `dev/lessons.md` is a ledger of past mistakes and the rule that closed each one. Read it
  before a non-trivial change; append to it after any fix that was not obvious in advance.
- `dev/todo.md` tracks what is in flight. `docs/roadmap-paper.md` holds longer-range reasoning.
- Do not confuse `dev/` with `tasks/`: the latter holds the benchmark's own task YAMLs, and
  editing one changes `task_set_digest`, not a lesson learned.
- Python >= 3.12. `ruff` `line-length = 100`; the lint `select` is pinned explicitly in
  `pyproject.toml` and must stay pinned.
- Public functions and classes need docstrings, and a docstring documents the *decision*
  behind the code rather than paraphrasing the signature.
- Never add `Co-Authored-By` trailers to commits.
