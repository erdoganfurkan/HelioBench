"""Two arms over the same questions, compared the paired way.

Every paired comparison in this project before this file was a scratch script run by hand and
transcribed into a summary — which is how a benchmark publishes a p-value nobody can recompute.
The command refuses two runs whose `task_set_digest` differs: different digests mean different
questions were asked, and there is no honest number to print for that.

Two collapsings of k repetitions into one verdict per task are reported, because they answer
different questions. Strict (`pass^k`) asks whether the arm is reliable; majority asks whether
it is usually right. An arm can win one and lose the other, and a reader should see both.

Two runs may also be compared on part of what they asked — one tier (`--tier`), or the tasks
both asked in the same wording (`--shared`) — but only through the per-task digests in
`meta.json`, never by trusting that a task id still names the same question. Everything
else that differs between the arms (model, index, experiments, dependencies, grader
version) is listed above the result: a comparison is only as clean as the one difference it
was meant to measure, and the September 0.3.0-vs-0.4.0 arms also differed by their index.

Beside the verdicts, the process metrics are paired task by task — tokens, tool calls, LLM
turns, wall clock, the n1 rank — with an exact sign test, because an architecture change
that leaves accuracy flat is exactly the one whose cost moves.
"""

from __future__ import annotations

import json
from pathlib import Path

from heliobench.report import outcome_of
from heliobench.stats import mcnemar, sign_test

# What a reader must see differ before believing a difference in scores. Agent keys first,
# then run-level keys; `agent_ref`/`agent_version` are listed too, being usually the point.
_ARM_KEYS = (
    "agent_version",
    "agent_ref",
    "provider",
    "model",
    "temperature",
    "max_output_tokens",
    "max_iterations",
    "restricted",
    "experiments",
    "role_models",
    "judgment",
    "vision",
    "mcp_servers",
    "rag_hybrid",
    "agent_env",
    "index_dir",
    "index_size",
    "index_digest",
    "env_digest",
    "dependencies",
)
_RUN_KEYS = ("heliobench", "runs", "jobs", "fixture_digests", "regraded")


class CompareError(ValueError):
    """Two runs that cannot be compared without lying about one of them."""


def load_run(run_dir: Path) -> tuple[dict, list[dict]]:
    """`meta.json` and `results.json` of a run directory."""
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    records = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    return meta, records


def collapse(records: list[dict], how: str) -> dict[str, bool]:
    """One verdict per task from its completed repetitions.

    Errored repetitions are dropped before collapsing, and a task with none left is absent
    from the result rather than scored: a comparison over it would be a comparison of two
    guesses.
    """
    outs: dict[str, list[bool]] = {}
    for r in records:
        o = outcome_of(r)
        if o is not None:
            outs.setdefault(r["task_id"], []).append(o)
    if how == "strict":
        return {t: all(v) for t, v in outs.items()}
    if how == "majority":
        return {t: sum(v) * 2 > len(v) for t, v in outs.items()}
    raise ValueError(f"unknown collapsing {how!r}")


def differences(meta_a: dict, meta_b: dict) -> list[tuple[str, object, object]]:
    """`(key, a, b)` for everything recorded about the two arms that is not the same.

    A key only one side recorded is listed too, as absent on the other: an arm recorded
    before a field existed is not evidence the field was equal.
    """
    out = []
    ag_a, ag_b = meta_a.get("agent", {}) or {}, meta_b.get("agent", {}) or {}
    for k in _ARM_KEYS:
        if (k in ag_a or k in ag_b) and ag_a.get(k) != ag_b.get(k):
            out.append((k, ag_a.get(k, "—"), ag_b.get(k, "—")))
    for k in _RUN_KEYS:
        if k == "regraded":
            ra, rb = bool(meta_a.get(k)), bool(meta_b.get(k))
            if ra != rb:
                out.append(("regraded", ra, rb))
            continue
        if (k in meta_a or k in meta_b) and meta_a.get(k) != meta_b.get(k):
            out.append((k, meta_a.get(k, "—"), meta_b.get(k, "—")))
    return out


def _scope(meta_a, rec_a, meta_b, rec_b, tier, shared) -> tuple[set[str] | None, dict]:
    """Which task ids the comparison may use, or None for "all, the digests matched"."""
    da, db = meta_a.get("task_set_digest"), meta_b.get("task_set_digest")
    if da == db and not tier:
        return None, {}
    ta, tb = meta_a.get("task_digests"), meta_b.get("task_digests")
    if da != db and not (tier or shared):
        raise CompareError(
            f"task_set_digest differs ({da} vs {db}): the two runs answered different "
            "questions, and their scores do not compare. --shared compares the tasks both "
            "asked in the same wording, --tier one tier"
        )
    if ta is None or tb is None:
        if da == db:
            ids = {r["task_id"] for r in rec_a if r.get("tier") == tier}
            return ids, {}
        raise CompareError(
            "a run was recorded before per-task digests existed, so which of its tasks were "
            "asked in the same wording cannot be told; regrade a copy of it first "
            "(`report <run> --regrade --out <copy>`)"
        )

    def in_tier(recs):
        return {r["task_id"] for r in recs if not tier or r.get("tier") == tier}

    ia, ib = in_tier(rec_a), in_tier(rec_b)
    same = {t for t in ia & ib if ta.get(t) and ta.get(t) == tb.get(t)}
    left_out = {
        "reworded": sorted(t for t in ia & ib if t not in same),
        "only_a": sorted(ia - ib),
        "only_b": sorted(ib - ia),
    }
    if not shared and any(left_out.values()):
        raise CompareError(
            f"within {'tier ' + tier if tier else 'the task set'} the runs did not ask the same "
            f"questions ({', '.join(f'{k}: {len(v)}' for k, v in left_out.items() if v)}); "
            "--shared compares only the ones they did"
        )
    return same, {k: v for k, v in left_out.items() if v}


