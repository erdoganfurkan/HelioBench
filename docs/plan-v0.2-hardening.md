# Plan — HelioBench v0.2: trustworthy numbers, faster sweeps, more than one event

**Status:** written 2026-08-28. On 2026-09-11 sections A, B1–B4, C1–C2, D1–D5 and E1 landed on
the `v0.2-hardening` branch, one commit each; `CHANGELOG.md [Unreleased]` has the details and
the before/after regrades. Still open: **B5** (concurrency against the real agent — needs a
paid run), **C3–C4** (more shock events — needs the network and a licence-checked selection),
**E2–E4** (publication). Companion to `docs/roadmap-paper.md` (which says
what a *paper* needs) and `dev/todo.md` (which tracks what is in flight). This file is the
ordered plan for the next release.

**Goal:** a HelioBench that can be tagged, cited, and re-run months from now, whose n3 numbers
carry a meaningful confidence interval, and whose sweeps finish in minutes rather than hours.

**Ordering principle:** nothing that makes sweeps faster ships before the thing that makes
failures attributable. Parallelism multiplies infrastructure errors, and today an
infrastructure error is scored as an agent failure — speeding that up would buy time by
spending trust.

---

## A. Failure accounting — the prerequisite

Today `runner.py:85` catches every `Exception` and turns it into a trace with `error=...`,
which `grade()` scores as `passed=False`. A provider timeout is therefore indistinguishable
from a wrong answer.

This is not hypothetical. The 2026-08-25 arm on `1fcb2f0` recorded two `APITimeoutError` runs
as failures; the comparison against main only became honest after excluding them **by hand**,
and that hand-exclusion favoured the arm that happened to have the timeouts. A benchmark whose
headline moves when the network hiccups is not measuring the agent.

**A1. A third outcome: `errored`.**
- `results.csv` and `results.json` gain `outcome` ∈ {`passed`, `failed`, `errored`} beside the
  existing boolean, kept for compatibility.
- Classification lives in one function, `heliobench/graders/outcome.py`, matching on exception
  type: `APITimeoutError`, `RateLimitError`, `APIConnectionError`, `OSError` with ENOSPC, and
  anything the adapter marks as transport. Everything else stays an agent failure — the
  default must be "the agent's fault", so a new exception class cannot silently launder a real
  failure into an excused one.
- `errored` runs leave the pass-rate denominator and are reported as their own line. A tier
  with more than 10% errored runs is flagged in the report as not yet comparable.
- `pass^k` counts an errored repetition as *unknown*, not as a pass: a task with 2 passes and
  1 error reports `2/2 (1 errored)`, never `3/3`.

**A2. `report --regrade` reclassifies stored traces.** The traces already carry the exception
string, so every past run can be re-scored under the new rule with no provider calls. Run it
over the five 2026-08-25/27 arms and re-issue `results/summary_2026-08-25.md` with the
hand-exclusion replaced by the mechanical one.

**Acceptance:** re-grading the `1fcb2f0` n3 arm yields 32/34 with 2 errored, without anyone
passing a flag or editing a CSV.

---

## B. Parallelism

`run_once` is already `async`; `runner.run` calls `asyncio.run` once per repetition inside two
nested loops. The change is to hoist the event loop and bound concurrency.

**B1. `--jobs N`, default 1.** One `asyncio.run` for the sweep, an `asyncio.Semaphore(N)`
around `run_once`, results collected with `asyncio.gather(..., return_exceptions=True)`.
Stdlib only; no new dependency. Roughly 20 lines in `heliobench/runner.py`.

Ordering: results are written per task as they land, but `results.csv` is sorted by
`(task_id, run)` before writing, so a sweep's output does not depend on completion order.
Two sweeps with the same seed and different `--jobs` must produce byte-identical `results.csv`
apart from timing fields — that is the test.

**B2. Honesty about what parallelism destroys.**
- `meta.json` records `jobs`.
- The report prints wall clock as `— (jobs=8)` rather than a per-run figure whenever `jobs > 1`.
  Under contention it measures queueing, not the agent, and we used per-run wall clock on
  2026-08-26 to detect a machine suspend — that diagnostic must not silently rot.
- Token counts stay exact and stay comparable. Cost remains the honest cross-sweep metric.

**B3. The disk gate scales.** `low_disk()` currently demands 2 GB. It becomes
`2 GB + 0.5 GB × (jobs − 1)`, because each concurrent session seeds its own workspace.

**B4. Backoff before concurrency.** Retry `429` and connection resets with exponential backoff
inside the adapter, so a rate limit costs latency rather than an `errored` run. Without this,
`--jobs 8` manufactures exactly the failures A1 was built to exclude.

**B5. Confirm the agent is concurrency-safe.** HelioAI keeps a per-`(user_id, session_id)`
SQLite history in `helioai/core/session.py`, and a sqlite failure has already been observed
under disk pressure. Before enabling `--jobs > 1` by default, run `--agent null --jobs 8` (free)
and then a 12-run n2 sweep at `--jobs 4`, and diff the results against `--jobs 1`. The null
sweep is not enough on its own: it never reaches the adapter, and the adapter's per-run patch
of `registry.call_tool` was corrupting concurrent traces while the null check passed (fixed
2026-09-11, `dev/lessons.md`). Anything the adapter installs on a shared object needs a test
with two overlapping runs, not one.

**Acceptance:** an n3 sweep at `--jobs 6` finishes in under 20 minutes with the same
`results.csv` as `--jobs 1`, and zero `errored` runs attributable to concurrency.

---

## C. More than one event — the statistical problem

