/* Finance: what each property costs and earns, and whether it pays its way.
 *
 * The Finance page (portfolio figures, a monthly chart, every property's
 * result), the Finance section of the property panel, and the form for
 * recording income, running costs and capital. Filters come from the shared
 * toolbar, so the page always describes the same properties as the Portfolio.
 */
window.Finance = (function () {
  'use strict';

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.prototype.slice.call((r || document).querySelectorAll(s));
  const esc = (v) => Fmt.esc(v);

  let notify = function () {};
  let app = null;            // the host app's state
  let hooks = {};            // filters(), openProperty(id), can(key), allowedOn(key, p), refreshDrawer()
  let ref = null;            // categories and kinds from /api/reference
  let report = null;
  let statusFilter = '';
  let sortKey = 'net-asc';
  let loading = 0;
  let arriving = false;      // the next render is a fresh visit: let things rise and draw in
  let editing = null;        // the entry open in the form, or null for a new one
  let formProperty = null;

  const STATUS = {
    profit: { label: 'Profitable', icon: 'up', cls: 'ok' },
    'break-even': { label: 'Break-even', icon: 'level', cls: 'warn' },
    loss: { label: 'Loss-making', icon: 'down', cls: 'bad' },
    'cost-only': { label: 'Cost only', icon: 'dot', cls: 'info' },
    none: { label: 'No figures', icon: 'dot', cls: 'none' }
  };
  const STATUS_ORDER = ['loss', 'break-even', 'profit', 'cost-only', 'none'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function icon(name) { return '<svg class="ic"><use href="#i-' + name + '"/></svg>'; }

  /* ---------- money and months ---------- */

  function lkr(n, compact) {
    const v = Number(n || 0), a = Math.abs(v), sign = v < 0 ? '−' : '';
    if (compact && a >= 1e9) return sign + 'LKR ' + (a / 1e9).toFixed(2).replace(/\.?0+$/, '') + ' Bn';
    if (compact && a >= 1e6) return sign + 'LKR ' + (a / 1e6).toFixed(2).replace(/\.?0+$/, '') + ' Mn';
    return sign + 'LKR ' + Math.round(a).toLocaleString('en-US');
  }

  function signed(n) { return (n > 0 ? '+' : '') + lkr(n, true); }

  function pct(v) {
    return (v < 0 ? '−' : '') + Math.abs(Number(v || 0)).toLocaleString('en-US', { maximumFractionDigits: 1 }) + '%';
  }

  // A sort key for a figure that may be missing: missing ones go last.
  function nv(v) { return v === null || v === undefined ? -1e15 : v; }

  function monthKey(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'); }

  function addMonths(key, n) {
    const p = key.split('-').map(Number);
    const d = new Date(p[0], p[1] - 1 + n, 1);
    return monthKey(d);
  }

  function monthLabel(key, withYear) {
    const p = key.split('-');
    return MONTHS[Number(p[1]) - 1] + (withYear === false ? '' : ' ' + p[0]);
  }

  function rangeLabel(from, to) {
    return from === to ? monthLabel(from) : monthLabel(from, from.slice(0, 4) !== to.slice(0, 4)) + ' – ' + monthLabel(to);
  }

  function yearStart(today) {
    const start = (ref && ref.yearStartMonth) || 4;
    const y = today.getMonth() + 1 >= start ? today.getFullYear() : today.getFullYear() - 1;
    return y + '-' + String(start).padStart(2, '0');
  }

  function fyName(startKey) {
    const y = Number(startKey.slice(0, 4));
    return 'FY ' + y + '/' + String((y + 1) % 100).padStart(2, '0');
  }

  function periods() {
    const today = new Date(), now = monthKey(today), fy = yearStart(today), lastFy = addMonths(fy, -12);
    return [
      { key: 'fy', label: fyName(fy) + ' to date', from: fy, to: now },
      { key: 'fy-full', label: fyName(fy) + ', full year', from: fy, to: addMonths(fy, 11) },
      { key: 'last-fy', label: fyName(lastFy), from: lastFy, to: addMonths(lastFy, 11) },
      { key: '12m', label: 'Last 12 months', from: addMonths(now, -11), to: now },
      { key: 'cal', label: 'Calendar ' + today.getFullYear() + ' to date', from: today.getFullYear() + '-01', to: now }
    ];
  }

  function period() {
    const all = periods();
    let key = 'fy';
    try { key = localStorage.getItem('finance-period') || 'fy'; } catch (e) { /* private window */ }
    return all.filter((p) => p.key === key)[0] || all[0];
  }

  function badge(status, small) {
    const s = STATUS[status] || STATUS.none;
    return '<span class="fin-badge ' + s.cls + (small ? ' sm' : '') + '">' + icon('fin-' + s.icon) + s.label + '</span>';
  }

  /* ---------- set up ---------- */

  function init(toastFn, appState, appHooks) {
    notify = toastFn || notify;
    app = appState;
    hooks = appHooks || {};
    ref = app.reference.finance;

    const select = $('#fin-period');
    select.innerHTML = periods().map((p) => '<option value="' + p.key + '">' + esc(p.label) + '</option>').join('');
    select.value = period().key;
    select.addEventListener('change', function () {
      try { localStorage.setItem('finance-period', select.value); } catch (e) { /* fine */ }
      refresh();
      hooks.refreshDrawer && hooks.refreshDrawer();
    });
    $('#fin-sort').addEventListener('change', function () { sortKey = this.value; renderTable(); Fx.rise($('#fin-rows'), 10); });
    $('#fin-status').addEventListener('click', function (event) {
      const b = event.target.closest('[data-status]');
      if (!b) return;
      statusFilter = statusFilter === b.dataset.status ? '' : b.dataset.status;
      renderTable();
      renderStanding();
      Fx.rise($('#fin-rows'), 10);
    });
    $('#fin-rows').addEventListener('click', function (event) {
      const tr = event.target.closest('[data-property]');
      if (tr) hooks.openProperty(Number(tr.dataset.property));
    });
    $('#fin-losers').addEventListener('click', function (event) {
      const li = event.target.closest('[data-property]');
      if (li) hooks.openProperty(Number(li.dataset.property));
    });
    $('#fin-mult-filter').addEventListener('click', function (event) {
      const b = event.target.closest('[data-mult]');
      if (!b) return;
      multFilter = b.dataset.mult;
      renderMultiples();
      Charts.bindTooltips($('#fin-mults'));
      Fx.rise($('#fin-mults'), 12);
      Fx.draw($('#fin-mults'));
    });
    $('#fin-mults').addEventListener('click', function (event) {
      const b = event.target.closest('[data-property]');
      if (b) hooks.openProperty(Number(b.dataset.property));
    });
    $('#fin-turning-list').addEventListener('click', function (event) {
      const li = event.target.closest('[data-property]');
      if (li) hooks.openProperty(Number(li.dataset.property));
    });
    $('#fin-roc').addEventListener('click', function (event) {
      const li = event.target.closest('[data-property]');
      if (li) hooks.openProperty(Number(li.dataset.property));
    });
    $('#fin-bench').addEventListener('click', function (event) {
      if (event.target.closest('[data-bench-edit]')) editBenchmark();
      else if (event.target.closest('[data-bench-cancel]')) renderBenchmark();
    });
    $('#fin-bench').addEventListener('submit', function (event) { event.preventDefault(); saveBenchmark(); });
    $('#btn-fin-new').addEventListener('click', () => openEntry(null, null));
    $('#btn-fin-export').addEventListener('click', function () {
      const p = period(), q = Object.assign({}, hooks.filters(), { from: p.from, to: p.to });
      location.href = '/api/export/finance.csv' + qs(q);
    });

    // The form
    $$('#fin-kind input').forEach((r) => r.addEventListener('change', () => { fillCategories(); updateHint(); }));
    $('#fin-form').addEventListener('input', updateHint);
    $('#fin-form').addEventListener('change', updateHint);
    $('#fin-form').addEventListener('submit', (e) => { e.preventDefault(); saveEntry(); });
    $('#btn-fin-save').addEventListener('click', saveEntry);
    $('#btn-fin-delete').addEventListener('click', deleteEntry);
  }

  function qs(params) {
    const parts = [];
    Object.keys(params).forEach(function (k) {
      if (params[k] !== undefined && params[k] !== null && params[k] !== '') {
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
      }
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  /* ---------- the Finance page ---------- */

  function show() { arriving = true; refresh(); }

  async function refresh() {
    const p = period(), mine = ++loading;
    $('#fin-caption').textContent = 'What each property costs and earns, ' + rangeLabel(p.from, p.to) + '.';
    let data;
    try {
      data = await API.financeSummary(Object.assign({}, hooks.filters(), { from: p.from, to: p.to }));
    } catch (err) {
      notify(err.message, true);
      return;
    }
    if (mine !== loading) return;            // a newer request is on its way
    report = data;
    renderKpis();
    renderChart();
    renderStanding();
    renderReturns();
    renderCategories();
    renderPortfolioTrend();
    renderMultiples();
    renderTable();
    Charts.bindTooltips($('#view-finance'));
    animate();
  }

  // The same motion as the other pages: figures count to their new values every
  // time; on arriving, the cards rise in turn and the charts draw themselves in.
  function animate() {
    const page = $('#view-finance');
    Fx.countUp(page, '.fin-kpi b');
    Fx.countUp(page, '.fin-key b');
    Fx.countUp(page, '.fin-standing-list b');
    Fx.countUp(page, '.fin-roc-sum b');
    if (!arriving) return;
    arriving = false;
    Fx.rise($('#fin-kpis'));
    Fx.rise($('.fin-grid', page), 4);
    Fx.rise($('#fin-losers'), 5);
    Fx.rise($('#fin-roc'), 8);
    Fx.rise($('#fin-mults'), 12);
    Fx.rise($('#fin-rows'), 10);
    Fx.draw(page);
  }

  // How a figure compares with the same months a year earlier.
  function delta(now, before, kind) {
    if (!report.previous || !report.previous.totals || before === undefined) return '';
    const diff = now - before;
    const months = 'Against ' + rangeLabel(report.previous.from, report.previous.to);
    if (Math.abs(diff) < 0.5) return '<em class="fin-delta" title="' + esc(months) + '">' + icon('fin-level') + 'Same as last year</em>';
    const better = kind === 'cost' ? diff < 0 : diff > 0;
    const text = kind === 'net' || !before ? signed(diff) : (diff > 0 ? '+' : '−') + pct(Math.abs(diff / before * 100));
    return '<em class="fin-delta ' + (better ? 'good' : 'bad') + '" title="' + esc(months) + '">' + icon(diff > 0 ? 'fin-up' : 'fin-down') +
      esc(text) + ' on last year</em>';
  }

  function renderKpis() {
    const t = report.totals, c = report.counts, before = (report.previous && report.previous.totals) || {};
    const cap = report.capital;
    const withFigures = report.properties.length - c.none;
    const invested = report.properties.reduce((s, r) => s + (r.invested || 0), 0);
    const cards = [
      ['fin-in', 'Income', lkr(t.income, true), t.income ? report.properties.filter((r) => r.income).length + ' properties earning' : 'None recorded'],
      ['fin-out', 'Running costs', lkr(t.cost, true), t.rent ? 'Rent ' + lkr(t.rent, true) + ' · ' + Math.round(t.rent / (t.cost || 1) * 100) + '% of costs' : 'No rent recorded'],
      ['fin-net', 'Net result', signed(t.net), t.margin === null ? (t.cost ? 'Costs with no income' : 'Nothing recorded yet') : t.margin + '% of income'],
      ['fin-loss', 'Losing money', String(c.loss), withFigures ? 'of ' + withFigures + ' with figures' + (c['cost-only'] ? ' · ' + c['cost-only'] + ' cost only' : '') : 'Record figures to see'],
      ['fin-cap', 'Capital invested', lkr(invested, true), cap.returnPct !== null ? 'Earning ' + pct(cap.returnPct) + ' a year · benchmark ' + pct(report.benchmark)
        : t.capital ? lkr(t.capital, true) + ' in this period' : 'Purchases and building work']
    ];
    const deltas = [delta(t.income, before.income, 'income'), delta(t.cost, before.cost, 'cost'), delta(t.net, before.net, 'net'), '', ''];
    $('#fin-kpis').innerHTML = cards.map((k, i) => '<div class="fin-kpi ' + k[0] + (i === 2 ? ' ' + (t.net < 0 ? 'is-neg' : t.net > 0 ? 'is-pos' : '') : '') + '">' +
      '<span class="fin-kpi-label">' + esc(k[1]) + '</span><b>' + esc(k[2]) + '</b><small>' + esc(k[3]) + '</small>' + deltas[i] + '</div>').join('');
  }

  function renderChart() {
    const months = report.byMonth;
    const max = Math.max.apply(null, months.map((m) => Math.max(m.income, m.cost)).concat([1]));
    const any = months.some((m) => m.income || m.cost);
    const t = report.totals;
    $('#fin-chart-legend').innerHTML =
      '<span class="fin-key"><i style="background:var(--viz-1)"></i>Income <b>' + esc(lkr(t.income, true)) + '</b></span>' +
      '<span class="fin-key"><i style="background:var(--viz-2)"></i>Running costs <b>' + esc(lkr(t.cost, true)) + '</b></span>';
    if (!any) {
      $('#fin-chart').innerHTML = '<div class="chart-empty">No income or costs recorded for ' + esc(rangeLabel(report.period.from, report.period.to)) + '.</div>';
      return;
    }
    const tick = (v) => '<span class="fin-tick" style="bottom:calc(26px + (100% - 26px) * ' + (v / max).toFixed(4) + ')"><em>' + esc(lkr(v, true).replace('LKR ', '')) + '</em></span>';
    $('#fin-chart').innerHTML = '<div class="fin-plot">' + [max, max / 2].map(tick).join('') +
      months.map(function (m) {
        const net = m.income - m.cost;
        const bar = (v, cls, label) => '<span class="fin-bar ' + cls + '" style="height:' + (v ? Math.max(1.5, v / max * 100) : 0).toFixed(2) + '%"' +
          ' tabindex="0" data-tip-label="' + esc(monthLabel(m.month) + ' · ' + label) + '" data-tip-value="' + esc(lkr(v)) + '"></span>';
        return '<div class="fin-month' + (net < 0 ? ' is-neg' : '') + '">' +
          '<div class="fin-pair">' + bar(m.income, 'in', 'Income') + bar(m.cost, 'out', 'Running costs') + '</div>' +
          '<span class="fin-mlabel">' + esc(monthLabel(m.month, months.length > 12 || m.month.slice(5) === '01' || m === months[0])) + '</span></div>';
      }).join('') + '</div>';
  }

  function renderStanding() {
    const c = report.counts, total = report.properties.length || 1;
    $('#fin-standing').innerHTML = '<div class="fin-stack">' + STATUS_ORDER.filter((s) => c[s]).map((s) =>
      '<span class="seg ' + STATUS[s].cls + '" style="flex:' + c[s] + '" tabindex="0" data-tip-label="' + esc(STATUS[s].label) +
        '" data-tip-value="' + c[s] + ' properties"></span>').join('') + '</div>' +
      '<ul class="fin-standing-list">' + STATUS_ORDER.map((s) => '<li><button type="button" data-status="' + s + '" class="' +
        (statusFilter === s ? 'is-on' : '') + '">' + badge(s, true) + '<b>' + c[s] + '</b><span>' +
        Math.round(c[s] / total * 100) + '%</span></button></li>').join('') + '</ul>';
    $$('#fin-standing [data-status]').forEach((b) => b.addEventListener('click', function () {
      statusFilter = statusFilter === b.dataset.status ? '' : b.dataset.status;
      renderTable();
      renderStanding();
      Fx.rise($('#fin-rows'), 10);
      $('#fin-table-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
    const turning = report.properties.filter((r) => (r.status === 'loss' || r.status === 'cost-only') && r.trend &&
      r.trend.direction === 'up').sort((a, b) => (a.trend.breakEven || '9999') < (b.trend.breakEven || '9999') ? -1 : 1).slice(0, 5);
    $('#fin-turning').hidden = !turning.length;
    $('#fin-turning-list').innerHTML = turning.map((r) => '<li data-property="' + r.id + '" tabindex="0"><span class="swatch" style="background:' +
      esc(r.sbu_color) + '"></span><span class="fin-lname"><b>' + esc(r.name) + '</b><small>' + esc(r.property_code) + ' · ' +
      esc(trendSentence(r.trend, true).replace(/ · .*/, '')) + '</small></span><span class="fin-lval up">' +
      (r.trend.breakEven ? 'break-even ~' + esc(monthLabel(r.trend.breakEven)) : icon('fin-up') + 'improving') + '</span></li>').join('');
    const losers = report.properties.filter((r) => r.net < 0).sort((a, b) => a.net - b.net).slice(0, 5);
    $('#fin-losers').innerHTML = losers.length
      ? losers.map((r) => '<li data-property="' + r.id + '" tabindex="0"><span class="swatch" style="background:' + esc(r.sbu_color) + '"></span>' +
          '<span class="fin-lname"><b>' + esc(r.name) + '</b><small>' + esc(r.property_code) +
          (r.rentShare ? ' · rent is ' + r.rentShare + '% of income' : r.status === 'cost-only' ? ' · no income recorded' : '') + '</small></span>' +
          '<span class="fin-lval">' + esc(signed(r.net)) + '</span></li>').join('')
      : '<li class="empty-li">No property is losing money in this period.</li>';
  }

  /* ---------- return on capital: is the money earning enough? ---------- */

  function renderBenchmark() {
    $('#fin-bench').innerHTML = '<span class="fin-bench-now" title="What the same money would earn elsewhere, for example in a fixed deposit">' +
      '<i></i>Benchmark <b>' + esc(pct(report.benchmark)) + '</b> a year</span>' +
      (report.mayChangeBenchmark ? '<button type="button" class="btn btn-ghost btn-sm" data-bench-edit>' + icon('pencil') + 'Change</button>' : '');
  }

  function editBenchmark() {
    $('#fin-bench').innerHTML = '<form class="fin-bench-form" novalidate><label>Benchmark <input name="benchmark" type="number" inputmode="decimal" step="0.1" min="0" max="50" value="' +
      esc(report.benchmark) + '" aria-label="Benchmark return, percent a year"> % a year</label>' +
      '<button type="submit" class="btn btn-dark btn-sm">Save</button><button type="button" class="btn btn-ghost btn-sm" data-bench-cancel>Cancel</button></form>';
    const input = $('#fin-bench input');
    input.focus();
    input.select();
  }

  async function saveBenchmark() {
    const input = $('#fin-bench input');
    try {
      const saved = await API.saveFinanceSettings({ benchmark: input.value });
      notify('Benchmark set to ' + pct(saved.benchmark) + ' a year.');
      refresh();
      hooks.refreshDrawer && hooks.refreshDrawer();
    } catch (err) {
      notify(err.message, true);
      input.focus();
    }
  }

  // Above the benchmark, below it but still earning, or losing money.
  function tone(r) { return r.returnPct < 0 ? 'bad' : r.benchmarkGap >= 0 ? 'ok' : 'warn'; }

  function renderReturns() {
    renderBenchmark();
    const rate = report.benchmark, cap = report.capital;
    const rows = report.properties.filter((r) => r.invested && r.status !== 'none').sort((a, b) => b.returnPct - a.returnPct);
    $('#fin-roc-empty').hidden = rows.length > 0;
    $('#fin-roc-sum').hidden = !rows.length;
    $('#fin-roc-sum').innerHTML = !rows.length ? '' :
      '<div><span>Capital in these properties</span><b>' + esc(lkr(cap.invested, true)) + '</b><small>' + cap.properties + ' propert' + (cap.properties === 1 ? 'y' : 'ies') +
        (cap.value ? ' · worth ' + esc(lkr(cap.value, true)) + ' today' : '') + '</small></div>' +
      '<div><span>Earning a year</span><b>' + esc(pct(cap.returnPct)) + '</b><small>' + esc(signed(cap.yearlyNet)) + ' a year' +
        (cap.valueReturnPct !== null ? ' · ' + esc(pct(cap.valueReturnPct)) + ' on today\'s value' : '') + '</small></div>' +
      '<div class="' + (cap.gap >= 0 ? 'pos' : 'neg') + '"><span>Against the benchmark</span><b>' + esc(signed(cap.gap)) + '</b><small>a year · ' +
        cap.above + ' above, ' + cap.below + ' below</small></div>';
    const top = Math.max.apply(null, rows.map((r) => r.returnPct).concat([rate * 1.5, 1]));
    $('#fin-roc').innerHTML = rows.map(function (r) {
      const gap = r.benchmarkGap;
      return '<li data-property="' + r.id + '" tabindex="0"><span class="swatch" style="background:' + esc(r.sbu_color) + '"></span>' +
        '<span class="fin-lname"><b>' + esc(r.name) + '</b><small>' + esc(r.property_code) + ' · ' + esc(lkr(r.invested, true)) + ' capital' +
          (r.valueReturnPct !== null ? ' · ' + esc(pct(r.valueReturnPct)) + ' on today\'s value' : '') + '</small></span>' +
        '<span class="fin-roc-bar" tabindex="0" data-tip-label="' + esc(r.name) + '" data-tip-value="' + esc(pct(r.returnPct) + ' a year · benchmark ' + pct(rate)) + '">' +
          '<i class="' + tone(r) + '" style="width:' + (Math.max(0, r.returnPct) / top * 100).toFixed(1) + '%"></i>' +
          '<em style="left:' + (rate / top * 100).toFixed(1) + '%"></em></span>' +
        '<span class="fin-roc-val"><b>' + esc(pct(r.returnPct)) + '</b><small class="' + (gap >= 0 ? 'pos' : 'neg') + '">' + esc(signed(gap)) + ' a year</small></span></li>';
    }).join('');
  }

  /* ---------- where the money goes ---------- */

  const CAT_GROUPS = [['cost', 'Running costs', 'var(--viz-2)'], ['income', 'Income', 'var(--viz-1)'], ['capital', 'Capital spent', 'var(--viz-other)']];

  function categoryHtml(cats, limit) {
    return CAT_GROUPS.map(function (g) {
      const list = cats.filter((c) => c.kind === g[0]);
      if (!list.length) return '';
      const total = list.reduce((sum, c) => sum + c.amount, 0), top = list[0].amount || 1;
      const shown = limit ? list.slice(0, limit) : list;
      return '<div class="fin-cat-group"><h3 class="fin-sub">' + esc(g[1]) + ' <b>' + esc(lkr(total, true)) + '</b></h3><ul class="fin-cats">' +
        shown.map((c) => '<li><span class="fin-cat-name" title="' + esc(c.label) + '">' + esc(c.label) + '</span>' +
          '<span class="fin-cat-bar"><i style="width:' + (c.amount / top * 100).toFixed(1) + '%;background:' + g[2] + '"></i></span>' +
          '<span class="fin-cat-val"><b>' + esc(lkr(c.amount, true)) + '</b><small>' + Math.round(c.amount / (total || 1) * 100) + '%</small></span></li>').join('') +
        (list.length > shown.length ? '<li class="fin-cat-more">' + (list.length - shown.length) + ' more</li>' : '') + '</ul></div>';
    }).join('');
  }

  function renderCategories() {
    const cats = report.byCategory || [];
    $('#fin-cats').innerHTML = cats.length ? categoryHtml(cats)
      : '<div class="chart-empty">No income or costs recorded for ' + esc(rangeLabel(report.period.from, report.period.to)) + '.</div>';
  }

  function slopeOf(r) { return r.trend && r.trend.slope !== null ? r.trend.slope : 0; }

  /* ---------- trend: is a property getting better or worse? ---------- */

  const DIRECTION = {
    up: { label: 'Improving', icon: 'fin-up', cls: 'ok' },
    down: { label: 'Worsening', icon: 'fin-down', cls: 'bad' },
    flat: { label: 'Steady', icon: 'fin-level', cls: 'flat' },
    short: { label: 'Too new to tell', icon: 'fin-dot', cls: 'none' }
  };

  function trendSentence(t, short) {
    if (!t) return 'No figures recorded yet.';
    if (t.direction === 'short') return 'Only ' + t.months + ' month' + (t.months === 1 ? '' : 's') + ' of figures — at least 4 are needed to see a trend.';
    const pace = lkr(Math.abs(t.slope));
    let text = t.direction === 'up' ? 'Improving by about ' + pace + ' a month'
      : t.direction === 'down' ? 'Worsening by about ' + pace + ' a month' : 'Holding steady';
    if (t.breakEven) text += short ? ' · breaks even ~' + monthLabel(t.breakEven) : '. At this rate it breaks even around ' + monthLabel(t.breakEven);
    else if (t.turnsLoss) text += short ? ' · could turn to a loss ~' + monthLabel(t.turnsLoss) : '. At this rate it could turn loss-making around ' + monthLabel(t.turnsLoss);
    return text + (short ? '' : '.');
  }

  function spark(values) {
    const w = 84, h = 28, n = values.length;
    if (!n) return '';
    const max = Math.max.apply(null, values.map(Math.abs).concat([1]));
    const step = w / n, bar = Math.max(2, step * 0.62), mid = h / 2;
    return '<svg class="fin-spark" viewBox="0 0 ' + w + ' ' + h + '" width="' + w + '" height="' + h + '" aria-hidden="true">' +
      '<line x1="0" x2="' + w + '" y1="' + mid + '" y2="' + mid + '" class="zero"/>' +
      values.map(function (v, i) {
        const len = Math.max(v ? 1.5 : 0, Math.abs(v) / max * (mid - 1));
        return '<rect x="' + (i * step + (step - bar) / 2).toFixed(1) + '" y="' + (v >= 0 ? mid - len : mid).toFixed(1) +
          '" width="' + bar.toFixed(1) + '" height="' + len.toFixed(1) + '" rx="1" class="' + (v >= 0 ? 'pos' : 'neg') + '"/>';
      }).join('') + '</svg>';
  }

  function trendCell(t) {
    if (!t) return '<span class="dash">—</span>';
    const d = DIRECTION[t.direction];
    return '<div class="fin-trend" data-tip-label="Trend" data-tip-value="' + esc(trendSentence(t, true)) + '" tabindex="0">' +
      spark(t.spark) + '<span class="fin-dirlabel ' + d.cls + '">' + icon(d.icon) + d.label + '</span></div>';
  }

  // The property panel's chart: each month's result, a 3-month average, and
  // the fitted line carried forward as a projection.
  function trendChart(t, opts) {
    opts = opts || {};
    const compact = !!opts.compact;
    const hist = t.history, proj = t.projection || [];
    const W = opts.width || 432, H = opts.height || 200;
    const padL = compact ? 4 : 46, padR = compact ? 4 : 8, padT = compact ? 6 : 14, padB = compact ? 6 : 26;
    const all = hist.map((h) => h.net).concat(hist.map((h) => h.avg3), proj.map((p) => p.net), [0]);
    let top = Math.max.apply(null, all), bottom = Math.min.apply(null, all);
    if (top === bottom) { top += 1; bottom -= 1; }
    const span = top - bottom;
    top += span * 0.08; bottom -= span * 0.08;
    const slots = hist.length + proj.length, step = (W - padL - padR) / slots;
    const x = (i) => padL + step * (i + 0.5);
    const y = (v) => padT + (top - v) / (top - bottom) * (H - padT - padB);
    const zero = y(0), bw = Math.max(2, step * 0.62);
    const tickVals = [top - span * 0.08, 0, bottom + span * 0.08].filter((v, i, a) => a.indexOf(v) === i);
    let svg = '<svg class="fin-trend-chart' + (compact ? ' compact' : '') + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(trendSentence(t)) + '">';
    if (proj.length && compact) {
      svg += '<rect class="proj-zone" x="' + (padL + step * hist.length).toFixed(1) + '" y="' + padT + '" width="' +
        (step * proj.length).toFixed(1) + '" height="' + (H - padT - padB) + '" rx="4"/>';
    } else if (proj.length) {
      svg += '<rect class="proj-zone" x="' + (padL + step * hist.length).toFixed(1) + '" y="' + padT + '" width="' +
        (step * proj.length).toFixed(1) + '" height="' + (H - padT - padB) + '" rx="6"/>' +
        '<text class="proj-label" x="' + (padL + step * (hist.length + proj.length / 2)).toFixed(1) + '" y="' + (padT + 12) + '">Projection</text>';
    }
    (compact ? [0] : tickVals).forEach(function (v) {
      if (compact) {
        svg += '<line class="zero" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + y(0).toFixed(1) + '" y2="' + y(0).toFixed(1) + '"/>';
        return;
      }
      svg += '<line class="' + (v === 0 ? 'zero' : 'grid') + '" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '"/>' +
        '<text class="tick" x="' + (padL - 6) + '" y="' + (y(v) + 3.5).toFixed(1) + '">' + esc(v === 0 ? '0' : lkr(v, true).replace('LKR ', '')) + '</text>';
    });
    hist.forEach(function (h, i) {
      const top_ = Math.min(y(h.net), zero), len = Math.max(h.net ? 1.5 : 0, Math.abs(y(h.net) - zero));
      svg += '<rect class="bar ' + (h.net >= 0 ? 'pos' : 'neg') + '" x="' + (x(i) - bw / 2).toFixed(1) + '" y="' + top_.toFixed(1) +
        '" width="' + bw.toFixed(1) + '" height="' + len.toFixed(1) + '" rx="2" tabindex="0" data-tip-label="' + esc(monthLabel(h.month)) +
        '" data-tip-value="' + esc(signed(h.net) + ' · income ' + lkr(h.income, true) + ', costs ' + lkr(h.cost, true)) + '"/>';
    });
    if (hist.length > 1) {
      svg += '<polyline class="avg" points="' + hist.map((h, i) => x(i).toFixed(1) + ',' + y(h.avg3).toFixed(1)).join(' ') + '"/>';
    }
    if (proj.length && t.fitNow !== null) {
      const pts = [[x(hist.length - 1), y(t.fitNow)]].concat(proj.map((p, i) => [x(hist.length + i), y(p.net)]));
      svg += '<polyline class="proj" points="' + pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ') + '"/>';
      const mark = t.breakEven || t.turnsLoss;
      const at = mark ? proj.findIndex((p) => p.month === mark) : -1;
      if (at !== -1) {
        svg += '<circle class="mark ' + (t.breakEven ? 'pos' : 'neg') + '" cx="' + x(hist.length + at).toFixed(1) + '" cy="' + zero.toFixed(1) + '" r="4.5" tabindex="0"' +
          ' data-tip-label="' + (t.breakEven ? 'Breaks even' : 'Turns to a loss') + '" data-tip-value="around ' + esc(monthLabel(mark)) + '"/>';
      }
    }
    if (compact) return svg + '</svg>';
    const label = (i, key, anchor) => '<text class="xlab" text-anchor="' + anchor + '" x="' + x(i).toFixed(1) + '" y="' + (H - 8) + '">' + esc(monthLabel(key)) + '</text>';
    svg += label(0, hist[0].month, 'start');
    if (hist.length > 2) svg += label(hist.length - 1, hist[hist.length - 1].month, proj.length ? 'middle' : 'end');
    if (proj.length) svg += label(slots - 1, proj[proj.length - 1].month, 'end');
    return svg + '</svg>';
  }

  function trendHtml(t) {
    if (!t) return '';
    const d = DIRECTION[t.direction];
    return '<div class="fin-trend-box"><div class="fin-trend-head"><b>Profit trend</b><span class="fin-dirlabel ' + d.cls + '">' + icon(d.icon) + d.label + '</span></div>' +
      '<p class="fin-trend-text">' + esc(trendSentence(t)) + '</p>' +
      (t.history.length ? trendChart(t) : '') +
      '<div class="fin-trend-legend"><span><i class="k-bar"></i>Monthly result</span><span><i class="k-avg"></i>3-month average</span>' +
        (t.projection.length ? '<span><i class="k-proj"></i>Projection</span>' : '') + '</div>' +
      (t.direction !== 'short' ? '<p class="fin-trend-note">A straight line through the last ' + t.months + ' months, carried forward: a guide, not a promise.' +
        (t.confidence === 'low' ? ' <b>The figures vary a lot, so treat it with care.</b>' : '') + '</p>' : '') +
      '</div>';
  }

  /* ---------- the pattern across properties ---------- */

  let multFilter = '';
  const MULT_FILTERS = [['', 'All'], ['turning', 'Turning around'], ['up', 'Improving'], ['down', 'Worsening'], ['flat', 'Steady']];

  function multMatches(r) {
    const t = r.trend;
    if (!t || t.direction === 'short') return multFilter === '';
    if (multFilter === 'turning') return (r.status === 'loss' || r.status === 'cost-only') && t.direction === 'up';
    return !multFilter || t.direction === multFilter;
  }

  function renderPortfolioTrend() {
    const t = report.trend;
    const host = $('#fin-portfolio-trend');
    if (!t || !t.history.length) {
      $('#fin-pt-text').textContent = 'Income less running costs, month by month, for the properties shown.';
      host.innerHTML = '<div class="chart-empty">No income or costs recorded for these properties yet.</div>';
      return;
    }
    const d = DIRECTION[t.direction];
    $('#fin-pt-text').innerHTML = '<span class="fin-dirlabel ' + d.cls + '">' + icon(d.icon) + d.label + '</span> ' +
      esc(trendSentence(t)) + (t.direction !== 'short' ? ' <span class="fin-pt-note">Last ' + t.months + ' months, carried forward: a guide, not a promise.</span>' : '');
    host.innerHTML = trendChart(t, { width: 1000, height: 260 });
  }

  function renderMultiples() {
    const withTrend = report.properties.filter((r) => r.trend && r.trend.history.length);
    const counts = {
      '': withTrend.length,
      turning: withTrend.filter((r) => (r.status === 'loss' || r.status === 'cost-only') && r.trend.direction === 'up').length,
      up: withTrend.filter((r) => r.trend.direction === 'up').length,
      down: withTrend.filter((r) => r.trend.direction === 'down').length,
      flat: withTrend.filter((r) => r.trend.direction === 'flat').length
    };
    $('#fin-mult-filter').innerHTML = MULT_FILTERS.map((f) => '<button type="button" data-mult="' + f[0] + '" class="' +
      (multFilter === f[0] ? 'is-active' : '') + '">' + esc(f[1]) + ' <b>' + counts[f[0]] + '</b></button>').join('');
    const rows = withTrend.filter(multMatches).sort((a, b) => slopeOf(b) - slopeOf(a));
    $('#fin-mults').innerHTML = rows.map(function (r) {
      const t = r.trend, d = DIRECTION[t.direction];
      const nets = t.history.map((h) => h.net), last = nets[nets.length - 1];
      return '<button type="button" class="fin-mult" data-property="' + r.id + '">' +
        '<span class="fin-mult-name" title="' + esc(r.name) + '">' + esc(r.name) + '</span>' +
        '<span class="fin-mult-meta"><span class="swatch" style="background:' + esc(r.sbu_color) + '"></span>' +
          '<span class="fin-mult-code">' + esc(r.property_code) + '</span>' +
          '<span class="fin-dirlabel ' + d.cls + '">' + icon(d.icon) + d.label + '</span></span>' +
        trendChart(t, { compact: true, width: 300, height: 92 }) +
        '<span class="fin-mult-foot"><span class="' + (last < 0 ? 'neg' : 'pos') + '">' + esc(signed(last)) + '/mo now</span>' +
          '<span>' + esc(t.direction === 'short' ? 'only ' + t.months + ' months of figures'
          : t.breakEven ? 'breaks even ~' + monthLabel(t.breakEven)
          : t.turnsLoss ? 'could turn to a loss ~' + monthLabel(t.turnsLoss)
          : (t.direction === 'flat' ? 'about the same each month' : (t.slope > 0 ? '+' : '−') + lkr(Math.abs(t.slope), true) + ' a month')) +
        '</span></span></button>';
    }).join('');
    const empty = $('#fin-mults-empty');
    empty.hidden = rows.length > 0;
    empty.textContent = withTrend.length ? 'No property matches this choice.' : 'No property has figures recorded yet.';
  }

  const SORTS = {
    'net-asc': (a, b) => a.net - b.net,
    'net-desc': (a, b) => b.net - a.net,
    income: (a, b) => b.income - a.income,
    cost: (a, b) => b.cost - a.cost,
    rent: (a, b) => (b.rentShare || 0) - (a.rentShare || 0),
    return: (a, b) => nv(b.returnPct) - nv(a.returnPct),
    sqft: (a, b) => nv(b.perSqft && b.perSqft.cost) - nv(a.perSqft && a.perSqft.cost),
    improving: (a, b) => slopeOf(b) - slopeOf(a),
    worsening: (a, b) => slopeOf(a) - slopeOf(b),
    name: (a, b) => a.name.localeCompare(b.name)
  };

  function renderTable() {
    const c = report.counts;
    $('#fin-status').innerHTML = [['', 'All', report.properties.length]].concat(STATUS_ORDER.map((s) => [s, STATUS[s].label, c[s]]))
      .map((s) => '<button type="button" data-status="' + s[0] + '" class="' + (statusFilter === s[0] ? 'is-active' : '') + '">' +
        esc(s[1]) + ' <b>' + s[2] + '</b></button>').join('');
    const rows = report.properties.filter((r) => !statusFilter || r.status === statusFilter);
    // Properties without figures sink to the bottom of every sort.
    rows.sort((a, b) => ((a.status === 'none') - (b.status === 'none')) || SORTS[sortKey](a, b));
    const tenure = (v) => (app.labels.ownershipTypes || {})[v] || v;
    $('#fin-rows').innerHTML = rows.map(function (r) {
      const none = r.status === 'none';
      return '<tr data-property="' + r.id + '" tabindex="0" class="' + (none ? 'is-none' : '') + '">' +
        '<td><div class="fin-prop"><span class="swatch" style="background:' + esc(r.sbu_color) + '"></span><div><b>' + esc(r.name) + '</b>' +
          '<small>' + esc(r.property_code) + ' · ' + esc(r.sbu_name) + (r.entity_code ? ' · ' + esc(r.entity_code) : '') + '</small></div></div></td>' +
        '<td class="muted-cell">' + esc(tenure(r.ownership_type)) + '</td>' +
        '<td class="num">' + (r.income ? esc(lkr(r.income)) : '<span class="dash">—</span>') + '</td>' +
        '<td class="num">' + (r.cost ? esc(lkr(r.cost)) : '<span class="dash">—</span>') + '</td>' +
        '<td class="num">' + (r.rent ? esc(lkr(r.rent)) + (r.rentShare ? '<small>' + r.rentShare + '% of income</small>' : '') : '<span class="dash">—</span>') + '</td>' +
        '<td class="num net ' + (r.net < 0 ? 'neg' : r.net > 0 ? 'pos' : '') + '">' + (none ? '<span class="dash">—</span>' : esc(signed(r.net)) +
          (r.margin !== null ? '<small>' + r.margin + '% margin</small>' : '')) + '</td>' +
        '<td>' + badge(r.status, true) + '</td>' +
        '<td>' + trendCell(r.trend) + '</td>' +
        '<td class="num">' + (r.invested ? esc(lkr(r.invested, true)) + (r.returnPct !== null ? '<small class="' + (r.benchmarkGap >= 0 ? 'pos' : 'neg') + '">' +
          esc(pct(r.returnPct)) + ' a year' + (r.paybackYears ? ' · pays back in ' + r.paybackYears + ' yrs' : '') + '</small>' : '') : '<span class="dash">—</span>') + '</td></tr>';
    }).join('');
    const empty = $('#fin-empty');
    empty.hidden = rows.length > 0;
    empty.textContent = report.properties.length ? 'No property matches this status.' : 'No properties match the filters.';
    $('#fin-hint').hidden = report.properties.some((r) => r.status !== 'none');
  }

  /* ---------- the property panel's Finance section ---------- */

  function measure(label, value, note, cls) {
    return '<div class="fin-m' + (cls ? ' ' + cls : '') + '"><span>' + esc(label) + '</span><b>' + esc(value) + '</b><small>' + esc(note) + '</small></div>';
  }

  // The property's figures set against its capital, its value, its size and last year.
  function measuresHtml(s, rate) {
    if (s.status === 'none') return '';
    const items = [];
    if (s.invested && s.returnPct !== null) {
      items.push(measure('Return a year', pct(s.returnPct), 'net ' + signed(s.yearly.net) + ' a year on ' + lkr(s.invested, true) + ' capital', tone(s)));
      items.push(measure('Against the ' + pct(rate) + ' benchmark', signed(s.benchmarkGap),
        'a year ' + (s.benchmarkGap >= 0 ? 'more' : 'less') + ' than the money would earn there', s.benchmarkGap >= 0 ? 'pos' : 'neg'));
    }
    if (s.valueReturnPct !== null && s.invested) items.push(measure('On today\'s value', pct(s.valueReturnPct), 'valued at ' + lkr(s.currentValue, true)));
    if (s.perSqft && (s.perSqft.cost || s.perSqft.income)) {
      const a = s.perSqft;
      items.push(measure('Per sq ft of ' + a.basis + ', a year', lkr(a.cost || a.income), (a.cost ? 'running cost' + (a.income ? ' · income ' + lkr(a.income) : '') : 'income') +
        ' · ' + Math.round(a.sqft).toLocaleString('en-US') + ' sq ft'));
    }
    if (s.prev) {
      const diff = s.net - s.prev.net;
      items.push(measure('Against last year', signed(diff), 'net; same months a year earlier ' + signed(s.prev.net), diff > 0 ? 'pos' : diff < 0 ? 'neg' : ''));
    }
    let html = items.length ? '<div class="fin-measures">' + items.join('') + '</div>' : '';
    const rec = s.recovery;
    if (rec) {
      const done = Math.max(0, Math.min(100, rec.pct));
      const text = rec.paidBack ? 'All ' + lkr(s.invested, true) + ' earned back.'
        : rec.recovered > 0 ? lkr(rec.recovered, true) + ' of ' + lkr(s.invested, true) + ' so far' +
          (rec.by ? ' · all back around ' + monthLabel(rec.by) + ' at the last year\'s pace' : '')
        : 'Nothing earned back yet: running costs so far are more than its income.';
      html += '<div class="fin-recover"><div class="fin-recover-head"><span>Capital earned back</span><b>' + esc(pct(Math.round(done))) + '</b></div>' +
        '<div class="fin-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + Math.round(done) + '"><i style="width:' + done.toFixed(1) + '%"></i></div>' +
        '<small>' + esc(text) + '</small></div>';
    }
    return html;
  }

  async function renderDrawer(property, host) {
    if (!hooks.can('finance.view')) return;
    const p = period();
    const box = document.createElement('section');
    box.className = 'detail-section fin-drawer';
    box.innerHTML = '<h3>Finance <span class="fin-period-tag">' + esc(p.label) + '</span></h3><p class="muted-inline">Loading…</p>';
    const after = $('.detail-actions', host);
    if (after && after.nextSibling) host.insertBefore(box, after.nextSibling); else host.appendChild(box);
    let data;
    try {
      data = await API.propertyFinance(property.id, { from: p.from, to: p.to });
    } catch (err) {
      box.remove();
      return;
    }
    const s = data.summary;
    const mayRecord = hooks.allowedOn('finance.create', property);
    const mayEdit = hooks.allowedOn('finance.edit', property);
    const list = data.entries.slice(0, 6);
    box.innerHTML = '<h3>Finance <span class="fin-period-tag">' + esc(p.label) + '</span>' + badge(s.status, true) + '</h3>' +
      '<div class="fin-mini">' +
        '<div><span>Income</span><b>' + esc(lkr(s.income, true)) + '</b></div>' +
        '<div><span>Running costs</span><b>' + esc(lkr(s.cost, true)) + '</b>' + (s.rent ? '<small>rent ' + esc(lkr(s.rent, true)) + '</small>' : '') + '</div>' +
        '<div class="' + (s.net < 0 ? 'neg' : s.net > 0 ? 'pos' : '') + '"><span>Net</span><b>' + esc(signed(s.net)) + '</b>' +
          (s.margin !== null ? '<small>' + s.margin + '% margin</small>' : '') + '</div>' +
      '</div>' +
      measuresHtml(s, data.benchmark) +
      trendHtml(data.trend) +
      (s.invested && s.returnPct === null ? '<p class="fin-capital">' + icon('landmark') + 'Capital invested <b>' + esc(lkr(s.invested)) + '</b></p>' : '') +
      (data.byCategory && data.byCategory.length ? '<div class="fin-drawer-cats">' + categoryHtml(data.byCategory, 4) + '</div>' : '') +
      (list.length ? '<ul class="fin-entries">' + list.map((e) => '<li data-entry="' + e.id + '" class="' + (mayEdit ? 'is-editable' : '') + '"' + (mayEdit ? ' tabindex="0"' : '') + '>' +
          '<span class="fin-dir ' + e.kind + '">' + icon(e.kind === 'income' ? 'fin-up' : e.kind === 'capital' ? 'landmark' : 'fin-down') + '</span>' +
          '<span class="fin-ename"><b>' + esc(e.category_label) + '</b><small>' + esc(rangeLabel(e.period_start, e.period_end)) +
            (e.months > 1 ? ' · ' + lkr(e.monthly) + '/month' : '') + (e.counterparty ? ' · ' + esc(e.counterparty) : '') + '</small></span>' +
          '<span class="fin-eamt ' + e.kind + '">' + (e.kind === 'income' ? '+' : '−') + esc(lkr(e.amount)) + '</span></li>').join('') + '</ul>' +
          (data.entries.length > list.length ? '<p class="muted-inline">' + (data.entries.length - list.length) + ' older entries</p>' : '')
        : '<p class="muted-inline fin-none">No income or costs recorded yet. Record the rent, running costs and what the property earns to see whether it pays its way.</p>') +
      '<div class="fin-drawer-actions">' +
        (mayRecord ? '<button type="button" class="btn btn-dark btn-sm" data-fin-new>' + icon('plus') + 'Record entry</button>' : '') +
        '<button type="button" class="btn btn-ghost btn-sm" data-fin-open>' + icon('chart') + 'Finance page</button></div>';
    Fx.countUp(box, '.fin-mini b');
    Fx.countUp(box, '.fin-m b');
    Charts.bindTooltips(box);
    Fx.draw(box);
    Fx.rise($('.fin-entries', box), 6);
    const entries = {};
    data.entries.forEach((e) => { entries[e.id] = e; });
    box.addEventListener('click', function (event) {
      if (event.target.closest('[data-fin-new]')) openEntry(property, null);
      else if (event.target.closest('[data-fin-open]')) hooks.openView('finance');
      else {
        const li = event.target.closest('li[data-entry].is-editable');
        if (li) openEntry(property, entries[li.dataset.entry]);
      }
    });
  }

  /* ---------- recording an entry ---------- */

  function kind() { const r = $('#fin-kind input:checked'); return r ? r.value : 'cost'; }

  function fillCategories(selected) {
    const k = kind(), sel = $('#fin-form select[name=category]');
    sel.innerHTML = ref.categories.filter((c) => c.kind === k).map((c) => '<option value="' + c.value + '"' +
      (c.value === selected ? ' selected' : '') + '>' + esc(c.label) + '</option>').join('');
    $('#fin-covers-row').hidden = k === 'capital';
  }

  function months() {
    const f = $('#fin-form');
    if (kind() === 'capital') return 1;
    return f.covers.value === 'custom' ? Math.max(1, parseInt(f.months.value, 10) || 1) : Number(f.covers.value);
  }

  function updateHint() {
    const f = $('#fin-form');
    const cat = ref.categories.filter((c) => c.value === f.category.value)[0];
    $('#fin-cat-hint').textContent = cat ? cat.hint : '';
    f.months.hidden = f.covers.value !== 'custom' || kind() === 'capital';
    const amount = parseFloat(String(f.amount.value).replace(/,/g, ''));
    const n = months(), start = f.period_start.value;
    let text = '';
    if (amount > 0 && start) {
      const end = addMonths(start, n - 1);
      text = kind() === 'capital'
        ? 'Counted as an investment in ' + monthLabel(start) + ', not as a running cost.'
        : (n > 1 ? lkr(amount / n) + ' a month, ' : '') + 'counted in ' + rangeLabel(start, end) + '.';
    }
    $('#fin-spread-hint').textContent = text;
  }

  function propertyOptions(selectedId) {
    const list = (app.properties || []).filter((p) => hooks.allowedOn('finance.create', p))
      .slice().sort((a, b) => a.name.localeCompare(b.name));
    return '<option value="">Choose a property…</option>' + list.map((p) => '<option value="' + p.id + '"' +
      (p.id === selectedId ? ' selected' : '') + '>' + esc(p.property_code + ' — ' + p.name) + '</option>').join('');
  }

  function openEntry(property, entry) {
    editing = entry;
    formProperty = property;
    const f = $('#fin-form');
    f.reset();
    $('#fin-form-error').hidden = true;
    $('#fin-modal-title').textContent = entry ? 'Edit entry' : 'Record income or a cost';
    const sel = f.property_id;
    sel.innerHTML = property ? '<option value="' + property.id + '">' + esc(property.property_code + ' — ' + property.name) + '</option>'
      : propertyOptions(null);
    sel.disabled = !!property;
    const k = entry ? entry.kind : 'cost';
    $$('#fin-kind input').forEach((r) => { r.checked = r.value === k; });
    fillCategories(entry ? entry.category : (k === 'cost' ? 'RENT' : null));
    const now = monthKey(new Date());
    f.period_start.value = entry ? entry.period_start : now;
    if (entry) {
      f.amount.value = entry.amount;
      const preset = ['1', '3', '6', '12'].indexOf(String(entry.months)) !== -1;
      f.covers.value = preset ? String(entry.months) : 'custom';
      f.months.value = entry.months;
      ['description', 'counterparty', 'reference_no', 'notes'].forEach((k2) => { f[k2].value = entry[k2] || ''; });
    }
    $('#btn-fin-delete').hidden = !(entry && hooks.allowedOn('finance.delete', property));
    updateHint();
    $('#finance-modal').hidden = false;
    (property ? f.amount : sel).focus();
  }

  function busy(button, text) {
    if (text) { button.dataset.idle = button.innerHTML; button.textContent = text; button.disabled = true; }
    else { button.innerHTML = button.dataset.idle || button.innerHTML; button.disabled = false; }
  }

  function showError(err) {
    const box = $('#fin-form-error');
    box.textContent = err.message;
    box.hidden = false;
    const field = err.field && $('#fin-form [name="' + err.field + '"]');
    if (field) field.focus();
  }

  async function saveEntry() {
    const f = $('#fin-form');
    const pid = Number(f.property_id.value);
    if (!pid) { showError({ message: 'Choose a property.', field: 'property_id' }); return; }
    const body = {
      kind: kind(), category: f.category.value, amount: f.amount.value, period_start: f.period_start.value,
      months: months(), description: f.description.value, counterparty: f.counterparty.value,
      reference_no: f.reference_no.value, notes: f.notes.value
    };
    const button = $('#btn-fin-save');
    busy(button, 'Saving…');
    try {
      if (editing) await API.updateFinance(editing.id, body);
      else await API.createFinance(pid, body);
      busy(button, null);
      $('#finance-modal').hidden = true;
      notify(editing ? 'Entry updated.' : 'Recorded.');
      afterChange();
    } catch (err) {
      busy(button, null);
      showError(err);
    }
  }

  async function deleteEntry() {
    if (!editing || !window.confirm('Remove this entry? The property\'s figures will no longer include it.')) return;
    try {
      await API.deleteFinance(editing.id);
      $('#finance-modal').hidden = true;
      notify('Entry removed.');
      afterChange();
    } catch (err) {
      showError(err);
    }
  }

  function afterChange() {
    if (app.view === 'finance') refresh();
    hooks.refreshDrawer && hooks.refreshDrawer();
  }

  return { init: init, show: show, refresh: refresh, renderDrawer: renderDrawer, openEntry: openEntry };
})();
