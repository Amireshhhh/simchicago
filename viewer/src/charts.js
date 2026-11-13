// Small SVG chart kit for the Insights page: line (crosshair tooltip), horizontal bars, interval
// dots, grouped bars. Colours come from CSS tokens (--s1..--s3 categorical, validated on the
// panel surface); text stays in text tokens; every chart has a hover layer and an accessible table.
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const fmt = (v, d) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return '–';
  const a = Math.abs(v);
  if (d !== undefined) return v.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 1 : 2) + 'M';
  if (a >= 1e4) return Math.round(v / 1e3) + 'k';
  if (a >= 1e3) return (v / 1e3).toFixed(1) + 'k';
  if (a >= 10 || Number.isInteger(v)) return v.toFixed(0);
  return v.toFixed(2);
};
const niceTicks = (lo, hi, n = 4) => {
  const span = hi - lo || 1, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0);
  const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
};

let tipEl;
function tip() {
  if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'ctip'; tipEl.setAttribute('role', 'tooltip'); document.body.appendChild(tipEl); }
  return tipEl;
}
function showTip(html, x, y) {
  const t = tip(); t.innerHTML = html; t.style.opacity = 1;
  const w = t.offsetWidth, h = t.offsetHeight;
  t.style.left = `${Math.min(innerWidth - w - 8, x + 14)}px`; t.style.top = `${Math.max(8, y - h - 12)}px`;
}
const hideTip = () => { if (tipEl) tipEl.style.opacity = 0; };

/** Multi-series line chart with a crosshair tooltip. series: [{name, color, values}], x: labels. */
export function lineChart(el, { x, series, yFmt = fmt, height = 240, label }) {
  const W = el.clientWidth || 640, H = height, pl = 52, pr = 14, pt = 12, pb = 26;
  const all = series.flatMap(s => s.values).filter(Number.isFinite);
  const lo = 0, hi = Math.max(...all) * 1.08;
  const X = i => pl + i / (x.length - 1) * (W - pl - pr), Y = v => pt + (1 - (v - lo) / (hi - lo)) * (H - pt - pb);
  const ticks = niceTicks(lo, hi);
  const years = x.map((d, i) => [d.slice(0, 4), i]).filter(([y], i, a) => i === 0 || y !== a[i - 1][0]);
  let s = `<svg viewBox="0 0 ${W} ${H}" class="cv" role="img" aria-label="${esc(label)}">`;
  for (const t of ticks) s += `<line class="grid" x1="${pl}" x2="${W - pr}" y1="${Y(t)}" y2="${Y(t)}"/><text class="ax" x="${pl - 8}" y="${Y(t) + 4}" text-anchor="end">${yFmt(t)}</text>`;
  for (const [yr, i] of years) s += `<line class="tick" x1="${X(i)}" x2="${X(i)}" y1="${H - pb}" y2="${H - pb + 4}"/><text class="ax" x="${X(i) + 3}" y="${H - 8}">${yr}</text>`;
  for (const sr of series) {
    const d = sr.values.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('');
    s += `<path d="${d}" fill="none" stroke="${sr.color}" stroke-width="2" stroke-linejoin="round" class="draw"/>`;
    const li = sr.values.length - 1;
    s += `<text class="dl" x="${X(li) - 4}" y="${Y(sr.values[li]) - 8}" text-anchor="end">${esc(sr.name)}</text>`;
  }
  s += `<line class="xh" x1="0" x2="0" y1="${pt}" y2="${H - pb}" opacity="0"/>`;
  s += series.map((sr, k) => `<circle class="xd" data-k="${k}" r="4" fill="${sr.color}" stroke="var(--panel-solid)" stroke-width="2" opacity="0"/>`).join('');
  s += `<rect class="hit" x="${pl}" y="${pt}" width="${W - pl - pr}" height="${H - pt - pb}" fill="transparent"/></svg>`;
  el.innerHTML = s;
  const svg = el.querySelector('svg'), xh = svg.querySelector('.xh'), dots = svg.querySelectorAll('.xd');
  svg.querySelector('.hit').addEventListener('pointermove', e => {
    const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(x.length - 1, Math.round((px - pl) / (W - pl - pr) * (x.length - 1))));
    xh.setAttribute('x1', X(i)); xh.setAttribute('x2', X(i)); xh.setAttribute('opacity', 1);
    dots.forEach(dn => { const v = series[+dn.dataset.k].values[i]; dn.setAttribute('cx', X(i)); dn.setAttribute('cy', Y(v)); dn.setAttribute('opacity', 1); });
    showTip(`<b>Week of ${esc(x[i])}</b>${series.map(sr => `<div><i style="background:${sr.color}"></i>${esc(sr.name)} <b>${yFmt(sr.values[i])}</b></div>`).join('')}`, e.clientX, e.clientY);
  });
  svg.querySelector('.hit').addEventListener('pointerleave', () => { hideTip(); xh.setAttribute('opacity', 0); dots.forEach(dn => dn.setAttribute('opacity', 0)); });
}

