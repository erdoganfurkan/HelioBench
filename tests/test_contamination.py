"""The contamination scan finds an answer written into the agent's context, and only that."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from heliobench.tasks import load_tasks

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import contamination_check as cc  # noqa: E402

TASKS = load_tasks(REPO / "tasks")
FIXTURES = REPO / "fixtures"


def test_an_accepted_id_in_a_skill_is_a_hit():
    n1 = next(t for t in TASKS if t.tier == "n1")
    pid = n1.expected["ids"][0]
    hits = cc.scan({"skills/x.md": f"for example use {pid}"}, [n1], FIXTURES)
    assert hits == [{"task": n1.id, "file": "skills/x.md", "found": pid}]


def test_an_id_inside_a_longer_id_is_not_a_hit():
    # The first real scan flagged `amda/imf` inside the skill's `amda/imf_real_gse`.
    n1 = next(t for t in TASKS if t.id == "n1_amda_imf")
    assert cc.scan({"s.md": "- `amda/imf_real_gse`"}, [n1], FIXTURES) == []
    assert cc.scan({"s.md": "- `amda/imf`."}, [n1], FIXTURES) != []


def test_an_n3_value_counts_only_beside_the_events_date():
    n3 = next(t for t in TASKS if t.id == "n3_theta_bn")
    value = f"{n3.expected['value']:g}"
    assert cc.scan({"r.py": f"theta = {value}"}, [n3], FIXTURES) == []
    hits = cc.scan({"r.py": f"On 2015-03-17 theta was {value} deg"}, [n3], FIXTURES)
    assert [h["found"] for h in hits] == [f"{value} beside 2015-03-17"]
    assert cc.scan({"r.py": f"On 2015-03-17 theta was 1{value}"}, [n3], FIXTURES) == []


def test_the_windows_every_prompt_states_are_not_a_hit():
    # HelioAI's rankine_hugoniot self-check asserts the St Patrick's windows; so do the prompts.
    n3 = next(t for t in TASKS if t.id == "n3_theta_bn")
    assert cc.scan({"s.py": "window 2015-03-17T03:35:59 to 03:55:59"}, [n3], FIXTURES) == []


@pytest.mark.skipif(not os.environ.get("HELIOAI_ROOT"), reason="needs a HelioAI checkout")
def test_the_agent_under_test_carries_no_answer():
    root = Path(os.environ["HELIOAI_ROOT"])
    hits = cc.scan(cc.context_files(root, []), TASKS, FIXTURES)
    assert hits == [], hits
