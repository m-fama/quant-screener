"""Investable universes.

Keep universes explicit and curated. A smaller, liquid universe makes the
screener fast and the cross-sectional scoring meaningful (you need enough names
for percentiles, but not so many that data fetching becomes painful).

Swap in a full index membership list later (e.g. scrape S&P 500 constituents)
without changing anything downstream.
"""

from __future__ import annotations

import json

import config

# Large, liquid US stocks across sectors — a sane default starter universe.
STOCKS_CORE = [
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "ADBE", "CRM",
    # Semis / hardware
    "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT",
    # Consumer
    "TSLA", "HD", "NKE", "MCD", "SBUX", "COST", "WMT", "PG", "KO", "PEP",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "BLK", "SCHW",
    # Health
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR",
    # Industrials / energy
    "CAT", "DE", "BA", "GE", "HON", "UPS", "XOM", "CVX", "COP",
    # Comms / media
    "NFLX", "DIS", "T", "VZ", "CMCSA",
]

# Popular mid-caps / high-interest names not always in the S&P 500. Important for
# value/contrarian hunting, where beaten-down mid-caps (e.g. HIMS, SOFI) live.
POPULAR_EXTRA = [
    "SOFI", "HIMS", "PLTR", "RIVN", "LCID", "HOOD", "COIN", "AFRM", "UBER",
    "ABNB", "SHOP", "SNAP", "PINS", "RBLX", "DKNG", "CVNA", "UPST", "U",
    "NET", "SNOW", "CRWD", "ZS", "MDB", "ROKU", "TWLO", "DOCU", "PYPL",
    "DASH", "RDDT", "CHWY", "ETSY", "W", "WBD", "F", "GM", "NIO",
]

# Broad and factor ETFs / funds — useful for the longer-horizon allocation side.
ETFS_CORE = [
    # Broad market
    "SPY", "VOO", "IVV", "QQQ", "DIA", "IWM", "VTI", "RSP",
    # International / EM / bonds
    "VEA", "VWO", "EFA", "IEFA", "IEMG", "BND", "AGG", "BNDX", "TLT", "IEF", "LQD", "HYG", "TIP",
    # Factor / smart-beta
    "MTUM", "VLUE", "QUAL", "USMV", "SIZE", "VIG", "VYM", "SCHD", "DGRO", "SPLV", "COWZ",
    # Sectors
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLB", "XLRE", "XLC", "SMH", "SOXX",
    # Themes / alternatives
    "GLD", "SLV", "VNQ", "ARKK", "ICLN", "IBIT",
]

# Commodities & metals, expressed via liquid ETFs/ETNs (free, clean, tradeable).
# Avoids futures-symbol messiness while still covering the asset class.
COMMODITIES = [
    # Broad commodity baskets
    "DBC", "GSG", "PDBC", "COMT",
    # Precious metals (+ miners)
    "GLD", "IAU", "SLV", "PPLT", "PALL", "GDX", "GDXJ", "SIL",
    # Energy
    "USO", "BNO", "UNG", "UGA",
    # Industrial / base metals (+ miners)
    "CPER", "COPX", "DBB", "XME", "PICK", "SLX",
    # Future / battery metals
    "LIT", "URA", "URNM", "REMX",
    # Agriculture
    "DBA", "WEAT", "CORN", "SOYB", "MOO",
]

# Cache files for scraped index membership.
_SP500_CACHE = config.CACHE_DIR / "sp500_constituents.json"
_SP400_CACHE = config.CACHE_DIR / "sp400_constituents.json"
_SP600_CACHE = config.CACHE_DIR / "sp600_constituents.json"

# Minimal hard-coded fallback so the tool still works fully offline / if the
# Wikipedia scrape fails. Not exhaustive — the live scrape returns all ~500.
_SP500_FALLBACK = sorted(set(STOCKS_CORE + [
    "ACN", "ADP", "AMGN", "AMT", "BKNG", "BMY", "BX", "C", "CB", "CI", "CL", "CME",
    "CSCO", "CVS", "DUK", "ELV", "EOG", "EQIX", "ETN", "FDX", "GD", "GILD", "GM",
    "ICE", "ISRG", "ITW", "LIN", "LMT", "LOW", "MDLZ", "MDT", "MMC", "MO", "MRNA",
    "NEE", "NOW", "PANW", "PGR", "PLD", "PM", "PNC", "REGN", "RTX", "SBAC", "STZ",
    "SO", "SPGI", "SYK", "TGT", "TJX", "USB", "VRTX", "WM", "ZTS",
]))