def _per_task_metric(records: list[dict], metric: str) -> dict[str, float]:
    """Mean of one process metric over each task's completed repetitions."""
    acc: dict[str, list[float]] = {}
    for r in records:
        if outcome_of(r) is None:
            continue
        if metric == "rank":
            v = (r.get("detail") or {}).get("rank")
            if v is None:
                continue
        elif metric == "tokens":
            m = r.get("metrics") or {}
            v = m.get("tokens_prompt", 0) + m.get("tokens_completion", 0)
        else:
            v = (r.get("metrics") or {}).get(metric)
            if v is None:
                continue
        acc.setdefault(r["task_id"], []).append(float(v))
    return {t: sum(v) / len(v) for t, v in acc.items()}


_PROCESS = (
    ("tokens", "Tokens per run"),
    ("tool_calls", "Tool calls per run"),
    ("n_iterations", "LLM turns per run"),
    ("wall_s", "Wall clock per run (s)"),
    ("rank", "n1 rank of the accepted id"),
)


def paired_process(meta_a, rec_a, meta_b, rec_b, ids) -> list[dict]:
    """The process metrics, paired task by task over `ids`, with an exact sign test."""
    out = []
    for metric, label in _PROCESS:
        if metric == "wall_s" and (meta_a.get("jobs", 1) > 1 or meta_b.get("jobs", 1) > 1):
            out.append({"metric": label, "withheld": "wall clock under jobs>1 measures queueing"})
            continue
        if metric == "tokens":
            inexact = [
                n
                for n, recs in (("A", rec_a), ("B", rec_b))
                if not all((r.get("metrics") or {}).get("tokens_exact", True) for r in recs)
            ]
            if inexact:
                out.append(
                    {"metric": label, "withheld": f"token count not exact in {', '.join(inexact)}"}
                )
                continue
        va, vb = _per_task_metric(rec_a, metric), _per_task_metric(rec_b, metric)
        shared = sorted(t for t in va.keys() & vb.keys() if ids is None or t in ids)
        if not shared:
            continue
        diffs = [vb[t] - va[t] for t in shared]
        b_lower = sum(1 for d in diffs if d < 0)
        a_lower = sum(1 for d in diffs if d > 0)
        out.append(
            {
                "metric": label,
                "n": len(shared),
                "median_a": _median([va[t] for t in shared]),
                "median_b": _median([vb[t] for t in shared]),
                "median_diff": _median(diffs),
                "a_lower": a_lower,
                "b_lower": b_lower,
                "p_value": sign_test(a_lower, b_lower),
            }
        )
    return out


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def compare(
    a: tuple[dict, list[dict]],
    b: tuple[dict, list[dict]],
    *,
    tier: str | None = None,
    shared: bool = False,
) -> dict:
    """Paired McNemar under both collapsings, and the tasks that moved between the arms.

    Raises:
        CompareError: when the two runs answered different questions and no scope that
            they share was asked for.
    """
    meta_a, rec_a = a
    meta_b, rec_b = b
    ids, left_out = _scope(meta_a, rec_a, meta_b, rec_b, tier, shared)
    if ids is not None:
        rec_a = [r for r in rec_a if r["task_id"] in ids]
        rec_b = [r for r in rec_b if r["task_id"] in ids]
    da = meta_a.get("task_set_digest")
    out = {
        "task_set_digest": da if da == meta_b.get("task_set_digest") else None,
        "scope": {"tier": tier, "shared": shared, "n_tasks": len(ids) if ids is not None else None},
        "left_out": left_out,
        "differences": differences(meta_a, meta_b),
        "process": paired_process(meta_a, rec_a, meta_b, rec_b, ids),
        "collapsings": {},
        # Recorded before `outcome` existed: stored errors read as failures until re-graded.
        "legacy": [
            name
            for name, recs in (("A", rec_a), ("B", rec_b))
            if any("outcome" not in r for r in recs)
        ],
    }
    for how in ("strict", "majority"):
        va, vb = collapse(rec_a, how), collapse(rec_b, how)
        shared = sorted(set(va) & set(vb))
        out["collapsings"][how] = {
            **mcnemar({t: va[t] for t in shared}, {t: vb[t] for t in shared}),
            "a_passed": sum(va[t] for t in shared),
            "b_passed": sum(vb[t] for t in shared),
            "moved_to_a": [t for t in shared if va[t] and not vb[t]],
            "moved_to_b": [t for t in shared if vb[t] and not va[t]],
        }
    return out


