"""Walk-forward validation — the anti-self-deception layer.

This is the most important file in the project. A pretty ranking is worthless
until we've checked, out-of-sample and without lookahead, whether the score
actually relates to *future* returns.

What it does, at each monthly rebalance date, using ONLY data available up to
that date:
  1. compute price-based factors and the horizon score,
  2. measure the cross-sectional rank correlation (Information Coefficient, IC)
     between today's score and the forward holding-period return,
  3. form a long (top quintile) / short (bottom quintile) portfolio and track
     its return, net of a simple per-rebalance transaction cost.

Two modes:
  - default: validates PRICE-based factors only.
  - --point-in-time: also adds fundamentals from SEC EDGAR using only filings
    that were actually filed on or before each rebalance date — a genuine,
    lookahead-free test of the full (price + fundamentals) strategy. (Yahoo
    fundamentals can't do this; they're only a current snapshot.)

A decent factor combo shows: mean IC ~0.02-0.05+, an IC t-stat > 2, and a
positive, reasonably steady long-short curve. Anything spectacular on free daily
data is almost certainly a bug or lookahead — treat it with suspicion.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import config
import data_loader
import factors
import scoring
import universe as universe_mod


def _forward_return(prices: pd.DataFrame, start_idx: int, horizon_days: int) -> pd.Series:
    end_idx = start_idx + horizon_days
    if end_idx >= len(prices):
        return pd.Series(dtype=float)
    p0 = prices.iloc[start_idx]
    p1 = prices.iloc[end_idx]
    return (p1 / p0 - 1).dropna()


def walk_forward(
    prices: pd.DataFrame,
    horizon: str,
    rebalance_days: int | None = None,
    holding_days: int | None = None,
    quantile: float = 0.2,
    cost_bps: float = 10.0,
    warmup: int = 252,
    point_in_time: bool = False,
    tickers: list[str] | None = None,
) -> dict:
    """Run the walk-forward test. Returns a dict of summary stats + the IC series
    and the long-short equity curve.

    Holding/rebalance default to the strategy's own horizon (config.HOLDING_DAYS)
    with NON-overlapping windows (rebalance == hold), so the test reflects how the
    strategy is actually meant to be held and the compounded total return is real
    (no overlap inflation).

    If `point_in_time` is True, fundamental factors are added at each rebalance
    date using ONLY SEC filings filed on or before that date (no lookahead),
    enabling an honest test of the full (price + fundamentals) strategy.
    """
    if holding_days is None:
        holding_days = config.HOLDING_DAYS.get(horizon, 21)
    if rebalance_days is None:
        rebalance_days = holding_days  # non-overlapping windows = honest totals

    ics: list[float] = []
    ls_returns: list[float] = []
    dates: list = []

    cost = cost_bps / 1e4

    facts_map = None
    if point_in_time:
        import edgar_data
        cols = list(tickers) if tickers is not None else list(prices.columns)
        facts_map = edgar_data.preload_facts(cols)

    i = warmup
    while i + holding_days < len(prices):
        hist = prices.iloc[: i + 1]
        table = factors.price_factors(hist)
        if table.empty or len(table) < 10:
            i += rebalance_days
            continue

        if point_in_time and facts_map is not None:
            import edgar_data
            asof = pd.Timestamp(prices.index[i]).strftime("%Y-%m-%d")
            px_asof = {t: float(hist[t].dropna().iloc[-1])
                       for t in table.index
                       if t in hist.columns and hist[t].notna().any()}
            fdf = edgar_data.fundamentals_from_facts(
                facts_map, list(table.index), prices=px_asof, asof=asof
            )
            ff = factors.fundamental_factors(fdf)
            table = table.join(ff, how="left")

        scored = scoring.score(table, horizon=horizon)
        fwd = _forward_return(prices, i, holding_days)

        common = scored.index.intersection(fwd.index)
        if len(common) < 10:
            i += rebalance_days
            continue

        s = scored.loc[common, "score"]
        r = fwd.loc[common]

        # Information Coefficient: Spearman rank correlation score vs fwd return.
        ic = s.rank().corr(r.rank())
        if np.isfinite(ic):
            ics.append(ic)

        # Long-short quintile spread, net of round-trip cost.
        n = len(common)
        k = max(1, int(n * quantile))
        ordered = s.sort_values(ascending=False)
        longs = ordered.head(k).index
        shorts = ordered.tail(k).index
        ls = r.loc[longs].mean() - r.loc[shorts].mean() - 2 * cost
        ls_returns.append(float(ls))
        dates.append(prices.index[i])

        i += rebalance_days

    ics_arr = np.array(ics, dtype=float)
    ls_arr = np.array(ls_returns, dtype=float)

    mean_ic = float(np.nanmean(ics_arr)) if len(ics_arr) else float("nan")
    ic_t = (
        float(np.nanmean(ics_arr) / (np.nanstd(ics_arr) / np.sqrt(len(ics_arr))))
        if len(ics_arr) > 1 and np.nanstd(ics_arr) > 0
        else float("nan")
    )

    equity = pd.Series((1 + ls_arr).cumprod(), index=pd.DatetimeIndex(dates)) if len(ls_arr) else pd.Series(dtype=float)

    return {
        "n_periods": len(ls_arr),
        "mean_ic": mean_ic,
        "ic_t_stat": ic_t,
        "ic_hit_rate": float(np.mean(ics_arr > 0)) if len(ics_arr) else float("nan"),
        "ls_mean_per_period": float(np.mean(ls_arr)) if len(ls_arr) else float("nan"),
        "ls_win_rate": float(np.mean(ls_arr > 0)) if len(ls_arr) else float("nan"),
        "ls_total_return": float(equity.iloc[-1] - 1) if len(equity) else float("nan"),
        "ic_series": pd.Series(ics_arr, index=pd.DatetimeIndex(dates)) if len(dates) == len(ics_arr) else pd.Series(ics_arr),
        "equity_curve": equity,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Walk-forward factor validation")
    ap.add_argument(
        "--universe", default="us_all",
        choices=["us_all", "emerging", "etfs", "commodities", "ngx",
                 "stocks", "all", "sp500", "sp500+etfs", "sp500+popular"],
    )
    ap.add_argument(
        "--horizon", default="mid",
        choices=["short", "mid", "long", "value", "emerging"],
    )
    ap.add_argument("--period", default="5y",
                    help="price history to pull (e.g. 5y, 10y, max). Longer history "
                         "gives more independent windows for long-horizon strategies.")
    ap.add_argument("--holding-days", type=int, default=None,
                    help="override the strategy's natural hold (config.HOLDING_DAYS)")
    ap.add_argument("--rebalance-days", type=int, default=None,
                    help="override rebalance cadence (defaults to holding = non-overlapping)")
    ap.add_argument("--cost-bps", type=float, default=10.0)
    ap.add_argument(
        "--point-in-time", action="store_true",
        help="add fundamentals via SEC EDGAR using only filings known at each "
             "date (honest test of the full strategy; US only)",
    )
    args = ap.parse_args()

    prov = data_loader.provider_for(args.universe)
    tickers = universe_mod.get_universe(args.universe)
    print(f"Loading {args.period} prices for {len(tickers)} tickers...")
    prices = prov.get_prices(
        tickers, period=args.period, universe_key=f"{args.universe}_bt_{args.period}"
    )

    pit = args.point_in_time and args.universe != "ngx"
    if pit:
        print("Point-in-time mode: loading SEC EDGAR filings (cached after first run)...")

    res = walk_forward(
        prices,
        horizon=args.horizon,
        rebalance_days=args.rebalance_days,
        holding_days=args.holding_days,
        cost_bps=args.cost_bps,
        point_in_time=pit,
        tickers=tickers,
    )

    print(f"\n=== Walk-forward | universe={args.universe} | horizon={args.horizon} ===")
    print(f"  periods tested      : {res['n_periods']}")
    print(f"  mean IC             : {res['mean_ic']:.4f}")
    print(f"  IC t-stat           : {res['ic_t_stat']:.2f}   (>2 is meaningful)")
    print(f"  IC hit rate         : {res['ic_hit_rate']:.1%}")
    print(f"  L/S mean/period     : {res['ls_mean_per_period']:.4%}")
    print(f"  L/S win rate        : {res['ls_win_rate']:.1%}")
    print(f"  L/S total return    : {res['ls_total_return']:.1%}")
    mode = ("price + point-in-time SEC fundamentals"
            if pit else "price factors only")
    print(
        f"\nMode: {mode}. "
        "Spectacular numbers = suspect a bug or lookahead."
    )


if __name__ == "__main__":
    main()
