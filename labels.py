"""Plain-English translation layer.

Turns the quant internals (factor codes, z-scores, percentiles) into language a
non-finance person can read at a glance: "Strong Buy", "Good value",
"12-month price trend", and short one-line explanations.

Nothing here changes the math — it only renames and summarises for humans.
"""

from __future__ import annotations

import config

# ---------------------------------------------------------------------------
# Friendly factor names + one-line explanations (no jargon)
# ---------------------------------------------------------------------------
# (short label, plain-English explanation)
FACTOR_LABELS: dict[str, tuple[str, str]] = {
    "mom_1m": ("Recent momentum (1 month)", "How the price has trended over the past month."),
    "mom_3m": ("Momentum (3 months)", "Price trend over the past three months."),
    "mom_12_1": ("Long-term momentum (1 year)", "Up-trend over the past year — historically a strong signal."),
    "rsi_reversion": ("Bounce-back potential", "Looks oversold recently and may rebound."),
    "trend_50d": ("Above its 2-month average", "Trading above its recent average price (a healthy sign)."),
    "trend_200d": ("Above its 1-year average", "Trading above its long-term average price."),
    "vol_inv": ("Steadiness", "Calmer price swings — a smoother ride."),
    "liquidity": ("Easy to trade", "Plenty of daily trading volume."),
    "above_52w_low": ("Off its lows", "How far it has recovered above its 1-year low."),
    "near_52w_low": ("Near its 52-week low", "Trading close to its 1-year low — potential value if the business is improving."),
    "earnings_growth": ("Growing profits", "The company is growing its earnings and sales."),
    "quality": ("Company quality", "Strong, well-run business with low debt."),
    "profitability": ("Profitability", "Healthy profit margins."),
    "value": ("Good value", "Reasonably priced — not overpriced vs. its fundamentals."),
}

# ---------------------------------------------------------------------------
# Horizon descriptions
# ---------------------------------------------------------------------------
HORIZON_LABELS: dict[str, str] = {
    "short": "Quick trades (days to weeks)",
    "mid": "Medium term (weeks to months)",
    "long": "Long-term hold (months to years)",
    "value": "Value / Mispriced (contrarian)",
}

HORIZON_BLURB: dict[str, str] = {
    "short": "Built for fast moves — leans on recent price action and steadiness.",
    "mid": "A balanced mix of price trend, profit growth and company quality.",
    "long": "Built for patient investors — favours good value, quality and steady businesses.",
    "value": "Hunts beaten-down names near their lows with improving fundamentals — "
             "cheap, oversold, low debt, growing revenue. Aims for mispriced assets, "
             "not falling knives.",
}

UNIVERSE_LABELS: dict[str, str] = {
    "all": "🇺🇸 Popular US stocks + ETFs",
    "stocks": "🇺🇸 Popular large US stocks",
    "etfs": "🇺🇸 ETFs & funds",
    "sp500": "🇺🇸 S&P 500 (500 biggest US companies)",
    "sp500+etfs": "🇺🇸 S&P 500 + ETFs/funds",
    "sp500+popular": "🇺🇸 S&P 500 + popular mid-caps (widest US net)",
    "ngx": "🇳🇬 Nigerian Exchange (NGX) — all listed companies",
}


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------
def rating(score_pct: float) -> tuple[str, str]:
    """Map a 0-100 percentile rank to a plain-English rating + emoji."""
    if score_pct >= 85:
        return "Strong Buy", "🟢"
    if score_pct >= 65:
        return "Buy", "🟢"
    if score_pct >= 40:
        return "Hold / Neutral", "🟡"
    if score_pct >= 20:
        return "Weak", "🟠"
    return "Avoid", "🔴"


def strength_word(z: float) -> str:
    """Turn a z-score into a simple word."""
    if z >= 1.0:
        return "Excellent"
    if z >= 0.3:
        return "Good"
    if z > -0.3:
        return "Average"
    if z > -1.0:
        return "Below average"
    return "Poor"


