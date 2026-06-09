"""Command-line screener.

Examples
--------
    python screener.py --universe all --horizon mid --top 20
    python screener.py --universe stocks --horizon short
    python screener.py --universe etfs --horizon long --refresh
"""

from __future__ import annotations

import argparse

import pandas as pd

import config
import pipeline
import universe as universe_mod

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)


def run(
    universe_name: str,
    horizon: str,
    top_n: int,
    refresh: bool,
    with_news: bool = False,
):
    n = len(universe_mod.get_universe(universe_name))
    print(f"Screening {n} tickers ({universe_name}) — price screen, then "
          "fundamentals on the finalists...")
    scored = pipeline.build_scored(universe_name, horizon, refresh=refresh)

    if with_news:
        import news as news_mod

        print(f"Running free news/sentiment overlay on top {top_n}...")
        scored, _ = news_mod.attach_to_scores(scored, top_n=top_n)

    return scored, with_news


def main() -> None:
    ap = argparse.ArgumentParser(description="Evidence-based stock/ETF screener")
    ap.add_argument(
        "--universe", default="us_all",
        choices=["us_all", "emerging", "etfs", "commodities", "ngx",
                 "stocks", "all", "sp500", "sp500+etfs", "sp500+popular"],
    )
    ap.add_argument(
        "--horizon", default="mid",
        choices=["short", "mid", "long", "value", "emerging"],
    )
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--refresh", action="store_true", help="bypass cache")
    ap.add_argument("--news", action="store_true", help="add free news/sentiment tilt")
    args = ap.parse_args()

    scored, with_news = run(args.universe, args.horizon, args.top, args.refresh, args.news)

    print(f"\n=== Top {args.top} | universe={args.universe} | horizon={args.horizon} ===\n")
    if with_news:
        cols = ["rank", "score", "news_label", "news_sentiment", "news_tilt",
                "risk_flags", "adj_score", "adj_rank"]
        view = scored[cols].head(args.top)
    else:
        zcols = [f"z_{f}" for f in config.HORIZONS[args.horizon]
                 if f"z_{f}" in scored.columns]
        view = scored[["rank", "score", "score_pct"] + zcols].head(args.top)
    print(view.round(3).to_string())
    print(
        "\nNote: 'score' is a RELATIVE cross-sectional ranking within this "
        "universe, not a return forecast. News is a BOUNDED tilt, never the "
        "primary driver. Always validate with backtest.py before trusting a tilt."
    )


if __name__ == "__main__":
    main()
