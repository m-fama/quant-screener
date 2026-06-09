"""Central configuration for the quant screener.

Everything that defines *how* we score is here, so the methodology is explicit,
auditable, and easy to tune. No magic numbers buried in code.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# How long cached market data stays fresh (hours). Prices update daily, so a
# few hours is plenty for intraday re-runs without hammering the data source.
PRICE_CACHE_HOURS = 6
FUNDAMENTAL_CACHE_HOURS = 24

# ---------------------------------------------------------------------------
# Horizon profiles
# ---------------------------------------------------------------------------
# Each horizon weights the underlying factors DIFFERENTLY, because the signals
# that predict a 2-week move are nearly the opposite of those that predict a
# multi-year hold. Weights are relative; they get normalised at scoring time.
#
# Factor keys must match those produced in factors.py.
HORIZONS: dict[str, dict[str, float]] = {
    # Days to a few weeks: technicals dominate, fundamentals barely matter.
    "short": {
        "mom_1m": 0.20,          # short-term momentum
        "mom_3m": 0.15,
        "rsi_reversion": 0.20,   # buy oversold / fade overbought
        "trend_50d": 0.15,       # above/below 50d MA
        "vol_inv": 0.10,         # prefer calmer names (risk control)
        "liquidity": 0.10,       # tradeable size
        "above_52w_low": 0.10,
    },
    # Weeks to a few months: classic medium-term momentum + a quality tilt.
    "mid": {
        "mom_12_1": 0.30,        # 12-1 month momentum (the workhorse factor)
        "mom_3m": 0.10,
        "trend_200d": 0.15,
        "earnings_growth": 0.15,
        "quality": 0.15,
        "vol_inv": 0.05,
        "value": 0.10,
    },
    # Months to years: value + quality + low-vol; momentum is a minor tilt.
    "long": {
        "value": 0.30,
        "quality": 0.25,
        "vol_inv": 0.15,         # low-volatility anomaly
        "profitability": 0.15,
        "mom_12_1": 0.10,
        "earnings_growth": 0.05,
    },
    # Contrarian / mispriced: beaten-down names near their lows WITH improving
    # fundamentals (cheap, oversold, low debt, growing). Designed to find value,
    # not catch falling knives — hence the heavy weight on quality + growth.
    "value": {
        "near_52w_low": 0.20,     # close to the 52-week low
        "rsi_reversion": 0.15,    # oversold (low RSI)
        "value": 0.20,            # cheap on fundamentals
        "quality": 0.15,          # strong balance sheet / low debt
        "earnings_growth": 0.15,  # growing revenue & earnings
        "profitability": 0.15,    # positive, improving margins
    },
    # Emerging / early movers: severely undervalued names that are JUST starting
    # to wake up. Blends a cheap, beaten-down entry (value + near-low) with
    # *improving fundamentals* (the real catalyst) and *early price confirmation*
    # (3-month momentum + a turn-up above the 50-day). The momentum tilt is what
    # separates "ready for take-off" from "value trap stuck at the bottom".
    "emerging": {
        "near_52w_low": 0.12,     # undervalued entry, near the lows
        "value": 0.15,            # cheap vs. fundamentals
        "earnings_growth": 0.22,  # revenue/earnings inflecting up = the catalyst
        "profitability": 0.10,    # margins turning positive
        "quality": 0.08,          # enough balance-sheet strength to survive
        "mom_3m": 0.18,           # early price confirmation (waking up)
        "trend_50d": 0.07,        # reclaiming its 50-day average
        "rsi_reversion": 0.08,    # still has room before overbought
    },
}

# Direction of each factor: +1 means higher raw value is better, -1 means lower
# is better. Used to orient z-scores before weighting.
FACTOR_DIRECTION: dict[str, int] = {
    "mom_1m": +1,
    "mom_3m": +1,
    "mom_12_1": +1,
    "rsi_reversion": +1,   # already transformed so higher = more attractive
    "trend_50d": +1,
    "trend_200d": +1,
    "vol_inv": +1,         # already inverted (higher = calmer)
    "liquidity": +1,
    "above_52w_low": +1,
    "near_52w_low": +1,    # higher = closer to the low (attractive for contrarian)
    "earnings_growth": +1,
    "quality": +1,
    "profitability": +1,
    "value": +1,           # composite already oriented (higher = cheaper)
}

# Winsorisation: clip cross-sectional z-scores to +/- this many std devs so a
# single outlier can't dominate a ranking.
ZSCORE_CLIP = 3.0
