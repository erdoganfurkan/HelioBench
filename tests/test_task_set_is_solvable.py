"""Every shipped task must be passable by a correct answer, and must reject a wrong one.

This is the audit that automated benchmark auditors run against published benchmarks and
keep finding: specification errors that make a task unsolvable, and answer keys naming
things that do not exist. Cheaper to run it on ourselves.
"""

from __future__ import annotations

import pytest

from heliobench.graders import grade
from heliobench.tasks import load_tasks
from heliobench.trace import Trace

TASKS = load_tasks("tasks")


def _ideal_reply(task) -> str:
    if task.tier == "n1":
        return f"The product is {task.expected['ids'][0]}."
    near = (task.expected.get("near") or ["value"])[0]
    return f"The {near} is {task.expected['value']} {task.expected.get('units', '')}".strip() + "."


def test_the_task_set_is_not_empty():
    assert len(TASKS) >= 40


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_a_correct_answer_passes(task):
    result = grade(
        task, Trace(task_id=task.id, prompt=task.prompt, agent="ideal", reply=_ideal_reply(task))
    )
    assert result.passed, f"{task.id} is unsolvable: {result.reason} ({result.detail})"


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_an_empty_answer_fails(task):
    # A grader that passes silence passes everything.
    result = grade(task, Trace(task_id=task.id, prompt=task.prompt, agent="mute", reply=""))
    assert not result.passed


@pytest.mark.parametrize("task", [t for t in TASKS if t.tier != "n1"], ids=lambda t: t.id)
def test_an_answer_off_by_half_fails(task):
    wrong = float(task.expected["value"]) * 0.5
    near = (task.expected.get("near") or ["value"])[0]
    reply = f"The {near} is {wrong} {task.expected.get('units', '')}".strip() + "."
    assert not grade(task, Trace(task_id=task.id, prompt="p", agent="wrong", reply=reply)).passed


@pytest.mark.parametrize("task", [t for t in TASKS if t.tier == "n3"], ids=lambda t: t.id)
def test_an_n3_answer_five_percent_off_fails(task):
    # n3 truth is derived from frozen bytes by a method the prompt states, so a correct
    # implementation reproduces it to the digits it prints. The tolerance leaves room for
    # rounding, not for having done something else: the reference run's own spread was
    # 0.33% at worst.
    wrong = float(task.expected["value"]) * 1.05
    near = (task.expected.get("near") or ["value"])[0]
    reply = f"The {near} is {wrong} {task.expected.get('units', '')}".strip() + "."
    assert not grade(task, Trace(task_id=task.id, prompt="p", agent="wrong", reply=reply)).passed


def test_every_task_declares_where_its_truth_came_from():
    for t in TASKS:
        assert t.provenance.strip(), f"{t.id} has no provenance"
        assert t.licence.strip(), f"{t.id} has no licence"
