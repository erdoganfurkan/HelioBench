"""The --agent-ref snapshot machinery, tested without the network.

The heavy path — clone, build a venv, install helioai-agent at a commit — needs uv, git
against the live remote and a full package build, so it is exercised manually and stays out of
CI (which runs with no network by design). What is tested here is everything around it:
ref resolution against a local git repo, argv rewriting, cache reuse, and the env the re-run
inherits.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from heliobench.agentsnapshot import (
    AgentRefError,
    _cache_dir,
    _looks_like_sha,
    _parse_ls_remote,
    _strip_agent_ref,
    build_env,
    ensure_venv,
    exec_in,
    resolve_ref,
)
from heliobench.cli import main


def _init_repo(path: Path) -> tuple[str, str]:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)
    sha = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(["git", "-C", str(path), "tag", "v1"], check=True)
    branch = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return sha, branch


# --- ref resolution -----------------------------------------------------------------


def test_a_commit_shaped_ref_passes_through_unchanged():
    sha = "0" * 40
    assert resolve_ref(sha) == sha


def test_a_short_sha_passes_through_unchanged():
    assert resolve_ref("deadbee") == "deadbee"


def test_resolving_a_branch_and_a_tag_read_the_commit_sha(tmp_path):
    sha, branch = _init_repo(tmp_path / "repo")
    assert resolve_ref(branch, repo=str(tmp_path / "repo")) == sha
    assert resolve_ref("v1", repo=str(tmp_path / "repo")) == sha


def test_an_unknown_ref_is_an_error_not_a_silent_miss(tmp_path):
    _init_repo(tmp_path / "repo")
    with pytest.raises(AgentRefError, match="not found"):
        resolve_ref("no_such_ref", repo=str(tmp_path / "repo"))


def test_parse_ls_remote_prefers_the_dereferenced_tag_commit():
    out = "aaa\trefs/tags/v1\nbbb\trefs/tags/v1^{}\n"
    assert _parse_ls_remote(out) == ["bbb"]


def test_parse_ls_remote_takes_the_plain_sha_for_a_branch():
    assert _parse_ls_remote("ccc\trefs/heads/main\n") == ["ccc"]


def test_looks_like_sha_accepts_hex_and_rejects_names():
    assert _looks_like_sha("abcdef1234567890") and not _looks_like_sha("main")


# --- venv cache ---------------------------------------------------------------------


def test_ensure_venv_requires_uv(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(AgentRefError, match="uv is required"):
        ensure_venv("0" * 40)


def test_ensure_venv_reuses_a_venv_that_is_already_built(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    venv_dir = _cache_dir() / "agents" / ("0" * 40) / ".venv"
    fake_py = venv_dir / "bin" / "python"
    fake_py.parent.mkdir(parents=True)
    fake_py.write_text("", encoding="utf-8")
    # uv must not be touched when the cache already holds the venv.
    monkeypatch.setattr(shutil, "which", lambda _name: "/does/not/exist/uv")
    assert ensure_venv("0" * 40) == fake_py


def test_ensure_venv_cleans_up_on_install_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(shutil, "which", lambda _name: "echo")  # fake uv

    orig_run = subprocess.run

    def mock_run(cmd, **kwargs):
        if cmd[1] == "venv":
            return orig_run(cmd, **kwargs)
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", mock_run)

    sha = "0" * 40
    venv_dir = _cache_dir() / "agents" / sha / ".venv"

    with pytest.raises(AgentRefError, match="failed to install"):
        ensure_venv(sha)

    assert not venv_dir.exists()


# --- the re-run environment ----------------------------------------------------------


def test_build_env_records_the_ref_and_prepends_the_harness(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/existing")
    env = build_env("abc123")
    assert env["HELIOBENCH_AGENT_REF"] == "abc123"
    entries = env["PYTHONPATH"].split(os.pathsep)
    assert entries[-1] == "/existing"
    assert (Path(entries[0]) / "heliobench" / "__init__.py").is_file()


def test_build_env_prepends_even_without_an_existing_pythonpath(monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    entries = build_env("abc123")["PYTHONPATH"].split(os.pathsep)
    assert (Path(entries[0]) / "heliobench" / "__init__.py").is_file()


def test_exec_in_replaces_the_process_with_the_stripped_argv_and_the_built_env(monkeypatch):
    calls: dict = {}

    def fake_execve(path, argv, env):
        calls["path"] = path
        calls["argv"] = argv
        calls["env"] = env

    monkeypatch.setattr(os, "execve", fake_execve)
    exec_in(Path("/tmp/venv/bin/python"), ["run", "--agent-ref", "main", "--runs", "3"], "abc")
    assert calls["path"] == "/tmp/venv/bin/python"
    assert calls["argv"] == ["/tmp/venv/bin/python", "-m", "heliobench.cli", "run", "--runs", "3"]
    assert calls["env"]["HELIOBENCH_AGENT_REF"] == "abc"
    assert (
        Path(calls["env"]["PYTHONPATH"].split(os.pathsep)[0]) / "heliobench" / "__init__.py"
    ).is_file()


# --- argv rewriting ------------------------------------------------------------------


def test_strip_agent_ref_removes_both_forms():
    assert _strip_agent_ref(["--agent", "helioai", "--agent-ref", "main", "--runs", "3"]) == [
        "--agent",
        "helioai",
        "--runs",
        "3",
    ]
    assert _strip_agent_ref(["--agent-ref=main", "run"]) == ["run"]
    assert _strip_agent_ref(["--runs", "3"]) == ["--runs", "3"]


# --- CLI -----------------------------------------------------------------------------


def test_agent_ref_requires_the_helioai_agent():
    with pytest.raises(SystemExit) as e:
        main(["run", "--agent", "null", "--agent-ref", "main"])
    assert "--agent helioai" in str(e.value)
