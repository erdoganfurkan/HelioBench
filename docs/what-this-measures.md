# What HelioBench measures

Three tiers, ordered from the least arguable to the most.

**n1 — retrieval (30 tasks).** Resolving a physical quantity to an archived product
identifier out of 82 433. The verdict is string equality against identifiers enumerated from
the index by `scripts/n1_key_candidates.py`, so there is no physics to dispute. This is the
tier no existing benchmark covers, and the one closest to what makes a heliophysics agent
useful or useless.

**n2 — formulary (16 tasks).** Plasma beta, Alfvén speed, Debye length, gyrofrequency,
inertial length, from stated inputs across three regimes. Reference values computed by calling
PlasmaPy. Boring on purpose: it is the floor, and a floor has to be unarguable.

**n3 — method (12 tasks).** Real analysis of the 17 March 2015 interplanetary shock, with the
averaging windows and the method stated in the prompt. Ground truth is derived from a frozen
fixture by the shipped recipe functions, so the answer is arithmetic rather than opinion. The
data replays offline; nothing is downloaded during a run.

## Alongside correctness

Every run also records how the answer was reached: numbers the session's provenance ledger
contradicts or cannot source, calibrated methods that were reimplemented from memory,
invented identifiers, tool efficiency, cost, and `pass^k` across repetitions.

These are the numbers that move when an agent's architecture changes but its accuracy does
not. An agent that reaches the right answer while stating figures no computation produced is
an agent that will be wrong next week.

## When the benchmark is the thing that is wrong

**A task is defective when a defensible answer exists that its key rejects.** Present in the
index is not enough: if the index describes a second product in the words of the prompt, an
agent naming it was right and the task was under-specified.

The choice is then to widen the key or to harden the prompt, and it is a choice about what
the task is for. Widen when the products are genuinely interchangeable for the question
asked. Harden when telling them apart is itself the skill worth measuring — distinguishing
definitive data from a real-time feed, or an L2 dataset from an on-board fit, is not a
technicality an agent may be excused from. Hardening changes `task_set_digest`, so the runs
that answered the old wording do not carry over; they are unscored, not re-scored.

The reference run of 2026-08-21 is the reason this is written down: 3 of its 5 n1 failures
were broken keys and 2 were real, so the benchmark was wrong more often than the agent under
test. That is the failure mode automated auditors keep finding in published benchmarks, and
the only defence is deriving each key from the index by script instead of from memory.

## What passing does not mean

Passing a task means agreeing with a reference implementation under a stated method. It is
not a claim that the physics was done well, and not evidence that any individual result is
scientifically sound.