def _scrape_wiki_symbols(url: str, cache_file, min_expected: int) -> list[str] | None:
    """Scrape a Wikipedia 'List of S&P xxx companies' table's Symbol column.

    Returns a cached list if available, else scrapes + caches. Returns None only
    if both the cache and the live scrape fail (caller supplies a fallback).
    """
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass
    try:
        import io

        import pandas as pd
        import requests

        # Wikipedia 403s the default urllib UA; use a browser-like header.
        html = requests.get(
            url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (quant-screener)"}
        ).text
        for tbl in pd.read_html(io.StringIO(html)):
            col = next((c for c in tbl.columns if str(c).lower() in
                        ("symbol", "ticker", "ticker symbol")), None)
            if col is None:
                continue
            syms = tbl[col].astype(str).str.replace(".", "-", regex=False)
            tickers = sorted({s for s in syms.tolist() if s and s.isascii()
                              and 1 <= len(s) <= 6 and s.upper() == s})
            if len(tickers) >= min_expected:
                cache_file.write_text(json.dumps(tickers))
                return tickers
    except Exception:
        pass
    return None


def get_sp500(force: bool = False) -> list[str]:
    """Current S&P 500 tickers, scraped free from Wikipedia and cached.
    Falls back to a bundled static list if the network scrape is unavailable."""
    if force and _SP500_CACHE.exists():
        _SP500_CACHE.unlink()
    syms = _scrape_wiki_symbols(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        _SP500_CACHE, min_expected=400,
    )
    return syms if syms else _SP500_FALLBACK


def get_sp400() -> list[str]:
    """S&P MidCap 400 constituents (free Wikipedia scrape). Empty list on failure."""
    return _scrape_wiki_symbols(
        "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        _SP400_CACHE, min_expected=300,
    ) or []


def get_sp600() -> list[str]:
    """S&P SmallCap 600 constituents (free Wikipedia scrape). Empty list on failure."""
    return _scrape_wiki_symbols(
        "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        _SP600_CACHE, min_expected=400,
    ) or []


def get_sp1500() -> list[str]:
    """All US Stocks proxy: S&P 1500 (large + mid + small cap) + popular names."""
    return sorted(set(get_sp500() + get_sp400() + get_sp600() + POPULAR_EXTRA))


def get_emerging() -> list[str]:
    """'Emerging' pool: small/mid-cap real companies where undervalued early
    movers actually live — S&P 400 + 600 + popular high-interest mid-caps,
    deliberately EXCLUDING the mega-cap S&P 500 (already well-discovered)."""
    small_mid = set(get_sp400() + get_sp600() + POPULAR_EXTRA)
    big = set(get_sp500())
    pool = sorted(small_mid - big)
    # Fallback: if the mid/small scrapes failed, lean on popular mid-caps.
    return pool if len(pool) >= 50 else sorted(set(POPULAR_EXTRA))


# Universes whose constituents are price-only (no per-company fundamentals).
PRICE_ONLY = {"etfs", "commodities"}

UNIVERSES: dict[str, list[str]] = {
    "stocks": sorted(set(STOCKS_CORE + POPULAR_EXTRA)),
    "etfs": ETFS_CORE,
    "commodities": COMMODITIES,
    "all": sorted(set(STOCKS_CORE + POPULAR_EXTRA + ETFS_CORE)),
}


def get_universe(name: str) -> list[str]:
    """Resolve a universe name to a ticker list. Index-based and market-based
    universes are resolved dynamically (scraped + cached)."""
    if name in ("us_all", "sp1500"):
        return get_sp1500()
    if name == "emerging":
        return get_emerging()
    if name == "sp500":
        return get_sp500()
    if name == "sp500+etfs":
        return sorted(set(get_sp500() + ETFS_CORE))
    if name == "sp500+popular":
        return sorted(set(get_sp500() + STOCKS_CORE + POPULAR_EXTRA))
    if name == "ngx":
        import ngx_data
        return ngx_data.get_universe()
    if name not in UNIVERSES:
        raise ValueError(
            f"Unknown universe '{name}'. Options: "
            f"{list(UNIVERSES) + ['us_all', 'emerging', 'sp500', 'sp500+etfs', 'sp500+popular', 'ngx']}"
        )
    return UNIVERSES[name]
