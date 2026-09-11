"""A run the infrastructure lost must not be scored as a run the agent got wrong."""

from __future__ import annotations

import json

from heliobench import report
from heliobench.graders.outcome import ERRORED, FAILED, PASSED, classify, is_transport_error
from heliobench.runner import regrade
from heliobench.stats import summarise
from heliobench.tasks import Task
from heliobench.trace import Trace


def _trace(error=None, **kw):
    return Trace(task_id="t", prompt="p", agent="a", error=error, **kw)


def test_a_provider_timeout_is_errored_not_failed():
    assert classify(_trace("APITimeoutError: Request timed out."), passed=False) == ERRORED


def test_a_rate_limit_is_errored():
    err = "RateLimitError: Error code: 429 - {'error': {'code': '429', 'message': 'quota'}}"
    assert classify(_trace(err), passed=False) == ERRORED


def test_a_full_disk_is_errored_by_errno_not_by_wording():
    assert is_transport_error("OSError: [Errno 28] No space left on device: '/tmp/x'")
    assert not is_transport_error("OSError: [Errno 13] Permission denied: '/tmp/x'")


def test_an_unknown_exception_stays_the_agents_fault():
    # The default must be "failed": a new exception class cannot launder itself into an
    # excuse, and neither can a misconfigured key or a malformed request.
    for err in (
        "RuntimeError: GROQ_API_KEY is not set in .env",
        "BadRequestError: Error code: 400 - MissingSessionID",
        "ValueError: something new",
        "the model returned neither text nor a tool call.",
    ):
        assert classify(_trace(err), passed=False) == FAILED, err


def test_the_adapters_own_word_wins():
    assert classify(_trace("SomethingOpaque: x", error_kind="transport"), passed=False) == ERRORED


def test_a_run_without_an_error_is_passed_or_failed():
    assert classify(_trace(), passed=True) == PASSED
    assert classify(_trace(), passed=False) == FAILED


def test_an_errored_repetition_is_unknown_never_a_pass():
    # Two passes and one timeout is 2/2 with one errored — not 3/3, and not 2/3.
    s = summarise({"a": [True, True, None]}, {"a": "e"}, runs=3)
    assert s.mean == 1.0 and s.pass_k == 1.0
    assert s.n_errored == 1 and s.n_unscored == 0


def test_a_task_whose_every_run_errored_leaves_the_denominator():
    s = summarise({"a": [None, None], "b": [True, False]}, {"a": "e", "b": "f"}, runs=2)
    assert s.n_tasks == 1 and s.n_unscored == 1 and s.n_errored == 2
    assert s.mean == 0.5


def test_a_tier_missing_more_than_a_tenth_of_its_runs_is_not_comparable():
    ok = summarise({f"t{i}": [True, True, True] for i in range(10)}, {}, runs=3)
    assert ok.comparable
    per_task = {f"t{i}": [True, True, True] for i in range(10)}
    per_task["t0"] = [None, None, None]
    per_task["t1"] = [None, True, True]
    assert not summarise(per_task, {}, runs=3).comparable


def test_regrading_reclassifies_a_stored_timeout_without_a_flag(tmp_path):
    # The acceptance criterion of the failure-accounting change: the stored trace already
    # carries the exception string, so an old run is re-scored under the new rule for free.
    task = Task(id="n1_x", tier="n1", prompt="p", expected={"ids": ["cda/A_B/Q"]}, provenance="v")
    out = tmp_path / "run"
    (out / "traces").mkdir(parents=True)
    Trace(task_id="n1_x", prompt="p", agent="a", reply="cda/A_B/Q").write(
        out / "traces" / "n1_x.0.json"
    )
    Trace(task_id="n1_x", prompt="p", agent="a", error="APITimeoutError: Request timed out.").write(
        out / "traces" / "n1_x.1.json"
    )
    Trace(task_id="n1_x", prompt="p", agent="a", reply="nothing").write(
        out / "traces" / "n1_x.2.json"
    )

    records = regrade(out, [task])["records"]
    assert [r["outcome"] for r in records] == [PASSED, ERRORED, FAILED]
    assert [r["passed"] for r in records] == [True, False, False]

    md = report.write(out).read_text(encoding="utf-8")
    assert "## Errored" in md
    assert "| n1 | 1 | 1 | 50.0% |" in md, md
    csv_rows = (out / "results.csv").read_text().splitlines()
    assert csv_rows[0].split(",")[5] == "outcome"
    assert csv_rows[2].split(",")[5] == ERRORED


def test_records_written_before_outcome_existed_are_read_as_their_boolean_says():
    old = {"task_id": "t", "tier": "n1", "event": "e", "run": 0, "passed": False, "reason": "x"}
    assert report.outcome_of(old) is False
    assert report.outcome_of({**old, "passed": True}) is True


def test_the_null_run_records_an_outcome_on_every_row(tmp_path):
    from heliobench.adapters.null import NullAgent
    from heliobench.runner import run

    task = Task(id="n1_x", tier="n1", prompt="p", expected={"ids": ["cda/A_B/Q"]}, provenance="v")
    out = tmp_path / "run"
    run(NullAgent(), [task], out, runs=2, scratch=tmp_path / "s")
    rows = json.loads((out / "results.json").read_text())
    assert all(r["outcome"] == FAILED for r in rows)
