"""Command-line screener.

    python -m saasscreener.query screen --rating BUY
    python -m saasscreener.query screen --max-pe 20 --min-growth 15
    python -m saasscreener.query show APPF
    python -m saasscreener.query filings APPF
    python -m saasscreener.query check
    python -m saasscreener.query sql "SELECT ticker, upside_pct FROM screener"
"""

from __future__ import annotations

import argparse
import json
import sys

from . import config, db


def _f(v, spec="%.1f", dash="-"):
    return dash if v is None else spec % v


def cmd_screen(args) -> int:
    conn = db.connect()
    where, params = [], []
    if args.rating:
        where.append("rating = ?"); params.append(args.rating.upper())
    if args.max_peg is not None:
        where.append("peg > 0 AND peg <= ?"); params.append(args.max_peg)
    if args.max_pe is not None:
        where.append("forward_pe > 0 AND forward_pe <= ?"); params.append(args.max_pe)
    if args.min_growth is not None:
        where.append("revenue_growth >= ?"); params.append(args.min_growth)

    sql = "SELECT * FROM companies"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {args.sort} IS NULL, {args.sort} DESC"
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    rows = list(conn.execute(sql, params))
    if not rows:
        print("No companies match.")
        return 0

    hdr = (f"{'ticker':7s}{'rating':8s}{'score':>6s}{'price':>9s}{'EPS':>8s}"
           f"{'P/E':>7s}{'growth':>8s}{'PEG':>7s}  name")
    print(hdr); print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['ticker']:7s}{(r['rating'] or '-'):8s}"
            f"{_f(r['score'], '%.0f'):>6s}"
            f"{_f(r['price'], '$%.2f'):>9s}"
            f"{_f(r['forward_eps'], '$%.2f'):>8s}"
            f"{_f(r['forward_pe'], '%.1fx'):>7s}"
            f"{_f(r['revenue_growth'], '%.1f%%'):>8s}"
            f"{_f(r['peg'], '%.2f'):>7s}  {r['name'] or ''}"
        )
    print(f"\n{len(rows)} companies")
    return 0


def cmd_show(args) -> int:
    conn = db.connect()
    r = conn.execute("SELECT * FROM companies WHERE ticker = ?", (args.ticker.upper(),)).fetchone()
    if r is None:
        print(f"Unknown ticker {args.ticker}.")
        return 1
    p = json.loads(r["payload"]) if r["payload"] else {}
    sent = p.get("sentiment_detail", {})
    r_peers = {x["key"]: x["value"] for x in conn.execute("SELECT * FROM peer_stats")}

    print(f"\n{r['ticker']}  {r['name']}")
    print(f"{r['sec_name'] or ''}  ·  CIK {r['cik']}  ·  sells to {r['sells_to']}")

    print(f"\n  {r['rating']}  —  score {_f(r['score'], '%.0f')}/100")
    print(f"    {'price':<22s} {_f(r['price'], '$%.2f')}")
    print(f"    {'P/E next year':<22s} {_f(r['forward_pe'], '%.1fx')}")
    print(f"    {'revenue growth':<22s} {_f(r['revenue_growth'], '%.1f%%')}")
    print(f"    {'P/E per pt of growth':<22s} {_f(r['peg'], '%.2f')}"
          f"   (group median {_f(r_peers.get('peg_median'), '%.2f')})")

    print(f"\n  Score  =  65% value ({_f(r['value_score'], '%.0f')})  +  35% sentiment ({_f(r['sentiment_score'], '%.0f')})")
    for k, v in (sent.get("parts") or {}).items():
        print(f"    {k:<22s} {v:.0f}")

    print("\n  Key numbers")
    for label, key, spec in [
        ("market cap", "market_cap", "$%.0f"), ("revenue", "revenue", "$%.0f"),
        ("revenue growth", "revenue_growth", "%.1f%%"),
        ("EPS now", "trailing_eps", "$%.2f"), ("EPS next year", "forward_eps", "$%.2f"),
        ("P/E now", "trailing_pe", "%.1fx"), ("P/E next year", "forward_pe", "%.1fx"),
        ("gross margin", "gross_margin", "%.1f%%"),
        ("operating margin", "operating_margin", "%.1f%%"),
        ("analysts covering", "analyst_count", "%.0f"),
        ("short interest", "short_pct_float", "%.1f%%"),
    ]:
        v = r[key]
        if key in ("market_cap", "revenue") and v:
            v, label = v / 1e6, label + " ($M)"
        print(f"    {label:<22s} {_f(v, spec):>14s}")

    if r["notes"]:
        print(f"\n  Notes: {r['notes'].replace(' | ', '; ')}")

    fl = list(conn.execute(
        "SELECT form, period, filed, index_url FROM filings WHERE ticker = ? ORDER BY filed DESC LIMIT 4",
        (r["ticker"],)))
    if fl:
        print("\n  Recent SEC filings")
        for f in fl:
            print(f"    {f['form']:6s} {str(f['period']):12s} filed {f['filed']}  {f['index_url']}")
    print()
    return 0


