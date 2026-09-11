"""What one agent run left behind.

A Trace is the only thing graders are allowed to look at. Separating "run the agent" from
"decide whether it was right" is what makes a stored run re-gradable months later, and what
keeps a grader from accidentally depending on live state that no longer exists.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class TokenUsage:
    """Tokens spent on one run.

    `exact` is not a formality. Cost per task is a reporting requirement, and an estimate
    presented as a measurement is the kind of number that gets a paper rejected — so the
    field travels with the count and lands in the report header.
    """

    prompt: int = 0
    completion: int = 0
    calls: int = 0
    exact: bool = True


@dataclass
class Trace:
    """One agent run over one task.

    Attributes:
        events: The agent's event stream, each entry with a `t` field in seconds since the
            run started. Kept raw: a grader written later must not be limited to the fields
            that seemed interesting when the run happened.
        ledger: The session provenance ledger — which numbers a computation actually
            produced, as opposed to which numbers the model wrote down.
        error: Set when the run failed. A failed run is scored as a miss, never dropped:
            silently discarding failures inflates every score above it.
        error_kind: The adapter's own word on `error`, when it has one. `"transport"` says
            the failure was the provider or the network rather than the agent, and
            `graders.outcome` scores it as errored instead of failed. Left empty, the
            exception class in `error` decides.
    """

    task_id: str
    prompt: str
    agent: str
    reply: str = ""
    events: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    ledger: dict = field(default_factory=dict)
    tokens: TokenUsage = field(default_factory=TokenUsage)
    wall_s: float = 0.0
    error: str | None = None
    error_kind: str | None = None
    env: dict = field(default_factory=dict)

    def events_named(self, name: str) -> list[dict]:
        """Every event of one kind, in order."""
        return [e for e in self.events if e.get("event") == name]

    def tool_calls(self) -> list[str]:
        """Names of the tools the agent called, in order, repeats included."""
        return [e["data"]["name"] for e in self.events_named("tool_call")]

    @property
    def n_iterations(self) -> int:
        """LLM turns the run consumed, or 0 if it never reported being done."""
        done = self.events_named("done")
        return int(done[-1]["data"].get("n_iterations", 0)) if done else 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Trace:
        d = dict(d)
        d["tokens"] = TokenUsage(**(d.get("tokens") or {}))
        return cls(**d)

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path

    @classmethod
    def read(cls, path: Path) -> Trace:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
