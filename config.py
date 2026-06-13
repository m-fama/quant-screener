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
    # Days to ~2 weeks: a fast trend/momentum follower. The original mix paired
    # short-term momentum WITH RSI mean-reversion (buy oversold) — the two fight
    # each other and tested clearly negative. Re-tuned to pure short-window
    # trend-following: ~break-even recently, still negative over a full cycle, so
    # treat it as a timing aid, not alpha. No fundamentals (they barely matter
    # over days).
    "short": {
        "mom_3m": 0.25,          # recent 3-month momentum
        "trend_50d": 0.20,       # above its 2-month average
        "trend_200d": 0.15,      # above its long-term average (trend intact)
        "mom_12_1": 0.15,        # broader uptrend behind the move
        "above_52w_low": 0.15,   # off its lows, not bottom-fishing
        "vol_inv": 0.10,         # prefer calmer names (risk control)
    },
    # Weeks to a few months: classic medium-term momentum + a quality tilt.
    # Strongest in the recent ~5y (large-cap IC ~+0.02, 66% hit, +15% L/S at ~21d)
    # but ~flat over the full 2010-2026 sample — a regime-dependent edge, not an
    # all-weather one. See the README validation section.
    "mid": {
        "mom_12_1": 0.30,        # 12-1 month momentum (the workhorse factor)
        "mom_3m": 0.10,
        "trend_200d": 0.15,
        "earnings_growth": 0.15,
        "quality": 0.15,
        "vol_inv": 0.05,
        "value": 0.10,
    },
    # Months to years: "quality value held long." The original value + low-vol
    # lead was strongly ANTI-predictive in the 2021-2026 large-cap regime
    # (point-in-time IC ~-0.03, t ~-2.4). Re-tuned to lead with quality + a
    # long-momentum confirmation so it buys good, reasonably-priced businesses
    # that are actually working. Honest caveat: a 6-month hold yields too few
    # independent windows to validate on 5y, and over the full 2010-2026 sample
    # it's still ~flat/negative. Treat as a tilt, not a proven edge.
    "long": {
        "quality": 0.30,          # strong, well-run businesses first
        "mom_12_1": 0.25,         # confirmation the market agrees (no value traps)
        "value": 0.20,            # still reasonably priced
        "profitability": 0.15,    # healthy, durable margins
        "earnings_growth": 0.10,  # growing
    },
    # Cheap-but-working value (a few months). The original "buy near 52-week lows
    # + oversold" version caught falling knives and lost. Re-tuned to lead with
    # cheapness BUT require quality and recent/long-term momentum confirmation so
    # it skips names that are still bleeding. The most consistent strategy in
    # testing — positive in BOTH the recent 5y (IC ~+0.03, +21% L/S) and the full
    # 2010-2026 sample (IC ~+0.005, +8% L/S) — though the long-run edge is modest.
    "value": {
        "value": 0.25,            # cheap on fundamentals (leads)
        "quality": 0.20,          # strong balance sheet / low debt
        "mom_12_1": 0.15,         # the market is starting to agree
        "earnings_growth": 0.15,  # growing revenue & earnings
        "profitability": 0.15,    # positive, improving margins
        "trend_200d": 0.10,       # above its long-term average (not a knife)
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

# Holding period (trading days) each strategy is designed for. The validator
# tests every strategy over ITS OWN horizon, with non-overlapping windows
# (rebalance == hold), so backtest results reflect how the strategy is actually
# meant to be held instead of forcing everything into a 1-month box.
HOLDING_DAYS: dict[str, int] = {
    "short": 10,    # ~2 weeks
    "mid": 21,      # ~1 month
    "long": 126,    # ~6 months
    "value": 63,    # ~3 months
    "emerging": 63, # ~3 months (a slice of the 6-12 month thesis)
}

# Winsorisation: clip cross-sectional z-scores to +/- this many std devs so a
# single outlier can't dominate a ranking.
ZSCORE_CLIP = 3.0