def cmd_filings(args) -> int:
    conn = db.connect()
    rows = list(conn.execute(
        "SELECT * FROM filings WHERE ticker = ? ORDER BY filed DESC", (args.ticker.upper(),)))
    if not rows:
        print("No filings stored. Rebuild without --skip-edgar.")
        return 1
    for r in rows:
        print(f"{r['form']:8s} period {str(r['period']):12s} filed {r['filed']}\n         {r['index_url']}")
    return 0


def cmd_peers(args) -> int:
    conn = db.connect()
    for r in conn.execute("SELECT key, value FROM peer_stats ORDER BY key"):
        print(f"  {r['key']:24s} {r['value']:>14.4f}")
    meta = db.read_meta(conn)
    print(f"\n  built {meta.get('built_at')}  ·  ratings {meta.get('rating_counts')}")
    return 0


def cmd_check(args) -> int:
    """Integrity check: every company priced, valued, rated and linked."""
    conn = db.connect()
    problems = []
    n = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    if n != len(config.UNIVERSE):
        problems.append(f"{n} companies, expected {len(config.UNIVERSE)}")

    for label, sql in [
        ("no CIK",    "SELECT ticker FROM companies WHERE cik IS NULL"),
        ("no price",  "SELECT ticker FROM companies WHERE price IS NULL"),
        ("no rating", "SELECT ticker FROM companies WHERE rating IS NULL"),
        ("no 10-K on file",
         "SELECT ticker FROM companies WHERE ticker NOT IN "
         "(SELECT DISTINCT ticker FROM filings WHERE base_form='10-K')"),
        ("no 10-Q on file",
         "SELECT ticker FROM companies WHERE ticker NOT IN "
         "(SELECT DISTINCT ticker FROM filings WHERE base_form='10-Q')"),
    ]:
        bad = [r[0] for r in conn.execute(sql)]
        if bad:
            problems.append(f"{label}: {', '.join(bad)}")

    unvalued = [r[0] for r in conn.execute("SELECT ticker FROM companies WHERE peg IS NULL")]
    filings = conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
    print(f"companies {n}   filings {filings}   unvalued {len(unvalued)}"
          + (f" ({', '.join(unvalued)} — not profitable)" if unvalued else ""))

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("all checks passed")
    return 0


def cmd_history(args) -> int:
    """How one company's rating and price have moved across snapshots."""
    conn = db.connect()
    rows = list(conn.execute(
        "SELECT * FROM snapshots WHERE ticker = ? ORDER BY taken_on", (args.ticker.upper(),)))
    if not rows:
        print("No snapshots yet. Each build records one; run it again tomorrow.")
        return 1
    print(f"\n{args.ticker.upper()}\n")
    print(f"{'date':12s}{'rating':8s}{'score':>6s}{'price':>10s}{'PEG':>8s}")
    first = rows[0]
    for r in rows:
        print(f"{r['taken_on']:12s}{(r['rating'] or '-'):8s}"
              f"{_f(r['score'], '%.0f'):>6s}{_f(r['price'], '$%.2f'):>10s}"
              f"{_f(r['peg'], '%.2f'):>8s}")
    if len(rows) > 1 and first["price"] and rows[-1]["price"]:
        move = (rows[-1]["price"] / first["price"] - 1) * 100
        print(f"\nprice {move:+.1f}% since {first['taken_on']}")
    return 0