def strength_dots(z: float) -> str:
    """A simple 5-dot visual for a z-score."""
    if z >= 1.0:
        n = 5
    elif z >= 0.3:
        n = 4
    elif z > -0.3:
        n = 3
    elif z > -1.0:
        n = 2
    else:
        n = 1
    return "●" * n + "○" * (5 - n)


# ---------------------------------------------------------------------------
# "Why" summaries
# ---------------------------------------------------------------------------
def factor_contributions(row, horizon: str) -> list[tuple[str, float]]:
    """Return [(factor_key, contribution)] sorted high→low for a scored row."""
    weights = config.HORIZONS[horizon]
    out = []
    for f, w in weights.items():
        zc = f"z_{f}"
        if zc in row and row[zc] == row[zc]:  # not NaN
            out.append((f, w * float(row[zc])))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def top_reasons(row, horizon: str, n: int = 3) -> list[str]:
    """Plain-English list of the biggest positive drivers."""
    contribs = factor_contributions(row, horizon)
    reasons = [FACTOR_LABELS.get(f, (f, ""))[0] for f, c in contribs if c > 0]
    return reasons[:n]


def top_concerns(row, horizon: str, n: int = 2) -> list[str]:
    """Plain-English list of the biggest negative drivers (the weak spots)."""
    contribs = factor_contributions(row, horizon)
    concerns = [FACTOR_LABELS.get(f, (f, ""))[0] for f, c in reversed(contribs) if c < 0]
    return concerns[:n]


# ---------------------------------------------------------------------------
# Heads-up flags (context only — never part of the score)
# ---------------------------------------------------------------------------
# Thresholds chosen to surface genuinely notable cases without crying wolf.
_EARNINGS_SOON_DAYS = 10      # earnings within ~2 weeks = real gap risk
_SHORT_HEAVY = 0.20           # >20% of float short = unusually crowded
_SHORT_ELEVATED = 0.10        # >10% = worth noting


def _isnum(x) -> bool:
    try:
        return x == x and x is not None  # filters NaN/NA/None
    except Exception:
        return False


def event_flags(short_pct=None, days_to_earnings=None) -> list[str]:
    """Short, neutral 'heads-up' tags for the ranking table.

    These never move the score — they just warn you about event/positioning risk
    so you can size or time a trade more sensibly.
    """
    flags: list[str] = []
    if _isnum(days_to_earnings) and 0 <= days_to_earnings <= _EARNINGS_SOON_DAYS:
        d = int(round(days_to_earnings))
        flags.append("📅 Earnings ~today" if d == 0 else f"📅 Earnings in ~{d}d")
    if _isnum(short_pct):
        if short_pct >= _SHORT_HEAVY:
            flags.append(f"🩳 Heavily shorted ({short_pct * 100:.0f}%)")
        elif short_pct >= _SHORT_ELEVATED:
            flags.append(f"🩳 Elevated short ({short_pct * 100:.0f}%)")
    return flags


def short_interest_note(short_pct) -> str:
    """One-line, balanced read on a stock's short interest for the detail view."""
    if not _isnum(short_pct):
        return "Short interest: not available."
    pct = short_pct * 100
    if short_pct >= _SHORT_HEAVY:
        return (
            f"Short interest is high ({pct:.0f}% of float). On average heavily-shorted "
            "stocks underperform, so treat this as a caution — but it can also fuel a "
            "short squeeze if a strong catalyst hits. Expect extra volatility."
        )
    if short_pct >= _SHORT_ELEVATED:
        return (
            f"Short interest is somewhat elevated ({pct:.0f}% of float) — a modest "
            "caution sign and a source of added volatility."
        )
    return f"Short interest is low ({pct:.0f}% of float) — little bearish positioning."


def earnings_note(days_to_earnings) -> str:
    """One-line read on earnings proximity for the detail view."""
    if not _isnum(days_to_earnings) or days_to_earnings < 0:
        return "Next earnings date: not available."
    d = int(round(days_to_earnings))
    if d <= _EARNINGS_SOON_DAYS:
        return (
            f"Earnings in ~{d} day(s). Prices can gap sharply around results — "
            "consider waiting until after, or sizing smaller."
        )
    return f"Next earnings in ~{d} days — no immediate event risk."
