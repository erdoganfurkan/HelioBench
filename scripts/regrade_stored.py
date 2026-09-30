"""Re-grade a copy of every stored run and print what moved, for a pull request.

A change to the graders, the statistics, the report or the tasks is only reviewable beside
the scores it moves, and until this script the comparison was assembled by hand: copy a run,
`report --regrade` the copy, read two tables, transcribe the difference. Doing it for the 28
stored runs by hand is how a PR ends up quoting three of them.

The originals are never written. Each run directory is copied under `--work` first, and the
script refuses a `--work` that sits inside one of the roots it reads: `--regrade` rewrites
`meta.json` and `results.json`, and the stored runs are frozen evidence.

    python scripts/regrade_stored.py ../HelioBench/results ../HelioBench/heliobench-results \\
        --work /tmp/hb_regrade --out /tmp/regrade.md

"Before" is what the stored `results.json` says; "after" is today's graders and task set.
Stored verdicts are often older than the last grader change, so a PR wants the other
comparison: `--json` on the base commit, then `--against` that file on the branch, and
"before" becomes the base commit's regrade instead of the stored verdicts.

    git stash; python scripts/regrade_stored.py <roots> --work /tmp/a --json /tmp/base.json
    git stash pop; python scripts/regrade_stored.py <roots> --work /tmp/b --against /tmp/base.json

Errored runs leave both denominators, exactly as the report counts them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from heliobench.report import outcome_of  # noqa: E402
from heliobench.runner import regrade  # noqa: E402
from heliobench.tasks import load_tasks  # noqa: E402


def find_runs(roots: list[Path]) -> list[tuple[Path, Path]]:
    """Every `(root, run_dir)` under `roots`: a directory holding `meta.json` and `traces/`."""
    out = []
    for root in roots:
        for meta in sorted(Path(root).rglob("meta.json")):
            if (meta.parent / "traces").is_dir():
                out.append((Path(root), meta.parent))
    return out


def tally(records: list[dict]) -> dict:
    """Per-tier `passed/scored` and errored counts, the way the report counts them."""
    t: dict = defaultdict(lambda: {"passed": 0, "scored": 0, "errored": 0})
    for r in records:
        o = outcome_of(r)
        for key in (r["tier"], "all"):
            if o is None:
                t[key]["errored"] += 1
            else:
                t[key]["scored"] += 1
                t[key]["passed"] += int(o)
    return dict(t)


def verdicts(records: list[dict]) -> dict[tuple[str, int], str]:
    """`(task_id, run)` → passed / failed / errored."""
    return {
        (r["task_id"], r["run"]): {True: "passed", False: "failed", None: "errored"}[outcome_of(r)]
        for r in records
    }


def compare_one(original: Path, copy: Path, tasks, before: list[dict] | None = None) -> dict:
    """Copy `original` to `copy`, regrade the copy, and diff it against `before`.

    `before` defaults to the original's stored records.
    """
    if before is None:
        before = json.loads((original / "results.json").read_text(encoding="utf-8"))
    meta_before = json.loads((original / "meta.json").read_text(encoding="utf-8"))
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(original, copy)
    out = regrade(copy, tasks)
    after, meta_after = out["records"], out["meta"]
    vb, va = verdicts(before), verdicts(after)
    flips = [
        {
            "task_id": k[0],
            "run": k[1],
            "before": vb.get(k, "absent"),
            "after": va.get(k, "absent"),
            "reason": next(
                (r["reason"] for r in after if (r["task_id"], r["run"]) == k),
                next((r["reason"] for r in before if (r["task_id"], r["run"]) == k), ""),
            ),
        }
        for k in sorted(set(vb) | set(va))
        if vb.get(k, "absent") != va.get(k, "absent")
    ]
    agent = meta_before.get("agent", {})
    return {
        "run": str(original),
        "arm": f"{agent.get('agent', '?')} {agent.get('agent_version', '')} "
        f"@{(agent.get('agent_ref') or '')[:7]} {agent.get('model', '')}".strip(),
        "digest_before": meta_before.get("task_set_digest"),
        "digest_after": meta_after.get("task_set_digest"),
        "before": tally(before),
        "after": tally(after),
        "flips": flips,
        "unscored": meta_after.get("unscored_traces", []),
        "records_after": [
            {k: r.get(k) for k in ("task_id", "tier", "run", "passed", "outcome", "reason")}
            for r in after
        ],
    }


def _cell(t: dict, tier: str) -> str:
    c = t.get(tier)
    if not c:
        return "—"
    err = f" (+{c['errored']}e)" if c["errored"] else ""
    return f"{c['passed']}/{c['scored']}{err}"


def render(rows: list[dict]) -> str:
    """The before/after table a pull request pastes."""
    lines = [
        "| Run | Arm | Digest | n1 | n2 | n3 | all | Flips |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        digest = r["digest_before"]
        if r["digest_after"] != digest:
            digest = f"{digest} → {r['digest_after']}"
        cells = []
        for tier in ("n1", "n2", "n3", "all"):
            b, a = _cell(r["before"], tier), _cell(r["after"], tier)
            cells.append(b if a == b else f"{b} → **{a}**")
        name = Path(r["run"]).name
        lines.append(
            f"| `{name}` | {r['arm']} | `{digest}` | {' | '.join(cells)} | {len(r['flips'])} |"
        )
    moved = [r for r in rows if r["flips"] or r["unscored"]]
    for r in moved:
        lines += ["", f"### `{Path(r['run']).name}`", ""]
        for f in r["flips"]:
            lines.append(
                f"- `{f['task_id']}` run {f['run']}: {f['before']} → **{f['after']}**"
                + (f" — {f['reason'][:120]}" if f["reason"] else "")
            )
        for u in r["unscored"]:
            lines.append(f"- unscored: `{u['task_id']}` run {u['run']} — {u['reason']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("roots", nargs="+", help="directories holding stored run directories")
    p.add_argument("--work", required=True, help="where the copies are regraded")
    p.add_argument("--tasks-dir", default=str(REPO / "tasks"))
    p.add_argument("--out", default=None, help="write the markdown here as well as stdout")
    p.add_argument("--json", default=None, help="write the raw comparison as JSON")
    p.add_argument(
        "--against",
        default=None,
        help="a previous --json: compare with its regrade rather than with the stored verdicts",
    )
    args = p.parse_args(argv)

    work = Path(args.work).resolve()
    roots = [Path(r).resolve() for r in args.roots]
    for root in roots:
        if work == root or root in work.parents:
            raise SystemExit(f"--work {work} is inside {root}: stored runs are never regraded")
    tasks = load_tasks(args.tasks_dir)
    base = {}
    if args.against:
        base = {
            r["run"]: r["records_after"]
            for r in json.loads(Path(args.against).read_text(encoding="utf-8"))
        }
    rows = []
    for i, (root, run_dir) in enumerate(find_runs(roots)):
        rel = run_dir.relative_to(root)
        copy = work / f"{i:02d}_{root.name}" / rel
        rows.append(compare_one(run_dir, copy, tasks, base.get(str(run_dir))))
    md = render(rows)
    print(md, end="")
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
