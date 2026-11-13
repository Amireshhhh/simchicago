// Insights: real data and validated results, as a scrollable dashboard (2D, no simulation needed).
import { lineChart, barList, intervalChart, groupedBars, countUp, fmt } from './charts.js';

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (v, d = 1) => Number.isFinite(v) ? `${(v * 100).toFixed(d)}%` : '–';
const sgn = (v, d = 1) => Number.isFinite(v) ? `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(d)}%` : '–';
export const PROV = {
  observed: ['Observed', 'Measured data: CTA ridership, live positions, census'],
  scheduled: ['Scheduled', "CTA's published GTFS timetable"],
  simulated: ['Simulated', 'Output of the SimChicago model'],
  hypothesis: ['Assumed', 'An assumption, not estimated from data'],
};
export const chip = k => `<span class="prov ${k}" title="${esc(PROV[k][1])}">${PROV[k][0]}</span>`;
const status = p => p === null || p === undefined ? '<span class="st info"><b>i</b>Reported</span>'
  : p ? '<span class="st good"><b>✓</b>Pass</span>' : '<span class="st bad"><b>✕</b>Fail</span>';

const shortIv = n => n.startsWith('Frequent network') ? 'Top-10 bus routes, headways ×0.75' : n.startsWith('All buses') ? 'All buses, headways ×0.8' : n.startsWith("All 'L'") ? "All 'L' lines, headways ×0.8" : n;
const SECTIONS = [['ridership', 'Ridership'], ['validation', 'Model vs reality'], ['design', 'Service design'], ['interventions', 'Interventions'], ['operations', 'Operations'], ['reliability', 'Reliability']];