n3 has **one** event. The bootstrap resamples events, so its interval prints as
`[91.7%, 91.7%]`, which is not precision but an artefact. Across five arms in August 2026,
paired McNemar returned **p = 1.0 on every pair**, including between two very different
models. The tier cannot currently distinguish anything.

**C1. Un-hardcode the truth deriver.** `scripts/reference_values.py:23` points at
`/home/furkan/HelioAI/helioai/data/recipes` — an absolute path on one machine. The repo claims
its ground truth is "reproducible by anyone, forever"; that claim is false while this line
stands. Freeze the recipe functions into `heliobench/recipes/` (they are small, pure, and
already exec'd rather than imported) and record the upstream commit they were taken from.

Verified on 2026-08-28: `rankine_hugoniot` under `main` and under `fix/audit-p0` produce
identical reference values, so freezing now does not change any existing key.

**C2. Parametrise by event.** `reference_values.py` hardcodes `SHOCK`, `UP`, `DOWN` as module
constants. They become a per-event record in `fixtures/<event>/windows.json`, written by
`scripts/build_fixture.py`, so adding an event is running two scripts rather than editing one.

**C3. Add four to six shock events.** Selection constrained by licence, per
`docs/roadmap-paper.md`: NASA SPDF/CDAWeb data is CC0 and shippable; HELIO4CAST ICMECAT is
CC BY and citable; **IPShocks and the CfA list have no open licence** and may only be used as
pointer + SHA-256 + fetch script, never redistributed. Candidate criteria: clean upstream and
downstream intervals at 1-minute cadence, a compression ratio above 1.5, and at least two
spacecraft where possible.

Each event multiplies the tier: 12 tasks × 6 events = 72 n3 tasks, and the bootstrap finally
has something to resample.

**C4. Re-derive and re-digest.** Adding tasks changes `task_set_digest`, so old n3 scores stop
comparing. That is intended and must be stated in the changelog rather than papered over.

**Acceptance:** the n3 confidence interval is a range rather than a point, and a paired McNemar
between two arms that genuinely differ returns p < 0.05.

---

## D. Correctness debt already identified

Ordered by cost per sweep.

**D1. The provenance gate fires on correct answers when a ledger entry holds a vector.**
`_NAME_WINDOW = 40` attributes any nearby number to a ledger name, so a component or a
magnitude reads as contradicting the vector's scalar summary. Seen three times across five
arms, always on `n3_theta_bn`: `-0.657` vs `shock_normal_gsm`, `161 km/s` vs
`shock_speed_km_s`, `9.68 nT`/`24.97 nT` vs `B_up_gsm`. Costs about one run a sweep, at the
gate, on right answers.

**D2. Recompute provenance harness-side.** `graders/__init__.py:65` reads
`collect(trace).contradicted` — a counter the agent under test computes about itself. The one
hard gate in the benchmark is currently supplied by the candidate. The 2026-08-25
`_MIN_BARE_INT` change was legitimate and checkable in the traces, which is precisely why the
general case is not: an agent could widen its own blind spot and pass the gate unnoticed.
Recompute from the ledger and the reply inside the harness; keep the agent's own number beside
it and report disagreement between the two.

**D3. `_TOOL_OUTPUT_LIMIT = 4000` in the HelioAI adapter truncates tool output**, so an
accepted identifier past the cut is recorded as "never returned" and corrupts the n1 rank
metric. The `truncated` flag is already recorded but read by nobody. Surface it in the report
and exclude truncated runs from recall@k.

**D4. `heliobench compare <runA> <runB>`.** `stats.py:mcnemar` has no CLI surface; every paired
comparison in this project so far was run by hand from a scratch script. The command refuses
when `task_set_digest` differs, and prints `only_a`, `only_b`, `p`, and the tasks that moved.

**D5. Two documentation lies.** `CLAUDE.md` still says "58 tasks × 3 = 174"; the real figure
after the n2 trim is 47 × 3 = 141. `cli.py --provider` defaults to `groq` while the HelioAI
adapter defaults to `azure`, so `run --agent helioai` with no flag lands somewhere nobody
intended.

---

## E. Version, publish, cite

**E1. Tag v0.1 as it stands** before any of the above lands, so the five August arms remain
reproducible against a fixed digest. `CHANGELOG.md` `[Unreleased]` becomes `[0.1.0]`.

**E2. Curate the results.** `results/summary_2026-08-25.md` currently accretes arms by
appending. Split into one file per campaign with a stable header: agent ref, provider, model,
`task_set_digest`, run dir, and the score table. A reader must be able to tell in ten seconds
which numbers compare.

**E3. Publish the results on the HelioAI side.** A benchmark with no published numbers is a
tool; a benchmark with numbers is evidence. HelioAI's README and docs get a results table
naming the digest and the harness version, linking back here. Update it per release, not per
run.

**E4. Reporting artefacts for a venue**, from `docs/roadmap-paper.md`: the datasheet, Croissant
metadata with Responsible AI fields, grader false-accept rate against human-checked answers,
and an error taxonomy with an agreement statistic.

---

## Suggested order

1. **A** (failure accounting) — unblocks honest comparison and is a prerequisite for B.
2. **E1** (tag v0.1) — freeze what exists before changing digests.
3. **D4, D5** (compare CLI, doc lies) — hours, and D4 removes hand-run statistics.
4. **B** (parallelism) — makes everything after it cheaper to iterate on.
5. **C** (events) — the largest piece, and the one that decides whether n3 means anything.
6. **D1–D3** (provenance and truncation) — can proceed in parallel with C.
7. **E2–E4** (publication) — once the digest is stable again.
