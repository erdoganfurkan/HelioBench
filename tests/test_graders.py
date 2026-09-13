import pytest

from heliobench.graders import grade
from heliobench.graders.numeric import candidates, same_unit
from heliobench.graders.process import collect
from heliobench.graders.retrieval import extract_ids, retrieved_ids
from heliobench.tasks import Task
from heliobench.trace import Trace


def _trace(reply="", **kw):
    return Trace(task_id="t", prompt="p", agent="a", reply=reply, **kw)


# --- tier n1 -------------------------------------------------------------------------

_N1 = Task(
    id="n1_wind",
    tier="n1",
    prompt="which product",
    expected={"ids": ["cda/WI_H0_MFI/B3GSM"]},
    provenance="index",
)


def test_extract_ids_keeps_order_and_drops_trailing_punctuation():
    text = "Use cda/WI_H0_MFI/B3GSM, or amda/imf. Again cda/WI_H0_MFI/B3GSM."
    assert extract_ids(text) == ["cda/WI_H0_MFI/B3GSM", "amda/imf"]


def test_n1_passes_when_the_accepted_id_is_quoted():
    assert grade(_N1, _trace("The product is cda/WI_H0_MFI/B3GSM.")).passed


def test_n1_fails_on_a_near_miss():
    r = grade(_N1, _trace("Use cda/WI_H0_MFI/BGSM (1 minute)."))
    assert not r.passed and "no accepted id" in r.reason


def _search(*ids, name="search_parameters"):
    """A tool_output event shaped like the search tool's own return value."""
    results = ", ".join(f'{{"id": "{i}"}}' for i in ids)
    return {"event": "tool_output", "data": {"name": name, "result": f'{{"results": [{results}]}}'}}


def test_the_rank_of_the_accepted_id_is_read_out_of_the_search_output():
    trace = _trace(
        "The product is cda/WI_H0_MFI/B3GSM.",
        events=[_search("cda/WI_H0_MFI/BGSM", "amda/imf", "cda/WI_H0_MFI/B3GSM")],
    )
    r = grade(_N1, trace)
    assert r.passed
    assert r.detail["rank"] == 3 and r.detail["retrieved"] == 3 and r.detail["searched"]


def test_a_failure_with_the_product_never_returned_is_told_apart_from_one_that_passed_it_over():
    # The two look identical in the pass rate and need opposite fixes.
    passed_over = grade(_N1, _trace("Use amda/imf.", events=[_search("cda/WI_H0_MFI/B3GSM")]))
    never_returned = grade(_N1, _trace("Use amda/imf.", events=[_search("amda/imf")]))
    assert not passed_over.passed and passed_over.detail["rank"] == 1
    assert not never_returned.passed and never_returned.detail["rank"] is None


def test_a_run_recorded_without_tool_output_reports_no_rank_rather_than_a_miss():
    # Traces predating the recorder must not be counted as retrieval failures.
    r = grade(_N1, _trace("The product is cda/WI_H0_MFI/B3GSM."))
    assert r.passed and r.detail["searched"] is False and r.detail["rank"] is None


def test_only_search_tools_contribute_to_the_rank():
    trace = _trace("x", events=[_search("cda/WI_H0_MFI/B3GSM", name="get_parameter_info")])
    assert retrieved_ids(trace) == []


def test_an_invented_id_fails_even_beside_a_correct_one():
    # A reply offering a real product next to a fabricated one is not a partial success:
    # the reader cannot tell which is which.
    trace = _trace(
        "Use cda/WI_H0_MFI/B3GSM or cda/WI_H9_MFI/BOGUS.",
        events=[{"event": "invalid_ids", "data": {"ids": ["cda/WI_H9_MFI/BOGUS"]}}],
    )
    r = grade(_N1, trace)
    assert not r.passed and "invented" in r.reason


# --- tier n2 -------------------------------------------------------------------------

_N2 = Task(
    id="n2_beta",
    tier="n2",
    prompt="plasma beta",
    expected={"value": 2.5167, "units": "", "near": ["beta"]},
    tolerance={"rel": 0.05},
    provenance="plasmapy",
)


def test_n2_passes_within_tolerance():
    assert grade(_N2, _trace("The plasma beta is about 2.52.")).passed


def test_n2_fails_outside_tolerance():
    r = grade(_N2, _trace("The plasma beta is about 4.1."))
    assert not r.passed and "closest 4.1" in r.reason


def test_a_number_far_from_the_keyword_does_not_count():
    # The defence against a lucky substring: 2.52 exists in the reply, but as a ratio in a
    # sentence about something else entirely.
    r = grade(_N2, _trace("The density compression ratio was 2.52. " + "x " * 200 + "beta is 9."))
    assert not r.passed


