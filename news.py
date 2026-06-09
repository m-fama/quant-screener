"""News / sentiment overlay  (Phase 2, fully free / open-source).

Inspired by the TradingAgents "analyst" idea, but implemented WITHOUT any paid
LLM. For each ticker we:
  1. pull recent headlines (yfinance's free news feed, with a Google News RSS
     fallback — neither needs an API key),
  2. score sentiment with VADER (a free, pure-Python lexicon model),
  3. scan for risk keywords (lawsuits, downgrades, investigations, ...),
  4. produce a BOUNDED tilt that nudges — never dominates — the factor score,
     and keep every source link as a citation.

Design choice that keeps it cheap & fast: the overlay is meant to run only on
the ranked TOP-N names, not the whole universe.
"""

from __future__ import annotations

import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "vaderSentiment not installed. Run: pip install -r requirements.txt"
    ) from exc

import config

_ANALYZER = SentimentIntensityAnalyzer()

# Lower-cased substrings that flag idiosyncratic risk worth a human's eyes.
_RISK_KEYWORDS = [
    "lawsuit", "sued", "investigation", "probe", "sec ", "doj", "fraud",
    "recall", "bankruptcy", "default", "downgrade", "cut to", "slash",
    "miss", "plunge", "halt", "delist", "layoff", "guidance cut",
    "subpoena", "antitrust", "data breach", "short seller", "accounting",
]

# Headlines older than this are ignored (stale news isn't a signal).
_MAX_AGE_DAYS = 14


@dataclass
class Article:
    title: str
    publisher: str
    link: str
    published: float  # epoch seconds (0 if unknown)
    sentiment: float = 0.0  # VADER compound, [-1, 1]


@dataclass
class AnalystView:
    ticker: str
    n_articles: int
    sentiment: float            # mean compound across articles, [-1, 1]
    tilt: float                 # bounded score adjustment to add to the factor score
    risk_flags: list[str] = field(default_factory=list)
    articles: list[Article] = field(default_factory=list)  # citations

    @property
    def label(self) -> str:
        if self.n_articles == 0:
            return "no news"
        if self.sentiment > 0.25:
            return "positive"
        if self.sentiment < -0.25:
            return "negative"
        return "neutral"


# ---------------------------------------------------------------------------
# Sources (both free, no keys)
# ---------------------------------------------------------------------------
def _from_yfinance(ticker: str) -> list[Article]:
    try:
        import yfinance as yf

        raw = yf.Ticker(ticker).news or []
    except Exception:
        return []

    out: list[Article] = []
    for item in raw:
        # yfinance has shifted shapes across versions; handle both flat & nested.
        c = item.get("content", item) if isinstance(item, dict) else {}
        title = c.get("title") or item.get("title") or ""
        if not title:
            continue
        link = (
            (c.get("canonicalUrl") or {}).get("url")
            if isinstance(c.get("canonicalUrl"), dict)
            else c.get("link") or item.get("link") or ""
        )
        pub = (
            (c.get("provider") or {}).get("displayName")
            if isinstance(c.get("provider"), dict)
            else item.get("publisher") or "Yahoo Finance"
        )
        ts = item.get("providerPublishTime", 0) or 0
        out.append(Article(title=title, publisher=pub or "", link=link or "", published=float(ts)))
    return out


def _from_google_rss(ticker: str) -> list[Article]:
    """Google News RSS — free, no key. Parsed with the stdlib XML parser."""
    q = urllib.parse.quote(f"{ticker} stock")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return []

    out: list[Article] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        src = item.find("{http://news.google.com/}source")
        publisher = (src.text if src is not None else "Google News") or "Google News"
        # pubDate -> epoch (best effort)
        ts = 0.0
        pd = item.findtext("pubDate")
        if pd:
            try:
                from email.utils import parsedate_to_datetime

                ts = parsedate_to_datetime(pd).timestamp()
            except Exception:
                ts = 0.0
        if title:
            out.append(Article(title=title, publisher=publisher, link=link, published=ts))
    return out


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def analyze_ticker(ticker: str, max_articles: int = 12, tilt_strength: float = 0.15) -> AnalystView:
    """Build a bounded, cited analyst view for a single ticker."""
    articles = _from_yfinance(ticker)
    if len(articles) < 3:
        articles += _from_google_rss(ticker)

    # Dedupe by lower-cased title; keep the most recent.
    seen: dict[str, Article] = {}
    for a in articles:
        key = a.title.lower().strip()
        if key and (key not in seen or a.published > seen[key].published):
            seen[key] = a
    articles = list(seen.values())

    # Drop stale items when we have a timestamp.
    now = time.time()
    fresh = [
        a for a in articles
        if a.published == 0 or (now - a.published) <= _MAX_AGE_DAYS * 86400
    ]
    articles = (fresh or articles)
    articles.sort(key=lambda a: a.published, reverse=True)
    articles = articles[:max_articles]

    risk_flags: set[str] = set()
    scores: list[float] = []
    for a in articles:
        a.sentiment = _ANALYZER.polarity_scores(a.title)["compound"]
        scores.append(a.sentiment)
        low = a.title.lower()
        for kw in _RISK_KEYWORDS:
            if kw in low:
                risk_flags.add(kw.strip())

    mean_sent = float(sum(scores) / len(scores)) if scores else 0.0
    # Bounded tilt: cap at +/- tilt_strength so news can nudge but never dominate.
    tilt = max(-1.0, min(1.0, mean_sent)) * tilt_strength
    # A risk flag applies a small extra haircut regardless of headline tone.
    if risk_flags:
        tilt -= 0.05 * min(len(risk_flags), 3)

    return AnalystView(
        ticker=ticker,
        n_articles=len(articles),
        sentiment=mean_sent,
        tilt=round(tilt, 4),
        risk_flags=sorted(risk_flags),
        articles=articles,
    )


def attach_to_scores(scored, top_n: int = 25, tilt_strength: float = 0.15):
    """Run the overlay on the top-N rows of a scored DataFrame.

    Returns (augmented_df, views) where augmented_df gains: news_sentiment,
    news_label, news_tilt, n_news, risk_flags, and adj_score (= score + tilt),
    re-ranked by adj_score. `views` maps ticker -> AnalystView (for citations).
    """
    import pandas as pd

    df = scored.copy()
    heads = df.head(top_n).index.tolist()

    views: dict[str, AnalystView] = {}
    for t in heads:
        views[t] = analyze_ticker(t, tilt_strength=tilt_strength)
        time.sleep(0.05)  # be polite to the free endpoints

    df["news_sentiment"] = [round(views[t].sentiment, 3) if t in views else None for t in df.index]
    df["news_label"] = [views[t].label if t in views else "—" for t in df.index]
    df["news_tilt"] = [views[t].tilt if t in views else 0.0 for t in df.index]
    df["n_news"] = [views[t].n_articles if t in views else 0 for t in df.index]
    df["risk_flags"] = [", ".join(views[t].risk_flags) if t in views else "" for t in df.index]

    df["adj_score"] = df["score"] + df["news_tilt"].fillna(0.0)
    df = df.sort_values("adj_score", ascending=False)
    df["adj_rank"] = range(1, len(df) + 1)
    return df, views
