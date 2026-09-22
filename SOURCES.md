# Where every number comes from

A plain-language guide to what this tool does, what each number means, and
which ones are facts from a source versus judgments the tool makes.

---

## The short version

Among AppFolio and 21 similar software companies, **which look cheap relative
to the others, and which look expensive?**

It works out the going rate the market pays for growth across the whole group,
then checks each company against it. It is a comparison, not a prediction.

---

## The two sources, and nothing else

### 1. SEC EDGAR — the government filing system

Free, official, no account. Where public companies legally must file results.

| What it gives | Used for |
|---|---|
| Ticker → CIK number | matching "APPF" to AppFolio's permanent SEC ID, 1433195 |
| Filing history | every 10-K and 10-Q, its period, filing date, and link |
| Reported financials | revenue, gross profit, operating income, net income and equity **as the company itself reported them** |

As authoritative as data gets. Its limitation is timing — it updates quarterly,
so nothing from here is live.

### 2. Yahoo Finance — via the `yfinance` library

Everything that moves and everything forward-looking: price, market cap,
revenue, margins, EPS (reported and forecast), P/E, analyst ratings, price
targets, short interest, and the 52-week range.

**Free and convenient but not authoritative.** It aggregates from data vendors
and can be stale. Two specific quirks are documented at the bottom.

---

## What each column means

| Column | Meaning | Source |
|---|---|---|
| **Size** | Market capitalisation — one share's price × every share. What the whole company is worth. | Yahoo |
| **Price** | Latest share price, and today's move. | Yahoo |
| **EPS** | Earnings per share expected next year — profit ÷ share count. The analysts' consensus forecast. | Yahoo |
| **P/E** | Price ÷ those expected earnings. Roughly how many years of profit you're paying for. | Yahoo |
| **Growth** | How much revenue grew over the past year. | Yahoo |
| **P/E ÷ Growth** | The P/E divided by the growth rate. **Calculated.** | the tool |
| **Rating** | Buy / hold / sell. **Calculated.** | the tool |

---

## The one calculation

A P/E on its own tells you nothing: 40× is cheap for a company compounding 30%
and dear for one growing 3%. So divide one by the other.

```
P/E per point of growth  =  forward P/E ÷ revenue growth %
```

**Lower is cheaper.** It is the standard PEG ratio.

| | P/E | Growth | Result |
|---|---|---|---|
| **Samsara** | 40.3× | 29.9% | **1.3** |
| **Tyler** | 21.6× | 8.2% | **2.6** |

Samsara's headline multiple is nearly double Tyler's, but per point of growth it
costs half as much. Across the 21 profitable, growing companies here the measure
runs 0.60 to 3.78, median **1.45**.

Watch Blackbaud: a 7.1× P/E is the lowest in the group, but on 3% growth it
works out to 2.35 — one of the dearest. **A low multiple is not the same as
cheap**, and catching that is the point.

## The rating

```
score = 65% × value  +  35% × market mood
```

**Value** = the P/E ÷ growth figure, scored against where this group sits (the median of 1.45 scores 50 out of 100).

**Market mood** = what everyone else thinks, from three signals:

| Signal | Weight | Why |
|---|---|---|
| Analyst consensus | 50% | the professional view, published |
| Price vs its 12-month range | 30% | the crowd voting with money |
| Short interest | 20% | the other side of that bet |

BUY at 60+, SELL at 40 or below.

Sentiment is a minority of the score but not absent, because a cheap company
everyone hates can be a value trap, while a cheap company the market likes is
more actionable. Where the two halves disagree sharply, the row says so —
*"popular with the market despite looking expensive."*

One thing worth knowing: across all 22 companies, analysts currently publish
**15 buys, 2 holds and zero sells**. That's an industry-wide pattern, not a fact
about these businesses, which is part of why their view is capped at a third of
the score.

---

## My judgment calls, not facts

All in one file, `saasscreener/config.py`, so you can change any of them.

| Choice | Value | Why |
|---|---|---|
| Which 22 companies | see README | RealPage, Yardi, Entrata and MRI — the real competitors — are all private |
| Value vs mood | 65 / 35 | the numbers should lead, but the crowd isn't nothing |
| Mood mix | 50 / 30 / 20 | analysts first, but not alone |
| BUY / SELL lines | 60 / 40 | round, and produces a sane spread |
| Scoring anchor | group median 1.45 = 50/100 | the textbook "PEG of 1 is fair" rule comes from slower industries and marks nearly all software expensive |

---

## Two Yahoo quirks that mattered

**1. Trailing EPS is GAAP, forward EPS is adjusted.** They're on different
accounting bases, so the jump between the `EPS` column and the forecast
overstates real earnings growth — Zillow implies 1171%, CoStar 885%. **This is
why the valuation runs off revenue growth, not earnings growth.** Revenue has no
such problem.

**2. Share counts and dual-class stock.** Yahoo's share count covers one class
while its market cap covers all of them — Zillow differs by 5.4×, AppFolio by
1.47×. The tool derives share count as market cap ÷ price instead. Companies
affected carry a note.

---

## What this cannot tell you

The measure sees two things: profit and growth. It cannot see competitive
position, switching costs, customer retention, management, contract length or
market size — the things you would learn from a 10-K and could never learn from
a ratio.

Tyler screens as one of the dearest names here. It also sells to city and state
governments on decade-long contracts that almost never change supplier, which is
genuinely valuable and completely invisible to this method.

**So the output is a list of questions, not answers.** The place to answer them
is the filings, which is why every ticker links to one.
