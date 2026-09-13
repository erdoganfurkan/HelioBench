"""Command-line entry point.

Deliberately argparse and not a CLI framework: the whole repository exists to make a number
reproducible, and every dependency is one more thing that can differ between the machine that
publishes the number and the machine that checks it.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from heliobench import __version__


def _build_agent(args):
    if args.agent == "null":
        from heliobench.adapters.null import NullAgent

        return NullAgent()
    if args.agent == "helioai":
        from heliobench.adapters.helioai import HelioAIAgent

        return HelioAIAgent(
            Path(args.data_dir or tempfile.mkdtemp(prefix="heliobench-")),
            provider=args.provider,
            model=args.model,
            index_dir=Path(args.index_dir) if args.index_dir else None,
            jobs=getattr(args, "jobs", 1),
        )
    raise SystemExit(f"unknown agent {args.agent!r}")


def _select(args):
    from heliobench.tasks import load_tasks

    tasks = load_tasks(args.tasks_dir, tiers=args.tier)
    if getattr(args, "task", None):
        wanted = set(args.task)
        tasks = [t for t in tasks if t.id in wanted]
        missing = wanted - {t.id for t in tasks}
        if missing:
            raise SystemExit(f"no such task(s): {sorted(missing)}")
    return tasks


def _cmd_list(args) -> int:
    tasks = _select(args)
    if not tasks:
        print(f"no tasks found under {args.tasks_dir}")
        return 0
    for t in tasks:
        print(f"{t.id:<28} {t.tier:<4} {t.prompt[:70]}")
    print(f"\n{len(tasks)} task(s)")
    return 0


def _cmd_verify(args) -> int:
    """Check everything that would invalidate a run, before the run spends anything."""
    problems: list[str] = []
    try:
        tasks = _select(args)
        print(f"tasks         : {len(tasks)} loaded from {args.tasks_dir}")
    except Exception as e:
        print(f"tasks         : FAILED {e}")
        return 1

    needed = {t.fixture for t in tasks if t.fixture}
    for name in sorted(needed):
        manifest = Path(args.fixtures) / name / "data" / "manifest.json"
        ok = manifest.is_file()
        print(f"fixture       : {name} {'ok' if ok else 'MISSING ' + str(manifest)}")
        if not ok:
            problems.append(f"fixture {name} is missing; run scripts/build_fixture.py {name}")

    agent = _build_agent(args)
    print(f"agent         : {agent.name}")
    for p in agent.preflight():
        print(f"                ! {p}")
        problems.append(p)

    if problems:
        print(f"\n{len(problems)} problem(s) — a run now would produce numbers you cannot defend")
        return 1
    print("\nready")
    return 0


def _cmd_run(args) -> int:
    from heliobench import report as report_mod
    from heliobench.runner import new_run_dir, run

    tasks = _select(args)
    if not tasks:
        print("no tasks to run", file=sys.stderr)
        return 2
    agent = _build_agent(args)

    problems = agent.preflight()
    if problems and not args.force:
        for p in problems:
            print(f"! {p}", file=sys.stderr)
        print("refusing to run; pass --force to override", file=sys.stderr)
        return 1

    out_dir = new_run_dir(args.out, agent.name)
    total = len(tasks) * args.runs
    state = {"n": 0, "ok": 0, "err": 0}

    def progress(record):
        state["n"] += 1
        errored = record.get("outcome") == "errored"
        state["ok"] += bool(record["passed"])
        state["err"] += errored
        mark = "." if record["passed"] else ("e" if errored else "x")
        end = "\n" if state["n"] % 50 == 0 or state["n"] == total else ""
        print(f"{mark}{end}", end="", flush=True)

    print(f"{len(tasks)} tasks x {args.runs} runs -> {out_dir}")
    run(
        agent,
        tasks,
        out_dir,
        runs=args.runs,
        fixtures=Path(args.fixtures),
        on_event=progress,
        jobs=args.jobs,
    )
    errored = f", {state['err']} errored" if state["err"] else ""
    print(f"\n{state['ok']}/{total} runs passed{errored}")
    print(f"report: {report_mod.write(out_dir)}")
    return 0


def _cmd_report(args) -> int:
    from heliobench import report as report_mod
    from heliobench.runner import regrade

    run_dir = Path(args.run_dir)
    if args.regrade:
        out = regrade(run_dir, _select(args))
        print(f"re-graded {len(out['records'])} runs over {out['meta']['n_tasks']} tasks")
    path = report_mod.write(run_dir)
    print(path.read_text(encoding="utf-8"))
    return 0


def _cmd_compare(args) -> int:
    from heliobench.compare import CompareError, compare, load_run, render

    a, b = load_run(Path(args.run_a)), load_run(Path(args.run_b))
    try:
        result = compare(a, b)
    except CompareError as e:
        print(f"refusing to compare: {e}", file=sys.stderr)
        return 1
    print(render(result, a[0], b[0], Path(args.run_a).name, Path(args.run_b).name), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="heliobench", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=f"heliobench {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--tasks-dir", default="tasks", help="directory holding task YAML files")
    common.add_argument(
        "--tier",
        action="append",
        choices=["n1", "n2", "n3"],
        help="restrict to a tier; repeatable (default: all)",
    )
    common.add_argument(
        "--task",
        action="append",
        default=None,
        metavar="ID",
        help="restrict to these task ids; repeatable. Reproduces one failure without paying "
        "for the whole sweep.",
    )

    agent_opts = argparse.ArgumentParser(add_help=False)
    agent_opts.add_argument("--agent", default="null", choices=["null", "helioai"])
    agent_opts.add_argument(
        "--agent-ref",
        default=None,
        metavar="REF",
        help="check out HelioAI at this branch, tag or commit and run against it, in an "
        "isolated venv (requires --agent helioai)",
    )
    # Same default as the adapter's own: a run launched without a flag must land where the
    # adapter documents it does, or the report header and the CLI disagree about the arm.
    agent_opts.add_argument("--provider", default="azure", help="LLM provider for the agent")
    agent_opts.add_argument("--model", default=None, help="model id; default is the agent's")
    agent_opts.add_argument("--index-dir", default=None, help="search index the agent must use")
    agent_opts.add_argument("--data-dir", default=None, help="agent storage root for this run")
    agent_opts.add_argument("--fixtures", default="fixtures", help="frozen data for tier n3")
    agent_opts.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="repetitions in flight at once (default 1). Above 1, per-run wall clock measures "
        "queueing rather than the agent and is not reported; cost stays exact.",
    )

    ls = sub.add_parser("list", parents=[common], help="list the tasks that would run")
    ls.set_defaults(func=_cmd_list)

    ver = sub.add_parser(
        "verify",
        parents=[common, agent_opts],
        help="check the environment before spending money on a run",
    )
    ver.set_defaults(func=_cmd_verify)

    run_p = sub.add_parser(
        "run", parents=[common, agent_opts], help="run an agent over the task set"
    )
    run_p.add_argument("--runs", type=int, default=3, help="repetitions per task (pass^k)")
    run_p.add_argument("--out", default="results", help="where to write traces and the report")
    run_p.add_argument("--force", action="store_true", help="run despite preflight problems")
    run_p.set_defaults(func=_cmd_run)

    rep = sub.add_parser("report", parents=[common], help="rebuild a report from stored traces")
    rep.add_argument("run_dir", help="directory of a previous run")
    rep.add_argument(
        "--regrade",
        action="store_true",
        help="score the stored traces again with today's graders and task set, then report. "
        "Costs nothing: graders read traces, never the agent.",
    )
    rep.set_defaults(func=_cmd_report)

    cmp_p = sub.add_parser(
        "compare",
        help="paired McNemar between two runs of the same task set",
        description="Refuses when the two runs' task_set_digest differ: different questions "
        "were asked, and the scores do not compare.",
    )
    cmp_p.add_argument("run_a", help="directory of the first run")
    cmp_p.add_argument("run_b", help="directory of the second run")
    cmp_p.set_defaults(func=_cmd_compare)

    return p


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw)
    if getattr(args, "agent_ref", None):
        if args.agent != "helioai":
            raise SystemExit("--agent-ref requires --agent helioai")
        from heliobench.agentsnapshot import prepare

        prepare(args.agent_ref, raw)
        raise SystemExit(
            "agent snapshot preparation did not replace the process"
        )  # pragma: no cover
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
