# Software screener — AppFolio and peers

A financial screener for AppFolio and 21 comparable software companies. One
list, one valuation equation you can check by hand, and one buy / hold / sell
per company. Every ticker links to that company's SEC filings.

```bash
cd ~/saas-screener
./.venv/bin/python -m saasscreener.server        # opens http://127.0.0.1:8899
```

Current build: **22 companies, 21 scored on value** (SmartRent is neither
profitable nor growing, so it has no P/E to compare), all 22 matched to an SEC
CIK, 20 with a sourced executive quote.

---

## The peer group

AppFolio is vertical SaaS for property management: SMB and mid-market
customers, subscription software with a large embedded-payments attach on top.
There is no clean set of listed pure-play competitors — **RealPage, Yardi,
Entrata and MRI are all private** — so the group is built in three rings, and
the UI lets you filter to any one of them.

| Ring | What it shares with AppFolio | Companies |
|---|---|---|
| **Same end market** | sells into real estate / property / buildings | APPF, CSGP, ZG, ALRM, SMRT |
| **Same business model** | SMB vertical SaaS with a payments or money-movement take rate | TTAN, TOST, EVCM, PCTY, WEAV |
| **Vertical SaaS comparable** | same shape of business, different vertical — widens the sample the multiple range is drawn from | PCOR, TYL, VEEV, GWRE, BLKB, QTWO, NCNO, INTA, WK, BSY, DOCS, IOT |

Every name is treated identically by the valuation and rating engines; the ring
is only for grouping and filtering.

> Two names that belong in this group are gone: **Olo** and **Clearwater
> Analytics** were both taken private and are no longer SEC filers, so neither
> has a CIK or a current quote. Paylocity and Samsara took their slots.

---

## What it computes

### Value — P/E divided by growth

A P/E on its own says nothing about whether a company is expensive: 40× is cheap
for something compounding 30% and dear for something growing 3%. Dividing one by
the other gives a figure comparable across the whole group.

```
P/E per point of growth  =  forward P/E ÷ revenue growth %
```

Lower is cheaper. Samsara trades at 40.3× while growing 29.9% → **1.3**. Tyler
trades at 21.6× while growing 8.2% → **2.6**. Samsara's headline multiple is
nearly double, but per point of growth it costs half as much. This is the classic
PEG ratio. Across the 21 profitable, growing companies here it runs 0.60 to 3.78,
median **1.45**.

> This replaced a least-squares fit of P/E on growth, which produced a fair value
> per share and an upside percentage. The regression fit better — R² 0.46 — but
> it could not be explained in a sentence, and **a number nobody can defend is
> worth less than a cruder one they can.** PEG needs no explanation beyond its
> own name.

### The rating

```
score = 65% × value  +  35% × market mood
```

**Value** is the P/E-per-point-of-growth figure above, scored against where the group sits — the median of 1.45 scores 50. **Market mood** is what
everyone else thinks, from three signals: the published analyst consensus (50%),
where the price sits within its own 12-month range (30%), and how much of the
float is sold short (20%).

BUY at 60+, SELL at 40 or below. Currently **7 buy, 11 hold, 4 sell**.

Sentiment is deliberately a minority of the score but not absent. A cheap
company everyone hates may be a value trap; a cheap company the market likes is
more actionable. Where the two halves disagree sharply, the company says so in
plain words — "popular with the market despite looking expensive."

## How to read the output

**It is a ranking, not a valuation.** The measure says what a company costs per
point of growth *relative to these 21 peers*. It does not say what any company
is worth. If the whole sector is mispriced, the tool cannot see it.

**A low P/E is not the same as cheap.** Blackbaud trades at 7.1× — the lowest
multiple in the group by a wide margin — but grows 3%, so per point of growth it
is one of the dearest names here. That inversion is the main thing the tool is
built to surface.

**Check the notes.** Where something needed a caveat it is written in plain
English on the row: thin analyst coverage, more than one share class, or rated
on sentiment alone because the company is not profitable.

### Known limitations

- **Only profitable companies can be valued.** The equation needs a positive
  expected EPS. SmartRent has none, so it is rated on market sentiment alone and
  says so.
- **Yahoo's trailing EPS is GAAP and its forward EPS is non-GAAP consensus,** so
  the two are not strictly comparable and the jump between the `EPS` and
  `EPS next year` columns overstates real earnings growth. The valuation sidesteps
  this by driving off *revenue* growth, which has no such problem.
- **Dual-class share counts.** Yahoo's `sharesOutstanding` reports one class
  while its `marketCap` covers all of them. For Zillow the two disagree by 5.4×,
  for AppFolio by 1.47×. Share count is therefore derived as market cap ÷ price,
  which is consistent with the enterprise value the multiples are built from;
  the six affected names carry a `multi_class_shares` flag.
- **The measure needs profit and growth.** SmartRent has neither, so it cannot
  be scored on value and is flagged as rated on sentiment alone.
- **Growth is backward-looking, earnings are forward-looking.** A company whose
  growth is about to inflect will look wrong in both directions.
