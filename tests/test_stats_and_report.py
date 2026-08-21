import json

from heliobench import report
from heliobench.adapters.null import NullAgent
from heliobench.runner import regrade, run, task_set_digest
from heliobench.stats import cluster_bootstrap_ci, mcnemar, summarise
from heliobench.tasks import Task, load_tasks


def test_clustering_widens_the_interval():
    # Twelve questions about one event are twelve looks at the same event. Treating them as
    # independent is what understates the interval; this is the whole reason `event` exists.
    values = [1.0] * 6 + [0.0] * 6
    tight = cluster_bootstrap_ci(values, [f"e{i}" for i in range(12)])
    loose = cluster_bootstrap_ci(values, ["a"] * 6 + ["b"] * 6)
    assert (loose[1] - loose[0]) > (tight[1] - tight[0])


def test_a_single_cluster_admits_no_between_cluster_variation():
    lo, hi = cluster_bootstrap_ci([1.0, 0.0, 1.0], ["same"] * 3)
    assert lo == hi


def test_pass_k_is_stricter_than_the_mean():
    per_task = {"a": [True, True, True], "b": [True, False, True], "c": [False, False, False]}
    s = summarise(per_task, {"a": "e1", "b": "e1", "c": "e2"}, runs=3)
    assert s.pass_k == pytest_approx(1 / 3)
    assert s.pass_any == pytest_approx(2 / 3)
    assert s.mean > s.pass_k
    assert s.n_events == 2


def pytest_approx(x):
    import pytest

    return pytest.approx(x, rel=1e-6)


def test_mcnemar_uses_only_discordant_pairs():
    a = {"t1": True, "t2": True, "t3": False, "t4": True}
    b = {"t1": True, "t2": False, "t3": False, "t4": False}
    r = mcnemar(a, b)
    assert (r["only_a"], r["only_b"], r["n_shared"]) == (2, 0, 4)
    assert r["p_value"] == pytest_approx(0.5)


def test_identical_arms_are_not_significantly_different():
    a = {"t1": True, "t2": False}
    assert mcnemar(a, dict(a))["p_value"] == 1.0


def test_the_digest_changes_when_a_prompt_changes():
    t1 = Task(id="a", tier="n1", prompt="x", expected={"ids": ["p/q"]}, provenance="v")
    t2 = Task(id="a", tier="n1", prompt="y", expected={"ids": ["p/q"]}, provenance="v")
    assert task_set_digest([t1]) != task_set_digest([t2])


def test_a_full_null_run_produces_a_readable_report(tmp_path):
    tasks = load_tasks("tasks", tiers=["n2"])[:3]
    out = tmp_path / "run"
    run(NullAgent(), tasks, out, runs=2, scratch=tmp_path / "scratch")

    records = json.loads((out / "results.json").read_text())
    assert len(records) == 6
    assert not any(r["passed"] for r in records), "the floor must score zero"

    md = report.write(out).read_text(encoding="utf-8")
    assert "## Score" in md and "## Process" in md and "## Failures" in md
    assert "pass^k" in md
    assert (out / "results.csv").is_file()
    assert len(list((out / "traces").glob("*.json"))) == 6


def test_a_task_needing_a_missing_fixture_fails_that_task_not_the_sweep(tmp_path):
    task = Task(
        id="n3_ghost",
        tier="n3",
        prompt="p",
        expected={"value": 1.0},
        provenance="v",
        fixture="does_not_exist",
    )
    out = tmp_path / "run"
    result = run(NullAgent(), [task], out, runs=1, fixtures=tmp_path, scratch=tmp_path / "s")
    assert result["records"][0]["passed"] is False
    assert "FileNotFoundError" in result["records"][0]["reason"]


def _n1_record(rank, searched=True, passed=True):
    return {
        "task_id": f"n1_t{rank}",
        "tier": "n1",
        "event": "e",
        "run": 0,
        "passed": passed,
        "reason": "",
        "detail": {"searched": searched, "retrieved": 5, "rank": rank},
        "metrics": {},
    }


def test_the_report_grades_retrieval_by_rank_when_the_tool_output_was_kept():
    records = [_n1_record(1), _n1_record(4), _n1_record(None, passed=False)]
    md = report.build({"runs": 1}, records)
    assert "## Retrieval (n1)" in md
    # MRR = (1/1 + 1/4 + 0) / 3, recall@1 = 1/3, one product never returned.
    assert "0.417" in md and "33.3%" in md


def test_runs_recorded_before_tool_output_was_kept_are_left_out_of_the_rank():
    md = report.build({"runs": 1}, [_n1_record(None, searched=False)])
    assert "## Retrieval (n1)" not in md


def test_regrading_a_stored_run_follows_a_corrected_answer_key(tmp_path):
    # The property the whole re-grade exists for: a key that was wrong when the run happened
    # gives a different verdict afterwards, from the stored trace alone and without an agent.
    from heliobench.trace import Trace

    task = Task(
        id="n1_x", tier="n1", prompt="p", expected={"ids": ["cda/A_B/RIGHT"]}, provenance="v"
    )
    out = tmp_path / "run"
    (out / "traces").mkdir(parents=True)
    Trace(task_id="n1_x", prompt="p", agent="a", reply="The product is cda/A_B/DEFENSIBLE.").write(
        out / "traces" / "n1_x.0.json"
    )

    assert regrade(out, [task])["records"][0]["passed"] is False

    widened = Task(
        id="n1_x",
        tier="n1",
        prompt="p",
        expected={"ids": ["cda/A_B/RIGHT", "cda/A_B/DEFENSIBLE"]},
        provenance="v",
    )
    after = regrade(out, [widened])
    assert after["records"][0]["passed"] is True
    assert after["meta"]["task_set_digest"] == task_set_digest([widened])


def test_regrading_skips_traces_whose_task_left_the_set(tmp_path):
    from heliobench.trace import Trace

    out = tmp_path / "run"
    (out / "traces").mkdir(parents=True)
    Trace(task_id="n1_gone", prompt="p", agent="a", reply="x").write(
        out / "traces" / "n1_gone.0.json"
    )
    kept = Task(
        id="n1_here", tier="n1", prompt="p", expected={"ids": ["cda/A_B/Q"]}, provenance="v"
    )
    Trace(task_id="n1_here", prompt="p", agent="a", reply="cda/A_B/Q").write(
        out / "traces" / "n1_here.0.json"
    )

    result = regrade(out, [kept])
    assert [r["task_id"] for r in result["records"]] == ["n1_here"]
    assert result["meta"]["skipped_traces"] == ["n1_gone"]