def _short(v, n: int = 60) -> str:
    text = v if isinstance(v, str) else json.dumps(v, sort_keys=True)
    return text if len(text) <= n else text[: n - 1] + "…"


def _arm_label(meta: dict) -> str:
    agent = meta.get("agent", {})
    ref = agent.get("agent_ref")
    bits = [agent.get("agent", "?"), agent.get("agent_version", "")]
    if ref:
        bits.append(f"@{ref[:7]}")
    bits.append(f"{agent.get('provider', '?')}/{agent.get('model', '?')}")
    return " ".join(str(b) for b in bits if b)


def render(result: dict, meta_a: dict, meta_b: dict, name_a: str, name_b: str) -> str:
    """Markdown for a comparison, in the shape the campaign summaries already use."""
    lines = [
        "# HelioBench — paired comparison",
        "",
        "| | A | B |",
        "|---|---|---|",
        f"| Run | `{name_a}` | `{name_b}` |",
        f"| Arm | {_arm_label(meta_a)} | {_arm_label(meta_b)} |",
        f"| Repetitions | {meta_a.get('runs')} | {meta_b.get('runs')} |",
    ]
    if result["task_set_digest"]:
        lines.append(f"| Task set digest | `{result['task_set_digest']}` | same |")
    else:
        lines.append(
            f"| Task set digest | `{meta_a.get('task_set_digest')}` | "
            f"`{meta_b.get('task_set_digest')}` |"
        )
    scope = result.get("scope") or {}
    if scope.get("tier") or scope.get("shared"):
        what = [f"tier {scope['tier']}"] if scope.get("tier") else []
        if scope.get("shared"):
            what.append("tasks asked in the same wording in both")
        lines.append(f"| Compared on | {', '.join(what)} ({scope.get('n_tasks')} tasks) | |")
    lines.append("")
    for k, v in (result.get("left_out") or {}).items():
        label = {
            "reworded": "asked in a different wording",
            "only_a": "only in A",
            "only_b": "only in B",
        }[k]
        lines.append(f"Left out, {label}: {', '.join(f'`{t}`' for t in v)}")
    if result.get("left_out"):
        lines.append("")
    if result.get("differences"):
        lines += [
            "## What differs between the arms",
            "",
            "Everything recorded about the two arms that is not the same. A difference in",
            "scores is only attributable to one of these if it is the only one.",
            "",
            "| | A | B |",
            "|---|---|---|",
        ]
        for k, va, vb in result["differences"]:
            lines.append(f"| {k} | `{_short(va)}` | `{_short(vb)}` |")
        lines.append("")
    lines += [
        "| Collapsing | A | B | A-only wins | B-only wins | shared | p |",
        "|---|---|---|---|---|---|---|",
    ]
    for how, c in result["collapsings"].items():
        label = "`pass^k` (strict)" if how == "strict" else "majority"
        lines.append(
            f"| {label} | {c['a_passed']}/{c['n_shared']} | {c['b_passed']}/{c['n_shared']} | "
            f"{c['only_a']} | {c['only_b']} | {c['n_shared']} | **{c['p_value']}** |"
        )
    lines += [
        "",
        "Exact two-sided McNemar over the discordant pairs. Paired, because both arms answered",
        "the same tasks: two overlapping confidence intervals are not evidence of no difference",
        "when the questions were the same. Errored repetitions are dropped before collapsing,",
        "and a task with none left in either arm is not in `shared`.",
        "",
    ]
    process = result.get("process") or []
    if process:
        lines += [
            "## Process, paired by task",
            "",
            "| Metric | tasks | median A | median B | median B−A | A lower | B lower | p |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for m in process:
            if "withheld" in m:
                lines.append(f"| {m['metric']} | — {m['withheld']} | | | | | | |")
                continue
            lines.append(
                f"| {m['metric']} | {m['n']} | {m['median_a']:.4g} | {m['median_b']:.4g} | "
                f"{m['median_diff']:+.4g} | {m['a_lower']} | {m['b_lower']} | {m['p_value']} |"
            )
        lines += [
            "",
            "Each task's mean over its completed repetitions, paired across the arms; p is an",
            "exact two-sided sign test over the tasks where the two differ.",
            "",
        ]
    if result.get("legacy"):
        lines += [
            f"⚠️ Run {' and '.join(result['legacy'])} was recorded before `outcome` existed:",
            "any errored repetition in it counts as failed here. Re-grade a copy with",
            "`heliobench report <copy> --regrade` first for an honest count.",
            "",
        ]
    for how, c in result["collapsings"].items():
        if c["moved_to_a"] or c["moved_to_b"]:
            lines.append(f"## Tasks that moved ({how})")
            lines.append("")
            for t in c["moved_to_a"]:
                lines.append(f"- `{t}` — A passed, B did not")
            for t in c["moved_to_b"]:
                lines.append(f"- `{t}` — B passed, A did not")
            lines.append("")
    return "\n".join(lines) + "\n"
