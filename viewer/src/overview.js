// Overview: what SimChicago is and what is new, with the real numbers behind each claim.
import { countUp, fmt } from './charts.js';
import { chip } from './insights.js';

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function renderOverview(root, I, D) {
  const n = I?.network?.counts || {}, R = I?.ridership, M = I?.models || {}, IV = I?.interventions, O = I?.ops || {};
  const V = I?.validation || [];
  const rv = M.ridership_validation?.bus?.male;
  const slow = (M.transit_disruption || []).find(r => /slower/.test(r.scenario));
  const best = IV?.ranking?.find(r => Number.isFinite(r.value) && r.ranked_by.includes('vehicle-hours'));
  const crowd = O.crowding;
  const cards = [
    { k: 'network', icon: 'net', title: 'The real CTA network', num: n.routes, unit: 'routes', fmtv: v => Math.round(v),
      body: `${fmt(n.stops)} stops, ${n.patterns} service patterns and ${fmt(n.weekday_trips)} weekday trips from CTA's GTFS timetable, turned into door-to-door travel times (walk, wait, ride, transfer, fare).`, prov: 'scheduled', go: '#live', cta: 'See it live' },
    { k: 'response', icon: 'wave', title: 'Riders respond to service', num: slow ? Math.abs(slow.rel) * 100 : null, unit: '% fewer trips', fmtv: v => v.toFixed(1),
      body: 'Slow every bus and train by 1.5× and simulated transit trips fall by this much, from the network, with no hand-set mode shift.', prov: 'simulated', go: '#insights/validation', cta: 'How it is validated' },
    { k: 'ridership', icon: 'check', title: 'Checked against real ridership', num: rv ? (1 - rv.M_cal / rv.B_service) * 100 : null, unit: '% lower error', fmtv: v => v.toFixed(0),
      body: `On bus routes the model never saw, simulation + schedule predicts 2025-26 ridership better than the schedule alone (log error ${rv ? rv.M_cal.toFixed(3) : '–'} vs ${rv ? rv.B_service.toFixed(3) : '–'}). On 'L' stations it does not, and we say so.`, prov: 'observed', go: '#insights/validation', cta: 'All checks' },
    { k: 'ranking', icon: 'rank', title: 'What moves riders per dollar of service', num: best?.value, unit: 'trips / 1,000 veh-h', fmtv: v => fmt(v),
      body: `${best ? esc(best.intervention) : ''} leads eight tested interventions on trips gained per added vehicle-hour, with 95% intervals and who benefits.`, prov: 'simulated', go: '#insights/interventions', cta: 'Intervention ranking' },
    { k: 'crowding', icon: 'cal', title: 'Crowding a week ahead', num: crowd ? (1 - crowd.male.bus.M_med4 / crowd.male.bus.B_naive) * 100 : null, unit: '% better than naive', fmtv: v => v.toFixed(0),
      body: 'One-week-ahead ridership per route and station beats "same day last week" across 63,000 held-out forecasts in 2026; crowding = riders per scheduled trip.', prov: 'observed', go: '#insights/operations', cta: 'Forecasts' },
    { k: 'live', icon: 'live', title: 'Near-live operations view', num: null, unit: '',
      body: 'Bus and train positions polled server-side every few minutes within CTA limits, with bunching advice and feed-anomaly flags. Keys never reach the browser.', prov: 'observed', go: '#live', cta: 'Open Live' },
  ];
  const nPass = V.filter(c => c.pass === true).length;
  root.innerHTML = `<div class="ov">
    <div class="ov-hero">
      <p class="eyebrow">CTA digital twin · Chicago</p>
      <h1>See how the city moves,<br><span class="grad">and what would move it more.</span></h1>
      <p class="lede">SimChicago couples the real CTA network and ridership with a calibrated synthetic Chicago of ${D ? fmt(D.meta.represented_population) : '2.6M'} residents, then tests changes to service against held-out data before ranking them.</p>
      <div class="ov-ctas"><a class="btn primary" href="#insights">Explore the insights</a><a class="btn" href="#simulate">Run the simulation</a><a class="btn ghost" href="#live">Live CTA</a></div>
      <div class="ov-meta"><span><b>${nPass}/${V.length}</b> validation checks pass</span><span><b>${R ? esc(R.period[1]) : '–'}</b> latest ridership</span><span><b>${n.stations ?? '–'}</b> 'L' stations</span></div>
    </div>
    <div class="ov-cards">${cards.map((c, i) => `<a class="ocard" href="${c.go}" style="animation-delay:${120 + i * 70}ms">
      <div class="oc-top"><span class="oc-ic ic-${c.icon}" aria-hidden="true"></span>${chip(c.prov)}</div>
      ${c.num !== null && c.num !== undefined ? `<div class="oc-num"><b data-to="${c.num}" data-fmt="${c.k}">0</b><span>${esc(c.unit)}</span></div>` : '<div class="oc-num"><b class="pulse-dot"></b><span>near-live snapshots</span></div>'}
      <h3>${esc(c.title)}</h3><p>${c.body}</p><span class="oc-go">${esc(c.cta)} →</span></a>`).join('')}</div>
    <div class="ov-steps">
      ${[['Data', 'CTA GTFS, ridership, live feeds; census and city data, all pinned'], ['Network', 'Frequency-based paths: walk, wait, ride, transfer, fare'], ['Behaviour', 'About 2,000 weighted synthetic residents choosing where and how to travel'], ['Validation', 'Held-out districts, routes and periods vs simple baselines'], ['Decisions', 'Interventions ranked by riders per vehicle-hour, with equity']]
        .map(([t, d], i) => `<div class="step"><span class="sn">${i + 1}</span><b>${t}</b><span>${d}</span></div>`).join('<span class="sarrow" aria-hidden="true"></span>')}
    </div>
  </div>`;
  const fmts = Object.fromEntries(cards.map(c => [c.k, c.fmtv]));
  root.querySelectorAll('[data-to]').forEach(el => countUp(el, +el.dataset.to, { dur: 1400, format: fmts[el.dataset.fmt] }));
}
