"""Pipeline: universe -> EDGAR + Yahoo -> valuation -> SQLite.

    python -m saasscreener.build                  refresh everything
    python -m saasscreener.build --recompute      re-model from cache, no network
    python -m saasscreener.build --quotes         refresh prices and consensus only
    python -m saasscreener.build --tickers APPF,TOST
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import config, db, edgar, market, quotes, valuation


def _log(msg: str) -> None:
    print(msg, flush=True)


def fetch_edgar(tickers: list[str]) -> dict[str, dict]:
    """CIK, registrant metadata, filings and XBRL facts for each ticker."""
    out: dict[str, dict] = {}

    def work(ticker: str) -> tuple[str, dict]:
        hit = edgar.resolve(ticker)
        if not hit:
            return ticker, {"error": "no CIK -- not a current SEC filer"}
        cik, title = hit
        rec: dict = {"cik": cik, "edgar_title": title}
        try:
            rec.update(edgar.company_meta(cik))
            rec["filings"] = edgar.filings(cik)
            rec["facts"] = edgar.company_facts(cik)
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
        # The executive quote is a separate walk through the 8-K exhibits and
        # may legitimately find nothing, so it must not fail the whole record.
        try:
            rec["quote"] = quotes.latest_quote(cik)
        except Exception:
            rec["quote"] = None
        return ticker, rec

    # SEC allows 10 req/s; edgar._get serialises to stay under it, so more
    # workers than this just queue up behind the rate limiter.
    with ThreadPoolExecutor(max_workers=5) as pool:
        for ticker, rec in pool.map(work, tickers):
            n = len(rec.get("filings", []))
            if rec.get("error"):
                _log(f"  EDGAR {ticker:6s} {rec['error']}")
            else:
                q = rec.get("quote")
                _log(f"  EDGAR {ticker:6s} CIK {rec['cik']:<9d} {n} filings, "
                     f"{len(rec.get('facts', {}))} fact series, "
                     + (f"quote from {q['speaker']}" if q else "no quote found"))
            out[ticker] = rec
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="saasscreener.build")
    ap.add_argument("--recompute", action="store_true",
                    help="re-model from cache without any network calls")
    ap.add_argument("--quotes", action="store_true",
                    help="refresh prices and analyst consensus only")
    ap.add_argument("--tickers", help="comma-separated subset")
    ap.add_argument("--cache-ttl", type=float, default=config.CACHE_TTL_HOURS)
    ap.add_argument("--skip-edgar", action="store_true")
    args = ap.parse_args(argv)

    started = time.monotonic()
    universe = {t: sells_to for t, sells_to in config.UNIVERSE}
    tickers = (
        [t.strip().upper() for t in args.tickers.split(",")]
        if args.tickers
        else list(universe)
    )

    ttl = -1 if args.recompute else (0 if args.quotes else args.cache_ttl)

    # ---- market data -----------------------------------------------------
    _log(f"Fetching market data for {len(tickers)} companies "
         f"({'cache only' if args.recompute else 'network'})...")
    if args.recompute:
        funds = {}
        for t in tickers:
            c = market.load_cached(t, ttl_hours=-1)
            if c:
                funds[t] = c
            else:
                _log(f"  {t:6s} no cache")
    else:
        funds = market.fetch_many(
            tickers,
            ttl_hours=ttl,
            on_result=lambda t, d, s: _log(
                f"  {t:6s} {s}" + ("" if d else "  <- dropped")
            ),
        )

    if not funds:
        _log("No market data. Aborting.")
        return 1

    # ---- EDGAR -----------------------------------------------------------
    edgar_data: dict[str, dict] = {}
    if not args.skip_edgar and not args.quotes:
        _log(f"\nFetching EDGAR filings and XBRL facts...")
        edgar_data = fetch_edgar(list(funds))
    elif args.quotes or args.skip_edgar:
        _log("\nSkipping EDGAR (reusing what is already in the database).")

    # The executive quote comes from EDGAR but belongs with the company's
    # cached record, so a later refresh -- which never touches EDGAR -- still
    # has it. Attach before valuing, since valuation copies the rows.
    for t, e in edgar_data.items():
        if e.get("quote") and t in funds:
            funds[t]["exec_quote"] = e["quote"]
            market.save_cached(t, funds[t])

    # ---- value and rate --------------------------------------------------
    _log(f"\nValuing {len(funds)} companies against the peer set...")
    rows, peers = valuation.run(funds)

    _log(f"  median P/E per point of growth: {peers.get('peg_median'):.2f} "
         f"across {peers.get('peg_n')} profitable, growing companies")

    # ---- persist ---------------------------------------------------------
    conn = db.connect()
    # db.init() drops and recreates the derived tables; snapshots are created
    # with IF NOT EXISTS and survive, but read the count first so the build
    # can report the series length.
    preserved_filings: list = []
    preserved_facts: list = []
    preserved_meta: dict = {}
    if args.quotes or args.skip_edgar:
        try:
            preserved_filings = [dict(r) for r in conn.execute("SELECT * FROM filings")]
            preserved_facts = [dict(r) for r in conn.execute("SELECT * FROM edgar_facts")]
            # The CIK, registrant name and SIC come from EDGAR, which this run
            # is skipping. Without carrying them across the drop-and-recreate
            # they would be silently blanked, taking every filing link in the
            # interface with them.
            preserved_meta = {
                r["ticker"]: dict(r)
                for r in conn.execute(
                    "SELECT ticker, cik, sells_to, sec_name, sic_description FROM companies")
            }
        except Exception:
            pass

    db.init(conn)

    metas = {}
    for t in funds:
        e = edgar_data.get(t, {})
        prior = preserved_meta.get(t, {})
        metas[t] = {
            "cik": e.get("cik") or prior.get("cik"),
            "sells_to": universe.get(t) or prior.get("sells_to"),
            "sec_name": e.get("sec_name") or e.get("edgar_title") or prior.get("sec_name"),
            "sic_description": e.get("sic_description") or prior.get("sic_description"),
        }

    db.write_companies(conn, rows, metas)
    db.write_peer_stats(conn, peers)

    today = datetime.now(timezone.utc).date().isoformat()
    # A fresh database has no snapshot table; reload any history from the CSV
    # before appending, so a rebuilt or cloned project keeps its record.
    db.import_snapshots(conn)
    db.write_snapshot(conn, rows, today)
    db.export_snapshots(conn)
    snap = db.snapshot_meta(conn)

    if edgar_data:
        for t, e in edgar_data.items():
            if e.get("cik") and e.get("filings"):
                db.write_filings(conn, t, e["cik"], e["filings"])
            if e.get("facts"):
                db.write_facts(conn, t, e["facts"])
    else:
        for r in preserved_filings:
            conn.execute(
                "INSERT OR REPLACE INTO filings VALUES (?,?,?,?,?,?,?,?,?)",
                tuple(r.values()),
            )
        for r in preserved_facts:
            conn.execute(
                "INSERT OR REPLACE INTO edgar_facts VALUES (?,?,?,?,?,?,?)",
                tuple(r.values()),
            )
        conn.commit()

    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("rating") or "unrated"] = counts.get(r.get("rating") or "unrated", 0) + 1

    db.write_meta(conn, {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_size": len(rows),
        "subject": config.SUBJECT,
        "rating_counts": counts,
        "peg_median": peers.get("peg_median"),
        "build_seconds": round(time.monotonic() - started, 1),
    })

    _log(f"\n{'ticker':8s}{'rating':8s}{'score':>7s}{'price':>10s}"
         f"{'P/E':>7s}{'growth':>8s}{'PEG':>7s}{'value':>7s}{'mood':>7s}  notes")
    for r in rows:
        q = r.get("quote") or {}
        fmt = lambda v, sp: (sp % v) if v is not None else "-"
        _log(
            f"{r['ticker']:8s}"
            f"{(r.get('rating') or '-'):8s}"
            f"{fmt(r.get('score'), '%.0f'):>7s}"
            f"{fmt(q.get('price'), '$%.2f'):>10s}"
            f"{fmt(r.get('forward_pe'), '%.1f'):>7s}"
            f"{fmt(r.get('revenue_growth'), '%.1f%%'):>8s}"
            f"{fmt(r.get('peg'), '%.2f'):>7s}"
            f"{fmt(r.get('value_score'), '%.0f'):>7s}"
            f"{fmt(r.get('sentiment_score'), '%.0f'):>7s}"
            f"  {'; '.join(r.get('notes') or [])}"
        )

    _log(f"\n{counts}")
    _log(f"Snapshot recorded for {today}. Tracking {snap['days']} day(s), "
         f"{snap['first']} to {snap['last']}.  ->  data/snapshots.csv")
    _log(f"Built {len(rows)} companies in {time.monotonic()-started:.1f}s -> {config.DB_PATH}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
