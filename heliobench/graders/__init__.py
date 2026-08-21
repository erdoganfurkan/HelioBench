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
    """Dispatch to the grader for a task's tier, then hold the verdict to the process gate."""
    from heliobench.graders import numeric, retrieval

    if trace.error:
        return Result(task.id, False, f"run failed: {trace.error}")
    if task.tier == "n1":
        result = retrieval.grade(task, trace)
    elif task.tier in ("n2", "n3"):
        result = numeric.grade(task, trace)
    else:
        return Result(task.id, False, f"no grader for tier {task.tier!r}")
    return process_gate(result, trace)


def process_gate(result: Result, trace: Trace) -> Result:
    """Fail a numerically correct run that contradicts its own provenance ledger.

    This is a gate rather than a footnote because of what it means: the session computed one
    number and the answer stated another. The reference run of 2026-08-21 scored 36/36 on
    tier n3 while doing exactly that once, and a benchmark that records the contradiction in
    a table below the score is a benchmark reporting that the run passed.

    Only contradiction gates. The other process metrics — bypassed recipes, unsourced
    figures, tool errors — describe how the answer was reached and are read alongside it;
    contradiction says the answer disagrees with the session that produced it, which no
    correct run does.
    """
    if not result.passed:
        return result

    from heliobench.graders.process import collect

    n = collect(trace).contradicted
    if n:
        return Result(
            result.task_id,
            False,
            f"{n} number(s) contradicted by the session's own ledger",
            {**result.detail, "gate": "contradicted"},
        )
    return result
