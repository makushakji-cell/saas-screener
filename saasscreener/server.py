"""JSON API and static file server. Standard library only.

    python -m saasscreener.server            http://127.0.0.1:8899

Endpoints
    GET  /api/screener            every company, peer stats, build metadata
    GET  /api/company/<ticker>    full record: methods, filings, XBRL history
    GET  /api/refresh             re-poll prices and analyst consensus, live
    GET  /api/export.csv          the screener table as CSV

`/api/refresh` is the live half. It re-fetches only the quote block -- price,
change, analyst consensus, price targets -- then re-runs the valuation and
rating engines in-process against the cached fundamentals, so the ratings move
with the market without a rebuild. It needs yfinance; everything else here
runs on the standard library against the database.
"""

from __future__ import annotations

import argparse
import csv
import errno
import io
import subprocess
import json
import sqlite3
import threading
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import config, db

PORT = 8899
HOST = "127.0.0.1"

_refresh_lock = threading.Lock()
_last_refresh: dict = {"at": None, "ok": 0, "failed": []}


# ---------------------------------------------------------------------------
# data access
# ---------------------------------------------------------------------------


def _rows(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM companies ORDER BY score DESC"):
        d = dict(r)
        d["payload"] = json.loads(d["payload"]) if d.get("payload") else {}
        d["notes"] = d["notes"].split(" | ") if d.get("notes") else []
        d["rec_trend"] = json.loads(d["rec_trend"]) if d.get("rec_trend") else None
        out.append(d)
    return out


def _peer_stats(conn: sqlite3.Connection) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT * FROM peer_stats")}


def _filings(conn: sqlite3.Connection, ticker: str | None = None) -> dict:
    q = "SELECT * FROM filings"
    args: tuple = ()
    if ticker:
        q += " WHERE ticker = ?"
        args = (ticker,)
    q += " ORDER BY filed DESC"
    out: dict[str, list[dict]] = {}
    for r in conn.execute(q, args):
        out.setdefault(r["ticker"], []).append(dict(r))
    return out


def _facts(conn: sqlite3.Connection, ticker: str) -> dict:
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
        "SELECT * FROM edgar_facts WHERE ticker = ? ORDER BY concept, fy DESC",
        (ticker,),
    ):
        out.setdefault(r["concept"], []).append(dict(r))
    return out


def screener_payload() -> dict:
    conn = db.connect()
    try:
        rows = _rows(conn)
        filings = _filings(conn)
        for r in rows:
            fl = filings.get(r["ticker"], [])
            r["filings"] = fl[:12]
            r["filing_counts"] = {
                form: sum(1 for f in fl if f["base_form"] == form)
                for form in ("10-K", "10-Q", "8-K", "DEF 14A")
            }
            r["latest_10k"] = next((f for f in fl if f["base_form"] == "10-K"), None)
            r["latest_10q"] = next((f for f in fl if f["base_form"] == "10-Q"), None)
        return {
            "companies": rows,
            "peer_stats": _peer_stats(conn),
            "meta": db.read_meta(conn),
            "snapshots": db.snapshot_meta(conn),
            "mix": config.RECOMMENDATION_MIX,
            "thresholds": {
                "buy": config.BUY_THRESHOLD,
                "sell": config.SELL_THRESHOLD,
            },
            "subject": config.SUBJECT,
            "last_refresh": _last_refresh,
            "served_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    finally:
        conn.close()


def company_payload(ticker: str) -> dict | None:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM companies WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"]) if d.get("payload") else {}
        d["notes"] = d["notes"].split(" | ") if d.get("notes") else []
        d["rec_trend"] = json.loads(d["rec_trend"]) if d.get("rec_trend") else None
        d["filings"] = _filings(conn, ticker.upper()).get(ticker.upper(), [])
        d["facts"] = _facts(conn, ticker.upper())
        d["peer_stats"] = _peer_stats(conn)
        return d
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# live refresh
# ---------------------------------------------------------------------------


def refresh_quotes() -> dict:
    """Re-poll quotes and consensus, re-rate, and write back.

    Serialised behind a lock: two browser tabs auto-refreshing should not
    produce two concurrent rounds of Yahoo requests.
    """
    if not _refresh_lock.acquire(blocking=False):
        return {"status": "busy", **_last_refresh}

    try:
        from . import market, valuation  # imported here so the API works without yfinance

        conn = db.connect()
        cached = {}
        metas = {}
        for r in conn.execute("SELECT ticker, cik, sells_to, sec_name, sic_description FROM companies"):
            t = r["ticker"]
            metas[t] = dict(r)
            c = market.load_cached(t, ttl_hours=-1)
            if c:
                cached[t] = c

        failed = []
        for t, rec in cached.items():
            try:
                rec["quote"] = market.quote(t)
                market.save_cached(t, rec)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{t}: {type(exc).__name__}")

        rows, peers = valuation.run(cached)
        # NOT db.init() here. That runs the schema script, which drops every
        # table -- including filings and edgar_facts, which a refresh does not
        # refetch and would therefore silently destroy, taking every 10-K and
        # 10-Q link in the UI with them. The ticker set cannot change during a
        # refresh and write_companies is INSERT OR REPLACE, so updating in
        # place is both sufficient and safe.
        db.write_companies(conn, rows, metas)
        db.write_peer_stats(conn, peers)
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.get("rating") or "unrated"] = counts.get(r.get("rating") or "unrated", 0) + 1
        db.write_meta(conn, {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "universe_size": len(rows),
            "subject": config.SUBJECT,
            "rating_counts": counts,
            "peer_fit": peers.get("ev_sales_fit"),
            "refreshed": True,
        })
        conn.close()

        _last_refresh.update({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ok": len(cached) - len(failed),
            "failed": failed,
        })
        return {"status": "ok", **_last_refresh}
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _refresh_lock.release()


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "ticker", "name", "sells_to", "rating", "score", "price", "change_pct",
    "market_cap", "trailing_eps", "forward_eps", "trailing_pe", "forward_pe",
    "revenue", "revenue_growth", "gross_margin", "operating_margin",
    "profit_margin", "peg", "value_score", "sentiment_score", "range_position",
    "analyst_rec", "analyst_rec_mean", "analyst_count", "target_mean",
    "short_pct_float", "cik", "notes",
]


