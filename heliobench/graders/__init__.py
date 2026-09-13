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
        return retrieval.grade(task, trace)
    if task.tier in ("n2", "n3"):
        return process_gate(numeric.grade(task, trace), trace, task)
    return Result(task.id, False, f"no grader for tier {task.tier!r}")


def process_gate(result: Result, trace: Trace, task: Task) -> Result:
    """Fail a numerically correct run whose answer is not the number its session computed.

    This is a gate rather than a footnote because of what it means: the session computed one
    number and the answer stated another. The reference run of 2026-08-21 scored 36/36 on
    tier n3 while doing exactly that once, and a benchmark that records the contradiction in
    a table below the score is a benchmark reporting that the run passed.

    The verdict is recomputed here from the ledger and the reply, not read from the agent's
    own `provenance` event. Until 2026-09-11 it was, and the one hard gate in the benchmark
    was a number the candidate supplied about itself — one that also fired on ten correct
    answers across the stored sweeps, every time on a vector component, a vector magnitude or
    a literature value quoted beside the right result. Its count is still collected and
    reported beside the harness's, so a disagreement between the two is visible.

    Only the graded answer gates. The other process metrics — bypassed recipes, unsourced
    figures in the prose, tool errors — describe how the answer was reached and are read
    alongside it; a contradicted answer disagrees with the session that produced it, which no
    correct run does.
    """
    if not result.passed:
        return result

    from heliobench.graders.provenance import check_answer

    pa = check_answer(
        result.detail.get("hits", []),
        task.expected.get("units", ""),
        trace.ledger,
        result.detail.get("hits_text"),
    )
    detail = {**result.detail, "provenance": pa.as_dict()}
    if pa.answer_contradicted:
        c = pa.answer_contradicted[0]
        return Result(
            result.task_id,
            False,
            f"answer {c['stated']:g} {c['units']} contradicts the session's own "
            f"{c['name']} = {c['computed']:.4g}",
            {**detail, "gate": "contradicted"},
        )
    return Result(result.task_id, True, "", detail)
