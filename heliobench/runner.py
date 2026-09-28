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


def _task_bytes(t: Task) -> bytes:
    return json.dumps(
        {"id": t.id, "prompt": t.prompt, "expected": t.expected, "tolerance": t.tolerance},
        sort_keys=True,
    ).encode()


def task_set_digest(tasks: list[Task]) -> str:
    """A fingerprint of exactly which questions were asked, in which wording.

    Two scores are only comparable if this matches. Editing one prompt changes it, which is
    the point: a benchmark whose questions drift silently compares nothing.
    """
    h = hashlib.sha256()
    for t in sorted(tasks, key=lambda t: t.id):
        h.update(_task_bytes(t))
    return h.hexdigest()[:16]


def task_digests(tasks: list[Task]) -> dict[str, str]:
    """The same fingerprint, one per task.

    The set digest says whether two runs asked the same questions; these say which ones
    they share. That is what lets two runs be compared on a tier, or on the tasks they have
    in common, without the comparison trusting that a task id still means the same question.
    """
    return {t.id: hashlib.sha256(_task_bytes(t)).hexdigest()[:16] for t in tasks}


def fixture_digests(tasks: list[Task], fixtures: Path) -> dict[str, str]:
    """A fingerprint of the frozen data each fixture the tasks use served to the agent.

    Not part of `task_set_digest`: re-freezing a fixture that yields the same keys must not
    orphan every stored run. It is recorded so that a fixture that did change is visible.
    """
    out: dict[str, str] = {}
    for name in sorted({t.fixture for t in tasks if t.fixture}):
        root = Path(fixtures) / name
        h = hashlib.sha256()
        for f in sorted(p for p in root.rglob("*") if p.is_file()):
            h.update(str(f.relative_to(root)).encode())
            h.update(f.read_bytes())
        out[name] = h.hexdigest()[:16] if root.is_dir() else "missing"
    return out


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


async def _sweep(
    agent, tasks, runs, scratch, fixtures, out_dir, jobs, on_event, done=None, sink=None
) -> list[dict]:
    """Every repetition of every task, at most `jobs` in flight, in a deterministic order.

    The order of *completion* depends on the machine; the order of *records* must not. Rows
    are sorted by `(task_id, run)` before they are returned, so two sweeps with different
    `jobs` write the same `results.json` apart from the timing fields.

    `done` maps `(task_id, run)` to a record already on disk, which is returned instead of
    running again; `sink` receives each new record the moment it lands.
    """
    gate = asyncio.Semaphore(jobs)
    done = done or {}

    async def guarded(task, i):
        async with gate:
            record = await _one(agent, task, i, scratch, fixtures, out_dir)
        if sink is not None:
            sink(record)
        if on_event:
            on_event(record)
        return record

    pending = [(t, i) for t in tasks for i in range(runs) if (t.id, i) not in done]
    records = list(done.values())
    records += await asyncio.gather(*(guarded(t, i) for t, i in pending))
    return sorted(records, key=lambda r: (r["task_id"], r["run"]))


