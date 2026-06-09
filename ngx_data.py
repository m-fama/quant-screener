"""Nigerian Exchange (NGX) data adapter — free, via AFX (afx.kwayisi.org).

Yahoo Finance has no NGX coverage, so we use AFX, which provides:
  - a full listing of NGX equities (ticker, name, current price, volume),
  - per-symbol DAILY price history back to ~2016 via its chart endpoint.

This module mirrors the public function names in `data_loader` (get_prices,
get_volume, get_names, get_fundamentals) so the rest of the pipeline can treat
NGX like any other market. Prices are in Nigerian Naira (NGN); since our scoring
is cross-sectional (relative z-scores), the currency/scale doesn't affect ranks.

Limitation: AFX doesn't publish deep fundamentals (ROE, margins, debt), so
`get_fundamentals` returns None — NGX ranking runs on price-based factors only.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

import config

BASE = "https://afx.kwayisi.org"
_HEADERS = {"User-Agent": "Mozilla/5.0 (quant-screener NGX adapter)"}

_LISTING_CACHE = config.CACHE_DIR / "ngx_listing.json"
_PRICES_CACHE = config.CACHE_DIR / "ngx_prices.parquet"
_SECTORS_CACHE = config.CACHE_DIR / "ngx_sectors.json"
_LISTING_CACHE_HOURS = 12
_SECTORS_CACHE_HOURS = 24

# NGX's official statistics API — the only free source that reliably tags every
# listed equity with its sector (deep fundamentals like P/E, ROE are NOT freely
# published for NGX, so we can't build value/quality factors here). The API only
# returns recently-traded names per call and caps page size near 50, so we
# paginate and MERGE results into the cache to build coverage over time.
_DOCLIB_URL = (
    "https://doclib.ngxgroup.com/REST/api/statistics/equities/"
    "?market=&sector=&orderby=&pageSize=50&pageNo={pn}"
)

# Matches each listing row: url-symbol, company name (title), volume, price.
_ROW_RE = re.compile(
    r'ngx/([a-z0-9&\-]+)\.html title="([^"]+)">[^<]+</a>'
    r'<td><a[^>]+>[^<]+</a>'
    r'<td>([\d,]*)'
    r'<td>([\d,]*\.?\d*)'
)

# Matches the [date, price] pairs in the Highcharts series.
_PT_RE = re.compile(r'd\("(\d{4}-\d{2}-\d{2})"\),([\d.]+)')


# ---------------------------------------------------------------------------
# Listing (universe + current snapshot)
# ---------------------------------------------------------------------------
def get_listing(force: bool = False) -> dict[str, dict]:
    """Return {TICKER: {name, price, volume}} for all NGX equities."""
    if _LISTING_CACHE.exists() and not force:
        age_h = (time.time() - _LISTING_CACHE.stat().st_mtime) / 3600
        if age_h < _LISTING_CACHE_HOURS:
            try:
                return json.loads(_LISTING_CACHE.read_text())
            except Exception:
                pass

    out: dict[str, dict] = {}
    for page in (1, 2, 3):  # AFX paginates ~100/page; 3 is a safe upper bound
        url = f"{BASE}/ngx/" if page == 1 else f"{BASE}/ngx/?page={page}"
        try:
            html = requests.get(url, headers=_HEADERS, timeout=15).text
        except Exception:
            continue
        found = 0
        for m in _ROW_RE.finditer(html):
            sym = m.group(1).upper()
            name = m.group(2).replace("&amp;", "&").strip()
            vol = m.group(3).replace(",", "")
            price = m.group(4).replace(",", "")
            if sym in out:
                continue
            out[sym] = {
                "name": name,
                "price": float(price) if price else None,
                "volume": float(vol) if vol else 0.0,
            }
            found += 1
        if found == 0 and page > 1:
            break

    if out:
        _LISTING_CACHE.write_text(json.dumps(out))
    return out


def get_universe(force: bool = False, active_only: bool = True) -> list[str]:
    """All NGX tickers. By default excludes names with no recent trading volume
    (suspended / dormant listings) so the ranking isn't polluted by dead stocks."""
    listing = get_listing(force=force)
    if active_only:
        return sorted(t for t, d in listing.items() if (d.get("volume") or 0) > 0)
    return sorted(listing.keys())


def get_names(tickers: list[str]) -> dict[str, str]:
    listing = get_listing()
    return {t: listing.get(t, {}).get("name", t) for t in tickers}