/** Horizontal bar list: rows [{label, value, sub?}]. */
export function barList(el, { rows, color = 'var(--s1)', valueFmt = fmt, unit = '' }) {
  const hi = Math.max(...rows.map(r => r.value)) || 1;
  el.innerHTML = `<div class="bars">${rows.map((r, i) => `<div class="bar" data-i="${i}" tabindex="0">
      <span class="bl">${esc(r.label)}${r.sub ? `<small>${esc(r.sub)}</small>` : ''}</span>
      <span class="bt"><i style="width:${(r.value / hi * 100).toFixed(1)}%;background:${color};animation-delay:${i * 30}ms"></i></span>
      <span class="bv">${valueFmt(r.value)}${unit}</span></div>`).join('')}</div>`;
  el.querySelectorAll('.bar').forEach(b => {
    const r = rows[+b.dataset.i];
    b.addEventListener('pointermove', e => showTip(`<b>${esc(r.label)}</b><div>${valueFmt(r.value)}${unit}</div>${r.tip ? `<div class="fine">${esc(r.tip)}</div>` : ''}`, e.clientX, e.clientY));
    b.addEventListener('pointerleave', hideTip);
  });
}

/** Point estimates with 95% intervals: rows [{label, mean, lo, hi, tip}]. */
export function intervalChart(el, { rows, valueFmt = fmt, color = 'var(--s1)', zero = true }) {
  const W = el.clientWidth || 560, rh = 34, pl = Math.min(260, W * 0.42), pr = 64, H = rows.length * rh + 24;
  const lo = Math.min(zero ? 0 : Infinity, ...rows.map(r => r.lo ?? r.mean)), hi = Math.max(...rows.map(r => r.hi ?? r.mean)) * 1.04;
  const X = v => pl + (v - lo) / (hi - lo || 1) * (W - pl - pr);
  let s = `<svg viewBox="0 0 ${W} ${H}" class="cv" role="img">`;
  for (const t of niceTicks(lo, hi, 3)) s += `<line class="grid" x1="${X(t)}" x2="${X(t)}" y1="4" y2="${H - 20}"/><text class="ax" x="${X(t)}" y="${H - 6}" text-anchor="middle">${valueFmt(t)}</text>`;
  rows.forEach((r, i) => {
    const y = 16 + i * rh;
    s += `<g class="row" data-i="${i}"><rect x="0" y="${y - rh / 2 + 2}" width="${W}" height="${rh - 4}" fill="transparent"/>`;
    s += `<text class="clbl" x="0" y="${y + 4}">${esc(r.label)}</text>`;
    if (Number.isFinite(r.lo)) s += `<line x1="${X(r.lo)}" x2="${X(r.hi)}" y1="${y}" y2="${y}" stroke="${color}" stroke-width="2" stroke-linecap="round" opacity=".55"/>`;
    s += `<circle cx="${X(r.mean)}" cy="${y}" r="5.5" fill="${color}" stroke="var(--panel-solid)" stroke-width="2"/>`;
    s += `<text class="val" x="${W - pr + 8}" y="${y + 4}">${valueFmt(r.mean)}</text></g>`;
  });
  el.innerHTML = s + '</svg>';
  el.querySelectorAll('.row').forEach(g => {
    const r = rows[+g.dataset.i];
    g.addEventListener('pointermove', e => showTip(`<b>${esc(r.label)}</b><div>${valueFmt(r.mean)}${Number.isFinite(r.lo) ? ` <span class="fine">95% [${valueFmt(r.lo)}, ${valueFmt(r.hi)}]</span>` : ''}</div>${r.tip ? `<div class="fine">${esc(r.tip)}</div>` : ''}`, e.clientX, e.clientY));
    g.addEventListener('pointerleave', hideTip);
  });
}

/** Grouped horizontal bars: groups [{label, items:[{name, value, color, best?}]}]; lower is better when `lowerBetter`. */
export function groupedBars(el, { groups, valueFmt = v => v.toFixed(3), lowerBetter = true }) {
  const hi = Math.max(...groups.flatMap(g => g.items.map(i => i.value))) || 1;
  el.innerHTML = groups.map(g => `<div class="gb"><div class="gbh">${esc(g.label)}</div>${g.items.map(it => `
    <div class="bar ${it.best ? 'best' : ''}" data-tip="${esc(`${it.name}: ${valueFmt(it.value)}${lowerBetter ? ' (lower is better)' : ''}`)}">
      <span class="bl">${esc(it.name)}</span><span class="bt"><i style="width:${(it.value / hi * 100).toFixed(1)}%;background:${it.color}"></i></span>
      <span class="bv">${valueFmt(it.value)}</span></div>`).join('')}</div>`).join('');
  el.querySelectorAll('.bar').forEach(b => {
    b.addEventListener('pointermove', e => showTip(esc(b.dataset.tip), e.clientX, e.clientY));
    b.addEventListener('pointerleave', hideTip);
  });
}

/** Count-up animation for hero numbers. */
export function countUp(el, to, { dur = 1200, format = fmt } = {}) {
  const t0 = performance.now();
  const step = now => { const f = Math.min(1, (now - t0) / dur), e = 1 - (1 - f) ** 3; el.textContent = format(to * e); if (f < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
