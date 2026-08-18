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
