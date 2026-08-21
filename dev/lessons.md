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
