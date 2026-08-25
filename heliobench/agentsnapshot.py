"""Run the benchmark against a pinned remote commit of the agent, in an isolated venv.

`--agent-ref <branch|tag|commit>` on ``run`` and ``verify`` resolves the ref to a commit,
builds (once) a dedicated virtualenv with ``helioai-agent`` installed at exactly that commit,
and replaces this process with a re-run of the same CLI inside that venv. The agent under
test then comes from the pinned package instead of whatever ``helioai-agent`` happens to be
installed in the harness venv — which is the failure mode in ``dev/lessons.md``: a fix is not
measured until the version that contains it is the one the harness imports.

The harness code rides along unchanged: ``PYTHONPATH`` is prepended with the directory that
provides the ``heliobench`` package in this process, so the re-executed CLI grades with the
same snapshot it was invoked from. The working directory is preserved, so relative
``--tasks-dir``/``--fixtures``/``--out`` still resolve. The resolved commit is recorded in
``HELIOBENCH_AGENT_REF`` and lands in the report header as ``agent_ref``.

The search index is *not* provisioned here — it stays the caller's job via ``--index-dir``,
and its versioning relative to the commit is the caller's concern too.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = "https://github.com/erdoganfurkan/HelioAI"

AGENT_REF_ENV = "HELIOBENCH_AGENT_REF"

_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")


class AgentRefError(RuntimeError):
    """The requested agent ref could not be resolved or installed."""


def _cache_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(root) / "heliobench"


def _looks_like_sha(ref: str) -> bool:
    return bool(_SHA.fullmatch(ref))


def _parse_ls_remote(stdout: str) -> list[str]:
    """Commit shas out of ``git ls-remote``, preferring dereferenced tag lines.

    An annotated tag appears twice — the tag object and the ``^{}`` commit it points at. The
    commit is what must be installed; the tag object sha would check out the tag's own tree.
    """
    deref: list[str] = []
    plain: list[str] = []
    for line in stdout.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        sha, refname = line.split("\t", 1)
        (deref if refname.endswith("^{}") else plain).append(sha.strip())
    return deref or plain


def resolve_ref(ref: str, repo: str = REPO) -> str:
    """Turn a branch/tag name into a commit sha; pass an already-commit-shaped ref through."""
    if _looks_like_sha(ref):
        return ref
    proc = subprocess.run(["git", "ls-remote", repo, ref], capture_output=True, text=True)
    if proc.returncode != 0:
        raise AgentRefError(
            f"cannot resolve ref {ref!r} against {repo}: {proc.stderr.strip() or 'unknown error'}"
        )
    shas = _parse_ls_remote(proc.stdout)
    if not shas:
        raise AgentRefError(f"ref {ref!r} not found on {repo}")
    return shas[0]


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def ensure_venv(sha: str, repo: str = REPO) -> Path:
    """Return the python of a venv with ``helioai-agent`` installed at exactly ``sha``.

    Cached by sha, so a commit is built once and reused. numpy and pyyaml are installed
    explicitly: the harness runs in this venv too, and its runtime contract must not depend on
    the agent's transitive dependencies happening to satisfy it.
    """
    venv_dir = _cache_dir() / "agents" / sha / ".venv"
    venv_py = _venv_python(venv_dir)
    if venv_py.is_file():
        return venv_py

    uv = shutil.which("uv")
    if uv is None:
        raise AgentRefError(
            "uv is required to build an agent snapshot; install it (https://docs.astral.sh/uv/)"
        )

    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([uv, "venv", str(venv_dir)], check=True)
    try:
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(venv_py),
                "numpy",
                "pyyaml",
                f"helioai-agent @ git+{repo}@{sha}",
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        shutil.rmtree(venv_dir, ignore_errors=True)
        raise AgentRefError(
            f"failed to install helioai-agent at {sha}: uv exited {e.returncode}"
        ) from e
    return venv_py


def _harness_parent() -> Path:
    """Directory providing the ``heliobench`` package in this process.

    For an editable install this is the repository; for a plugin snapshot it is the snapshot
    tree. Either way, prepending it to ``PYTHONPATH`` makes the re-executed CLI grade with the
    same harness code the user invoked.
    """
    import heliobench

    return Path(heliobench.__file__).resolve().parent.parent


def build_env(sha: str) -> dict:
    """Environment for the re-run: the resolved commit, and the harness on ``sys.path``."""
    env = os.environ.copy()
    env[AGENT_REF_ENV] = sha
    harness = str(_harness_parent())
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = harness if not existing else f"{harness}{os.pathsep}{existing}"
    return env


def _strip_agent_ref(argv: list[str]) -> list[str]:
    """Remove ``--agent-ref`` (both ``--flag value`` and ``--flag=value`` forms) from argv."""
    out: list[str] = []
    it = iter(argv)
    for token in it:
        if token == "--agent-ref":
            next(it, None)
            continue
        if token.startswith("--agent-ref="):
            continue
        out.append(token)
    return out


def exec_in(venv_py: Path, argv: list[str], sha: str) -> None:
    """Replace this process with the same CLI run inside the pinned venv."""
    os.execve(
        str(venv_py),
        [str(venv_py), "-m", "heliobench.cli", *_strip_agent_ref(argv)],
        build_env(sha),
    )


def prepare(ref: str, argv: list[str], repo: str = REPO) -> None:
    """Resolve ``ref``, build its venv, and re-run the CLI inside it. Does not return."""
    sha = resolve_ref(ref, repo)
    venv_py = ensure_venv(sha, repo)
    exec_in(venv_py, argv, sha)
    raise AgentRefError(
        "agent snapshot preparation did not replace the process"
    )  # pragma: no cover
