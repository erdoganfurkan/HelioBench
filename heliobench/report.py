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

from heliobench.stats import summarise


def _by_task(records: list[dict], tier: str | None = None) -> tuple[dict, dict]:
    per_task: dict[str, list[bool]] = defaultdict(list)
    events: dict[str, str] = {}
    for r in records:
        if tier and r["tier"] != tier:
            continue
        per_task[r["task_id"]].append(bool(r["passed"]))
        events[r["task_id"]] = r["event"]
    return per_task, events


def _totals(records: list[dict]) -> dict:
    keys = (
        "tool_calls",
        "tool_errors",
        "invented_ids",
        "recipes_bypassed",
        "contradicted",
        "unsourced",
        "ledger_entries",
        "n_iterations",
        "tokens_prompt",
        "tokens_completion",
    )
    out = {k: sum(r["metrics"].get(k, 0) for r in records) for k in keys}
    out["wall_s"] = round(sum(r["metrics"].get("wall_s", 0.0) for r in records), 1)
    out["runs"] = len(records)
    out["tokens_exact"] = all(r["metrics"].get("tokens_exact", True) for r in records)
    out["provenance_reported"] = sum(1 for r in records if r["metrics"].get("provenance_reported"))
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
    ranks = [(r.get("detail") or {}).get("rank") for r in measured]
    n = len(ranks)

    def recall_at(k: int) -> float:
        return sum(1 for x in ranks if x and x <= k) / n

    mrr = sum(1 / x for x in ranks if x) / n
    return [
        "## Retrieval (n1)",
        "",
        "| Runs measured | MRR | recall@1 | recall@3 | recall@5 | never returned |",
        "|---|---|---|---|---|---|",
        f"| {n} | {mrr:.3f} | {recall_at(1):.1%} | {recall_at(3):.1%} | {recall_at(5):.1%} | "
        f"{sum(1 for x in ranks if not x)} |",
        "",
        "Rank of the first accepted identifier inside what the search tools returned, in the",
        "order the agent was shown them. It splits a wrong answer into the two defects that",
        "look identical in the pass rate: never retrieved, or retrieved and passed over.",
        "",
    ]


def build(meta: dict, records: list[dict]) -> str:
    """Render the markdown report."""
    agent = meta.get("agent", {})
    lines = [
        f"# HelioBench — {agent.get('agent', '?')} {agent.get('agent_version', '')}".rstrip(),
        "",
        "| | |",
        "|---|---|",
        f"| Generated | {meta.get('generated', '')} |",
        f"| Agent | `{agent.get('agent', '?')}` {agent.get('agent_version', '')} |",
        f"| Provider / model | {agent.get('provider', '?')} / `{agent.get('model', '?')}` |",
        f"| Temperature | {agent.get('temperature', 'n/a')} |",
        f"| Search index | `{agent.get('index_dir', 'n/a')}` ({agent.get('index_size', 'n/a')} products) |",
        f"| Task set | {meta.get('n_tasks')} tasks, digest `{meta.get('task_set_digest')}` |",
        f"| Repetitions | {meta.get('runs')} |",
        f"| Harness | heliobench {meta.get('heliobench')} on Python {meta.get('python')} |",
        f"| Elapsed | {meta.get('elapsed_s')} s |",
        "",
        "## Score",
        "",
        "| Tier | Tasks | Events | Mean | 95% CI | pass^k | pass≥1 |",
        "|---|---|---|---|---|---|---|",
    ]
    runs = int(meta.get("runs", 1))
    for tier in ("n1", "n2", "n3", None):
        per_task, events = _by_task(records, tier)
        if not per_task:
            continue
        s = summarise(per_task, events, runs)
        label = tier or "**all**"
        lines.append(
            f"| {label} | {s.n_tasks} | {s.n_events} | {s.mean:.1%} | "
            f"[{s.ci[0]:.1%}, {s.ci[1]:.1%}] | {s.pass_k:.1%} | {s.pass_any:.1%} |"
        )

    t = _totals(records)
    cost_note = "" if t["tokens_exact"] else " ⚠️ not exact"
    lines += [
        "",
        "The interval is bootstrapped over events, not tasks: several questions about one",
        "event are several looks at the same event. `pass^k` is the fraction passing on every",
        "repetition — the gap to `pass≥1` is how much of the score is luck.",
        "",
        "## Process",
        "",
        "| Metric | Total | Per run |",
        "|---|---|---|",
        f"| Tool calls | {t['tool_calls']} | {t['tool_calls'] / max(t['runs'], 1):.1f} |",
        f"| Tool errors | {t['tool_errors']} | {t['tool_errors'] / max(t['runs'], 1):.2f} |",
        f"| LLM turns | {t['n_iterations']} | {t['n_iterations'] / max(t['runs'], 1):.1f} |",
        f"| Invented identifiers | {t['invented_ids']} | {t['invented_ids'] / max(t['runs'], 1):.2f} |",
        f"| Recipes bypassed | {t['recipes_bypassed']} | {t['recipes_bypassed'] / max(t['runs'], 1):.2f} |",
        f"| Numbers contradicted by the ledger | {t['contradicted']} | — |",
        f"| Numbers no computation produced | {t['unsourced']} | — |",
        f"| Ledger entries | {t['ledger_entries']} | {t['ledger_entries'] / max(t['runs'], 1):.1f} |",
        f"| Prompt tokens{cost_note} | {t['tokens_prompt']} | {t['tokens_prompt'] / max(t['runs'], 1):.0f} |",
        f"| Completion tokens{cost_note} | {t['tokens_completion']} | {t['tokens_completion'] / max(t['runs'], 1):.0f} |",
        f"| Wall clock | {t['wall_s']} s | {t['wall_s'] / max(t['runs'], 1):.1f} s |",
        "",
    ]
    lines += _retrieval_lines(records)
    lines += ["## Failures", ""]
    failed = defaultdict(list)
    for r in records:
        if not r["passed"]:
            failed[r["task_id"]].append(r["reason"] or "?")
    if not failed:
        lines.append("None.")
    else:
        lines += ["| Task | Runs failed | First reason |", "|---|---|---|"]
        for tid in sorted(failed):
            lines.append(f"| `{tid}` | {len(failed[tid])}/{runs} | {failed[tid][0][:90]} |")
    return "\n".join(lines) + "\n"


def write(out_dir: Path) -> Path:
    """Rebuild report.md and results.csv from a run directory's stored records."""
    out_dir = Path(out_dir)
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    records = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))

    md = out_dir / "report.md"
    md.write_text(build(meta, records), encoding="utf-8")

    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["task_id", "tier", "event", "run", "passed", "reason"])
        for r in records:
            w.writerow([r["task_id"], r["tier"], r["event"], r["run"], r["passed"], r["reason"]])
    return md
