"""Derive tier-n3 ground truth from the frozen fixture, using the shipped recipe functions.

The truth is computed from the fixture, not from a catalogue. That is deliberate: a catalogue
value depends on whoever produced it and on which method they used, while a number derived
from frozen bytes by a named method is reproducible by anyone, forever, and disagreeing with
it is a disagreement about arithmetic rather than about physics.

The recipes are exec'd rather than imported: each ships a runnable tail that calls the
sandbox's `export`, which does not exist out here. The tails also carry their own assertions
against archived values, and letting them run is a free check that the recipe still agrees
with the numbers it was calibrated on.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "fixtures" / "stpatrick_2015" / "data"
RECIPES = Path("/home/furkan/HelioAI/helioai/data/recipes")

# The windows are part of the task statement, not a choice made here. A shock normal computed
# over an unstated interval is not reproducible, and the spread over plausible intervals is
# wider than any tolerance worth quoting.
SHOCK = np.datetime64("2015-03-17T04:00:59")
UP = (np.datetime64("2015-03-17T03:35:59"), np.datetime64("2015-03-17T03:55:59"))
DOWN = (np.datetime64("2015-03-17T04:05:59"), np.datetime64("2015-03-17T04:25:59"))


def load(name: str):
    d = np.load(FIXTURE / f"{name}.npz")
    return d["time"], d["values"].astype(float)


def window_mean(name: str, lo, hi, column: int | None = None) -> float:
    t, v = load(name)
    sel = (t >= lo) & (t <= hi)
    block = v[sel] if column is None else v[sel, column : column + 1]
    return float(np.nanmean(block))


def vector_mean(name: str, lo, hi) -> np.ndarray:
    t, v = load(name)
    sel = (t >= lo) & (t <= hi)
    return np.nanmean(v[sel], axis=0)


def magnitude_mean(name: str, lo, hi) -> float:
    t, v = load(name)
    sel = (t >= lo) & (t <= hi)
    return float(np.nanmean(np.linalg.norm(v[sel], axis=1)))


def recipe(name: str) -> dict:
    """Execute a shipped recipe and return its namespace, with `export` stubbed out."""
    ns: dict = {"export": lambda *a, **k: None}
    exec(compile((RECIPES / f"{name}.py").read_text(), f"{name}.py", "exec"), ns)
    return ns


def main() -> dict:
    theta_bn = recipe("theta_bn")["theta_bn"]
    rh = recipe("rankine_hugoniot")

    B_up, B_dn = vector_mean("bgsm", *UP), vector_mean("bgsm", *DOWN)
    tb = theta_bn(B_up, B_dn)

    n_u, n_d = window_mean("proton_np_moment", *UP), window_mean("proton_np_moment", *DOWN)
    v_u, v_d = window_mean("proton_v_moment", *UP), window_mean("proton_v_moment", *DOWN)
    w_u, w_d = window_mean("proton_w_moment", *UP), window_mean("proton_w_moment", *DOWN)
    b_u, b_d = magnitude_mean("bgsm", *UP), magnitude_mean("bgsm", *DOWN)

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
            "shock": str(SHOCK),
            "upstream": [str(UP[0]), str(UP[1])],
            "downstream": [str(DOWN[0]), str(DOWN[1])],
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

    path = REPO / "fixtures" / "stpatrick_2015" / "reference.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    main()
