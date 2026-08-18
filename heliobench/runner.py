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
from heliobench.graders.process import collect
from heliobench.tasks import Task, load_tasks
from heliobench.trace import Trace


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


def run(
    agent,
    tasks: list[Task],
    out_dir: Path,
    *,
    runs: int = 3,
    fixtures: Path = Path("fixtures"),
    scratch: Path | None = None,
    on_event=None,
) -> dict:
    """Execute every task `runs` times, grade each, and write the run directory.

    A run that raises is recorded as a failed trace rather than aborting the sweep: losing
    forty finished tasks to the forty-first is how a benchmark becomes something nobody runs.
    """
    out_dir = Path(out_dir)
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    scratch = Path(scratch or out_dir / "scratch")
    records: list[dict] = []
    started = time.time()

    for task in tasks:
        for i in range(runs):
            workdir = scratch / f"{task.id}_{i}"
            try:
                trace = asyncio.run(run_once(agent, task, workdir, fixtures))
            except Exception as e:
                trace = Trace(
                    task_id=task.id,
                    prompt=task.prompt,
                    agent=getattr(agent, "name", "?"),
                    error=f"{type(e).__name__}: {e}",
                )
            result = grade(task, trace)
            metrics = collect(trace)
            trace.write(out_dir / "traces" / f"{task.id}.{i}.json")
            record = {
                "task_id": task.id,
                "tier": task.tier,
                "event": task.event,
                "run": i,
                "passed": result.passed,
                "reason": result.reason,
                "detail": result.detail,
                "metrics": metrics.as_dict(),
            }
            records.append(record)
            if on_event:
                on_event(record)

    meta = {
        "heliobench": __version__,
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "elapsed_s": round(time.time() - started, 1),
        "runs": runs,
        "n_tasks": len(tasks),
        "task_set_digest": task_set_digest(tasks),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "agent": agent.describe(),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return {"meta": meta, "records": records}


def load_task_set(tasks_dir: str | Path, tiers: list[str] | None) -> list[Task]:
    return load_tasks(tasks_dir, tiers=tiers)