def _clean_sector(raw: str) -> str:
    s = raw.strip().title()
    if not s:
        return ""
    s = s.replace(" And ", " & ")
    # Fix acronyms that title-casing mangles.
    for wrong, right in {"Ict": "ICT"}.items():
        s = s.replace(wrong, right)
    return s


def get_sectors(force: bool = False) -> dict[str, str]:
    """Return {TICKER: sector} from NGX's official statistics API (free).

    Merges freshly fetched sectors into the on-disk cache, so coverage grows as
    more names trade across days (the API only reports recently-traded equities).
    """
    cached: dict[str, str] = {}
    if _SECTORS_CACHE.exists():
        try:
            cached = json.loads(_SECTORS_CACHE.read_text())
        except Exception:
            cached = {}

    fresh_enough = (
        _SECTORS_CACHE.exists()
        and (time.time() - _SECTORS_CACHE.stat().st_mtime) / 3600 < _SECTORS_CACHE_HOURS
    )
    if cached and fresh_enough and not force:
        return cached

    fetched: dict[str, str] = {}
    headers = {**_HEADERS, "Referer": "https://ngxgroup.com/"}
    for pn in range(1, 8):
        try:
            data = requests.get(_DOCLIB_URL.format(pn=pn), headers=headers, timeout=20).json()
        except Exception:
            break
        if not data:
            break
        for d in data:
            sym = (d.get("Symbol") or "").upper()
            sector = _clean_sector(d.get("Sector") or "")
            if sym and sector:
                fetched[sym] = sector

    merged = {**cached, **fetched}
    if merged:
        _SECTORS_CACHE.write_text(json.dumps(merged))
    return merged


# ---------------------------------------------------------------------------
# Price history (the key piece, via the chart endpoint)
# ---------------------------------------------------------------------------
def _fetch_one_history(sym: str) -> tuple[str, pd.Series | None]:
    url = f"{BASE}/chart/ngx/{sym.lower()}"
    try:
        txt = requests.get(url, headers=_HEADERS, timeout=15).text
    except Exception:
        return sym, None
    pts = _PT_RE.findall(txt)
    if not pts:
        return sym, None
    idx = pd.to_datetime([p[0] for p in pts])
    vals = [float(p[1]) for p in pts]
    s = pd.Series(vals, index=idx).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return sym, s


def get_prices(
    tickers: list[str],
    period: str = "3y",
    universe_key: str = "ngx",
    force: bool = False,
) -> pd.DataFrame:
    """Wide DataFrame (index=date, cols=ticker) of daily NGX closing prices.

    Cached to parquet for `config.PRICE_CACHE_HOURS`.
    """
    if _PRICES_CACHE.exists() and not force:
        age_h = (time.time() - _PRICES_CACHE.stat().st_mtime) / 3600
        if age_h < config.PRICE_CACHE_HOURS:
            df = pd.read_parquet(_PRICES_CACHE)
            have = [t for t in tickers if t in df.columns]
            if len(have) >= 0.9 * len(tickers):  # mostly cached → good enough
                return df[have]

    series: dict[str, pd.Series] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_fetch_one_history, t): t for t in tickers}
        for fut in as_completed(futs):
            sym, s = fut.result()
            if s is not None and len(s) > 0:
                series[sym] = s

    if not series:
        return pd.DataFrame()

    df = pd.DataFrame(series).sort_index()
    df.to_parquet(_PRICES_CACHE)
    return df


def get_volume(tickers: list[str], period: str = "6mo") -> pd.DataFrame:
    """AFX only exposes current volume, so we return a single-row frame of the
    latest volume per ticker. The factor engine averages a trailing window,
    which collapses to this value — fine for a relative liquidity signal."""
    listing = get_listing()
    today = pd.Timestamp.today().normalize()
    row = {t: listing.get(t, {}).get("volume", 0.0) for t in tickers}
    return pd.DataFrame([row], index=[today])


def get_fundamentals(tickers: list[str], force: bool = False):
    """AFX doesn't publish the fundamentals our quality/value composites need
    (ROE, margins, debt). Return None so the pipeline uses price factors only."""
    return None


def get_signals(tickers: list[str]):
    """Short interest / earnings dates aren't published for NGX on free sources.
    Return an empty frame so the dashboard simply shows no heads-up flags."""
    import pandas as pd

    out = pd.DataFrame(index=pd.Index(tickers, name="ticker"))
    out["short_pct"] = pd.NA
    out["days_to_earnings"] = pd.NA
    return out
