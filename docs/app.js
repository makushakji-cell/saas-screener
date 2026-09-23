'use strict';

/* One list of 22 companies. Nine simple columns, each row expanding to show
   the arithmetic behind its rating. */

let DATA = null;
let sortKey = 'score', sortDir = -1;
let open = null;

const $ = (id) => document.getElementById(id);
const ICON = { BUY: '▲', HOLD: '■', SELL: '▼' };

/* ------------------------------------------------------------ formatters */
const n = (v) => v === null || v === undefined || Number.isNaN(v);
const usd  = (v, d = 2) => n(v) ? '—' : `$${Number(v).toFixed(d)}`;
const pct  = (v, d = 1) => n(v) ? '—' : `${Number(v).toFixed(d)}%`;
const sgn  = (v, d = 0) => n(v) ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`;
const mult = (v) => (n(v) || v <= 0) ? '—' : `${Number(v).toFixed(1)}×`;
function big(v) {
  if (n(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (a >= 1e9)  return `$${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6)  return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toFixed(0)}`;
}
const dir = (v) => n(v) ? 'mut' : v > 0 ? 'up' : v < 0 ? 'down' : '';
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
function ago(iso) {
  if (!iso) return 'never';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return 'just now';
  if (s < 3600) return `${(s / 60) | 0}m ago`;
  if (s < 86400) return `${(s / 3600) | 0}h ago`;
  return `${(s / 86400) | 0}d ago`;
}

/* --------------------------------------------------------------- tooltip */
const tip = $('tip');
function hover(el, html) {
  el.addEventListener('mousemove', ev => {
    tip.innerHTML = html;
    tip.classList.add('on');
    const r = tip.getBoundingClientRect();
    let x = ev.clientX + 14, y = ev.clientY + 16;
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 16;
    tip.style.left = `${Math.max(8, x)}px`;
    tip.style.top = `${Math.max(8, y)}px`;
  });
  el.addEventListener('mouseleave', () => tip.classList.remove('on'));
}

/* ----------------------------------------------------------------- table */
const COLS = [
  { k: 'ticker', t: 'Company',
    help: 'Click the ticker for this company’s SEC filings; the 10-K and 10-Q chips open the latest annual and quarterly report.' },
  { k: 'market_cap', t: 'Size',
    help: 'Market capitalisation — the price of one share multiplied by every share outstanding. What the whole company is worth.' },
  { k: 'price', t: 'Price', help: 'Latest share price, with today’s move.' },
  { k: 'forward_eps', t: 'EPS',
    help: 'Earnings per share expected next year — the company’s profit divided by its share count. This is the analysts’ consensus forecast.' },
  { k: 'forward_pe', t: 'P/E',
    help: 'Price divided by those expected earnings. Roughly, how many years of profit you are paying for. A P/E of 20 means 20 years at next year’s profit level.' },
  { k: 'pe_vs_group', t: 'vs group',
    help: 'How this company’s P/E compares with the median across the group. AppFolio at 24.5x against a group median of 17.3x is a 41% premium. Read it together with the Growth column beside it — a premium is warranted if the company grows faster than the group, and is not if it does not.' },
  { k: 'revenue_growth', t: 'Growth',
    help: 'Revenue growth over the past year, sitting next to the multiple on purpose. The two only mean something together: Blackbaud trades at 7.1x, the lowest multiple here, but grows 3% — a low multiple on a stagnant company is not cheap.' },
  { k: 'operating_margin', t: 'Op margin',
    help: 'Operating margin \u2014 how much of each revenue dollar is left as operating profit after all the costs of running the business. 19% means 19 cents of every dollar. It shows what P/E cannot: ServiceTitan and Weave are growing but still lose money at the operating line.' },
  { k: 'ps_ratio', t: 'P/S',
    help: 'Price divided by annual revenue per share — what you pay per dollar of sales. Useful alongside P/E because it does not depend on profitability, so it stays comparable for companies whose earnings are thin or negative.' },
  { k: 'target_upside', t: 'Analyst target',
    help: 'The average 12-month price target published by analysts covering the stock, and how far the price sits from it. This is their number, not ours \u2014 shown beside our own upside so you can see where the two disagree. Note it is almost never negative: across these 22 companies the analyst view is positive on every single one, which is an industry pattern rather than a fact about these businesses.' },
  { k: 'rating', t: 'Rating',
    help: 'Our call. 65% the P/E-per-point-of-growth measure, 35% how the market feels about it — analyst ratings, where the price sits in its 12-month range, and how heavily it is shorted. The two bars show those halves. BUY at 60+, SELL at 40 or below.' },
];

function badge(r) {
  return r ? `<span class="badge ${r}"><span class="ic">${ICON[r]}</span>${r}</span>`
           : '<span class="badge NR">—</span>';
}
function edgar(c, form = '') {
  return c.cik
    ? `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${String(c.cik).padStart(10, '0')}&type=${encodeURIComponent(form)}&dateb=&owner=include&count=40`
    : null;
}

function cellFor(c, k) {
  switch (k) {
    case 'ticker': {
      const chip = (f, label) => f
        ? `<a href="${f.index_url}" target="_blank" rel="noopener" title="${label}, filed ${f.filed}">${label}</a>` : '';
      const notes = (c.notes ?? []).filter(Boolean);
      return `<a class="tk" href="${edgar(c) ?? '#'}" target="_blank" rel="noopener"
                 title="All SEC filings for ${esc(c.name ?? c.ticker)}">${c.ticker}</a>`
        + `<span class="sec">${chip(c.latest_10k, '10-K')}${chip(c.latest_10q, '10-Q')}</span>`
        + `<span class="nm">${esc(c.name ?? '')}</span>`
        + (notes.length ? `<span class="flag" title="${esc(notes.join(' · '))}">ⓘ</span>` : '');
    }
    case 'market_cap':   return big(c.market_cap);
    case 'price':
      return `${usd(c.price)} <span class="${dir(c.change_pct)}" style="font-size:11px">${sgn(c.change_pct, 1)}</span>`;
    case 'forward_eps':  return usd(c.forward_eps);
    case 'forward_pe':   return mult(c.forward_pe);
    case 'revenue_growth': return pct(c.revenue_growth, 0);
    case 'pe_vs_group': {
      const v = peVsGroup(c);
      if (v === null) return '<span class="mut">n/a</span>';
      // Not coloured. A premium is not automatically bad -- whether it is
      // depends on the growth column beside it, so colouring it would be
      // asserting something the number alone does not support.
      return `<span class="mut">${sgn(v)}</span>`;
    }
    case 'ps_ratio':     return mult(c.ps_ratio);
    case 'operating_margin':
      return `<span class="${dir(c.operating_margin)}">${pct(c.operating_margin, 0)}</span>`;
    case 'target_upside': {
      const u = targetUpside(c);
      if (u === null) return '<span class="mut">not covered</span>';
      return `${usd(c.target_mean)} <span class="${dir(u)}" style="font-size:11px">${sgn(u)}</span>`;
    }
    case 'rating': {
      // Two small bars: the value half and the sentiment half of the call.
      const seg = (v) => `<i class="${v != null && v >= 50 ? 'on' : ''}" title="${
        v != null ? v.toFixed(0) : 'n/a'}"></i>`;
      return badge(c.rating)
        + `<span class="mix">${seg(c.value_score)}${seg(c.sentiment_score)}</span>`;
    }
    default: return esc(c[k]);
  }
}

