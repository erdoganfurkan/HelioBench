"""The one thing an agent must be able to do to be benchmarked.

Kept to a single method on purpose. Every constraint beyond "given a prompt and a working
directory, produce a Trace" would encode an assumption about how HelioAI happens to be
built, and the benchmark stops being about heliophysics agents the moment it does.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from heliobench.trace import Trace


@runtime_checkable
class Agent(Protocol):
    """An agent under test."""

    name: str

    def describe(self) -> dict:
        """Everything a reader needs to reproduce this arm: version, provider, model
        snapshot, temperature, and whatever else moves the numbers. Lands in the report
        header verbatim."""
        ...

    def preflight(self) -> list[str]:
        """Problems that would make the results meaningless, as human-readable strings.

        Empty means ready. Checked before a run rather than after, because the failure this
        exists for is the silent one: a missing search index makes the hallucination metric
        read as a perfect score.
        """
        ...

    async def run(self, prompt: str, workdir, task_id: str = "") -> Trace:
        """Answer one prompt in `workdir` and return what the run left behind."""
        ...
