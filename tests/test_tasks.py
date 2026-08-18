import pytest
import yaml

from heliobench.tasks import Task, TaskError, load_tasks

_GOOD = {
    "id": "n2_beta_magnetosheath",
    "tier": "n2",
    "prompt": "Plasma beta for B = 20 nT, n = 25 cm^-3, T = 100 eV?",
    "expected": {"value": 2.52, "units": ""},
    "provenance": "plasmapy.formulary.beta",
}


def _write(tmp_path, name, mapping):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    return p


def test_loads_a_well_formed_task(tmp_path):
    _write(tmp_path, "a.yaml", _GOOD)
    (task,) = load_tasks(tmp_path)
    assert task.id == "n2_beta_magnetosheath"
    assert task.expected["value"] == 2.52


def test_a_task_with_no_event_clusters_alone():
    # Not cosmetic: the clustering key feeds the confidence interval, and a task silently
    # sharing the empty-string cluster with every other would correlate unrelated items.
    t = Task(id="x", tier="n1", prompt="p", expected={}, provenance="q")
    assert t.event == "x"


@pytest.mark.parametrize(
    "mutate, complaint",
    [
        (lambda d: d.pop("expected"), "missing required key"),
        (lambda d: d.update(tier="n9"), "not one of"),
        (lambda d: d.update(expected="2.52"), "must be a mapping"),
        (lambda d: d.update(tolerence={"rel": 0.05}), "unknown key"),
    ],
)
def test_a_task_that_cannot_be_trusted_raises(tmp_path, mutate, complaint):
    bad = dict(_GOOD)
    mutate(bad)
    _write(tmp_path, "bad.yaml", bad)
    with pytest.raises(TaskError, match=complaint):
        load_tasks(tmp_path)


def test_duplicate_ids_raise(tmp_path):
    # Two files, one id: the denominator would move without anyone noticing.
    _write(tmp_path, "a.yaml", _GOOD)
    _write(tmp_path, "b.yaml", _GOOD)
    with pytest.raises(TaskError, match="duplicate task id"):
        load_tasks(tmp_path)


def test_tier_filter(tmp_path):
    _write(tmp_path, "a.yaml", _GOOD)
    _write(tmp_path, "b.yaml", {**_GOOD, "id": "n1_x", "tier": "n1"})
    assert [t.id for t in load_tasks(tmp_path, tiers=["n1"])] == ["n1_x"]
