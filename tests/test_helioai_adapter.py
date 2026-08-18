"""Adapter tests. Skipped wholesale when HelioAI is absent — CI installs no agent."""

import asyncio

import pytest

from heliobench.adapters.helioai import HelioAIAgent, _discoverable_dotenv

helioai = pytest.importorskip("helioai", reason="agent extra not installed")


def test_dotenv_discovery_matches_the_walk_up_that_helioai_does(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert _discoverable_dotenv(deep) is None
    env = tmp_path / "a" / ".env"
    env.write_text("X=1")
    assert _discoverable_dotenv(deep) == env


class _FakeLLM:
    """Answers once, with no tool calls, and exposes an OpenAI-shaped SDK object so the
    token meter attaches the same way it does in a real run."""

    def __init__(self, reply: str):
        self._reply = reply
        import types

        async def create(**kwargs):
            return types.SimpleNamespace(
                usage=types.SimpleNamespace(prompt_tokens=7, completion_tokens=3)
            )

        self._client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
        )

    async def chat(self, messages, tools, system_prompt=None, tool_choice="auto"):
        from helioai.core.llm.base import Message

        await self._client.chat.completions.create(model="fake")
        return Message(role="assistant", content=self._reply)


def test_a_run_produces_a_trace_without_touching_a_provider(tmp_path, monkeypatch):
    agent = HelioAIAgent(tmp_path / "data", provider="ollama")
    agent._load()
    monkeypatch.setattr(
        "helioai.core.llm.factory.build_llm_client",
        lambda provider=None: _FakeLLM("Plasma beta is 2.52."),
    )

    workdir = tmp_path / "bench_n2_beta"
    trace = asyncio.run(agent.run("Plasma beta for B=20 nT?", workdir, task_id="n2_beta"))

    assert trace.error is None
    assert "2.52" in trace.reply
    assert trace.n_iterations == 1
    assert trace.wall_s > 0
    assert trace.tokens.prompt == 7 and trace.tokens.exact
    assert trace.env["provider"] == "ollama"


def test_seeding_makes_the_agent_reuse_our_directory(tmp_path):
    # The whole offline story rests on this: stream_chat reuses a recorded workspace label
    # verbatim, so a pre-filled manifest is served by get_timeseries without any network.
    agent = HelioAIAgent(tmp_path / "data", provider="ollama")
    agent._load()
    from helioai.core.session import store
    from helioai.workspace import user_home

    fixture = tmp_path / "fixture" / "data"
    fixture.mkdir(parents=True)
    (fixture / "manifest.json").write_text('{"datasets": {}}')

    label = agent.seed(tmp_path / "bench_x", fixture.parent, "sess-1")
    assert store.get_workspace_dir("heliobench", "sess-1") == label
    seeded = user_home("heliobench") / "workspace" / label / "data" / "manifest.json"
    assert seeded.is_file(), "the fixture must land where get_timeseries will look"
    store.reset("heliobench", "sess-1")


class _ScriptedLLM(_FakeLLM):
    """Runs one sandbox computation, then answers. The point is the ledger: a number the
    agent computed must be distinguishable from a number it wrote down, and that distinction
    is only made on disk."""

    def __init__(self, code: str, reply: str):
        super().__init__(reply)
        self._code = code
        self._turn = 0

    async def chat(self, messages, tools, system_prompt=None, tool_choice="auto"):
        from helioai.core.llm.base import Message, ToolCall

        await self._client.chat.completions.create(model="fake")
        self._turn += 1
        if self._turn == 1:
            return Message(
                role="assistant",
                tool_calls=[
                    ToolCall(id="call_1", name="run_python", arguments={"code": self._code})
                ],
            )
        return Message(role="assistant", content=self._reply)


def test_a_computed_number_reaches_the_provenance_ledger(tmp_path, monkeypatch):
    agent = HelioAIAgent(tmp_path / "data", provider="ollama")
    agent._load()
    monkeypatch.setattr(
        "helioai.core.llm.factory.build_llm_client",
        lambda provider=None: _ScriptedLLM('export("beta", 2.52, "")', "Plasma beta is 2.52."),
    )

    trace = asyncio.run(
        agent.run("compute plasma beta", tmp_path / "bench_ledger", task_id="n2_ledger")
    )

    assert trace.error is None, trace.error
    assert trace.tool_calls() == ["run_python"]
    names = {v["name"]: v for v in trace.ledger.get("values", [])}
    assert "beta" in names, f"ledger empty; artifacts={trace.artifacts}"
    assert names["beta"]["mean"] == pytest.approx(2.52)
    assert trace.tokens.calls == 2, "both LLM turns must be counted, not just the last"