/* This company's P/E against the group median, in percent. */
function peVsGroup(c) {
  const med = (DATA.peer_stats || {}).forward_pe_median;
  return (med && c.forward_pe > 0) ? (c.forward_pe / med - 1) * 100 : null;
}

/* Upside to the analyst consensus target. Derived rather than stored, so it
   moves with the price on every refresh. */
function targetUpside(c) {
  return (c.target_mean && c.price) ? (c.target_mean / c.price - 1) * 100 : null;
}

function sorted() {
  const key = (r) => sortKey === 'target_upside' ? targetUpside(r)
                   : sortKey === 'pe_vs_group'  ? peVsGroup(r)
                   : r[sortKey];
  return [...DATA.companies].sort((a, b) => {
    const x = key(a), y = key(b);
    if (n(x) && n(y)) return 0;
    if (n(x)) return 1;
    if (n(y)) return -1;
    if (typeof x === 'string') return sortDir * x.localeCompare(y);
    return sortDir * (x < y ? -1 : x > y ? 1 : 0);
  });
}

function render() {
  $('thead').innerHTML = '<tr>' + COLS.map(c =>
    `<th data-k="${c.k}" class="${sortKey === c.k ? 'sorted' : ''}">${esc(c.t)}<span class="arrow">${
      sortKey === c.k ? (sortDir < 0 ? '▼' : '▲') : '▽'}</span></th>`).join('') + '</tr>';

  $('thead').querySelectorAll('th').forEach(th => {
    const col = COLS.find(c => c.k === th.dataset.k);
    hover(th, `<b>${esc(col.t)}</b><br>${esc(col.help)}`);
    th.addEventListener('click', () => {
      if (sortKey === th.dataset.k) sortDir = -sortDir;
      else { sortKey = th.dataset.k; sortDir = th.dataset.k === 'ticker' ? 1 : -1; }
      render();
    });
  });

  let html = '';
  for (const c of sorted()) {
    const isOpen = c.ticker === open;
    html += `<tr class="co ${c.ticker === DATA.subject ? 'subject' : ''} ${isOpen ? 'open' : ''}" data-tk="${c.ticker}">`
      + COLS.map(col => `<td>${cellFor(c, col.k)}</td>`).join('') + '</tr>';
    if (isOpen) html += `<tr class="detail"><td colspan="${COLS.length}"><div class="dwrap">${detail(c)}</div></td></tr>`;
  }
  $('tbody').innerHTML = html;

  $('tbody').querySelectorAll('tr.co').forEach(tr => tr.addEventListener('click', ev => {
    if (ev.target.closest('a')) return;
    open = open === tr.dataset.tk ? null : tr.dataset.tk;
    render();
  }));
}

