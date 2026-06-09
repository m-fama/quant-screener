"""Scoring pipeline with a two-stage funnel.

Pulling per-company fundamentals for 1,000+ names at once gets rate-limited by
free data sources (Yahoo). So for large universes we:

  1. Download prices in ONE batch (cheap, reliable) and score the *whole*
     universe on price factors.
  2. Keep only the top `FUND_LIMIT` candidates, then fetch fundamentals for
     *those* and re-score with the full factor set.

This keeps API usage sustainable, makes loads fast, and mirrors how real
screeners work: a broad price-based pass narrows the field, then fundamentals
confirm the finalists. Horizons that don't use fundamentals (e.g. "short") skip
stage 2 entirely and rank the full universe.
"""

from __future__ import annotations

import config
import data_loader
import factors
import scoring
import universe as universe_mod

# How many price-screened finalists to pull fundamentals for.
FUND_LIMIT = 150

# Composite factors that require per-company fundamentals.
_FUND_FACTORS = {"value", "quality", "profitability", "earnings_growth"}


def horizon_needs_fundamentals(horizon: str) -> bool:
    weights = config.HORIZONS.get(horizon, {})
    return any(f in weights for f in _FUND_FACTORS)


def _latest_prices(prices, tickers: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in tickers:
        if t in prices.columns:
            s = prices[t].dropna()
            if len(s):
                out[t] = float(s.iloc[-1])
    return out


def load_fundamentals(tickers: list[str], prices, *, refresh: bool = False, asof=None):
    """Fundamentals for US tickers, EDGAR-first with optional Yahoo backfill.

    EDGAR is free, point-in-time and rate-limit-free, but doesn't cover ETFs,
    some foreign issuers, or pre-filing IPOs — those get backfilled from Yahoo.
    """
    latest = _latest_prices(prices, tickers)

    if config.FUNDAMENTALS_SOURCE == "edgar":
        import pandas as pd

        import edgar_data
        df = edgar_data.get_fundamentals(tickers, prices=latest, force=refresh, asof=asof)
        if config.FUNDAMENTALS_FALLBACK:
            key = ["profitMargins", "returnOnEquity", "revenueGrowth"]
            miss = [t for t in df.index if df.loc[t, key].isna().all()]
            # Yahoo has no point-in-time history, so only backfill live (asof=None).
            if miss and asof is None:
                ydf = data_loader.get_fundamentals(miss).reindex(columns=df.columns)
                df = pd.concat([df.drop(index=miss), ydf]).reindex(index=tickers)
        # Ensure numeric columns are floats (concat/None can leave them object).
        for c in df.columns:
            if c not in ("shortName", "longName", "sector"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    return data_loader.get_fundamentals(tickers, force=refresh)


def build_scored(
    universe_name: str,
    horizon: str,
    *,
    refresh: bool = False,
    fund_limit: int = FUND_LIMIT,
):
    """Return a scored, ranked DataFrame for a universe + horizon."""
    prov = data_loader.provider_for(universe_name)
    tickers = universe_mod.get_universe(universe_name)

    prices = prov.get_prices(
        tickers, period="3y", universe_key=universe_name, force=refresh
    )
    volume = prov.get_volume(tickers, period="6mo")

    price_only_universe = universe_name in universe_mod.PRICE_ONLY or universe_name == "ngx"

    # Stage 1 — price factors on the whole universe.
    price_table = factors.build_factor_table(prices, fundamentals=None, volume=volume)

    if price_only_universe or not horizon_needs_fundamentals(horizon):
        return scoring.score(price_table, horizon=horizon)

    # Stage 2 — narrow to finalists (by the price-based slice of this horizon),
    # then fetch fundamentals only for them and re-score with everything.
    if len(price_table.index) > fund_limit:
        prelim = scoring.score(price_table, horizon=horizon)
        candidates = list(prelim.head(fund_limit).index)
    else:
        candidates = list(price_table.index)

    # EDGAR-first fundamentals (free, point-in-time) with Yahoo backfill.
    if universe_name == "ngx":
        fundamentals = prov.get_fundamentals(candidates, force=refresh)
    else:
        fundamentals = load_fundamentals(candidates, prices, refresh=refresh)
    sub_prices = prices[[c for c in candidates if c in prices.columns]]
    sub_volume = (
        volume[[c for c in candidates if c in volume.columns]]
        if volume is not None else None
    )
    table = factors.build_factor_table(
        sub_prices, fundamentals=fundamentals, volume=sub_volume
    )
    return scoring.score(table, horizon=horizon)
