import json

from heliobench import report
from heliobench.adapters.null import NullAgent
from heliobench.runner import run, task_set_digest
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
