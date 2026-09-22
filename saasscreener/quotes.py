"""Pull a real, attributed executive quote from each company's own filings.

Every quarter a company files its earnings press release with the SEC as an
exhibit to an 8-K, and that release almost always contains a sentence in
quotation marks attributed to a named executive. That is the only kind of
quote this tool will show: **published by the company, filed with the
regulator, and linkable to the exact document it came from.**

Nothing here is generated, paraphrased, or taken from second-hand commentary.
If no attributed quote can be extracted the company simply has none, and the
interface omits the section -- an empty slot is better than a
plausible-sounding invention attached to a real person and a real security.
"""

from __future__ import annotations

import html
import re
import urllib.request

from . import edgar

_VERB = r"(?:said|says|according to|commented|stated|noted|added|remarked)"

# Releases use both word orders --
#   "said Shane Trigg, Chairman and CEO"      (name first)
#   "said Toast CEO Aman Narang"              (title first)
# -- so rather than guess, capture the whole attribution clause and parse it.
_PATTERNS = [
    # "<quote>," said <attribution>.
    (re.compile(
        r'[“"]([^”"]{40,700}?)[”"][\s,]*' + _VERB
        + r'\s+([^.“”"]{3,90}?)\s*[.“]', re.DOTALL), False),
    # <attribution> said "<quote>"
    (re.compile(
        r'([A-Z][^.“”"]{3,90}?)\s*,?\s*' + _VERB
        + r'[\s,:]*[“"]([^”"]{40,700}?)[”"]', re.DOTALL), True),
]

_ROLE = (r"chief\s+\w+\s+officer|chief\s+\w+|CEO|CFO|COO|CTO|CRO|CIO|"
         r"president|chair(?:man|woman|person)?|founder|co-founder|"
         r"head\s+of\s+\w+|managing\s+\w+|general\s+manager|"
         r"executive\s+\w+|vice\s+president")
_ROLE_RE = re.compile(_ROLE, re.I)
_CEO_RE = re.compile(r"chief\s+executive|CEO|founder|chair", re.I)
_NAME_RE = re.compile(r"^[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3}$")

# Phrases that appear in quotation marks in every release and are never quotes.
_BOILERPLATE = re.compile(
    r"^(the\s+)?(company|corporation|issuer)\b|safe harbor|forward-looking|"
    r"as amended|interest expense|interest income|non-GAAP", re.I)


def _split_attribution(text: str) -> tuple[str, str] | None:
    """Turn an attribution clause into (name, title), or None if it isn't one."""
    text = text.strip(" ,;:—-")
    if not text:
        return None

    if "," in text:
        name, title = (p.strip() for p in text.split(",", 1))
        if _NAME_RE.match(name) and _ROLE_RE.search(title):
            return name, title

    # No comma: the role precedes the name, sometimes after the company name.
    last = None
    for last in _ROLE_RE.finditer(text):
        pass
    if last:
        title, name = text[: last.end()].strip(), text[last.end():].strip()
        if _NAME_RE.match(name):
            return name, title
    return None


def _text(body: bytes) -> str:
    raw = body.decode("utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def _exhibit_urls(cik: int, accession: str) -> list[str]:
    """Documents in a filing, most-likely press release first."""
    nodash = accession.replace("-", "")
    try:
        idx = edgar._get(
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/index.json")
    except Exception:
        return []
    names = [i.get("name", "") for i in idx.get("directory", {}).get("item", [])
             if i.get("name", "").lower().endswith((".htm", ".html"))]
    # Index pages are not exhibits. Prefer ex-99.x -- the conventional slot for
    # an earnings release -- and prefer shorter names, since the long ones tend
    # to be credit agreements and equity plans.
    names = [n for n in names if "index" not in n.lower()]
    names.sort(key=lambda n: (
        0 if re.search(r"ex.?99|99\d|press|release|earnings", n, re.I) else 1,
        len(n)))
    return [f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{n}"
            for n in names[:6]]


def latest_quote(cik: int, max_filings: int = 6) -> dict | None:
    """First attributed executive quote in the most recent earnings release.

    Walks back several 8-Ks, because not every one is an earnings release --
    some announce a board change or a debt facility and carry no quote.
    """
    try:
        filings = edgar.filings(cik, forms=("8-K",))
    except Exception:
        return None

    for f in filings[:max_filings]:
        for url in _exhibit_urls(cik, f["accession"]):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": edgar.config.SEC_USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    txt = _text(resp.read())
            except Exception:
                continue
            if len(txt) < 400:
                continue

            found = []
            for pattern, reversed_order in _PATTERNS:
                for m in pattern.finditer(txt):
                    a, b = m.groups()
                    quote, attribution = (b, a) if reversed_order else (a, b)
                    quote = quote.strip()
                    if _BOILERPLATE.search(quote) or len(quote.split()) < 8:
                        continue
                    parsed = _split_attribution(attribution)
                    if parsed:
                        found.append((parsed[0], parsed[1], quote))

            if found:
                # A release often quotes the CEO and then the CFO on the
                # numbers. The chief executive is the one worth showing, so
                # prefer that title and fall back to whoever spoke first.
                found.sort(key=lambda r: 0 if _CEO_RE.search(r[1]) else 1)
                name, title, quote = found[0]
                return {
                    "quote": quote,
                    "speaker": name,
                    "title": title,
                    "source_url": url,
                    "filed": f["filed"],
                    "form": f["form"],
                }
    return None
