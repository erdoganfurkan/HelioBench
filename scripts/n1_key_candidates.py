"""List every catalogue entry that could answer a tier-n1 prompt, straight from the index.

An n1 answer key is a claim about what the archive contains, so it has to be read out of the
archive rather than recalled. The reference run made that concrete: three keys had been
written from memory, and each rejected an identifier that the index describes in the exact
words of the prompt. A task whose key rejects a defensible answer measures the key, not the
agent.

Matching is a plain regex over `id || document`, not a nearest-neighbour query: the point is
the *whole* set of defensible answers, which a top-k search is built to hide.

    python scripts/n1_key_candidates.py '^cda/WI_' 'position' 'gse'

Every pattern must match. Read-only, and no test ships with it: the index is HelioAI's
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
    hits = candidates(sys.argv[1:])
    for pid, doc in hits:
        print(f"{pid}\n    {doc[:300]}\n")
    print(f"-- {len(hits)} of 82433 entries match", file=sys.stderr)
