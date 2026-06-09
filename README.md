# Quant Screener

An objective, evidence-based screener and dashboard for stocks, ETFs, funds,
and commodities. It ranks an investable universe by well-documented academic
factors, explains every pick in plain English, and — critically —
**validates each strategy with walk-forward, out-of-sample, point-in-time
backtesting** so you never trust a curve-fit ranking.

> **Honest expectations.** This does **not** predict individual winners with
> "impressive accuracy" — nothing reliably does. What it does is tilt the odds
> in your favour across baskets using factors that have decades of evidence
> behind them (value, momentum, quality, low-volatility). The edge is real but
> modest and statistical, not magical. The validation layer (below) exists to
> keep us honest about exactly how much edge — if any — a given strategy has,
> and the results are reported warts-and-all.

## What it gives you

- **Five strategies (horizons)**, because the signals that predict a 2-week
  move differ from those that predict a 3-year hold. See the table below.
- **Plain-English output**: every name gets a **Strong Buy / Buy / Hold /
  Weak / Avoid** rating, the company's real name, the top reasons it ranks
  well, and its main concerns — no `mom_12_1` jargon in your face.
- **Cross-sectional ranking** via winsorised z-scores → a composite `score`
  and a 0-100 percentile (how a name stacks up against the rest of the field).
- **Point-in-time fundamentals from SEC EDGAR** (free, no rate limits) so
  fundamental-factor strategies can be backtested honestly, with no lookahead.
- **Two-stage funnel** so large universes stay fast and stay within free-data
  limits: price-screen the *whole* universe cheaply, then pull fundamentals
  only for the top finalists.
- **"Heads-up" flags** (context only — never part of the score): short interest
  and earnings-date proximity, so you can size/time a trade more sensibly.
- **Free news/sentiment overlay** (optional): a bounded tilt + risk flags from
  free headlines, never able to override the objective factors.
- **Walk-forward validation** built in: Information Coefficient (IC), IC t-stat,
  and a long-short equity curve net of transaction costs.
- **Interactive Streamlit dashboard** plus a CLI.

## The five strategies

Weights live in `config.py` (`HORIZONS`) — explicit and auditable.

| Strategy | Hold | Leans on |
|----------|------|----------|
| **short** | ~2 weeks | a fast trend-follower: 3-month & 12-1 momentum, above its 50/200-day averages, off its lows, calmer names preferred |
| **mid** | ~1 month | 12-1 momentum (the workhorse), trend, earnings growth, quality, mild value |
| **long** | ~6 months | quality value: quality + reasonable price + long-momentum confirmation + profitability (skips value traps) |
| **value** | ~3 months | cheap-but-working: leads with value, but demands quality + momentum confirmation so it skips falling knives |
| **emerging** | ~3–6 months | early movers: already trending up with improving earnings, bought at a still-reasonable price (momentum + growth + quality) |

