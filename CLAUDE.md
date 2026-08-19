# HelioBench

A benchmark for scientific agents in heliophysics. You are here to **run** it and explain
what it produced.

@docs/what-this-measures.md

## The rule that overrides everything else

**You never decide whether an answer was right.** Verdicts come from `heliobench/graders/`,
which is deterministic code with no model in the loop. That is the property the whole project
rests on: benchmarks scored by a language model get taken apart on position bias and
self-preference, and the ones that survive review have programmatic graders.

If a grader gives a verdict you disagree with, fix the grader and add a test. Do not overrule
it in prose.

## Getting started

Use the `heliobench` skill (`/heliobench`). It knows the commands, the order to run them in,
and how to read a report.

Always `verify` before `run` — the search-index check fails open, so a missing index looks
like a flawless score. And a real run spends the user's API quota: 58 tasks × 3 repetitions
is 174 agent runs. Agree on that before starting one.

## Working on this repo

`dev/lessons.md` is a ledger of past mistakes and the rule that closed each one — read it
before a non-trivial change, and append to it after any fix that wasn't obvious in advance.
`dev/todo.md` tracks what's in flight; `docs/roadmap-paper.md` has the longer-range reasoning.
(Don't confuse `dev/` with `tasks/` — the latter holds the benchmark's own task YAMLs, and
editing one of those changes `task_set_digest`, not a lesson learned.)

## Ground rules for changing the benchmark

- **A task's answer key is measured, never remembered.** `scripts/build_fixture.py` freezes
  the data; `scripts/reference_values.py` derives the truth from the frozen bytes. Adding a
  task means running those, not typing a number.
- **Every task declares its `provenance` and `licence`.** No third-party catalogue is
  redistributed here without an open licence.
- **Editing a prompt changes `task_set_digest`**, and scores across different digests are not
  comparable. That is intentional.
- `ruff format` and `ruff check` before committing; the tests audit that every shipped task is
  solvable, rejects silence, and rejects an answer off by half.