@pytest.mark.parametrize("a,b", [("cm^-3", "cm-3"), ("#/cc", "n/cc"), ("°", "deg"), ("R_E", "Re")])
def test_unit_spellings_fold_together(a, b):
    assert same_unit(a, b)


def test_a_bare_number_never_matches_a_number_with_units():
    # 2.53 and 2.53 nT are not the same claim. Every false contradiction in the agent's own
    # provenance checker came from treating an unknown unit as compatible.
    assert candidates("B was 2.53 nT", "", None) == []


def test_a_run_that_failed_is_scored_as_a_miss_not_dropped():
    r = grade(_N2, _trace("2.52", error="boom"))
    assert not r.passed and "run failed" in r.reason


# --- the process gate ----------------------------------------------------------------


def _provenance(**counts):
    return {"event": "provenance", "data": counts}


def _ledger(*entries):
    """A ledger of scalars: (name, value, units)."""
    return {
        "values": [
            {"name": n, "mean": v, "min": v, "max": v, "std": 0.0, "units": u}
            for n, v, u in entries
        ]
    }


def test_a_number_the_session_computed_differently_fails_a_numerically_correct_run():
    # The gate: the session computed one number and the answer stated another. Recording
    # that under a passing score is recording that the run passed.
    r = grade(_N2, _trace("The plasma beta is about 2.52.", ledger=_ledger(("beta", 2.61, ""))))
    assert not r.passed
    assert "contradicts" in r.reason and r.detail["gate"] == "contradicted"
    assert r.detail["provenance"]["answer_contradicted"][0]["computed"] == 2.61


def test_the_gate_is_the_harness_verdict_not_the_agents():
    # The agent's own counter said "contradicted" ten times across the stored sweeps, every
    # time on a correct answer. It is reported beside the score and never gates it.
    trace = _trace(
        "The plasma beta is about 2.52.",
        events=[_provenance(contradicted=1)],
        ledger=_ledger(("beta", 2.5167, "")),
    )
    r = grade(_N2, trace)
    assert r.passed and r.detail["provenance"]["answer_sourced"] is True
    assert collect(trace).contradicted == 1


def test_an_answer_the_session_never_computed_is_unsourced_not_contradicted():
    # No number in the ledger is anywhere near the answer: the session computed something
    # else entirely. That is reported, not gated.
    r = grade(_N2, _trace("The plasma beta is about 2.52.", ledger=_ledger(("n_up", 17.7, "cm-3"))))
    assert r.passed and r.detail["provenance"]["answer_sourced"] is False


def test_an_empty_ledger_cannot_contradict_anything():
    r = grade(_N2, _trace("The plasma beta is about 2.52."))
    assert r.passed and r.detail["provenance"]["answer_sourced"] is None


def test_the_gate_reads_only_the_answer():
    # Bypassed recipes and unsourced figures are read beside the score, not instead of it.
    trace = _trace(
        "The plasma beta is about 2.52. Also 9.99 and 12.3 nT.",
        events=[_provenance(unsourced=3), {"event": "recipe_bypassed", "data": {"recipes": ["r"]}}],
        ledger=_ledger(("beta", 2.5167, "")),
    )
    assert grade(_N2, trace).passed


def test_the_gate_cannot_rescue_a_wrong_number():
    r = grade(_N2, _trace("The plasma beta is about 4.1.", ledger=_ledger(("beta", 4.1, ""))))
    assert not r.passed and "closest" in r.reason


# --- process -------------------------------------------------------------------------


def test_process_metrics_read_what_the_agent_already_reported():
    trace = _trace(
        events=[
            {"event": "tool_call", "data": {"name": "run_python"}},
            {"event": "tool_result", "data": {"name": "run_python", "summary": "error: boom"}},
            {"event": "invalid_ids", "data": {"ids": ["a/b/c"]}},
            {"event": "recipe_bypassed", "data": {"recipes": [{"recipe": "theta_bn"}]}},
            {"event": "provenance", "data": {"matched": 2, "contradicted": 1, "unsourced": 3}},
            {"event": "done", "data": {"n_iterations": 4}},
        ],
        ledger={"values": [{"name": "x"}]},
    )
    m = collect(trace)
    assert (m.n_iterations, m.tool_calls, m.tool_errors) == (4, 1, 1)
    assert (m.invented_ids, m.recipes_bypassed, m.ledger_entries) == (1, 1, 1)
    assert (m.matched, m.contradicted, m.unsourced) == (2, 1, 3)
    assert m.provenance_reported


def test_silence_about_provenance_is_not_four_zeros():
    # The agent emits nothing when the session computed nothing. An absent report and a
    # clean report must not read the same in the results table.
    assert collect(_trace()).provenance_reported is False
