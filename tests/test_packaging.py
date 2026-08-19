"""The shipped repository has to work on clone, without anyone reading the source first."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".claude/skills/heliobench/SKILL.md"
SCRIPT = REPO / ".claude/skills/heliobench/scripts/heliobench.sh"


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_the_skill_declares_what_it_is_for():
    fm = _frontmatter(SKILL)
    assert fm["name"] == "heliobench"
    assert len(fm["description"]) > 40, "the description is the only trigger Claude sees"


def test_the_skill_preapproves_exactly_the_script_it_tells_claude_to_run():
    # The documented no-prompt pattern: the same ${CLAUDE_SKILL_DIR} path in `allowed-tools`
    # and in the body. If they drift apart the skill starts asking for permission mid-run.
    fm = _frontmatter(SKILL)
    assert "${CLAUDE_SKILL_DIR}/scripts/heliobench.sh" in fm["allowed-tools"]
    assert "${CLAUDE_SKILL_DIR}/scripts/heliobench.sh" in SKILL.read_text(encoding="utf-8")


def test_the_skill_forbids_the_model_from_grading():
    body = SKILL.read_text(encoding="utf-8").lower()
    assert "never decide whether an answer was right" in body


def test_the_launcher_is_executable_and_finds_the_repo_from_anywhere():
    assert os.access(SCRIPT, os.X_OK), "the launcher must be committed executable"
    out = subprocess.run(
        [str(SCRIPT), "list", "--tier", "n2"],
        cwd="/",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert "task(s)" in out.stdout, "the script must resolve the repo, not trust cwd"


def test_the_plugin_declares_no_version_so_the_commit_is_the_cache_key():
    # Claude Code keys its plugin cache on the declared version and falls back to the git
    # commit when there is none. Declaring one means every skill edit needs a manual bump,
    # which will be forgotten, and the user silently keeps running a stale copy.
    plugin = json.loads((REPO / ".claude-plugin/plugin.json").read_text())
    assert "version" not in plugin
    market = json.loads((REPO / ".claude-plugin/marketplace.json").read_text())
    assert "version" not in market["plugins"][0]


def test_the_plugin_manifests_parse_and_name_themselves_consistently():
    plugin = json.loads((REPO / ".claude-plugin/plugin.json").read_text())
    market = json.loads((REPO / ".claude-plugin/marketplace.json").read_text())
    assert plugin["name"] == "heliobench"
    assert [p["name"] for p in market["plugins"]] == ["heliobench"]
    assert market["plugins"][0]["source"] == "./"
    assert market["owner"]["name"]


def test_the_console_script_is_installed():
    out = subprocess.run(
        [sys.executable, "-m", "heliobench.cli", "--version"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )
    assert out.returncode == 0 and "heliobench" in out.stdout


def test_the_fixture_is_shipped_and_its_manifest_is_readable():
    manifest = REPO / "fixtures/stpatrick_2015/data/manifest.json"
    assert manifest.is_file(), "tier n3 cannot replay offline without the frozen fixture"
    datasets = json.loads(manifest.read_text())["datasets"]
    assert len(datasets) == 8
    for name, entry in datasets.items():
        assert (manifest.parent / entry["file"]).is_file(), f"{name} names a missing npz"


def test_the_reference_values_are_shipped_beside_the_fixture():
    ref = json.loads((REPO / "fixtures/stpatrick_2015/reference.json").read_text())
    assert ref["windows"]["upstream"] and ref["theta_bn_deg"] > 0


def test_the_skill_is_pinned_to_a_small_model():
    # Reading a markdown report and launching a script does not need a large model, and a
    # sweep that takes an hour should not be expensive to supervise.
    assert _frontmatter(SKILL)["model"] == "sonnet"


def test_the_plugin_points_at_the_one_copy_of_the_skill():
    # A plugin scans `skills/` by default, but the skill lives under `.claude/skills/` so it
    # also loads as a project skill inside this repo. Pointing the manifest at that directory
    # is what keeps one file instead of two copies that drift apart.
    plugin = json.loads((REPO / ".claude-plugin/plugin.json").read_text())
    assert plugin["skills"] == ["./.claude/skills"]
    assert (REPO / plugin["skills"][0].removeprefix("./") / "heliobench" / "SKILL.md").is_file()


def test_a_run_writes_its_results_where_it_was_invoked_not_beside_the_tasks():
    # An installed plugin's copy is erased on reinstall. A report written beside the tasks is
    # a report the user loses the first time they update.
    out = subprocess.run(
        [
            "bash",
            "-x",
            str(SCRIPT),
            "run",
            "--agent",
            "null",
            "--task",
            "n2_beta_solar_wind",
            "--runs",
            "1",
        ],
        cwd="/tmp",
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stderr
    assert "/tmp/heliobench-results" in out.stderr + out.stdout


def test_an_explicit_out_still_wins(tmp_path):
    out = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "run",
            "--agent",
            "null",
            "--task",
            "n2_beta_solar_wind",
            "--runs",
            "1",
            "--out",
            str(tmp_path / "mine"),
        ],
        cwd="/tmp",
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "mine").is_dir()


def _fake_plugin_copy(root: Path) -> Path:
    """A tree shaped like an installed plugin: the tasks and the launcher, and a `.venv` whose
    interpreter symlink no longer resolves — which is what a copied virtualenv looks like."""
    skill = root / ".claude/skills/heliobench/scripts"
    skill.mkdir(parents=True)
    (skill / "heliobench.sh").write_bytes(SCRIPT.read_bytes())
    (skill / "heliobench.sh").chmod(0o755)
    venv_bin = root / ".venv/bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(root / "nowhere/python")
    (venv_bin / "heliobench").write_text("#!/does/not/exist\n")
    (venv_bin / "heliobench").chmod(0o755)
    return skill / "heliobench.sh"


def test_a_copied_virtualenv_is_refused_instead_of_silently_running_another_repo(tmp_path):
    # Installing from a local path copies `.venv` too, and the copied console scripts keep an
    # absolute shebang pointing back at the original repo. Trusting them would run the live
    # repo's code against the snapshot's tasks and report it as the snapshot's commit.
    launcher = _fake_plugin_copy(tmp_path / "plugin")
    out = subprocess.run(
        ["bash", str(launcher), "list"],
        cwd="/tmp",
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 127
    assert "HELIOBENCH_PYTHON" in out.stderr


def test_an_explicit_interpreter_overrides_everything(tmp_path):
    launcher = _fake_plugin_copy(tmp_path / "plugin2")
    (tmp_path / "plugin2" / "tasks").mkdir()
    out = subprocess.run(
        ["bash", str(launcher), "list"],
        cwd="/tmp",
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "HELIOBENCH_PYTHON": sys.executable},
    )
    assert out.returncode == 0, out.stderr
    assert "no tasks found" in out.stdout
