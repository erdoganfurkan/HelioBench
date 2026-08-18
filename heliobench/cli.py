"""Command-line entry point.

Deliberately argparse and not a CLI framework: the whole repository exists to make a number
reproducible, and every dependency is one more thing that can differ between the machine that
publishes the number and the machine that checks it.
"""

from __future__ import annotations

import argparse
import sys

from heliobench import __version__


def _cmd_list(args: argparse.Namespace) -> int:
    from heliobench.tasks import load_tasks

    tasks = load_tasks(args.tasks_dir, tiers=args.tier)
    if not tasks:
        print(f"no tasks found under {args.tasks_dir}")
        return 0
    for t in tasks:
        print(f"{t.id:<28} {t.tier:<4} {t.prompt[:70]}")
    print(f"\n{len(tasks)} task(s)")
    return 0


def _not_yet(name: str):
    def run(args: argparse.Namespace) -> int:
        print(f"heliobench {name}: not implemented yet", file=sys.stderr)
        return 2

    return run


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

    ls = sub.add_parser("list", parents=[common], help="list the tasks that would run")
    ls.set_defaults(func=_cmd_list)

    run = sub.add_parser("run", parents=[common], help="run an agent over the task set")
    run.add_argument("--agent", default="helioai", help="adapter name")
    run.add_argument("--runs", type=int, default=3, help="repetitions per task (pass^k)")
    run.add_argument("--out", default="results", help="where to write traces and the report")
    run.set_defaults(func=_not_yet("run"))

    rep = sub.add_parser("report", help="rebuild a report from stored traces")
    rep.add_argument("run_dir", help="directory of a previous run")
    rep.set_defaults(func=_not_yet("report"))

    ver = sub.add_parser("verify", help="check the environment before spending money on a run")
    ver.set_defaults(func=_not_yet("verify"))

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
