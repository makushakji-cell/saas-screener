"""SEC EDGAR ingestion: CIK resolution, filing index, and XBRL company facts.

Two things come from EDGAR and nowhere else:

  * the filing links themselves -- every 10-K and 10-Q, with its period and
    accession number, so a ticker in the screener can hyperlink to the primary
    documents a reader would actually want;
  * a check on the market data. Revenue and net income as the company itself
    reported them in XBRL, used to verify the numbers Yahoo hands back.

Only the standard library is used here, so this module runs without the venv.
"""

from __future__ import annotations

import gzip
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from . import config

_BASE_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_BASE_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_TICKER_FILE = "https://www.sec.gov/files/company_tickers.json"

# EDGAR's viewer renders the filing with its exhibits; the Archives path is the
# raw primary document. We link the viewer because it is what a human wants.
FILING_VIEWER = "https://www.sec.gov/cgi-bin/viewer?action=view&cik={cik}&accession_number={acc}"
FILING_INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}-index.htm"
FILING_DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
COMPANY_PAGE = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={cik:010d}&type={form}&dateb=&owner=include&count=40"
)

_rate_lock = threading.Lock()
_last_request = [0.0]


def _get(url: str) -> Any:
    """Fetch and parse JSON from EDGAR, respecting the published rate limit."""
    with _rate_lock:
        gap = 1.0 / config.SEC_RATE_LIMIT
        wait = gap - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": config.SEC_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Host": urllib.parse.urlsplit(url).hostname or "",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# CIK resolution
# ---------------------------------------------------------------------------

_cik_map: dict[str, tuple[int, str]] | None = None


def cik_map(refresh: bool = False) -> dict[str, tuple[int, str]]:
    """ticker -> (cik, registrant name) for every current SEC filer."""
    global _cik_map
    if _cik_map is not None and not refresh:
        return _cik_map

    path = config.DATA / "company_tickers.json"
    if refresh or not path.exists():
        data = _get(_TICKER_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    else:
        data = json.loads(path.read_text())

    _cik_map = {
        v["ticker"].upper(): (int(v["cik_str"]), v["title"]) for v in data.values()
    }
    return _cik_map


def resolve(ticker: str) -> tuple[int, str] | None:
    return cik_map().get(ticker.upper())


# ---------------------------------------------------------------------------
# Filings
# ---------------------------------------------------------------------------


def filings(cik: int, forms: tuple[str, ...] = config.EDGAR_FORMS) -> list[dict]:
    """Recent filings of the given form types, newest first.

    EDGAR splits a long filing history across `recent` plus paginated overflow
    files. For 10-K/10-Q the recent block reaches back several years, which is
    all we display, so the overflow is not fetched.
    """
    data = _get(_BASE_SUBMISSIONS.format(cik=cik))
    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []

    cols = ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument")
    rows = zip(*(recent.get(c, []) for c in cols))

    wanted = {f.upper() for f in forms}
    out: list[dict] = []
    seen: dict[str, int] = {}

    for form, acc, filed, period, doc in rows:
        key = form.upper()
        # 10-K/A and 10-Q/A are amendments; group them with the parent form so
        # an amended quarter does not crowd out an unamended one.
        base = key.split("/")[0]
        if base not in wanted:
            continue
        if seen.get(base, 0) >= config.EDGAR_KEEP_PER_FORM:
            continue
        seen[base] = seen.get(base, 0) + 1

        acc_nodash = acc.replace("-", "")
        out.append(
            {
                "form": form,
                "base_form": base,
                "accession": acc,
                "filed": filed,
                "period": period or None,
                "doc_url": FILING_DOC.format(cik=cik, acc_nodash=acc_nodash, doc=doc)
                if doc
                else None,
                "index_url": FILING_INDEX.format(
                    cik=cik, acc_nodash=acc_nodash, acc=acc
                ),
            }
        )

    return out


def company_meta(cik: int) -> dict:
    """Registrant metadata: exact name, SIC, state, fiscal year end."""
    data = _get(_BASE_SUBMISSIONS.format(cik=cik))
    return {
        "sec_name": data.get("name"),
        "sic": data.get("sic"),
        "sic_description": data.get("sicDescription"),
        "fiscal_year_end": data.get("fiscalYearEnd"),
        "state": data.get("stateOfIncorporation"),
        "exchange": (data.get("exchanges") or [None])[0],
    }


# ---------------------------------------------------------------------------
# XBRL company facts
# ---------------------------------------------------------------------------

# Companies tag the same economic concept under different us-gaap elements.
# Each entry is tried in order until one yields data.
_FACT_ALIASES = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "assets": ["Assets"],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
}


def company_facts(cik: int) -> dict:
    """Annual (FY) values for the concepts in _FACT_ALIASES, newest first.

    Returns {concept: [{"fy", "end", "val", "form", "accn", "tag"}, ...]}.
    Only 10-K figures are kept, deduplicated by fiscal year with the most
    recently filed value winning -- that is the restated number if there is one.
    """
    try:
        data = _get(_BASE_FACTS.format(cik=cik))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise

    gaap = data.get("facts", {}).get("us-gaap", {})
    out: dict[str, list[dict]] = {}

    for concept, tags in _FACT_ALIASES.items():
        for tag in tags:
            node = gaap.get(tag)
            if not node:
                continue
            units = node.get("units", {}).get("USD")
            if not units:
                continue

            by_fy: dict[int, dict] = {}
            for item in units:
                if item.get("form") not in ("10-K", "10-K/A"):
                    continue
                if item.get("fp") != "FY":
                    continue
                # Income-statement concepts are durations; skip the quarterly
                # slices that share the FY label but cover ~90 days.
                start, end = item.get("start"), item.get("end")
                if start and end:
                    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                    if days < 300:
                        continue

                fy = item.get("fy")
                if fy is None:
                    continue
                prev = by_fy.get(fy)
                if prev is None or (item.get("filed") or "") > (prev.get("_filed") or ""):
                    by_fy[fy] = {
                        "fy": fy,
                        "end": end,
                        "val": item.get("val"),
                        "form": item.get("form"),
                        "accn": item.get("accn"),
                        "tag": tag,
                        "_filed": item.get("filed"),
                    }

            if by_fy:
                rows = sorted(by_fy.values(), key=lambda r: r["fy"], reverse=True)[:6]
                for r in rows:
                    r.pop("_filed", None)
                out[concept] = rows
                break  # first alias that produced data wins

    return out
