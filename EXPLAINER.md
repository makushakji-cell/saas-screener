# The screener, explained simply

What the tool does, and how to talk about it.

---

## The one idea

**A P/E ratio on its own tells you nothing about whether a stock is expensive.**

P/E is the share price divided by earnings per share — how many dollars you pay
for each dollar of annual profit. AppFolio costs $206.27 a share and is expected
to earn $8.43, so:

```
$206.27 ÷ $8.43  =  24.5
```

You pay **$24.50 for every $1 of annual profit.**

Now: is 24.5 expensive? You can't say. **40× is cheap for a company compounding
30% a year, and 40× is outrageous for one growing 3%** — because the fast
grower's dollar of profit becomes several dollars, while the slow grower's stays
a dollar.

So you have to hold the two together. The way to do that is divide one by the
other:

> ### P/E ÷ growth rate

That's what you pay per dollar of profit, **per point of growth.** Lower is
cheaper. It's a standard measure, commonly called the PEG ratio.

---

## Two companies, side by side

| | P/E | Growth | P/E ÷ Growth |
|---|---|---|---|
| **Samsara** | 40.3× | 29.9% | **1.3** |
| **Tyler Technologies** | 21.6× | 8.2% | **2.6** |

Samsara's headline P/E is nearly **twice** Tyler's — it looks far more
expensive. But per point of growth it costs **half as much.**

That reversal is the whole point of the exercise. It's the kind of thing you
cannot see by looking at either number alone.

---

## The full picture

Across the 21 companies here that are both profitable and growing, the measure
runs from **0.60 to 3.78**, with a **median of 1.45.**

**Cheapest per point of growth:**

| | P/E | Growth | P/E ÷ Growth |
|---|---|---|---|
| Zillow | 10.8× | 17.9% | 0.60 |
| Toast | 17.1× | 23.1% | 0.74 |
| CoStar | 16.2× | 18.4% | 0.88 |
| Workiva | 17.2× | 18.6% | 0.93 |

**Dearest:**

| | P/E | Growth | P/E ÷ Growth |
|---|---|---|---|
| EverCommerce | 10.2× | 2.7% | 3.78 |
| Tyler | 21.6× | 8.2% | 2.63 |
| Blackbaud | 7.1× | 3.0% | 2.35 |
| Doximity | 17.1× | 7.3% | 2.34 |

Note **Blackbaud**: a 7.1× P/E looks like the cheapest stock in the group by a
mile. But it's barely growing, so per point of growth it's one of the dearest.
That's the trap the measure is designed to catch.

---

## How the rating works

```
score  =  65% × (P/E ÷ growth)  +  35% × market sentiment
```

**Value (65%)** — the measure above, scored against where this group sits. The
median of 1.45 scores 50 out of 100; 0.6 scores near 100; 2.6 scores near 13.

**Sentiment (35%)** — what everyone else thinks: the published analyst
consensus, where the price sits within its own 12-month range, and how much of
the float is sold short.

BUY at 60 or above, SELL at 40 or below. Currently **7 buy, 11 hold, 4 sell.**

Sentiment is deliberately the minority share but not absent — a cheap company
everyone hates may be cheap for a reason, while a cheap company the market likes
is more actionable.

---

## Saying it in an interview

> "I built a screener for AppFolio and 21 comparable software companies.
>
> The core idea is that a P/E ratio means nothing without growth beside it. Forty
> times earnings is cheap for a company compounding 30% and expensive for one
> growing 3%. So I divide the P/E by the growth rate — that gives you what you
> pay per dollar of profit, per point of growth. Lower is cheaper.
>
> It surfaces things you'd otherwise miss. Blackbaud trades at 7× earnings, the
> lowest multiple in the group — but it's only growing 3%, so per point of growth
> it's one of the most expensive names there. Samsara is the opposite: 40×
> earnings looks dear until you see the 30% growth behind it.
>
> The rating is 65% that measure and 35% market sentiment — analyst consensus,
> where the price sits in its 12-month range, short interest.
>
> It's a **relative** comparison, not a valuation. I'm ranking these companies
> against each other, not saying what any one is worth. And it only looks at
> growth and profit — it can't see competitive position, switching costs or
> customer retention, which is why every ticker links to the company's SEC
> filings."

**That last paragraph matters most.** It's the difference between sounding like
you ran a script and sounding like you know what it can't do.

---

## The follow-up questions

**"Isn't a PEG of 1.0 supposed to be fair value?"**

That's the textbook rule, and it comes from slower-growth industries. Software
routinely trades above it — the median here is 1.45. So I score each company
against where this group actually sits rather than against an absolute
threshold. Otherwise nearly every software company screens expensive and the
tool stops discriminating.

**"Why revenue growth rather than earnings growth?"**

Orthodox PEG uses earnings growth. I used revenue growth because my data source
reports trailing EPS on a GAAP basis and forward EPS on an adjusted one, so the
implied earnings growth between them is an accounting artefact — Zillow reads
1171%. Revenue growth is clean.

**"What are the weaknesses?"**

Three, and I'd name them before being asked:

1. It **needs profit and growth.** SmartRent has neither, so it can't be scored on value at all — it's flagged and rated on sentiment alone.
2. It's **relative.** If the whole sector is mispriced, the tool can't see it.
3. It's **backward-looking on growth** and forward-looking on earnings. A company whose growth is about to inflect looks wrong in both directions.

**"What would you add?"**

Track record. Every build now records a dated snapshot of its own ratings, so in
a few months `query track` will report whether the BUY bucket actually beat the
SELL bucket. Until there's data, the honest answer is that I don't know if it
works yet.
