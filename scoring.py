"""Cross-sectional scoring.

Turns the raw factor table into a ranked, horizon-specific score. The score is a
weighted sum of winsorised cross-sectional z-scores. It is a RELATIVE ranking
within the universe, not a return forecast — by construction it answers
"which names look most attractive on these factors right now", which is the
honest, evidence-based version of the question.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


def _zscore(s: pd.Series) -> pd.Series:
    s = s.astype(float)
    sd = s.std(skipna=True)
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    z = (s - s.mean(skipna=True)) / sd
    return z.clip(-config.ZSCORE_CLIP, config.ZSCORE_CLIP)


def score(factor_table: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """Return the factor table augmented with per-factor z-scores, a composite
    `score`, a 0-100 `score_pct`, and a `rank`, sorted best-first."""
    if horizon not in config.HORIZONS:
        raise ValueError(f"Unknown horizon '{horizon}'. Options: {list(config.HORIZONS)}")

    weights = config.HORIZONS[horizon]
    df = factor_table.copy()

    composite = pd.Series(0.0, index=df.index)
    total_w = 0.0

    for factor, w in weights.items():
        if factor not in df.columns:
            continue
        direction = config.FACTOR_DIRECTION.get(factor, +1)
        z = _zscore(df[factor]) * direction
        # If a factor is entirely missing for a name, treat its contribution as
        # neutral (0) rather than dropping the name from the ranking.
        z = z.fillna(0.0)
        df[f"z_{factor}"] = z
        composite = composite + w * z
        total_w += w

    if total_w > 0:
        composite = composite / total_w

    df["score"] = composite
    # Percentile rank for an intuitive 0-100 readout.
    df["score_pct"] = (df["score"].rank(pct=True) * 100).round(1)
    df = df.sort_values("score", ascending=False)
    df["rank"] = range(1, len(df) + 1)
    return df


def top(factor_table: pd.DataFrame, horizon: str, n: int = 15) -> pd.DataFrame:
    """Convenience: top-N names for a horizon with the most useful columns."""
    scored = score(factor_table, horizon)
    cols = ["rank", "score", "score_pct"] + [
        f"z_{f}" for f in config.HORIZONS[horizon] if f"z_{f}" in scored.columns
    ]
    return scored[cols].head(n)
