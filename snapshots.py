"""Precomputed snapshots so the dashboard loads instantly.

Building a scored table live means fetching 3y of prices for ~1,000+ tickers
(and fundamentals for the finalists) on every cold start / redeploy — a minute
or more on free infra, and Streamlit Cloud wipes its cache on each deploy.

Instead we precompute the scored tables offline (see ``precompute.py``), commit
the small result files to the repo, and the dashboard reads them in
milliseconds. A "live data" toggle still recomputes on demand. Snapshots live
under ``data/snapshots/`` (committed, NOT in .gitignore).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

import config
import data_loader
import pipeline
import universe as universe_mod

SNAP_DIR = config.ROOT / "data" / "snapshots"
SNAP_DIR.mkdir(parents=True, exist_ok=True)


def _key(universe: str, horizon: str) -> str:
    return f"{universe.replace('+', '-')}__{horizon}"


def _paths(universe: str, horizon: str):
    k = _key(universe, horizon)
    return SNAP_DIR / f"{k}.parquet", SNAP_DIR / f"{k}.json"


def save(universe: str, horizon: str, *, top_meta: int = 100) -> dict:
    """Compute and persist a snapshot bundle for one (universe, horizon)."""
    scored = pipeline.build_scored(universe, horizon)
    finalists = list(scored.head(top_meta).index)
    prov = data_loader.provider_for(universe)

    try:
        names = prov.get_names(finalists)
    except Exception:
        names = {}

    sectors: dict = {}
    if universe == "ngx":
        try:
            import ngx_data
            sectors = ngx_data.get_sectors()
        except Exception:
            sectors = {}

    signals: dict = {}
    if universe not in universe_mod.PRICE_ONLY:
        try:
            sdf = prov.get_signals(finalists)
            for t, r in sdf.iterrows():
                sp, dte = r.get("short_pct"), r.get("days_to_earnings")
                signals[t] = {
                    "short_pct": None if pd.isna(sp) else float(sp),
                    "days_to_earnings": None if pd.isna(dte) else float(dte),
                }
        except Exception:
            signals = {}

    p_parq, p_json = _paths(universe, horizon)
    scored.to_parquet(p_parq)
    p_json.write_text(json.dumps({
        "universe": universe,
        "horizon": horizon,
        "asof": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "rows": int(len(scored)),
        "names": names,
        "sectors": sectors,
        "signals": signals,
    }))
    return {"rows": len(scored), "finalists": len(finalists)}


def load(universe: str, horizon: str):
    """Return a snapshot bundle dict, or None if not available/readable."""
    p_parq, p_json = _paths(universe, horizon)
    if not (p_parq.exists() and p_json.exists()):
        return None
    try:
        scored = pd.read_parquet(p_parq)
        meta = json.loads(p_json.read_text())
        signals = pd.DataFrame.from_dict(meta.get("signals", {}), orient="index")
        if not signals.empty:
            signals.index.name = "ticker"
        return {
            "scored": scored,
            "names": meta.get("names", {}),
            "sectors": meta.get("sectors", {}),
            "signals": signals,
            "asof": meta.get("asof", "unknown"),
        }
    except Exception:
        return None
