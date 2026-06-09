"""Pluggable market-data layer.

Right now this wraps yfinance (free, no API key). Everything downstream depends
ONLY on the two public functions below — `get_prices` and `get_fundamentals` —
so swapping in a paid provider (Polygon, Tiingo, FMP) later is a localized change.

Both functions cache to disk (parquet / json) to stay fast and polite to the API.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pandas as pd

import config

try:
    import yfinance as yf
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "yfinance is not installed. Activate the venv and run:\n"
        "    pip install -r requirements.txt"
    ) from exc

# Markets that use a non-Yahoo data source.
NON_US_MARKETS = {"ngx"}


def provider_for(universe_name: str):
    """Return the data-source module for a given universe.

    US markets use this module (Yahoo Finance); NGX uses the AFX adapter.
    All providers expose the same functions: get_prices / get_volume /
    get_names / get_fundamentals.
    """
    if universe_name == "ngx":
        import ngx_data
        return ngx_data
    import sys
    return sys.modules[__name__]


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
def _price_cache_path(universe_key: str) -> "config.Path":
    return config.CACHE_DIR / f"prices_{universe_key}.parquet"


def get_prices(
    tickers: list[str],
    period: str = "3y",
    universe_key: str = "default",
    force: bool = False,
) -> pd.DataFrame:
    """Return daily adjusted-close prices as a wide DataFrame (index=date, cols=ticker).

    Cached for `config.PRICE_CACHE_HOURS`.
    """
    cache = _price_cache_path(universe_key)
    if cache.exists() and not force:
        age_h = (time.time() - cache.stat().st_mtime) / 3600
        if age_h < config.PRICE_CACHE_HOURS:
            df = pd.read_parquet(cache)
            # Ensure all requested tickers are present; else refetch.
            if set(tickers).issubset(df.columns):
                return df[tickers]

    raw = yf.download(
        tickers,
        period=period,
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    # yfinance returns a column MultiIndex; grab Close (already adjusted).
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:  # single ticker edge case
        prices = raw[["Close"]].copy()
        prices.columns = tickers[:1]

    prices = prices.dropna(how="all").sort_index()
    prices.to_parquet(cache)
    return prices


def get_volume(tickers: list[str], period: str = "1y") -> pd.DataFrame:
    """Daily volume, used for a liquidity factor."""
    raw = yf.download(tickers, period=period, progress=False, threads=True)
    if isinstance(raw.columns, pd.MultiIndex):
        return raw["Volume"].copy()
    out = raw[["Volume"]].copy()
    out.columns = tickers[:1]
    return out


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------
_FUND_FIELDS = [
    "shortName", "longName", "sector",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    "returnOnEquity", "profitMargins", "operatingMargins", "grossMargins",
    "debtToEquity", "currentRatio", "earningsGrowth", "revenueGrowth",
    "marketCap", "freeCashflow", "enterpriseValue", "quickRatio",
    # Context-only signals (NOT scored — see get_signals): event/positioning risk.
    "shortPercentOfFloat", "shortRatio",
    "earningsTimestampStart", "earningsTimestamp",
]


def _fund_cache_path() -> "config.Path":
    return config.CACHE_DIR / "fundamentals.json"


def get_fundamentals(tickers: list[str], force: bool = False) -> pd.DataFrame:
    """Return a DataFrame indexed by ticker with the fields in `_FUND_FIELDS`.

    Cached for `config.FUNDAMENTAL_CACHE_HOURS`. Missing fields become NaN and
    are handled gracefully by the scoring layer.
    """
    cache = _fund_cache_path()
    cached: dict = {}
    if cache.exists() and not force:
        age_h = (time.time() - cache.stat().st_mtime) / 3600
        if age_h < config.FUNDAMENTAL_CACHE_HOURS:
            cached = json.loads(cache.read_text())

    rows: dict[str, dict] = {}
    # Refetch anything we've never seen OR whose cached row predates a newly
    # added field (keeps the cache self-healing when _FUND_FIELDS grows).
    _req = set(_FUND_FIELDS)
    to_fetch = [
        t for t in tickers
        if t not in cached or not _req.issubset(cached[t].keys())
    ]

    for t in to_fetch:
        try:
            info = yf.Ticker(t).info or {}
        except Exception:
            info = {}
        rows[t] = {f: info.get(f) for f in _FUND_FIELDS}
        time.sleep(0.05)  # be polite to the endpoint

    merged = {**cached, **rows}
    cache.write_text(json.dumps(merged))

    df = pd.DataFrame.from_dict(
        {t: merged[t] for t in tickers if t in merged}, orient="index"
    )
    df.index.name = "ticker"
    return df


# ---------------------------------------------------------------------------
# Context signals (informational only — never fed into the score)
# ---------------------------------------------------------------------------
def get_signals(tickers: list[str]) -> pd.DataFrame:
    """Return a DataFrame indexed by ticker with context-only signals:

    - ``short_pct``        : short interest as a fraction of float (0.33 = 33%)
    - ``days_to_earnings`` : calendar days until the next reported earnings date

    These are deliberately kept OUT of the composite score. Heavily-shorted
    stocks underperform on average, and an upcoming earnings date is event risk,
    not a buy signal — so we surface them as "heads-up" context, not as factors.
    Reuses the cached fundamentals pull, so it costs no extra network calls.
    """
    fund = get_fundamentals(tickers)
    out = pd.DataFrame(index=fund.index)
    out.index.name = "ticker"

    out["short_pct"] = pd.to_numeric(
        fund.get("shortPercentOfFloat"), errors="coerce"
    )

    ets = fund.get("earningsTimestampStart")
    if ets is None:
        ets = fund.get("earningsTimestamp")
    ets = pd.to_numeric(ets, errors="coerce")
    now = time.time()
    out["days_to_earnings"] = (ets - now) / 86400.0
    # Past dates are stale (Yahoo sometimes lags); treat as unknown.
    out.loc[out["days_to_earnings"] < -1, "days_to_earnings"] = pd.NA
    return out


# ---------------------------------------------------------------------------
# Company names (for friendly, layman display)
# ---------------------------------------------------------------------------
def _names_cache_path() -> "config.Path":
    return config.CACHE_DIR / "names.json"


def get_names(tickers: list[str]) -> dict[str, str]:
    """Return {ticker: human-readable company/fund name}.

    Seeds from the fundamentals cache first (free, already fetched for stocks),
    only hitting the network for names we still don't have. Falls back to the
    ticker itself if no name is available.
    """
    cache = _names_cache_path()
    names: dict[str, str] = {}
    if cache.exists():
        try:
            names = json.loads(cache.read_text())
        except Exception:
            names = {}

    # Seed from fundamentals cache (no network).
    fund_cache = _fund_cache_path()
    if fund_cache.exists():
        try:
            fund = json.loads(fund_cache.read_text())
            for t, row in fund.items():
                if t not in names:
                    nm = row.get("shortName") or row.get("longName")
                    if nm:
                        names[t] = nm
        except Exception:
            pass

    missing = [t for t in tickers if t not in names or not names[t]]
    for t in missing:
        try:
            info = yf.Ticker(t).info or {}
            names[t] = info.get("shortName") or info.get("longName") or t
        except Exception:
            names[t] = t
        time.sleep(0.03)

    if missing:
        cache.write_text(json.dumps(names))

    return {t: names.get(t, t) for t in tickers}