def cmd_track(args) -> int:
    """Scoreboard: how have the shares moved since each rating was given?

    The question this exists to answer is whether the model is worth
    believing. A BUY bucket that has not beaten the SELL bucket over a
    meaningful stretch is a model to fix, not to follow.
    """
    conn = db.connect()
    meta = db.snapshot_meta(conn)
    if meta["days"] < 2:
        print(f"Only {meta['days']} snapshot so far ({meta['first']}).")
        print("Nothing to measure yet -- each build records one per day.")
        print("Come back after a week or two of builds.")
        return 0

    first = meta["first"]
    latest = conn.execute("SELECT MAX(taken_on) FROM snapshots").fetchone()[0]
    rows = list(conn.execute(
        """SELECT a.ticker, a.rating, a.price AS p0, b.price AS p1
           FROM snapshots a JOIN snapshots b
             ON a.ticker = b.ticker AND a.taken_on = ? AND b.taken_on = ?
           WHERE a.price > 0 AND b.price > 0""", (first, latest)))
    if not rows:
        print("No overlapping companies between the first and latest snapshot.")
        return 0

    print(f"\nFrom {first} to {latest}  ({len(rows)} companies)\n")
    buckets: dict[str, list[float]] = {}
    for r in rows:
        buckets.setdefault(r["rating"] or "unrated", []).append(
            (r["p1"] / r["p0"] - 1) * 100)
    allmoves = [m for v in buckets.values() for m in v]
    market = sum(allmoves) / len(allmoves)

    print(f"{'rating':10s}{'n':>4s}{'avg move':>11s}{'vs group':>11s}")
    for rating in ("BUY", "HOLD", "SELL", "unrated"):
        v = buckets.get(rating)
        if not v:
            continue
        avg = sum(v) / len(v)
        print(f"{rating:10s}{len(v):>4d}{avg:>10.1f}%{avg - market:>+10.1f}%")
    print(f"{'ALL':10s}{len(allmoves):>4d}{market:>10.1f}%")
    print("\nA model worth following puts BUY above the group and SELL below it.")
    return 0


def cmd_sql(args) -> int:
    conn = db.connect()
    try:
        rows = list(conn.execute(args.query))
    except Exception as exc:  # noqa: BLE001
        print(f"SQL error: {exc}")
        return 1
    if not rows:
        print("(no rows)")
        return 0
    cols = rows[0].keys()
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join("" if r[c] is None else str(r[c]) for c in cols))
    print(f"\n{len(rows)} rows")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="saasscreener.query", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("screen", help="filter and rank the companies")
    s.add_argument("--rating", choices=["BUY", "HOLD", "SELL", "buy", "hold", "sell"])
    s.add_argument("--max-peg", type=float, help="P/E per point of growth ceiling")
    s.add_argument("--max-pe", type=float)
    s.add_argument("--min-growth", type=float)
    s.add_argument("--sort", default="score")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_screen)

    s = sub.add_parser("show", help="full detail for one company")
    s.add_argument("ticker"); s.set_defaults(fn=cmd_show)

    s = sub.add_parser("filings", help="SEC filings for one company")
    s.add_argument("ticker"); s.set_defaults(fn=cmd_filings)

    s = sub.add_parser("peers", help="peer-group statistics")
    s.set_defaults(fn=cmd_peers)

    s = sub.add_parser("history", help="one company's ratings over time")
    s.add_argument("ticker"); s.set_defaults(fn=cmd_history)

    s = sub.add_parser("track", help="have the ratings actually worked?")
    s.set_defaults(fn=cmd_track)

    s = sub.add_parser("check", help="integrity check")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("sql", help="run SQL against the database")
    s.add_argument("query"); s.set_defaults(fn=cmd_sql)

    args = ap.parse_args(argv)
    if not config.DB_PATH.exists():
        print(f"No database at {config.DB_PATH}. Run: python -m saasscreener.build")
        return 1
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
