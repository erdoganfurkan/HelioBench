"""Token accounting for an agent that does not keep its own.

HelioAI discards `response.usage` when it converts a provider reply into its neutral
`Message`, so the count cannot be recovered downstream — not from the reply, not from the
event stream. It is recovered here instead, by wrapping the provider SDK call on the client
instance the harness itself constructs. Nothing in the agent is patched.

A streamed completion carries no `usage` on the object `create` returns: it arrives on the
last chunk, when the caller asked for it with `stream_options.include_usage`. HelioAI 0.4.0
streams every lead turn, and until the meter learned to read chunks the whole 0.4.0
candidate sweep reported `0 ⚠️ not exact` — a zero with a warning on it is still a zero in a
table. The stream is therefore handed back wrapped, every chunk passes through unchanged,
and the usage is taken from the chunk that carries it.
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
        self._add(getattr(response, "usage", None))

    def _add(self, u) -> None:
        if u is None:
            # A provider that answered without a usage block: the total is no longer exact,
            # and saying so is the whole point of the flag.
            self.usage.exact = False
            return
        self.usage.prompt += int(getattr(u, "prompt_tokens", 0) or 0)
        self.usage.completion += int(getattr(u, "completion_tokens", 0) or 0)
        details = getattr(u, "prompt_tokens_details", None)
        self.usage.cached += int(getattr(details, "cached_tokens", 0) or 0) if details else 0
        self.usage.calls += 1


class MeteredStream:
    """A streamed completion that counts its own usage as the caller consumes it.

    The last usage seen wins rather than being summed: `include_usage` puts it on the final
    chunk only, and a provider that repeats a running total on every chunk must not be
    counted once per chunk. A stream abandoned before any usage arrived — the caller broke
    out, or the connection died — is counted as inexact, never as zero.
    """

    def __init__(self, stream, meter: TokenMeter) -> None:
        self._stream = stream
        self._meter = meter
        self._done = False

    def __getattr__(self, name):
        return getattr(self._stream, name)

    async def __aenter__(self):
        if hasattr(self._stream, "__aenter__"):
            await self._stream.__aenter__()
        return self

    async def __aexit__(self, *exc):
        if hasattr(self._stream, "__aexit__"):
            return await self._stream.__aexit__(*exc)
        return None

    def __aiter__(self):
        return self._chunks()

    async def _chunks(self):
        usage = None
        try:
            async for chunk in self._stream:
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                yield chunk
        finally:
            if not self._done:
                self._done = True
                self._meter._add(usage)


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
        if kwargs.get("stream") and getattr(response, "usage", None) is None:
            return MeteredStream(response, meter)
        meter._record(response)
        return response

    sdk.chat.completions.create = counting_create
    return meter
