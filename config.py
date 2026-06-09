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

# Fundamentals source: "edgar" (SEC, free, point-in-time, no rate limits) or
# "yahoo". EDGAR is primary; Yahoo backfills the rare names EDGAR can't resolve
# (foreign issuers, brand-new IPOs without filings) when the fallback is on.
FUNDAMENTALS_SOURCE = "edgar"
FUNDAMENTALS_FALLBACK = True

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
    # Emerging / early movers: companies ALREADY trending up with improving
    # fundamentals, bought at a still-reasonable price. This is the momentum +
    # growth + quality recipe — NOT a deep-value/contrarian bet.
    #
    # Why not contrarian? Point-in-time backtesting showed the original "buy
    # beaten-down names near their 52-week lows" version had NEGATIVE predictive
    # power in small/mid caps (it caught falling knives: IC ~-0.014, L/S ~-15%).
    # Flipping to a momentum lead turned it positive (IC ~+0.02, L/S ~+13%).
    # Momentum leads; earnings growth supplies the catalyst; a mild value tilt
    # avoids overpaying. See backtest.py --point-in-time.
    "emerging": {
        "mom_12_1": 0.30,         # established 12-1 month uptrend (the workhorse)
        "mom_3m": 0.15,           # recent acceleration
        "trend_200d": 0.10,       # above its long-term average
        "earnings_growth": 0.20,  # revenue/earnings inflecting up = the catalyst
        "quality": 0.10,          # balance-sheet strength
        "profitability": 0.05,    # positive/improving margins
        "value": 0.10,            # mild value tilt — don't overpay
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
