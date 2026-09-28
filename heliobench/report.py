"""Turn a run directory into something a person, and a reviewer, can read.

The header is not decoration. A score without the model snapshot, the temperature, the index
it searched and the exact task-set fingerprint is a number nobody can reproduce or contest,
and the review literature is unanimous that reporting accuracy without cost is a defect.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from heliobench.graders.outcome import ERRORED, PASSED
from heliobench.stats import summarise


def outcome_of(record: dict) -> bool | None:
    """The three-way verdict of a stored record: True, False, or None for errored.

    Records written before `outcome` existed carry only the boolean, and are read as it
    says: a re-grade rewrites them with the field, and until then a stored error stays a
    failure rather than being guessed at.
    """
    out = record.get("outcome")
    if out == ERRORED:
        return None
    if out is not None:
        return out == PASSED
    return bool(record["passed"])


def _by_task(records: list[dict], tier: str | None = None) -> tuple[dict, dict]:
    per_task: dict[str, list[bool | None]] = defaultdict(list)
    events: dict[str, str] = {}
    for r in records:
        if tier and r["tier"] != tier:
            continue
        per_task[r["task_id"]].append(outcome_of(r))
        events[r["task_id"]] = r["event"]
    return per_task, events


def _totals(records: list[dict]) -> dict:
    keys = (
        "tool_calls",
        "tool_errors",
        "retries",
        "invented_ids",
        "recipes_bypassed",
        "contradicted",
        "unsourced",
        "harness_matched",
        "harness_derived",
        "harness_unsourced",
        "ledger_entries",
        "n_iterations",
        "tokens_prompt",
        "tokens_completion",
        "tokens_cached",
        "tokens_self_reported",
    )
    out = {k: sum(r["metrics"].get(k, 0) for r in records) for k in keys}
    out["wall_s"] = round(sum(r["metrics"].get("wall_s", 0.0) for r in records), 1)
    out["runs"] = len(records)
    out["tokens_exact"] = all(r["metrics"].get("tokens_exact", True) for r in records)
    out["provenance_reported"] = sum(1 for r in records if r["metrics"].get("provenance_reported"))
    out["gated"] = sum(1 for r in records if (r.get("detail") or {}).get("gate") == "contradicted")
    return out


def _retrieval_lines(records: list[dict]) -> list[str]:
    """Where the accepted identifier sat in what the search returned, over the n1 runs.

    A tier graded on string equality yields one bit per run. The rank grades the same run: a
    failure with the product ranked first is a selection defect, a failure with it never
    returned is a retrieval defect, and the two have nothing to do with each other. Runs
    recorded before tool output was kept carry no rank and are left out rather than counted
    as misses.
    """
    measured = [r for r in records if r["tier"] == "n1" and (r.get("detail") or {}).get("searched")]
    if not measured:
        return []
    # A run whose search output was cut at the adapter's limit and whose accepted id was not
    # in the kept part is not a "never returned": the id may have been past the cut. Such runs
    # are counted, not ranked. A run where the id *was* found before the cut is ranked as
    # usual — the cut cannot have moved it.
    truncated_unranked = [
        r
        for r in measured
        if (r.get("detail") or {}).get("truncated") and not (r.get("detail") or {}).get("rank")
    ]
    ranked = [r for r in measured if r not in truncated_unranked]
    ranks = [(r.get("detail") or {}).get("rank") for r in ranked]
    n = len(ranks)
    if not n:
        return []

    def recall_at(k: int) -> float:
        return sum(1 for x in ranks if x and x <= k) / n

    mrr = sum(1 / x for x in ranks if x) / n
    return [
        "## Retrieval (n1)",
        "",
        "| Runs measured | MRR | recall@1 | recall@3 | recall@5 | never returned | truncated, unranked |",
        "|---|---|---|---|---|---|---|",
        f"| {n} | {mrr:.3f} | {recall_at(1):.1%} | {recall_at(3):.1%} | {recall_at(5):.1%} | "
        f"{sum(1 for x in ranks if not x)} | {len(truncated_unranked)} |",
        "",
        "Rank of the first accepted identifier inside what the search tools returned, in the",
        "order the agent was shown them. It splits a wrong answer into the two defects that",
        "look identical in the pass rate: never retrieved, or retrieved and passed over. A run",
        "whose search output was cut at the trace's limit before any accepted id appeared",
        "is left out of the rank rather than counted as never returned.",
        "",
        *_answer_lines(records),
    ]


def _answer_lines(records: list[dict]) -> list[str]:
    """How the n1 answers named their product — reported beside the score, not gated."""
    done = [r for r in records if r["tier"] == "n1" and outcome_of(r) is not None]
    with_detail = [r for r in done if "first_accepted" in (r.get("detail") or {})]
    if not with_detail:
        return []
    passed = [r for r in with_detail if outcome_of(r)]
    hedged = sum(1 for r in passed if r["detail"].get("hedged"))
    strict = sum(1 for r in with_detail if outcome_of(r) and r["detail"].get("first_accepted"))
    clean = [
        r for r in with_detail if r["detail"].get("searched") and not r["detail"].get("truncated")
    ]
    unreturned = sum(1 for r in clean if r["detail"].get("unreturned"))
    n = len(with_detail)
    return [
        "| Passed | …also naming a non-accepted id | Passed, first id named accepted | "
        "Named an id no search returned |",
        "|---|---|---|---|",
        f"| {len(passed)}/{n} | {hedged} | {strict}/{n} ({strict / n:.1%}) | "
        f"{unreturned}/{len(clean)} |",
        "",
        "A pass names an accepted id and invents none; a reply that also offers other products",
        "still passes, and the stricter column counts only replies whose first id is accepted.",
        "The last column is the harness's own view of invention, independent of the agent's",
        "`invalid_ids` report, over the runs that searched and whose output was kept whole.",
        "",
    ]


def load_prices(path: Path) -> dict:
    """USD per million tokens by model, from a YAML file the caller owns.

    Not shipped: prices change monthly and differ by contract, and a benchmark that carried
    a price table would publish yesterday's cost as today's. Shape:

        deepseek-v4-pro: {input: 0.27, output: 1.10, cached: 0.07}
    """
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping of model -> prices")
    return data


def cost_usd(prompt: int, completion: int, cached: int, model, prices: dict | None):
    """USD for one token count, or None when the model has no price."""
    p = (prices or {}).get(model or "")
    if not p:
        return None
    cached_rate = p.get("cached", p.get("input", 0))
    fresh = max(prompt - cached, 0)
    return (
        fresh * p.get("input", 0) + cached * cached_rate + completion * p.get("output", 0)
    ) / 1e6


def _cost_rows(t: dict, model, prices) -> list[str]:
    usd = cost_usd(t["tokens_prompt"], t["tokens_completion"], t["tokens_cached"], model, prices)
    if usd is None:
        return []
    note = "" if t["tokens_exact"] else " ⚠️ not exact"
    return [f"| Cost (USD){note} | {usd:.4f} | {usd / max(t['runs'], 1):.4f} |"]


def _percentile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _tier_process_lines(records: list[dict], jobs: int, model, prices) -> list[str]:
    """Process per tier: n1 lookups and n3 analyses cost an order of magnitude apart, and a
    total over both says little about either."""
    tiers = sorted({r["tier"] for r in records})
    if len(tiers) < 2:
        return []
    priced = cost_usd(1, 1, 0, model, prices) is not None
    head = "| Tier | Runs | Tool calls/run | LLM turns/run | Tokens/run |"
    sep = "|---|---|---|---|---|"
    if priced:
        head += " USD/run |"
        sep += "---|"
    if jobs == 1:
        head += " Wall p50 | Wall p95 |"
        sep += "---|---|"
    out = ["## Process by tier", "", head, sep]
    for tier in tiers:
        rs = [r for r in records if r["tier"] == tier]
        t = _totals(rs)
        n = max(t["runs"], 1)
        row = (
            f"| {tier} | {t['runs']} | {t['tool_calls'] / n:.1f} | {t['n_iterations'] / n:.1f} | "
            f"{(t['tokens_prompt'] + t['tokens_completion']) / n:.0f}"
            + ("" if t["tokens_exact"] else " ⚠️")
            + " |"
        )
        if priced:
            usd = cost_usd(
                t["tokens_prompt"], t["tokens_completion"], t["tokens_cached"], model, prices
            )
            row += f" {usd / n:.4f} |"
        if jobs == 1:
            walls = [r["metrics"].get("wall_s", 0.0) for r in rs]
            row += f" {_percentile(walls, 0.5):.1f} s | {_percentile(walls, 0.95):.1f} s |"
        out.append(row)
    return out + [""]


def _matrix_lines(records: list[dict], runs: int) -> list[str]:
    """Every task, every repetition: the table a reader goes to after the headline."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by[r["task_id"]].append(r)
    if not by:
        return []
    mark = {True: "✓", False: "✗", None: "e"}
    out = [
        "## Per task",
        "",
        "`✓` passed, `✗` failed, `e` errored, one mark per repetition. Rank is the n1 rank of",
        "the first accepted id in what the search returned (mean over repetitions).",
        "",
        "| Task | Tier | Runs | Tokens/run | Tool calls/run | Rank |",
        "|---|---|---|---|---|---|",
    ]
    for tid in sorted(by):
        rs = sorted(by[tid], key=lambda r: r["run"])
        marks = "".join(mark[outcome_of(r)] for r in rs)
        n = len(rs)
        tokens = sum(
            r["metrics"].get("tokens_prompt", 0) + r["metrics"].get("tokens_completion", 0)
            for r in rs
        )
        calls = sum(r["metrics"].get("tool_calls", 0) for r in rs)
        ranks = [(r.get("detail") or {}).get("rank") for r in rs]
        ranks = [x for x in ranks if x]
        rank = f"{sum(ranks) / len(ranks):.1f}" if ranks else "—"
        out.append(
            f"| `{tid}` | {rs[0]['tier']} | {marks} | {tokens / n:.0f} | {calls / n:.1f} | {rank} |"
        )
    return out + [""]


