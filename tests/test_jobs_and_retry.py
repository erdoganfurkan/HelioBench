"""Concurrency must not change what a sweep writes, and a rate limit must cost latency, not a run."""

from __future__ import annotations

import asyncio
import json
import types

import pytest

from heliobench.adapters.null import NullAgent
from heliobench.retry import attach_backoff, with_backoff
from heliobench.runner import run
from heliobench.tasks import load_tasks
from heliobench.trace import Trace


class _SlowNull(NullAgent):
    """A null agent whose runs finish out of order, to make completion order visible."""

    async def run(self, prompt, workdir, task_id="", **kw):
        # Later task ids sleep less, so under concurrency they finish first.
        await asyncio.sleep(0.02 * (5 - (hash(task_id) % 5)))
        return await super().run(prompt, workdir, task_id=task_id, **kw)


def _strip_timing(records):
    for r in records:
        r["metrics"].pop("wall_s", None)
    return records


def test_jobs_does_not_change_what_the_sweep_writes(tmp_path):
    # The acceptance test of the parallelism change: two sweeps differing only in `jobs`
    # produce the same results apart from timing, in the same order.
    tasks = load_tasks("tasks", tiers=["n2"])
    serial = run(_SlowNull(), tasks, tmp_path / "s", runs=2, scratch=tmp_path / "ss", jobs=1)
    parallel = run(_SlowNull(), tasks, tmp_path / "p", runs=2, scratch=tmp_path / "ps", jobs=8)
    assert _strip_timing(serial["records"]) == _strip_timing(parallel["records"])
    assert [(r["task_id"], r["run"]) for r in parallel["records"]] == sorted(
        (r["task_id"], r["run"]) for r in parallel["records"]
    )
    assert serial["meta"]["jobs"] == 1 and parallel["meta"]["jobs"] == 8
    assert len(list((tmp_path / "p" / "traces").glob("*.json"))) == len(tasks) * 2


def test_at_most_jobs_runs_are_in_flight(tmp_path):
    state = {"now": 0, "peak": 0}

    class Counting(NullAgent):
        async def run(self, prompt, workdir, task_id="", **kw):
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            await asyncio.sleep(0.01)
            state["now"] -= 1
            return await super().run(prompt, workdir, task_id=task_id, **kw)

    tasks = load_tasks("tasks", tiers=["n2"])
    run(Counting(), tasks, tmp_path / "r", runs=3, scratch=tmp_path / "s", jobs=3)
    assert state["peak"] == 3


def test_zero_jobs_is_refused(tmp_path):
    with pytest.raises(ValueError):
        run(NullAgent(), [], tmp_path / "r", runs=1, jobs=0)


def test_the_report_withholds_per_run_wall_clock_under_concurrency(tmp_path):
    from heliobench import report

    tasks = load_tasks("tasks", tiers=["n2"])[:2]
    run(NullAgent(), tasks, tmp_path / "r", runs=1, scratch=tmp_path / "s", jobs=4)
    md = report.write(tmp_path / "r").read_text(encoding="utf-8")
    assert "| Concurrency | 4 |" in md
    assert "— (jobs=4)" in md


# --- backoff ---------------------------------------------------------------------------


class RateLimitError(Exception):
    pass


class BadRequestError(Exception):
    pass


def _flaky(failures, exc=RateLimitError):
    state = {"calls": 0}

    async def create(**kwargs):
        state["calls"] += 1
        if state["calls"] <= failures:
            raise exc("429")
        return types.SimpleNamespace(usage=None, ok=True)

    return create, state


def test_a_transient_failure_is_retried_with_exponential_backoff():
    create, state = _flaky(3)
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    result = asyncio.run(with_backoff(create, sleep=fake_sleep, model="m"))
    assert result.ok and state["calls"] == 4
    assert slept == [1.0, 2.0, 4.0]


def test_a_failure_that_could_be_the_agents_fault_is_not_retried():
    create, state = _flaky(1, exc=BadRequestError)
    with pytest.raises(BadRequestError):
        asyncio.run(with_backoff(create, sleep=lambda s: asyncio.sleep(0)))
    assert state["calls"] == 1


def test_the_last_attempt_raises_rather_than_retrying_forever():
    create, state = _flaky(99)

    async def no_sleep(s):
        pass

    with pytest.raises(RateLimitError):
        asyncio.run(with_backoff(create, attempts=3, sleep=no_sleep))
    assert state["calls"] == 3


def test_retries_are_recorded_in_the_trace_and_counted_as_a_process_metric():
    from heliobench.graders.process import collect

    create, _ = _flaky(2)
    completions = types.SimpleNamespace(create=create)
    client = types.SimpleNamespace(
        _client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
    )
    trace = Trace(task_id="t", prompt="p", agent="a")

    async def no_sleep(s):
        pass

    attach_backoff(client, trace, t0=0.0, sleep=no_sleep)
    asyncio.run(client._client.chat.completions.create(model="m"))
    assert [e["data"]["attempt"] for e in trace.events_named("retry")] == [1, 2]
    assert collect(trace).retries == 2
    json.dumps(trace.to_dict())  # the retry event must survive the trace's own serialisation


