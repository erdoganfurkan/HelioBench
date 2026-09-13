"""The recipe functions that derive tier-n3 ground truth, frozen here.

`scripts/reference_values.py` used to exec these out of `/home/furkan/HelioAI/...` — an
absolute path on one machine, under a claim that the truth was "reproducible by anyone,
forever". It was not, while that line stood. The files in this directory are byte-for-byte
copies of the upstream recipes at the commits recorded in `MANIFEST`, and a test checks the
hash of each against it, so a drive-by edit here is caught rather than silently changing
what the benchmark calls true.

They are exec'd rather than imported, as before: each ships a runnable tail that calls the
sandbox's `export`, which does not exist out here, and the tails carry their own assertions
against archived values — letting them run is a free check that the frozen recipe still
agrees with the numbers it was calibrated on.

Ruff is told to leave this directory alone (`extend-exclude` in `pyproject.toml`). A
reformatted copy would compute the same thing and hash differently, and the hash is the
point.

Upstream: https://github.com/erdoganfurkan/HelioAI, `helioai/data/recipes/`, MIT.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent

# name -> (upstream commit that last touched the file, sha256 of the frozen copy)
MANIFEST: dict[str, tuple[str, str]] = {
    "theta_bn": (
        "d1c2ea232280e1400d0efcffa64b82d714bd53da",
        "db60b7501597fe2d00bf20d069f4285c58c9fd087be0585d23e7497fa54927bc",
    ),
    "rankine_hugoniot": (
        "d4c5a38203b2f70e345eb4f951fa2262ce9ca370",
        "5d10cb360606331b375a29a77225482a2df5d585bedacdafe1a179f78df88473",
    ),
}


class RecipeError(RuntimeError):
    """A frozen recipe that is not the bytes the manifest says it is."""


def path(name: str) -> Path:
    return HERE / f"{name}.py"


def digest(name: str) -> str:
    return hashlib.sha256(path(name).read_bytes()).hexdigest()


def verify(name: str) -> None:
    """Raise unless the frozen file hashes to what `MANIFEST` records."""
    if name not in MANIFEST:
        raise RecipeError(f"no frozen recipe named {name!r}")
    want = MANIFEST[name][1]
    got = digest(name)
    if got != want:
        raise RecipeError(f"{name}.py hashes to {got}, manifest says {want}: edited or corrupt")


def namespace(name: str, *, quiet: bool = True) -> dict:
    """Execute a frozen recipe and return its namespace, with `export` stubbed out.

    The recipe's runnable tail prints its placeholder result; `quiet` swallows that so a
    caller deriving reference values does not get the placeholder in its output.
    """
    verify(name)
    ns: dict = {"export": lambda *a, **k: None}
    if quiet:
        ns["print"] = lambda *a, **k: None
    exec(compile(path(name).read_text(encoding="utf-8"), f"{name}.py", "exec"), ns)
    return ns
