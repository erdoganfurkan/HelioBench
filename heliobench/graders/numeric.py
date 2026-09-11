"""Tiers n2 and n3: is the number right?

Two rules decide almost every disputed verdict here.

A number is only compared when its unit agrees. A compression ratio of 2.53 and a field of
2.53 nT are not the same claim, and a grader that treats them as one produces its loudest
findings on its own confusion.

An angle is compared in degrees, never in percent. Five percent of 89° is 4.5°, which passes
almost anything; five percent of 2° is 0.1°, which passes almost nothing. Tolerances for
angles are absolute, and the task file has to say so.
"""

from __future__ import annotations

import re

from heliobench.graders import Result
from heliobench.tasks import Task
from heliobench.trace import Trace

_UNIT_ALIASES = {
    "cm⁻³": "cm-3",
    "cm^-3": "cm-3",
    "cm**-3": "cm-3",
    "/cm3": "cm-3",
    "#/cc": "cm-3",
    "n/cc": "cm-3",
    "cm-3": "cm-3",
    "r_e": "re",
    "re": "re",
    "°": "deg",
    "degrees": "deg",
    "degree": "deg",
    "deg": "deg",
    "km s-1": "km/s",
    "kms-1": "km/s",
}

# Longest spellings first: `km/s` must win over `km`, and `km` over `m`, or a speed is
# read as a length. The trailing lookahead is what keeps `5 min` from parsing as 5 metres.
_UNIT_PATTERN = (
    r"km/s|km s-1|kms-1|cm\^?-3|cm\*\*-3|cm-3|cm⁻³|/cm3|#/cc|n/cc|"
    r"nT|pT|nPa|keV|MeV|eV|kK|MK|Hz|mHz|kHz|R_E|RE|Re|degrees|deg|°|%|km|m|K"
)
_NUMBER = re.compile(rf"(-?\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})?(?![\w/^-])")


def canonical_unit(u: str) -> str:
    """Fold the spellings of one unit onto a single token. Unitless stays unitless."""
    u = (u or "").strip()
    return _UNIT_ALIASES.get(u.lower(), u)


def same_unit(a: str, b: str) -> bool:
    """Whether two unit strings denote the same quantity."""
    return canonical_unit(a).lower() == canonical_unit(b).lower()


def _within(found: float, want: float, tol: dict) -> bool:
    if "abs" in tol:
        return abs(found - want) <= float(tol["abs"])
    rel = float(tol.get("rel", 0.05))
    return abs(found - want) <= rel * max(abs(want), 1e-12)


def candidates_with_text(text: str, units: str, near: list[str] | None) -> list[tuple[str, float]]:
    """`candidates`, keeping the spelling each number had in the reply.

    The spelling carries the precision the agent claimed — `571` and `571.07` are the same
    float and different claims — and the provenance check needs it to know how much rounding
    a match may absorb.
    """
    text = (text or "").replace("−", "-").replace("≈", "~")
    windows: list[tuple[int, int]] = []
    if near:
        low = text.lower()
        for word in near:
            for m in re.finditer(re.escape(word.lower()), low):
                windows.append((m.start() - 120, m.end() + 120))

    out: list[tuple[str, float]] = []
    for m in _NUMBER.finditer(text):
        raw, unit = m.group(1), (m.group(2) or "")
        if not same_unit(unit, units):
            continue
        if windows and not any(a <= m.start() <= b for a, b in windows):
            continue
        try:
            out.append((raw, float(raw)))
        except ValueError:
            continue
    return out


def candidates(text: str, units: str, near: list[str] | None) -> list[float]:
    """Numbers in `text` that carry a compatible unit, optionally close to a keyword.

    `near` is the defence against a lucky substring: a reply full of numbers will eventually
    contain the right one by accident, and requiring it to sit beside the words naming the
    quantity is what separates an answer from a coincidence.
    """
    return [v for _, v in candidates_with_text(text, units, near)]


def grade(task: Task, trace: Trace) -> Result:
    """Pass when the answer states a number of the right magnitude, in the right unit."""
    if "value" not in task.expected:
        return Result(task.id, False, "task declares no expected value")
    want = float(task.expected["value"])
    units = task.expected.get("units", "")
    near = task.expected.get("near") or []
    tol = task.tolerance or {"rel": 0.05}

    pairs = candidates_with_text(trace.reply, units, near)
    found = [v for _, v in pairs]
    detail = {"want": want, "units": units, "tolerance": tol, "found": found}
    if not found:
        return Result(task.id, False, "no number with the expected unit in the answer", detail)
    hit_pairs = [(raw, v) for raw, v in pairs if _within(v, want, tol)]
    hits = [v for _, v in hit_pairs]
    detail["hits"] = hits
    detail["hits_text"] = [raw for raw, _ in hit_pairs]
    if not hits:
        return Result(task.id, False, f"closest {min(found, key=lambda v: abs(v - want))}", detail)
    return Result(task.id, True, "", detail)
