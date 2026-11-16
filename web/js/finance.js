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
    if (!arriving) return;
    arriving = false;
    Fx.rise($('#fin-kpis'));
    Fx.rise($('.fin-grid', page), 4);
    Fx.rise($('#fin-losers'), 5);
    Fx.rise($('#fin-rows'), 10);
    Fx.draw(page);
  }

  function renderKpis() {
    const t = report.totals, c = report.counts;
    const withFigures = report.properties.length - c.none;
    const invested = report.properties.reduce((s, r) => s + (r.invested || 0), 0);
    const cards = [
      ['fin-in', 'Income', lkr(t.income, true), t.income ? report.properties.filter((r) => r.income).length + ' properties earning' : 'None recorded'],
      ['fin-out', 'Running costs', lkr(t.cost, true), t.rent ? 'Rent ' + lkr(t.rent, true) + ' · ' + Math.round(t.rent / (t.cost || 1) * 100) + '% of costs' : 'No rent recorded'],
      ['fin-net', 'Net result', signed(t.net), t.margin === null ? (t.cost ? 'Costs with no income' : 'Nothing recorded yet') : t.margin + '% of income'],
      ['fin-loss', 'Losing money', String(c.loss), withFigures ? 'of ' + withFigures + ' with figures' + (c['cost-only'] ? ' · ' + c['cost-only'] + ' cost only' : '') : 'Record figures to see'],
      ['fin-cap', 'Capital invested', lkr(invested, true), t.capital ? lkr(t.capital, true) + ' in this period' : 'Purchases and building work']
    ];
    $('#fin-kpis').innerHTML = cards.map((k, i) => '<div class="fin-kpi ' + k[0] + (i === 2 ? ' ' + (t.net < 0 ? 'is-neg' : t.net > 0 ? 'is-pos' : '') : '') + '">' +
      '<span class="fin-kpi-label">' + esc(k[1]) + '</span><b>' + esc(k[2]) + '</b><small>' + esc(k[3]) + '</small></div>').join('');
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
    const losers = report.properties.filter((r) => r.net < 0).sort((a, b) => a.net - b.net).slice(0, 5);
    $('#fin-losers').innerHTML = losers.length
      ? losers.map((r) => '<li data-property="' + r.id + '" tabindex="0"><span class="swatch" style="background:' + esc(r.sbu_color) + '"></span>' +
          '<span class="fin-lname"><b>' + esc(r.name) + '</b><small>' + esc(r.property_code) +
          (r.rentShare ? ' · rent is ' + r.rentShare + '% of income' : r.status === 'cost-only' ? ' · no income recorded' : '') + '</small></span>' +
          '<span class="fin-lval">' + esc(signed(r.net)) + '</span></li>').join('')
      : '<li class="empty-li">No property is losing money in this period.</li>';
  }

  const SORTS = {
    'net-asc': (a, b) => a.net - b.net,
    'net-desc': (a, b) => b.net - a.net,
    income: (a, b) => b.income - a.income,
    cost: (a, b) => b.cost - a.cost,
    rent: (a, b) => (b.rentShare || 0) - (a.rentShare || 0),
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
        '<td class="num">' + (r.invested ? esc(lkr(r.invested, true)) + (r.paybackYears ? '<small>pays back in ' + r.paybackYears + ' yrs</small>' :
          r.returnPct !== null ? '<small>no return yet</small>' : '') : '<span class="dash">—</span>') + '</td>' +
        '<td class="row-actions"><span class="circle-btn sm" aria-hidden="true">' + icon('chevron') + '</span></td></tr>';
    }).join('');
    const empty = $('#fin-empty');
    empty.hidden = rows.length > 0;
    empty.textContent = report.properties.length ? 'No property matches this status.' : 'No properties match the filters.';
    $('#fin-hint').hidden = report.properties.some((r) => r.status !== 'none');
  }

  /* ---------- the property panel's Finance section ---------- */

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
      (s.invested ? '<p class="fin-capital">' + icon('landmark') + 'Capital invested <b>' + esc(lkr(s.invested)) + '</b>' +
        (s.paybackYears ? ' · pays back in about <b>' + s.paybackYears + ' years</b> at this rate' : '') + '</p>' : '') +
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
