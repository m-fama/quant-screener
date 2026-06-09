"""Streamlit dashboard for the quant screener — designed for non-experts.

Plain-English ratings (Strong Buy / Buy / Hold / Weak / Avoid), company names,
and simple explanations. The technical details are tucked into expanders for
anyone curious.

Run from the project root:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import html as _html
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Make the project root importable when launched from anywhere.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import data_loader  # noqa: E402
import factors  # noqa: E402
import labels  # noqa: E402
import scoring  # noqa: E402
import universe as universe_mod  # noqa: E402
from backtest import walk_forward  # noqa: E402

st.set_page_config(page_title="Quant Screener", page_icon="📊", layout="wide")


def _check_password() -> None:
    """Optional, zero-config password gate for public hosting.

    Stays fully open unless an ``app_password`` secret is set (in Streamlit
    Cloud: Manage app → Settings → Secrets). When set, visitors must enter it
    once per session before seeing anything.
    """
    try:
        pw = st.secrets.get("app_password")
    except Exception:
        pw = None
    if not pw:
        return  # no password configured → open access
    if st.session_state.get("_auth_ok"):
        return
    st.title("🔒 Quant Screener")
    entered = st.text_input("Enter the access password", type="password")
    if not entered:
        st.stop()
    if entered == pw:
        st.session_state["_auth_ok"] = True
        st.rerun()
    else:
        st.error("Incorrect password — try again.")
        st.stop()


_check_password()


@st.cache_data(ttl=60 * 60 * 3, show_spinner=False)
def load_factor_table(universe_name: str) -> pd.DataFrame:
    prov = data_loader.provider_for(universe_name)
    tickers = universe_mod.get_universe(universe_name)
    prices = prov.get_prices(tickers, period="3y", universe_key=universe_name)
    volume = prov.get_volume(tickers, period="6mo")
    fundamentals = None if universe_name == "etfs" else prov.get_fundamentals(tickers)
    return factors.build_factor_table(prices, fundamentals=fundamentals, volume=volume)


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def load_names(universe_name: str) -> dict:
    prov = data_loader.provider_for(universe_name)
    tickers = universe_mod.get_universe(universe_name)
    return prov.get_names(tickers)


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def load_prices(universe_name: str, period: str = "5y") -> pd.DataFrame:
    prov = data_loader.provider_for(universe_name)
    tickers = universe_mod.get_universe(universe_name)
    return prov.get_prices(tickers, period=period, universe_key=f"{universe_name}_dash")


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def load_sectors(universe_name: str) -> dict:
    if universe_name == "ngx":
        import ngx_data
        return ngx_data.get_sectors()
    return {}


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def load_signals(universe_name: str) -> pd.DataFrame:
    """Context-only signals (short interest, days-to-earnings). Never scored."""
    if universe_name == "etfs":
        return pd.DataFrame()
    prov = data_loader.provider_for(universe_name)
    tickers = universe_mod.get_universe(universe_name)
    try:
        return prov.get_signals(tickers)
    except Exception:
        return pd.DataFrame()


def name_of(names: dict, ticker: str) -> str:
    return names.get(ticker, ticker)


# ---------------------------------------------------------------------------
# Sidebar — friendly controls
# ---------------------------------------------------------------------------
st.sidebar.title("Quant Screener")

universe_name = st.sidebar.selectbox(
    "What should we look at?",
    ["all", "stocks", "etfs", "sp500", "sp500+etfs", "sp500+popular", "ngx"],
    index=0,
    format_func=lambda u: labels.UNIVERSE_LABELS.get(u, u),
    help="The S&P 500 lists load ~500 companies the first time and may take a "
         "few minutes; saved afterwards so it's fast next time. For hunting "
         "undervalued names, use 'S&P 500 + popular mid-caps' with the "
         "'Value / Mispriced' strategy.",
)

if universe_name == "ngx":
    st.sidebar.info(
        "🇳🇬 Nigerian market — prices in Naira (₦), possibly slightly delayed. "
        "Full price history + sector data available, so trend-based ratings and "
        "sector context work well. Note: company financials (P/E, margins) aren't "
        "freely published for NGX, so the **Long-term** value/quality view is "
        "limited here — favour **Quick** and **Medium** horizons."
    )

horizon = st.sidebar.selectbox(
    "Strategy",
    ["short", "mid", "long", "value"],
    index=1,
    format_func=lambda h: labels.HORIZON_LABELS[h],
)
st.sidebar.info(labels.HORIZON_BLURB[horizon])

top_n = st.sidebar.slider("How many to show?", 5, 40, 15)

with st.sidebar.expander("What do the ratings mean?"):
    st.markdown(
        "- 🟢 **Strong Buy** — looks excellent vs. the others right now\n"
        "- 🟢 **Buy** — looks attractive\n"
        "- 🟡 **Hold / Neutral** — middle of the pack, nothing special\n"
        "- 🟠 **Weak** — below average\n"
        "- 🔴 **Avoid** — looks poor right now\n\n"
        "Ratings are **relative** — how each name compares to the others in the "
        "list today. This is research to help you think, **not** financial advice."
    )

# ---------------------------------------------------------------------------
# Load + score
# ---------------------------------------------------------------------------
st.title("Quant Screener: Stocks & Assets Worth Buying Now")
st.caption(
    "Factor-based rankings for US stocks, ETFs and the Nigerian Exchange — "
    "price trend, value, quality and steadiness, scored side by side."
)

with st.spinner("Crunching the numbers..."):
    table = load_factor_table(universe_name)
    names = load_names(universe_name)
    sectors = load_sectors(universe_name)
    signals = load_signals(universe_name)
    scored = scoring.score(table, horizon=horizon)


def signal_for(ticker: str):
    """Return (short_pct, days_to_earnings) for a ticker, or (None, None)."""
    if signals is None or signals.empty or ticker not in signals.index:
        return None, None
    r = signals.loc[ticker]
    return r.get("short_pct"), r.get("days_to_earnings")

# Attach friendly columns
scored["Company"] = [name_of(names, t) for t in scored.index]
scored["Rating"], scored["_emoji"] = zip(*[labels.rating(p) for p in scored["score_pct"]])


def build_reasons(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    likes, watch = [], []
    for _, row in df.iterrows():
        r = labels.top_reasons(row, horizon, n=3)
        c = labels.top_concerns(row, horizon, n=2)
        likes.append(", ".join(r) if r else "—")
        watch.append(", ".join(c) if c else "—")
    return likes, watch


tab_rank, tab_why, tab_news, tab_basket, tab_trust = st.tabs(
    ["⭐ Top picks", "🔍 Why this pick?", "📰 Latest news", "🧺 Build a basket", "✅ Can we trust this?"]
)

# ---------------------------------------------------------------------------
# Tab 1 — Top picks
# ---------------------------------------------------------------------------
with tab_rank:
    st.subheader(f"Top {top_n} — {labels.HORIZON_LABELS[horizon].lower()}")

    head = scored.head(top_n).copy()
    likes, watch = build_reasons(head)

    rating_colors = {
        "Strong Buy": "#16a34a", "Buy": "#22c55e",
        "Hold / Neutral": "#f59e0b", "Weak": "#f97316", "Avoid": "#dc2626",
    }
    sector_head = "<th>Sector</th>" if sectors else ""
    have_flags = signals is not None and not signals.empty
    heads_head = "<th>Heads-up</th>" if have_flags else ""
    body = []
    for i, t in enumerate(head.index):
        row = head.loc[t]
        rt = str(row["Rating"])
        color = rating_colors.get(rt, "#9aa0aa")
        score = int(round(row["score_pct"]))
        hue = max(0, min(120, int(score * 1.2)))
        sector_cell = (
            f"<td>{_html.escape(str(sectors.get(t, '—')))}</td>" if sectors else ""
        )
        if have_flags:
            sp, dte = signal_for(t)
            flags = labels.event_flags(sp, dte)
            flag_html = "<br>".join(_html.escape(f) for f in flags) if flags else "—"
            heads_cell = f"<td class='heads'>{flag_html}</td>"
        else:
            heads_cell = ""
        body.append(
            "<tr>"
            f"<td class='nowrap'><span class='dot' style='background:{color}'></span>{_html.escape(rt)}</td>"
            f"<td>{_html.escape(str(row['Company']))}</td>"
            f"<td class='tk'>{_html.escape(str(t))}</td>"
            f"{sector_cell}"
            f"<td class='nowrap'><span class='bar'><span style='width:{score}%;"
            f"background:hsl({hue},65%,45%)'></span></span>{score}</td>"
            f"<td class='why'>{_html.escape(likes[i])}</td>"
            f"<td class='watch'>{_html.escape(watch[i])}</td>"
            f"{heads_cell}"
            "</tr>"
        )

    table_html = f"""
