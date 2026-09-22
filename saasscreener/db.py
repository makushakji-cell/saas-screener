"""SQLite persistence.

The database is a rebuildable artefact, never a source of truth -- `build`
drops and recreates it from the cache each run. It exists so the screener is
queryable with plain SQL, the same way `sp500-dcf` works.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import config

SCHEMA = """
DROP VIEW  IF EXISTS screener;
DROP TABLE IF EXISTS companies;
DROP TABLE IF EXISTS filings;
DROP TABLE IF EXISTS edgar_facts;
DROP TABLE IF EXISTS peer_stats;
DROP TABLE IF EXISTS build_meta;

CREATE TABLE companies (
    ticker              TEXT PRIMARY KEY,
    name                TEXT,
    sec_name            TEXT,
    cik                 INTEGER,
    sells_to            TEXT,
    sic_description     TEXT,
    website             TEXT,

    price               REAL,
    prev_close          REAL,
    change_pct          REAL,
    market_cap          REAL,
    enterprise_value    REAL,
    week52_low          REAL,
    week52_high         REAL,
    range_position      REAL,

    revenue             REAL,
    revenue_growth      REAL,
    gross_margin        REAL,
    operating_margin    REAL,
    profit_margin       REAL,
    free_cash_flow      REAL,
    net_income          REAL,

    trailing_eps        REAL,
    forward_eps         REAL,
    trailing_pe         REAL,
    forward_pe          REAL,
    ps_ratio            REAL,
    ev_revenue          REAL,

    peg                 REAL,

    score               REAL,
    rating              TEXT,
    value_score         REAL,
    sentiment_score     REAL,

    analyst_rec         TEXT,
    analyst_rec_mean    REAL,
    analyst_count       REAL,
    target_mean         REAL,
    short_pct_float     REAL,
    rec_trend           TEXT,

    quote_text          TEXT,
    quote_speaker       TEXT,
    quote_title         TEXT,
    quote_url           TEXT,
    quote_filed         TEXT,

    notes               TEXT,
    payload             TEXT,
    quoted_at           TEXT,
    fetched_at          TEXT
);

CREATE TABLE filings (
    ticker      TEXT,
    cik         INTEGER,
    form        TEXT,
    base_form   TEXT,
    accession   TEXT,
    filed       TEXT,
    period      TEXT,
    doc_url     TEXT,
    index_url   TEXT,
    PRIMARY KEY (ticker, accession)
);

CREATE TABLE edgar_facts (
    ticker      TEXT,
    concept     TEXT,
    fy          INTEGER,
    period_end  TEXT,
    value       REAL,
    tag         TEXT,
    accession   TEXT,
    PRIMARY KEY (ticker, concept, fy)
);

CREATE TABLE peer_stats (
    key     TEXT PRIMARY KEY,
    value   REAL
);

CREATE TABLE build_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

CREATE VIEW screener AS
SELECT ticker, name, sells_to, rating, score, price, market_cap,
       trailing_eps, forward_eps, trailing_pe, forward_pe, revenue_growth,
       peg, value_score, sentiment_score, target_mean, notes
FROM companies;
"""

# Everything above is a rebuildable artefact and is dropped on each build.
# Snapshots are not: they are the accumulated record of what the model said
# and when, which is the only way to find out later whether it was any good.
# Created separately, never dropped.
SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    taken_on    TEXT,          -- calendar date, one row per company per day
    ticker      TEXT,
    price       REAL,
    rating      TEXT,
    score       REAL,
    peg         REAL,
    target_mean REAL,
    PRIMARY KEY (taken_on, ticker)
);
"""

_COLUMNS: list[str] | None = None


