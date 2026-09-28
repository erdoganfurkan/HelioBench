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


def _with(d, meta=None, metrics=None, tier=None):
    m = json.loads((d / "meta.json").read_text())
    m.update(meta or {})
    (d / "meta.json").write_text(json.dumps(m))
    recs = json.loads((d / "results.json").read_text())
    for r in recs:
        if metrics:
            r["metrics"] = dict(metrics(r))
        if tier:
            r["tier"] = tier(r)
    (d / "results.json").write_text(json.dumps(recs))
    return d


def test_what_differs_between_the_arms_is_listed_above_the_result(tmp_path, capsys):
    # The 0.3.0-vs-0.4.0 arms of 2026-09-23 also differed by their index, and nothing said so.
    a = _run(tmp_path, "a", "same", {"t1": [True]})
    b = _run(tmp_path, "b", "same", {"t1": [True]})
    agent_a = {"agent": "x", "model": "m", "index_size": 82244, "index_dir": "/i/prod"}
    agent_b = {"agent": "x", "model": "m", "index_size": 82266, "index_dir": "/i/live"}
    _with(a, {"agent": agent_a})
    _with(b, {"agent": agent_b})
    assert main(["compare", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "## What differs between the arms" in out
    assert "| index_size | `82244` | `82266` |" in out
    assert "| model |" not in out, "what is equal is not listed"


def test_shared_compares_only_the_tasks_asked_in_the_same_wording(tmp_path, capsys):
    a = _run(tmp_path, "a", "da", {"t1": [True], "t2": [True], "t3": [True]})
    b = _run(tmp_path, "b", "db", {"t1": [False], "t2": [True], "t4": [True]})
    _with(a, {"task_digests": {"t1": "x", "t2": "y", "t3": "z"}})
    _with(b, {"task_digests": {"t1": "x", "t2": "CHANGED", "t4": "w"}})
    assert main(["compare", str(a), str(b)]) == 1, "different digests still refuse by default"
    assert "--shared" in capsys.readouterr().err
    r = compare(load(a), load(b), shared=True)
    assert r["scope"]["n_tasks"] == 1
    assert r["left_out"] == {"reworded": ["t2"], "only_a": ["t3"], "only_b": ["t4"]}
    assert r["collapsings"]["strict"]["moved_to_a"] == ["t1"]


def test_a_legacy_run_cannot_be_compared_on_a_subset_by_id_alone(tmp_path):
    a = _run(tmp_path, "a", "da", {"t1": [True]})
    b = _run(tmp_path, "b", "db", {"t1": [True]})
    with pytest.raises(CompareError, match="per-task digests"):
        compare(load(a), load(b), shared=True)


def test_tier_restricts_both_runs_when_the_set_digest_matches(tmp_path):
    a = _run(tmp_path, "a", "same", {"n1_a": [True], "n3_b": [False]})
    b = _run(tmp_path, "b", "same", {"n1_a": [True], "n3_b": [True]})
    tier = lambda r: r["task_id"].split("_")[0]  # noqa: E731
    _with(a, tier=tier)
    _with(b, tier=tier)
    r = compare(load(a), load(b), tier="n1")
    assert r["collapsings"]["strict"]["n_shared"] == 1
    assert r["collapsings"]["strict"]["moved_to_b"] == []


def test_process_metrics_are_paired_by_task_with_a_sign_test(tmp_path, capsys):
    ids = {f"t{i}": [True] for i in range(8)}
    a = _run(tmp_path, "a", "same", ids)
    b = _run(tmp_path, "b", "same", ids)
    base = {"tokens_exact": True, "tool_calls": 3, "n_iterations": 2, "wall_s": 10.0}
    _with(a, metrics=lambda r: {**base, "tokens_prompt": 1000, "tokens_completion": 100})
    _with(b, metrics=lambda r: {**base, "tokens_prompt": 600, "tokens_completion": 100})
    r = compare(load(a), load(b))
    (tokens,) = [m for m in r["process"] if m["metric"] == "Tokens per run"]
    assert (tokens["median_diff"], tokens["b_lower"], tokens["a_lower"]) == (-400, 8, 0)
    assert tokens["p_value"] == pytest.approx(0.0078125, abs=1e-6)
    (calls,) = [m for m in r["process"] if m["metric"] == "Tool calls per run"]
    assert calls["p_value"] == 1.0, "ties carry no sign"


def test_an_inexact_token_count_is_withheld_from_the_pairing(tmp_path):
    a = _run(tmp_path, "a", "same", {"t": [True]})
    b = _run(tmp_path, "b", "same", {"t": [True]})
    _with(a, metrics=lambda r: {"tokens_exact": True, "tokens_prompt": 5})
    _with(b, metrics=lambda r: {"tokens_exact": False, "tokens_prompt": 0})
    (tokens,) = [m for m in compare(load(a), load(b))["process"] if "Tokens" in m["metric"]]
    assert tokens["withheld"] == "token count not exact in B"


def load(d):
    from heliobench.compare import load_run

    return load_run(d)