These weights were **tuned against point-in-time backtests** (see below), not
hand-waved. Earlier versions of `short`/`long`/`value` paired momentum with
mean-reversion / deep-value tilts that *fought each other* and tested negative;
they were re-tuned to lead with the signals that actually validated (momentum +
quality, with confirmation that a name isn't still falling).

## Does it actually work? (validation)

The backtester (`backtest.py`) does a walk-forward test: at each rebalance it
ranks the universe using *only* data available at that point in time
(fundamentals pulled as-of the filing date from EDGAR), forms a top-quintile
vs. bottom-quintile long/short basket, and measures the spread net of costs.
Crucially, **each strategy is tested over its own holding period with
non-overlapping windows** (`config.HOLDING_DAYS`), so a 6-month strategy is
judged over 6 months — not crammed into a 1-month box — and the compounded
total return is real (no overlap inflation).

Latest run (~2021–2026, point-in-time fundamentals):

| Strategy | Hold | S&P 500 (large-cap) | Emerging (small/mid-cap) |
|----------|------|---------------------|--------------------------|
| **mid**      | 21d  | IC +0.021, hit 66%, **L/S +15.4%** ✅ | IC +0.021, +0.9% (flat) |
| **value**    | 63d  | IC +0.029, hit 60%, **L/S +20.8%** ✅ | IC +0.028, +1.3% |
| **emerging** | 63d  | —                                     | IC +0.034, hit 73%, **L/S +4.4%** ✅ |
| **short**    | 10d  | IC +0.004, ~flat (−0.4%) ⚠️           | — |
| **long**     | 126d | IC +0.026, hit 86%, but only n=7 ⚠️   | — |

**What this means, honestly:**

- The re-tune **flipped `short`/`long`/`value` from anti-predictive to
  predictive** — every strategy now has a positive Information Coefficient,
  where three of them used to be negative.
- **`mid` (large caps), `value` (large caps) and `emerging` (small/mid caps)
  are the clear, profitable performers** — lean on these.
- **`short` is roughly break-even** now (up from −13%): a small positive edge
  before costs, easily eaten by trading frictions. Treat it as a timing aid,
  not an alpha engine.
- **`long` is directionally positive** (IC +0.026, 86% of periods positive) but
  there are only ~7 non-overlapping 6-month windows in 5 years — too few to
  call statistically. A 6-month strategy simply can't be robustly validated on
  5 years of history; treat it as promising-but-unproven.
- These are **long/short factor spreads**, not a long-only portfolio's return,
  and one ~5-year window is one regime. Re-run the validation before trusting
  any configuration: `python backtest.py --universe sp500 --horizon value
  --point-in-time`.

Re-validate any strategy from the **"Can we trust this?"** tab in the dashboard,
or from the CLI (use `--point-in-time` for the fundamental strategies).

## Universes

| Pick (dashboard) | Key | What's in it |
|------------------|-----|--------------|
| 🇺🇸 All US Stocks | `us_all` | S&P 1500 (large+mid+small) + popular & thematic early movers |
| 🚀 Emerging Stocks | `emerging` | Small/mid-caps (S&P 400/600 + popular + thematic), **excludes** mega-caps |
| 📦 ETFs & Funds | `etfs` | ~55 broad/factor/sector/thematic ETFs (price-only) |
| 🛢️ Commodities & Metals | `commodities` | Liquid commodity/metal ETFs & ETNs (price-only) |
| 🇳🇬 Nigerian Exchange | `ngx` | NGX-listed stocks via free sources (see below) |

Index membership (S&P 500/400/600) is scraped free from Wikipedia and cached.
The first scan of a large universe takes ~1-2 min while data loads, then it's
cached. Legacy CLI keys still work: `stocks`, `all`, `sp500`, `sp500+etfs`,
`sp500+popular`.

## Data sources (all free, no API keys)

| Data | Source |
|------|--------|
| US prices & history | `yfinance` (with `curl_cffi` browser impersonation for resilience) |
| **US fundamentals (point-in-time)** | **SEC EDGAR `companyfacts` API** — official, free, no rate-limit headaches |
| US fundamentals fallback | `yfinance` (for the rare names EDGAR can't resolve: foreign issuers, brand-new IPOs) |
| Short interest & earnings dates | `yfinance` (heads-up flags only) |
| News & sentiment | `yfinance` news + Google News RSS, scored with VADER |
| NGX prices & history | AFX (afx.kwayisi.org) |
| NGX sectors | NGX's official statistics API (merged into a local cache) |

`config.py` controls the fundamentals source (`FUNDAMENTALS_SOURCE = "edgar"`,
`FUNDAMENTALS_FALLBACK = True`). `data_loader.py` is the only place that knows
about providers, so swapping in a paid source later is a localized change.

### Nigerian Exchange (NGX) support

Yahoo has no NGX coverage, so `ngx_data.py` uses AFX (prices/history) and NGX's
official stats API (sectors). **Honest limitation:** deep fundamentals
(P/E, EPS, ROE, margins) are **not freely published** for NGX, so the
**long-term** value/quality view is limited there — favour the **short** and
**mid** (price-trend) horizons. NGX trend-following also did **not** validate in
backtesting (thin trading + a market-wide bull run), so treat NGX rankings as
visibility/context rather than a proven edge.

## Setup

```bash
cd quant-screener
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

CLI:

```bash
python screener.py --universe us_all --horizon mid --top 20
python screener.py --universe emerging --horizon emerging --top 20
python screener.py --universe us_all --horizon mid --news        # + free news tilt
python backtest.py --universe sp500 --horizon mid --point-in-time # validate first!
python backtest.py --universe emerging --horizon emerging --point-in-time
```

`--universe`: `us_all`, `emerging`, `etfs`, `commodities`, `ngx`
(+ legacy `stocks`, `all`, `sp500`, `sp500+etfs`, `sp500+popular`).
`--horizon`: `short`, `mid`, `long`, `value`, `emerging`.
Use `--point-in-time` on `backtest.py` for any fundamental strategy
(`mid`/`long`/`value`/`emerging`) to avoid lookahead bias.

Dashboard:

```bash
streamlit run dashboard/app.py
```

The dashboard defaults to the **Emerging Stocks** universe + **Emerging**
strategy (the early-mover lens). An optional password gate (`_check_password`)
lets you share it via Streamlit Community Cloud.

## Project layout

```
quant-screener/
  config.py        # horizon/strategy weights, factor directions, data-source switch
  universe.py      # investable universes (us_all / emerging / etfs / commodities / ngx)
  data_loader.py   # US price + fundamental fetch (yfinance + curl_cffi), caching
  edgar_data.py    # SEC EDGAR point-in-time fundamentals provider
  ngx_data.py      # Nigerian Exchange adapter (AFX prices + NGX sectors)
  factors.py       # factor engine (price + fundamental composites)
  scoring.py       # cross-sectional z-score → composite ranking
  pipeline.py      # two-stage funnel: price-screen all → fundamentals for finalists
  news.py          # free news/sentiment overlay (VADER), bounded tilt + risk flags
  labels.py        # plain-English translation layer (ratings, reasons, heads-up)
  screener.py      # CLI
  backtest.py      # walk-forward, point-in-time validation (anti-self-deception layer)
  dashboard/app.py # Streamlit UI
```

## Methodology lineage (what we borrowed)

| Source | What we took |
|--------|--------------|
| Microsoft **Qlib** | Cross-sectional factor-scoring & walk-forward backtest discipline (alpha-factor + IC evaluation pattern). |
| **TradingAgents** | The news/sentiment "analyst overlay" idea — a *tilt + risk flag*, not the primary signal. |
| **pandas-ta-classic** | Technical-indicator definitions (RSI etc.), reimplemented directly to avoid version pinning. |

## Roadmap

- **Longer history for `long`** — 5 years only yields ~7 non-overlapping
  6-month windows, too few to validate; pull more history to confirm the edge.
- **Regime awareness** (dial momentum vs. value by market regime).
- **Russell 2000 / international** universes.
- **Optional FinBERT** (free, open-source) as a heavier-but-better sentiment model.
