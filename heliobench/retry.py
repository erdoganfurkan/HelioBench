"""Retry a provider call that failed for a reason the provider will get over.

A rate limit or a dropped connection costs one errored run without this, and `--jobs` above
one manufactures exactly those: eight concurrent requests against a per-minute quota is a
`429` on the ninth. Backing off inside the call turns that into latency, which the token count
does not see and the wall clock, already meaningless under concurrency, does not need to.

Only failures that are transient by construction are retried. A quota that resets at midnight
is a `RateLimitError` too, and retrying it five times is thirty seconds wasted before the run
errors out — that is the accepted price of not having to know the provider's message formats.
Nothing that could be the agent's fault is retried: a `BadRequestError` is a malformed request
and retrying it would only repeat the fault.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from heliobench.trace import Trace

# By class name rather than by import: the harness must not depend on the provider SDK to
# know which of its exceptions are transient.
RETRIABLE = frozenset(
    {
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "ServiceUnavailableError",
        "ConnectionResetError",
    }
)


def is_retriable(exc: BaseException) -> bool:
    return type(exc).__name__ in RETRIABLE


async def with_backoff(
    call: Callable[..., Awaitable],
    *,
    attempts: int = 5,
    base_s: float = 1.0,
    cap_s: float = 30.0,
    sleep: Callable[[float], Awaitable] = asyncio.sleep,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
    **kwargs,
):
    """Await `call(**kwargs)`, retrying a transient failure with exponential backoff.

    `on_retry(attempt, exc, delay)` is called before each sleep, so the caller can record the
    retry in the trace: a run that needed four attempts to answer is a fact about the
    provider that the report should carry.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await call(**kwargs)
        except Exception as e:
            if not is_retriable(e) or attempt == attempts:
                raise
            delay = min(cap_s, base_s * 2 ** (attempt - 1))
            if on_retry:
                on_retry(attempt, e, delay)
            await sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def attach_backoff(llm_client, trace: Trace, t0: float, **policy) -> None:
    """Wrap the SDK call on `llm_client` with `with_backoff`, recording retries in `trace`.

    Layered over whatever already wraps `create` — the token meter, in practice — so every
    attempt that returns is counted and every one that raises is retried.
    """
    import time

    sdk = getattr(llm_client, "_client", None)
    completions = getattr(getattr(sdk, "chat", None), "completions", None)
    create = getattr(completions, "create", None)
    if create is None:
        return

    def record(attempt: int, exc: BaseException, delay: float) -> None:
        trace.events.append(
            {
                "event": "retry",
                "data": {"attempt": attempt, "error": type(exc).__name__, "delay_s": delay},
                "t": round(time.monotonic() - t0, 3),
            }
        )

    async def retrying_create(**kwargs):
        return await with_backoff(create, on_retry=record, **policy, **kwargs)

    completions.create = retrying_create
