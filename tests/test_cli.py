import pytest

from heliobench.cli import main


def test_help_exits_clean(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    assert "heliobench" in capsys.readouterr().out


def test_list_on_an_empty_dir_says_so(tmp_path, capsys):
    assert main(["list", "--tasks-dir", str(tmp_path)]) == 0
    assert "no tasks found" in capsys.readouterr().out


def test_unimplemented_subcommand_returns_nonzero(tmp_path, capsys):
    # A benchmark that exits 0 while doing nothing is worse than one that crashes.
    assert main(["run", "--tasks-dir", str(tmp_path)]) == 2


def test_the_task_filter_selects_exactly_those_ids(capsys):
    assert main(["list", "--task", "n2_beta_solar_wind", "--task", "n3_theta_bn"]) == 0
    out = capsys.readouterr().out
    assert "n2_beta_solar_wind" in out and "n3_theta_bn" in out
    assert "2 task(s)" in out


def test_an_unknown_task_id_is_refused_rather_than_silently_dropped(capsys):
    # Silently running 57 of the 58 tasks you asked for is how a benchmark reports a score
    # for a question set nobody chose.
    with pytest.raises(SystemExit) as e:
        main(["list", "--task", "no_such_task"])
    assert "no such task" in str(e.value)


def test_the_cli_and_the_adapter_agree_on_the_default_provider():
    # `run --agent helioai` with no flag used to land on groq while the adapter's own
    # default, and every documented run, was azure.
    import inspect

    from heliobench.adapters.helioai import HelioAIAgent
    from heliobench.cli import build_parser

    args = build_parser().parse_args(["verify", "--agent", "helioai"])
    adapter_default = inspect.signature(HelioAIAgent.__init__).parameters["provider"].default
    assert args.provider == adapter_default == "azure"


def test_agent_env_takes_only_helioai_variables_the_adapter_does_not_own():
    from heliobench.adapters.helioai import parse_agent_env

    assert parse_agent_env(["HELIOAI_EXPERIMENTS=final_answer,deferred_tools"]) == {
        "HELIOAI_EXPERIMENTS": "final_answer,deferred_tools"
    }
    for bad, why in [
        ("OPENCODE_API_KEY=x", "only sets HELIOAI_"),
        ("HELIOAI_DATA_DIR=/tmp", "set by the adapter"),
        ("HELIOAI_OPENCODE_MODEL=m", "set by the adapter"),
        ("HELIOAI_EXPERIMENTS", "KEY=VALUE"),
        ("HELIOAI_MCP_TOKEN=abc", "credential"),
        ("HELIOAI_DEV_TOKEN=abc", "credential"),
    ]:
        with pytest.raises(ValueError, match=why):
            parse_agent_env([bad])


def test_the_env_snapshot_masks_anything_credential_like():
    from heliobench.adapters.helioai import redacted_env

    env = {"HELIOAI_MCP_TOKEN": "s3cret", "HELIOAI_EXPERIMENTS": "x", "PATH": "/bin"}
    assert redacted_env(env) == {"HELIOAI_EXPERIMENTS": "x", "HELIOAI_MCP_TOKEN": "<set>"}


def _null_run(tmp_path, where):
    from heliobench.adapters.null import NullAgent
    from heliobench.runner import run
    from heliobench.tasks import load_tasks

    run(NullAgent(), load_tasks("tasks", tiers=["n2"])[:1], where, runs=1)
    return where


def test_a_stored_run_is_not_regraded_in_place(tmp_path):
    stored = _null_run(tmp_path, tmp_path / "results" / "20260101T000000Z_null")
    with pytest.raises(SystemExit, match="refusing to regrade"):
        main(["report", str(stored), "--regrade"])


def test_regrade_out_works_on_a_copy_and_leaves_the_original(tmp_path, capsys):
    stored = _null_run(tmp_path, tmp_path / "results" / "20260101T000000Z_null")
    before = (stored / "meta.json").read_text()
    copy = tmp_path / "copy"
    assert main(["report", str(stored), "--regrade", "--out", str(copy)]) == 0
    assert (stored / "meta.json").read_text() == before
    assert "regraded" in (copy / "meta.json").read_text()


def test_in_place_is_an_explicit_choice(tmp_path, capsys):
    stored = _null_run(tmp_path, tmp_path / "results" / "20260101T000000Z_null")
    assert main(["report", str(stored), "--regrade", "--in-place"]) == 0


def test_an_n1_key_the_index_cannot_satisfy_is_a_verify_problem(capsys):
    from heliobench.cli import _check_keys_in_index
    from heliobench.tasks import Task

    t_ok = Task(id="a", tier="n1", prompt="p", expected={"ids": ["x/1", "x/2"]}, provenance="v")
    t_gone = Task(id="b", tier="n1", prompt="p", expected={"ids": ["y/1"]}, provenance="v")

    class Agent:
        def missing_ids(self, ids):
            return {"x/2", "y/1"}

    problems = _check_keys_in_index(Agent(), [t_ok, t_gone])
    assert problems == ["b: no accepted id is in this index (y/1)"]
    out = capsys.readouterr().out
    assert "a names ids this index lacks: x/2" in out and "1/3 ids found" in out


def test_an_agent_that_cannot_be_asked_is_not_a_problem():
    from heliobench.cli import _check_keys_in_index
    from heliobench.tasks import load_tasks

    assert _check_keys_in_index(object(), load_tasks("tasks", tiers=["n1"])) == []
