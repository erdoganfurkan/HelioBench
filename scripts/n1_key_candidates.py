"""List every catalogue entry that could answer a tier-n1 prompt, straight from the index.

An n1 answer key is a claim about what the archive contains, so it has to be read out of the
archive rather than recalled. The reference run made that concrete: three keys had been
written from memory, and each rejected an identifier that the index describes in the exact
words of the prompt. A task whose key rejects a defensible answer measures the key, not the
agent.

Matching is a plain regex over `id || document`, not a nearest-neighbour query: the point is
the *whole* set of defensible answers, which a top-k search is built to hide.

    python scripts/n1_key_candidates.py '^cda/WI_' 'position' 'gse'
    python scripts/n1_key_candidates.py --check        # every task that records its query

Every pattern must match.

`--check` re-runs the `key_query` each n1 task records and lists every candidate that is
neither accepted nor covered by one of the task's `key_excluded` patterns (each with its
reason), and every accepted id the query no longer finds. An unexplained candidate is a
defensible answer nobody decided about — the defect of 2026-08-21 and of `n1_dst_index`,
whose recorded query returned `cda/OMNI2_H0_MRG1HR/DST1800` and whose key omitted it by hand. Read-only, and no test ships with it: the index is HelioAI's
342 MB Chroma store, which this repository deliberately does not vendor.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

INDEX = Path(os.environ.get("HELIOBENCH_INDEX", "../HelioAI/data/chroma")) / "chroma.sqlite3"

_ROWS = """
select e.embedding_id,
       max(case when m.key = 'chroma:document' then m.string_value end)
from embeddings e
join segments s on s.id = e.segment_id
join embedding_metadata m on m.id = e.id
where s.collection = (select id from collections where name = 'speasy_catalog')
group by e.id
"""


def index_count() -> int:
    """Products in the index, counted rather than remembered."""
    db = sqlite3.connect(f"file:{INDEX}?mode=ro", uri=True)
    return sum(1 for _ in db.execute(_ROWS))


def check(tasks) -> list[str]:
    """Problems with every task that records its enumeration; empty when all keys hold."""
    problems = []
    for t in tasks:
        if t.tier != "n1" or not t.key_query:
            continue
        found = [pid for pid, _ in candidates(list(t.key_query))]
        accepted = set(t.expected.get("ids", []))
        excluded = [(re.compile(e["pattern"]), e["reason"]) for e in t.key_excluded]
        for pid in found:
            if pid not in accepted and not any(rx.search(pid) for rx, _ in excluded):
                problems.append(
                    f"{t.id}: {pid} matches the query and is neither accepted nor excluded"
                )
        for pid in sorted(accepted - set(found)):
            problems.append(f"{t.id}: accepted {pid} is not returned by the recorded query")
    return problems


def candidates(patterns: list[str]) -> list[tuple[str, str]]:
    """Entries whose identifier or description matches all of `patterns`, case-insensitively."""
    db = sqlite3.connect(f"file:{INDEX}?mode=ro", uri=True)
    res = [re.compile(p, re.I) for p in patterns]
    return [
        (pid, doc or "")
        for pid, doc in db.execute(_ROWS)
        if all(r.search(f"{pid} || {doc}") for r in res)
    ]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--check":
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from heliobench.tasks import load_tasks

        tasks = load_tasks(Path(__file__).resolve().parent.parent / "tasks", tiers=["n1"])
        problems = check(tasks)
        recorded = sum(1 for t in tasks if t.key_query)
        for p in problems:
            print(p)
        print(
            f"-- {recorded}/{len(tasks)} n1 tasks record their query; {len(problems)} problem(s)",
            file=sys.stderr,
        )
        sys.exit(1 if problems else 0)
    hits = candidates(sys.argv[1:])
    for pid, doc in hits:
        print(f"{pid}\n    {doc[:300]}\n")
    print(f"-- {len(hits)} of {index_count()} entries match", file=sys.stderr)
