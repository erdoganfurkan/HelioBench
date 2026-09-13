"""Derive tier-n3 ground truth from a frozen fixture, using the frozen recipe functions.

The truth is computed from the fixture, not from a catalogue. That is deliberate: a catalogue
value depends on whoever produced it and on which method they used, while a number derived
from frozen bytes by a named method is reproducible by anyone, forever, and disagreeing with
it is a disagreement about arithmetic rather than about physics.

Both halves of that claim now live in this repository. The recipes are the byte-for-byte
copies under `heliobench/recipes/`, hash-checked against the upstream commit they were taken
from; the windows are `fixtures/<event>/windows.json`, written when the fixture was built.
Nothing here reaches outside the checkout.

    python scripts/reference_values.py stpatrick_2015            # writes reference.json
    python scripts/reference_values.py stpatrick_2015 --check    # compares, writes nothing
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from heliobench.recipes import namespace  # noqa: E402

FIXTURES = REPO / "fixtures"


def load(fixture: Path, name: str):
    d = np.load(fixture / "data" / f"{name}.npz")
    return d["time"], d["values"].astype(float)


def window_mean(fixture: Path, name: str, lo, hi) -> float:
    t, v = load(fixture, name)
    sel = (t >= lo) & (t <= hi)
    return float(np.nanmean(v[sel]))


def vector_mean(fixture: Path, name: str, lo, hi) -> np.ndarray:
    t, v = load(fixture, name)
    sel = (t >= lo) & (t <= hi)
    return np.nanmean(v[sel], axis=0)


def magnitude_mean(fixture: Path, name: str, lo, hi) -> float:
    t, v = load(fixture, name)
    sel = (t >= lo) & (t <= hi)
    return float(np.nanmean(np.linalg.norm(v[sel], axis=1)))


def derive(event: str) -> dict:
    """Every reference value for one event, from its frozen bytes and stated windows."""
    fixture = FIXTURES / event
    win = json.loads((fixture / "windows.json").read_text(encoding="utf-8"))
    up = tuple(np.datetime64(s) for s in win["upstream"])
    down = tuple(np.datetime64(s) for s in win["downstream"])
    field, dens, speed, therm = (
        win["field"],
        win["density"],
        win["speed"],
        win["thermal_speed"],
    )

    theta_bn = namespace("theta_bn")["theta_bn"]
    rh = namespace("rankine_hugoniot")

    B_up, B_dn = vector_mean(fixture, field, *up), vector_mean(fixture, field, *down)
    tb = theta_bn(B_up, B_dn)

    n_u, n_d = window_mean(fixture, dens, *up), window_mean(fixture, dens, *down)
    v_u, v_d = window_mean(fixture, speed, *up), window_mean(fixture, speed, *down)
    w_u, w_d = window_mean(fixture, therm, *up), window_mean(fixture, therm, *down)
    b_u, b_d = magnitude_mean(fixture, field, *up), magnitude_mean(fixture, field, *down)

    # Wind SWE reports a thermal speed; the recipe wants a temperature **in eV**. Its own
    # self-check pins the unit: it passes T_u=8.34 for the event the showcase notebook
    # records as 96.8 kK, and 96.8 kK is 8.34 eV. Feeding it kK leaves the Alfven Mach
    # number untouched — it does not depend on temperature — while quietly halving the
    # MHD-predicted compression, which is how the mistake was caught.
    m_p, q_e = 1.67262192e-27, 1.602176634e-19
    T_u = m_p * (w_u * 1e3) ** 2 / (2 * q_e)  # eV
    T_d = m_p * (w_d * 1e3) ** 2 / (2 * q_e)

    jump = rh["_rh_core"](n_u=n_u, n_d=n_d, V_u=v_u, V_d=v_d, B_u=b_u, B_d=b_d, T_u=T_u, T_d=T_d)

    out = {
        "windows": {
            "shock": win["shock"],
            "upstream": list(win["upstream"]),
            "downstream": list(win["downstream"]),
        },
        "b_up_nT": round(b_u, 4),
        "b_dn_nT": round(b_d, 4),
        "n_up_cm3": round(n_u, 4),
        "n_dn_cm3": round(n_d, 4),
        "v_up_km_s": round(v_u, 4),
        "v_dn_km_s": round(v_d, 4),
        "w_up_km_s": round(w_u, 4),
        "T_up_eV": round(T_u, 4),
        "density_compression": round(n_d / n_u, 4),
        "field_compression": round(b_d / b_u, 4),
        "theta_bn_deg": round(float(tb["theta_bn_deg"]), 4),
        "B_up_vec_nT": [round(float(x), 4) for x in B_up],
        "B_dn_vec_nT": [round(float(x), 4) for x in B_dn],
    }
    for k in ("r", "V_shock", "V_A", "M_A", "U_upstream", "r_predicted"):
        if k in jump:
            out[f"rh_{k}"] = round(float(jump[k]), 4)
    return out


def main(argv: list[str]) -> int:
    event = next((a for a in argv if not a.startswith("--")), "stpatrick_2015")
    out = derive(event)
    path = FIXTURES / event / "reference.json"
    if "--check" in argv:
        stored = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        if stored == out:
            print(f"{path} reproduces from the frozen bytes and recipes")
            return 0
        print(f"{path} DIFFERS from what the frozen bytes and recipes derive:", file=sys.stderr)
        for k in sorted(set(stored or {}) | set(out)):
            if (stored or {}).get(k) != out.get(k):
                print(f"  {k}: stored {(stored or {}).get(k)!r} derived {out.get(k)!r}")
        return 1
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