def _config_cell(agent: dict) -> str | None:
    """The agent's behaviour settings in one cell, or None for a header that predates them."""
    if "agent_env" not in agent and "experiments" not in agent:
        return None
    bits = [
        f"experiments: {', '.join(agent.get('experiments') or []) or 'none'}",
        "role models: "
        + (
            ", ".join(
                f"{r}→{'/'.join(str(x) for x in v if x)}" for r, v in agent["role_models"].items()
            )
            if agent.get("role_models")
            else "none"
        ),
    ]
    if agent.get("judgment"):
        bits.append(f"judgment: {agent['judgment'].get('backend')}")
    if agent.get("vision"):
        bits.append(f"vision: {'on' if agent['vision'].get('enabled') else 'off'}")
    if "mcp_servers" in agent:
        bits.append(f"MCP servers: {'yes' if agent['mcp_servers'] else 'none'}")
    if "rag_hybrid" in agent:
        bits.append(f"hybrid search: {'on' if agent['rag_hybrid'] else 'off'}")
    env = agent.get("agent_env") or {}
    bits.append("--agent-env: " + (", ".join(f"`{k}={v}`" for k, v in env.items()) or "none"))
    return " · ".join(bits)


def _header(meta: dict) -> list[str]:
    """The table that says which arm this is, and what of the run is missing or redone."""
    agent = meta.get("agent", {})
    index = f"`{agent.get('index_dir', 'n/a')}` ({agent.get('index_size', 'n/a')} products"
    index += f", digest `{agent['index_digest']}`)" if agent.get("index_digest") else ")"
    rows = [
        ("Generated", meta.get("generated", "")),
        ("Agent", f"`{agent.get('agent', '?')}` {agent.get('agent_version', '')}"),
    ]
    if agent.get("agent_ref"):
        rows.append(("Agent ref", f"`{agent['agent_ref']}`"))
    rows += [
        ("Provider / model", f"{agent.get('provider', '?')} / `{agent.get('model', '?')}`"),
        ("Temperature", agent.get("temperature", "n/a")),
    ]
    if agent.get("max_iterations") is not None:
        limits = f"{agent['max_iterations']} iterations"
        if agent.get("max_output_tokens"):
            limits += f", {agent['max_output_tokens']} output tokens"
        rows.append(("Limits", limits))
    config = _config_cell(agent)
    if config:
        rows.append(("Agent config", config))
    rows += [
        ("Search index", index),
        ("Task set", f"{meta.get('n_tasks')} tasks, digest `{meta.get('task_set_digest')}`"),
    ]
    if meta.get("fixture_digests"):
        rows.append(
            ("Fixtures", ", ".join(f"{k} `{v}`" for k, v in meta["fixture_digests"].items()))
        )
    rows += [
        ("Repetitions", meta.get("runs")),
        ("Concurrency", meta.get("jobs", 1)),
    ]
    harness = f"heliobench {meta.get('heliobench')} on Python {meta.get('python')}"
    if agent.get("env_digest"):
        deps = ", ".join(f"{k} {v}" for k, v in (agent.get("dependencies") or {}).items())
        harness += f"; environment `{agent['env_digest']}`" + (f" ({deps})" if deps else "")
    rows += [("Harness", harness), ("Elapsed", f"{meta.get('elapsed_s')} s")]
    if meta.get("status") and meta["status"] != "complete":
        rows.append(("Status", f"⚠️ {meta['status']} — `run --resume` finishes it"))
    if meta.get("resumed"):
        rows.append(
            ("Resumed", f"{meta['resumed']} repetition(s) regraded from a previous attempt")
        )
    if meta.get("regraded"):
        rows.append(("Regraded", meta["regraded"]))
    unscored = meta.get("unscored_traces") or []
    if unscored:
        tids = sorted({u["task_id"] for u in unscored})
        rows.append(
            (
                "Unscored traces",
                f"{len(unscored)} — the prompt changed since the run ({', '.join(tids)})",
            )
        )
    if meta.get("skipped_traces"):
        rows.append(
            ("Skipped traces", f"tasks no longer in the set: {', '.join(meta['skipped_traces'])}")
        )
    agent_name = f"{agent.get('agent', '?')} {agent.get('agent_version', '')}".rstrip()
    return [f"# HelioBench — {agent_name}", "", "| | |", "|---|---|"] + [
        f"| {k} | {v} |" for k, v in rows
    ]


