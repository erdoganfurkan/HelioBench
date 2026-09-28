"""The tool-output recorder under concurrency.

Separate from `test_helioai_adapter.py` on purpose: that file is skipped wherever HelioAI is
not installed, which includes CI, and the failure this guards against — two runs in flight
writing into each other's trace — is one CI has to be able to see. The recorder accepts any
object with an async `call_tool`, so a stand-in for HelioAI's registry is enough.
"""

import asyncio

from heliobench.adapters.helioai import _DISPATCHER, _TOOL_OUTPUT_LIMIT, _recording_tool_output
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
            return "x" * (_TOOL_OUTPUT_LIMIT + 1000)

    registry = _Long()
    trace = Trace(task_id="t", prompt="", agent="")

    async def main():
        with _recording_tool_output(trace, 0.0, registry=registry):
            return await registry.call_tool("search_parameters", {"query": "Bz"})

    out = asyncio.run(main())
    (ev,) = [e for e in trace.events if e["event"] == "tool_output"]
    assert out == "x" * (_TOOL_OUTPUT_LIMIT + 1000), "the agent must see the full result"
    assert ev["data"]["result"] == "x" * _TOOL_OUTPUT_LIMIT
    assert ev["data"]["truncated"] is True
    assert ev["data"]["limit"] == _TOOL_OUTPUT_LIMIT
    assert ev["data"]["arguments"] == {"query": "Bz"}


def test_a_tool_result_object_is_recorded_as_the_text_the_model_saw():
    # HelioAI 0.4.0's registry returns a `ToolResult`; its repr is not what the model read.
    class _Result:
        def for_llm(self):
            return '{"results": [{"id": "cda/AC_H0_MFI/BGSM"}]}'

        def __repr__(self):
            return "ToolResult(tool='search_parameters', payload={...})"

    class _Objects(_Registry):
        async def call_tool(self, name, arguments=None, *, trusted=None):
            return _Result()

    registry = _Objects()
    trace = Trace(task_id="t", prompt="", agent="")

    async def main():
        with _recording_tool_output(trace, 0.0, registry=registry):
            return await registry.call_tool("search_parameters", {"query": "Bz"})

    out = asyncio.run(main())
    (ev,) = [e for e in trace.events if e["event"] == "tool_output"]
    assert isinstance(out, _Result), "the agent must get its own object back"
    assert ev["data"]["result"] == '{"results": [{"id": "cda/AC_H0_MFI/BGSM"}]}'


def test_artifacts_are_copied_out_of_the_workspace_before_it_goes(tmp_path):
    from heliobench.adapters.helioai import keep_artifacts

    ws = tmp_path / "ws"
    (ws / "figs").mkdir(parents=True)
    (ws / "code_0.py").write_text("print(1)")
    (ws / "figs" / "b.png").write_bytes(b"png")
    outside = tmp_path / "elsewhere.png"
    outside.write_bytes(b"x")
    artifacts = [
        {"kind": "code", "code_path": str(ws / "code_0.py")},
        {"kind": "image", "figure_paths": [str(ws / "figs" / "b.png"), str(outside)]},
    ]
    assert keep_artifacts(artifacts, ws, tmp_path / "run" / "artifacts") == 2
    assert (tmp_path / "run" / "artifacts" / "figs" / "b.png").read_bytes() == b"png"
    assert artifacts[1]["kept"] == [str(tmp_path / "run" / "artifacts" / "figs" / "b.png")]
    assert artifacts[0]["code_path"] == str(ws / "code_0.py"), "what the agent said stays"
