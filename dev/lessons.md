# Lessons

A ledger of mistakes made while building this repo, and the rule that closed each one.
Read before a non-trivial change. Append after any fix that wasn't obvious in advance —
a lesson only pays for itself if it gets read back in the next session.

Format: `[date] | what went wrong | rule to avoid it`

---

`2026-08-21` | Three n1 answer keys were written from what the author remembered the
catalogue held, so the keys rejected identifiers the index describes in the exact words of
the prompt. The reference run scored those as agent failures and the summary was published
saying so — the benchmark was wrong more often than the agent it measured (3 broken tasks
against 2 real failures). | Enumerate an n1 key with `scripts/n1_key_candidates.py` and
record the query in the task's `provenance`. A regex sweep over the whole index, never a
top-k search: top-k is built to hide the rest of the defensible answers, which are exactly
what the key has to contain.

`2026-08-21` | Fixing the above by hardening two prompts made the stored traces useless for
those tasks — the agent had answered a different question, and re-grading them against the
new wording would have repeated the original mistake in the other direction. | When a prompt
changes, its earlier runs are unscored, not re-scored. Widening a key is the only edit that
lets old traces carry over, because the question stayed the same.

`2026-08-21` | Tier n2 scored 16/16 with `pass^3` at 100% on 1.0 tool call per run, three
sweeps in a row, and stayed at 16 tasks because a full tier looked like thoroughness. It was
512k tokens a sweep buying no information, on a quota that cannot fit one full iteration in a
day. | A tier that no arm has ever failed is a regression guard, not a measurement. Keep one
task per code path and spend the budget where the pass rate still moves.

`2026-08-21` | n3 ground truth is derived from frozen bytes by a method the prompt states,
and the tolerance was still 5–10% — wide enough to accept a number reached some other way,
on the one tier built to detect exactly that. The runs themselves showed it: worst deviation
0.33%, most exact to the digits printed. | Set a tolerance from what the method can actually
reproduce, not from what feels safe. Where the fixture is frozen, the slack is rounding and
nothing else.

`2026-08-21` | The n3 sweep reported 36/36 with one answer contradicted by the session's own
provenance ledger, and the contradiction was printed in a table under the score. A reader
takes the score. | A process signal that cannot fail a run is decoration. Contradiction is a
gate in `graders/__init__.py`; the softer signals stay beside the score, and the difference
is deliberate.

`2026-08-21` | Launched a 90-run sweep without looking at free disk space. It died at run 69
with the quota already spent, and the error was a sqlite failure inside HelioAI's agent loop
— nothing in it said "disk". The space had been eaten by leftovers from earlier runs: each
tier-n3 session workspace is seeded with a ~37 MB copy of the speasy inventory, and 36 of
them sat in `/tmp` from the previous sweep. | `verify` now fails under 2 GB free where the
agent writes. Check what a sweep leaves in `$TMPDIR` after it finishes, and read the whole
preflight before spending money — the check exists because the failure is silent, expensive
and hours from where it is felt.

`2026-08-21` | Recovering those 69 runs meant grading stored traces against corrected keys,
which had already been done by hand twice that day. | `heliobench report --regrade` does it
in code. A benchmark whose numbers are recomputed by hand publishes numbers nobody can
reproduce, including the person who counted them.

`2026-08-21` | The corrected n1 sweep still failed `n1_mms_fgm` 3/3 with the same two invented
ids, although HelioAI's detect-and-retry fix had been written that morning. The fix is in
HelioAI's working tree; the harness runs the snapshot installed in its own virtualenv, which
predates it. The run log says which: `lead_invented_ids` against the fixed
`lead_invented_ids_retry`. | An agent fix is not measured until it is installed. Before
reading a re-run as evidence that a fix worked, check the code the harness actually imported
— the report header pins the version, and a version number does not move for an unreleased
fix.

`2026-08-21` | A fourth defective key surfaced only after the rank metric existed: the two
failures whose accepted id was never returned looked exactly like the ones where it was
returned and passed over. | Attribution before diagnosis. A pass rate cannot say whether a
retrieval tier failed at retrieval or at selection, and every fix for one is a waste of time
on the other.

`2026-08-25` | `--agent-ref` re-runs the CLI by replacing the process image, and the first
version did it with `os.execv` — which inherits the *current* environment, silently dropping
the freshly built `HELIOBENCH_AGENT_REF` and `PYTHONPATH`. The re-executed run would have
imported the installed agent and found no harness on `sys.path`. | `os.execv` does not take an
environment; `os.execve` does. When the whole point of re-executing is a modified environment,
pass it explicitly — and lock it with a test that monkeypatches `os.execve` and asserts on the
captured env, not just on the code that built it.

`2026-09-11` | The one hard gate read `collect(trace).contradicted`, a counter the agent under
test computed about itself. Checked against the 236 stored n3 traces it had fired ten times,
every one on a correct answer — a vector component read against the vector's scalar summary,
a magnitude read against its components, a literature value quoted beside the right result.
Three attempts to gate the *prose* harness-side (name within N chars, same unit, within a
quarter of the ledger value) each flagged only correct runs: range endpoints, inputs restated,
published values. | A verdict the candidate supplies is a report, not a gate. And a gate on
free text is a gate on how the agent writes; the only thing the evidence supports gating is
the graded answer itself: sourced from the ledger, or contradicted by a same-unit scalar
beside it. Before adding any gate, run the candidate rule over every stored trace and read
each hit — the stored runs are the only ground truth for the gate's own false-positive rate.

`2026-09-11` | A provider `400 BadRequestError` (a missing session header on the opencode
side) made the 2026-09-09 n1 sweep score 0/30, and it sat in `results/` as a 0% arm. Two
`APITimeoutError` runs on 2026-08-25 had already been excluded by hand to make a comparison
honest. | `errored` is a third outcome, classified by exception class with the default being
"the agent's fault", and `report --regrade` reclassifies stored runs for free. Never exclude
a run by hand: the exclusion favours whichever arm happened to fail.

`2026-09-11` | `reference_values.py` exec'd the n3 recipes from `/home/furkan/HelioAI/...` for
three weeks under a docstring claiming the truth was "reproducible by anyone, forever". |
Anything the truth depends on lives in the repository, byte-for-byte, with the upstream
commit and a hash a test checks. `--check` proves the stored reference reproduces; a test
runs it in CI.

`2026-09-11` | `--jobs N` shipped with `--agent null --jobs 8` writing the same `results.csv`
as `--jobs 1`, and that was taken as evidence the sweep was concurrency-safe. The HelioAI
adapter's tool-output recorder monkeypatched a module-level singleton (`registry.call_tool`)
per run and restored it on exit; two concurrent runs nested the wrappers, both traces got
both runs' tool output, and the first to finish unwrapped the second, which recorded nothing
from then on. The null agent never calls the registry, so the check exercised the runner and
not the seam. | Anything patched on a shared object for the duration of a run is a bug the
moment two runs overlap. Patch once and dispatch on the asyncio task context
(`contextvars`), as HelioAI itself does for its workspace state. And a concurrency test on a
path the null agent skips is not a concurrency test: the recorder now takes an injectable
registry so CI, which installs no agent, can run two overlapping runs through it.
