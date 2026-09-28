"""Tiers n2 and n3: is the number right?

Two rules decide almost every disputed verdict here.

A number is only compared when its unit agrees. A compression ratio of 2.53 and a field of
2.53 nT are not the same claim, and a grader that treats them as one produces its loudest
findings on its own confusion.

An angle is compared in degrees, never in percent. Five percent of 89° is 4.5°, which passes
almost anything; five percent of 2° is 0.1°, which passes almost nothing. Tolerances for
angles are absolute, and the task file has to say so.

Units are folded, never scaled: `0.56 kHz` is not read as 560 Hz, and `0.235 km` is not a
Debye length asked for in metres. Every prompt names the unit it wants, and converting would
make the grader decide what the agent meant.
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
    "/cm^3": "cm-3",
    "#/cm3": "cm-3",
    "#/cm^3": "cm-3",
    "/cc": "cm-3",
    "#/cc": "cm-3",
    "n/cc": "cm-3",
    "p/cc": "cm-3",
    "per cc": "cm-3",
    "cm-3": "cm-3",
    "r_e": "re",
    "re": "re",
    "°": "deg",
    "degrees": "deg",
    "degree": "deg",
    "deg": "deg",
    "km s-1": "km/s",
    "kms-1": "km/s",
    "km s^-1": "km/s",
    "kms^-1": "km/s",
    "km·s^-1": "km/s",
    "km/sec": "km/s",
    "metres": "m",
    "meters": "m",
    "metre": "m",
    "meter": "m",
    "kilometres": "km",
    "kilometers": "km",
    "kilometre": "km",
    "kilometer": "km",
    "nanotesla": "nt",
    "hertz": "hz",
}

# Longest spellings first: `km/s` must win over `km`, and `km` over `m`, or a speed is
# read as a length. The trailing lookahead is what keeps `5 mol` from parsing as 5 metres.
# Units no task asks for (durations) are listed so that a duration is read as one: unlisted,
# `5 min` was a bare 5, and a bare number is what a ratio or a Mach number is graded against.
_UNIT_PATTERN = (
    r"km s\^-1|kms\^-1|km·s\^-1|km s-1|kms-1|km/sec|km/s|"
    r"cm\^-3|cm\*\*-3|cm-3|cm⁻³|#/cm\^3|#/cm3|/cm\^3|/cm3|#/cc|n/cc|p/cc|per cc|/cc|"
    r"nanotesla|nT|pT|nPa|keV|MeV|eV|kK|MK|hertz|Hz|mHz|kHz|R_E|RE|Re|degrees|degree|deg|°|%|"
    r"kilometres|kilometers|kilometre|kilometer|km|metres|meters|metre|meter|"
    r"minutes|minute|mins|min|seconds|second|secs|sec|hours|hour|hrs|hr|days|day|UTC|UT|"
    r"m|K|s|h"
)
# Read so that a duration is not a bare number; never a unit a task is graded in.
DURATION_UNITS = frozenset(
    "minutes minute mins min seconds second secs sec hours hour hrs hr days day UTC UT s h".split()
)

# A sign only where nothing numeric precedes it, so `400-450 km/s` is a range and not 400
# and −450; digits grouped by commas in threes; an exponent written `e-3` or `× 10^-3`.
_MANTISSA = r"(?<![\w.,])(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?)"
_TIMES_TEN = r"(?:\s*[×x·*]\s*10\^\(?([-+]?\d+)\)?)?"
_NUMBER = re.compile(rf"{_MANTISSA}{_TIMES_TEN}\s*({_UNIT_PATTERN})?(?![\w/^-])")

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
# ISO dates and clock times are not quantities: blanked before any number is read, so that
# `2015-03-17` is not read as three numbers, nor `08:30 UT` as two.
_DATETIME = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?)?"
    r"|(?<![\d.])\d{1,2}:\d{2}(?::\d{2})?(?![\d.])"
)
_LATEX = (
    (re.compile(r"\\(?:mathrm|text|rm|textrm|operatorname)\s*\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\^\{([^{}]*)\}"), r"^\1"),
    (re.compile(r"\\(?:,|;|:|!| |quad|qquad)"), " "),
    (re.compile(r"\\times"), "×"),
    (re.compile(r"\\cdot"), "·"),
    (re.compile(r"\\(?:approx|sim|simeq)"), "~"),
    (re.compile(r"\\(?:circ|degree)"), "°"),
    (re.compile(r"\$"), " "),
)


def normalise(text: str) -> str:
    """The reply with its typography folded onto one spelling.

    Every rule here is a defensible answer the parser used to reject or misread: `87.5 km
    s⁻¹` (nothing), `2.351e2 m` (2.0 m), `86,066 m` (66 m), `400-450 km/s` (−450), LaTeX
    `\\mathrm{km/s}` (nothing), `235.1 metres` (nothing). Positions — and so the `near`
    windows — refer to the normalised text.
    """
    text = (text or "").replace("−", "-").replace("≈", "~").replace("–", "-")
    for space in ("\u00a0", "\u202f", "\u2009", "\u2005"):
        text = text.replace(space, " ")
    for pattern, repl in _LATEX:
        text = pattern.sub(repl, text)
    text = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+", lambda m: "^" + m.group(0).translate(_SUPERSCRIPT), text)
    # Markdown bold is not an exponent: `**87.5 km/s**` must not read as `** 87.5`.
    text = re.sub(r"(?<!cm)\*\*", "  ", text)
    return _DATETIME.sub(lambda m: " " * len(m.group(0)), text)


def parse(m: re.Match) -> tuple[str, float, str]:
    """`(spelling, value, unit)` of one `_NUMBER` match.

    The spelling keeps the precision the reply claimed, with a `× 10^n` folded into an `e`
    exponent, so `provenance._tolerance` can read the rounding it allows.
    """
    mantissa, exponent, unit = m.group(1), m.group(2), m.group(3) or ""
    raw = mantissa.replace(",", "")
    if exponent is not None:
        raw = f"{raw}e{int(exponent)}"
    return raw, float(raw), unit


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


def _near_pattern(word: str) -> re.Pattern:
    """`word` as a whole token of the lowercased reply.

    A substring match made `di` match *distance* and *indicates* and `va` match *value*, so
    the keyword window covered most replies. Letters and digits bound a token; `_` and `|` do
    not, so `v_a` and `|b|` still match themselves.
    """
    return re.compile(rf"(?<![a-z0-9]){re.escape(word.lower())}(?![a-z0-9])")


def candidates_with_text(text: str, units: str, near: list[str] | None) -> list[tuple[str, float]]:
    """`candidates`, keeping the spelling each number had in the reply.

    The spelling carries the precision the agent claimed — `571` and `571.07` are the same
    float and different claims — and the provenance check needs it to know how much rounding
    a match may absorb.
    """
    text = normalise(text)
    windows: list[tuple[int, int]] = []
    if near:
        low = text.lower()
        for word in near:
            for m in _near_pattern(word).finditer(low):
                windows.append((m.start() - 120, m.end() + 120))

    out: list[tuple[str, float]] = []
    for m in _NUMBER.finditer(text):
        try:
            raw, value, unit = parse(m)
        except ValueError:
            continue
        if not same_unit(unit, units):
            continue
        if windows and not any(a <= m.start() <= b for a, b in windows):
            continue
        out.append((raw, value))
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
