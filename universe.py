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

# Cache file for scraped S&P 500 membership.
_SP500_CACHE = config.CACHE_DIR / "sp500_constituents.json"

# Minimal hard-coded fallback so the tool still works fully offline / if the
# Wikipedia scrape fails. Not exhaustive — the live scrape returns all ~500.
_SP500_FALLBACK = sorted(set(STOCKS_CORE + [
    "ACN", "ADP", "AMGN", "AMT", "BKNG", "BMY", "BX", "C", "CB", "CI", "CL", "CME",
    "CSCO", "CVS", "DUK", "ELV", "EOG", "EQIX", "ETN", "FDX", "GD", "GILD", "GM",
    "ICE", "ISRG", "ITW", "LIN", "LMT", "LOW", "MDLZ", "MDT", "MMC", "MO", "MRNA",
    "NEE", "NOW", "PANW", "PGR", "PLD", "PM", "PNC", "REGN", "RTX", "SBAC", "STZ",
    "SO", "SPGI", "SYK", "TGT", "TJX", "USB", "VRTX", "WM", "ZTS",
]))


def get_sp500(force: bool = False) -> list[str]:
    """Return the current S&P 500 tickers, scraped free from Wikipedia and cached.

    Falls back to a bundled static list if the network scrape is unavailable.
    """
    if _SP500_CACHE.exists() and not force:
        try:
            return json.loads(_SP500_CACHE.read_text())
        except Exception:
            pass

    try:
        import io

        import pandas as pd
        import requests

        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        # Wikipedia 403s the default urllib UA, so fetch via requests with a
        # browser-like header, then parse the HTML.
        html = requests.get(
            url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (quant-screener)"}
        ).text
        tables = pd.read_html(io.StringIO(html))
        syms = tables[0]["Symbol"].astype(str).str.replace(".", "-", regex=False)
        tickers = sorted(set(syms.tolist()))
        if len(tickers) > 400:
            _SP500_CACHE.write_text(json.dumps(tickers))
            return tickers
    except Exception:
        pass

    return _SP500_FALLBACK


UNIVERSES: dict[str, list[str]] = {
    "stocks": sorted(set(STOCKS_CORE + POPULAR_EXTRA)),
    "etfs": ETFS_CORE,
    "all": sorted(set(STOCKS_CORE + POPULAR_EXTRA + ETFS_CORE)),
}


def get_universe(name: str) -> list[str]:
    """Resolve a universe name to a ticker list. 'sp500'/'sp500+etfs' and 'ngx'
    are resolved dynamically (scraped + cached)."""
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
            f"{list(UNIVERSES) + ['sp500', 'sp500+etfs', 'sp500+popular', 'ngx']}"
        )
    return UNIVERSES[name]
