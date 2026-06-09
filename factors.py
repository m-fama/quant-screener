"""Factor engine.

Produces a tidy DataFrame indexed by ticker, with one column per factor named to
match the keys in `config.HORIZONS`. Price factors are computed from the daily
price matrix; fundamental composites (value/quality/profitability) are built by
cross-sectionally standardising their sub-components, then averaging, so that
fields on wildly different scales (a P/E vs a margin) combine sensibly.

Technical indicators (RSI etc.) are implemented directly in pandas/numpy rather
than pulling in pandas-ta, keeping the dependency surface small and Python-3.13/14
friendly. pandas-ta-classic can be swapped in later for the full 190-indicator set.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _zscore(s: pd.Series) -> pd.Series:
    """Cross-sectional z-score, robust to all-NaN / zero-variance inputs."""
    s = s.astype(float)
    mu = s.mean(skipna=True)
    sd = s.std(skipna=True)
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def _rsi(prices: pd.Series, window: int = 14) -> float:
    """Classic Wilder RSI on the most recent `window`; returns the latest value."""
    delta = prices.diff().dropna()
    if len(delta) < window:
        return np.nan
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


# ---------------------------------------------------------------------------
# Price-based factors
# ---------------------------------------------------------------------------
def price_factors(prices: pd.DataFrame, volume: pd.DataFrame | None = None) -> pd.DataFrame:
    """`prices`: wide DataFrame (index=date, cols=ticker) of adjusted closes."""
    out: dict[str, dict[str, float]] = {}

    for t in prices.columns:
        p = prices[t].dropna()
        if len(p) < 60:  # need enough history to be meaningful
            continue

        last = p.iloc[-1]
        rec: dict[str, float] = {}

        # Momentum (skip-a-month convention for 12-1 to avoid reversal noise)
        rec["mom_1m"] = last / p.iloc[-21] - 1 if len(p) > 21 else np.nan
        rec["mom_3m"] = last / p.iloc[-63] - 1 if len(p) > 63 else np.nan
        if len(p) > TRADING_DAYS:
            rec["mom_12_1"] = p.iloc[-21] / p.iloc[-TRADING_DAYS] - 1
        else:
            rec["mom_12_1"] = np.nan

        # Trend vs moving averages
        ma50 = p.tail(50).mean()
        ma200 = p.tail(200).mean() if len(p) >= 200 else np.nan
        rec["trend_50d"] = last / ma50 - 1
        rec["trend_200d"] = last / ma200 - 1 if np.isfinite(ma200) else np.nan

        # Mean-reversion: oversold names score higher (50 - RSI)
        rsi = _rsi(p)
        rec["rsi_reversion"] = (50 - rsi) if np.isfinite(rsi) else np.nan

        # Volatility (annualised, last 63d) — stored negative so higher = calmer
        rets = p.pct_change().dropna()
        vol = rets.tail(63).std() * np.sqrt(TRADING_DAYS)
        rec["vol_inv"] = -float(vol) if np.isfinite(vol) else np.nan

        # 52-week range position
        win = p.tail(TRADING_DAYS)
        lo, hi = win.min(), win.max()
        rec["above_52w_low"] = (last / lo - 1) if lo > 0 else np.nan
        # Closeness to the 52-week low: 1.0 = at the low, 0.0 = at the high.
        # Used by the contrarian "Value / Mispriced" profile.
        rec["near_52w_low"] = ((hi - last) / (hi - lo)) if hi > lo else np.nan

        # Liquidity: log avg dollar volume (21d)
        if volume is not None and t in volume.columns:
            v = volume[t].tail(21).mean()
            rec["liquidity"] = float(np.log(max(v * last, 1.0)))
        else:
            rec["liquidity"] = np.nan

        out[t] = rec

    return pd.DataFrame.from_dict(out, orient="index")


# ---------------------------------------------------------------------------
# Fundamental factors
# ---------------------------------------------------------------------------
def fundamental_factors(fund: pd.DataFrame) -> pd.DataFrame:
    """Build value / quality / profitability / growth composites from raw fields."""
    f = fund.copy()

    # --- Value: yields (higher = cheaper). Invert the price-multiple ratios. ---
    earnings_yield = 1.0 / f["trailingPE"].where(f["trailingPE"] > 0)
    book_yield = 1.0 / f["priceToBook"].where(f["priceToBook"] > 0)
    ebitda_yield = 1.0 / f["enterpriseToEbitda"].where(f["enterpriseToEbitda"] > 0)
    fcf_yield = f["freeCashflow"] / f["enterpriseValue"].where(f["enterpriseValue"] > 0)
    value = (
        _zscore(earnings_yield) + _zscore(book_yield)
        + _zscore(ebitda_yield) + _zscore(fcf_yield)
    ) / 4.0

    # --- Quality: profitability + balance-sheet strength. ---
    roe = _zscore(f["returnOnEquity"])
    op_margin = _zscore(f["operatingMargins"])
    low_debt = _zscore(-f["debtToEquity"])  # less debt is better
    liquidity_ratio = _zscore(f["currentRatio"])
    quality = (roe + op_margin + low_debt + liquidity_ratio) / 4.0

    # --- Profitability (margins-focused). ---
    profitability = (
        _zscore(f["profitMargins"]) + _zscore(f["operatingMargins"])
        + _zscore(f["grossMargins"]) + _zscore(f["returnOnEquity"])
    ) / 4.0

    # --- Growth. ---
    earnings_growth = (
        _zscore(f["earningsGrowth"]) + _zscore(f["revenueGrowth"])
    ) / 2.0

    return pd.DataFrame(
        {
            "value": value,
            "quality": quality,
            "profitability": profitability,
            "earnings_growth": earnings_growth,
        }
    )


def build_factor_table(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame | None = None,
    volume: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine all factors into one ticker-indexed DataFrame."""
    pf = price_factors(prices, volume=volume)
    if fundamentals is not None and not fundamentals.empty:
        ff = fundamental_factors(fundamentals)
        table = pf.join(ff, how="left")
    else:
        table = pf
    table.index.name = "ticker"
    return table
