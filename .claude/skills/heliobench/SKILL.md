---
name: heliobench
description: Run the HelioBench benchmark against a heliophysics agent and explain the results. Use when asked to benchmark an agent, score HelioAI, compare two agents or two versions, check for a regression, or read an existing benchmark report.
argument-hint: "[verify|run|report] [--agent helioai|null] [--tier n1|n2|n3]"
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/heliobench.sh *), Read, Glob, Grep
---

# HelioBench

You are running a benchmark, not judging one.

## The one rule

**Never decide whether an answer was right.** Every verdict in this repository comes from
deterministic code — string comparison against verified product identifiers, unit-aware
numeric tolerance, arithmetic. Your job is to run that code, read what it produced, and
explain it.

If you find yourself about to write "this answer looks correct", stop. Run the grader. If the
grader is wrong, that is a bug to fix in `heliobench/graders/`, with a test — not a judgement
to make in conversation.

## Running it

Everything goes through one script, which forwards to the CLI:

```
${CLAUDE_SKILL_DIR}/scripts/heliobench.sh verify --agent helioai
${CLAUDE_SKILL_DIR}/scripts/heliobench.sh run --agent helioai --runs 3
${CLAUDE_SKILL_DIR}/scripts/heliobench.sh run --agent null --runs 1      # costs nothing
${CLAUDE_SKILL_DIR}/scripts/heliobench.sh report results/<run-dir>
```

**Always `verify` before `run`.** A run against an unreachable search index scores a perfect
zero on invented identifiers — the check fails open, so absence of the index looks like
flawless behaviour. `verify` catches that, plus missing fixtures and inherited `.env` files.

**A real run spends the user's API quota.** 58 tasks × 3 repetitions is 174 agent runs. Say
what that will cost in calls before starting one, and get agreement. `--agent null` and
`--tier n2` are the cheap ways to check the machinery.

## Reading a report

The report leads with mean accuracy per tier and a 95% interval bootstrapped over *events*,
not tasks. Point out these things, in this order:

1. **The gap between `pass^k` and `pass≥1`.** That gap is how much of the score is luck. A
   tier where they are far apart has a reproducibility problem, not an accuracy problem, and
   the accuracy number should not be quoted without it.
2. **The process table.** Invented identifiers, bypassed recipes, and numbers the ledger
   contradicts are failures even on tasks that passed. An agent that reaches the right answer
   while stating figures no computation produced will be wrong next week.
3. **Cost.** Tokens per run, and whether the count is exact. An inexact count is flagged; do
   not quote it as if measured.
4. **Which tasks failed and why.** `results.csv` and `traces/<task>.<run>.json` hold the full
   event stream of every run. When asked why something failed, read the trace — do not guess
   from the reply text.

## Comparing two runs

Only compare runs whose `task_set_digest` matches in `meta.json`. Different digests mean
different questions were asked, and the numbers are not comparable — say so rather than
comparing them anyway.

For two arms over the same tasks, the paired McNemar test in `heliobench/stats.py` is the
right comparison. Overlapping confidence intervals are **not** evidence of no difference when
the arms answered the same questions.

## What this benchmark does not claim

Passing a task means agreeing with a reference implementation under a stated method. It does
not mean the physics was done well, and it is not evidence that any individual result is
scientifically sound. Say so if someone reads the score that way.
