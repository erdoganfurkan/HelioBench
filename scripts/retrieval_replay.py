"""Replay a recorded run's search queries through HelioAI's search, with no model in the loop.

HelioBench's `recall@1` is the rank of the first accepted identifier inside what
`search_parameters` returned *for the query the agent wrote* (`graders/retrieval.py`). Moving
that number by one more HelioBench run costs ~1.2 M prompt tokens and 25 minutes, and it
confounds two experiments: what the runtime did and what the index returned. This script
keeps the agent out of it. It reads the `search_parameters` calls out of a run's stored
traces, replays them through the HelioAI checkout named on the command line, against the
index named on the command line, and ranks the accepted ids exactly as the grader does. Zero
tokens; a few seconds per process once the embedding model is loaded.

Run in several processes and it also measures what a single run cannot: HNSW is approximate,
so two processes may not rank the same query the same way. The spread of a task's rank across
processes is the noise floor under any recall@1 delta — a change that moves recall@1 by less
than that spread has not been shown to move anything.

    .venv/bin/python scripts/retrieval_replay.py \\
        --helioai-root ../HelioAI.worktrees/runtime-experiments \\
        --index ../HelioAI/data/chroma \\
        --run results/pr15_fix-dataset-alias/20260913T151025Z_helioai \\
        --processes 5 --out /tmp/replay.json

Two things this does not reproduce, on purpose. The adapter keeps the first 4000 characters
of a tool result, so a recorded rank can be missing where the replay finds one; the replay
sees the whole result. And the index is whatever sits at `--index` today, not the one the
run saw — the manifest records its size so the two can be told apart.

Read-only on the index, the traces and the tasks. `HELIOAI_DATA_DIR` is pinned to a temporary
directory so nothing HelioAI writes lands in real data. The interpreter must carry HelioAI's
dependencies (a working torch for the dense channel: with an incompatible one the search
silently falls back to an inventory scan and every rank comes back empty, which the manifest
line `index_count` and a `never returned` column at 100 % make visible). Like
`n1_key_candidates.py`, no test ships with it: it needs the 348 MB index this repository does
not vendor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from heliobench.graders.retrieval import extract_ids  # noqa: E402

SEARCH_TOOL = "search_parameters"


def load_accepted(tasks_dir: Path) -> dict[str, set[str]]:
    """Accepted identifiers per n1 task, read from the YAML keys the grader reads."""
    import yaml

    accepted: dict[str, set[str]] = {}
    for path in sorted(tasks_dir.glob("*.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        ids = {i.strip() for i in task.get("expected", {}).get("ids", []) if i.strip()}
        if ids:
            accepted[task["id"]] = ids
    return accepted


def load_calls(run_dir: Path, task_ids: set[str]) -> list[dict]:
    """The `search_parameters` calls of every recorded run of an n1 task, in call order.

    One entry per (task, run): the grader ranks against the concatenation of everything the
    searches returned, so the calls of one run stay together.
    """
    items: list[dict] = []
    for path in sorted((run_dir / "traces").glob("*.json")):
        task_id, _, run = path.stem.rpartition(".")
        if task_id not in task_ids:
            continue
        trace = json.loads(path.read_text(encoding="utf-8"))
        calls = [
            e["data"].get("arguments") or {}
            for e in trace.get("events", [])
            if e.get("event") == "tool_call" and e.get("data", {}).get("name") == SEARCH_TOOL
        ]
        if calls:
            items.append({"task": task_id, "run": int(run), "calls": calls})
    return items


def worker(args: argparse.Namespace) -> None:
    """One process: bind HelioAI, replay every call, print the ranks as JSON on stdout."""
    root = Path(args.helioai_root).resolve()
    sys.path.insert(0, str(root))
    os.environ["HELIOAI_DATA_DIR"] = tempfile.mkdtemp(prefix="retrieval-replay-")
    os.environ.setdefault("HELIOAI_LOG_FORMAT", "json")
    import helioai

    if not Path(helioai.__file__).resolve().is_relative_to(root):
        sys.exit(f"helioai imported from {helioai.__file__}, not from {root}")
    from helioai.config import settings

    settings.rag.chroma_dir = Path(args.index).resolve()
    from helioai.tools.rag import _collection_only
    from helioai.tools.speasy_tools import _search_parameters_sync

    accepted = load_accepted(Path(args.tasks))
    items = load_calls(Path(args.run), set(accepted))
    out = []
    for item in items:
        seen: dict[str, None] = {}
        for call in item["calls"]:
            result = _search_parameters_sync(
                query=call.get("query"),
                top_k=call.get("top_k") or 5,
                provider=call.get("provider"),
                queries=call.get("queries"),
                start=call.get("start"),
                stop=call.get("stop"),
            )
            for pid in extract_ids(json.dumps(result)):
                seen.setdefault(pid, None)
        retrieved = list(seen)
        rank = next(
            (i + 1 for i, pid in enumerate(retrieved) if pid in accepted[item["task"]]), None
        )
        out.append(
            {
                "task": item["task"],
                "run": item["run"],
                "rank": rank,
                "top1": retrieved[0] if retrieved else None,
                "retrieved": len(retrieved),
                "digest": hashlib.md5(" ".join(retrieved).encode()).hexdigest()[:8],
            }
        )
    print(
        json.dumps(
            {
                "helioai_file": helioai.__file__,
                "helioai_version": helioai.__version__,
                "index_count": int(_collection_only().count()),
                "items": out,
            }
        )
    )


def _git_head(path: Path) -> str:
    try:
        return subprocess.run(
            ["/usr/bin/git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "?"


def _metrics(ranks: list[int | None]) -> dict:
    n = len(ranks)
    hit = [r for r in ranks if r]
    return {
        "n": n,
        "recall@1": sum(1 for r in hit if r <= 1) / n,
        "recall@3": sum(1 for r in hit if r <= 3) / n,
        "recall@5": sum(1 for r in hit if r <= 5) / n,
        "mrr": sum(1 / r for r in hit) / n,
        "never": n - len(hit),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--helioai-root", required=True, help="HelioAI checkout whose search is measured"
    )
    p.add_argument("--index", required=True, help="Chroma directory (HelioAI's data/chroma)")
    p.add_argument("--run", required=True, help="HelioBench results directory holding traces/")
    p.add_argument("--tasks", default=str(ROOT / "tasks" / "n1_retrieval"))
    p.add_argument("--processes", type=int, default=5)
    p.add_argument("--out", help="Write the full manifest (per task, per process) as JSON")
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.worker:
        worker(args)
        return

    child_argv = [sys.executable, __file__, "--worker", *sys.argv[1:]]
    runs: list[dict] = []
    for i in range(args.processes):
        proc = subprocess.run(child_argv, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"process {i + 1} failed:\n{proc.stderr[-3000:]}")
        runs.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        m = _metrics([it["rank"] for it in runs[-1]["items"]])
        print(
            f"process {i + 1}: recall@1 {m['recall@1']:.1%}  recall@3 {m['recall@3']:.1%}  "
            f"recall@5 {m['recall@5']:.1%}  MRR {m['mrr']:.3f}  never {m['never']}/{m['n']}",
            file=sys.stderr,
        )

    keys = [(it["task"], it["run"]) for it in runs[0]["items"]]
    by_key = {
        k: [next(it for it in r["items"] if (it["task"], it["run"]) == k) for r in runs]
        for k in keys
    }
    per_process = [_metrics([it["rank"] for it in r["items"]]) for r in runs]
    r1 = [m["recall@1"] for m in per_process]
    unstable_rank = [k for k, its in by_key.items() if len({it["rank"] for it in its}) > 1]
    unstable_top1 = [k for k, its in by_key.items() if len({it["top1"] for it in its}) > 1]
    sigmas = [
        statistics.pstdev([it["rank"] for it in its])
        for its in by_key.values()
        if all(it["rank"] for it in its) and len(its) > 1
    ]

    head = _git_head(Path(args.helioai_root))
    lines = [
        f"# Retrieval replay — HelioAI @ {head} · index {runs[0]['index_count']} products · "
        f"{args.processes} process(es) · {len(keys)} (task, run) · run `{Path(args.run).name}`",
        "",
        f"`helioai` from `{runs[0]['helioai_file']}` (v{runs[0]['helioai_version']})",
        "",
        "| process | recall@1 | recall@3 | recall@5 | MRR | never returned |",
        "|---|---|---|---|---|---|",
    ]
    for i, m in enumerate(per_process, 1):
        lines.append(
            f"| {i} | {m['recall@1']:.1%} | {m['recall@3']:.1%} | {m['recall@5']:.1%} | "
            f"{m['mrr']:.3f} | {m['never']} |"
        )
    lines += [
        "",
        f"**recall@1 across processes: {min(r1):.1%} – {max(r1):.1%}** "
        f"(mean {statistics.fmean(r1):.1%}, σ {statistics.pstdev(r1):.1%})",
        f"- tasks whose rank differs between processes: **{len(unstable_rank)}/{len(keys)}**",
        f"- tasks whose top-1 differs between processes: **{len(unstable_top1)}/{len(keys)}**",
        f"- mean σ of the accepted id's rank (tasks ranked in every process): "
        f"{statistics.fmean(sigmas) if sigmas else 0.0:.2f}",
        "",
        "| task | run | ranks per process | top-1 (process 1) |",
        "|---|---|---|---|",
    ]
    for k, its in by_key.items():
        ranks = " ".join("—" if it["rank"] is None else str(it["rank"]) for it in its)
        flag = " ⚠️" if k in unstable_rank else ""
        lines.append(f"| {k[0]} | {k[1]} | {ranks}{flag} | `{its[0]['top1']}` |")
    print("\n".join(lines))

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "helioai_root": str(Path(args.helioai_root).resolve()),
                    "helioai_head": head,
                    "helioai_file": runs[0]["helioai_file"],
                    "index": str(Path(args.index).resolve()),
                    "index_count": runs[0]["index_count"],
                    "run": str(Path(args.run).resolve()),
                    "processes": args.processes,
                    "per_process": per_process,
                    "unstable_rank": unstable_rank,
                    "unstable_top1": unstable_top1,
                    "items": {f"{k[0]}.{k[1]}": its for k, its in by_key.items()},
                },
                indent=1,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
