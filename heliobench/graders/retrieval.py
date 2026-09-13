"""Tier n1: did the agent name the right archived product?

The strongest tier in the benchmark, because the verdict is string equality against
identifiers that either exist in the archive or do not. No physics judgement is involved, so
there is nothing for a reviewer to dispute except the task list itself.
"""

from __future__ import annotations

import re

from heliobench.graders import Result
from heliobench.tasks import Task
from heliobench.trace import Trace

# Mirrors the agent's own id shape. Deliberately duplicated rather than imported: a grader
# that imports the thing it grades cannot be run without it, and cannot outlive it.
_ID = re.compile(r"\b(?:amda|cda|csa|ssc)/[A-Za-z0-9_\-./]*[A-Za-z0-9_]")


def extract_ids(text: str) -> list[str]:
    """Product identifiers quoted in a piece of text, in order, without repeats."""
    seen: dict[str, None] = {}
    for m in _ID.finditer(text or ""):
        seen.setdefault(m.group(0), None)
    return list(seen)


def retrieved_ids(trace: Trace) -> list[str]:
    """Identifiers the search tools returned, in the order the agent was shown them.

    Reading them back out of the raw tool output rather than out of a structured field keeps
    this working across every search tool and every shape of result: what matters is the
    position an identifier occupied in what the agent saw.
    """
    seen: dict[str, None] = {}
    for e in trace.events_named("tool_output"):
        if "search" not in str(e["data"].get("name", "")):
            continue
        for i in extract_ids(str(e["data"].get("result", ""))):
            seen.setdefault(i, None)
    return list(seen)


def grade(task: Task, trace: Trace) -> Result:
    """Pass when the answer names one of the accepted products and invents none.

    Inventing an identifier fails the task even when a correct one is also present. A reply
    that offers a real product beside a fabricated one is not a partial success: the reader
    has no way to tell which is which, and that is the failure mode the whole tier exists to
    surface.
    """
    accepted = {i.strip() for i in task.expected.get("ids", []) if i.strip()}
    if not accepted:
        return Result(task.id, False, "task declares no accepted ids")

    quoted = extract_ids(trace.reply)
    hit = sorted(set(quoted) & accepted)

    # The agent checks its own ids against the catalogue and says so; taking its word here
    # keeps the grader from needing the 342 MB index.
    invented = sorted({i for ev in trace.events_named("invalid_ids") for i in ev["data"]["ids"]})

    # Where the answer sat in what the search returned. A tier scored on string equality is
    # 30 bits of information per sweep; the rank turns each of those into a graded one, and
    # separates a retrieval that never surfaced the product from a selection that passed it
    # over. `searched` is false for runs recorded before tool output was kept, and their
    # absent rank must not be read as a miss.
    retrieved = retrieved_ids(trace)
    outputs = [
        e for e in trace.events_named("tool_output") if "search" in str(e["data"].get("name", ""))
    ]
    searched = bool(outputs)
    # The adapter keeps the first 4000 characters of what a tool returned. An accepted id
    # beyond that cut was shown to the agent and not to us, so a missing rank here is not
    # evidence it was never retrieved — the report leaves truncated runs out of recall@k.
    truncated = any(e["data"].get("truncated") for e in outputs)
    rank = next((i + 1 for i, pid in enumerate(retrieved) if pid in accepted), None)

    detail = {
        "quoted": quoted,
        "accepted": sorted(accepted),
        "hit": hit,
        "invented": invented,
        "searched": searched,
        "truncated": truncated,
        "retrieved": len(retrieved),
        "rank": rank,
    }
    if invented:
        return Result(task.id, False, f"invented {len(invented)} id(s)", detail)
    if not hit:
        return Result(task.id, False, "no accepted id in the answer", detail)
    return Result(task.id, True, "", detail)
