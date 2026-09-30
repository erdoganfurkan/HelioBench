"""The before/after tool a scoring PR pastes must never touch the runs it reads."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from heliobench.adapters.null import NullAgent
from heliobench.runner import run
from heliobench.tasks import load_tasks

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import regrade_stored  # noqa: E402


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_regrading_a_copy_leaves_the_stored_run_byte_for_byte(tmp_path):
    stored = tmp_path / "stored"
    tasks = load_tasks("tasks", tiers=["n2"])[:2]
    run(NullAgent(), tasks, stored / "20260101T000000Z_null", runs=1)
    before = _tree_digest(stored)

    assert regrade_stored.main([str(stored), "--work", str(tmp_path / "work")]) == 0

    assert _tree_digest(stored) == before
    assert (tmp_path / "work").is_dir()


def test_a_work_dir_inside_a_stored_root_is_refused(tmp_path):
    stored = tmp_path / "stored"
    stored.mkdir()
    with pytest.raises(SystemExit, match="never regraded"):
        regrade_stored.main([str(stored), "--work", str(stored / "copies")])


def test_a_verdict_that_moves_is_listed(tmp_path):
    stored = tmp_path / "stored"
    tasks = load_tasks("tasks", tiers=["n2"])[:1]
    run_dir = stored / "20260101T000000Z_null"
    run(NullAgent(), tasks, run_dir, runs=1)
    results = run_dir / "results.json"
    results.write_text(
        results.read_text().replace('"outcome": "failed"', '"outcome": "passed"'),
        encoding="utf-8",
    )
    row = regrade_stored.compare_one(run_dir, tmp_path / "copy", tasks)
    assert [(f["before"], f["after"]) for f in row["flips"]] == [("passed", "failed")]
    assert "→ **" in regrade_stored.render([row])


def test_against_a_previous_regrade_diffs_the_two_regrades(tmp_path):
    stored = tmp_path / "stored"
    tasks = load_tasks("tasks", tiers=["n2"])[:1]
    run(NullAgent(), tasks, stored / "20260101T000000Z_null", runs=1)
    base = tmp_path / "base.json"
    regrade_stored.main([str(stored), "--work", str(tmp_path / "a"), "--json", str(base)])
    data = base.read_text().replace('"outcome": "failed"', '"outcome": "passed"')
    base.write_text(data, encoding="utf-8")
    out = tmp_path / "b.json"
    regrade_stored.main(
        [str(stored), "--work", str(tmp_path / "b"), "--against", str(base), "--json", str(out)]
    )
    import json

    (row,) = json.loads(out.read_text())
    assert [(f["before"], f["after"]) for f in row["flips"]] == [("passed", "failed")]
