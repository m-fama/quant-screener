"""SEC EDGAR fundamentals provider (free, official, point-in-time).

Why this exists
---------------
Yahoo fundamentals are (a) rate-limited at scale and (b) only a *current*
snapshot — useless for honest backtesting because using today's numbers on a
past date is lookahead bias. SEC EDGAR's ``companyfacts`` API is free, has no
key, covers every filer (including small caps outside any index), and stamps
every datapoint with the date it was ``filed`` — so we can ask "what was known
as of date D?" and get a truly point-in-time answer.

This module exposes the same shape as ``data_loader.get_fundamentals`` so it
drops straight into the pipeline. ``get_fundamentals_asof`` adds the historical,
point-in-time variant used by the backtester.

Notes / honest caveats
-----------------------
- We use the latest *annual* figures (10-K / 20-F). Clean and point-in-time, but
  up to ~a year stale vs. the freshest quarter. Good enough for value/quality;
  quarterly TTM is a future refinement.
- Price-based ratios (P/E, P/B, EV/EBITDA, FCF yield) need a market price, which
  EDGAR doesn't carry — the caller passes in the price(s).
- XBRL is messy: each metric is tried against several common concept aliases.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import pandas as pd
import requests

import config

# SEC asks for a descriptive User-Agent with contact info; be polite.
_HEADERS = {"User-Agent": "quant-screener research (contact: quant@example.com)"}
_SEC_RATE_SLEEP = 0.12  # ~8 req/s, under SEC's 10 req/s guidance

_EDGAR_DIR = config.CACHE_DIR / "edgar"
_EDGAR_DIR.mkdir(exist_ok=True)
_CIK_CACHE = config.CACHE_DIR / "sec_ticker_cik.json"
_FACTS_TTL_DAYS = 7

# Concept aliases (XBRL us-gaap tags vary by filer/taxonomy year).
_FLOW = {
    "revenue": [
        "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets"],
    "dep_amort": ["DepreciationDepletionAndAmortization",
                  "DepreciationAmortizationAndAccretionNet",
                  "DepreciationAndAmortization"],
}
_INSTANT = {
    "assets": ["Assets"],
    "assets_current": ["AssetsCurrent"],
    "liabilities": ["Liabilities"],
    "liabilities_current": ["LiabilitiesCurrent"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt", "DebtCurrent"],
}
_SHARES = ["EntityCommonStockSharesOutstanding"]  # dei namespace

# Output schema must match data_loader._FUND_FIELDS' fundamental columns.
_OUT_FIELDS = [
    "shortName", "longName", "sector",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    "returnOnEquity", "profitMargins", "operatingMargins", "grossMargins",
    "debtToEquity", "currentRatio", "earningsGrowth", "revenueGrowth",
    "marketCap", "freeCashflow", "enterpriseValue", "quickRatio",
]


# ---------------------------------------------------------------------------
# Ticker -> CIK
# ---------------------------------------------------------------------------
def _cik_map() -> dict[str, str]:
    if _CIK_CACHE.exists():
        age_d = (time.time() - _CIK_CACHE.stat().st_mtime) / 86400
        if age_d < 30:
            try:
                return json.loads(_CIK_CACHE.read_text())
            except Exception:
                pass
    try:
        raw = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_HEADERS, timeout=20,
        ).json()
        m = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
        _CIK_CACHE.write_text(json.dumps(m))
        return m
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# companyfacts fetch + cache
# ---------------------------------------------------------------------------
def _facts_path(cik: str):
    return _EDGAR_DIR / f"{cik}.json"


def _get_company_facts(cik: str) -> dict | None:
    path = _facts_path(cik)
    if path.exists():
        age_d = (time.time() - path.stat().st_mtime) / 86400
        if age_d < _FACTS_TTL_DAYS:
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
    try:
        time.sleep(_SEC_RATE_SLEEP)
        r = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=_HEADERS, timeout=30,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        path.write_text(json.dumps(data))
        return data
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fact selection (point-in-time aware)
# ---------------------------------------------------------------------------
def _units(facts: dict, namespace: str, concepts: list[str], unit: str) -> list[dict]:
    """Merge facts across ALL alias concepts so the most recent value wins.

    Picking the first alias that merely *exists* is dangerous: some filers keep a
    legacy tag (e.g. Apple's old `Revenues`) populated only with stale pre-2019
    data while the real figure lives under a newer tag. Merging and selecting by
    recency avoids that trap.
    """
    block = facts.get("facts", {}).get(namespace, {})
    merged: list[dict] = []
    for c in concepts:
        if c in block:
            u = block[c].get("units", {}).get(unit)
            if u:
                merged.extend(u)
    return merged


def _latest_annual(rows: list[dict], asof: str | None) -> float | None:
    """Most recent annual (≈365-day) flow value known as of `asof`."""
    best = None
    for r in rows:
        if r.get("form") not in ("10-K", "10-K/A", "20-F", "40-F"):
            continue
        start, end = r.get("start"), r.get("end")
        if not start or not end:
            continue
        dur = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
        if dur < 340 or dur > 380:
            continue
        if asof and r.get("filed", "9999") > asof:
            continue
        if best is None or end > best[0]:
            best = (end, r.get("val"))
    return best[1] if best else None


def _annual_series(rows: list[dict], asof: str | None) -> list[tuple[str, float]]:
    """All annual flow values (end, val) known as of `asof`, newest first."""
    seen: dict[str, float] = {}
    for r in rows:
        if r.get("form") not in ("10-K", "10-K/A", "20-F", "40-F"):
            continue
        start, end = r.get("start"), r.get("end")
        if not start or not end:
            continue
        dur = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
        if dur < 340 or dur > 380:
            continue
        if asof and r.get("filed", "9999") > asof:
            continue
        if end not in seen or r.get("filed", "") >= seen.get(end + "_f", ""):
            seen[end] = r.get("val")
    return sorted(seen.items(), key=lambda x: x[0], reverse=True)


def _latest_instant(rows: list[dict], asof: str | None) -> float | None:
    """Most recent balance-sheet (instant) value known as of `asof`."""
    best = None
    for r in rows:
        end = r.get("end")
        if not end:
            continue
        if asof and r.get("filed", "9999") > asof:
            continue
        if best is None or end > best[0]:
            best = (end, r.get("val"))
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Compute a fundamentals row for one company
# ---------------------------------------------------------------------------
def _row_for(facts: dict, price: float | None, asof: str | None) -> dict:
    def flow(key):
        return _latest_annual(_units(facts, "us-gaap", _FLOW[key], "USD"), asof)

    def inst(key):
        return _latest_instant(_units(facts, "us-gaap", _INSTANT[key], "USD"), asof)

    rev = flow("revenue")
    ni = flow("net_income")
    gp = flow("gross_profit")
    oi = flow("operating_income")
    ocf = flow("ocf")
    capex = flow("capex")
    da = flow("dep_amort")

    equity = inst("equity")
    assets_cur = inst("assets_current")
    liab_cur = inst("liabilities_current")
    liab = inst("liabilities")
    cash = inst("cash")
    debt = inst("debt")

    shares = _latest_instant(_units(facts, "dei", _SHARES, "shares"), asof)

    # Growth from consecutive annual periods.
    rev_series = _annual_series(_units(facts, "us-gaap", _FLOW["revenue"], "USD"), asof)
    ni_series = _annual_series(_units(facts, "us-gaap", _FLOW["net_income"], "USD"), asof)

    def yoy(series):
        if len(series) >= 2 and series[1][1]:
            prev = series[1][1]
            if prev != 0:
                return series[0][1] / abs(prev) - 1 if prev > 0 else None
        return None

    out = {k: None for k in _OUT_FIELDS}

    def safe_div(a, b):
        return (a / b) if (a is not None and b not in (None, 0)) else None

    out["profitMargins"] = safe_div(ni, rev)
    out["grossMargins"] = safe_div(gp, rev)
    out["operatingMargins"] = safe_div(oi, rev)
    out["returnOnEquity"] = safe_div(ni, equity)
    out["currentRatio"] = safe_div(assets_cur, liab_cur)
    out["quickRatio"] = out["currentRatio"]  # no inventory split; approximate
    # Leverage proxy: total liabilities / equity, ×100 to match Yahoo's scale.
    de = safe_div(liab, equity)
    out["debtToEquity"] = de * 100 if de is not None else None
    out["revenueGrowth"] = yoy(rev_series)
    out["earningsGrowth"] = yoy(ni_series)
    out["freeCashflow"] = (ocf - capex) if (ocf is not None and capex is not None) else ocf

    # Price-dependent ratios.
    if price is not None and shares:
        mcap = price * shares
        out["marketCap"] = mcap
        ev = mcap + (debt or liab or 0) - (cash or 0)
        out["enterpriseValue"] = ev
        out["trailingPE"] = safe_div(mcap, ni) if (ni and ni > 0) else None
        out["priceToBook"] = safe_div(mcap, equity) if (equity and equity > 0) else None
        ebitda = (oi + da) if (oi is not None and da is not None) else oi
        out["enterpriseToEbitda"] = safe_div(ev, ebitda) if (ebitda and ebitda > 0) else None
    return out


# ---------------------------------------------------------------------------
# Public API (matches data_loader provider shape)
# ---------------------------------------------------------------------------
def preload_facts(tickers: list[str]) -> dict[str, dict | None]:
    """Fetch (cached) companyfacts for many tickers once, into memory. Used by
    the backtester so it can replay history without re-reading disk each date."""
    cmap = _cik_map()
    out: dict[str, dict | None] = {}
    for t in tickers:
        cik = cmap.get(t.upper())
        out[t] = _get_company_facts(cik) if cik else None
    return out


def fundamentals_from_facts(
    facts_map: dict[str, dict | None],
    tickers: list[str],
    prices: dict[str, float] | None = None,
    asof: str | None = None,
) -> pd.DataFrame:
    """Compute the fundamentals table from already-loaded companyfacts."""
    prices = prices or {}
    rows: dict[str, dict] = {}
    for t in tickers:
        facts = facts_map.get(t)
        if not facts:
            rows[t] = {k: None for k in _OUT_FIELDS}
            continue
        row = _row_for(facts, prices.get(t), asof)
        row["longName"] = facts.get("entityName")
        row["shortName"] = facts.get("entityName")
        rows[t] = row
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "ticker"
    return df


def get_fundamentals(
    tickers: list[str],
    prices: dict[str, float] | None = None,
    force: bool = False,
    asof: str | None = None,
) -> pd.DataFrame:
    """Fundamentals from SEC EDGAR. `prices` (ticker->latest close) enables the
    price-based value ratios. `asof` (YYYY-MM-DD) restricts to data filed on or
    before that date (point-in-time); None = latest available."""
    facts_map = preload_facts(tickers)
    return fundamentals_from_facts(facts_map, tickers, prices=prices, asof=asof)


def get_fundamentals_asof(
    tickers: list[str], asof: str, prices: dict[str, float] | None = None
) -> pd.DataFrame:
    """Point-in-time fundamentals as known on `asof` (YYYY-MM-DD)."""
    return get_fundamentals(tickers, prices=prices, asof=asof)


def has_coverage(ticker: str) -> bool:
    return ticker.upper() in _cik_map()
