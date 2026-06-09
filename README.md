# Quant Screener

An objective, evidence-based screener and dashboard for stocks, ETFs, and funds.
It ranks an investable universe by well-documented academic factors, lets you
build a risk-balanced portfolio from the top names, and — critically —
**validates every signal with walk-forward, out-of-sample backtesting** so you
never trust a curve-fit ranking.

> **Honest expectations.** This does **not** predict individual winners with
> "impressive accuracy" — nothing reliably does. What it does is tilt the odds
> in your favor across baskets using factors that have decades of evidence
> behind them (value, momentum, quality, low-volatility). The edge is real but
> modest and statistical, not magical. The validation layer exists to keep us
> honest about exactly how much edge (if any) a given configuration has.

## What it gives you

- **Multi-horizon scoring.** Three profiles, because the signals that predict a
  2-week move differ from those that predict a 3-year hold:
  - **short** (days-weeks): momentum, RSI mean-reversion, trend, low-vol, liquidity
  - **mid** (weeks-months): 12-1 momentum, trend, earnings growth, quality
  - **long** (months-years): value, quality, low-volatility, profitability
- **Cross-sectional ranking** via winsorised z-scores → a composite `score` and
  a 0-100 percentile.
- **Risk-balanced portfolio builder** (inverse-vol / equal / score-weighted).
- **Walk-forward validation**: Information Coefficient (IC), IC t-stat, and a
  long-short equity curve net of transaction costs.
- **Interactive Streamlit dashboard** plus a CLI.

## Methodology lineage (what we borrowed)

| Source | What we took |
|--------|--------------|
| Microsoft **Qlib** | Cross-sectional factor-scoring & walk-forward backtest discipline (alpha-factor + IC evaluation pattern). |
| **TradingAgents** | The news/sentiment "analyst overlay" idea — planned as a *tilt + risk flag*, not the primary signal (Phase 2). |
| **pandas-ta-classic** | Technical-indicator definitions (RSI etc.), reimplemented directly to avoid version pinning. |

## Setup

```bash
cd quant-screener
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

CLI:

```bash
python screener.py --universe sp500 --horizon mid --top 20
python screener.py --universe stocks --horizon short
python screener.py --universe sp500 --horizon long --top 15 --news   # + free news tilt
python backtest.py --universe sp500 --horizon mid                    # validate first!
```

Universes: `stocks`, `etfs`, `all`, `sp500` (scraped live from Wikipedia + cached),
`sp500+etfs`, `ngx` (Nigerian Exchange).

### Nigerian Exchange (NGX) support

Yahoo Finance has no NGX coverage, so `ngx_data.py` uses free sources instead:

- **Prices & history**: AFX (afx.kwayisi.org) — ~10 years of daily prices per stock.
- **Sector classification**: NGX's official statistics API (merged into a local
  cache over time, since it only reports recently-traded names per call).

Honest limitation: deep fundamentals (P/E, EPS, ROE, margins, dividend yield) are
**not freely published** for NGX — confirmed ~0% coverage across free sources. So
the **Long-term** value/quality view is limited for Nigeria; favour the **short**
and **mid** (price-trend) horizons. Also note NGX trend-following did **not**
validate in backtesting (thin trading + a strong market-wide bull run), so treat
NGX rankings as visibility/context rather than a proven edge.

Dashboard:

```bash
streamlit run dashboard/app.py
```

## Data

Uses free `yfinance` data by default (no API key). The data layer
(`data_loader.py`) is the only place that knows about the provider, so swapping
in a paid source (Polygon, Tiingo, Financial Modeling Prep) for higher quality
and point-in-time fundamentals is a localized change.

## Project layout

```
quant-screener/
  config.py        # horizon profiles, factor weights, directions (the methodology)
  universe.py      # investable universes (stocks / etfs / all)
  data_loader.py   # pluggable price + fundamental fetch with caching
  factors.py       # factor engine (price + fundamental composites)
  scoring.py       # cross-sectional z-score → composite ranking
  screener.py      # CLI
  backtest.py      # walk-forward validation (anti-self-deception layer)
  dashboard/app.py # Streamlit UI
```

## News overlay (Phase 2 — done, 100% free)

`news.py` adds a TradingAgents-inspired "analyst" layer with **zero paid APIs**:

- **Headlines**: yfinance's free news feed + Google News RSS fallback (no keys).
- **Sentiment**: VADER (open-source, pure-Python lexicon) — no LLM tokens.
- **Risk flags**: keyword scan for lawsuits, downgrades, investigations, halts, etc.
- **Bounded tilt**: news nudges the factor score by at most ±0.15 (plus a small
  risk-flag haircut) — it can never override the objective factors.
- **Citations**: every headline keeps its source link and per-article sentiment.
- **Cheap by design**: runs only on the ranked **top-N** names, not the whole universe.

Use it via `--news` on the CLI or the "News overlay" tab in the dashboard.

## Roadmap

- **Point-in-time fundamentals** for honest fundamental-factor backtesting.
- **Russell 2000 / international** universes.
- **Regime awareness** (e.g. dial momentum vs. value by market regime).
- **Optional FinBERT** (free, open-source) as a heavier-but-better sentiment model.
