"""Run an agent over the task set and record everything.

Each run gets its own storage root, so one task cannot leave a cached download or a session
row where the next one will find it. That isolation is what makes the k repetitions
independent, which is the only thing that makes `pass^k` mean anything.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path

from heliobench import __version__
from heliobench.graders import grade
from heliobench.graders.outcome import classify
from heliobench.graders.process import collect
from heliobench.tasks import Task, load_tasks
from heliobench.trace import Trace


def make_record(task: Task, trace: Trace, run: int) -> dict:
    """Grade one trace and shape the row that `results.json` stores.

    `passed` stays a boolean for every reader written against it; `outcome` is the
    three-way verdict beside it. An errored run is `passed: false` *and* `outcome: errored`,
    so a tool that only knows the boolean still never counts it as a success.
    """
    result = grade(task, trace)
    return {
        "task_id": task.id,
        "tier": task.tier,
        "event": task.event,
        "run": run,
        "passed": result.passed,
        "outcome": classify(trace, result.passed),
        "reason": result.reason,
        "detail": result.detail,
        "metrics": collect(trace).as_dict(),
    }


def task_set_digest(tasks: list[Task]) -> str:
    """A fingerprint of exactly which questions were asked, in which wording.

    Two scores are only comparable if this matches. Editing one prompt changes it, which is
    the point: a benchmark whose questions drift silently compares nothing.
    """
    h = hashlib.sha256()
    for t in sorted(tasks, key=lambda t: t.id):
        h.update(
            json.dumps(
                {"id": t.id, "prompt": t.prompt, "expected": t.expected, "tolerance": t.tolerance},
                sort_keys=True,
            ).encode()
        )
    return h.hexdigest()[:16]


def new_run_dir(root: Path, agent_name: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    d = Path(root) / f"{stamp}_{agent_name}"
    (d / "traces").mkdir(parents=True, exist_ok=True)
    return d


async def run_once(agent, task: Task, workdir: Path, fixtures: Path) -> Trace:
    kwargs = {}
    if task.fixture:
        fixture = Path(fixtures) / task.fixture
        if not fixture.is_dir():
            raise FileNotFoundError(f"{task.id} needs fixture {task.fixture!r} at {fixture}")
        kwargs["fixture"] = fixture
    return await agent.run(task.prompt, workdir, task_id=task.id, **kwargs)


async def _one(agent, task: Task, i: int, scratch: Path, fixtures: Path, out_dir: Path) -> dict:
    """One repetition, end to end: run, catch, write the trace, grade."""
    workdir = scratch / f"{task.id}_{i}"
    try:
        trace = await run_once(agent, task, workdir, fixtures)
    except Exception as e:
        trace = Trace(
            task_id=task.id,
            prompt=task.prompt,
            agent=getattr(agent, "name", "?"),
            error=f"{type(e).__name__}: {e}",
        )
    trace.write(out_dir / "traces" / f"{task.id}.{i}.json")
    return make_record(task, trace, i)


async def _sweep(agent, tasks, runs, scratch, fixtures, out_dir, jobs, on_event) -> list[dict]:
    """Every repetition of every task, at most `jobs` in flight, in a deterministic order.

    The order of *completion* depends on the machine; the order of *records* must not. Rows
    are sorted by `(task_id, run)` before they are returned, so two sweeps with different
    `jobs` write the same `results.json` apart from the timing fields.
    """
    gate = asyncio.Semaphore(jobs)

    async def guarded(task, i):
        async with gate:
            record = await _one(agent, task, i, scratch, fixtures, out_dir)
        if on_event:
            on_event(record)
        return record

    records = await asyncio.gather(*(guarded(t, i) for t in tasks for i in range(runs)))
    return sorted(records, key=lambda r: (r["task_id"], r["run"]))


def run(
    agent,
    tasks: list[Task],
    out_dir: Path,
    *,
    runs: int = 3,
    fixtures: Path = Path("fixtures"),
    scratch: Path | None = None,
    on_event=None,
    jobs: int = 1,
) -> dict:
    """Execute every task `runs` times, grade each, and write the run directory.

    A run that raises is recorded as a failed trace rather than aborting the sweep: losing
    forty finished tasks to the forty-first is how a benchmark becomes something nobody runs.

    `jobs` bounds how many repetitions are in flight at once. It defaults to one because
    concurrency destroys the per-run wall clock as a diagnostic and multiplies every transport
    failure — which is why failure accounting shipped before this did.
    """
    if jobs < 1:
        raise ValueError(f"jobs must be at least 1, got {jobs}")
    out_dir = Path(out_dir)
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    scratch = Path(scratch or out_dir / "scratch")
    started = time.time()

    records = asyncio.run(_sweep(agent, tasks, runs, scratch, fixtures, out_dir, jobs, on_event))

    meta = {
        "heliobench": __version__,
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "elapsed_s": round(time.time() - started, 1),
        "runs": runs,
        "jobs": jobs,
        "n_tasks": len(tasks),
        "task_set_digest": task_set_digest(tasks),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "agent": agent.describe(),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return {"meta": meta, "records": records}


def regrade(run_dir: Path, tasks: list[Task]) -> dict:
    """Re-derive every record in a run directory from its stored traces.

    A grader reads a trace and nothing else, so a finished run can be scored again after a
    key was widened, a tolerance tightened or a gate added — no provider, no money, no agent.
    That this is code rather than a hand tally is the point: the correction of 2026-08-21
    began as a manual count across two run directories, and a number counted by hand is a
    number nobody can reproduce.

    Traces for tasks no longer in the set are skipped, and the rebuilt meta says how many
    were kept: a re-grade against a different task set is a different measurement, and the
    digest it writes is what says so.
    """
    run_dir = Path(run_dir)
    by_id = {t.id: t for t in tasks}
    records: list[dict] = []
    skipped: list[str] = []

    for path in sorted((run_dir / "traces").glob("*.json")):
        trace = Trace.read(path)
        task = by_id.get(trace.task_id)
        if task is None:
            skipped.append(trace.task_id)
            continue
        records.append(make_record(task, trace, int(path.stem.rsplit(".", 1)[-1])))

    seen = {r["task_id"] for r in records}
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    first = Trace.read(sorted((run_dir / "traces").glob("*.json"))[0]) if records else None
    meta.update(
        {
            "heliobench": __version__,
            "regraded": datetime.now(UTC).isoformat(timespec="seconds"),
            "runs": max((r["run"] for r in records), default=0) + 1,
            "n_tasks": len(seen),
            "task_set_digest": task_set_digest([by_id[t] for t in sorted(seen)]),
            "skipped_traces": sorted(set(skipped)),
        }
    )
    meta.setdefault("agent", first.env if first else {})
    meta.setdefault("generated", meta["regraded"])
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (run_dir / "results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return {"meta": meta, "records": records}


def load_task_set(tasks_dir: str | Path, tiers: list[str] | None) -> list[Task]:
    return load_tasks(tasks_dir, tiers=tiers)