def export_csv() -> str:
    conn = db.connect()
    try:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(CSV_COLUMNS)
        for r in conn.execute(f"SELECT {','.join(CSV_COLUMNS)} FROM companies ORDER BY score DESC"):
            w.writerow([r[c] for c in CSV_COLUMNS])
        return buf.getvalue()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter console
        if "/api/" in (self.path or ""):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        try:
            if path == "/api/screener":
                return self._json(screener_payload())

            if path.startswith("/api/company/"):
                ticker = path.rsplit("/", 1)[-1]
                data = company_payload(ticker)
                if data is None:
                    return self._json({"error": f"unknown ticker {ticker}"}, 404)
                return self._json(data)

            if path == "/api/refresh":
                result = refresh_quotes()
                if result.get("status") == "error":
                    return self._json(result, 500)
                return self._json({**result, "screener": screener_payload()})

            if path == "/api/export.csv":
                body = export_csv().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="saas-screener.csv"',
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            # static
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (config.WEB / rel).resolve()
            if not str(target).startswith(str(config.WEB.resolve())):
                return self._send(403, b"forbidden", "text/plain")
            if not target.exists() or not target.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = _CONTENT_TYPES.get(target.suffix, "application/octet-stream")
            return self._send(200, target.read_bytes(), ctype)

        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def _who_has_port(port: int) -> str | None:
    """Best-effort description of whatever is already listening."""
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()
    except Exception:
        return None
    return out[1] if len(out) > 1 else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="saasscreener.server")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--host", default=HOST)
    args = ap.parse_args(argv)

    if not config.DB_PATH.exists():
        print(f"No database at {config.DB_PATH}.")
        print("Build it first:  python -m saasscreener.build")
        return 1

    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        # A bare traceback here is unhelpful -- this is nearly always another
        # copy of this same server, so say so and give the one-line fix.
        print(f"Port {args.port} is already in use.")
        holder = _who_has_port(args.port)
        if holder:
            print(f"  held by: {holder}")
        print()
        print("If that is another copy of this screener, it is already serving at")
        print(f"  http://{args.host}:{args.port}")
        print("Otherwise stop it and try again:")
        print("  pkill -f saasscreener.server")
        print(f"Or run on a different port:  python -m saasscreener.server --port {args.port + 1}")
        return 1

    print(f"Software screener  ->  http://{args.host}:{args.port}")
    print("Ctrl-C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