def _finished(out_dir: Path, tasks: list[Task], runs: int) -> dict[tuple[str, int], dict]:
    """Records rebuilt from the traces a previous, interrupted sweep already wrote.

    Regraded from the trace rather than read from `results.partial.jsonl`, so a resumed run
    is graded by one version of the graders throughout. A trace whose prompt is not the
    task's prompt today is not reused: it answered another question.
    """
    by_id = {t.id: t for t in tasks}
    out: dict[tuple[str, int], dict] = {}
    for path in sorted((out_dir / "traces").glob("*.json")):
        tid, _, i = path.stem.rpartition(".")
        task = by_id.get(tid)
        if task is None or not i.isdigit() or int(i) >= runs:
            continue
        trace = Trace.read(path)
        if trace.prompt == task.prompt:
            out[(tid, int(i))] = make_record(task, trace, int(i))
    return out


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
    resume: bool = False,
) -> dict:
    """Execute every task `runs` times, grade each, and write the run directory.

    A run that raises is recorded as a failed trace rather than aborting the sweep: losing
    forty finished tasks to the forty-first is how a benchmark becomes something nobody runs.

    `jobs` bounds how many repetitions are in flight at once. It defaults to one because
    concurrency destroys the per-run wall clock as a diagnostic and multiplies every transport
    failure — which is why failure accounting shipped before this did.

    `meta.json` is written before the first run, with `status: running`, and every record is
    appended to `results.partial.jsonl` as it lands; a sweep that is interrupted still leaves
    a run directory `report --regrade` can read, and `status: interrupted` says so. With
    `resume`, the repetitions whose trace is already in `out_dir` are regraded rather than
    run again. The 2026-08-21 sweep died at run 69 of 90 with the quota spent; recovering it
    took a day of hand-tallying.
    """
    if jobs < 1:
        raise ValueError(f"jobs must be at least 1, got {jobs}")
    out_dir = Path(out_dir)
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    scratch = Path(scratch or out_dir / "scratch")
    started = time.time()

    done = _finished(out_dir, tasks, runs) if resume else {}
    meta = {
        "heliobench": __version__,
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "running",
        "runs": runs,
        "jobs": jobs,
        "n_tasks": len(tasks),
        "task_set_digest": task_set_digest(tasks),
        "task_digests": task_digests(tasks),
        "fixture_digests": fixture_digests(tasks, fixtures),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "agent": agent.describe(),
    }
    if resume:
        meta["resumed"] = len(done)
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    partial = out_dir / "results.partial.jsonl"
    landed: list[dict] = list(done.values())

    def sink(record: dict) -> None:
        landed.append(record)
        with partial.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def finish(records: list[dict], status: str) -> None:
        meta["status"] = status
        meta["elapsed_s"] = round(time.time() - started, 1)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        records = sorted(records, key=lambda r: (r["task_id"], r["run"]))
        (out_dir / "results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    try:
        records = asyncio.run(
            _sweep(agent, tasks, runs, scratch, fixtures, out_dir, jobs, on_event, done, sink)
        )
    except BaseException:
        finish(landed, "interrupted")
        raise
    finish(records, "complete")
    partial.unlink(missing_ok=True)
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

    A trace whose prompt is not the task's prompt today is left unscored, and listed in
    `unscored_traces`. The agent answered a different question, so grading its reply against
    today's key repeats the mistake a hardened prompt was meant to fix, in the other
    direction — and until 2026-09-28 it did exactly that, then stamped the run with today's
    digest so that `compare` would have accepted it. Widening a key keeps the prompt and
    carries a trace over; rewording it does not.
    """
    run_dir = Path(run_dir)
    by_id = {t.id: t for t in tasks}
    records: list[dict] = []
    skipped: list[str] = []
    unscored: list[dict] = []

    for path in sorted((run_dir / "traces").glob("*.json")):
        trace = Trace.read(path)
        task = by_id.get(trace.task_id)
        if task is None:
            skipped.append(trace.task_id)
            continue
        i = int(path.stem.rsplit(".", 1)[-1])
        if trace.prompt != task.prompt:
            unscored.append(
                {"task_id": task.id, "run": i, "reason": "the prompt changed since this run"}
            )
            continue
        records.append(make_record(task, trace, i))

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
            "task_digests": task_digests([by_id[t] for t in sorted(seen)]),
            "skipped_traces": sorted(set(skipped)),
            "unscored_traces": unscored,
        }
    )
    meta.setdefault("agent", first.env if first else {})
    meta.setdefault("generated", meta["regraded"])
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (run_dir / "results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return {"meta": meta, "records": records}


def load_task_set(tasks_dir: str | Path, tiers: list[str] | None) -> list[Task]:
    return load_tasks(tasks_dir, tiers=tiers)
