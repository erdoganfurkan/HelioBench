"""How the answer was reached, regardless of whether it was right.

These are the numbers that move when an agent's architecture changes but its accuracy does
not. A run that gets the right answer while inventing an identifier, skipping the calibrated
method and stating figures no computation produced is a run that will be wrong next week.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from heliobench.trace import Trace


@dataclass
class ProcessMetrics:
    """Attributes:
    unsourced: numbers the answer states that no computation in the session produced,
        by the agent's own count.
    contradicted: numbers the session computed *differently* from what the answer claims,
        by the agent's own count. Reported, never gated: the gate recomputes its own
        verdict in `graders.provenance`, and the two are shown side by side.
    recipes_bypassed: calibrated methods that were reimplemented from memory, or read and
        then not actually called.
    retries: provider calls that failed transiently and were repeated; the run paid for
        them in latency, not in tokens, and a sweep full of them is a provider problem.
    harness_matched, harness_derived, harness_unsourced: the harness's own classification
        of every number in the reply against the ledger, so the agent's count can be checked
        rather than trusted.
    """

    n_iterations: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    retries: int = 0
    matched: int = 0
    contradicted: int = 0
    derived: int = 0
    unsourced: int = 0
    provenance_reported: bool = False
    harness_matched: int = 0
    harness_derived: int = 0
    harness_unsourced: int = 0
    invented_ids: int = 0
    recipes_bypassed: int = 0
    ledger_entries: int = 0
    figures: int = 0
    wall_s: float = 0.0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_exact: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


def collect(trace: Trace) -> ProcessMetrics:
    """Read every process metric the agent already computed, plus the ones the harness timed.

    `provenance_reported` is kept separately from the four counts on purpose: the agent stays
    silent when nothing was computed, and an absent report is not the same as four zeros.
    """
    m = ProcessMetrics(
        n_iterations=trace.n_iterations,
        tool_calls=len(trace.tool_calls()),
        tool_errors=sum(
            1
            for e in trace.events_named("tool_result")
            if str(e["data"].get("summary", "")).startswith("error: ")
        ),
        retries=len(trace.events_named("retry")),
        invented_ids=sum(len(e["data"]["ids"]) for e in trace.events_named("invalid_ids")),
        recipes_bypassed=sum(
            len(e["data"]["recipes"]) for e in trace.events_named("recipe_bypassed")
        ),
        ledger_entries=len(trace.ledger.get("values", [])),
        figures=sum(
            len(a.get("figure_paths", [])) for a in trace.artifacts if a.get("kind") == "image"
        ),
        wall_s=trace.wall_s,
        tokens_prompt=trace.tokens.prompt,
        tokens_completion=trace.tokens.completion,
        tokens_exact=trace.tokens.exact,
    )
    prov = trace.events_named("provenance")
    if prov:
        d = prov[-1]["data"]
        m.provenance_reported = True
        m.matched = int(d.get("matched", 0))
        m.contradicted = int(d.get("contradicted", 0))
        m.derived = int(d.get("derived", 0))
        m.unsourced = int(d.get("unsourced", 0))
    if trace.ledger.get("values"):
        from heliobench.graders.provenance import classify_prose

        h = classify_prose(trace.reply, trace.ledger, trace.prompt)
        m.harness_matched, m.harness_derived, m.harness_unsourced = (
            h.matched,
            h.derived,
            h.unsourced,
        )
    return m
