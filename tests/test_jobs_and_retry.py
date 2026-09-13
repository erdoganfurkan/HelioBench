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
