"""Value and the buy / hold / sell recommendation.

Two steps, both checkable in your head.

**Value.** Divide what you pay per dollar of profit by how fast that profit is
growing:

    P/E per point of growth  =  forward P/E / revenue growth %

Lower is cheaper. Tyler trades at 21.6x while growing 8%, so 2.6. Samsara
trades at 40.3x while growing 30%, so 1.3 -- cheaper per unit of growth despite
the far higher headline multiple. This is the classic PEG ratio, and it needs a
company to be profitable and growing; anything else has no PEG.

**Recommendation.** 65% that value measure, 35% how the market feels about the
company (analyst consensus, where the price sits in its own 12-month range, and
how much of the float is sold short).
"""

from __future__ import annotations

import math
import statistics
from typing import Iterable

from . import config


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _interp(curve: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear lookup on an ascending-in-x curve."""
    pts = sorted(curve, key=lambda p: p[0])
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def _median(vals: Iterable[float | None]) -> float | None:
    clean = [v for v in vals if v is not None and not math.isnan(v)]
    return statistics.median(clean) if clean else None


# ---------------------------------------------------------------------------
# peer group
# ---------------------------------------------------------------------------


def peer_stats(rows: list[dict]) -> dict:
    """Group context for the interface. No longer feeds the valuation."""
    pegs = [p for p in (peg(r) for r in rows) if p is not None]
    return {
        "n": len(rows),
        "peg_median": _median(pegs),
        "peg_n": len(pegs),
        # Only profitable companies can contribute a P/E; a negative one is
        # not a cheaper multiple, it is a meaningless one.
        "forward_pe_median": _median(
            r.get("forward_pe") for r in rows if (r.get("forward_pe") or 0) > 0
        ),
        "growth_median": _median(r.get("revenue_growth") for r in rows),
        "trailing_pe_median": _median(
            r.get("trailing_pe") for r in rows if (r.get("trailing_pe") or 0) > 0
        ),
        "market_cap_median": _median(r.get("market_cap") for r in rows),
        # Medians for the side-by-side comparison shown per company.
        "operating_margin_median": _median(r.get("operating_margin") for r in rows),
        "gross_margin_median": _median(r.get("gross_margin") for r in rows),
        "ps_median": _median(r.get("ps_ratio") for r in rows),
    }


# ---------------------------------------------------------------------------
# fair value
# ---------------------------------------------------------------------------


def peg(f: dict) -> float | None:
    """Forward P/E divided by revenue growth. Lower is cheaper.

    Needs both a positive multiple and positive growth: a negative P/E is not
    a cheap one, and dividing by zero or negative growth is meaningless.
    """
    pe, g = f.get("forward_pe"), f.get("revenue_growth")
    if not pe or pe <= 0 or not g or g <= 0:
        return None
    return pe / g


# ---------------------------------------------------------------------------
# sentiment
# ---------------------------------------------------------------------------


def sentiment(f: dict) -> dict:
    """What the market and the professionals currently think.

    Components with no data drop out and the rest are reweighted, so a company
    nobody covers is judged on price action and short interest rather than
    being marked down for the absence.
    """
    q = f.get("quote") or {}
    parts: dict[str, float] = {}

    mean = q.get("analyst_rec_mean")
    if mean is not None:
        parts["analysts"] = _interp(config.CURVES["analysts"], mean)

    price, lo, hi = q.get("price"), q.get("week52_low"), q.get("week52_high")
    pos = None
    if price is not None and lo is not None and hi is not None and hi > lo:
        pos = (price - lo) / (hi - lo) * 100.0
        parts["momentum"] = _interp(config.CURVES["momentum"], pos)

    short = f.get("short_pct_float")
    if short is not None:
        parts["short_int"] = _interp(config.CURVES["short_int"], short)

    if not parts:
        return {"score": None, "parts": {}, "range_position": None}

    weights = {k: config.SENTIMENT_MIX[k] for k in parts}
    total = sum(weights.values())
    score = sum(parts[k] * weights[k] / total for k in parts)

    return {"score": score, "parts": parts, "range_position": pos}


# ---------------------------------------------------------------------------
# recommendation
# ---------------------------------------------------------------------------


def recommend(f: dict, ratio: float | None, sent: dict) -> dict:
    """Blend the value measure and the mood into one call."""
    value_score = _interp(config.CURVES["value"], ratio) if ratio is not None else None
    sent_score = sent.get("score")

    parts = {}
    if value_score is not None:
        parts["value"] = value_score
    if sent_score is not None:
        parts["sentiment"] = sent_score

    if not parts:
        return {"score": None, "rating": None, "value_score": None,
                "sentiment_score": None,
                "notes": ["not enough data to rate this company"]}

    weights = {k: config.RECOMMENDATION_MIX[k] for k in parts}
    total = sum(weights.values())
    score = sum(parts[k] * weights[k] / total for k in parts)

    if score >= config.BUY_THRESHOLD:
        rating = "BUY"
    elif score <= config.SELL_THRESHOLD:
        rating = "SELL"
    else:
        rating = "HOLD"

    # Notes are written for a reader, not a log file. They appear verbatim in
    # the interface, so they say what happened rather than naming a flag.
    notes: list[str] = []
    if value_score is None:
        notes.append("Rated on market sentiment alone — not expected to be "
                     "profitable and growing, so there is no P/E to compare")
    count = (f.get("quote") or {}).get("analyst_count")
    if count is None:
        notes.append("No analysts cover this company")
    elif count < config.THIN_COVERAGE:
        notes.append(f"Only {int(count)} analysts cover this company")
    if f.get("multi_class_shares"):
        notes.append("Has more than one class of shares")
    if value_score is not None and sent_score is not None and abs(value_score - sent_score) > 35:
        notes.append(
            "The numbers and the market mood disagree sharply here"
            if value_score > sent_score
            else "Popular with the market despite looking expensive"
        )

    return {
        "score": score,
        "rating": rating,
        "value_score": value_score,
        "sentiment_score": sent_score,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------


def run(fundamentals_by_ticker: dict[str, dict]) -> tuple[list[dict], dict]:
    """Score and rate every company."""
    rows = [dict(f) for f in fundamentals_by_ticker.values()]
    peers = peer_stats(rows)

    for r in rows:
        ratio = peg(r)
        sent = sentiment(r)
        rec = recommend(r, ratio, sent)

        r["peg"] = ratio
        r["sentiment_detail"] = sent
        r["recommendation_detail"] = rec
        r["rating"] = rec.get("rating")
        r["score"] = rec.get("score")
        r["value_score"] = rec.get("value_score")
        r["sentiment_score"] = rec.get("sentiment_score")
        r["range_position"] = sent.get("range_position")
        r["notes"] = rec.get("notes") or []

    rows.sort(key=lambda r: (r.get("score") is None, -(r.get("score") or 0)))
    return rows, peers
