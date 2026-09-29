"""Look for the benchmark's answers inside the agent under test.

A key an agent was shown is a key it can recite. ReplicationBench's warning is that this
happens by accident — an example in a skill file, a worked case in a recipe docstring, a
user profile written while debugging — and that a score cannot tell recall from retrieval.
This script reads the files that reach HelioAI's context (its skills, its system prompts, its
recipes, and optionally a profile) and reports, per task:

- n1: an accepted identifier written out literally;
- n3: the answer's value in a file that also names the event's date (a bare `57.5` is
  noise; beside `2015-03-17` it is the answer). The averaging windows are not searched for:
  every n3 prompt states them, and HelioAI's own `rankine_hugoniot` self-check asserts them.

    python scripts/contamination_check.py --helioai-root ../HelioAI [--profile PATH ...]

Exit status 1 when anything is found. An n1 hit is not proof of contamination — a skill may
legitimately use OMNI as an example — but every hit is a task whose pass rate can no longer
be read as retrieval without reading the hit first. Read-only; no test runs it against a
real checkout in CI, which has none (`tests/test_contamination.py` skips without
`HELIOAI_ROOT`), but its scanning logic is tested there.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from heliobench.tasks import Task, load_tasks  # noqa: E402

# What reaches the agent's context, relative to a HelioAI checkout.
CONTEXT_GLOBS = (
    "helioai/core/skills/**/*.md",
    "helioai/core/agent_loop.py",
    "helioai/core/sub_agents.py",
    "helioai/data/recipes/*.py",
)


def event_date(fixtures: Path, event: str) -> str | None:
    """The date that names an event in prose, from its fixture's windows."""
    windows = fixtures / event / "windows.json"
    if not windows.is_file():
        return None
    return json.loads(windows.read_text(encoding="utf-8"))["shock"][:10]


def _spellings_of(value: float, text: str) -> list[str]:
    """Numbers in `text` that are `value` rounded to the digits they print.

    `409.9881`, `409.99` and `410.0` are all the answer; `f"{value:g}"` searched only for
    `409.988`, which the exact spelling never contains. At least three significant digits,
    or every `2` beside a date would be the density compression.
    """
    from heliobench.graders.numeric import _NUMBER, normalise, parse
    from heliobench.graders.provenance import _tolerance

    out = []
    for m in _NUMBER.finditer(normalise(text)):
        try:
            raw, v, _ = parse(m)
        except ValueError:
            continue
        digits = len(raw.lower().split("e")[0].replace("-", "").replace(".", "").lstrip("0"))
        if digits >= 3 and abs(v - value) <= _tolerance(raw):
            out.append(raw)
    return out


def scan(files: dict[str, str], tasks: list[Task], fixtures: Path) -> list[dict]:
    """Every place a task's answer is written in `files` (path → text)."""
    hits: list[dict] = []
    for t in tasks:
        if t.tier == "n1":
            for pid in t.expected.get("ids", []):
                # `amda/imf` is not written inside `amda/imf_real_gse`: an id ends where the
                # characters an id may contain do.
                whole = re.compile(rf"(?<![\w/.\-]){re.escape(pid)}(?![\w/.\-])")
                for path, text in files.items():
                    if whole.search(text):
                        hits.append({"task": t.id, "file": path, "found": pid})
        elif t.tier == "n3" and "value" in t.expected:
            date = event_date(fixtures, t.event)
            if not date:
                continue
            value = float(t.expected["value"])
            for path, text in files.items():
                if date not in text:
                    continue
                for raw in _spellings_of(value, text):
                    hits.append({"task": t.id, "file": path, "found": f"{raw} beside {date}"})
    return hits


def context_files(root: Path, profiles: list[Path]) -> dict[str, str]:
    """The text of every file that reaches the agent's context."""
    out: dict[str, str] = {}
    for pattern in CONTEXT_GLOBS:
        for p in sorted(root.glob(pattern)):
            out[str(p.relative_to(root))] = p.read_text(encoding="utf-8", errors="replace")
    for p in profiles:
        if p.is_file():
            out[str(p)] = p.read_text(encoding="utf-8", errors="replace")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--helioai-root", required=True, type=Path)
    ap.add_argument("--profile", action="append", default=[], type=Path)
    ap.add_argument("--tasks-dir", default=str(REPO / "tasks"))
    ap.add_argument("--fixtures", default=str(REPO / "fixtures"), type=Path)
    args = ap.parse_args(argv)

    files = context_files(args.helioai_root, args.profile)
    if not files:
        raise SystemExit(f"nothing to scan under {args.helioai_root}")
    hits = scan(files, load_tasks(args.tasks_dir), args.fixtures)
    print(f"scanned {len(files)} file(s)")
    for h in hits:
        print(f"{h['task']:<28} {h['file']}: {h['found']}")
    print(f"{len(hits)} hit(s) over {len({h['task'] for h in hits})} task(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