/* ---------------------------------------------------------------- detail */
function detail(c) {
  const p = c.payload ?? {};
  const sd = p.sentiment_detail ?? {};

  /* A side-by-side against the group. This replaced a block that tried to
     explain the derived value measure and only confused matters -- it showed a
     "-1% discount" and a "0.74 premium per point of growth" in the same
     breath. A comps table needs no explanation: you read across. */
  const ps_ = DATA.peer_stats || {};
  const cmp = [
    ['P/E next year',    mult(c.forward_pe),                mult(ps_.forward_pe_median)],
    ['Revenue growth',   pct(c.revenue_growth, 1),          pct(ps_.growth_median, 1)],
    ['Operating margin', pct(c.operating_margin, 0),        pct(ps_.operating_margin_median, 0)],
    ['Gross margin',     pct(c.gross_margin, 0),            pct(ps_.gross_margin_median, 0)],
    ['Price / sales',    mult(c.ps_ratio),                  mult(ps_.ps_median)],
  ];
  const sum = `<table class="cmp">
      <thead><tr><th></th><th>${c.ticker}</th><th>Group median</th></tr></thead>
      <tbody>${cmp.map(([k, a, b]) =>
        `<tr><td>${k}</td><td class="me">${a}</td><td class="them">${b}</td></tr>`).join('')}
      </tbody></table>`;

  /* Analyst ratings, stated as counts. A distribution says something a single
     average cannot: "11 buys and 1 hold" and "5 buys and 7 holds" can share a
     mean while meaning very different things. */
  const rt = c.rec_trend || {};
  const VOTES = [
    ['strongBuy',  'Strong buy',  'var(--good)'],
    ['buy',        'Buy',         'color-mix(in srgb, var(--good) 55%, var(--surface))'],
    ['hold',       'Hold',        'var(--warning)'],
    ['sell',       'Sell',        'color-mix(in srgb, var(--critical) 55%, var(--surface))'],
    ['strongSell', 'Strong sell', 'var(--critical)'],
  ];
  const total = VOTES.reduce((t, [k]) => t + (rt[k] || 0), 0);
  let votes;
  if (total) {
    votes = `<div class="votebar">` + VOTES.filter(([k]) => rt[k] > 0)
        .map(([k, , col]) => `<i style="width:${rt[k] / total * 100}%;background:${col}" title="${rt[k]}"></i>`).join('')
      + `</div><div class="votelist">` + VOTES.filter(([k]) => rt[k] > 0)
        .map(([k, label, col]) => `<span><b>${rt[k]}</b> <i style="background:${col}"></i>${label}</span>`).join('')
      + `</div><div class="why">${total} analyst${total === 1 ? '' : 's'} covering`
      + (c.target_mean ? ` · average price target ${usd(c.target_mean)}, `
          + `<span class="${dir(targetUpside(c))}">${sgn(targetUpside(c))}</span> from here` : '')
      + `</div>`;
  } else if (c.analyst_count) {
    votes = `<div class="why">${c.analyst_count | 0} analysts cover this company`
      + (c.analyst_rec ? `, consensus <b>${c.analyst_rec}</b>` : '')
      + (c.target_mean ? `, average target ${usd(c.target_mean)}` : '')
      + `. No published breakdown.</div>`;
  } else {
    votes = `<div class="why">No analysts cover this company.</div>`;
  }

  /* A quote only ever comes from the company's own earnings release as filed
     with the SEC, and is shown with a link to that exact document. Where none
     could be extracted the slot stays empty rather than being filled. */
  const quoteBlock = c.quote_text ? `
    <h4 style="margin-top:16px">What the company says</h4>
    <blockquote class="quote">
      <p>${esc(c.quote_text)}</p>
      <footer>
        <b>${esc(c.quote_speaker)}</b><span>${esc(c.quote_title)}</span>
        <a href="${c.quote_url}" target="_blank" rel="noopener">earnings release, ${esc(c.quote_filed)} \u2197</a>
      </footer>
    </blockquote>` : '';

  const notes = (c.notes ?? []).filter(Boolean);
  const fl = c.filings ?? [];
  const recent = ['10-K', '10-Q'].flatMap(f => fl.filter(x => x.base_form === f).slice(0, 2));

  return `<div class="dgrid">
    <div class="dsec">
      <h4>Compared with the group</h4>
      ${sum}
    </div>

    <div class="dsec">
      <h4>What the analysts say</h4>
      ${votes}
      ${quoteBlock}
      ${notes.length ? `<div class="flags">${notes.map(x => `<span>${esc(x)}</span>`).join('')}</div>` : ''}
    </div>

    <div class="dsec">
      <h4>The numbers</h4>
      <div class="row"><span class="k">Market cap</span><span class="v">${big(c.market_cap)}</span></div>
      <div class="row"><span class="k">Revenue</span><span class="v">${big(c.revenue)}</span></div>
      <div class="row"><span class="k">Revenue growth</span><span class="v">${pct(c.revenue_growth)}</span></div>
      <div class="row"><span class="k">EPS</span><span class="v">${usd(c.forward_eps)}</span></div>
      <div class="row"><span class="k">P/E</span><span class="v">${mult(c.forward_pe)}</span></div>
      <div class="row"><span class="k">Gross margin</span><span class="v">${pct(c.gross_margin, 0)}</span></div>
      <div class="row"><span class="k">Operating margin</span><span class="v ${dir(c.operating_margin)}">${pct(c.operating_margin, 0)}</span></div>
      <div class="row"><span class="k">52-week range</span><span class="v">${usd(c.week52_low)} – ${usd(c.week52_high)}</span></div>
      <div class="row"><span class="k">Sells software to</span><span class="v">${esc(c.sells_to ?? '—')}</span></div>
    </div>

    <div class="dsec">
      <h4>SEC filings</h4>
      ${recent.map(f => `<div class="filing">
          <a href="${f.index_url}" target="_blank" rel="noopener">${esc(f.form)} · ${esc(f.period ?? '')}</a>
          <span class="d">${esc(f.filed)}</span></div>`).join('') || '<div class="why">none on file</div>'}
      ${c.cik ? `<div class="why" style="margin-top:8px">
        <a href="${edgar(c, '10-K')}" target="_blank" rel="noopener">all annual reports</a> ·
        <a href="${edgar(c, '10-Q')}" target="_blank" rel="noopener">all quarterlies</a>
        <br>CIK ${c.cik}</div>` : ''}
    </div>
  </div>`;
}

