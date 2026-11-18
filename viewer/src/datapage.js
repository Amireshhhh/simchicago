// Data: the City of Chicago data portal catalog with measured freshness, searchable, with
// copy-paste access snippets (Python client, SODA URL). Read from data/portal/catalog.json.
import { barList, countUp, fmt } from './charts.js';

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ST = { fresh: ['Fresh', 'st good', 'Updated within its declared period (+7 days), or within 30 days if no period is declared'],
  late: ['Late', 'st warn', 'Past its declared period, within max(2 periods, 30 days)'],
  overdue: ['Overdue', 'st bad', 'Older than max(2 x its declared period, 30 days)'],
  static: ['No schedule', 'st info', 'No update frequency declared, older than 30 days (many are historical by design)'],
  unknown: ['Unknown', 'st info', 'No update timestamp'] };
const ageTxt = d => d === null || d === undefined ? '–' : d < 1 ? 'today' : d < 60 ? `${Math.round(d)} d` : d < 730 ? `${Math.round(d / 30.4)} mo` : `${(d / 365.25).toFixed(1)} y`;

export function renderData(root, C) {
  if (!C) { root.innerHTML = '<div class="page-inner"><h1>Data</h1><p>No catalog export found.</p></div>'; return; }
  const S = C.summary, D = C.datasets;
  const cats = [...new Set(D.map(d => d.category || 'Uncategorised'))].sort();
  root.innerHTML = `<div class="page-inner">
    <header class="page-head"><p class="eyebrow">Data</p><h1>Chicago's open data, with an honest freshness check</h1>
      <p class="lede">All ${S.datasets} datasets on the City of Chicago data portal, checked against the update frequency each one declares. Catalog read ${esc(C.fetched_utc.slice(0, 10))} from the portal's catalog API.</p></header>
    <div class="kpis">
      <div class="kpi"><span class="k">Datasets</span><b data-count="${S.datasets}">0</b><span class="d">${S.updated_within_7d} changed in the last 7 days</span></div>
      <div class="kpi"><span class="k">Median time since last data change</span><b>${(S.median_age_days / 365.25).toFixed(1)}<small> y</small></b><span class="d">${S.older_than_1y} older than 1 year, ${S.older_than_5y} older than 5</span></div>
      <div class="kpi"><span class="k">Behind their own declared schedule</span><b data-count="${S.status.overdue || 0}">0</b><span class="d">of ${S.with_declared_period} that declare one</span></div>
      <div class="kpi"><span class="k">"Updated daily" but overdue</span><b data-count="${S.declared_daily_overdue}">0</b><span class="d">of ${S.declared_daily} that promise daily updates</span></div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Freshness by category</h3><p class="sub">Share of each category's datasets that are fresh.</p><div id="chCatFresh"></div></div>
      <div class="card"><h3>Most viewed datasets that are overdue</h3><p class="sub">Page views last month; these are what people rely on.</p><div id="chOverdue"></div></div>
    </div>
    <section class="sec"><h2>Find a dataset</h2>
      <div class="dfilters">
        <input id="dq" type="search" placeholder="Search names, descriptions, column names…" aria-label="Search datasets">
        <select id="dcat" aria-label="Category"><option value="">All categories</option>${cats.map(c => `<option>${esc(c)}</option>`).join('')}</select>
        <select id="dst" aria-label="Freshness"><option value="">Any freshness</option>${Object.entries(ST).slice(0, 4).map(([k, v]) => `<option value="${k}">${v[0]}</option>`).join('')}</select>
        <select id="dsort" aria-label="Sort"><option value="views">Most viewed</option><option value="fresh">Most recently changed</option><option value="stale">Longest unchanged</option><option value="name">Name</option></select>
      </div>
      <p class="fine" id="dcount"></p>
      <div id="dlist" class="dlist"></div>
    </section>
    <section class="sec"><h2>Use it from Python</h2>
      <div class="card"><pre class="code">from simchi.portal.client import Portal
p = Portal()                          # optional: export SODA_APP_TOKEN=... for higher rate limits
p.search("bus")                       # datasets by name, description or column
p.info("ijzp-q8t2")                   # columns, last change, declared frequency, freshness status
df = p.query("ijzp-q8t2", select="date, primary_type, community_area",
             where="date >= '2026-10-01'")   # every matching row, paged and typed, cached on disk</pre>
      <p class="note">Pages with a stable order so no row is skipped or repeated, converts each column to its declared type, retries with backoff, and caches each query until the City changes the data. Freshness rules: ${Object.values(ST).slice(0, 4).map(v => `<b>${v[0]}</b>: ${esc(v[2])}`).join('; ')}.</p></div>
    </section>
    <footer class="page-foot">Source: City of Chicago data portal catalog API. "Overdue" measures time since the portal's last data change against the frequency the City declares; it does not say why (some datasets are seasonal, e.g. beach data, or historical).</footer></div>`;

  root.querySelectorAll('[data-count]').forEach(el => countUp(el, +el.dataset.count, { format: v => Math.round(v).toLocaleString('en-US') }));
  const byCat = {};
  for (const d of D) { const c = d.category || 'Uncategorised'; (byCat[c] ||= { n: 0, f: 0 }).n++; if (d.status === 'fresh') byCat[c].f++; }
  barList(root.querySelector('#chCatFresh'), { rows: Object.entries(byCat).filter(([, v]) => v.n >= 5).map(([k, v]) => ({ label: `${k} (${v.n})`, value: v.f / v.n, tip: `${v.f} of ${v.n} fresh` })).sort((a, b) => b.value - a.value),
    color: 'var(--s3)', valueFmt: v => (v * 100).toFixed(0) + '%' });
  barList(root.querySelector('#chOverdue'), { rows: D.filter(d => d.status === 'overdue').slice(0, 10).map(d => ({ label: d.name, value: d.views_month || 0, tip: `${d.declared} · last change ${ageTxt(d.age_days)} ago` })),
    color: 'var(--s2)', valueFmt: v => fmt(v) });

  const list = root.querySelector('#dlist');
  const draw = () => {
    const q = root.querySelector('#dq').value.trim().toLowerCase(), cat = root.querySelector('#dcat').value, st = root.querySelector('#dst').value, so = root.querySelector('#dsort').value;
    let rows = D.filter(d => (!cat || (d.category || 'Uncategorised') === cat) && (!st || d.status === st) &&
      (!q || d.name.toLowerCase().includes(q) || (d.description || '').toLowerCase().includes(q) || d.columns.some(c => c.name.toLowerCase().includes(q))));
    const key = { views: d => -(d.views_month || 0), fresh: d => d.age_days ?? 1e9, stale: d => -(d.age_days ?? -1), name: d => d.name }[so];
    rows = rows.slice().sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
    root.querySelector('#dcount').textContent = `${rows.length} datasets${rows.length > 80 ? ', showing the first 80' : ''}`;
    list.innerHTML = rows.slice(0, 80).map(d => `<details class="ditem"><summary><span class="${ST[d.status][1]}" title="${esc(ST[d.status][2])}"><b>${d.status === 'fresh' ? '✓' : d.status === 'overdue' ? '!' : d.status === 'late' ? '~' : 'i'}</b>${ST[d.status][0]}</span>
        <span class="dn">${esc(d.name)}</span><span class="dm">${esc(d.category || '')} · changed ${ageTxt(d.age_days)} ago${d.declared ? ` · declares “${esc(d.declared.slice(0, 40))}”` : ''} · ${fmt(d.views_month || 0)} views/mo</span></summary>
        <div class="dbody"><p>${esc(d.description)}</p>
        <p class="fine">${d.columns.length} columns: ${d.columns.slice(0, 18).map(c => `<code>${esc(c.field)}</code> ${esc(c.type)}`).join(', ')}${d.columns.length > 18 ? ' …' : ''}</p>
        <pre class="code">df = Portal().query("${esc(d.id)}", limit=10_000)</pre>
        <p class="fine">API: <code>https://data.cityofchicago.org/resource/${esc(d.id)}.json?$limit=100</code> · <a href="${esc(d.link)}" target="_blank" rel="noopener">portal page</a> · owner: ${esc(d.owner || '–')}</p></div></details>`).join('');
  };
  ['#dq', '#dcat', '#dst', '#dsort'].forEach(s => root.querySelector(s).addEventListener('input', draw));
  draw();
}
