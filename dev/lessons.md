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