export function renderInsights(root, I) {
  if (!I) { root.innerHTML = '<div class="page-inner"><h1>Insights</h1><p>No insights export found (data/insights.json). Run <code>python -m simchi.cli demo</code>.</p></div>'; return; }
  const R = I.ridership, V = I.validation || [], M = I.models || {}, IV = I.interventions, O = I.ops || {}, SD = I.service_design;
  const nPass = V.filter(c => c.pass === true).length, nFail = V.filter(c => c.pass === false).length;
  const rv = M.ridership_validation || {};
  root.innerHTML = `<div class="page-inner">
  <header class="page-head">
    <div><p class="eyebrow">Insights</p><h1>What the data say, and how well the model holds up</h1>
    <p class="lede">Real CTA ridership and schedules, the model's held-out validation, and the intervention ranking. Every number carries its source: ${chip('observed')} ${chip('scheduled')} ${chip('simulated')} ${chip('hypothesis')}</p></div>
  </header>
  <nav class="subnav" aria-label="Insights sections">${SECTIONS.map(([id, l]) => `<a href="#insights/${id}" data-sec="${id}">${l}</a>`).join('')}</nav>

  <div class="kpis">
    <div class="kpi"><span class="k">Bus rides, last 12 months ${chip('observed')}</span><b data-count="${R.bus_last12_total}">0</b><span class="d ${R.bus_yoy >= 0 ? 'up' : 'down'}">${sgn(R.bus_yoy)} vs the year before</span></div>
    <div class="kpi"><span class="k">'L' entries, last 12 months ${chip('observed')}</span><b data-count="${R.rail_last12_total}">0</b><span class="d ${R.rail_yoy >= 0 ? 'up' : 'down'}">${sgn(R.rail_yoy)} vs the year before</span></div>
    <div class="kpi"><span class="k">Scheduled weekday trips ${chip('scheduled')}</span><b data-count="${I.network.counts.weekday_trips}">0</b><span class="d">${I.network.counts.routes} routes · ${fmt(I.network.counts.stops)} stops</span></div>
    <div class="kpi"><span class="k">Validation checks</span><b>${nPass}<small>/${V.length}</small></b><span class="d">${nFail} fail, reported as failures</span></div>
  </div>

  <section id="sec-ridership" class="sec">
    <h2>Ridership ${chip('observed')}</h2>
    <p class="sub">Average daily rides per week, ${esc(R.period[0])} to ${esc(R.period[1])}. Source: CTA ridership on the City of Chicago data portal.</p>
    <div class="card wide"><div class="legend-row"><span><i style="background:var(--s1)"></i>Bus boardings</span><span><i style="background:var(--s2)"></i>'L' station entries</span></div><div id="chRidership"></div></div>
    <div class="grid2">
      <div class="card"><h3>Busiest bus routes</h3><p class="sub">Average weekday boardings, last 12 months</p><div id="chTopBus"></div></div>
      <div class="card"><h3>Busiest 'L' stations</h3><p class="sub">Average weekday entries, last 12 months</p><div id="chTopRail"></div></div>
    </div>
  </section>

  <section id="sec-validation" class="sec">
    <h2>Model vs reality</h2>
    <p class="sub">Each check compares the model with a simple baseline on data it was not fitted to. Pass criteria were fixed (and for the newest checks, committed) before the results were seen.</p>
    <div class="card wide"><h3>Ridership on held-out routes and stations ${chip('observed')} ${chip('simulated')}</h3>
      <p class="sub">Trained on 2024, tested on 2025 to Aug 2026 on routes and stations left out of the fit. Mean absolute log error (lower is better; 0.45 ≈ a typical factor of 1.57).</p>
      <div class="grid2"><div id="chRvBus"></div><div id="chRvRail"></div></div>
      <p class="note">Simulation + schedule beats the schedule alone on bus routes (pass) but not on 'L' stations (fail). Each unit's own past ridership predicts next year far better (${rv.bus ? rv.bus.persistence.toFixed(3) : '–'} bus, ${rv.rail ? rv.rail.persistence.toFixed(3) : '–'} 'L'): the model is for routes, places and scenarios without history.</p></div>
    <div class="scorecard">${V.map(c => `<div class="sc ${c.pass === false ? 'fail' : ''}"><div class="sch">${status(c.pass)}<span class="grp">${esc(c.group)}</span></div><h4>${esc(c.label)}</h4><p>${esc(c.summary)}</p></div>`).join('')}</div>
    <div class="grid2">
      <div class="card"><h3>Riders respond to service, not to a dial ${chip('simulated')}</h3><p class="sub">Change in simulated transit trips when CTA service changes; no manual mode shift. 95% intervals over 10 replicates.</p><div id="chDisruption"></div></div>
      <div class="card"><h3>Sensitivities of the fitted mode choice ${chip('simulated')}</h3><div class="tiles">
        <div class="tile"><b>${M.elasticity ? M.elasticity['in-vehicle time +10%'].toFixed(2) : '–'}</b><span>in-vehicle time elasticity of transit share</span></div>
        <div class="tile"><b>${M.elasticity ? M.elasticity['wait +10%'].toFixed(2) : '–'}</b><span>wait-time elasticity</span></div>
        <div class="tile"><b>${M.elasticity ? M.elasticity.fare_by_vot['VOT $15/h'].toFixed(2) : '–'}</b><span>fare elasticity ${chip('hypothesis')} at $15/h value of time</span></div>
        <div class="tile"><b>${M.elasticity ? pct(M.elasticity.transit_share_model) : '–'}</b><span>model transit commute share (ACS ${M.elasticity ? pct(M.elasticity.transit_share_acs) : '–'})</span></div></div>
        <p class="note">Estimated from differences between community areas, so the time sensitivity is not a measured causal effect.</p></div>
    </div>
  </section>

  ${SD ? `<section id="sec-design" class="sec">
    <h2>Service design: same budget, better allocation ${chip('observed')} ${chip('scheduled')} ${chip('simulated')}</h2>
    <p class="sub">Two tested ways to get more riders per bus-hour or the same riders for fewer bus-hours. Each design is simulated on ${SD.replicates} synthetic populations against today's schedule (95% intervals); costs are scheduled vehicle-hours from GTFS; demand is observed CTA ridership.</p>
    <div class="grid2">
      <div class="card"><h3>Re-allocate bus frequency (square-root rule)</h3>
        <p class="sub">Riders wait about half a headway, so total waiting is Σ Q/(2f) for ridership Q and frequency f, while cost is Σ C·f for round-trip time C. Minimising waiting for a fixed budget gives <b>f ∝ √(Q/C)</b> (bounded to 0.6×-1.6× today). Today's busiest routes already run very often, so the rule moves hours to infrequent routes, where each extra bus cuts more waiting.</p>
        <div id="chSdTrips"></div><p class="note">Change in simulated transit trips per weekday; vehicle-hours change as shown in the table.</p></div>
      <div class="card"><h3>Bus stop balancing on the ten busiest routes ${chip('hypothesis')}</h3>
        <p class="sub">Keep terminals, transfer points and stops at least 400 m apart; buses skip the rest and save an assumed 20 s per skipped stop. Riders walk to the next stop; the network model routes them.</p>
        <div id="tbSdStops" class="tablewrap"></div></div>
    </div>
    <div class="card wide" style="margin-top:14px"><h3>Results</h3><div id="tbSd" class="tablewrap"></div></div>
    <div class="grid2">
      <div class="card"><h3>Routes that gain service</h3><p class="sub">Square-root allocation at today's budget: proposed weekday trips ÷ today's.</p><div id="chSdUp"></div></div>
      <div class="card"><h3>Routes that give service back</h3><p class="sub">Already frequent for their ridership by this rule; the hours move to the routes on the left.</p><div id="chSdDown"></div></div>
    </div>
    <p class="note">These lists are what the formula implies, not an operational recommendation: it has no crowding limit (cutting route 66 by 30% would crowd it) and assumes riders wait half a headway even on hourly routes, where they time their arrival. The simulation finds no measurable ridership gain from it at today's budget; cutting hours loses riders. Stop balancing is the design that saves hours and gains riders, under its 20 s assumption.</p>
  </section>` : ''}

  <section id="sec-interventions" class="sec">
    <h2>Interventions ${chip('simulated')} ${chip('scheduled')}</h2>
    <p class="sub">${IV ? `Each change runs on ${IV.replicates} synthetic populations against today's schedule; behaviour is simulated, cost is scheduled vehicle-hours from GTFS. Bus and train vehicle-hours are not equally costly: compare within a mode.` : 'No intervention report.'}</p>
    <div class="grid2">
      <div class="card"><h3>Transit trips per 1,000 added vehicle-hours</h3><div id="chIvService"></div></div>
      <div class="card"><h3>Transit trips per $1,000 of fare revenue forgone ${chip('hypothesis')}</h3><div id="chIvFare"></div><p class="note">Fare response follows from an assumed $15/h value of time.</p></div>
    </div>
    <div class="card wide"><h3>Who benefits</h3><p class="sub">Lowest-income community areas hold ${IV ? pct(IV.low_income_population_share) : '–'} of residents. Jobs reachable by transit within 45 min (60 min at night).</p><div id="tbEquity" class="tablewrap"></div></div>
  </section>

  <section id="sec-operations" class="sec">
    <h2>Operations tools</h2>
    <div class="grid2">
      <div class="card"><h3>Crowding forecast ${chip('observed')}</h3><p class="sub">${O.crowding ? `Forecast weekday rides per scheduled trip, ${esc(O.crowding.date)} (data to ${esc(O.crowding.asof)})` : ''}</p><div id="chCrowd"></div>
        ${O.crowding ? `<div class="tiles small"><div class="tile"><b>${O.crowding.male.bus.M_med4.toFixed(3)}</b><span>bus forecast error vs ${O.crowding.male.bus.B_naive.toFixed(3)} for same-day-last-week</span></div><div class="tile"><b>${O.crowding.male.rail.M_med4.toFixed(3)}</b><span>'L' error vs ${O.crowding.male.rail.B_naive.toFixed(3)}</span></div></div>` : ''}</div>
      <div class="card"><h3>Live-feed anomaly detection ${chip('simulated')}</h3><p class="sub">Precision and recall on a simulated feed with injected, labelled anomalies (not real incidents).</p><div id="tbAnom" class="tablewrap"></div>
        <h3 style="margin-top:18px">Bus holding rule ${chip('simulated')}</h3>${O.holding ? `<p>${status(false)} Pre-registered test: passenger wait <b>${O.holding.preregistered.diff >= 0 ? '+' : ''}${O.holding.preregistered.diff.toFixed(2)} min</b> [${O.holding.preregistered.ci_low.toFixed(2)}, ${O.holding.preregistered.ci_high.toFixed(2)}]. After a start-up fix found later: ${O.holding.corrected.diff.toFixed(2)} min. Shown in Live as advisory only.</p>` : ''}</div>
    </div>
  </section>

  <section id="sec-reliability" class="sec">
    <h2>Reliability: scheduled vs observed ${chip('observed')} ${chip('scheduled')}</h2>
    ${O.reliability && O.reliability.coverage && O.reliability.coverage.runs ? `<p class="sub">${O.reliability.coverage.runs} polling runs, ${O.reliability.coverage.polls} polls.</p>` :
      '<div class="empty"><b>Waiting for live history.</b> Bunching, gaps and service delivered are computed from polled CTA positions against the GTFS schedule. No polls with positions exist yet; this fills in after the live workflow runs with the CTA keys.</div>'}
    <div class="card wide"><h3>What 5-minute polling can recover ${chip('simulated')}</h3><p class="sub">True vs estimated, on a simulated line. Gaps are undercounted (censored), bunching slightly overcounted.</p><div id="tbBias" class="tablewrap"></div></div>
  </section>
  <footer class="page-foot">SimChicago is not affiliated with or endorsed by CTA. Sources and methods: docs/EVALUATION.md, docs/BRIEF.md in the repository.</footer>
  </div>`;

  root.querySelectorAll('[data-count]').forEach(el => countUp(el, +el.dataset.count));
  const draw = () => {
    lineChart(root.querySelector('#chRidership'), { x: R.weekly.week_start, label: 'Average daily rides per week',
      series: [{ name: 'Bus', color: 'var(--s1)', values: R.weekly.bus }, { name: "'L'", color: 'var(--s2)', values: R.weekly.rail }] });
    barList(root.querySelector('#chTopBus'), { rows: R.top_bus.map(r => ({ label: `${r.id} ${r.name}`, value: r.weekday_rides })), color: 'var(--s1)' });
    barList(root.querySelector('#chTopRail'), { rows: R.top_rail.map(r => ({ label: r.name, value: r.weekday_rides })), color: 'var(--s2)' });
    const names = { B_mean: 'Constant', B_service: 'Scheduled service', M_sim: 'Simulation alone', M_cal: 'Simulation + schedule' };
    for (const [kind, id, lbl] of [['bus', '#chRvBus', 'Bus routes'], ['rail', '#chRvRail', "'L' stations"]]) {
      if (!rv[kind]) continue;
      const m = rv[kind].male, best = Object.entries(m).sort((a, b) => a[1] - b[1])[0][0];
      groupedBars(root.querySelector(id), { groups: [{ label: `${lbl} (${rv[kind].units})`, items: Object.keys(names).map(k => ({ name: names[k], value: m[k], best: k === best,
        color: k === 'M_cal' ? 'var(--s1)' : k === 'M_sim' ? 'var(--s3)' : 'var(--neutral)' })) }] });
    }
    if (M.transit_disruption) intervalChart(root.querySelector('#chDisruption'), { rows: M.transit_disruption.map(r => ({ label: r.scenario, mean: r.rel, lo: r.ci_low, hi: r.ci_high })), valueFmt: v => sgn(v, 1), color: 'var(--s2)', zero: true });
    if (IV) {
      const rk = IV.ranking;
      intervalChart(root.querySelector('#chIvService'), { rows: rk.filter(r => r.ranked_by.includes('vehicle-hours') && Number.isFinite(r.value)).map(r => ({ label: shortIv(r.intervention), mean: r.value, lo: r.ci_low, hi: r.ci_high, tip: `${fmt(r.vehicle_hours_per_weekday)} added vehicle-hours, +${fmt(r.transit_trips)} trips/weekday` })) });
      intervalChart(root.querySelector('#chIvFare'), { rows: rk.filter(r => r.ranked_by.includes('revenue')).map(r => ({ label: r.intervention, mean: r.value, lo: r.ci_low, hi: r.ci_high, tip: `+${fmt(r.transit_trips)} trips/weekday` })), color: 'var(--s2)' });
      root.querySelector('#tbEquity').innerHTML = `<table class="tb"><thead><tr><th>Intervention</th><th>Added veh-h/day</th><th>Δ transit trips/day</th><th>Time savings to low-income areas</th><th>Jobs reachable: low-income / other areas</th></tr></thead><tbody>${rk.map(r => `<tr><td>${esc(r.intervention)}</td><td class="n">${fmt(r.vehicle_hours_per_weekday)}</td><td class="n">${Number.isFinite(r.transit_trips) ? '+' + fmt(r.transit_trips) : '–'}</td><td class="n">${pct(r.low_income_share_of_savings, 0)}</td><td class="n">${r.access_jobs ? `+${fmt(r.access_gain_low)} / +${fmt(r.access_gain_other)}` : '–'}</td></tr>`).join('')}</tbody></table>`;
    }
    if (SD) {
      const short = n => n.replace("Re-allocate bus frequency (square-root rule), ", 'Square-root, ').replace(" of today's bus vehicle-hours", ' budget').replace(/Bus stop balancing.*/, 'Stop balancing, top-10');
      intervalChart(root.querySelector('#chSdTrips'), { rows: SD.results.filter(r => r.transit_trips).map(r => ({ label: short(r.name), mean: r.transit_trips.mean, lo: r.transit_trips.ci_low, hi: r.transit_trips.ci_high, tip: `${fmt(r.vehicle_hours)} vehicle-hours per weekday` })), valueFmt: v => (v >= 0 ? '+' : '') + fmt(v) });
      root.querySelector('#tbSd').innerHTML = `<table class="tb"><thead><tr><th>Design</th><th>Δ bus veh-h/weekday</th><th>Δ transit trips/day [95%]</th><th>Rider time saved/day</th><th>Savings to low-income areas</th><th>Jobs in 45 min (low-income / other)</th></tr></thead><tbody>${SD.results.map(r => `<tr><td>${esc(r.name)}</td><td class="n">${r.vehicle_hours >= 0 ? '+' : ''}${fmt(r.vehicle_hours)}</td><td class="n">${r.transit_trips ? `${r.transit_trips.mean >= 0 ? '+' : ''}${fmt(r.transit_trips.mean)} [${fmt(r.transit_trips.ci_low)}, ${fmt(r.transit_trips.ci_high)}]` : '–'}</td><td class="n">${r.time_saved_min ? fmt(r.time_saved_min.mean / 60) + ' h' : '–'}</td><td class="n">${r.low_income_share_of_savings ? pct(r.low_income_share_of_savings.mean, 0) : '–'}</td><td class="n">${fmt(r.access_gain_low)} / ${fmt(r.access_gain_other)}</td></tr>`).join('')}</tbody></table>`;
      const stops = Object.values(SD.analytic).find(a => a.removed_stops)?.removed_stops || {};
      root.querySelector('#tbSdStops').innerHTML = `<table class="tb"><thead><tr><th>Route</th><th>Stops no longer served (both directions)</th></tr></thead><tbody>${Object.entries(stops).map(([r, n]) => `<tr><td>${esc(r)}</td><td class="n">${n}</td></tr>`).join('')}</tbody></table>`;
      barList(root.querySelector('#chSdUp'), { rows: SD.more_service.map(r => ({ label: `${r.route} ${r.name}`, value: r.multiplier, tip: `${Math.round(r.weekday_trips)} → ${Math.round(r.proposed_trips)} weekday trips; ${Math.round(r.boardings)} boardings/weekday` })), color: 'var(--s3)', valueFmt: v => '×' + v.toFixed(2) });
      barList(root.querySelector('#chSdDown'), { rows: SD.less_service.map(r => ({ label: `${r.route} ${r.name}`, value: r.multiplier, tip: `${Math.round(r.weekday_trips)} → ${Math.round(r.proposed_trips)} weekday trips; ${Math.round(r.boardings)} boardings/weekday` })), color: 'var(--s2)', valueFmt: v => '×' + v.toFixed(2) });
    }
    if (O.crowding) barList(root.querySelector('#chCrowd'), { rows: O.crowding.top_bus.map(r => ({ label: `${r.id} ${r.name}`, value: r.per_trip, tip: `${fmt(r.rides)} rides over ${r.trips} scheduled trips` })), color: 'var(--s3)', valueFmt: v => v.toFixed(0), unit: ' /trip' });
    if (O.anomalies) root.querySelector('#tbAnom').innerHTML = `<table class="tb"><thead><tr><th>Detector</th><th>Precision</th><th>Recall</th><th>TP / FP / FN</th></tr></thead><tbody>${Object.entries(O.anomalies.detectors).map(([k, v]) => `<tr><td>${esc(k.replace('_', ' '))}</td><td class="n">${v.precision.toFixed(2)}</td><td class="n">${v.recall.toFixed(2)}</td><td class="n">${v.tp} / ${v.fp} / ${v.fn}</td></tr>`).join('')}</tbody></table>`;
    if (O.reliability) root.querySelector('#tbBias').innerHTML = `<table class="tb"><thead><tr><th>Simulated line</th><th>Bunching true → est.</th><th>Gaps true → est.</th><th>Headway CV true → est.</th></tr></thead><tbody>${O.reliability.polling_bias.map(b => `<tr><td>headway CV ${b.inputs.cv}, speed CV ${b.inputs.speed_cv}, ${Math.round(b.inputs.skip * 100)}% runs skipped</td><td class="n">${b.truth.bunching_share.toFixed(3)} → ${b.estimate.bunching_share.toFixed(3)}</td><td class="n">${b.truth.gap_share.toFixed(3)} → ${b.estimate.gap_share.toFixed(3)}</td><td class="n">${b.truth.headway_cv.toFixed(2)} → ${b.estimate.headway_cv.toFixed(2)}</td></tr>`).join('')}</tbody></table>`;
  };
  requestAnimationFrame(draw);
  let to; addEventListener('resize', () => { clearTimeout(to); to = setTimeout(draw, 200); });
  // sub-navigation: smooth scroll and active section highlight
  const scroller = root.closest('.view');
  root.querySelectorAll('.subnav a').forEach(a => a.addEventListener('click', e => { e.preventDefault(); root.querySelector(`#sec-${a.dataset.sec}`).scrollIntoView({ behavior: 'smooth', block: 'start' }); history.replaceState(null, '', a.getAttribute('href')); }));
  const obs = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) root.querySelectorAll('.subnav a').forEach(a => a.classList.toggle('on', `sec-${a.dataset.sec}` === en.target.id)); }), { root: scroller, rootMargin: '-30% 0px -60% 0px' });
  root.querySelectorAll('.sec').forEach(s => obs.observe(s));
}