/* ---------------------------------------------------------------- chrome */
function status() {
  const q = DATA.companies.map(c => c.quoted_at).filter(Boolean).sort().pop();
  const cnt = (r) => DATA.companies.filter(c => c.rating === r).length;
  const s = DATA.snapshots || {};
  // Every build records one dated snapshot, so the model's own calls can be
  // scored later. Until there are a few, this just says when it started.
  const track = s.days
    ? ` · tracking since ${s.first}${s.days > 1 ? ` (${s.days} days)` : ''}`
    : '';
  // A published copy cannot be live, so it states its date rather than
  // implying freshness with "updated 2m ago".
  const when = DATA.static ? `data as of ${(q || '').slice(0, 10)}` : `updated ${ago(q)}`;
  $('status').textContent =
    `${cnt('BUY')} buy · ${cnt('HOLD')} hold · ${cnt('SELL')} sell · ${when}${track}`;
}

/* The live version talks to the local Python server; the published copy is a
   folder of static files with the same data baked into data.json. Trying the
   API first and falling back means one codebase serves both. */
async function load(url = '/api/screener') {
  try {
    let d;
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      d = await r.json();
    } catch (apiErr) {
      const r = await fetch('data.json');
      if (!r.ok) throw apiErr;
      d = await r.json();
    }
    DATA = d.screener ?? d;
    $('error').innerHTML = '';
    if (DATA.static) {
      // No server behind this copy: nothing to refresh, and the CSV has to
      // come from a file written at publish time rather than an endpoint.
      $('refresh').hidden = true;
      const csv = document.querySelector('a[href="/api/export.csv"]');
      if (csv) csv.setAttribute('href', 'screener.csv');
    }
    render(); status();
  } catch (e) {
    $('error').innerHTML = `<div class="err">Could not load the data.
      If you are running this locally, start the server:
      <code>python -m saasscreener.server</code></div>`;
  }
}

async function refresh() {
  const b = $('refresh');
  b.disabled = true; b.textContent = 'refreshing…';
  await load('/api/refresh');
  b.disabled = false; b.textContent = 'Refresh';
}

$('refresh').addEventListener('click', refresh);
setInterval(() => { if (!document.hidden && DATA && !DATA.static) refresh(); }, 90000);
setInterval(() => { if (DATA) status(); }, 30000);
load();
