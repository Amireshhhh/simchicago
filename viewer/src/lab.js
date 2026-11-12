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

function ivRanking(I) {
  const ranked = I.ranking.filter(r => Number.isFinite(r.value));
  const W = 400, rowH = 30, padL = 170, padR = 50;
  const byGroup = {};
  for (const r of ranked) (byGroup[r.ranked_by] ||= []).push(r);
  let s = '';
  for (const [g, rows] of Object.entries(byGroup)) {
    const H = rows.length * rowH + 26;
    const hi = Math.max(...rows.map(r => Number.isFinite(r.ci_high) ? r.ci_high : r.value), 1e-9);
    const lo = Math.min(0, ...rows.map(r => Number.isFinite(r.ci_low) ? r.ci_low : r.value));
    const x = v => padL + (v - lo) / (hi - lo || 1) * (W - padL - padR);
    s += `<h3>${esc(g)}</h3><svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(g)} with 95% intervals">`;
    s += `<line x1="${x(0)}" x2="${x(0)}" y1="4" y2="${H - 18}" stroke="rgba(140,190,255,.25)"/>`;
    rows.forEach((r, i) => {
      const y = 14 + i * rowH, name = r.intervention.length > 30 ? r.intervention.slice(0, 29) + '…' : r.intervention;
      s += `<text x="0" y="${y + 4}">${esc(name)}</text><rect x="${Math.min(x(0), x(r.value))}" y="${y - 7}" width="${Math.abs(x(r.value) - x(0))}" height="14" rx="3" fill="#5fd4ff" opacity=".55"/>`;
      if (Number.isFinite(r.ci_low)) s += `<line x1="${x(r.ci_low)}" x2="${x(r.ci_high)}" y1="${y}" y2="${y}" stroke="#fff" stroke-width="1.5"/>`;
      s += `<text class="val" x="${W - padR + 6}" y="${y + 4}">${fmt(r.value)}</text>`;
    });
    s += '</svg>';
  }
  const pct = v => Number.isFinite(v) ? (v * 100).toFixed(0) + '%' : '–';
  s += `<h3>All interventions</h3><table class="effects"><thead><tr><th>Intervention</th><th style="text-align:right">Δ veh-h/day</th><th style="text-align:right">Δ transit trips/day [95% CI]</th><th style="text-align:right">Δ jobs reachable (low-income / other areas)</th><th style="text-align:right">Time savings to low-income areas</th></tr></thead><tbody>
    ${I.ranking.map(r => `<tr><td>${esc(r.intervention)}<div class="fine">${esc(r.ranked_by)}</div></td><td class="num">${fmt(r.vehicle_hours_per_weekday)}</td>
      <td class="num">${r.transit_trips === null || r.transit_trips === undefined ? '–' : `${fmt(r.transit_trips)} [${fmt(r.transit_trips_ci[0])}, ${fmt(r.transit_trips_ci[1])}]`}</td>
      <td class="num">${fmt(r.access_jobs)} (${fmt(r.access_gain_low)} / ${fmt(r.access_gain_other)})</td><td class="num">${pct(r.low_income_share_of_savings)}</td></tr>`).join('')}
    </tbody></table>
    <p class="fine">Behaviour (trips, time savings) is simulated on ${I.replicates} synthetic populations (paired 95% t-intervals); vehicle-hours come from the GTFS schedule; jobs reachable within 45 min by transit (60 min at night). Low-income areas: lowest median income, ${pct(I.low_income_population_share)} of residents. Bus and train vehicle-hours are not equally costly; fare and service changes are ranked separately. Effect sizes for bus priority and reliability are assumptions.</p>
    <p class="fine"><code>python -m simchi.interventions --replicates 10</code> · brief: docs/BRIEF.md</p>`;
  return s;
}

export function renderLab(el, D) {
  const exps = D.experiments || [];
  const I = D.interventions;
  if (I && I.ranking) {
    // the intervention ranking is its own tab, shown first
    const host = el;
    let showIv = true;
    const drawTabs = () => {
      if (showIv) {
        host.innerHTML = `<h2>Experiment Lab</h2><div class="lab-tabs"><button class="ghost small on" data-iv="1">intervention ranking</button>${exps.length ? '<button class="ghost small" data-iv="0">scenario experiments</button>' : ''}</div>${ivRanking(I)}`;
        host.querySelectorAll('[data-iv]').forEach(b => b.onclick = () => { showIv = b.dataset.iv === '1'; drawTabs(); });
      } else {
        renderExperiments(host, exps);
        const tabs = host.querySelector('.lab-tabs');
        if (tabs) {
          const b = document.createElement('button'); b.className = 'ghost small'; b.textContent = 'intervention ranking';
          b.onclick = () => { showIv = true; drawTabs(); }; tabs.prepend(b);
        }
      }
    };
    drawTabs();
    return;
  }
  renderExperiments(el, exps);
}

function renderExperiments(el, exps) {
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