def test_backoff_layers_over_the_token_meter_and_counts_only_what_returned():
    from heliobench.usage import attach_token_meter

    usages = iter([types.SimpleNamespace(prompt_tokens=10, completion_tokens=1)])
    state = {"calls": 0}

    async def create(**kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RateLimitError("429")
        return types.SimpleNamespace(usage=next(usages))

    completions = types.SimpleNamespace(create=create)
    client = types.SimpleNamespace(
        _client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
    )
    meter = attach_token_meter(client)

    async def no_sleep(s):
        pass

    attach_backoff(client, Trace(task_id="t", prompt="p", agent="a"), t0=0.0, sleep=no_sleep)
    asyncio.run(client._client.chat.completions.create(model="m"))
    assert meter.usage.prompt == 10 and meter.usage.calls == 1 and meter.usage.exact


# The SDK's class name, which is what `is_retriable` reads, with the SDK's status attribute.
_Status429 = type("RateLimitError", (Exception,), {"status_code": 429})


class APIConnectionError(Exception):
    pass


def _client_of(create):
    completions = types.SimpleNamespace(create=create)
    return types.SimpleNamespace(
        _client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
    )


def test_a_status_bearing_error_is_left_to_the_agent_and_still_recorded():
    # HelioAI retries 408/429/5xx around this method; retrying here too multiplied them.
    create, state = _flaky(99, exc=_Status429)
    client = _client_of(create)
    trace = Trace(task_id="t", prompt="p", agent="a")
    attach_backoff(client, trace, t0=0.0, defer_status=True)
    with pytest.raises(_Status429):
        asyncio.run(client._client.chat.completions.create(model="m"))
    assert state["calls"] == 1
    (ev,) = trace.events_named("retry")
    assert ev["data"]["by"] == "agent" and ev["data"]["error"] == "RateLimitError"


def test_a_connection_error_is_still_retried_when_the_agent_retries_only_statuses():
    # HelioAI's clients have max_retries=0 and call_with_retry skips status-less errors:
    # deferring these too left a dropped connection retried by nobody.
    create, state = _flaky(2, exc=APIConnectionError)
    client = _client_of(create)
    trace = Trace(task_id="t", prompt="p", agent="a")

    async def no_sleep(s):
        pass

    attach_backoff(client, trace, t0=0.0, defer_status=True, sleep=no_sleep)
    assert asyncio.run(client._client.chat.completions.create(model="m")).ok
    assert state["calls"] == 3
    assert [e["data"]["by"] for e in trace.events_named("retry")] == ["harness", "harness"]


def test_deferral_does_not_record_the_agents_own_faults():
    create, _ = _flaky(1, exc=BadRequestError)
    client = _client_of(create)
    trace = Trace(task_id="t", prompt="p", agent="a")
    attach_backoff(client, trace, t0=0.0, defer_status=True)
    with pytest.raises(BadRequestError):
        asyncio.run(client._client.chat.completions.create(model="m"))
    assert trace.events_named("retry") == []


# --- interruption and resume -------------------------------------------------------------


class _DiesAfter(NullAgent):
    """Runs `n` repetitions, then the sweep is interrupted."""

    def __init__(self, n):
        super().__init__()
        self.n = n
        self.calls = 0

    async def run(self, prompt, workdir, task_id="", **kw):
        self.calls += 1
        if self.calls > self.n:
            raise KeyboardInterrupt
        return await super().run(prompt, workdir, task_id=task_id, **kw)


def test_an_interrupted_sweep_leaves_a_readable_run_and_resumes(tmp_path):
    tasks = load_tasks("tasks", tiers=["n2"])
    out = tmp_path / "r"
    with pytest.raises(KeyboardInterrupt):
        run(_DiesAfter(3), tasks, out, runs=1, scratch=tmp_path / "s")
    meta = json.loads((out / "meta.json").read_text())
    assert meta["status"] == "interrupted"
    assert len(json.loads((out / "results.json").read_text())) == 3
    assert len((out / "results.partial.jsonl").read_text().splitlines()) == 3

    again = _DiesAfter(99)
    res = run(again, tasks, out, runs=1, scratch=tmp_path / "s", resume=True)
    assert again.calls == len(tasks) - 3, "finished repetitions are not run again"
    assert res["meta"]["status"] == "complete" and res["meta"]["resumed"] == 3
    assert len(res["records"]) == len(tasks)
    assert not (out / "results.partial.jsonl").exists()


def test_resume_refuses_another_task_selection(tmp_path, capsys):
    from heliobench.cli import main

    tasks = load_tasks("tasks", tiers=["n2"])
    out = tmp_path / "r"
    with pytest.raises(KeyboardInterrupt):
        run(_DiesAfter(1), tasks, out, runs=1, scratch=tmp_path / "s")
    assert main(["run", "--tier", "n3", "--resume", str(out)]) == 1
    assert "task selection differs" in capsys.readouterr().err
    assert main(["run", "--tier", "n2", "--resume", str(out)]) == 0
