// Experiment Lab: scenario means with 95% intervals and paired effects vs the baseline.
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = v => {
  if (v === null || v === undefined || !Number.isFinite(v)) return '–';
  const a = Math.abs(v);
  if (a >= 1e5) return (v / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(1) + 'k';
  if (a >= 10) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  return v.toFixed(4);
};
const DEFAULT_METRIC = { incident_response: 'activities_cancelled', safety_sensitivity: 'activities_cancelled', remote_work: 'pkm_car', transit_disruption: 'pkm_transit' };

function chart(rows, baseline) {
  const W = 400, rowH = 30, padL = 150, padR = 54, H = rows.length * rowH + 30;
  const lo = Math.min(0, ...rows.map(r => Number.isFinite(r.ci_low) ? r.ci_low : r.mean));
  const hi = Math.max(...rows.map(r => Number.isFinite(r.ci_high) ? r.ci_high : r.mean), 1e-12);
  const x = v => padL + (v - lo) / (hi - lo || 1) * (W - padL - padR);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Scenario means with 95% intervals">`;
  s += `<line x1="${x(0)}" x2="${x(0)}" y1="4" y2="${H - 22}" stroke="rgba(140,190,255,.25)"/>`;
  rows.forEach((r, i) => {
    const y = 14 + i * rowH, isBase = r.scenario === baseline;
    const col = isBase ? '#93a7c1' : '#5fd4ff';
    s += `<text x="0" y="${y + 4}">${esc(r.scenario.length > 24 ? r.scenario.slice(0, 23) + '…' : r.scenario)}</text>`;
    s += `<rect x="${Math.min(x(0), x(r.mean))}" y="${y - 7}" width="${Math.abs(x(r.mean) - x(0))}" height="14" rx="3" fill="${col}" opacity="${isBase ? 0.35 : 0.55}"/>`;
    if (Number.isFinite(r.ci_low)) s += `<line x1="${x(r.ci_low)}" x2="${x(r.ci_high)}" y1="${y}" y2="${y}" stroke="#fff" stroke-width="1.5"/><line x1="${x(r.ci_low)}" x2="${x(r.ci_low)}" y1="${y - 5}" y2="${y + 5}" stroke="#fff"/><line x1="${x(r.ci_high)}" x2="${x(r.ci_high)}" y1="${y - 5}" y2="${y + 5}" stroke="#fff"/>`;
    s += `<text class="val" x="${W - padR + 6}" y="${y + 4}">${fmt(r.mean)}</text>`;
  });
  s += `<text x="${padL}" y="${H - 6}">${fmt(lo)}</text><text x="${W - padR}" y="${H - 6}" text-anchor="end">${fmt(hi)}</text></svg>`;
  return s;
}

export function renderLab(el, D) {
  const exps = D.experiments || [];
  if (!exps.length) {
    el.innerHTML = `<h2>Experiment Lab</h2><p>No experiments in this export. Run</p><p><code>python -m simchi.cli demo</code></p>
      <p>or <code>python -m simchi.cli experiment configs/experiments/remote_work.toml</code>.</p>`;
    return;
  }
  let cur = 0, metric = DEFAULT_METRIC[exps[0].name] || 'activities_cancelled';
  function draw() {
    const e = exps[cur];
    const metrics = Object.keys(e.metrics);
    if (!metrics.includes(metric)) metric = DEFAULT_METRIC[e.name] || metrics[0];
    const rows = e.summary.filter(r => r.metric === metric);
    const eff = e.effects.filter(r => r.metric === metric);
    const hyp = /safety|incident|cancel/.test(e.name + metric);
    el.innerHTML = `<h2>Experiment Lab</h2>
      <p class="fine">Every scenario runs on the same synthetic city with the same seeds, so differences are paired (common random numbers). Intervals are 95% t-intervals over ${e.seeds.length} replicates.</p>
      <div class="lab-tabs">${exps.map((x, i) => `<button class="ghost small ${i === cur ? 'on' : ''}" data-exp="${i}">${esc(x.name.replace(/_/g, ' '))}</button>`).join('')}</div>
      <p>${esc(e.description)}</p>
      <div class="lab-controls"><label class="select">Metric<select id="labMetric">${metrics.map(m => `<option value="${m}" ${m === metric ? 'selected' : ''}>${esc(e.metrics[m])}</option>`).join('')}</select></label></div>
      ${chart(rows, e.baseline)}
      <h3>Effect vs “${esc(e.baseline)}”</h3>
      <table class="effects"><thead><tr><th>Scenario</th><th style="text-align:right">Δ</th><th style="text-align:right">95% CI</th><th style="text-align:right">rel.</th></tr></thead><tbody>
      ${eff.map(r => `<tr><td>${esc(r.scenario)}</td><td class="num ${r.significant ? 'sig' : 'nsig'}">${r.diff >= 0 ? '+' : ''}${fmt(r.diff)}</td>
        <td class="num">[${fmt(r.ci_low)}, ${fmt(r.ci_high)}]</td><td class="num">${Number.isFinite(r.rel_diff) ? (r.rel_diff * 100).toFixed(1) + '%' : '–'}</td></tr>`).join('')}
      </tbody></table>
      <p class="fine">Bold cyan: the 95% interval excludes zero.</p>
      ${hyp ? '<div class="callout">The safety response is a hypothesised mechanism with no data behind it. These results show what the model implies under that hypothesis, not measured behaviour.</div>' : ''}
      <h3>Run it yourself</h3>
      <p class="fine"><code>python -m simchi.cli experiment configs/experiments/${esc(e.name)}.toml --replicates 30</code></p>`;
    el.querySelectorAll('[data-exp]').forEach(b => b.onclick = () => { cur = +b.dataset.exp; metric = DEFAULT_METRIC[exps[cur].name] || metric; draw(); });
    el.querySelector('#labMetric').onchange = ev => { metric = ev.target.value; draw(); };
  }
  draw();
}