def build(meta: dict, records: list[dict], prices: dict | None = None) -> str:
    """Render the markdown report.

    `prices` maps a model name to USD per million tokens (`input`, `output`, `cached`); with
    it the process tables gain a cost line. Without it cost stays in tokens, which is exact.
    """
    agent = meta.get("agent", {})
    lines = _header(meta) + [
        "",
        "## Score",
        "",
        "| Tier | Tasks | Events | Mean | 95% CI | pass^k | pass≥1 | Errored |",
        "|---|---|---|---|---|---|---|---|",
    ]
    runs = int(meta.get("runs", 1))
    not_comparable: list[str] = []
    for tier in ("n1", "n2", "n3", None):
        per_task, events = _by_task(records, tier)
        if not per_task:
            continue
        s = summarise(per_task, events, runs)
        label = tier or "**all**"
        errored = str(s.n_errored)
        if s.n_unscored:
            errored += f" ({s.n_unscored} task(s) unscored)"
        if not s.comparable:
            errored += " ⚠️"
            not_comparable.append(label)
        lines.append(
            f"| {label} | {s.n_tasks} | {s.n_events} | {s.mean:.1%} | "
            f"[{s.ci[0]:.1%}, {s.ci[1]:.1%}] | {s.pass_k:.1%} | {s.pass_any:.1%} | {errored} |"
        )

    t = _totals(records)
    cost_note = "" if t["tokens_exact"] else " ⚠️ not exact"
    jobs = int(meta.get("jobs", 1))
    # Under contention the per-run wall clock measures queueing, not the agent. It was used
    # once to detect a machine suspend mid-sweep, and a figure that silently stopped meaning
    # that would be worse than no figure.
    wall_per_run = f"{t['wall_s'] / max(t['runs'], 1):.1f} s" if jobs == 1 else f"— (jobs={jobs})"
    lines += [
        "",
        "The interval is bootstrapped over events, not tasks: several questions about one",
        "event are several looks at the same event. `pass^k` is the fraction passing on every",
        "repetition — the gap to `pass≥1` is how much of the score is luck. An errored run is",
        "one the provider or the network lost; it leaves every denominator, and a task whose",
        "every repetition errored is unscored rather than failed.",
        "",
    ]
    if runs == 1:
        lines += [
            "⚠️ **One repetition:** `pass^k` and `pass≥1` equal the mean and say nothing about",
            "reproducibility. Quote a published figure from `--runs 3` or more.",
            "",
        ]
    qualities = defaultdict(set)
    for r in records:
        if r.get("quality"):
            qualities[r["quality"]].add(r["task_id"])
    if qualities:
        lines += [
            "Interval quality: "
            + ", ".join(f"{len(v)} {k.replace('_', ' ')}" for k, v in sorted(qualities.items()))
            + " — a *proxy* interval is derived by a stated rule around a published event",
            "time rather than taken from a paper, and agreeing with it is the weaker claim.",
            "",
        ]
    if not_comparable:
        lines += [
            f"⚠️ **Not comparable:** {', '.join(not_comparable)} — more than 10% of the runs",
            "errored. A score with that much of the sweep missing cannot be quoted against",
            "another arm; re-run the errored tasks first.",
            "",
        ]
    lines += [
        "## Process",
        "",
        "| Metric | Total | Per run |",
        "|---|---|---|",
        f"| Tool calls | {t['tool_calls']} | {t['tool_calls'] / max(t['runs'], 1):.1f} |",
        f"| Tool errors | {t['tool_errors']} | {t['tool_errors'] / max(t['runs'], 1):.2f} |",
        f"| Provider retries | {t['retries']} | {t['retries'] / max(t['runs'], 1):.2f} |",
        f"| LLM turns | {t['n_iterations']} | {t['n_iterations'] / max(t['runs'], 1):.1f} |",
        f"| Invented identifiers | {t['invented_ids']} | {t['invented_ids'] / max(t['runs'], 1):.2f} |",
        f"| Recipes bypassed | {t['recipes_bypassed']} | {t['recipes_bypassed'] / max(t['runs'], 1):.2f} |",
        f"| Answers contradicting the ledger (gate) | {t['gated']} | — |",
        f"| Numbers contradicted, by the agent's own count | {t['contradicted']} | — |",
        f"| Numbers no computation produced, by the agent's count | {t['unsourced']} | — |",
        f"| Numbers no computation produced, by the harness | {t['harness_unsourced']} | — |",
        f"| Numbers the harness sourced from the ledger | {t['harness_matched'] + t['harness_derived']} | — |",
        f"| Ledger entries | {t['ledger_entries']} | {t['ledger_entries'] / max(t['runs'], 1):.1f} |",
        f"| Prompt tokens{cost_note} | {t['tokens_prompt']} | {t['tokens_prompt'] / max(t['runs'], 1):.0f} |",
        f"| Completion tokens{cost_note} | {t['tokens_completion']} | {t['tokens_completion'] / max(t['runs'], 1):.0f} |",
        f"| of which prompt tokens served from cache | {t['tokens_cached']} | {t['tokens_cached'] / max(t['runs'], 1):.0f} |",
        *(
            [
                f"| Sub-agent runs on their own model, tokens as the agent reported them | {t['tokens_self_reported']} | — |"
            ]
            if t["tokens_self_reported"]
            else []
        ),
        *_cost_rows(t, agent.get("model"), prices),
        f"| Wall clock | {t['wall_s']} s | {wall_per_run} |",
        "",
    ]
    lines += _tier_process_lines(records, jobs, agent.get("model"), prices)
    lines += _retrieval_lines(records)
    errored = [r for r in records if outcome_of(r) is None]
    if errored:
        lines += [
            "## Errored",
            "",
            "Runs the infrastructure lost, not the agent. Excluded from every score above.",
            "",
            "| Task | Run | Error |",
            "|---|---|---|",
        ]
        for r in sorted(errored, key=lambda r: (r["task_id"], r["run"])):
            lines.append(f"| `{r['task_id']}` | {r['run']} | {(r['reason'] or '?')[:90]} |")
        lines.append("")
    lines += ["## Failures", ""]
    failed = defaultdict(list)
    for r in records:
        if outcome_of(r) is False:
            failed[r["task_id"]].append(r["reason"] or "?")
    if not failed:
        lines.append("None.")
    else:
        lines += ["| Task | Runs failed | First reason |", "|---|---|---|"]
        for tid in sorted(failed):
            lines.append(f"| `{tid}` | {len(failed[tid])}/{runs} | {failed[tid][0][:90]} |")
    lines += ["", *_matrix_lines(records, runs)]
    return "\n".join(lines) + "\n"


def write(out_dir: Path, prices: dict | None = None, html: bool = False) -> Path:
    """Rebuild report.md and results.csv (and report.html) from a run's stored records."""
    out_dir = Path(out_dir)
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    records = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))

    md = out_dir / "report.md"
    text = build(meta, records, prices)
    md.write_text(text, encoding="utf-8")
    if html:
        from heliobench.htmlreport import render

        (out_dir / "report.html").write_text(render(text), encoding="utf-8")

    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["task_id", "tier", "event", "run", "passed", "outcome", "reason"])
        for r in records:
            w.writerow(
                [
                    r["task_id"],
                    r["tier"],
                    r["event"],
                    r["run"],
                    r["passed"],
                    r.get("outcome", PASSED if r["passed"] else "failed"),
                    r["reason"],
                ]
            )
    return md
