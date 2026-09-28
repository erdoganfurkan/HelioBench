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


def test_a_truncated_search_output_with_no_rank_is_not_counted_as_never_returned():
    # The accepted id may have been past the 4000-character cut: shown to the agent, not to
    # us. Such a run is counted apart, not as a retrieval failure.
    cut = _n1_record(None, passed=False)
    cut["detail"]["truncated"] = True
    md = report.build({"runs": 1}, [_n1_record(1), cut])
    assert "| 1 | 1.000 | 100.0% |" in md
    assert "| 0 | 1 |" in md  # never returned 0, truncated-unranked 1


def test_a_rank_found_before_the_cut_is_kept_even_when_the_output_was_truncated():
    found = _n1_record(2)
    found["detail"]["truncated"] = True
    md = report.build({"runs": 1}, [found])
    assert "| 1 | 0.500 |" in md


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


def test_a_regrade_leaves_a_trace_whose_prompt_changed_unscored(tmp_path):
    # When a prompt is hardened, the old runs answered a different question: they are
    # unscored, not re-scored. Regrading used to grade them against the new key and write the
    # new digest, which `compare` would then have accepted.
    tasks = load_tasks("tasks", tiers=["n2"])[:2]
    out = tmp_path / "run"
    run(NullAgent(), tasks, out, runs=1)
    trace_path = out / "traces" / f"{tasks[0].id}.0.json"
    data = json.loads(trace_path.read_text())
    data["prompt"] = "an older wording of the question"
    trace_path.write_text(json.dumps(data))

    res = regrade(out, tasks)
    assert [r["task_id"] for r in res["records"]] == [tasks[1].id]
    assert res["meta"]["unscored_traces"] == [
        {"task_id": tasks[0].id, "run": 0, "reason": "the prompt changed since this run"}
    ]
    assert res["meta"]["task_set_digest"] == task_set_digest([tasks[1]])


def test_meta_records_a_digest_per_task_and_per_fixture(tmp_path):
    from heliobench.runner import fixture_digests, task_digests

    tasks = load_tasks("tasks", tiers=["n3"])[:2]
    meta = run(NullAgent(), tasks, tmp_path / "r", runs=1)["meta"]
    assert meta["task_digests"] == task_digests(tasks)
    assert set(meta["fixture_digests"]) == {t.fixture for t in tasks}
    assert meta["fixture_digests"] == fixture_digests(tasks, __import__("pathlib").Path("fixtures"))
    # The set digest is unchanged by this: stored runs must keep comparing.
    assert meta["task_set_digest"] == task_set_digest(tasks)


def _n3_run(tmp_path, runs=1):
    tasks = load_tasks("tasks", tiers=["n2"])[:2] + load_tasks("tasks", tiers=["n3"])[:2]
    out = tmp_path / "run"
    run(NullAgent(), tasks, out, runs=runs)
    return out


def test_one_repetition_is_flagged_as_saying_nothing_about_reproducibility(tmp_path):
    md = report.write(_n3_run(tmp_path, runs=1)).read_text(encoding="utf-8")
    assert "One repetition" in md
    md = report.write(_n3_run(tmp_path / "k", runs=2)).read_text(encoding="utf-8")
    assert "One repetition" not in md


def test_the_report_has_a_per_task_matrix_and_process_by_tier(tmp_path):
    md = report.write(_n3_run(tmp_path, runs=2)).read_text(encoding="utf-8")
    assert "## Per task" in md and "| n2 | ✗✗ |" in md
    assert "## Process by tier" in md and "Wall p95" in md


def test_prices_turn_tokens_into_cost(tmp_path):
    out = _n3_run(tmp_path)
    recs = json.loads((out / "results.json").read_text())
    for r in recs:
        r["metrics"].update(tokens_prompt=1_000_000, tokens_completion=100_000, tokens_cached=0)
    (out / "results.json").write_text(json.dumps(recs))
    meta = json.loads((out / "meta.json").read_text())
    prices = {meta["agent"]["model"]: {"input": 1.0, "output": 10.0}}
    md = report.build(meta, recs, prices)
    assert "| Cost (USD) | 8.0000 | 2.0000 |" in md
    assert "Cost (USD)" not in report.build(meta, recs)


def test_cached_prompt_tokens_are_priced_at_the_cached_rate():
    assert report.cost_usd(1_000_000, 0, 400_000, "m", {"m": {"input": 1, "cached": 0.1}}) == (
        pytest_approx(0.64)
    )


def test_the_header_says_what_was_regraded_and_what_was_left_unscored(tmp_path):
    meta = {
        "agent": {"agent": "helioai", "experiments": ["search_budget"], "agent_env": {}},
        "regraded": "2026-09-28T10:00:00+00:00",
        "unscored_traces": [{"task_id": "n1_x", "run": 0, "reason": "the prompt changed"}],
        "status": "interrupted",
    }
    md = report.build(meta, [])
    assert "| Regraded | 2026-09-28T10:00:00+00:00 |" in md
    assert "1 — the prompt changed since the run (n1_x)" in md
    assert "experiments: search_budget" in md
    assert "⚠️ interrupted" in md


def test_the_html_page_is_self_contained_and_carries_the_same_tables(tmp_path):
    out = _n3_run(tmp_path)
    report.write(out, html=True)
    page = (out / "report.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and "<table>" in page
    assert "<script" not in page and "http" not in page.split("<body>")[0]
    assert '<span class="ko">✗</span>' in page


def test_two_sweeps_started_in_the_same_second_get_two_directories(tmp_path):
    from heliobench.runner import new_run_dir

    a, b = new_run_dir(tmp_path, "null"), new_run_dir(tmp_path, "null")
    assert a != b and (b / "traces").is_dir()
