"""Does the answer state the number the session computed, or a different one?

Until now the one hard gate in the benchmark — a run whose answer contradicts its own
provenance ledger fails — read a counter the agent under test computed about itself. An agent
that loosened its own detector would pass the gate unnoticed. This module recomputes the
verdict from the two things a trace stores and the agent cannot rewrite after the fact: the
ledger of values its computations exported, and the reply it gave.

What the stored runs taught, and what this module does because of it:

**Match against the whole ledger before attributing anything.** The agent's detector matched
a number to the nearest ledger *name* first and asked whether it agreed second, so a component
of a vector read as contradicting the vector's scalar summary, and a magnitude read as
contradicting its own components. Here a number that equals any ledger value — a scalar, a
reconstructed vector component, a vector magnitude, or the difference or ratio of two scalars
— is sourced, whatever it sits next to. `161 km/s` beside `shock_speed_km_s = 571` is not a
contradiction: it is `571 − 410`, and both are in the ledger.

**A ledger entry is a 3-vector when its (min, mean, max, std) say so.** The ledger stores a
summary, not the array, but for three components the summary is invertible: the middle one is
`3·mean − min − max`, and the std of the three must come out right. All 48 vector entries in
the stored n3 traces reconstruct exactly.

**Prose cannot be gated; the graded answer can.** Every rule tried for reading a
contradiction out of the reply's running text — name within N characters, same unit, within a
quarter of the ledger value — flagged only correct runs across the 236 stored n3 traces: range
endpoints, literature values, inputs restated beside the result. So the prose classification
here has three classes, matched / derived / unsourced, and is reported, not gated. The gate
reads the number the numeric grader accepted as the answer: if that number is not in the
ledger and not derivable from it, while the ledger holds a same-unit scalar within a quarter
of it, the session computed one value and the reply stated another. That is the only reading
of the gate that the stored evidence supports.

Numbers that also appear in the prompt are the question's inputs, not the answer's claims,
and are ignored.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from heliobench.graders.numeric import _NUMBER, canonical_unit

# How far from a ledger scalar the graded answer may sit and still be read as another value
# for the same quantity. Beyond it, it is a different quantity and merely unsourced.
NEAR_MISS = 0.25


@dataclass
class Sourced:
    """One ledger-derived value a reply could be quoting."""

    value: float
    units: str
    name: str
    kind: str  # scalar | component | magnitude | stat | difference | ratio

    @property
    def direct(self) -> bool:
        return self.kind not in ("difference", "ratio")


@dataclass
class Provenance:
    """Attributes:
    matched: numbers in the reply equal to a ledger value.
    derived: numbers equal to a difference or ratio of two ledger scalars.
    unsourced: everything else the reply states that no computation produced.
    answer_sourced: whether every graded answer value is matched or derived.
    answer_contradicted: graded answer values the ledger holds a different value for.
    """

    matched: int = 0
    derived: int = 0
    unsourced: int = 0
    details: list[dict] = field(default_factory=list)
    answer_sourced: bool | None = None
    answer_contradicted: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "matched": self.matched,
            "derived": self.derived,
            "unsourced": self.unsourced,
            "answer_sourced": self.answer_sourced,
            "answer_contradicted": self.answer_contradicted,
        }


def _is_vector3(entry: dict) -> tuple[float, float, float] | None:
    """The three components of a ledger entry that summarises a 3-vector, else None."""
    try:
        lo, hi, mean, std = (float(entry[k]) for k in ("min", "max", "mean", "std"))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in (lo, hi, mean, std)) or lo == hi:
        return None
    mid = 3 * mean - lo - hi
    if not lo <= mid <= hi:
        return None
    comps = (lo, mid, hi)
    m = sum(comps) / 3
    want = math.sqrt(sum((c - m) ** 2 for c in comps) / 3)
    if abs(want - std) > 1e-6 * max(1.0, abs(std)):
        return None
    return comps


def sources(ledger: dict) -> list[Sourced]:
    """Every number a reply could legitimately be quoting from the ledger."""
    out: list[Sourced] = []
    scalars: list[Sourced] = []
    for e in (ledger or {}).get("values", []) or []:
        name, units = str(e.get("name", "")), canonical_unit(str(e.get("units", "") or ""))
        try:
            lo, hi, mean = float(e["min"]), float(e["max"]), float(e["mean"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(mean):
            continue
        if lo == hi:
            s = Sourced(mean, units, name, "scalar")
            out.append(s)
            scalars.append(s)
            continue
        comps = _is_vector3(e)
        if comps:
            out += [Sourced(c, units, name, "component") for c in comps]
            out.append(Sourced(math.sqrt(sum(c * c for c in comps)), units, name, "magnitude"))
            continue
        out += [Sourced(v, units, name, "stat") for v in (mean, lo, hi)]
    for i, a in enumerate(scalars):
        for b in scalars[i + 1 :]:
            if a.units == b.units:
                out.append(
                    Sourced(abs(a.value - b.value), a.units, f"{a.name}-{b.name}", "difference")
                )
            if b.value:
                out.append(Sourced(a.value / b.value, "", f"{a.name}/{b.name}", "ratio"))
            if a.value:
                out.append(Sourced(b.value / a.value, "", f"{b.name}/{a.name}", "ratio"))
    return out


def _tolerance(text: str) -> float:
    """Half a unit in the last printed place: what rounding to those digits can hide."""
    decimals = len(text.split(".")[1]) if "." in text else 0
    return 0.5 * 10.0**-decimals * 1.001 + 1e-12


def _unit_ok(claim_unit: str, source_unit: str) -> bool:
    return not claim_unit or not source_unit or claim_unit == source_unit


def _find(pool: list[Sourced], value: float, tol: float, unit: str, direct: bool) -> Sourced | None:
    return next(
        (
            s
            for s in pool
            if s.direct == direct and _unit_ok(unit, s.units) and abs(s.value - value) <= tol
        ),
        None,
    )


def classify_prose(reply: str, ledger: dict, prompt: str = "") -> Provenance:
    """Sort every number the reply states into matched, derived or unsourced."""
    pool = sources(ledger)
    given = set(re.findall(r"-?\d+(?:\.\d+)?", prompt or ""))
    text = (reply or "").replace("−", "-").replace("≈", "~")
    p = Provenance()
    for m in _NUMBER.finditer(text):
        raw, unit = m.group(1), canonical_unit(m.group(2) or "")
        if unit == "%" or raw in given:
            continue
        # A bare integer with no unit is a date, a count or an index far more often than a
        # result; it is not counted at all rather than swelling `unsourced`.
        if "." not in raw and not unit:
            continue
        value, tol = float(raw), _tolerance(raw)
        if hit := _find(pool, value, tol, unit, direct=True):
            p.matched += 1
            p.details.append({"text": m.group(0), "status": "matched", "name": hit.name})
        elif hit := _find(pool, value, tol, unit, direct=False):
            p.derived += 1
            p.details.append({"text": m.group(0), "status": "derived", "name": hit.name})
        else:
            p.unsourced += 1
            p.details.append({"text": m.group(0), "status": "unsourced", "name": None})
    return p


def check_answer(
    values: list[float], units: str, ledger: dict, texts: list[str] | None = None
) -> Provenance:
    """Hold the graded answer to the ledger.

    `values` are the numbers the numeric grader accepted as the answer, `units` the task's
    unit, `texts` the spellings they had in the reply (for the rounding tolerance; absent,
    the tolerance is that of two decimals). Returns a Provenance with only the answer fields
    set.

    The answer is sourced when *any* accepted value is in the ledger or derivable from it: a
    reply that states the computed mean and, beside it, the window's median or a literature
    value is a reply that stated the number the session produced. It is contradicted only
    when none of them is, and one sits within a quarter of a same-unit ledger scalar — the
    session computed one value and the reply stated another. With an empty ledger nothing was
    computed, so nothing can be contradicted and `answer_sourced` is None rather than False.
    """
    pool = sources(ledger)
    p = Provenance()
    if not pool or not values:
        return p
    unit = canonical_unit(units)
    near_misses: list[dict] = []
    for i, v in enumerate(values):
        tol = _tolerance(texts[i]) if texts and i < len(texts) else _tolerance("0.00")
        if _find(pool, v, tol, unit, True) or _find(pool, v, tol, unit, False):
            p.answer_sourced = True
            return p
        near = [
            s
            for s in pool
            if s.kind == "scalar"
            and s.units == unit
            and s.value
            and abs(v - s.value) / abs(s.value) <= NEAR_MISS
        ]
        if near:
            closest = min(near, key=lambda s: abs(s.value - v))
            near_misses.append(
                {"stated": v, "computed": closest.value, "name": closest.name, "units": unit}
            )
    p.answer_sourced = False
    p.answer_contradicted = near_misses
    return p
