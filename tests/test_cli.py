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
