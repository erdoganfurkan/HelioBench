import asyncio
import types

import pytest

from heliobench.usage import UnmeteredProvider, attach_token_meter


def _fake_openai_client(usages):
    """A client shaped like HelioAI's OpenAI-compatible one, returning canned usages."""
    calls = iter(usages)

    async def create(**kwargs):
        u = next(calls)
        return types.SimpleNamespace(usage=u)

    completions = types.SimpleNamespace(create=create)
    return types.SimpleNamespace(
        _client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
    )


def _usage(p, c):
    return types.SimpleNamespace(prompt_tokens=p, completion_tokens=c)


def test_counts_every_completion_including_retries():
    # HelioAI retries the same request on an empty turn and on a rejected tool_choice.
    # Counting only the last one would under-report exactly the runs that cost the most.
    client = _fake_openai_client([_usage(100, 20), _usage(150, 5)])
    meter = attach_token_meter(client)
    asyncio.run(client._client.chat.completions.create(model="m"))
    asyncio.run(client._client.chat.completions.create(model="m"))
    assert (meter.usage.prompt, meter.usage.completion, meter.usage.calls) == (250, 25, 2)
    assert meter.usage.exact


def test_a_response_without_usage_marks_the_total_inexact():
    client = _fake_openai_client([None])
    meter = attach_token_meter(client)
    asyncio.run(client._client.chat.completions.create(model="m"))
    assert meter.usage.exact is False


def test_an_unrecognised_client_refuses_rather_than_reporting_zero():
    # A zero that looks like a measurement is worse than a crash: cost per task is reported.
    with pytest.raises(UnmeteredProvider, match="no OpenAI-shaped SDK client"):
        attach_token_meter(types.SimpleNamespace(_client=object()))


class _Stream:
    """An `AsyncStream` stand-in: chunks, the last one carrying usage when asked for."""

    def __init__(self, chunks, fail_after=None):
        self._chunks = chunks
        self._fail_after = fail_after
        self.closed = False

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for i, c in enumerate(self._chunks):
            if self._fail_after is not None and i == self._fail_after:
                raise ConnectionResetError("peer closed")
            yield c


def _chunk(text="", usage=None):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=text)], usage=usage)


def _streaming_client(streams):
    it = iter(streams)

    async def create(**kwargs):
        assert kwargs.get("stream")
        return next(it)

    completions = types.SimpleNamespace(create=create)
    return types.SimpleNamespace(
        _client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
    )


async def _consume(client, **kw):
    stream = await client._client.chat.completions.create(model="m", stream=True, **kw)
    return [c async for c in stream], stream


def test_a_streamed_completion_is_counted_from_its_final_chunk():
    # HelioAI 0.4.0 streams every lead turn; the 0.4.0 candidate sweep reported zero tokens.
    details = types.SimpleNamespace(cached_tokens=40)
    last = types.SimpleNamespace(
        prompt_tokens=120, completion_tokens=30, prompt_tokens_details=details
    )
    chunks = [_chunk("a"), _chunk("b"), _chunk(usage=last)]
    client = _streaming_client([_Stream(chunks)])
    meter = attach_token_meter(client)
    seen, stream = asyncio.run(_consume(client))
    assert len(seen) == 3, "every chunk must reach the agent unchanged"
    assert (meter.usage.prompt, meter.usage.completion, meter.usage.calls) == (120, 30, 1)
    assert meter.usage.cached == 40
    assert meter.usage.exact
    asyncio.run(stream.close())
    assert stream._stream.closed, "attributes the agent uses on the stream must pass through"


def test_a_running_total_repeated_on_every_chunk_is_counted_once():
    chunks = [_chunk("a", _usage(10, 1)), _chunk("b", _usage(10, 2)), _chunk(usage=_usage(10, 3))]
    client = _streaming_client([_Stream(chunks)])
    meter = attach_token_meter(client)
    asyncio.run(_consume(client))
    assert (meter.usage.prompt, meter.usage.completion, meter.usage.calls) == (10, 3, 1)


def test_a_stream_without_usage_is_inexact_not_zero():
    client = _streaming_client([_Stream([_chunk("a"), _chunk("b")])])
    meter = attach_token_meter(client)
    asyncio.run(_consume(client))
    assert meter.usage.exact is False


def test_a_stream_that_dies_before_its_usage_is_inexact():
    client = _streaming_client([_Stream([_chunk("a"), _chunk(usage=_usage(5, 5))], fail_after=1)])
    meter = attach_token_meter(client)
    with pytest.raises(ConnectionResetError):
        asyncio.run(_consume(client))
    assert meter.usage.exact is False
    assert meter.usage.calls == 0


def _sub_end(role, p, c, cached=0):
    usage = {"prompt_tokens": p, "completion_tokens": c, "cached_tokens": cached}
    return {"event": "sub_agent_end", "data": {"role": role, "usage": usage}}


def test_a_sub_agent_on_its_own_model_is_added_once_and_marked_self_reported():
    from heliobench.trace import TokenUsage
    from heliobench.usage import add_own_client_usage

    tokens = TokenUsage(prompt=100, completion=10, calls=2)
    events = [_sub_end("parameter_hunter", 50, 5, 20), _sub_end("data_analyst", 70, 7)]
    add_own_client_usage(tokens, events, {"parameter_hunter": ("groq", None)})
    # data_analyst ran on the lead's client: the meter saw it, its own account is not added.
    assert (tokens.prompt, tokens.completion, tokens.cached) == (150, 15, 20)
    assert tokens.self_reported == 1 and tokens.exact


def test_without_role_models_nothing_is_added():
    from heliobench.trace import TokenUsage
    from heliobench.usage import add_own_client_usage

    tokens = TokenUsage(prompt=1)
    add_own_client_usage(tokens, [_sub_end("parameter_hunter", 50, 5)], {})
    assert tokens.prompt == 1 and tokens.self_reported == 0


def test_an_own_model_sub_agent_that_reported_nothing_makes_the_total_inexact():
    from heliobench.trace import TokenUsage
    from heliobench.usage import add_own_client_usage

    tokens = TokenUsage()
    add_own_client_usage(tokens, [_sub_end("parameter_hunter", 0, 0)], {"parameter_hunter": 1})
    assert tokens.exact is False
