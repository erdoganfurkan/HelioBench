"""Two arms over the same questions, compared the paired way.

Every paired comparison in this project before this file was a scratch script run by hand and
transcribed into a summary — which is how a benchmark publishes a p-value nobody can recompute.
The command refuses two runs whose `task_set_digest` differs: different digests mean different
questions were asked, and there is no honest number to print for that.

Two collapsings of k repetitions into one verdict per task are reported, because they answer
different questions. Strict (`pass^k`) asks whether the arm is reliable; majority asks whether
it is usually right. An arm can win one and lose the other, and a reader should see both.
"""

from __future__ import annotations

import json
from pathlib import Path

from heliobench.report import outcome_of
from heliobench.stats import mcnemar


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


def compare(a: tuple[dict, list[dict]], b: tuple[dict, list[dict]]) -> dict:
    """Paired McNemar under both collapsings, and the tasks that moved between the arms.

    Raises:
        CompareError: when the two runs answered different questions.
    """
    meta_a, rec_a = a
    meta_b, rec_b = b
    da, db = meta_a.get("task_set_digest"), meta_b.get("task_set_digest")
    if da != db:
        raise CompareError(
            f"task_set_digest differs ({da} vs {db}): the two runs answered different "
            "questions, and their scores do not compare"
        )
    out = {
        "task_set_digest": da,
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
        f"| Task set digest | `{result['task_set_digest']}` | same |",
        "",
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
