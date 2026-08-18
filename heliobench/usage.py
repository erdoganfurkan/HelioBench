"""Token accounting for an agent that does not keep its own.

HelioAI discards `response.usage` when it converts a provider reply into its neutral
`Message`, so the count cannot be recovered downstream — not from the reply, not from the
event stream. It is recovered here instead, by wrapping the provider SDK call on the client
instance the harness itself constructs. Nothing in the agent is patched.
"""

from __future__ import annotations

from heliobench.trace import TokenUsage


class UnmeteredProvider(RuntimeError):
    """The client's shape is unknown, so its tokens cannot be counted.

    Raised rather than degraded on purpose: a benchmark that must report cost per task is
    better off refusing to run than publishing a zero that looks like a measurement.
    """


class TokenMeter:
    """Accumulates provider-reported token usage across one run."""

    def __init__(self) -> None:
        self.usage = TokenUsage()

    def _record(self, response) -> None:
        u = getattr(response, "usage", None)
        if u is None:
            # A provider that answered without a usage block: the total is no longer exact,
            # and saying so is the whole point of the flag.
            self.usage.exact = False
            return
        self.usage.prompt += int(getattr(u, "prompt_tokens", 0) or 0)
        self.usage.completion += int(getattr(u, "completion_tokens", 0) or 0)
        self.usage.calls += 1


def attach_token_meter(llm_client) -> TokenMeter:
    """Wrap `llm_client`'s SDK call so every completion's usage is counted.

    Mutates the instance the caller owns; the class and the agent package are untouched.

    Raises:
        UnmeteredProvider: when the client does not expose an OpenAI-shaped SDK object.
            Gemini's native client is the known case — it needs its own wrapper, which will
            be written when a Gemini run is actually wanted.
    """
    sdk = getattr(llm_client, "_client", None)
    create = getattr(getattr(getattr(sdk, "chat", None), "completions", None), "create", None)
    if create is None:
        raise UnmeteredProvider(
            f"cannot count tokens for {type(llm_client).__name__}: no OpenAI-shaped SDK client"
        )

    meter = TokenMeter()

    async def counting_create(**kwargs):
        response = await create(**kwargs)
        meter._record(response)
        return response

    sdk.chat.completions.create = counting_create
    return meter
