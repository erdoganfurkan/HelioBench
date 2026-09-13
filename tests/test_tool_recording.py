"""The tool-output recorder under concurrency.

Separate from `test_helioai_adapter.py` on purpose: that file is skipped wherever HelioAI is
not installed, which includes CI, and the failure this guards against — two runs in flight
writing into each other's trace — is one CI has to be able to see. The recorder accepts any
object with an async `call_tool`, so a stand-in for HelioAI's registry is enough.
"""

import asyncio

from heliobench.adapters.helioai import _DISPATCHER, _recording_tool_output
from heliobench.trace import Trace


class _Registry:
    """Stands in for `helioai.tools.registry.registry`: one module-level singleton."""

    async def call_tool(self, name, arguments=None, *, trusted=None):
        return f"{name} -> {arguments}"


def _recorded(trace: Trace) -> list[str]:
    return [e["data"]["name"] for e in trace.events if e["event"] == "tool_output"]


async def _run(registry, trace, label, n_calls, delay):
    with _recording_tool_output(trace, 0.0, registry=registry):
        for i in range(n_calls):
            await asyncio.sleep(delay)
            await registry.call_tool(f"{label}-{i}", {"q": i})


def test_concurrent_runs_record_only_their_own_tool_output():
    # Run A finishes first. Before the fix, both traces received both runs' calls, and A's
    # exit unwrapped the registry so B's remaining calls were recorded nowhere.
    registry = _Registry()
    original = registry.call_tool
    a, b = Trace(task_id="a", prompt="", agent=""), Trace(task_id="b", prompt="", agent="")

    async def main():
        await asyncio.gather(_run(registry, a, "A", 2, 0.005), _run(registry, b, "B", 4, 0.01))

    asyncio.run(main())

    assert _recorded(a) == ["A-0", "A-1"]
    assert _recorded(b) == ["B-0", "B-1", "B-2", "B-3"]
    assert registry.call_tool == original, "the last run out must leave the registry as found"
    assert "call_tool" not in vars(registry), "the class method, not a copy bound on the instance"
    assert _DISPATCHER._active == 0


def test_a_call_outside_any_run_is_passed_through_unrecorded():
    registry = _Registry()
    trace = Trace(task_id="t", prompt="", agent="")

    async def main():
        with _recording_tool_output(trace, 0.0, registry=registry):
            pass
        return await registry.call_tool("after", None)

    assert asyncio.run(main()) == "after -> None"
    assert _recorded(trace) == []


def test_the_recorder_keeps_what_a_tool_returned_verbatim_and_flags_truncation():
    class _Long(_Registry):
        async def call_tool(self, name, arguments=None, *, trusted=None):
            return "x" * 5000

    registry = _Long()
    trace = Trace(task_id="t", prompt="", agent="")

    async def main():
        with _recording_tool_output(trace, 0.0, registry=registry):
            return await registry.call_tool("search_parameters", {"query": "Bz"})

    out = asyncio.run(main())
    (ev,) = [e for e in trace.events if e["event"] == "tool_output"]
    assert out == "x" * 5000, "the agent must see the full result"
    assert ev["data"]["result"] == "x" * 4000
    assert ev["data"]["truncated"] is True
    assert ev["data"]["arguments"] == {"query": "Bz"}
