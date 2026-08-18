"""Deciding whether a run was right.

Graders read a `Trace` and nothing else. They never import the agent, never touch the
network, and never ask a model — which is what lets them run in CI with no provider
installed, and what lets a stored run be re-graded years later when the grader has improved
and the agent no longer exists in that version.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from heliobench.tasks import Task
from heliobench.trace import Trace


@dataclass
class Result:
    """The verdict on one run of one task.

    `detail` carries whatever the grader wants a human to see when the verdict is disputed —
    which numbers it found, which ids it accepted. A benchmark whose failures cannot be
    inspected is a benchmark nobody trusts twice.
    """

    task_id: str
    passed: bool
    reason: str = ""
    detail: dict = field(default_factory=dict)


def grade(task: Task, trace: Trace) -> Result:
    """Dispatch to the grader for a task's tier."""
    from heliobench.graders import numeric, retrieval

    if trace.error:
        return Result(task.id, False, f"run failed: {trace.error}")
    if task.tier == "n1":
        return retrieval.grade(task, trace)
    if task.tier in ("n2", "n3"):
        return numeric.grade(task, trace)
    return Result(task.id, False, f"no grader for tier {task.tier!r}")