<style>
.rank-wrap{{overflow-x:auto}}
table.rank{{border-collapse:collapse;width:100%;font-size:0.9rem}}
table.rank th{{text-align:left;padding:8px 10px;border-bottom:2px solid rgba(128,128,128,.35);
opacity:.7;font-weight:600;white-space:nowrap}}
table.rank td{{padding:9px 10px;border-bottom:1px solid rgba(128,128,128,.18);
vertical-align:top;white-space:normal;line-height:1.35}}
table.rank td.nowrap{{white-space:nowrap}}
.rank .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;
margin-right:7px;vertical-align:middle}}
.rank .bar{{background:rgba(128,128,128,.25);border-radius:6px;height:8px;width:80px;
max-width:22vw;display:inline-block;vertical-align:middle;overflow:hidden;margin-right:8px}}
.rank .bar>span{{display:block;height:100%}}
.rank .tk{{font-weight:600}}
.rank .watch{{opacity:.6}}
.rank .heads{{white-space:nowrap;font-size:0.82rem}}
</style>
<div class="rank-wrap">
<table class="rank">
<thead><tr><th>Rating</th><th>Company</th><th>Ticker</th>{sector_head}
<th>Score</th><th>Why we like it</th><th>Keep an eye on</th>{heads_head}</tr></thead>
<tbody>{''.join(body)}</tbody>
</table>
</div>
"""
    st.markdown(table_html, unsafe_allow_html=True)
    st.caption(
        "“Score” shows how each name ranks against the others (100 = best). "
        "Trust the clear leaders near the top; small score gaps in the middle "
        "are basically a tie."
    )
    if have_flags:
        st.caption(
            "📅 = earnings due soon (prices can gap around results). "
            "🩳 = unusually high short interest (extra volatility; on average a "
            "caution sign, though it can fuel a squeeze on good news). These are "
            "context only — they don't change the score."
        )

# ---------------------------------------------------------------------------
# Tab 2 — Why this pick?
# ---------------------------------------------------------------------------
with tab_why:
    options = scored.index.tolist()
    pick = st.selectbox(
        "Pick a company or fund",
        options,
        format_func=lambda t: f"{name_of(names, t)}  ({t})",
    )
    row = scored.loc[pick]
    rating_txt, emoji = labels.rating(row["score_pct"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Company", name_of(names, pick))
    c2.metric("Our rating", f"{emoji} {rating_txt}")
    c3.metric("Score (0-100)", int(round(row["score_pct"])))

    sp, dte = signal_for(pick)
    if labels._isnum(sp) or labels._isnum(dte):
        with st.expander("📌 Heads-up (timing & risk context)", expanded=False):
            st.markdown(f"- {labels.earnings_note(dte)}")
            st.markdown(f"- {labels.short_interest_note(sp)}")
            st.caption(
                "These don't affect the score — they help you time and size a trade."
            )

    st.markdown("#### What's behind this rating")
    st.caption("Green bars push the rating up, red bars pull it down.")

    contribs = labels.factor_contributions(row, horizon)
    if contribs:
        bar_df = pd.DataFrame({
            "Factor": [labels.FACTOR_LABELS.get(f, (f, ""))[0] for f, _ in contribs],
            "Effect": [c for _, c in contribs],
        }).sort_values("Effect")
        fig = px.bar(
            bar_df, x="Effect", y="Factor", orientation="h",
            color="Effect", color_continuous_scale=["#d62728", "#dddddd", "#2ca02c"],
            color_continuous_midpoint=0,
        )
        fig.update_layout(coloraxis_showscale=False, height=380,
                          xaxis_title="Hurts  ←        →  Helps", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### In plain English")
        for f, _ in contribs:
            label, expl = labels.FACTOR_LABELS.get(f, (f, ""))
            z = row.get(f"z_{f}", 0.0)
            st.markdown(
                f"**{label}** — {labels.strength_dots(z)} *{labels.strength_word(z)}*  \n"
                f"<span style='color:gray'>{expl}</span>",
                unsafe_allow_html=True,
            )

# ---------------------------------------------------------------------------
# Tab 3 — Latest news
# ---------------------------------------------------------------------------
with tab_news:
    st.subheader("What's the latest news saying?")
    st.caption(
        "We read recent free headlines and gauge whether the tone is positive or "
        "negative. It only slightly nudges the rating — the numbers lead. "
        "Every headline links to its source."
    )
    news_top = st.slider("Check news for the top N", 5, 30, 15, key="news_top")
    if st.button("Get the latest news"):
        import news as news_mod

        with st.spinner("Reading the headlines..."):
            augmented, views = news_mod.attach_to_scores(scored, top_n=news_top)
        st.session_state["news_aug"] = augmented
        st.session_state["news_views"] = dict(views)

    if "news_aug" in st.session_state:
        aug = st.session_state["news_aug"]
        views = st.session_state["news_views"]

        mood_map = {"positive": "🟢 Positive", "negative": "🔴 Negative",
                    "neutral": "🟡 Mixed", "no news": "⚪ No recent news"}
        rows = []
        for t in aug.head(news_top).index:
            v = views.get(t)
            rows.append({
                "Company": name_of(names, t),
                "Ticker": t,
                "News mood": mood_map.get(v.label if v else "no news", "⚪ No recent news"),
                "Warning signs": (", ".join(v.risk_flags) if v and v.risk_flags else "—"),
                "Headlines": v.n_articles if v else 0,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("#### Read the headlines")
        for t in aug.head(news_top).index:
            v = views.get(t)
            if not v or v.n_articles == 0:
                continue
            mood = mood_map.get(v.label, "⚪")
            warn = f"  ⚠️ {', '.join(v.risk_flags)}" if v.risk_flags else ""
            with st.expander(f"{name_of(names, t)} ({t}) — {mood}{warn}"):
                for a in v.articles:
                    tone = "🟢" if a.sentiment > 0.2 else "🔴" if a.sentiment < -0.2 else "⚪"
                    if a.link:
                        st.markdown(f"{tone} [{a.title}]({a.link}) — *{a.publisher}*")
                    else:
                        st.markdown(f"{tone} {a.title} — *{a.publisher}*")

# ---------------------------------------------------------------------------
# Tab 4 — Build a basket
# ---------------------------------------------------------------------------
with tab_basket:
    st.subheader("Build a simple basket from the top picks")
    st.caption("Spreads your money across several top names instead of betting on one.")

    n_hold = st.slider("How many to include?", 3, 25, 10)
    method = st.radio(
        "How should we split the money?",
        ["Calmer names get more (lower risk)", "Equal amounts", "More into the top picks"],
        index=0,
    )
    picks = scored.head(n_hold).copy()

    if method.startswith("Calmer") and "vol_inv" in picks.columns:
        vol = (-picks["vol_inv"]).clip(lower=1e-4)
        w = 1 / vol
    elif method == "More into the top picks":
        w = (picks["score"] - picks["score"].min() + 1e-6)
    else:
        w = pd.Series(1.0, index=picks.index)
    w = w / w.sum()

    alloc = pd.DataFrame({
        "Company": [name_of(names, t) for t in picks.index],
        "Ticker": picks.index,
        "Share of money": (w * 100).round(1).values,
        "Rating": [f"{labels.rating(p)[1]} {labels.rating(p)[0]}" for p in picks["score_pct"]],
    })

    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.dataframe(
            alloc, use_container_width=True, hide_index=True,
            column_config={
                "Share of money": st.column_config.ProgressColumn(
                    "Share of money (%)", min_value=0,
                    max_value=float(alloc["Share of money"].max()), format="%.1f%%",
                ),
            },
        )
    with c2:
        pie = px.pie(alloc, names="Company", values="Share of money", hole=0.4)
        pie.update_traces(textposition="inside", textinfo="percent")
        pie.update_layout(showlegend=False, height=360)
        st.plotly_chart(pie, use_container_width=True)

    st.info(
        "💡 This is a starting point to spread risk, not a recommendation. "
        "How much to actually invest depends on your own goals and risk comfort."
    )

# ---------------------------------------------------------------------------
# Tab 5 — Can we trust this?
# ---------------------------------------------------------------------------
with tab_trust:
    st.subheader("How well has this approach worked in the past?")
    st.markdown(
        "We replayed the last few years of real market history and checked: "
        "**if you'd bought the names this tool rated highly and avoided the ones "
        "it rated poorly, would you have come out ahead?**"
    )
    if st.button("Run the history check"):
        with st.spinner("Replaying years of market history (takes a moment)..."):
            prices = load_prices(universe_name, period="5y")
            res = walk_forward(prices, horizon=horizon)

        win = res["ls_win_rate"]
        total = res["ls_total_return"]
        verdict = (
            "✅ The highly-rated names beat the poorly-rated ones more often than not."
            if win and win > 0.5 else
            "⚠️ The edge was weak in this test — treat results with caution."
        )
        st.success(verdict) if (win and win > 0.5) else st.warning(verdict)

        c1, c2, c3 = st.columns(3)
        c1.metric("How often the favorites won", f"{win:.0%}" if win == win else "—")
        c2.metric("Total head-start vs. the rejects", f"{total:+.0%}" if total == total else "—")
        c3.metric("Months tested", res["n_periods"])

        eq = res["equity_curve"]
        if len(eq):
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=eq.index, y=(eq.values - 1) * 100,
                                     fill="tozeroy", name="Lead over time"))
            fig.update_layout(
                title="The favorites' lead over the rejects, over time (%)",
                height=380, yaxis_title="% ahead", xaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)

        st.caption(
            "Plain-English caveat: this measures buying the best vs. the worst. "
            "It's most reliable at the extremes (clear winners vs. clear losers) "
            "and fuzzier for middle-of-the-pack names. Past results never "
            "guarantee the future."
        )
