"""The floor.

Every benchmark needs a baseline that has no capability at all, for two reasons. It says what
a score of "nothing" looks like, so a real score can be read against something. And it
exercises the whole harness — task loading, grading, statistics, reporting — for no money and
no network, which is how the pipeline gets tested without an API key.
"""

from __future__ import annotations

from pathlib import Path

from heliobench.trace import Trace


class NullAgent:
    """Answers the same thing to everything."""

    name = "null"

    def __init__(self, reply: str = "I don't know.") -> None:
        self.reply = reply

    def describe(self) -> dict:
        return {"agent": self.name, "agent_version": "1", "provider": "none", "model": "none"}

    def preflight(self) -> list[str]:
        return []

    async def run(self, prompt: str, workdir, task_id: str = "", **kw) -> Trace:
        Path(workdir).mkdir(parents=True, exist_ok=True)
        return Trace(
            task_id=task_id, prompt=prompt, agent=self.name, reply=self.reply, env=self.describe()
        )