- **Nothing qualitative is modelled.** No competitive position, no management,
  no customer concentration, no pending litigation. That is what the filings the
  tool links to are for.

---

## Using it

### Web app

```bash
./.venv/bin/python -m saasscreener.server
```

One list: **Company · Size · Price · EPS · P/E · Growth · P/E ÷ Growth ·
Analyst target · Rating**. Sorted by score; click any heading to re-sort, or
hover it for a sentence explaining that metric. The P/E ÷ Growth figure is
coloured against the group median rather than an absolute threshold.

**Click a company** to expand it into four short sections:

- **What you pay for the growth** — the division, line by line, against the group median
- **What the analysts say** — the rating breakdown as counts (2 strong buy, 6 buy, 1 hold), the number covering, and the average target
- **What the company says** — an executive quote pulled from the company's own earnings release, with a link to that SEC filing. Omitted where none could be extracted
- **The numbers** and **SEC filings**

Click a **ticker** for the full EDGAR history; the `10-K` and `10-Q` chips open
the latest of each.

Prices and ratings re-poll every 90 seconds while the tab is visible;
**Refresh** does it on demand. **CSV** carries every field.

> The interface was rebuilt three times, and the model twice. The first version
> had tiles, tabs, two charts and 24 columns; the second blended three valuation
> methods; the third fitted a regression of P/E on growth. Each was defensible.
> What survived is the version that can be explained in one sentence.

### Command line

```bash
./.venv/bin/python -m saasscreener.query screen --rating BUY
./.venv/bin/python -m saasscreener.query screen --max-pe 20 --min-growth 15
./.venv/bin/python -m saasscreener.query show APPF
./.venv/bin/python -m saasscreener.query filings APPF
./.venv/bin/python -m saasscreener.query peers
./.venv/bin/python -m saasscreener.query history APPF
./.venv/bin/python -m saasscreener.query track
./.venv/bin/python -m saasscreener.query check
./.venv/bin/python -m saasscreener.query sql "SELECT ticker, peg FROM screener"
```

`track` is the one that matters over time. Every build records a dated
snapshot of what the model said, in the one table a rebuild does **not** drop.
After a few weeks of builds it reports whether the BUY bucket actually beat the
SELL bucket — which is the only honest way to find out if a model with an R² of
0.46 is worth following. `history APPF` shows one company's calls over time.

`check` verifies that every company is priced, rated, valued, matched to a CIK
and has its 10-K, 10-Q and XBRL facts on file. Run it after a rebuild if
anything looks wrong — it exits non-zero and names the companies at fault.

### Straight SQL

`data/screener.db` is a plain SQLite file. The `screener` view is the headline
table; `companies` carries every computed field plus the full JSON payload,
and `filings`, `edgar_facts` and `peer_stats` hold the rest.

```sql
SELECT ticker, name, rating, score, forward_pe, revenue_growth, peg
FROM screener
WHERE peg > 0 AND revenue_growth > 15
ORDER BY peg ASC;
```

---

## Rebuilding

```bash
./.venv/bin/python -m saasscreener.build              # everything: EDGAR + Yahoo
./.venv/bin/python -m saasscreener.build --quotes     # prices and consensus only
./.venv/bin/python -m saasscreener.build --recompute  # re-model from cache, no network
./.venv/bin/python -m saasscreener.build --tickers APPF,TOST
```

A full build takes about 25 seconds. Fundamentals are cached per ticker in
`data/cache/` with a 12-hour TTL; quotes are refetched every run regardless, so
a cache hit still gives a live price. Yahoo rate-limits above ~4 concurrent
requests — the defaults stay under it, and the cache makes a build resumable.

EDGAR requests carry the descriptive User-Agent the SEC requires and are
serialised below the published 10 req/s ceiling. Change the contact address in
`config.SEC_USER_AGENT` if someone else runs this.

---

## Layout

```
saasscreener/
  config.py      universe, weights, curves and bounds — each with its reasoning
  edgar.py       SEC: CIK resolution, filing index, XBRL company facts (stdlib only)
  market.py      Yahoo ingestion via yfinance; quote and fundamentals split by refresh cost
  valuation.py   the value measure and the rating engine (stdlib only)
  build.py       pipeline: universe → EDGAR + Yahoo → valuation → SQLite
  server.py      JSON API + static server + live refresh (stdlib only)
  query.py       command-line screener
web/             the browser app — no build step, no framework
data/screener.db the database
data/cache/      raw fundamentals per ticker
```

Runtime dependencies are `yfinance`, `pandas` and `requests`, all in `.venv`.
Everything except `market.py` runs on the standard library.

---

## Sources

Filing links, CIK numbers, SIC codes and the as-reported annual figures come
from **SEC EDGAR**. Prices, multiples, estimates and the sell-side consensus
come from **Yahoo Finance** via `yfinance`, and carry that source's accuracy and
delay.

*This is a screening and comparison tool, not investment advice.*
