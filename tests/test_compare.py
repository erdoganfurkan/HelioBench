"""`heliobench compare`: the paired test, in code rather than in a scratch script."""

from __future__ import annotations

import json

import pytest

from heliobench.cli import main
from heliobench.compare import CompareError, collapse, compare


def _run(tmp_path, name, digest, per_task, runs=3):
    d = tmp_path / name
    d.mkdir()
    (d / "meta.json").write_text(
        json.dumps({"task_set_digest": digest, "runs": runs, "agent": {"agent": "x", "model": "m"}})
    )
    records = []
    for tid, outs in per_task.items():
        for i, o in enumerate(outs):
            records.append(
                {
                    "task_id": tid,
                    "tier": "n1",
                    "event": tid,
                    "run": i,
                    "passed": o is True,
                    "outcome": "errored" if o is None else ("passed" if o else "failed"),
                    "reason": "",
                }
            )
    (d / "results.json").write_text(json.dumps(records))
    return d


def test_strict_and_majority_collapse_differently():
    records = []
    for i, o in enumerate([True, True, False]):
        records.append(
            {"task_id": "t", "run": i, "passed": o, "outcome": "passed" if o else "failed"}
        )
    assert collapse(records, "strict") == {"t": False}
    assert collapse(records, "majority") == {"t": True}


def test_an_errored_repetition_is_dropped_before_collapsing():
    records = [
        {"task_id": "t", "run": 0, "passed": True, "outcome": "passed"},
        {"task_id": "t", "run": 1, "passed": False, "outcome": "errored"},
        {"task_id": "u", "run": 0, "passed": False, "outcome": "errored"},
    ]
    assert collapse(records, "strict") == {"t": True}  # `u` has nothing left to collapse


def test_different_digests_are_refused(tmp_path, capsys):
    a = _run(tmp_path, "a", "aaaa", {"t": [True]})
    b = _run(tmp_path, "b", "bbbb", {"t": [True]})
    with pytest.raises(CompareError):
        compare(
            (json.loads((a / "meta.json").read_text()), []),
            (json.loads((b / "meta.json").read_text()), []),
        )
    assert main(["compare", str(a), str(b)]) == 1
    assert "task_set_digest differs" in capsys.readouterr().err


def test_the_command_prints_the_paired_test_and_the_tasks_that_moved(tmp_path, capsys):
    a = _run(
        tmp_path, "a", "same", {"t1": [True] * 3, "t2": [True, True, False], "t3": [False] * 3}
    )
    b = _run(tmp_path, "b", "same", {"t1": [True] * 3, "t2": [False] * 3, "t3": [True] * 3})
    assert main(["compare", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "`pass^k` (strict) | 1/3 | 2/3 | 0 | 1 |" in out
    assert "majority | 2/3 | 2/3 | 1 | 1 |" in out
    assert "`t3` — B passed, A did not" in out
    assert "`t2` — A passed, B did not" in out
    assert "recorded before `outcome` existed" not in out


def test_a_run_without_outcomes_is_flagged_rather_than_trusted(tmp_path, capsys):
    a = _run(tmp_path, "a", "same", {"t1": [True]})
    b = _run(tmp_path, "b", "same", {"t1": [True]})
    recs = json.loads((b / "results.json").read_text())
    for r in recs:
        del r["outcome"]
    (b / "results.json").write_text(json.dumps(recs))
    assert main(["compare", str(a), str(b)]) == 0
    assert "Run B was recorded before `outcome` existed" in capsys.readouterr().out
