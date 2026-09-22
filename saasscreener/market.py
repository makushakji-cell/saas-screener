"""Market data ingestion from Yahoo Finance via yfinance.

Everything price-dependent lives here: the quote, the traded multiples, the
balance-sheet items needed to bridge enterprise value to equity value, and the
live sell-side consensus that the screener reports alongside its own rating.

The split matters for refresh cost. `fundamentals()` is expensive and changes
once a quarter, so it is cached to disk. `quote()` is cheap and changes every
minute, so it is never cached -- the "live" half of the screener is exactly the
set of fields this returns.
"""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

import yfinance as yf

from . import config


def _num(x: Any) -> float | None:
    """Coerce to float, mapping Yahoo's several flavours of missing to None."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _pct(x: Any) -> float | None:
    """Yahoo returns rates as fractions; the screener works in percent."""
    v = _num(x)
    return None if v is None else v * 100.0


# ---------------------------------------------------------------------------
# Live quote + consensus
# ---------------------------------------------------------------------------

# Yahoo's recommendationKey vocabulary, collapsed to the three ratings the
# screener speaks. `none` appears for names with no covering analysts.
_REC_KEY_MAP = {
    "strong_buy": "BUY",
    "buy": "BUY",
    "outperform": "BUY",
    "hold": "HOLD",
    "neutral": "HOLD",
    "underperform": "SELL",
    "sell": "SELL",
    "strong_sell": "SELL",
}


def quote(ticker: str, info: dict | None = None) -> dict:
    """The fields that move intraday. Never cached."""
    if info is None:
        info = yf.Ticker(ticker).info or {}

    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    prev = _num(info.get("regularMarketPreviousClose")) or _num(
        info.get("previousClose")
    )
    change_pct = None
    if price is not None and prev:
        change_pct = (price / prev - 1.0) * 100.0

    rec_key = (info.get("recommendationKey") or "").lower()
    target = _num(info.get("targetMeanPrice"))

    return {
        "price": price,
        "prev_close": prev,
        "change_pct": change_pct,
        "day_low": _num(info.get("dayLow")),
        "day_high": _num(info.get("dayHigh")),
        "week52_low": _num(info.get("fiftyTwoWeekLow")),
        "week52_high": _num(info.get("fiftyTwoWeekHigh")),
        "market_cap": _num(info.get("marketCap")),
        "volume": _num(info.get("volume")) or _num(info.get("regularMarketVolume")),
        # live sell-side consensus
        "analyst_rec_key": rec_key or None,
        "analyst_rec": _REC_KEY_MAP.get(rec_key),
        "analyst_rec_mean": _num(info.get("recommendationMean")),
        "analyst_count": _num(info.get("numberOfAnalystOpinions")),
        "target_mean": target,
        "target_high": _num(info.get("targetHighPrice")),
        "target_low": _num(info.get("targetLowPrice")),
        "target_upside_pct": (
            (target / price - 1.0) * 100.0 if target and price else None
        ),
        "quoted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def recommendation_trend(tk: yf.Ticker) -> dict | None:
    """The analyst vote distribution for the current month, if published.

    yfinance exposes this as a DataFrame indexed by period ('0m' = this month).
    It is the raw material behind recommendationMean and is worth showing,
    because '12 buys and 1 sell' and '5 buys and 8 holds' can produce a similar
    mean while meaning very different things.
    """
    try:
        df = tk.recommendations
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None

    try:
        row = None
        if "period" in df.columns:
            match = df[df["period"] == "0m"]
            row = match.iloc[0] if len(match) else df.iloc[0]
        else:
            row = df.iloc[0]

        out = {
            k: int(row[k])
            for k in ("strongBuy", "buy", "hold", "sell", "strongSell")
            if k in row.index and row[k] == row[k]
        }
        return out or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------


def fundamentals(ticker: str) -> dict:
    """Everything needed to value the company, plus the traded multiples.

    Revenue growth is taken from Yahoo's `revenueGrowth` (most recent quarter
    year over year) when present, and recomputed from the income statement when
    it is not -- several smaller names in this universe have a null there.
    """
    tk = yf.Ticker(ticker)
    info = tk.info or {}

    revenue = _num(info.get("totalRevenue"))
    gross_margin = _pct(info.get("grossMargins"))
    gross_profit = (
        revenue * gross_margin / 100.0
        if revenue is not None and gross_margin is not None
        else None
    )

    fcf = _num(info.get("freeCashflow"))
    fcf_margin = (fcf / revenue * 100.0) if fcf is not None and revenue else None

    growth = _pct(info.get("revenueGrowth"))
    growth_source = "yahoo_quarterly_yoy"
    if growth is None:
        growth, growth_source = _growth_from_statements(tk)

    ev = _num(info.get("enterpriseValue"))
    mcap = _num(info.get("marketCap"))
    # Net debt implied by Yahoo's own EV, which keeps EV/x and the equity bridge
    # internally consistent even where the balance sheet is stale.
    net_debt = (ev - mcap) if ev is not None and mcap is not None else None

    # Share count. Yahoo's `sharesOutstanding` reports a single class, but its
    # marketCap covers all of them -- for the dual-class names here (Zillow,
    # AppFolio, Samsara, Doximity, Toast, ServiceTitan) the two disagree by up
    # to 5x. Dividing an enterprise value by the Class A count alone inflates
    # the per-share result by exactly that factor, so market cap / price is
    # used instead: it is consistent with the EV the multiples are built from
    # and it counts every class.
    price_now = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    shares_reported = _num(info.get("sharesOutstanding"))
    shares_implied = (mcap / price_now) if mcap and price_now else None
    shares = shares_implied or shares_reported
    share_source = "market_cap/price" if shares_implied else "sharesOutstanding"
    multi_class = bool(
        shares_implied
        and shares_reported
        and abs(shares_implied / shares_reported - 1.0) > 0.05
    )

    trailing_eps = _num(info.get("trailingEps"))
    forward_eps = _num(info.get("forwardEps"))
    eps_growth = None
    if trailing_eps and forward_eps and trailing_eps > 0:
        eps_growth = (forward_eps / trailing_eps - 1.0) * 100.0

    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "employees": _num(info.get("fullTimeEmployees")),
        "summary": info.get("longBusinessSummary"),
        "website": info.get("website"),
        # scale
        "revenue": revenue,
        "gross_profit": gross_profit,
        "ebitda": _num(info.get("ebitda")),
        "free_cash_flow": fcf,
        "operating_cash_flow": _num(info.get("operatingCashflow")),
        "net_income": _num(info.get("netIncomeToCommon")),
        "total_cash": _num(info.get("totalCash")),
        "total_debt": _num(info.get("totalDebt")),
        "shares_out": shares,
        "shares_reported": shares_reported,
        "shares_source": share_source,
        "multi_class_shares": multi_class,
        "enterprise_value": ev,
        "net_debt": net_debt,
        # margins and growth, all in percent
        "gross_margin": gross_margin,
        "operating_margin": _pct(info.get("operatingMargins")),
        "profit_margin": _pct(info.get("profitMargins")),
        "ebitda_margin": _pct(info.get("ebitdaMargins")),
        "fcf_margin": fcf_margin,
        "revenue_growth": growth,
        "revenue_growth_source": growth_source,
        "earnings_growth": _pct(info.get("earningsGrowth")),
        "eps_growth_fwd": eps_growth,
        # per share
        "trailing_eps": trailing_eps,
        "forward_eps": forward_eps,
        "book_value_ps": _num(info.get("bookValue")),
        # traded multiples as Yahoo computes them
        "trailing_pe": _num(info.get("trailingPE")),
        "forward_pe": _num(info.get("forwardPE")),
        "ps_ratio": _num(info.get("priceToSalesTrailing12Months")),
        "pb_ratio": _num(info.get("priceToBook")),
        "ev_revenue": _num(info.get("enterpriseToRevenue")),
        "ev_ebitda": _num(info.get("enterpriseToEbitda")),
        "peg_ratio": _num(info.get("pegRatio")) or _num(info.get("trailingPegRatio")),
        # risk
        "beta": _num(info.get("beta")),
        "short_pct_float": _pct(info.get("shortPercentOfFloat")),
        # live half
        "quote": quote(ticker, info),
        "rec_trend": recommendation_trend(tk),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _growth_from_statements(tk: yf.Ticker) -> tuple[float | None, str]:
    """Year-over-year revenue growth from the annual income statement.

    Fallback for names where Yahoo's revenueGrowth field is null.
    """
    try:
        fin = tk.income_stmt
        if fin is None or fin.empty or "Total Revenue" not in fin.index:
            return None, "unavailable"
        row = fin.loc["Total Revenue"].dropna()
        if len(row) < 2:
            return None, "unavailable"
        newest, prior = float(row.iloc[0]), float(row.iloc[1])
        if prior <= 0:
            return None, "unavailable"
        return (newest / prior - 1.0) * 100.0, "annual_income_statement"
    except Exception:
        return None, "unavailable"


# ---------------------------------------------------------------------------
# Caching and batch fetch
# ---------------------------------------------------------------------------


def _cache_path(ticker: str):
    return config.CACHE / f"{ticker.upper()}.json"


def load_cached(ticker: str, ttl_hours: float = config.CACHE_TTL_HOURS) -> dict | None:
    path = _cache_path(ticker)
    if not path.exists():
        return None
    if ttl_hours >= 0:
        age = (time.time() - path.stat().st_mtime) / 3600.0
        if age > ttl_hours:
            return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_cached(ticker: str, payload: dict) -> None:
    config.CACHE.mkdir(parents=True, exist_ok=True)
    _cache_path(ticker).write_text(json.dumps(payload, indent=1, default=str))


def fetch_many(
    tickers: list[str],
    ttl_hours: float = config.CACHE_TTL_HOURS,
    on_result: Callable[[str, dict | None, str], None] | None = None,
) -> dict[str, dict]:
    """Fetch fundamentals for many tickers, using the disk cache where fresh.

    Yahoo throttles hard above a few concurrent requests, so this stays at
    FETCH_WORKERS with FETCH_DELAY spacing. Failures are returned as absent
    keys rather than raising -- one dead ticker should not stop a build.
    """
    out: dict[str, dict] = {}

    def work(ticker: str) -> tuple[str, dict | None, str]:
        cached = load_cached(ticker, ttl_hours)
        if cached is not None:
            # Even on a cache hit the quote is refreshed, so the price and the
            # consensus are live while the quarterly numbers come from disk.
            try:
                cached["quote"] = quote(ticker)
                save_cached(ticker, cached)
                return ticker, cached, "cache+quote"
            except Exception:
                return ticker, cached, "cache"
        try:
            time.sleep(config.FETCH_DELAY)
            data = fundamentals(ticker)
            if data.get("revenue") is None and data.get("quote", {}).get("price") is None:
                return ticker, None, "empty"
            save_cached(ticker, data)
            return ticker, data, "network"
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort
            stale = load_cached(ticker, ttl_hours=-1)
            if stale is not None:
                return ticker, stale, f"stale ({type(exc).__name__})"
            return ticker, None, f"FAIL {type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=config.FETCH_WORKERS) as pool:
        for ticker, data, status in pool.map(work, tickers):
            if on_result:
                on_result(ticker, data, status)
            if data is not None:
                out[ticker] = data

    return out
