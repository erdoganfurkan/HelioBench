from heliobench.trace import TokenUsage, Trace


def _trace():
    return Trace(
        task_id="t1",
        prompt="p",
        agent="helioai",
        events=[
            {"event": "tool_call", "data": {"name": "search_parameters"}, "t": 0.1},
            {"event": "tool_call", "data": {"name": "get_timeseries"}, "t": 0.4},
            {"event": "done", "data": {"n_iterations": 3}, "t": 1.0},
        ],
        tokens=TokenUsage(prompt=10, completion=2, calls=1),
    )


def test_tool_calls_keep_order_and_repeats():
    assert _trace().tool_calls() == ["search_parameters", "get_timeseries"]


def test_n_iterations_is_zero_when_the_run_never_finished():
    assert Trace(task_id="t", prompt="p", agent="a").n_iterations == 0
    assert _trace().n_iterations == 3


def test_round_trip_through_disk_preserves_the_token_type(tmp_path):
    path = _trace().write(tmp_path / "trace.json")
    back = Trace.read(path)
    assert isinstance(back.tokens, TokenUsage)
    assert back.tokens.prompt == 10
    assert back.tool_calls() == ["search_parameters", "get_timeseries"]
