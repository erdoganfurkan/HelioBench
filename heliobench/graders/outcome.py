"""Telling a run the agent got wrong from a run the infrastructure lost.

Until this existed, a provider timeout and a wrong answer were the same record: `passed:
false`. The 2026-08-25 arm on `1fcb2f0` carried two `APITimeoutError` runs as failures, and
the comparison against `main` only became honest after excluding them by hand — an exclusion
that favoured whichever arm happened to time out. A headline that moves when the network
hiccups is not measuring the agent.

The classification is deliberately narrow and the default is deliberately "the agent's
fault". Only exception classes that name a transport failure are excused. A new exception
class, a misconfigured key, a malformed request: all of those stay failures, because the
alternative is a rule under which any unexpected error launders itself into an excuse.
"""

from __future__ import annotations

from heliobench.trace import Trace

PASSED = "passed"
FAILED = "failed"
ERRORED = "errored"

OUTCOMES = (PASSED, FAILED, ERRORED)

# Exception class names, as the runner records them in `Trace.error` (`"{type}: {message}"`).
# Every one of these was seen in a stored trace or is the OpenAI-SDK sibling of one that was.
_TRANSPORT_CLASSES = frozenset(
    {
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailableError",
        "TimeoutError",
        "ConnectionError",
        "ConnectionResetError",
    }
)

# `OSError: [Errno 28] No space left on device` — the failure of 2026-08-21, which surfaced
# as a sqlite error inside the agent loop. Matched on the errno, not the English.
_ENOSPC_MARKERS = ("Errno 28", "No space left on device")

TRANSPORT = "transport"


def is_transport_error(error: str | None, kind: str | None = None) -> bool:
    """Whether a recorded error string names a failure outside the agent's control.

    `kind` is the adapter's own word: an adapter that knows a failure was transport can mark
    the trace, and that mark wins. Without it, the exception class at the head of the string
    decides.
    """
    if kind == TRANSPORT:
        return True
    if not error:
        return False
    head = error.split(":", 1)[0].strip()
    if head in _TRANSPORT_CLASSES:
        return True
    if head == "OSError" and any(m in error for m in _ENOSPC_MARKERS):
        return True
    return False


def classify(trace: Trace, passed: bool) -> str:
    """One of `OUTCOMES` for a graded run."""
    if trace.error and is_transport_error(trace.error, trace.error_kind):
        return ERRORED
    return PASSED if passed else FAILED
