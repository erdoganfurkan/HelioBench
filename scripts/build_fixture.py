"""Freeze one event's data so a tier-n3 task replays offline, forever, identically.

Downloads through HelioAI's own `get_timeseries` rather than speasy directly: the manifest
that `datastore.find_existing` consults is written by that function, and a hand-rolled
manifest that differs in any field is a cache that silently never hits.

The start/stop strings here are the cache key. `find_existing` compares them as strings, so
`T00:00` and `T00:00:00` are different keys, and the task prompts must quote these exact
spellings or the replay leaves for the network.

Beside the data, `windows.json` records the shock time and the averaging windows the frozen
`rankine_hugoniot` recipe derives from it, plus which saved series is which quantity. That
file is what `scripts/reference_values.py` reads, so adding an event is running this script
and that one — not editing either.

    python scripts/build_fixture.py stpatrick_2015
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

EVENTS = {
    "stpatrick_2015": {
        "start": "2015-03-16T18:00:00",
        "stop": "2015-03-18T12:00:00",
        "shock": "2015-03-17T04:00:59",
        "params": [
            "cda/WI_H0_MFI/BGSM",
            "cda/WI_H0_MFI/B3GSM",
            "cda/AC_H0_MFI/BGSM",
            "cda/WI_H1_SWE/Proton_Np_moment",
            "cda/WI_H1_SWE/Proton_V_moment",
            "cda/WI_H1_SWE/Proton_W_moment",
            "amda/wnd_xyz_gse",
            "amda/ace_xyz_gse",
        ],
        # Saved-series name (as `get_timeseries` writes it) per quantity the truth needs.
        "series": {
            "field": "bgsm",
            "density": "proton_np_moment",
            "speed": "proton_v_moment",
            "thermal_speed": "proton_w_moment",
        },
    }
}


def windows_for(spec: dict) -> dict:
    """The `windows.json` record for an event, with the windows derived by the frozen recipe."""
    from heliobench.recipes import namespace

    rh = namespace("rankine_hugoniot")
    u0, u1, d0, d1 = rh["shock_windows"](spec["shock"])
    return {
        "shock": spec["shock"],
        "upstream": [str(u0), str(u1)],
        "downstream": [str(d0), str(d1)],
        **spec["series"],
        "note": (
            f"Windows are shock_windows(shock) from the frozen rankine_hugoniot recipe: guard "
            f"{rh['GUARD_MIN']:g} min, span {rh['SPAN_MIN']:g} min. They are part of every n3 "
            "prompt for this event; changing them here without changing the prompts derives a "
            "truth for a question nobody asked."
        ),
    }


async def build(event: str) -> Path:
    spec = EVENTS[event]
    tmp = Path(tempfile.mkdtemp(prefix=f"heliobench-fixture-{event}-"))
    os.environ.setdefault("HELIOAI_LLM_PROVIDER", "ollama")
    os.environ["HELIOAI_DATA_DIR"] = str(tmp)
    os.environ["HELIOAI_SESSION_DB"] = str(tmp / "sessions.db")

    import helioai.workspace as ws
    from helioai.tools.speasy_tools import get_timeseries

    ws.set_user("fixture")
    ws.set_session(event)
    ws.set_label(event)

    ok, failed = [], []
    for pid in spec["params"]:
        res = await get_timeseries(param_id=pid, start=spec["start"], stop=spec["stop"])
        if res.get("error"):
            failed.append((pid, res["error"]))
        else:
            ok.append((pid, res.get("dataset"), res.get("n_points"), res.get("missing_pct")))
        print(
            f"  {'ok ' if not res.get('error') else 'FAIL'} {pid}: "
            f"{res.get('dataset') or res.get('error')}"
        )

    src = ws.get_session_dir() / "data"
    dst = REPO / "fixtures" / event / "data"
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    shutil.rmtree(tmp, ignore_errors=True)
    (dst.parent / "windows.json").write_text(
        json.dumps(windows_for(spec), indent=2) + "\n", encoding="utf-8"
    )

    size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
    print(f"\n{len(ok)} ok, {len(failed)} failed — {size / 1e6:.1f} MB in {dst}")
    for pid, err in failed:
        print(f"  FAILED {pid}: {err}")
    return dst


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "stpatrick_2015"
    asyncio.run(build(name))
