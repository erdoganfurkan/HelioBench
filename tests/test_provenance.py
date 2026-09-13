"""The provenance verdict is the harness's, computed from the ledger and the reply.

Every case here is a shape seen in a stored trace: the vector whose component read as a
contradiction, the magnitude that read as one, the difference of two ledger scalars, the
literature value quoted beside the right answer.
"""

from __future__ import annotations

from heliobench.graders.provenance import check_answer, classify_prose, sources


def _scalar(name, v, units=""):
    return {"name": name, "mean": v, "min": v, "max": v, "std": 0.0, "units": units}


def _vector(name, comps, units=""):
    import statistics

    return {
        "name": name,
        "mean": sum(comps) / 3,
        "min": min(comps),
        "max": max(comps),
        "std": statistics.pstdev(comps),
        "units": units,
    }


# The B_up_gsm entry of the 2026-08-27 n3_theta_bn run, which the agent flagged twice.
B_UP = _vector("B_up_gsm", [-2.3298197388648987, -0.401, 9.38207643032074], "nT")
N_HAT = _vector("shock_normal_gsm", [-0.6609380065362107, -0.657397, 0.36192522480537503])


def test_a_3_vector_is_reconstructed_from_its_summary():
    kinds = {(s.kind, round(s.value, 3)) for s in sources({"values": [B_UP]})}
    assert ("component", -0.401) in kinds
    assert ("magnitude", 9.675) in kinds


def test_a_series_summary_is_not_mistaken_for_a_vector():
    series = {"name": "np", "mean": 30.0, "min": 10.0, "max": 50.0, "std": 12.0, "units": "cm-3"}
    kinds = {s.kind for s in sources({"values": [series]})}
    assert kinds == {"stat"}


def test_the_component_and_the_magnitude_of_a_vector_are_sourced():
    # `-0.657` beside `shock_normal_gsm`, `9.68 nT` beside `B_up_gsm`: the agent called both
    # contradictions. They are the vector's own numbers.
    p = classify_prose("n̂ = (−0.661, −0.657, +0.362); |B_up| = 9.68 nT.", {"values": [B_UP, N_HAT]})
    assert p.matched == 4 and p.unsourced == 0


def test_the_difference_of_two_ledger_scalars_is_derived():
    # `161 km/s` beside `shock_speed_km_s = 571`: it is 571 − 410, both in the ledger.
    ledger = {"values": [_scalar("V_up", 409.9881, "km/s"), _scalar("V_shock", 571.0655, "km/s")]}
    p = classify_prose("the flow relative to the shock drops from ≈161 km/s", ledger)
    assert p.derived == 1 and p.unsourced == 0


def test_a_ratio_of_two_ledger_scalars_is_derived():
    ledger = {"values": [_scalar("n_up", 17.7707, "cm-3"), _scalar("n_dn", 48.5418, "cm-3")]}
    assert classify_prose("compression ≈ 2.73", ledger).derived == 1


def test_rounding_to_the_printed_digits_is_a_match():
    ledger = {"values": [_scalar("M_A", 3.2082)]}
    assert classify_prose("M_A ≈ 3.2 (3.21)", ledger).matched == 2


def test_units_must_agree_for_a_match():
    ledger = {"values": [_scalar("theta", 57.5, "deg")]}
    p = classify_prose("57.5 nT", ledger)
    assert p.matched == 0 and p.unsourced == 1


def test_bare_integers_and_the_prompts_own_numbers_are_not_claims():
    ledger = {"values": [_scalar("x", 1.0)]}
    p = classify_prose(
        "On 17 March 2015, 20 samples between 03:35:59 and 03:55:59; B = 5.0 nT as given.",
        ledger,
        prompt="B = 5.0 nT",
    )
    assert (p.matched, p.derived, p.unsourced) == (0, 0, 0)


def test_the_answer_is_sourced_when_any_accepted_value_is_in_the_ledger():
    # The reply stated the computed mean and, beside it, the window's median.
    ledger = {"values": [_scalar("V_up_mean", 409.9881, "km/s")]}
    p = check_answer([409.5, 409.99], "km/s", ledger, ["409.5", "409.99"])
    assert p.answer_sourced is True and not p.answer_contradicted


def test_the_answer_is_contradicted_when_the_ledger_holds_a_different_nearby_value():
    ledger = {"values": [_scalar("V_shock", 571.0655, "km/s")]}
    p = check_answer([575.0], "km/s", ledger, ["575.0"])
    assert p.answer_sourced is False
    assert p.answer_contradicted[0]["name"] == "V_shock"


def test_a_distant_ledger_value_is_not_a_contradiction():
    ledger = {"values": [_scalar("n_up", 17.7707, "cm-3")]}
    p = check_answer([48.5], "cm-3", ledger, ["48.5"])
    assert p.answer_sourced is False and not p.answer_contradicted


def test_an_empty_ledger_says_nothing():
    p = check_answer([2.52], "", {}, ["2.52"])
    assert p.answer_sourced is None and not p.answer_contradicted
