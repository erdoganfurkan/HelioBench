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
    ]:
        with pytest.raises(ValueError, match=why):
            parse_agent_env([bad])


def test_the_env_snapshot_masks_anything_credential_like():
    from heliobench.adapters.helioai import redacted_env

    env = {"HELIOAI_MCP_TOKEN": "s3cret", "HELIOAI_EXPERIMENTS": "x", "PATH": "/bin"}
    assert redacted_env(env) == {"HELIOAI_EXPERIMENTS": "x", "HELIOAI_MCP_TOKEN": "<set>"}