def connect(path=None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executescript(SNAPSHOT_SCHEMA)
    conn.commit()


def write_snapshot(conn: sqlite3.Connection, rows: list[dict], taken_on: str) -> int:
    """Record today's ratings. Re-running a build the same day overwrites
    rather than appends, so the series stays one point per day."""
    conn.executescript(SNAPSHOT_SCHEMA)
    payload = [
        (
            taken_on,
            r["ticker"],
            (r.get("quote") or {}).get("price"),
            r.get("rating"),
            r.get("score"),
            r.get("peg"),
            (r.get("quote") or {}).get("target_mean"),
        )
        for r in rows
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO snapshots "
        "(taken_on, ticker, price, rating, score, peg, target_mean) "
        "VALUES (?,?,?,?,?,?,?)",
        payload,
    )
    conn.commit()
    return len(payload)


def export_snapshots(conn: sqlite3.Connection) -> int:
    """Mirror the snapshot history to a CSV beside the database.

    The database itself is a rebuildable artefact and is not worth tracking in
    version control -- it is rewritten on every build. The snapshots inside it
    are the exception: they are the accumulated record of what the model said
    and when, and nothing can recreate them. Writing them out as text means the
    one irreplaceable thing in the project survives in git, a backup, or a
    copied folder.
    """
    import csv as _csv

    rows = list(conn.execute("SELECT * FROM snapshots ORDER BY taken_on, ticker"))
    path = config.DATA / "snapshots.csv"
    with path.open("w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(rows[0].keys() if rows else
                   ["taken_on", "ticker", "price", "rating", "score", "peg", "target_mean"])
        for r in rows:
            w.writerow(list(r))
    return len(rows)


def import_snapshots(conn: sqlite3.Connection) -> int:
    """Reload the CSV into the database, for a fresh clone or a lost db."""
    import csv as _csv

    path = config.DATA / "snapshots.csv"
    if not path.exists():
        return 0
    conn.executescript(SNAPSHOT_SCHEMA)
    with path.open(newline="") as fh:
        rows = [tuple(r.values()) for r in _csv.DictReader(fh)]
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO snapshots "
            "(taken_on, ticker, price, rating, score, peg, target_mean) "
            "VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
    return len(rows)


def snapshot_meta(conn: sqlite3.Connection) -> dict:
    try:
        r = conn.execute(
            "SELECT COUNT(DISTINCT taken_on) n, MIN(taken_on) first, MAX(taken_on) last "
            "FROM snapshots"
        ).fetchone()
    except sqlite3.OperationalError:
        return {"days": 0, "first": None, "last": None}
    return {"days": r["n"] or 0, "first": r["first"], "last": r["last"]}


def _columns(conn: sqlite3.Connection) -> list[str]:
    global _COLUMNS
    if _COLUMNS is None:
        _COLUMNS = [r[1] for r in conn.execute("PRAGMA table_info(companies)")]
    return _COLUMNS


def _flatten(row: dict, meta: dict) -> dict[str, Any]:
    """Project a computed row onto the companies table's flat shape."""
    q = row.get("quote") or {}

    return {
        **{k: row.get(k) for k in row if not isinstance(row.get(k), (dict, list))},
        "cik": meta.get("cik"),
        "sells_to": meta.get("sells_to"),
        "sec_name": meta.get("sec_name"),
        "sic_description": meta.get("sic_description"),
        "price": q.get("price"),
        "prev_close": q.get("prev_close"),
        "change_pct": q.get("change_pct"),
        "market_cap": q.get("market_cap"),
        "week52_low": q.get("week52_low"),
        "week52_high": q.get("week52_high"),
        "analyst_rec": q.get("analyst_rec"),
        "analyst_rec_mean": q.get("analyst_rec_mean"),
        "analyst_count": q.get("analyst_count"),
        "target_mean": q.get("target_mean"),
        "quoted_at": q.get("quoted_at"),
        "rec_trend": json.dumps(row.get("rec_trend")) if row.get("rec_trend") else None,
        "quote_text": (row.get("exec_quote") or {}).get("quote"),
        "quote_speaker": (row.get("exec_quote") or {}).get("speaker"),
        "quote_title": (row.get("exec_quote") or {}).get("title"),
        "quote_url": (row.get("exec_quote") or {}).get("source_url"),
        "quote_filed": (row.get("exec_quote") or {}).get("filed"),
        "notes": " | ".join(row.get("notes") or []) or None,
        # The full computed record, so the interface can show the working
        # without the schema growing a column per nested field.
        "payload": json.dumps(row, default=str),
    }


def write_companies(conn: sqlite3.Connection, rows: list[dict], metas: dict) -> None:
    cols = _columns(conn)
    payloads = []
    for row in rows:
        flat = _flatten(row, metas.get(row["ticker"], {}))
        payloads.append(tuple(flat.get(c) for c in cols))

    placeholders = ",".join("?" * len(cols))
    conn.executemany(
        f"INSERT OR REPLACE INTO companies ({','.join(cols)}) VALUES ({placeholders})",
        payloads,
    )
    conn.commit()


def write_filings(conn: sqlite3.Connection, ticker: str, cik: int, rows: list[dict]) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO filings
           (ticker, cik, form, base_form, accession, filed, period, doc_url, index_url)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        [
            (
                ticker,
                cik,
                r["form"],
                r["base_form"],
                r["accession"],
                r["filed"],
                r.get("period"),
                r.get("doc_url"),
                r.get("index_url"),
            )
            for r in rows
        ],
    )
    conn.commit()


def write_facts(conn: sqlite3.Connection, ticker: str, facts: dict) -> None:
    rows = [
        (ticker, concept, item["fy"], item.get("end"), item.get("val"),
         item.get("tag"), item.get("accn"))
        for concept, items in facts.items()
        for item in items
    ]
    if rows:
        conn.executemany(
            """INSERT OR REPLACE INTO edgar_facts
               (ticker, concept, fy, period_end, value, tag, accession)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()


def write_peer_stats(conn: sqlite3.Connection, peers: dict) -> None:
    flat = {k: v for k, v in peers.items() if isinstance(v, (int, float))}
    fit = peers.get("ev_sales_fit") or {}
    for k, v in fit.items():
        flat[f"fit_{k}"] = v
    conn.executemany(
        "INSERT OR REPLACE INTO peer_stats (key, value) VALUES (?,?)", list(flat.items())
    )
    conn.commit()


def write_meta(conn: sqlite3.Connection, meta: dict) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO build_meta (key, value) VALUES (?,?)",
        [(k, json.dumps(v, default=str)) for k, v in meta.items()],
    )
    conn.commit()


def read_meta(conn: sqlite3.Connection) -> dict:
    return {
        r["key"]: json.loads(r["value"])
        for r in conn.execute("SELECT key, value FROM build_meta")
    }
