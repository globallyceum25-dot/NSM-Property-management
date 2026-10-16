/* Dashboard charts: donut, gauge, horizontal bars and columns, as plain SVG/HTML.
 *
 * Built to the data-viz method the dashboard follows:
 *   - categorical hues come from one validated palette, assigned by entity in a
 *     fixed order (never by rank), so a filter never repaints a category;
 *   - thin marks, a 2px surface gap between touching marks, rounded data ends;
 *   - every value is also visible as text (legend or bar label), so the
 *     tooltip enhances but never gates;
 *   - text stays in text colours; identity comes from the swatch beside it.
 */
window.Charts = (function () {
  'use strict';

  // Colours are CSS custom properties, so a theme change recolours every chart
  // in place. Each mode has its own steps (styles.css), validated in this slot
  // order against that mode's card surface: light CVD dE 9.1 / normal 19.6 on
  // white; dark CVD dE 8.4 / normal 19.3, all >= 3:1, on #111e1d. Three light
  // slots sit under 3:1, which is why every donut legend prints its values.
  const SLOTS = ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)',
                 'var(--viz-4)', 'var(--viz-5)', 'var(--viz-6)'];
  const OTHER = 'var(--viz-other)';     // teal-tinted grey for "Other" and context
  const SERIES = 'var(--viz-series)';   // the logo teal: single-series bars and columns
  const STATUS = {
    critical: { fill: 'var(--viz-critical)', track: 'var(--viz-critical-track)' },
    warning:  { fill: 'var(--viz-warning)', track: 'var(--viz-warning-track)' },
    good:     { fill: 'var(--viz-good)', track: 'var(--viz-good-track)' }
  };

  const esc = (v) => Fmt.esc(v);
  const fmt = (n) => Fmt.num(n);

  function tipAttrs(label, value) {
    return ' tabindex="0" data-tip-label="' + esc(label) + '" data-tip-value="' + esc(value) + '"';
  }

  /* Cross-filtering. A chart given `dim` makes each keyed mark a filter
     control; `selected` (a list of keys) highlights the chosen marks and dims
     the rest, so the clicked chart keeps its context while the others filter. */
  function selectedSet(opts) {
    return (opts.selected || []).map(String);
  }

  function xfAttrs(opts, key) {
    if (!opts.dim || key === undefined || key === null) return '';
    const on = selectedSet(opts).indexOf(String(key)) !== -1;
    return ' data-xf-dim="' + esc(opts.dim) + '" data-xf-value="' + esc(key) + '"' +
      ' role="button" aria-pressed="' + on + '"';
  }

  function xfClass(opts, key) {
    if (!opts.dim || !selectedSet(opts).length || key === undefined || key === null) return '';
    return selectedSet(opts).indexOf(String(key)) !== -1 ? ' is-selected' : ' is-dimmed';
  }

  function wrapClass(opts) {
    return opts.dim ? ' is-filterable' + (selectedSet(opts).length ? ' has-selection' : '') : '';
  }

  /* ---------- donut: part-to-whole, at most six segments ---------- */

  // items: [{ label, value, color }] in their fixed slot order.
  function donut(opts) {
    const items = opts.items.filter((i) => i.value > 0);
    const total = items.reduce((s, i) => s + i.value, 0);
    const size = 172, cx = size / 2, cy = size / 2, r = 70, width = 22;
    const C = 2 * Math.PI * r;
    const gap = items.length > 1 ? 2 : 0;   // 2px surface gap between segments

    let offset = 0;
    const segments = items.map(function (item) {
      const len = item.value / total * C;
      const dash = Math.max(len - gap, 0.01);
      const pct = Math.round(item.value / total * 100);
      const seg = '<circle class="donut-seg' + xfClass(opts, item.key) + '" cx="' + cx + '" cy="' + cy + '" r="' + r + '" ' +
        'fill="none" style="stroke:' + item.color + '" stroke-width="' + width + '" ' +
        'stroke-dasharray="' + dash.toFixed(2) + ' ' + C.toFixed(2) + '" ' +
        'stroke-dashoffset="' + (-offset).toFixed(2) + '"' +
        tipAttrs(item.label, fmt(item.value) + ' · ' + pct + '%') + xfAttrs(opts, item.key) + '></circle>';
      offset += len;
      return seg;
    }).join('');

    const svg = total
      ? '<svg class="donut" viewBox="0 0 ' + size + ' ' + size + '" role="img" ' +
          'aria-label="' + esc(opts.ariaLabel || '') + '">' +
          '<g transform="rotate(-90 ' + cx + ' ' + cy + ')">' + segments + '</g>' +
          '<text x="' + cx + '" y="' + (cy - 2) + '" class="donut-total">' + fmt(total) + '</text>' +
          '<text x="' + cx + '" y="' + (cy + 18) + '" class="donut-caption">' + esc(opts.centerLabel || '') + '</text>' +
        '</svg>'
      : '<div class="chart-empty">' + esc(opts.emptyText || 'Nothing to show') + '</div>';

    // The legend is the always-visible twin of the chart: every value, in text.
    const legend = '<ul class="legend">' + opts.items.map(function (item) {
      const pct = total ? Math.round(item.value / total * 100) : 0;
      const cls = (item.value ? '' : 'is-zero') + xfClass(opts, item.value ? item.key : null);
      return '<li' + (cls.trim() ? ' class="' + cls.trim() + '"' : '') +
        (item.value ? xfAttrs(opts, item.key) + (opts.dim && item.key !== undefined ? ' tabindex="0"' : '') : '') + '>' +
        '<span class="swatch" style="background:' + item.color + '"></span>' +
        '<span class="legend-label">' + esc(item.label) + '</span>' +
        '<span class="legend-value">' + fmt(item.value) + '</span>' +
        '<span class="legend-pct">' + pct + '%</span></li>';
    }).join('') + '</ul>';

    return '<div class="donut-wrap' + wrapClass(opts) + '">' + svg + legend + '</div>';
  }

  /* ---------- gauge: one ratio against the whole ---------- */

  function gauge(opts) {
    const pct = Math.max(0, Math.min(100, opts.percent));
    const tone = STATUS[opts.status] || STATUS.good;
    const w = 240, h = 132, cx = w / 2, cy = 120, r = 96, stroke = 18;
    const point = (t) => [cx + r * Math.cos(t), cy - r * Math.sin(t)];
    const start = point(Math.PI);
    const end = point(0);
    const arc = (to) => 'M ' + start[0].toFixed(2) + ' ' + start[1].toFixed(2) +
      ' A ' + r + ' ' + r + ' 0 0 1 ' + to[0].toFixed(2) + ' ' + to[1].toFixed(2);
    const fillTo = point(Math.PI * (1 - pct / 100));

    return '<div class="gauge-wrap">' +
      '<svg class="gauge' + wrapClass(opts) + '" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + esc(opts.ariaLabel) + '">' +
        '<path class="gauge-track' + xfClass(opts, opts.trackKey) + '" d="' + arc(end) + '" fill="none" style="stroke:' + tone.track + '" stroke-width="' + stroke + '" stroke-linecap="round"' +
          (opts.trackTipLabel ? tipAttrs(opts.trackTipLabel, opts.trackTipValue) : '') + xfAttrs(opts, opts.trackKey) + '/>' +
        (pct > 0
          ? '<path class="gauge-fill' + xfClass(opts, opts.fillKey) + '" pathLength="100" d="' + arc(fillTo) + '" fill="none" style="stroke:' + tone.fill + '" ' +
              'stroke-width="' + stroke + '" stroke-linecap="round"' +
              tipAttrs(opts.tipLabel, opts.tipValue) + xfAttrs(opts, opts.fillKey) + '/>'
          : '') +
        '<text x="' + cx + '" y="' + (cy - 26) + '" class="gauge-value">' + Math.round(pct) + '%</text>' +
        '<text x="' + cx + '" y="' + (cy - 4) + '" class="gauge-caption">' + esc(opts.caption) + '</text>' +
      '</svg>' +
      // Status never rides on colour alone: icon + words.
      '<div class="gauge-status s-' + esc(opts.status) + '">' +
        '<svg class="ic"><use href="#i-' + (opts.status === 'good' ? 'verified' : 'shield') + '"/></svg>' +
        '<span><b>' + esc(opts.statusLabel) + '</b> ' + esc(opts.detail) + '</span>' +
      '</div>' +
    '</div>';
  }

  /* ---------- horizontal bars: compare magnitude across named items ---------- */

  // items: [{ label, value, display?, dot? }]; one series, one colour.
  function hbars(opts) {
    const items = opts.items;
    if (!items.length || !items.some((i) => i.value > 0)) {
      return '<div class="chart-empty">' + esc(opts.emptyText || 'Nothing to show') + '</div>';
    }
    const max = Math.max.apply(null, items.map((i) => i.value)) || 1;
    return '<div class="hbars' + (opts.className ? ' ' + opts.className : '') + wrapClass(opts) + '" role="list">' + items.map(function (item) {
      const width = item.value > 0 ? Math.max(1.5, item.value / max * 100) : 0;
      const shown = item.display !== undefined ? item.display : fmt(item.value);
      return '<div class="hbar-row' + xfClass(opts, item.key) + '"' + (opts.dim ? '' : ' role="listitem"') + tipAttrs(item.label, shown) +
        xfAttrs(opts, item.key) + '>' +
        '<span class="hbar-label">' +
          (item.dot ? '<span class="swatch round" style="background:' + esc(item.dot) + '"></span>' : '') +
          '<span>' + esc(item.label) + '</span></span>' +
        '<span class="hbar-track"><span class="hbar" style="width:' + width.toFixed(1) + '%;' +
          'background:' + (item.color || opts.color || SERIES) + '"></span>' +
          '<span class="hbar-value">' + esc(shown) + '</span></span>' +
      '</div>';
    }).join('') + '</div>';
  }

  /* ---------- columns: magnitude across an ordered or short axis ---------- */

  // items: [{ label, value, color?, note? }]
  function columns(opts) {
    const items = opts.items;
    const max = Math.max.apply(null, items.map((i) => i.value).concat([1]));
    const height = opts.height || 170;
    return '<div class="cols' + wrapClass(opts) + '" style="--plot:' + height + 'px">' + items.map(function (item) {
      const h = item.value > 0 ? Math.max(4, item.value / max * (height - 26)) : 0;
      return '<div class="col' + xfClass(opts, item.key) + '"' +
        tipAttrs(item.label, fmt(item.value) + (item.note ? ' · ' + item.note : '')) + xfAttrs(opts, item.key) + '>' +
        '<div class="col-plot">' +
          '<span class="col-value">' + fmt(item.value) + '</span>' +
          '<span class="col-bar" style="height:' + h.toFixed(1) + 'px;background:' +
            (item.color || opts.color || SERIES) + '"></span>' +
        '</div>' +
        '<span class="col-label">' + esc(item.label) + '</span>' +
      '</div>';
    }).join('') + '</div>';
  }

  /* ---------- the shared tooltip ---------- */

  let tip = null;

  function ensureTip() {
    if (tip) return tip;
    tip = document.createElement('div');
    tip.className = 'chart-tip';
    tip.hidden = true;
    tip.setAttribute('role', 'status');
    const value = document.createElement('strong');
    const label = document.createElement('span');
    const hint = document.createElement('em');
    tip.appendChild(value);
    tip.appendChild(label);
    tip.appendChild(hint);
    document.body.appendChild(tip);
    return tip;
  }

  function show(el, x, y) {
    const t = ensureTip();
    // Labels come from the database: set as text, never as markup.
    t.children[0].textContent = el.getAttribute('data-tip-value');
    t.children[1].textContent = el.getAttribute('data-tip-label');
    const dim = el.getAttribute('data-xf-dim');
    t.children[2].textContent = !dim ? ''
      : (el.getAttribute('aria-pressed') === 'true' ? 'Click to clear this filter' : 'Click to filter the dashboard');
    t.children[2].hidden = !dim;
    t.hidden = false;
    const box = t.getBoundingClientRect();
    const left = Math.min(window.innerWidth - box.width - 8, Math.max(8, x - box.width / 2));
    const top = y - box.height - 14 < 8 ? y + 18 : y - box.height - 14;
    t.style.left = left + 'px';
    t.style.top = top + 'px';
  }

  function hide() { if (tip) tip.hidden = true; }

  // One set of listeners for a container; charts inside can be re-rendered freely.
  function bindTooltips(container) {
    if (container.__chartTips) return;
    container.__chartTips = true;
    container.addEventListener('pointermove', function (event) {
      const el = event.target.closest('[data-tip-label]');
      if (el && container.contains(el)) show(el, event.clientX, event.clientY);
      else hide();
    });
    container.addEventListener('pointerleave', hide);
    container.addEventListener('focusin', function (event) {
      const el = event.target.closest('[data-tip-label]');
      if (!el) return;
      const r = el.getBoundingClientRect();
      show(el, r.left + r.width / 2, r.top);
    });
    container.addEventListener('focusout', hide);
    window.addEventListener('scroll', hide, true);
  }

  return {
    SLOTS: SLOTS, OTHER: OTHER, SERIES: SERIES, STATUS: STATUS, xfAttrs: xfAttrs, xfClass: xfClass,
    donut: donut, gauge: gauge, hbars: hbars, columns: columns,
    bindTooltips: bindTooltips
  };
})();
