# What HelioBench measures

Three tiers, ordered from the least arguable to the most.

**n1 — retrieval (30 tasks).** Resolving a physical quantity to an archived product
identifier out of 82 433. The verdict is string equality against identifiers verified present
in the index at authoring time, so there is no physics to dispute. This is the tier no
existing benchmark covers, and the one closest to what makes a heliophysics agent useful or
useless.

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

## What passing does not mean

Passing a task means agreeing with a reference implementation under a stated method. It is
not a claim that the physics was done well, and not evidence that any individual result is
scientifically sound.
