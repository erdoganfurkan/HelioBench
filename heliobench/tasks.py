"""Task definitions: load and validate the YAML task files.

A task is data, never code. The benchmark must be auditable by someone who does not run it,
and a reviewer reading `tasks/` should be able to see the whole contract: what is asked, what
counts as right, where the truth came from, and under what licence it may be redistributed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

TIERS = ("n1", "n2", "n3")

_REQUIRED = ("id", "tier", "prompt", "expected", "provenance")


@dataclass(frozen=True)
class Task:
    """One benchmark item.

    `event` is the clustering key, not decoration: several tasks built on the same physical
    event are correlated, and a confidence interval that ignores that understates its own
    error. Tasks with no natural event cluster alone under their own id.
    """

    id: str
    tier: str
    prompt: str
    expected: dict
    provenance: str
    event: str = ""
    tolerance: dict = field(default_factory=dict)
    licence: str = "internal"
    fixture: str = ""
    path: Path | None = None

    def __post_init__(self) -> None:
        if not self.event:
            object.__setattr__(self, "event", self.id)


class TaskError(ValueError):
    """A task file that cannot be trusted to score anything."""


def _load_one(path: Path) -> Task:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TaskError(f"{path}: expected a mapping at the top level")
    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        raise TaskError(f"{path}: missing required key(s) {missing}")
    if raw["tier"] not in TIERS:
        raise TaskError(f"{path}: tier {raw['tier']!r} not one of {TIERS}")
    if not isinstance(raw["expected"], dict):
        raise TaskError(f"{path}: `expected` must be a mapping")
    known = {f for f in Task.__dataclass_fields__ if f != "path"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise TaskError(f"{path}: unknown key(s) {unknown}")
    return Task(path=path, **raw)


def load_tasks(tasks_dir: str | Path, tiers: list[str] | None = None) -> list[Task]:
    """Every task under `tasks_dir`, sorted by id, optionally restricted to some tiers.

    Raises on the first malformed file rather than skipping it: a task set that silently
    shrinks is a benchmark whose denominator moved without anyone noticing.
    """
    root = Path(tasks_dir)
    tasks = [_load_one(p) for p in sorted(root.rglob("*.yaml"))]
    seen: dict[str, Path] = {}
    for t in tasks:
        if t.id in seen:
            raise TaskError(f"duplicate task id {t.id!r} in {t.path} and {seen[t.id]}")
        seen[t.id] = t.path
    if tiers:
        tasks = [t for t in tasks if t.tier in set(tiers)]
    return sorted(tasks, key=lambda t: t.id)
