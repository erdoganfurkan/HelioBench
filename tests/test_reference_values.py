"""Tier-n3 truth must be derivable from what this repository ships, and nothing else."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from heliobench import recipes
from heliobench.tasks import load_tasks

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

# Which reference figure each n3 task's key is. Kept beside the check rather than in the
# task files so that adding the link did not touch `tasks/`; the provenance line of each
# task names the deriving script, and this is the table that makes that line testable.
REFERENCE_KEY = {
    "n3_alfven_speed": "rh_V_A",
    "n3_bmag_downstream": "b_dn_nT",
    "n3_bmag_upstream": "b_up_nT",
    "n3_density_compression": "density_compression",
    "n3_density_downstream": "n_dn_cm3",
    "n3_density_upstream": "n_up_cm3",
    "n3_field_compression": "field_compression",
    "n3_mach_alfven": "rh_M_A",
    "n3_shock_speed": "rh_V_shock",
    "n3_speed_downstream": "v_dn_km_s",
    "n3_speed_upstream": "v_up_km_s",
    "n3_theta_bn": "theta_bn_deg",
}


@pytest.mark.parametrize("name", sorted(recipes.MANIFEST))
def test_each_frozen_recipe_is_the_bytes_the_manifest_says(name):
    recipes.verify(name)
    assert len(recipes.MANIFEST[name][0]) == 40, "upstream commit must be a full sha"


def test_an_edited_recipe_is_refused(tmp_path, monkeypatch):
    fake = tmp_path / "theta_bn.py"
    fake.write_text("def theta_bn(a, b): return {'theta_bn_deg': 0.0}\n")
    monkeypatch.setattr(recipes, "HERE", tmp_path)
    with pytest.raises(recipes.RecipeError):
        recipes.namespace("theta_bn")


def test_the_frozen_recipes_pass_their_own_self_checks():
    # rankine_hugoniot's tail asserts against the archived 2015-03-17 values; theta_bn's
    # runs on a placeholder. Both must import cleanly with `export` stubbed.
    assert callable(recipes.namespace("theta_bn")["theta_bn"])
    assert callable(recipes.namespace("rankine_hugoniot")["_rh_core"])


def test_the_stored_reference_reproduces_from_the_frozen_bytes():
    import reference_values

    derived = reference_values.derive("stpatrick_2015")
    stored = json.loads((REPO / "fixtures/stpatrick_2015/reference.json").read_text())
    assert derived == stored


def test_every_n3_answer_key_is_the_derived_value_not_a_remembered_one():
    stored = json.loads((REPO / "fixtures/stpatrick_2015/reference.json").read_text())
    n3 = load_tasks("tasks", tiers=["n3"])
    assert {t.id for t in n3} == set(REFERENCE_KEY), "a new n3 task needs a reference key"
    for t in n3:
        assert float(t.expected["value"]) == stored[REFERENCE_KEY[t.id]], t.id


def test_the_windows_the_prompts_state_are_the_windows_the_truth_used():
    win = json.loads((REPO / "fixtures/stpatrick_2015/windows.json").read_text())
    for t in load_tasks("tasks", tiers=["n3"]):
        for edge in (*win["upstream"], *win["downstream"]):
            assert edge in t.prompt, f"{t.id} does not state window edge {edge}"
