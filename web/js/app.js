/* Application controller: state, rendering and event wiring. */
(function () {
  'use strict';

  function emptyFilters() {
    return { q: '', district: '', status: '', property_type: '',
             legal_entity_id: '', location_id: '', ownership_type: '', has_deed: '' };
  }

  const state = {
    reference: null,
    sbus: [],
    entities: [],
    locations: [],
    properties: [],
    stats: null,                 // /api/stats for the current filters
    docs: { status: '', type: '', sort: 'newest', fromModule: false, focus: null },
    sbuPage: { id: null, tab: 'properties' },   // one business unit's page
    currentDoc: null,            // document open in the document panel
    alerts: [],
    selectedSbus: null,          // null = all
    filters: emptyFilters(),
    labels: {},
    currentProperty: null,
    view: 'portfolio',
    mode: 'map',                 // portfolio layout: map | grid | table
    expanded: false,             // map mode with the card column hidden
    sort: 'newest'
  };

  // Cover heights as a share of their width.
  const CARD_R = 0.72;
  const DRAWER_R = 0.4;
  const MAPCARD_R = 1;

  const TENURE_SHORT = {
    FREEHOLD: 'Freehold', LEASEHOLD: 'Leasehold', RENTED_IN: 'Rented in',
    LEASED_OUT: 'Leased out', STATE_GRANT: 'State grant', OTHER: 'Other tenure'
  };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.prototype.slice.call(document.querySelectorAll(selector));
  const esc = (value) => Fmt.esc(value);
  const icon = (name) => '<svg class="ic"><use href="#i-' + name + '"/></svg>';

  /* ---------- small helpers ---------- */

  let toastTimer = null;
  function toast(message, isError) {
    const el = $('#toast');
    el.textContent = message;
    el.className = 'toast' + (isError ? ' error' : '');
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3000);
  }

  function labelFor(group, code) {
    const map = state.labels[group] || {};
    return map[code] || code || '';
  }

  // "Warehouse / stores" -> "Warehouse": card-sized labels.
  function shortLabel(group, code) {
    return labelFor(group, code).split(' / ')[0];
  }

  function fillSelect(select, options, opts) {
    opts = opts || {};
    select.innerHTML = '';
    if (opts.placeholder) {
      const blank = document.createElement('option');
      blank.value = '';
      blank.textContent = opts.placeholder;
      select.appendChild(blank);
    }
    options.forEach(function (option) {
      const el = document.createElement('option');
      el.value = option.value;
      el.textContent = option.label;
      select.appendChild(el);
    });
    if (opts.value !== undefined) select.value = opts.value;
  }

  function optionsFrom(list) {
    return list.map((x) => ({ value: x.value, label: x.label }));
  }

  // Avatar text: short codes as they are, longer ones cut to three (RETAIL -> RET).
  function initials(code) {
    const clean = String(code || '?').replace(/[^A-Za-z0-9]/g, '').toUpperCase();
    return clean.length <= 4 ? clean : clean.slice(0, 3);
  }

  // Units at reading size: "42.5 perches", "6.6 acres", "38,000 sq ft".
  const UNIT_SHORT = {
    PERCH: ['perch', 'perches'], ACRE: ['acre', 'acres'], ROOD: ['rood', 'roods'],
    HECTARE: ['hectare', 'hectares'], SQ_M: ['sq m', 'sq m'], SQ_FT: ['sq ft', 'sq ft']
  };

  function unitName(unit, value) {
    const names = UNIT_SHORT[unit] || [unit, unit];
    return Number(value) === 1 ? names[0] : names[1];
  }

  function sqftFor(value, unit) {
    const factor = (state.reference.sqftPerUnit || {})[unit || 'PERCH'];
    return value === null || value === undefined || value === '' || !factor ? null : Number(value) * factor;
  }

  // An area as entered, then in square feet: "6.6 acres · 287,496 sq ft".
  function areaText(value, unit, sqft) {
    if (value === null || value === undefined || value === '') return '';
    const entered = Fmt.num(value) + ' ' + unitName(unit, value);
    if (unit === 'SQ_FT') return entered;
    const inSqft = sqft !== null && sqft !== undefined ? sqft : sqftFor(value, unit);
    return entered + (inSqft !== null ? ' · ' + Fmt.num(Math.round(inSqft)) + ' sq ft' : '');
  }

  function toPerches(value, unit) {
    const n = Number(value) || 0;
    switch (unit) {
      case 'ACRE': return n * 160;
      case 'ROOD': return n * 40;
      case 'HECTARE': return n * 395.37;
      case 'SQ_M': return n * 0.0395369;
      case 'SQ_FT': return n / 272.25;
      default: return n;
    }
  }

  /* ---------- covers: an uploaded photograph, else a street map of the spot ---------- */

  function coverHtml(p, ratio) {
    const aspect = 'aspect-ratio: 100 / ' + (ratio * 100).toFixed(1);
    if (p.cover_document_id) {
      return '<div class="cover" style="' + aspect + '">' +
        '<img class="photo" src="/api/documents/' + p.cover_document_id + '/file" ' +
          'alt="Photograph of ' + esc(p.name) + '" loading="lazy"></div>';
    }

    // Four OpenStreetMap tiles around the property, positioned so its exact
    // coordinates sit in the visible frame, with the pin drawn on that point.
    const lat = Number(p.latitude);
    const lng = Number(p.longitude);
    const z = 16;
    const n = Math.pow(2, z);
    const xf = (lng + 180) / 360 * n;
    const rad = lat * Math.PI / 180;
    const yf = (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 * n;
    const x = Math.floor(xf);
    const y = Math.floor(yf);
    const x0 = (xf - x) < 0.5 ? x - 1 : x;
    const y0 = (yf - y) < 0.5 ? y - 1 : y;
    const px = (xf - x0) / 2;                 // point within the 2x2 mosaic, 0..1
    const py = (yf - y0) / 2;
    const offset = Math.min(0, Math.max(ratio - 1, ratio / 2 - py));  // in cover widths
    const top = offset / ratio * 100;
    const pinTop = (offset + py) / ratio * 100;
    const tiles = [[x0, y0], [x0 + 1, y0], [x0, y0 + 1], [x0 + 1, y0 + 1]]
      .map((t) => '<img src="https://tile.openstreetmap.org/' + z + '/' + t[0] + '/' + t[1] +
                  '.png" alt="" loading="lazy" draggable="false">').join('');

    return '<div class="cover" style="' + aspect + '" role="img" ' +
        'aria-label="Street map around ' + esc(p.name) + '">' +
      '<div class="mosaic" style="top:' + top.toFixed(2) + '%">' + tiles + '</div>' +
      '<span class="cover-pin" style="left:' + (px * 100).toFixed(2) + '%;top:' +
        pinTop.toFixed(2) + '%;--c:' + esc(p.sbu_color || '#00a69a') + '"></span>' +
    '</div>';
  }

  /* ---------- shared card fragments ---------- */

  function statusHtml(code) {
    return '<span class="status s-' + esc(code) + '"><i></i>' +
      esc(shortLabel('statuses', code)) + '</span>';
  }

  function verifiedHtml(p) {
    if (!p.has_deed) return '';
    return '<svg class="verified" role="img" aria-label="Deed or title on file">' +
      '<title>Deed or title on file</title><use href="#i-verified"/></svg>';
  }

  /* Every area in the portfolio reads in one unit, square feet; the unit it
     was recorded in stays one hover away. */
  function sqftShort(sqft) {
    if (sqft >= 1e6) return Fmt.num(sqft / 1e6, sqft >= 1e7 ? 1 : 2).replace(/\.?0+$/, '') + 'M sq ft';
    return Fmt.num(Math.round(sqft)) + ' sq ft';
  }

  function sqftCell(sqft, value, unit) {
    if (!sqft) return '<td class="num"><span class="muted-inline">—</span></td>';
    const recorded = unit && unit !== 'SQ_FT'
      ? ' title="Recorded as ' + esc(Fmt.num(value) + ' ' + unitName(unit, value)) + '"' : '';
    return '<td class="num"' + recorded + '>' + Fmt.num(Math.round(sqft)) + '</td>';
  }

  function areaFact(kind, sqft, value, unit) {
    const label = kind === 'land' ? 'Land' : 'Floor area';
    if (!sqft) return '<div><dt>' + label + '</dt><dd class="is-empty">—</dd></div>';
    const recorded = unit && unit !== 'SQ_FT'
      ? ' title="Recorded as ' + esc(Fmt.num(value) + ' ' + unitName(unit, value)) + '"' : '';
    return '<div' + recorded + '><dt>' + label + '</dt><dd>' + esc(sqftShort(sqft)) + '</dd></div>';
  }

  function specsHtml(p) {
    const docs = p.document_count;
    return '<div class="specs-wrap"><div class="specs">' +
      '<span>' + icon('home') + esc(shortLabel('propertyTypes', p.property_type)) + '</span>' +
      '<span' + (docs ? '' : ' class="none"') + '>' + icon('file') +
        (docs ? docs + (docs === 1 ? ' doc' : ' docs') : 'No docs') + '</span>' +
    '</div></div>' +
    // Both areas in one unit, side by side, so cards compare at a glance.
    '<dl class="area-facts">' +
      areaFact('land', p.extent_sqft, p.extent_value, p.extent_unit) +
      areaFact('floor', p.building_area_sqft, p.building_area_value, p.building_area_unit) +
    '</dl>';
  }

  function locationLine(p) {
    if (p.location_name) {
      return (p.location_code ? p.location_code + ' · ' : '') + p.location_name;
    }
    return p.city || p.district || 'No location set';
  }

  function addressLine(p) {
    return [p.address_line1, p.city, p.district].filter(Boolean).join(', ');
  }

  function footLine(p) {
    return [
      p.property_code,
      p.entity_code ? 'Owned by ' + p.entity_code : 'No group owner',
      TENURE_SHORT[p.ownership_type] || labelFor('ownershipTypes', p.ownership_type)
    ].join(' · ');
  }

  function cardHtml(p) {
    return '<article class="pcard" data-card="' + p.id + '" tabindex="0" ' +
        'aria-label="' + esc(p.property_code + ' — ' + p.name) + '">' +
      '<div class="pcard-media">' +
        coverHtml(p, CARD_R) +
        '<span class="media-badge" title="Documents on file">' + icon('file') +
          p.document_count + '</span>' +
        '<div class="media-overlay">' +
          '<span class="avatar" style="background:' + esc(p.sbu_color) + '">' +
            esc(initials(p.sbu_code)) + '</span>' +
          '<div class="ov-text">' +
            '<div class="ov-title">' + esc(p.sbu_name) + '</div>' +
            '<div class="ov-sub">' + icon('pin') + esc(locationLine(p)) + '</div>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="pcard-body">' +
        '<div class="pcard-row">' + statusHtml(p.status) +
          '<div class="pcard-actions">' +
            '<button class="circle-btn sm" data-locate="' + p.id + '" title="Show on map" ' +
              'aria-label="Show on map">' + icon('map') + '</button>' +
            '<button class="circle-btn sm" data-edit="' + p.id + '" title="Edit" ' +
              'aria-label="Edit property">' + icon('pencil') + '</button>' +
          '</div>' +
        '</div>' +
        '<h3 class="pcard-title">' + esc(p.name) + verifiedHtml(p) + '</h3>' +
        specsHtml(p) +
        (addressLine(p) ? '<p class="pcard-addr">' + esc(addressLine(p)) + '</p>' : '') +
        '<p class="pcard-foot">' + esc(footLine(p)) + '</p>' +
      '</div>' +
    '</article>';
  }

  function mapCardHtml(p) {
    return '<div class="mc-media">' + coverHtml(p, MAPCARD_R) + '</div>' +
      '<div class="mc-body">' +
        '<div class="pcard-row">' + statusHtml(p.status) +
          '<button class="circle-btn sm" data-card-close aria-label="Close">' + icon('x') + '</button>' +
        '</div>' +
        '<h3 class="mc-title" data-open="' + p.id + '">' + esc(p.name) + verifiedHtml(p) + '</h3>' +
        specsHtml(p) +
        '<p class="pcard-addr">' + esc(addressLine(p) || locationLine(p)) + '</p>' +
        '<div class="mc-actions">' +
          '<button class="btn btn-dark btn-sm" data-open="' + p.id + '">Open details</button>' +
          '<button class="btn btn-ghost btn-sm" data-edit="' + p.id + '">' + icon('pencil') + 'Edit</button>' +
        '</div>' +
      '</div>';
  }

  /* ---------- boot ---------- */

  async function boot() {
    try {
      state.reference = await API.reference();
    } catch (err) {
      toast('Could not reach the server: ' + err.message, true);
      return;
    }

    ['propertyTypes', 'ownershipTypes', 'statuses', 'extentUnits', 'documentTypes']
      .forEach(function (group) {
        state.labels[group] = {};
        state.reference[group].forEach((o) => { state.labels[group][o.value] = o.label; });
      });

    buildStaticSelects();
    window.__districts = state.reference.districts;   // used by the masters form
    Masters.init(toast, async function (key) {
      // Keep the filters and the property form in step with edits made in the
      // Master sheets module.
      if (key === 'location' || key === 'location_code') await refreshLocations();
      if (key === 'sbu') await refreshSbus();
      if (key === 'legal_entity') await refreshEntities();
      await refreshProperties();
    });
    MapView.init('map', state.reference, {
      cardHtml: mapCardHtml,
      onPick: pickCard,
      onHover: hoverCard
    });
    wireEvents();

    await refreshSbus();
    await refreshEntities();
    await refreshLocations();
    await refreshProperties();
    loadAlerts();

    applyHash();
    window.addEventListener('hashchange', applyHash);
  }

  /* ---------- links: #dashboard, #portfolio/grid, #property/12 ... ---------- */

  const VIEWS = ['portfolio', 'documents', 'dashboard', 'sbus', 'entities', 'masters'];
  const MODES = ['map', 'grid', 'table'];

  function writeHash() {
    let hash = state.view + (state.view === 'portfolio' && state.mode !== 'map' ? '/' + state.mode : '') +
      (state.view === 'documents' && state.docs.status ? '/' + state.docs.status : '');
    if (state.view === 'sbus' && state.sbuPage.id) {
      hash = 'sbus/' + state.sbuPage.id + (state.sbuPage.tab === 'documents' ? '/documents' : '');
    }
    if (state.currentDoc) hash = 'documents/doc/' + state.currentDoc.id;
    if (state.currentProperty) hash = 'property/' + state.currentProperty.id;
    if (location.hash !== '#' + hash) history.replaceState(null, '', '#' + hash);
  }

  function applyHash() {
    const parts = location.hash.replace(/^#/, '').split('/');
    if (parts[0] === 'property' && /^\d+$/.test(parts[1] || '')) {
      if (!state.currentProperty || String(state.currentProperty.id) !== parts[1]) {
        openDrawer(Number(parts[1]));
      }
      return;
    }
    if (parts[0] === 'documents' && parts[1] === 'doc' && /^\d+$/.test(parts[2] || '')) {
      if (!$('#drawer').hidden) closeDrawer();
      if (state.view !== 'documents') switchView('documents');
      if (!state.currentDoc || String(state.currentDoc.id) !== parts[2]) openDocPanel(Number(parts[2]));
      return;
    }
    if (VIEWS.indexOf(parts[0]) === -1) return;
    if (!$('#doc-drawer').hidden) closeDocPanel();
    if (parts[0] === 'sbus') {
      if (!$('#drawer').hidden) closeDrawer();
      if (/^\d+$/.test(parts[1] || '')) {
        openSbuPage(Number(parts[1]), parts[2] === 'documents' ? 'documents' : 'properties');
      } else {
        closeSbuPage();
        if (state.view !== 'sbus') switchView('sbus');
      }
      return;
    }
    if (parts[0] === 'portfolio') setMode(MODES.indexOf(parts[1]) !== -1 ? parts[1] : 'map');
    if (parts[0] === 'documents') {
      const status = DOC_STATUSES.indexOf(parts[1]) !== -1 ? parts[1] : '';
      if (status !== state.docs.status) {
        state.docs.status = status;
        if (state.view === 'documents') renderDocuments();
      }
    }
    if (!$('#drawer').hidden) closeDrawer();
    if (state.view !== parts[0]) switchView(parts[0]);
  }

  async function refreshLocations() {
    state.locations = await API.listLocations();
    const options = state.locations.map((l) => ({
      value: l.id,
      label: (l.code ? l.code + ' — ' : '') + l.name +
             (l.district ? ' (' + l.district + ')' : '')
    }));

    const filter = $('#filter-location');
    const keepFilter = filter.value;
    fillSelect(filter, options.concat([{ value: 'none', label: 'No location set' }]),
      { placeholder: 'All locations' });
    filter.value = keepFilter;

    const field = $('#property-form').location_id;
    const keepField = field.value;
    fillSelect(field, options, { placeholder: '— not set —' });
    field.value = keepField;
  }

  function buildStaticSelects() {
    const ref = state.reference;
    const districtOptions = ref.districts.map((d) => ({
      value: d.district, label: d.district + ' (' + d.province + ')'
    }));

    fillSelect($('#filter-district'), districtOptions, { placeholder: 'All districts' });
    fillSelect($('#filter-status'), optionsFrom(ref.statuses), { placeholder: 'Any status' });
    fillSelect($('#filter-type'), optionsFrom(ref.propertyTypes), { placeholder: 'Any type' });
    fillSelect($('#filter-tenure'), optionsFrom(ref.ownershipTypes), { placeholder: 'Any tenure' });

    const form = $('#property-form');
    fillSelect(form.status, optionsFrom(ref.statuses), { value: 'ACTIVE' });
    fillSelect(form.property_type, optionsFrom(ref.propertyTypes), { value: 'LAND' });
    fillSelect(form.ownership_type, optionsFrom(ref.ownershipTypes), { value: 'FREEHOLD' });
    fillSelect(form.extent_unit, optionsFrom(ref.extentUnits), { value: 'PERCH' });
    fillSelect(form.district, districtOptions, { placeholder: '—' });

    fillSelect($('#doc-form').doc_type, optionsFrom(ref.documentTypes), { value: 'DEED' });
    $('#doc-file-hint').textContent =
      'Optional. PDF, image, Word, Excel or ZIP, up to ' +
      Math.round(ref.maxUploadBytes / (1024 * 1024)) + ' MB. You can record the reference ' +
      'now and attach the scan later. A Photograph with an image file becomes the ' +
      'property’s cover picture.';
  }

  /* ---------- data ---------- */

  async function refreshSbus() {
    state.sbus = await API.listSbus();
    renderSbuFilters();
    renderSbuCards();
    const select = $('#property-form').sbu_id;
    const keep = select.value;
    fillSelect(select, state.sbus.map((s) => ({ value: s.id, label: s.code + ' — ' + s.name })),
      { placeholder: 'Select a business unit' });
    if (keep) select.value = keep;
  }

  async function refreshEntities() {
    state.entities = await API.listEntities();
    renderEntityCards();

    const options = state.entities.map((e) => ({
      value: e.id, label: e.short_code + ' — ' + e.name
    }));

    const filter = $('#filter-entity');
    const keepFilter = filter.value;
    fillSelect(filter, options.concat([{ value: 'none', label: 'Not recorded / leased in' }]),
      { placeholder: 'Any company' });
    filter.value = keepFilter;

    const field = $('#property-form').legal_entity_id;
    const keepField = field.value;
    fillSelect(field, options, { placeholder: '— none (leased / rented in) —' });
    field.value = keepField;
  }

  function activeFilters() {
    const filters = Object.assign({}, state.filters);
    if (state.selectedSbus && state.selectedSbus.length) {
      filters.sbu_id = state.selectedSbus.join(',');
    }
    return filters;
  }

  function registerTotal() {
    // The SBU list is never filtered, so its counts give the register total.
    return state.sbus.reduce((sum, s) => sum + s.property_count, 0);
  }

  // Every business unit switched off: nothing can match, so don't ask the
  // server (an empty sbu_id would mean "no filter" to it).
  function emptyStats() {
    return {
      totals: { properties: 0, sbus: 0, documents: 0, files: 0, without_deed: 0,
                allProperties: registerTotal() },
      bySbu: [], byStatus: [], byDistrict: [], byEntity: [], byTenure: [],
      expiringSoon: [], filtered: true
    };
  }

  async function refreshProperties() {
    if (state.selectedSbus && state.selectedSbus.length === 0) {
      state.properties = [];
      state.stats = emptyStats();
    } else {
      const filters = activeFilters();
      const results = await Promise.all([API.listProperties(filters), API.stats(filters)]);
      state.properties = results[0];
      state.stats = results[1];
    }
    renderKpis();
    renderCount();
    renderHeading();
    renderActiveChips();
    renderFilterBadge();
    renderCards();
    renderTable();
    renderLegend();
    MapView.render(state.properties);
    const shown = state.properties.length;
    $('#btn-filters-done').textContent =
      'Show ' + shown + (shown === 1 ? ' property' : ' properties');
    // The dashboard describes the same set, so keep it in step with the filters.
    if (state.view === 'dashboard') await renderDashboard();
    if (state.view === 'documents') await renderDocuments();
    if (state.view === 'sbus' && state.sbuPage.id) await renderSbuPage();
  }

  function sortedProperties() {
    const list = state.properties.slice();
    const byCode = (a, b) => String(a.property_code).localeCompare(String(b.property_code));
    switch (state.sort) {
      case 'code':
        return list.sort(byCode);
      case 'name':
        return list.sort((a, b) => String(a.name).localeCompare(String(b.name)));
      case 'extent':
        return list.sort((a, b) =>
          (b.extent_sqft || 0) - (a.extent_sqft || 0) ||
          byCode(a, b));
      case 'docs':
        return list.sort((a, b) => b.document_count - a.document_count || byCode(a, b));
      default:   // newest
        return list.sort((a, b) =>
          String(b.created_at).localeCompare(String(a.created_at)) || b.id - a.id);
    }
  }

  function resetFilters() {
    state.filters = emptyFilters();
    state.selectedSbus = null;
    $('#search').value = '';
    ['#filter-location', '#filter-entity', '#filter-district', '#filter-status',
     '#filter-type', '#filter-tenure'].forEach((sel) => { $(sel).value = ''; });
    syncTenureTabs();
    renderSbuFilters();
    return refreshProperties();
  }

  function setTenure(code) {
    state.filters.ownership_type = code || '';
    $('#filter-tenure').value = state.filters.ownership_type;
    syncTenureTabs();
    return refreshProperties();
  }

  function syncTenureTabs() {
    $$('#tenure-tabs button').forEach((b) =>
      b.classList.toggle('is-active', b.dataset.tenure === state.filters.ownership_type));
  }

  /* ---------- describing the active filters ---------- */

  // One entry per active filter, with how to clear it. Drives the chips under
  // the heading, the dashboard banner and the "N of M" wording.
  function activeChips() {
    const f = state.filters;
    const chips = [];
    const clearSelect = (key, selector) => () => {
      state.filters[key] = '';
      $(selector).value = '';
    };

    // `popover: false` marks filters that are not set from the filter popover,
    // so they do not count towards its badge.
    if (f.q) {
      chips.push({ label: 'Search: ' + f.q, popover: false,
                   clear: () => { state.filters.q = ''; $('#search').value = ''; } });
    }
    if (f.has_deed) {
      chips.push({ label: f.has_deed === '0' ? 'No deed or title on file' : 'Deed or title on file',
                   popover: false, clear: () => { state.filters.has_deed = ''; } });
    }
    if (state.selectedSbus) {
      const names = state.sbus
        .filter((s) => state.selectedSbus.indexOf(s.id) !== -1).map((s) => s.code);
      chips.push({
        label: names.length ? 'Business unit' + (names.length === 1 ? ': ' : 's: ') + names.join(', ')
                            : 'No business unit selected',
        clear: () => { state.selectedSbus = null; renderSbuFilters(); }
      });
    }
    if (f.ownership_type) {
      chips.push({ label: 'Tenure: ' + (TENURE_SHORT[f.ownership_type] || f.ownership_type),
                   clear: () => { state.filters.ownership_type = '';
                                  $('#filter-tenure').value = ''; syncTenureTabs(); } });
    }
    if (f.location_id) {
      const location = state.locations.filter((l) => String(l.id) === f.location_id)[0];
      chips.push({ label: 'Location: ' + (location ? location.name : 'not set'),
                   clear: clearSelect('location_id', '#filter-location') });
    }
    if (f.legal_entity_id) {
      const entity = state.entities.filter((e) => String(e.id) === f.legal_entity_id)[0];
      chips.push({ label: 'Owned by: ' + (entity ? entity.short_code : 'nobody recorded'),
                   clear: clearSelect('legal_entity_id', '#filter-entity') });
    }
    if (f.district) {
      chips.push({ label: 'District: ' + f.district, clear: clearSelect('district', '#filter-district') });
    }
    if (f.status) {
      chips.push({ label: 'Status: ' + shortLabel('statuses', f.status),
                   clear: clearSelect('status', '#filter-status') });
    }
    if (f.property_type) {
      chips.push({ label: 'Type: ' + shortLabel('propertyTypes', f.property_type),
                   clear: clearSelect('property_type', '#filter-type') });
    }
    return chips;
  }

  let currentChips = [];

  function renderActiveChips() {
    currentChips = activeChips();
    const host = $('#active-chips');
    host.hidden = currentChips.length === 0;
    host.innerHTML = currentChips.map((c, i) =>
      '<span class="fchip">' + esc(c.label) +
        '<button data-chip-clear="' + i + '" aria-label="Remove filter ' + esc(c.label) + '">' +
          icon('x') + '</button></span>').join('') +
      (currentChips.length ? '<button class="link-btn" data-chip-clear="all">Clear all</button>' : '');
  }

  function renderFilterBadge() {
    // Only filters set from the popover count towards its badge.
    const n = activeChips().filter((c) => c.popover !== false).length;
    const badge = $('#filter-count');
    badge.textContent = n;
    badge.hidden = n === 0;
  }

  function filterBannerHtml(stats) {
    const parts = activeChips().map((c) => c.label);
    if (!parts.length) return '';
    return '<div class="filter-banner">' +
      '<div><strong>Filtered view</strong> — ' + esc(parts.join(' · ')) + '. ' +
        'Every figure below covers these ' + stats.totals.properties +
        ' of ' + stats.totals.allProperties + ' properties.</div>' +
      '<button class="btn btn-ghost btn-sm" id="btn-clear-from-dashboard">Clear filters</button>' +
      '</div>';
  }

  /* ---------- filter popover ---------- */

  function renderSbuFilters() {
    const host = $('#sbu-filters');
    host.innerHTML = state.sbus.map(function (sbu) {
      const on = !state.selectedSbus || state.selectedSbus.indexOf(sbu.id) !== -1;
      return '<button type="button" class="chip ' + (on ? 'is-on' : 'is-off') + '" ' +
          'data-sbu-chip="' + sbu.id + '" aria-pressed="' + on + '">' +
        '<i style="background:' + esc(sbu.color) + '"></i>' +
        '<span>' + esc(sbu.name) + '</span><b>' + sbu.property_count + '</b></button>';
    }).join('');
  }

  function toggleSbu(id) {
    const all = state.sbus.map((s) => s.id);
    const selected = state.selectedSbus ? state.selectedSbus.slice() : all.slice();
    const at = selected.indexOf(id);
    if (at === -1) selected.push(id); else selected.splice(at, 1);
    state.selectedSbus = selected.length === all.length ? null : selected;
    renderSbuFilters();
    refreshProperties();
  }

  /* ---------- heading, counts, legend ---------- */

  function renderCount() {
    const shown = state.properties.length;
    const total = registerTotal();
    const filtered = activeChips().length > 0;

    $('#result-count').textContent = shown;
    $('#result-caption').textContent = filtered
      ? 'of ' + total + (total === 1 ? ' property' : ' properties')
      : (shown === 1 ? 'property' : 'properties') + ' in the register';
    $('#result-caption').classList.toggle('is-filtered', filtered);
  }

  /* ---------- summary strip ---------- */

  function pct(part, whole) {
    return whole ? Math.round(part / whole * 100) : 0;
  }

  function plural(n, one, many) {
    return n + ' ' + (n === 1 ? one : many);
  }

  // Owned vs leased or rented in: the split the blueprint's dashboard asks for.
  function tenureSplit(byTenure) {
    const count = {};
    (byTenure || []).forEach((t) => { count[t.ownership_type] = t.n; });
    const owned = (count.FREEHOLD || 0) + (count.LEASED_OUT || 0);
    const leased = (count.LEASEHOLD || 0) + (count.RENTED_IN || 0);
    const total = (byTenure || []).reduce((sum, t) => sum + t.n, 0);
    const other = total - owned - leased;
    if (!total) return 'None match the filters';
    return [owned ? owned + ' owned' : '', leased ? leased + ' leased' : '',
            other ? other + ' other' : '']
      .filter(Boolean).join(' · ');
  }

  // Every card is a shortcut: the arrow mark says so, the whole card is the target.
  function kpiHtml(opts) {
    return '<button type="button" class="kpi ' + opts.cls + (opts.active ? ' is-active' : '') + '" ' +
        'data-kpi="' + opts.action + '"' +
        (opts.pressed !== undefined ? ' aria-pressed="' + opts.pressed + '"' : '') +
        ' aria-label="' + esc(opts.label + ': ' + opts.value + '. ' + opts.go) + '"' +
        ' title="' + esc(opts.go) + '">' +
      '<div class="kpi-top"><span class="kpi-value">' + opts.value + '</span>' +
        '<span class="kpi-icon">' + icon(opts.icon) + '</span></div>' +
      '<div class="kpi-label"><span>' + esc(opts.label) + '</span>' +
        (opts.active
          ? '<span class="kpi-cta">Clear</span>'
          : '<span class="kpi-go" aria-hidden="true">' + icon('open') + '</span>') + '</div>' +
      '<div class="kpi-sub">' + opts.sub + '</div>' +
      (opts.bar !== undefined ? '<span class="kpi-bar"><i style="width:' + opts.bar + '%"></i></span>' : '') +
    '</button>';
  }

  function renderKpis() {
    const s = state.stats || emptyStats();
    const t = s.totals;
    const districts = s.byDistrict.length;
    const expiring = s.expiringSoon.length;
    const scanned = pct(t.files, t.documents);
    const missing = pct(t.without_deed, t.properties);
    const showingMissing = state.filters.has_deed === '0';
    // Nothing matches: say so once, rather than "no documents yet" etc., which
    // would read as an empty register.
    const none = t.properties === 0 && s.filtered;
    const sub = (text) => (none ? '—' : text);

    $('#kpi-strip').innerHTML = [
      kpiHtml({ cls: 'hero', icon: 'home', value: t.properties, label: 'Properties',
                action: 'properties', go: 'Open the property list',
                sub: esc(tenureSplit(s.byTenure)) }),
      kpiHtml({ cls: 't-units', icon: 'building', value: t.sbus, label: 'Business units',
                action: 'sbus', go: 'Open business units',
                sub: sub(districts ? 'across ' + plural(districts, 'district', 'districts') : 'No districts recorded') }),
      kpiHtml({ cls: 't-docs', icon: 'file', value: t.documents, label: 'Documents',
                action: 'documents', go: 'Open all documents',
                sub: sub(expiring ? '<b>' + expiring + ' expiring</b> within 180 days'
                                  : 'None expiring within 180 days') }),
      kpiHtml({ cls: 't-files', icon: 'paperclip', value: t.files, label: 'Files stored',
                action: 'files', go: 'Open the documents that have a stored file',
                sub: sub(t.documents ? scanned + '% of documents scanned' : 'No documents yet'),
                bar: scanned }),
      kpiHtml({ cls: 't-deed', icon: 'shield', value: t.without_deed, label: 'Without deed / title',
                action: 'deed', active: showingMissing, pressed: showingMissing,
                go: showingMissing ? 'Show every property again'
                                   : 'List the properties with no deed or title on file',
                sub: t.properties ? missing + '% of the portfolio' : '—',
                bar: missing })
    ].join('');
  }

  // Where each summary card leads.
  function goFromKpi(action) {
    if (action === 'deed') { toggleMissingDeeds(); return; }
    if (action === 'sbus') { switchView('sbus'); return; }
    if (action === 'documents' || action === 'files') {
      state.docs.status = action === 'files' ? 'file' : '';
      state.docs.type = '';
      switchView('documents');
      return;
    }
    if (action === 'properties') {
      if (state.view !== 'portfolio') switchView('portfolio');
      setMode('table');
      const table = $('#table-panel');
      if (table) table.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  function toggleMissingDeeds() {
    state.filters.has_deed = state.filters.has_deed === '0' ? '' : '0';
    refreshProperties();
  }

  function renderHeading() {
    const q = state.filters.q;
    $('#portfolio-title').textContent = q ? 'Results for “' + q + '”' : 'Property portfolio';
  }

  // Map legend doubles as a quick filter: click a unit to show only it.
  function renderLegend() {
    const counts = {};
    state.properties.forEach((p) => { counts[p.sbu_id] = (counts[p.sbu_id] || 0) + 1; });
    const solo = state.selectedSbus && state.selectedSbus.length === 1 ? state.selectedSbus[0] : null;
    $('#map-legend').innerHTML = state.sbus
      .filter((s) => counts[s.id])
      .map((s) => '<button class="legend-chip' + (solo === s.id ? ' is-solo' : '') + '" ' +
          'data-legend-sbu="' + s.id + '" title="' +
          (solo === s.id ? 'Show all business units' : 'Show only ' + esc(s.name)) + '">' +
        '<i style="background:' + esc(s.color) + '"></i>' + esc(s.name) +
        ' <b>' + counts[s.id] + '</b></button>')
      .join('');
  }

  /* ---------- cards ---------- */

  function renderCards() {
    const list = sortedProperties();
    const host = $('#property-cards');
    host.innerHTML = list.map(cardHtml).join('');
    $('#cards-empty').hidden = list.length > 0;

    $$('#property-cards .pcard').forEach(function (card) {
      const id = Number(card.dataset.card);
      card.addEventListener('mouseenter', () => MapView.highlight(id, true));
      card.addEventListener('mouseleave', () => MapView.highlight(id, false));
    });
  }

  function cardEl(id) {
    return $('#property-cards .pcard[data-card="' + id + '"]');
  }

  // A pin was clicked: mark its card and bring it into view.
  function pickCard(id) {
    $$('#property-cards .pcard.is-picked').forEach((c) => c.classList.remove('is-picked'));
    if (id === null) return;
    const card = cardEl(id);
    if (card) {
      card.classList.add('is-picked');
      card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  function hoverCard(id, on) {
    const card = cardEl(id);
    if (card) card.classList.toggle('is-hot', on);
  }

  /* ---------- property table ---------- */

  function renderTable() {
    const body = $('#property-rows');
    body.innerHTML = '';
    const list = sortedProperties();
    $('#list-empty').hidden = list.length > 0;

    list.forEach(function (p) {
      const tr = document.createElement('tr');
      tr.innerHTML =
        '<td class="code">' + esc(p.property_code) + '</td>' +
        '<td class="prop-cell"><span class="prop-name">' + esc(p.name) + verifiedHtml(p) + '</span>' +
          '<span class="prop-sub">' + esc([p.address_line1, p.city].filter(Boolean).join(', ')) + '</span></td>' +
        '<td><span class="sbu-pill"><span class="swatch" style="background:' +
          esc(p.sbu_color) + '"></span>' + esc(p.sbu_code) + '</span></td>' +
        '<td>' + (p.entity_code
          ? '<span title="' + esc(p.entity_name) + '">' + esc(p.entity_code) + '</span>'
          : '<span class="muted-inline" title="Leased or rented in — owned by an outside landlord">—</span>') + '</td>' +
        '<td title="' + esc(labelFor('propertyTypes', p.property_type)) + '">' +
          esc(shortLabel('propertyTypes', p.property_type)) + '</td>' +
        '<td>' + (p.location_name
          ? (p.location_code ? '<span class="loc-code">' + esc(p.location_code) +
              '</span> ' : '') + esc(p.location_name)
          : '<span class="muted-inline" title="No location from the master list">—</span>') +
          (p.district ? '<span class="prop-sub">' + esc(p.district) + ' district</span>' : '') + '</td>' +
        sqftCell(p.extent_sqft, p.extent_value, p.extent_unit) +
        sqftCell(p.building_area_sqft, p.building_area_value, p.building_area_unit) +
        '<td><span class="badge ' + esc(p.status) + '" title="' + esc(labelFor('statuses', p.status)) + '">' +
          esc(shortLabel('statuses', p.status)) + '</span></td>' +
        '<td class="doc-count' + (p.document_count ? '' : ' zero') + '">' + p.document_count + '</td>' +
        '<td class="coords">' + Fmt.coords(p.latitude, p.longitude) + '</td>' +
        '<td class="row-actions">' +
          '<button class="circle-btn sm" data-locate="' + p.id + '" title="Show on map" ' +
            'aria-label="Show on map">' + icon('map') + '</button>' +
          '<button class="circle-btn sm" data-open="' + p.id + '" title="Open details" ' +
            'aria-label="Open details">' + icon('open') + '</button>' +
        '</td>';
      tr.addEventListener('click', function (event) {
        if (event.target.closest('button')) return;
        openDrawer(p.id);
      });
      body.appendChild(tr);
    });
  }

  /* ---------- business units & owning companies ---------- */

  function tileHtml(opts) {
    const open = opts.openId
      ? ' data-sbu-open="' + opts.openId + '" role="link" tabindex="0" ' +
        'aria-label="Open ' + esc(opts.name) + ': properties and documents"'
      : '';
    return '<div class="tile' + (opts.openId ? ' is-link' : '') + '"' + open + '>' +
      '<div class="tile-top">' +
        '<span class="avatar lg" style="background:' + esc(opts.color) + '">' +
          esc(initials(opts.code)) + '</span>' +
        '<div class="tile-actions">' +
          '<button class="circle-btn sm" ' + opts.editAttr + ' title="Edit" aria-label="Edit">' +
            icon('pencil') + '</button>' +
          '<button class="circle-btn sm danger" ' + opts.deleteAttr + ' title="Delete" aria-label="Delete">' +
            icon('trash') + '</button>' +
        '</div>' +
      '</div>' +
      '<h3>' + esc(opts.name) + ' <span class="code">' + esc(opts.code) + '</span></h3>' +
      (opts.sub ? '<p class="tile-sub">' + esc(opts.sub) + '</p>' : '') +
      '<p class="tile-desc">' + esc(opts.description) + '</p>' +
      '<div class="tile-foot"><span><b>' + opts.count + '</b> propert' +
        (opts.count === 1 ? 'y' : 'ies') + '</span>' + (opts.badge || '') +
        (opts.openId ? '<span class="tile-open">Open' + icon('open') + '</span>' : '') + '</div>' +
    '</div>';
  }

  function renderSbuCards() {
    const host = $('#sbu-cards');
    if (!state.sbus.length) {
      host.innerHTML = '<p class="empty">No business units yet. Every property belongs to one, ' +
        'so add these first.</p>';
      return;
    }
    host.innerHTML = state.sbus.map((sbu) => tileHtml({
      color: sbu.color,
      code: sbu.code,
      name: sbu.name,
      sub: [sbu.sector, sbu.cost_centre ? 'CC ' + sbu.cost_centre : ''].filter(Boolean).join(' · '),
      description: sbu.description || 'No description.',
      count: sbu.property_count,
      openId: sbu.id,
      editAttr: 'data-edit-sbu="' + sbu.id + '"',
      deleteAttr: 'data-delete-sbu="' + sbu.id + '"'
    })).join('');
  }

  function renderEntityCards() {
    const host = $('#entity-cards');
    if (!state.entities.length) {
      host.innerHTML = '<p class="empty">No owning companies yet. Add the group ' +
        'companies that hold title to your properties.</p>';
      return;
    }
    host.innerHTML = state.entities.map((entity) => tileHtml({
      color: '#04524d',
      code: entity.short_code,
      name: entity.name,
      sub: entity.reg_no ? 'Reg. ' + entity.reg_no : '',
      description: entity.description || 'No notes.',
      count: entity.property_count,
      badge: entity.name === entity.short_code ? '<span class="warn-chip">Name unconfirmed</span>' : '',
      editAttr: 'data-edit-entity="' + entity.id + '"',
      deleteAttr: 'data-delete-entity="' + entity.id + '"'
    })).join('');
  }

  function openEntityModal(entityId) {
    const form = $('#entity-form');
    form.reset();
    $('#entity-form-error').hidden = true;
    const entity = entityId ? state.entities.filter((e) => e.id === entityId)[0] : null;
    $('#entity-modal-title').textContent = entity ? 'Edit owning company' : 'New owning company';
    form.id.value = entity ? entity.id : '';
    if (entity) {
      form.short_code.value = entity.short_code;
      form.name.value = entity.name;
      form.reg_no.value = entity.reg_no || '';
      form.description.value = entity.description || '';
      form.is_active.checked = !!entity.is_active;
    }
    $('#entity-modal').hidden = false;
    setTimeout(() => form.short_code.focus(), 50);
  }

  async function saveEntity() {
    const form = $('#entity-form');
    const errorBox = $('#entity-form-error');
    clearFieldErrors(form);
    errorBox.hidden = true;
    if (!checkRequired(form)) return;

    const data = collectForm(form);
    const id = form.id.value;
    delete data.id;
    const button = $('#btn-save-entity');
    setBusy(button, 'Saving…');
    try {
      if (id) await API.updateEntity(id, data);
      else await API.createEntity(data);
      $('#entity-modal').hidden = true;
      await refreshEntities();
      await refreshProperties();
      toast(id ? 'Owning company updated.' : 'Owning company added.');
    } catch (err) {
      showFormError(form, errorBox, err.message, err.field);
    } finally {
      setBusy(button, null);
    }
  }

  async function removeEntity(entityId) {
    const entity = state.entities.filter((e) => e.id === entityId)[0];
    if (!entity) return;
    if (!window.confirm('Delete owning company "' + entity.name + '"?')) return;
    try {
      await API.deleteEntity(entityId);
      await refreshEntities();
      await refreshProperties();
      toast('Owning company deleted.');
    } catch (err) { toast(err.message, true); }
  }

  /* ---------- alerts (bell) ---------- */

  // Always the whole register: an expiring lease matters whatever is filtered.
  async function loadAlerts() {
    try {
      const stats = await API.stats();
      state.alerts = stats.expiringSoon;
    } catch (err) {
      state.alerts = [];
    }
    const n = state.alerts.length;
    const badge = $('#alert-count');
    badge.textContent = n;
    badge.hidden = n === 0;
    $('#btn-alerts').setAttribute('aria-label',
      n ? n + ' document' + (n === 1 ? '' : 's') + ' expiring within 180 days'
        : 'No documents expiring soon');

    $('#alerts-pop').innerHTML =
      '<div class="pop-head"><h3>Expiring within 180 days</h3></div>' +
      (n
        ? '<ul class="alert-list">' + state.alerts.map(function (d) {
            const days = Fmt.daysUntil(d.expiry_date);
            return '<li data-open="' + d.property_id + '">' +
              '<span class="al-icon">' + icon('clock') + '</span>' +
              '<span class="al-text"><b>' + esc(d.title) + '</b>' +
                '<span>' + esc(d.property_code) + ' · ' + Fmt.date(d.expiry_date) + '</span></span>' +
              (days !== null ? '<span class="al-days">' + days + 'd</span>' : '') +
            '</li>';
          }).join('') + '</ul>'
        : '<p class="pop-empty">No leases, policies or permits expire in the next 180 days.</p>') +
      '<div class="pop-foot"><button class="btn btn-ghost btn-sm btn-block" data-go="dashboard">' +
        'Open the dashboard</button></div>';
  }

  /* ---------- popovers ---------- */

  const POPOVERS = [['#btn-filters', '#filter-pop'], ['#btn-alerts', '#alerts-pop'],
                    ['#btn-theme', '#theme-pop']];

  /* ---------- appearance: light, dark or follow the system ---------- */

  const THEME_KEY = 'pr-theme';
  const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

  function themeChoice() {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      return saved === 'light' || saved === 'dark' ? saved : 'system';
    } catch (e) { return 'system'; }
  }

  function isDark() {
    const choice = themeChoice();
    return choice === 'dark' || (choice === 'system' && systemDark.matches);
  }

  function applyTheme(choice, animate) {
    const root = document.documentElement;
    if (animate) {
      root.classList.add('theme-switching');
      setTimeout(() => root.classList.remove('theme-switching'), 320);
    }
    if (choice === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', choice);
    try {
      if (choice === 'system') localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, choice);
    } catch (e) { /* the choice still holds for this visit */ }
    $$('[data-theme-choice]').forEach((b) =>
      b.setAttribute('aria-checked', String(b.dataset.themeChoice === choice)));
    // The browser's own chrome follows the page.
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', isDark() ? '#0b1514' : '#ffffff');
    const label = 'Appearance: ' + (choice === 'system'
      ? 'System (' + (isDark() ? 'dark' : 'light') + ')' : choice.charAt(0).toUpperCase() + choice.slice(1));
    $('#btn-theme').setAttribute('aria-label', label);
    $('#btn-theme').title = label;
  }

  function wireTheme() {
    applyTheme(themeChoice(), false);
    $('#btn-theme').addEventListener('click', (e) => {
      e.stopPropagation(); togglePopover('#btn-theme', '#theme-pop');
    });
    $('#theme-pop').addEventListener('click', function (event) {
      event.stopPropagation();
      const option = event.target.closest('[data-theme-choice]');
      if (!option) return;
      applyTheme(option.dataset.themeChoice, true);
      closePopovers();
      $('#btn-theme').focus();
    });
    // With System chosen, follow the device as it changes (e.g. at sunset).
    systemDark.addEventListener('change', function () {
      if (themeChoice() === 'system') applyTheme('system', true);
    });
    // Shift+D toggles light and dark from anywhere outside a text field.
    document.addEventListener('keydown', function (event) {
      if (!event.shiftKey || event.key.toLowerCase() !== 'd' || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.target.closest('input, textarea, select, [contenteditable]')) return;
      applyTheme(isDark() ? 'light' : 'dark', true);
    });
  }

  function closePopovers() {
    POPOVERS.forEach(function (pair) {
      $(pair[1]).hidden = true;
      $(pair[0]).setAttribute('aria-expanded', 'false');
    });
  }

  function togglePopover(buttonSel, popSel) {
    const pop = $(popSel);
    const opening = pop.hidden;
    closePopovers();
    if (opening) {
      pop.hidden = false;
      $(buttonSel).setAttribute('aria-expanded', 'true');
    }
  }

  function anyPopoverOpen() {
    return POPOVERS.some((pair) => !$(pair[1]).hidden);
  }

  /* ---------- documents module ---------- */

  const DOC_STATUSES = ['file', 'nofile', 'expiring', 'expired'];
  let docsRequest = 0;

  function sbuTag(d) {
    return '<span class="sbu-tag" style="--c:' + esc(d.sbu_color || '#8c8c8c') + '" ' +
        'title="' + esc(d.sbu_code + ' — ' + d.sbu_name) + '">' +
      '<i></i><b>' + esc(d.sbu_code) + '</b><span>' + esc(d.sbu_name) + '</span></span>';
  }

  function expiryHtml(date) {
    const days = Fmt.daysUntil(date);
    if (days === null) return '<span class="muted-inline">No expiry</span>';
    if (days < 0) {
      return '<span class="exp-badge is-expired">Expired ' + esc(Fmt.date(date)) + '</span>';
    }
    if (days <= 90) {
      return '<span class="exp-badge is-soon">' + esc(Fmt.date(date)) + ' · ' + days + 'd</span>';
    }
    if (days <= 180) {
      return '<span class="exp-badge is-upcoming">' + esc(Fmt.date(date)) + ' · ' + days + 'd</span>';
    }
    return '<span>' + esc(Fmt.date(date)) + '</span>';
  }

  function docRowHtml(d) {
    const file = d.stored_name
      ? '<span class="file-line" title="' + esc(d.file_name) + '">' + icon('file') +
          '<span>' + esc(d.file_name) + '</span><small>' + esc(Fmt.fileSize(d.size_bytes)) + '</small></span>'
      : '<span class="file-line is-none">No file attached</span>';
    const fileButtons = d.stored_name
      ? '<a class="circle-btn sm" href="/api/documents/' + d.id + '/file" target="_blank" rel="noopener" ' +
          'title="View the file" aria-label="View ' + esc(d.file_name) + '">' + icon('open') + '</a>' +
        '<a class="circle-btn sm" href="/api/documents/' + d.id + '/file?disposition=attachment" ' +
          'title="Download the file" aria-label="Download ' + esc(d.file_name) + '">' + icon('download') + '</a>'
      : '';
    return '<tr data-doc-id="' + d.id + '" data-doc-property="' + d.property_id + '"' +
        (String(d.id) === String(state.docs.focus) ? ' class="is-focus"' : '') + '>' +
      '<td class="doc-cell">' +
        '<span class="doc-type ' + esc(d.doc_type) + '">' + esc(labelFor('documentTypes', d.doc_type)) + '</span>' +
        '<span class="doc-title">' + esc(d.title) + '</span>' +
        '<span class="only-narrow doc-sbu">' + sbuTag(d) + '</span>' +
        (d.reference_no ? '<span class="prop-sub">Ref ' + esc(d.reference_no) + '</span>' : '') +
        file +
      '</td>' +
      '<td>' + sbuTag(d) + '</td>' +
      '<td class="prop-cell"><span class="prop-name">' + esc(d.property_name) + '</span>' +
        '<span class="prop-sub">' + esc([d.property_code, d.location_name || d.city].filter(Boolean).join(' · ')) + '</span></td>' +
      '<td>' + (d.issue_date ? esc(Fmt.date(d.issue_date)) : '<span class="muted-inline">—</span>') + '</td>' +
      '<td>' + expiryHtml(d.expiry_date) + '</td>' +
      '<td class="wrap-cell">' + (d.counterparty ? esc(d.counterparty) : '<span class="muted-inline">—</span>') + '</td>' +
      '<td class="num">' + (d.amount ? esc(Fmt.money(d.amount, d.currency)) : '<span class="muted-inline">—</span>') + '</td>' +
      '<td class="row-actions">' + fileButtons +
        '<button class="circle-btn sm" data-open="' + d.property_id + '" title="Open the property" ' +
          'aria-label="Open ' + esc(d.property_name) + '">' + icon('home') + '</button>' +
      '</td></tr>';
  }

  async function renderDocuments() {
    const seq = ++docsRequest;
    let data;
    if (state.selectedSbus && state.selectedSbus.length === 0) {
      data = { documents: [], properties: 0,
               counts: { all: 0, file: 0, nofile: 0, expiring: 0, expired: 0 } };
    } else {
      try {
        data = await API.listDocuments(Object.assign({}, activeFilters(), {
          doc_status: state.docs.status, doc_type: state.docs.type, sort: state.docs.sort
        }));
      } catch (err) {
        toast('Could not load documents: ' + err.message, true);
        return;
      }
    }
    if (seq !== docsRequest) return;          // a newer request has taken over

    $$('#doc-tabs button').forEach(function (b) {
      const on = b.dataset.docStatus === state.docs.status;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-selected', on);
    });
    Object.keys(data.counts).forEach(function (key) {
      const el = $('#doc-tabs [data-count="' + key + '"]');
      if (el) el.textContent = data.counts[key];
    });
    $('#doc-type-filter').value = state.docs.type;
    $('#doc-sort').value = state.docs.sort;

    const rows = data.documents;
    const c = data.counts;
    $('#docs-summary').textContent = state.docs.status || state.docs.type
      ? 'Showing ' + rows.length + ' of ' + plural(c.all, 'document', 'documents') +
        ' · on ' + plural(data.properties, 'property', 'properties')
      : plural(c.all, 'document', 'documents') + ' across ' +
        plural(data.properties, 'property', 'properties') + ' · ' +
        plural(c.file, 'file', 'files') + ' stored';

    // The portfolio filters scope this list too; say so, and offer the way out.
    const chips = activeChips();
    const banner = $('#docs-banner');
    banner.hidden = !chips.length;
    if (chips.length) {
      banner.innerHTML = '<div><strong>Filtered</strong> — only documents of properties matching ' +
        esc(chips.map((x) => x.label).join(' · ')) + '.</div>' +
        '<button class="btn btn-ghost btn-sm" data-clear-filters>Clear filters</button>';
    }

    $('#doc-rows').innerHTML = rows.map(docRowHtml).join('');
    const focused = $('#doc-rows tr.is-focus');
    if (focused) focused.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const empty = $('#docs-empty');
    empty.hidden = rows.length > 0;
    empty.textContent = c.all
      ? 'No documents in this view. Try another tab or type.'
      : (chips.length ? 'No documents match the current filters.'
                      : 'No documents recorded yet. Use Attach document to add the first.');
  }

  /* ---------- dashboard charts ---------- */

  // Fixed slot per category, so a category keeps its colour whatever is
  // filtered (colour follows the entity, never its rank).
  const TENURE_SLOTS = ['FREEHOLD', 'LEASEHOLD', 'RENTED_IN', 'LEASED_OUT', 'STATE_GRANT'];
  const DOC_SLOTS = ['DEED', 'LEASE_AGREEMENT', 'TITLE_CERTIFICATE', 'SURVEY_PLAN',
                     'VALUATION_REPORT', 'INSURANCE_POLICY'];
  // Document types at legend size ("Rent / lease agreement" must not become "Rent").
  const DOC_SHORT = {
    DEED: 'Deed', LEASE_AGREEMENT: 'Lease / rent', TITLE_CERTIFICATE: 'Title certificate',
    SURVEY_PLAN: 'Survey plan', VALUATION_REPORT: 'Valuation', INSURANCE_POLICY: 'Insurance'
  };
  const RENEWAL_LABELS = {
    expired: 'Expired', m3: 'Within 3 mo', m6: '3–6 mo', m9: '6–9 mo', m12: '9–12 mo', later: 'Later'
  };

  function chartCard(opts) {
    return '<section class="chart-card span-' + opts.span + (opts.cls ? ' ' + opts.cls : '') + '">' +
      '<header class="chart-head"><div><h3>' + esc(opts.title) + '</h3>' +
        (opts.sub ? '<p class="chart-sub">' + esc(opts.sub) + '</p>' : '') + '</div>' +
        (opts.link
          ? '<button type="button" class="chart-link" data-dash-go="' + opts.link.go + '">' +
              esc(opts.link.label) + icon('open') + '</button>'
          : '') +
      '</header>' + opts.body + '</section>';
  }

  function sectionHead(title) {
    return '<div class="dash-section"><h2>' + esc(title) + '</h2></div>';
  }

  /* The dashboard opens on what needs doing: each signal is a shortcut to the
     list behind it, and its state is carried by icon and words, not colour alone. */
  function signalHtml(o) {
    return '<button type="button" class="signal s-' + o.tone + '" data-dash-go="' + o.go + '" ' +
        'aria-label="' + esc(o.value + ' ' + o.label + '. ' + o.sub + '. ' + o.hint) + '" title="' + esc(o.hint) + '">' +
      '<span class="sig-top"><span class="sig-icon">' + icon(o.icon) + '</span>' +
        '<span class="sig-go" aria-hidden="true">' + icon('open') + '</span></span>' +
      '<span class="sig-value">' + Fmt.num(o.value) + '</span>' +
      '<span class="sig-label">' + esc(o.label) + '</span>' +
      '<span class="sig-sub">' + esc(o.sub) + '</span>' +
    '</button>';
  }

  function dashHeroHtml(stats) {
    const t = stats.totals;
    const n = t.properties;
    const expired = (stats.renewals.filter((r) => r.bucket === 'expired')[0] || { n: 0 }).n;
    const due = stats.expiringSoon;
    const noFile = Math.max(0, t.documents - t.files);
    const missing = pct(t.without_deed, n);
    const today = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });

    const scope = stats.filtered
      ? 'A filtered view: ' + n + ' of ' + plural(t.allProperties, 'property', 'properties') +
        '. Every figure on this page follows the filters.'
      : plural(n, 'property', 'properties') + ' across ' +
        plural(t.sbus, 'business unit', 'business units') + ' and ' +
        plural(stats.byDistrict.length, 'district', 'districts') + ', holding ' +
        plural(t.documents, 'document', 'documents') + '.';

    const signals = [
      { go: 'deed', icon: t.without_deed ? 'shield' : 'verified', value: t.without_deed,
        tone: !n || !t.without_deed ? 'good' : (missing > 50 ? 'critical' : 'warning'),
        label: 'Without deed or title',
        sub: !n ? 'No properties' : (t.without_deed ? missing + '% of properties' : 'All covered'),
        hint: 'List the properties with no deed or title on file' },
      { go: 'expired', icon: 'clock', value: expired, tone: expired ? 'critical' : 'good',
        label: 'Expired documents',
        sub: expired ? 'Past their expiry date' : 'None past expiry',
        hint: 'Open the expired documents' },
      { go: 'expiring', icon: 'bell', value: due.length, tone: due.length ? 'warning' : 'good',
        label: 'Due within 180 days',
        sub: due.length ? 'Next on ' + Fmt.date(due[0].expiry_date) : 'Nothing due',
        hint: 'Open the documents expiring within 180 days' },
      { go: 'nofile', icon: 'paperclip', value: noFile, tone: noFile ? 'info' : 'good',
        label: 'Documents without a file',
        sub: t.documents ? pct(t.files, t.documents) + '% scanned' : 'No documents yet',
        hint: 'Open the documents that have no scan attached' }
    ];

    return '<section class="dash-hero">' +
      '<div class="dh-intro">' +
        '<p class="dh-eyebrow">As of ' + esc(today) + '</p>' +
        '<h1>Portfolio dashboard</h1>' +
        '<p class="dh-scope">' + esc(scope) + '</p>' +
      '</div>' +
      '<div class="dh-signals" role="group" aria-label="Needs attention">' +
        signals.map(signalHtml).join('') +
      '</div>' +
    '</section>';
  }

  // Leases, policies and permits coming up, soonest first: the renewal
  // pipeline's companion list.
  function upcomingHtml(stats) {
    const rows = stats.expiringSoon;
    if (!rows.length) {
      return '<div class="chart-empty">No leases, policies or permits expire in the next 180 days' +
        (stats.filtered ? ' among the filtered properties' : '') + '.</div>';
    }
    const shown = rows.slice(0, 5);
    return '<ul class="upcoming">' + shown.map(function (d) {
      const days = Fmt.daysUntil(d.expiry_date);
      const date = new Date(d.expiry_date + 'T00:00:00');
      return '<li data-open="' + d.property_id + '" tabindex="0" title="Expires ' + esc(Fmt.date(d.expiry_date)) + '">' +
        '<span class="up-date"><b>' + date.getDate() + '</b>' +
          '<span>' + esc(date.toLocaleDateString('en-GB', { month: 'short' })) + '</span></span>' +
        '<span class="up-text"><b>' + esc(d.title) + '</b>' +
          '<span><i class="swatch round" style="background:' + esc(d.sbu_color || '#8c8c8c') + '"></i>' +
            esc(d.property_code + ' · ' + d.property_name) + '</span></span>' +
        '<span class="exp-badge ' + (days <= 90 ? 'is-soon' : 'is-upcoming') + '">' +
          (days === 0 ? 'Today' : plural(days, 'day', 'days')) + '</span>' +
      '</li>';
    }).join('') + '</ul>' +
    (rows.length > shown.length
      ? '<p class="chart-foot">and ' + (rows.length - shown.length) + ' more in Documents</p>' : '');
  }

  function tenureDonut(stats) {
    const count = {};
    stats.byTenure.forEach((t) => { count[t.ownership_type] = t.n; });
    const items = TENURE_SLOTS.map((code, i) => ({
      label: TENURE_SHORT[code], value: count[code] || 0, color: Charts.SLOTS[i]
    }));
    if (count.OTHER) items.push({ label: 'Other tenure', value: count.OTHER, color: Charts.OTHER });
    return Charts.donut({ items: items, centerLabel: 'properties',
                          ariaLabel: 'Properties by tenure', emptyText: 'No properties match' });
  }

  function documentsDonut(stats) {
    const count = {};
    stats.byDocType.forEach((d) => { count[d.doc_type] = d.n; });
    let items = DOC_SLOTS
      .map((code, i) => ({ code: code, label: DOC_SHORT[code],
                           value: count[code] || 0, color: Charts.SLOTS[i] }))
      .filter((i) => i.value > 0);
    let other = Object.keys(count)
      .filter((code) => DOC_SLOTS.indexOf(code) === -1)
      .reduce((s, code) => s + count[code], 0);
    // At most six segments: past that, the smallest named type joins "Other".
    while (items.length + (other ? 1 : 0) > 6) {
      const smallest = items.reduce((a, b) => (b.value < a.value ? b : a));
      other += smallest.value;
      items = items.filter((i) => i !== smallest);
    }
    if (other) items.push({ label: 'Other documents', value: other, color: Charts.OTHER });
    return Charts.donut({ items: items, centerLabel: 'documents',
                          ariaLabel: 'Documents by type', emptyText: 'No documents recorded' });
  }

  function deedGauge(stats) {
    const n = stats.totals.properties;
    if (!n) return '<div class="chart-empty">No properties match</div>';
    const withDeed = n - stats.totals.without_deed;
    const pctCovered = withDeed / n * 100;
    const status = pctCovered >= 80 ? 'good' : (pctCovered >= 50 ? 'warning' : 'critical');
    return Charts.gauge({
      percent: pctCovered,
      status: status,
      statusLabel: { good: 'Good coverage.', warning: 'Partial coverage.', critical: 'Low coverage.' }[status],
      detail: stats.totals.without_deed
        ? plural(stats.totals.without_deed, 'property has', 'properties have') + ' no deed or title on file.'
        : 'Every property has a deed or title on file.',
      caption: 'with a deed or title',
      ariaLabel: Math.round(pctCovered) + '% of properties have a deed or title on file',
      tipLabel: 'Deed or title on file',
      tipValue: withDeed + ' of ' + plural(n, 'property', 'properties')
    });
  }

  function renewalColumns(stats) {
    const total = stats.renewals.reduce((s, r) => s + r.n, 0);
    if (!total) return '<div class="chart-empty">No documents carry an expiry date</div>';
    return Charts.columns({
      height: 220,
      items: stats.renewals.map((r) => ({
        label: RENEWAL_LABELS[r.bucket],
        value: r.n,
        // Expired is a status, shown by its label as well as its colour;
        // "later" is context beyond the reminder ladder, so it recedes.
        color: r.bucket === 'expired' ? Charts.STATUS.critical.fill
          : r.bucket === 'm3' ? Charts.STATUS.warning.fill
          : (r.bucket === 'later' ? Charts.OTHER : Charts.SERIES),
        note: r.bucket === 'later' ? 'beyond 12 months'
          : r.bucket === 'expired' ? 'past expiry'
          : r.bucket === 'm3' ? 'renewal due soon' : 'renewal due'
      }))
    });
  }

  function landBars(stats) {
    const withLand = stats.bySbu.filter((s) => s.extent_perches > 0);
    const total = withLand.reduce((sum, s) => sum + s.extent_perches, 0);
    const rows = withLand
      .sort((a, b) => b.extent_perches - a.extent_perches)
      .map(function (s) {
        const acres = s.extent_perches / 160;
        const share = s.extent_perches / total * 100;
        return { label: s.name, value: acres, dot: s.color,
                 display: Fmt.num(acres, acres < 10 ? 1 : 0) + ' ac · ' +
                   (share < 1 ? '<1' : Math.round(share)) + '%' };
      });
    const chart = Charts.hbars({ items: rows, className: 'wide-val', emptyText: stats.totals.properties
      ? 'No land extent recorded' : 'No properties match' });
    // The exact figures, in the unit the register records.
    const perches = stats.bySbu.filter((s) => s.extent_perches > 0)
      .map((s) => s.code + ' ' + Fmt.num(s.extent_perches, 1)).join(' · ');
    return chart + (perches ? '<p class="chart-foot">In perches: ' + esc(perches) + '</p>' : '');
  }

  function provinceColumns(stats) {
    const rows = stats.byProvince.slice()
      .sort((a, b) => b.n - a.n || a.province.localeCompare(b.province));
    // Nine columns need width; on a phone the same data reads better as bars.
    return '<div class="only-wide">' + Charts.columns({
        height: 220,
        items: rows.map((p) => ({ label: p.province, value: p.n, note: p.province + ' Province' }))
      }) + '</div>' +
      '<div class="only-narrow">' + Charts.hbars({
        items: rows.map((p) => ({ label: p.province, value: p.n }))
      }) + '</div>';
  }

  function typeBars(stats) {
    return Charts.hbars({
      items: stats.byType.map((t) => ({ label: shortLabel('propertyTypes', t.property_type), value: t.n })),
      emptyText: 'No properties match'
    });
  }

  function largestHoldings() {
    const ranked = state.properties
      .map((p) => ({ p: p, perches: toPerches(p.extent_value, p.extent_unit) }))
      .filter((x) => x.perches > 0)
      .sort((a, b) => b.perches - a.perches);
    if (!ranked.length) {
      return '<div class="chart-empty">' +
        (state.properties.length ? 'No land extent recorded' : 'No properties match') + '</div>';
    }
    const totalLand = ranked.reduce((s, x) => s + x.perches, 0);
    return '<ul class="holdings">' + ranked.slice(0, 5).map(function (x) {
      const acres = x.perches / 160;
      const share = Math.round(x.perches / totalLand * 100);
      return '<li data-open="' + x.p.id + '" tabindex="0">' +
        '<span class="lh-thumb">' + coverHtml(x.p, 0.78) + '</span>' +
        '<span class="lh-text"><b>' + esc(x.p.name) + '</b>' +
          '<span>' + esc(x.p.property_code) + ' · ' + esc(x.p.sbu_code) + '</span></span>' +
        '<span class="lh-figs"><b>' + Fmt.num(acres, acres < 10 ? 1 : 0) + ' ac</b>' +
          '<span class="lh-share">' + share + '% of land</span></span>' +
      '</li>';
    }).join('') + '</ul>';
  }

  function chartsHtml(stats) {
    return sectionHead('Portfolio at a glance') +
      '<div class="chart-grid">' +
        chartCard({ span: 4, title: 'Tenure mix', sub: 'How the properties are held',
                    body: tenureDonut(stats) }) +
        chartCard({ span: 4, title: 'Deed & title coverage', sub: 'Properties with a deed or title certificate on file',
                    body: deedGauge(stats) }) +
        chartCard({ span: 4, title: 'Documents by type', sub: 'Every document recorded against these properties',
                    body: documentsDonut(stats), link: { go: 'all', label: 'Documents' } }) +
      '</div>' +
      sectionHead('Renewals') +
      '<div class="chart-grid">' +
        chartCard({ span: 7, title: 'Renewal pipeline',
                    sub: 'Documents by expiry, on the 3 / 6 / 9 / 12-month reminder ladder',
                    body: renewalColumns(stats) }) +
        chartCard({ span: 5, title: 'Expiring within 180 days', sub: 'Soonest first · click to open the property',
                    body: upcomingHtml(stats), link: { go: 'expiring', label: 'View all' } }) +
      '</div>' +
      sectionHead('Land & location') +
      '<div class="chart-grid">' +
        chartCard({ span: 7, title: 'Land extent by business unit', sub: 'Acres and share of all land, largest first',
                    body: landBars(stats) }) +
        chartCard({ span: 5, title: 'Largest holdings', sub: 'By land extent · click to open',
                    body: largestHoldings(), link: { go: 'register', label: 'Register' } }) +
        chartCard({ span: 7, title: 'Properties by province', sub: 'All nine provinces, including any with none',
                    body: provinceColumns(stats) }) +
        chartCard({ span: 5, title: 'Property types', sub: 'Number of properties of each type',
                    body: typeBars(stats) }) +
      '</div>';
  }

  function breakdownBars(rows, labelKey, valueKey, colorFor, emptyNote) {
    if (!rows.length) return emptyNote;
    const max = Math.max.apply(null, rows.map((r) => r[valueKey]).concat([1]));
    return rows.map(function (row) {
      const width = Math.max(4, Math.round((row[valueKey] / max) * 100));
      return '<div class="bar-row">' +
        '<span class="label" title="' + esc(row[labelKey]) + '">' + esc(row[labelKey]) + '</span>' +
        '<span class="bar-track"><span class="bar-fill" style="width:' + width + '%;background:' +
          esc(colorFor(row)) + '"></span></span>' +
        '<span class="n">' + row[valueKey] + '</span>' +
      '</div>';
    }).join('');
  }

  function breakdownsHtml(stats) {
    // Under a filter an empty card means "nothing matched", not "nothing exists".
    const emptyNote = stats.filtered
      ? '<p class="muted">No properties match the current filters.</p>'
      : '<p class="muted">Nothing recorded yet.</p>';
    const series = () => Charts.SERIES;
    return sectionHead('Breakdowns') +
      '<div class="chart-grid breakdowns">' +
        chartCard({ span: 4, title: 'Properties by business unit', sub: 'In each unit’s map colour',
                    body: breakdownBars(stats.bySbu, 'name', 'property_count', (r) => r.color, emptyNote) }) +
        chartCard({ span: 4, title: 'Properties by owning company', sub: 'The group company holding title',
                    body: breakdownBars(stats.byEntity, 'short_code', 'n',
                      (r) => (r.short_code === 'Not recorded' ? Charts.OTHER : Charts.SERIES), emptyNote) }) +
        chartCard({ span: 4, title: 'By status', sub: 'How each property is being used',
                    body: breakdownBars(stats.byStatus.map((x) => ({ label: labelFor('statuses', x.status), n: x.n })),
                      'label', 'n', series, emptyNote) }) +
        chartCard({ span: 12, title: 'Properties by district', sub: 'Every district with at least one property',
                    body: '<div class="bar-cols">' +
                      breakdownBars(stats.byDistrict, 'district', 'n', series, emptyNote) + '</div>' }) +
      '</div>';
  }

  function goFromDashboard(action) {
    if (action === 'deed') {
      state.filters.has_deed = '0';
      switchView('portfolio');
      refreshProperties();
      return;
    }
    if (action === 'register') {
      switchView('portfolio');
      setMode('table');
      return;
    }
    state.docs.status = action === 'all' ? '' : action;
    state.docs.type = '';
    switchView('documents');
  }

  /* ---------- dashboard ---------- */

  async function renderDashboard() {
    const host = $('#dashboard');
    if (!host.innerHTML) host.innerHTML = '<p class="empty">Loading…</p>';
    // Same figures the Portfolio summary shows, already loaded for these filters.
    let stats = state.stats;
    if (!stats) {
      try {
        stats = await API.stats(activeFilters());
      } catch (err) {
        host.innerHTML = '<p class="empty">Could not load statistics: ' + esc(err.message) + '</p>';
        return;
      }
    }

    host.innerHTML =
      dashHeroHtml(stats) +
      filterBannerHtml(stats) +
      chartsHtml(stats) +
      breakdownsHtml(stats);

    if (!host.__dashGo) {
      host.__dashGo = true;
      host.addEventListener('click', function (event) {
        const target = event.target.closest('[data-dash-go]');
        if (target) goFromDashboard(target.dataset.dashGo);
      });
    }
    const clear = $('#btn-clear-from-dashboard');
    if (clear) clear.addEventListener('click', resetFilters);
    Charts.bindTooltips(host);
  }

  /* ---------- one business unit: its properties and documents ---------- */

  let sbuRequest = 0;

  function showSbuDetail(on) {
    $('#sbu-detail').hidden = !on;
    $('#sbu-index').hidden = on;
  }

  async function openSbuPage(id, tab) {
    const changed = state.sbuPage.id !== id;
    state.sbuPage = { id: id, tab: tab || 'properties' };
    if (state.view !== 'sbus') switchView('sbus');
    showSbuDetail(true);
    writeHash();
    if (changed) {
      $('#sbu-detail').innerHTML = '<p class="empty">Loading…</p>';
      $('#view-sbus').scrollTop = 0;
    }
    await renderSbuPage();
  }

  function closeSbuPage() {
    if (!state.sbuPage.id) return;
    state.sbuPage.id = null;
    showSbuDetail(false);
    writeHash();
  }

  function sbuStatHtml(value, label, tone) {
    return '<div class="sh-stat' + (tone ? ' is-' + tone : '') + '"><b>' + value + '</b>' +
      '<span>' + esc(label) + '</span></div>';
  }

  function sbuPropertyRow(p) {
    const place = [p.city, p.district].filter(Boolean).join(', ');
    return '<tr data-open="' + p.id + '" tabindex="0">' +
      '<td><div class="sp-cell"><span class="sp-thumb">' + coverHtml(p, 0.72) + '</span>' +
        '<span class="sp-text"><b>' + esc(p.name) + verifiedHtml(p) + '</b>' +
          '<span>' + esc(p.property_code) + '</span></span></div></td>' +
      '<td class="wrap-cell">' + esc(place) +
        (p.location_name ? '<span class="prop-sub">' + esc(p.location_name) + '</span>' : '') + '</td>' +
      '<td>' + esc(shortLabel('propertyTypes', p.property_type)) + '</td>' +
      '<td>' + esc(TENURE_SHORT[p.ownership_type] || labelFor('ownershipTypes', p.ownership_type)) + '</td>' +
      '<td><span class="badge ' + esc(p.status) + '">' + esc(shortLabel('statuses', p.status)) + '</span></td>' +
      '<td class="num">' + (p.document_count
        ? '<button class="count-chip" data-sbu-tab="documents" title="See this unit’s documents">' +
            icon('file') + p.document_count + '</button>'
        : '<span class="muted-inline">0</span>') + '</td>' +
      '<td class="row-actions">' +
        '<button class="circle-btn sm" data-locate="' + p.id + '" title="Show on map" aria-label="Show ' +
          esc(p.name) + ' on the map">' + icon('map') + '</button>' +
        '<button class="circle-btn sm" data-open="' + p.id + '" title="Open the property" aria-label="Open ' +
          esc(p.name) + '">' + icon('open') + '</button>' +
      '</td></tr>';
  }

  function sbuDocumentRow(d) {
    const file = d.stored_name
      ? '<span class="file-line">' + icon('file') + '<span>' + esc(d.file_name) + '</span>' +
          '<small>' + esc(Fmt.fileSize(d.size_bytes)) + '</small></span>'
      : '<span class="file-line is-none">No file attached</span>';
    return '<tr data-doc-go="' + d.id + '" tabindex="0" title="Open in the Documents module">' +
      '<td class="doc-cell">' +
        '<span class="doc-type ' + esc(d.doc_type) + '">' + esc(labelFor('documentTypes', d.doc_type)) + '</span>' +
        '<span class="doc-title">' + esc(d.title) + '</span>' +
        (d.reference_no ? '<span class="prop-sub">Ref ' + esc(d.reference_no) + '</span>' : '') + file +
      '</td>' +
      '<td class="prop-cell"><span class="prop-name">' + esc(d.property_name) + '</span>' +
        '<span class="prop-sub">' + esc(d.property_code) + '</span></td>' +
      '<td>' + (d.issue_date ? esc(Fmt.date(d.issue_date)) : '<span class="muted-inline">—</span>') + '</td>' +
      '<td>' + expiryHtml(d.expiry_date) + '</td>' +
      '<td class="num">' + (d.amount ? esc(Fmt.money(d.amount, d.currency)) : '<span class="muted-inline">—</span>') + '</td>' +
      '<td class="row-actions"><button class="go-btn" data-doc-go="' + d.id + '">' +
        '<span>Open in Documents</span>' + icon('open') + '</button></td>' +
    '</tr>';
  }

  async function renderSbuPage() {
    const id = state.sbuPage.id;
    const host = $('#sbu-detail');
    const sbu = state.sbus.filter((x) => x.id === id)[0];
    if (!sbu) {
      host.innerHTML = '<button class="crumb-back" data-sbu-back>' + icon('chevron') +
        'All business units</button><p class="empty">This business unit no longer exists.</p>';
      return;
    }
    const seq = ++sbuRequest;
    let props, docs, stats;
    try {
      const results = await Promise.all([
        API.listProperties({ sbu_id: id }),
        API.listDocuments({ sbu_id: id, sort: 'expiry' }),
        API.stats({ sbu_id: id })
      ]);
      props = results[0]; docs = results[1]; stats = results[2];
    } catch (err) {
      host.innerHTML = '<p class="empty">Could not load this business unit: ' + esc(err.message) + '</p>';
      return;
    }
    if (seq !== sbuRequest || state.sbuPage.id !== id) return;

    const t = stats.totals;
    const perches = (stats.bySbu.filter((x) => x.id === id)[0] || {}).extent_perches || 0;
    const acres = perches / 160;
    const expiring = stats.expiringSoon.length;
    const tab = state.sbuPage.tab;
    const meta = ['Business unit', sbu.code, sbu.sector, sbu.cost_centre ? 'Cost centre ' + sbu.cost_centre : '']
      .filter(Boolean).join(' · ');

    const head =
      '<nav class="crumbs" aria-label="Breadcrumb">' +
        '<button class="crumb-back" data-sbu-back>' + icon('chevron') + 'Business units</button>' +
        '<span aria-hidden="true">/</span><span aria-current="page">' + esc(sbu.name) + '</span>' +
      '</nav>' +
      '<section class="sbu-hero" style="--c:' + esc(sbu.color) + '">' +
        '<div class="sh-id">' +
          '<span class="avatar xl" style="background:' + esc(sbu.color) + '">' + esc(initials(sbu.code)) + '</span>' +
          '<div class="sh-text"><p class="sh-meta">' + esc(meta) + '</p>' +
            '<h1>' + esc(sbu.name) + '</h1>' +
            (sbu.description ? '<p class="sh-desc">' + esc(sbu.description) + '</p>' : '') + '</div>' +
        '</div>' +
        '<div class="sh-actions">' +
          '<button class="btn btn-ghost btn-sm" data-edit-sbu="' + id + '">' + icon('pencil') + 'Edit unit</button>' +
          '<button class="btn btn-dark btn-sm" data-sbu-map>' + icon('map') + 'Show on map</button>' +
        '</div>' +
        '<div class="sh-stats">' +
          sbuStatHtml(t.properties, t.properties === 1 ? 'Property' : 'Properties') +
          sbuStatHtml(t.documents, t.documents === 1 ? 'Document' : 'Documents') +
          sbuStatHtml(t.files, 'Files stored') +
          sbuStatHtml(acres ? Fmt.num(acres, acres < 10 ? 1 : 0) + '<small> ac</small>' : '—', 'Land') +
          sbuStatHtml(t.without_deed, 'Without deed / title', t.without_deed ? 'bad' : '') +
          sbuStatHtml(expiring, 'Due within 180 days', expiring ? 'warn' : '') +
        '</div>' +
      '</section>';

    const tabs =
      '<div class="docs-bar">' +
        '<div class="doc-tabs" role="tablist" aria-label="Show">' +
          '<button role="tab" data-sbu-tab="properties" class="' + (tab === 'properties' ? 'is-active' : '') + '" ' +
            'aria-selected="' + (tab === 'properties') + '">' + icon('building') + 'Properties <b>' + props.length + '</b></button>' +
          '<button role="tab" data-sbu-tab="documents" class="' + (tab === 'documents' ? 'is-active' : '') + '" ' +
            'aria-selected="' + (tab === 'documents') + '">' + icon('file') + 'Documents <b>' + docs.documents.length + '</b></button>' +
        '</div>' +
        (tab === 'properties'
          ? '<button class="chart-link" data-sbu-portfolio>Open in Portfolio' + icon('open') + '</button>'
          : '<button class="chart-link" data-sbu-docs>Open all in Documents' + icon('open') + '</button>') +
      '</div>';

    let body;
    if (tab === 'properties') {
      body = props.length
        ? '<div class="table-wrap sbu-table"><table class="grid sbu-grid"><thead><tr>' +
            '<th>Property</th><th>Location</th><th>Type</th><th>Tenure</th><th>Status</th>' +
            '<th class="num">Docs</th><th class="row-actions"><span class="sr-only">Actions</span></th>' +
          '</tr></thead><tbody>' + props.map(sbuPropertyRow).join('') + '</tbody></table></div>'
        : '<p class="empty">No properties in this business unit yet.</p>';
    } else {
      body = docs.documents.length
        ? '<div class="table-wrap sbu-table"><table class="grid sbu-grid docs-grid"><thead><tr>' +
            '<th>Document</th><th>Property</th><th>Issued</th><th>Expiry</th><th class="num">Amount</th>' +
            '<th class="row-actions"><span class="sr-only">Actions</span></th>' +
          '</tr></thead><tbody>' + docs.documents.map(sbuDocumentRow).join('') + '</tbody></table></div>' +
          '<p class="sbu-note">Soonest expiry first. Click a document to open it in the Documents module.</p>'
        : '<p class="empty">No documents recorded against this unit’s properties yet.</p>';
    }

    host.innerHTML = head + tabs + body;
  }

  function onSbuPageClick(event) {
    const t = event.target.closest('[data-sbu-back],[data-sbu-tab],[data-sbu-map],' +
      '[data-sbu-portfolio],[data-sbu-docs],[data-doc-go]');
    if (!t) return;
    const id = state.sbuPage.id;
    const d = t.dataset;
    if (d.sbuBack !== undefined) { closeSbuPage(); return; }
    if (d.sbuTab !== undefined) {
      event.stopPropagation();
      state.sbuPage.tab = d.sbuTab;
      writeHash();
      renderSbuPage();
      return;
    }
    if (d.docGo !== undefined) { goToDocument(Number(d.docGo)); return; }
    // The remaining shortcuts show this unit in another module, as a filter.
    state.selectedSbus = [id];
    renderSbuFilters();
    if (d.sbuMap !== undefined || d.sbuPortfolio !== undefined) {
      switchView('portfolio');
      setMode(d.sbuMap !== undefined ? 'map' : 'table');
    } else {
      state.docs.status = '';
      state.docs.type = '';
      switchView('documents');
    }
    refreshProperties();
  }

  /* ---------- one document: the document panel ---------- */

  function goToDocument(id) {
    state.docs.status = '';
    state.docs.type = '';
    state.docs.focus = id;
    if (state.view !== 'documents') switchView('documents');
    else renderDocuments();
    openDocPanel(id);
  }

  function markFocusRow() {
    $$('#doc-rows tr').forEach((tr) =>
      tr.classList.toggle('is-focus', String(tr.dataset.docId) === String(state.docs.focus)));
  }

  function docPreviewHtml(d) {
    const src = '/api/documents/' + d.id + '/file';
    if (!d.stored_name) {
      return '<div class="dd-preview is-empty">' + icon('paperclip') +
        '<p><b>No file attached</b>The reference is recorded; the scan can follow later.</p></div>';
    }
    const ext = extensionOf(d.file_name || '');
    if (IMAGE_TYPES.indexOf(ext) !== -1) {
      return '<div class="dd-preview"><img src="' + src + '" alt="' + esc(d.title) + '"></div>';
    }
    if (ext === '.pdf') {
      return '<div class="dd-preview is-pdf"><iframe src="' + src + '#view=FitH" title="' +
        esc(d.file_name) + '"></iframe></div>';
    }
    return '<div class="dd-preview is-empty">' + icon('file') +
      '<p><b>' + esc(d.file_name) + '</b>No preview for ' + esc(ext.slice(1).toUpperCase() || 'this') +
      ' files — download it to open.</p></div>';
  }

  function docPanelHtml(d) {
    const src = '/api/documents/' + d.id + '/file';
    const actions = (d.stored_name
        ? '<a class="btn btn-dark btn-sm" href="' + src + '" target="_blank" rel="noopener">' +
            icon('open') + 'View file</a>' +
          '<a class="btn btn-ghost btn-sm" href="' + src + '?disposition=attachment">' +
            icon('download') + 'Download</a>'
        : '') +
      '<button class="btn btn-ghost btn-sm" data-doc-property-open="' + d.property_id + '">' +
        icon('home') + 'Open property</button>';
    return '<header class="dd-head">' +
        '<span class="doc-type ' + esc(d.doc_type) + '">' + esc(labelFor('documentTypes', d.doc_type)) + '</span>' +
        '<h2>' + esc(d.title) + '</h2>' +
        '<div class="dd-sub">' + sbuTag(d) +
          (d.reference_no ? '<span>Ref ' + esc(d.reference_no) + '</span>' : '') + '</div>' +
      '</header>' +
      '<div class="dd-body">' +
        docPreviewHtml(d) +
        '<div class="detail-actions">' + actions + '</div>' +
        '<section class="detail-section"><h3>Details</h3><dl class="detail-grid">' +
          row('Property', '<a href="#" data-doc-property-open="' + d.property_id + '">' +
            esc(d.property_code + ' — ' + d.property_name) + '</a>') +
          row('Location', esc([d.location_name, d.city, d.district]
            .filter((v, i, all) => v && all.indexOf(v) === i).join(' · '))) +
          row('Issued', d.issue_date ? esc(Fmt.date(d.issue_date)) : '') +
          row('Expiry', expiryHtml(d.expiry_date)) +
          row('Counterparty', esc(d.counterparty)) +
          row('Amount', d.amount ? esc(Fmt.money(d.amount, d.currency)) : '') +
          row('File', d.stored_name ? esc(d.file_name) + ' · ' + esc(Fmt.fileSize(d.size_bytes)) : '') +
          row('Recorded', d.created_at ? esc(Fmt.date(String(d.created_at).slice(0, 10))) : '') +
          row('Notes', esc(d.notes)) +
        '</dl></section>' +
      '</div>';
  }

  async function openDocPanel(id) {
    let d;
    try {
      d = await API.getDocument(id);
    } catch (err) {
      toast(err.message, true);
      return;
    }
    if (!$('#drawer').hidden) closeDrawer();
    state.currentDoc = d;
    state.docs.focus = d.id;
    markFocusRow();
    $('#doc-drawer-body').innerHTML = docPanelHtml(d);
    $('#doc-drawer').hidden = false;
    $('#scrim').hidden = false;
    writeHash();
  }

  function closeDocPanel() {
    if ($('#doc-drawer').hidden) return;
    $('#doc-drawer').hidden = true;
    $('#doc-drawer-body').innerHTML = '';      // stops an embedded PDF
    if ($('#drawer').hidden) $('#scrim').hidden = true;
    state.currentDoc = null;
    state.docs.focus = null;
    markFocusRow();
    writeHash();
  }

  /* ---------- property drawer ---------- */

  async function openDrawer(propertyId) {
    let property;
    try {
      property = await API.getProperty(propertyId);
    } catch (err) {
      toast(err.message, true);
      return;
    }
    if (!$('#doc-drawer').hidden) closeDocPanel();
    state.currentProperty = property;
    closePopovers();

    $('#drawer-cover').innerHTML = coverHtml(property, DRAWER_R);
    $('#drawer-code').textContent = property.property_code + ' · ' +
      shortLabel('statuses', property.status);
    $('#drawer-name').innerHTML = esc(property.name) + verifiedHtml(property);
    $('#drawer-body').innerHTML = detailHtml(property);
    $('#drawer').hidden = false;
    $('#scrim').hidden = false;
    writeHash();
  }

  function closeDrawer() {
    const wasOpen = !$('#drawer').hidden;
    $('#drawer').hidden = true;
    $('#scrim').hidden = true;
    state.currentProperty = null;
    if (wasOpen) writeHash();
  }

  function row(label, value) {
    if (value === null || value === undefined || value === '') return '';
    return '<dt>' + esc(label) + '</dt><dd>' + value + '</dd>';
  }

  function detailHtml(p) {
    const address = [p.address_line1, p.address_line2, p.city, p.postal_code]
      .filter(Boolean).map(esc).join('<br>');

    return '<div class="detail-actions">' +
        '<button class="btn btn-dark btn-sm" data-edit="' + p.id + '">' + icon('pencil') + 'Edit property</button>' +
        '<button class="btn btn-ghost btn-sm" data-locate="' + p.id + '">' + icon('map') + 'Show on map</button>' +
        '<button class="btn btn-ghost btn-sm" data-add-doc="' + p.id + '">' + icon('plus') + 'Add document</button>' +
        '<button class="btn btn-danger btn-sm" data-delete="' + p.id + '">Delete</button>' +
      '</div>' +
      '<section class="detail-section"><h3>Classification</h3><dl class="detail-grid">' +
        row('Business unit', '<span class="sbu-pill"><span class="swatch" style="background:' +
            esc(p.sbu_color) + '"></span>' + esc(p.sbu_code + ' — ' + p.sbu_name) + '</span>') +
        row('Owned by', p.entity_code
            ? esc(p.entity_code + ' — ' + p.entity_name)
            : '<span class="muted-inline">No group company — leased or rented in</span>') +
        row('Sector', esc([p.sbu_sector, p.sbu_cost_centre ? 'CC ' + p.sbu_cost_centre : '']
            .filter(Boolean).join(' · '))) +
        row('Type', esc(labelFor('propertyTypes', p.property_type))) +
        row('Ownership', esc(labelFor('ownershipTypes', p.ownership_type))) +
        row('Status', '<span class="badge ' + esc(p.status) + '">' +
            esc(labelFor('statuses', p.status)) + '</span>') +
        row('Current use', esc(p.current_use)) +
      '</dl></section>' +

      '<section class="detail-section"><h3>Location</h3><dl class="detail-grid">' +
        row('Location', p.location_name
            ? (p.location_code ? '<span class="loc-code">' + esc(p.location_code) +
                '</span> ' : '') + esc(p.location_name)
            : '<span class="muted-inline">Not linked to the location master</span>') +
        row('Address', address) +
        row('District', esc(p.district)) +
        row('Province', esc(p.province)) +
        row('Coordinates', '<span style="font-variant-numeric:tabular-nums">' +
            Fmt.coords(p.latitude, p.longitude) + '</span>') +
      '</dl></section>' +

      '<section class="detail-section"><h3>Extent &amp; value</h3><dl class="detail-grid">' +
        row('Land extent', esc(areaText(p.extent_value, p.extent_unit, p.extent_sqft))) +
        row('Building area', esc(areaText(p.building_area_value, p.building_area_unit, p.building_area_sqft))) +
        row('Assessment no.', esc(p.assessment_no)) +
        row('Survey plan', esc([p.plan_no, p.lot_no ? 'Lot ' + p.lot_no : ''].filter(Boolean).join(' · '))) +
        row('Acquired', Fmt.date(p.acquisition_date)) +
        row('Acquisition cost', Fmt.money(p.acquisition_cost, p.currency)) +
        row('Current value', Fmt.money(p.current_value, p.currency)) +
      '</dl></section>' +

      (p.custodian || p.contact_phone || p.notes
        ? '<section class="detail-section"><h3>Custody</h3><dl class="detail-grid">' +
            row('Custodian', esc(p.custodian)) +
            row('Contact', esc(p.contact_phone)) +
            row('Notes', esc(p.notes)) +
          '</dl></section>'
        : '') +

      '<section class="detail-section"><h3>Documents (' + p.documents.length + ')</h3>' +
        documentsHtml(p.documents) +
      '</section>';
  }

  function documentsHtml(documents) {
    if (!documents.length) {
      return '<p class="muted">No deed, lease or other document recorded for this property yet.</p>';
    }
    return documents.map(function (d) {
      const days = Fmt.daysUntil(d.expiry_date);
      let expiryNote = '';
      if (d.expiry_date) {
        const cls = days < 0 ? 'expired' : (days <= 90 ? 'expiring' : '');
        const suffix = days < 0 ? ' (expired)' : (days <= 90 ? ' (' + days + ' days left)' : '');
        expiryNote = ' · expires <span class="' + cls + '">' + Fmt.date(d.expiry_date) + suffix + '</span>';
      }
      const meta = [
        d.reference_no ? 'Ref ' + esc(d.reference_no) : '',
        d.issue_date ? 'issued ' + Fmt.date(d.issue_date) : '',
        d.counterparty ? esc(d.counterparty) : '',
        d.amount ? Fmt.money(d.amount, d.currency) : ''
      ].filter(Boolean).join(' · ');

      const fileBits = d.stored_name
        ? '<a class="btn btn-ghost btn-sm" href="/api/documents/' + d.id + '/file" target="_blank" rel="noopener">' +
            icon('open') + 'View</a>' +
          '<a class="btn btn-ghost btn-sm" href="/api/documents/' + d.id + '/file?disposition=attachment">' +
            icon('download') + 'Download</a>' +
          '<span class="no-file">' + esc(d.file_name) + ' · ' + Fmt.fileSize(d.size_bytes) + '</span>'
        : '<span class="no-file">No file attached</span>';

      return '<div class="doc-item">' +
        '<div class="doc-top"><span class="doc-type ' + esc(d.doc_type) + '">' +
          esc(labelFor('documentTypes', d.doc_type)) + '</span>' +
          '<button class="btn btn-danger btn-sm" data-delete-doc="' + d.id + '">Remove</button></div>' +
        '<h4>' + esc(d.title) + '</h4>' +
        '<p class="doc-meta">' + meta + expiryNote + '</p>' +
        (d.notes ? '<p class="doc-meta">' + esc(d.notes) + '</p>' : '') +
        '<div class="doc-foot">' + fileBits + '</div>' +
      '</div>';
    }).join('');
  }

  /* ---------- property form ---------- */

  let pickerReady = false;

  function openPropertyModal(propertyId) {
    if (!state.sbus.length) {
      toast('Create a business unit first — every property belongs to one.', true);
      switchView('sbus');
      return;
    }
    closePopovers();
    const form = $('#property-form');
    form.reset();
    clearFieldErrors(form);
    $('#property-form-error').hidden = true;
    $('#coord-error').hidden = true;
    fillSelect(form.status, optionsFrom(state.reference.statuses), { value: 'ACTIVE' });
    fillSelect(form.property_type, optionsFrom(state.reference.propertyTypes), { value: 'LAND' });
    fillSelect(form.ownership_type, optionsFrom(state.reference.ownershipTypes), { value: 'FREEHOLD' });
    fillSelect(form.extent_unit, optionsFrom(state.reference.extentUnits), { value: 'PERCH' });
    fillSelect(form.building_area_unit, optionsFrom(state.reference.extentUnits), { value: 'PERCH' });
    form.currency.value = 'LKR';

    const source = propertyId
      ? state.properties.filter((p) => p.id === propertyId)[0] ||
        (state.currentProperty && state.currentProperty.id === propertyId ? state.currentProperty : null)
      : null;

    $('#property-modal-title').textContent = source ? 'Edit property' : 'New property';
    form.id.value = source ? source.id : '';

    if (source) {
      Object.keys(source).forEach(function (key) {
        const field = form.elements[key];
        if (field && field.type !== 'file' && key !== 'id') {
          field.value = source[key] === null ? '' : source[key];
        }
      });
      form.sbu_id.value = source.sbu_id;
      if (!source.building_area_unit) form.building_area_unit.value = form.extent_unit.value;
    }
    // The building unit follows the land unit until someone picks a different one.
    areaLink = !source || !source.building_area_value ||
      source.building_area_unit === source.extent_unit;
    updateAreas();

    $('#property-modal').hidden = false;

    if (!pickerReady) {
      MapView.initPicker('picker-map', state.reference, function (lat, lng) {
        form.latitude.value = lat.toFixed(6);
        form.longitude.value = lng.toFixed(6);
        validateCoords();
      });
      pickerReady = true;
    }
    MapView.invalidatePicker();
    MapView.clearPickerPoint();

    if (source && source.latitude) {
      MapView.setPickerPoint(Number(source.latitude), Number(source.longitude), true);
    } else {
      MapView.centerPicker(state.reference.mapCenter[0], state.reference.mapCenter[1],
                           state.reference.mapZoom - 1);
    }
    validateCoords();
    setTimeout(() => form.name.focus(), 50);
  }

  function validateCoords() {
    const form = $('#property-form');
    const error = $('#coord-error');
    const lat = parseFloat(form.latitude.value);
    const lng = parseFloat(form.longitude.value);
    const b = state.reference.bounds;

    if (!isFinite(lat) || !isFinite(lng)) { error.hidden = true; return false; }

    const inside = lat >= b.min_lat && lat <= b.max_lat && lng >= b.min_lng && lng <= b.max_lng;
    if (!inside) {
      const swapped = lng >= b.min_lat && lng <= b.max_lat && lat >= b.min_lng && lat <= b.max_lng;
      error.textContent = 'These coordinates are outside Sri Lanka.' +
        (swapped ? ' Latitude and longitude look swapped — latitude should be about 5.9–9.9.' : '');
      error.hidden = false;
      return false;
    }
    error.hidden = true;
    MapView.setPickerPoint(lat, lng, false);
    return true;
  }

  /* ---------- form helpers ---------- */

  // Read a number the way people type one: "1,250,000", "LKR 1,250,000",
  // "Rs. 420,000/=". Mirrors the server, so what passes here saves there.
  function parseNumber(raw) {
    const text = String(raw == null ? '' : raw).trim()
      .replace(/^(?:lkr|rs\.?|usd|us\$|\$)\s*/i, '')
      .replace(/\s*\/\s*[=-]\s*$/, '')
      .replace(/[,\s_]/g, '');
    if (text === '') return { ok: true, value: null };
    const value = Number(text);
    return isFinite(value) ? { ok: true, value: value } : { ok: false, value: null };
  }

  function collectForm(form, numericFields) {
    const data = {};
    Array.prototype.forEach.call(form.elements, function (field) {
      if (!field.name || field.type === 'file' || field.type === 'submit') return;
      if (field.type === 'checkbox') { data[field.name] = field.checked; return; }
      let value = field.value;
      if (typeof value === 'string') value = value.trim();
      if (numericFields && numericFields.indexOf(field.name) !== -1) {
        // Never silently drop a value: an unreadable one is sent as typed so
        // the server names the field (checkNumbers normally catches it first).
        const parsed = parseNumber(value);
        data[field.name] = parsed.ok ? parsed.value : value;
      } else {
        data[field.name] = value === '' ? null : value;
      }
    });
    return data;
  }

  function fieldLabel(field) {
    if (field.dataset && field.dataset.label) return field.dataset.label;
    const label = field.closest('label');
    const text = label ? label.firstChild && label.firstChild.textContent : field.name;
    return String(text || field.name).replace(/\*/g, '').trim();
  }

  // Required and malformed fields, reported inline like every other error
  // (the forms are novalidate, so the browser's pop-up bubbles never appear).
  function checkRequired(form) {
    const fields = Array.prototype.slice.call(form.elements);
    for (let i = 0; i < fields.length; i++) {
      const field = fields[i];
      if (!field.name || field.disabled || field.type === 'hidden' || field.checkValidity()) continue;
      const label = fieldLabel(field);
      const message = field.validity.valueMissing
        ? (field.tagName === 'SELECT' ? 'Choose ' : 'Enter ') +
          label.charAt(0).toLowerCase() + label.slice(1) + '.'
        : field.validationMessage;
      fieldError(form, field.name, message);
      return false;
    }
    return true;
  }

  // Flags the first numeric field that can't be read. Returns true if all are fine.
  function checkNumbers(form, names) {
    for (let i = 0; i < names.length; i++) {
      const field = form.elements[names[i]];
      if (field && !parseNumber(field.value).ok) {
        fieldError(form, names[i], fieldLabel(field) + ' must be a number, for example 1,250,000.');
        return false;
      }
    }
    return true;
  }

  function clearFieldErrors(form) {
    form.querySelectorAll('.is-invalid').forEach((el) => {
      el.classList.remove('is-invalid');
      el.removeAttribute('aria-invalid');
    });
    form.querySelectorAll('.field-msg').forEach((el) => el.remove());
  }

  // Put the message on the field itself, then bring it into view and focus it,
  // so a long form never looks as if its button did nothing.
  function fieldError(form, name, message) {
    const field = name && form.elements[name];
    if (!field || field.type === 'hidden') return false;
    field.classList.add('is-invalid');
    field.setAttribute('aria-invalid', 'true');
    const msg = document.createElement('span');
    msg.className = 'field-msg';
    msg.setAttribute('role', 'alert');
    msg.textContent = message;
    const host = field.closest('label') || field.closest('.field-block') || field.parentElement;
    host.appendChild(msg);
    field.scrollIntoView({ block: 'center', behavior: 'smooth' });
    field.focus({ preventScroll: true });
    return true;
  }

  function showFormError(form, box, message, fieldName) {
    clearFieldErrors(form);
    box.hidden = true;
    if (fieldError(form, fieldName, message)) return;
    box.textContent = message;
    box.hidden = false;
    box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  // Shows the button is working, and stops a double submit.
  function setBusy(button, busyText) {
    if (busyText) {
      button.dataset.idleText = button.textContent;
      button.textContent = busyText;
      button.disabled = true;
      button.classList.add('is-busy');
    } else {
      if (button.dataset.idleText) button.textContent = button.dataset.idleText;
      button.disabled = false;
      button.classList.remove('is-busy');
    }
  }

  const PROPERTY_NUMBERS = ['latitude', 'longitude', 'extent_value',
    'building_area_value', 'acquisition_cost', 'current_value'];

  /* ---------- areas: land and building, each also in square feet ---------- */

  let areaLink = true;    // building unit follows the land unit

  function rateText(unit) {
    const factor = (state.reference.sqftPerUnit || {})[unit];
    if (!factor || unit === 'SQ_FT') return 'Already in square feet.';
    return '1 ' + unitName(unit, 1) + ' = ' + Fmt.num(factor) + ' sq ft';
  }

  function derivedText(raw, unit) {
    const parsed = parseNumber(raw);
    if (!parsed.ok) return { text: 'Not a number', bad: true };
    if (parsed.value === null) return { text: '—', empty: true };
    if (parsed.value < 0) return { text: 'Cannot be negative', bad: true };
    return { text: Fmt.num(sqftFor(parsed.value, unit)) + ' sq ft' };
  }

  function paintDerived(el, result) {
    el.textContent = result.text;
    el.classList.toggle('is-bad', !!result.bad);
    el.classList.toggle('is-empty', !!result.empty);
  }

  function updateAreas() {
    const form = $('#property-form');
    const landUnit = form.extent_unit.value;
    const buildUnit = form.building_area_unit.value;
    paintDerived($('#extent-sqft'), derivedText(form.extent_value.value, landUnit));
    paintDerived($('#building-sqft'), derivedText(form.building_area_value.value, buildUnit));
    $('#extent-rate').textContent = rateText(landUnit);
    $('#building-rate').textContent = rateText(buildUnit);
    $('#building-unit-tag').textContent = '(' + unitName(buildUnit, 2) + ')';
    $('#building-link-hint').textContent = areaLink
      ? 'Follows the land unit — pick another to measure it differently.'
      : 'Measured in its own unit.';
  }

  async function saveProperty() {
    const form = $('#property-form');
    const errorBox = $('#property-form-error');
    clearFieldErrors(form);
    errorBox.hidden = true;

    if (!checkRequired(form)) return;
    if (!checkNumbers(form, PROPERTY_NUMBERS)) return;
    if (!validateCoords()) {
      const coord = $('#coord-error');
      if (coord.hidden) {
        showFormError(form, errorBox, 'Enter both latitude and longitude, or click the map to place the pin.', 'latitude');
      } else {
        coord.scrollIntoView({ block: 'center', behavior: 'smooth' });
        form.latitude.focus({ preventScroll: true });
      }
      return;
    }

    const data = collectForm(form, PROPERTY_NUMBERS.concat(['sbu_id']));
    const id = form.id.value;
    delete data.id;

    const button = $('#btn-save-property');
    setBusy(button, 'Saving…');
    try {
      const saved = id ? await API.updateProperty(id, data) : await API.createProperty(data);
      $('#property-modal').hidden = true;
      await refreshSbus();
      await refreshProperties();
      toast(id ? 'Property updated.' : 'Property ' + saved.property_code + ' added.');
      if (!id || (state.currentProperty && String(state.currentProperty.id) === String(id))) {
        openDrawer(saved.id);
      }
      if (state.view === 'portfolio' && state.mode === 'map') MapView.focus(saved.id);
    } catch (err) {
      showFormError(form, errorBox, err.message, err.field);
    } finally {
      setBusy(button, null);
    }
  }

  /* ---------- SBU form ---------- */

  function openSbuModal(sbuId) {
    const form = $('#sbu-form');
    form.reset();
    $('#sbu-form-error').hidden = true;
    const sbu = sbuId ? state.sbus.filter((s) => s.id === sbuId)[0] : null;
    $('#sbu-modal-title').textContent = sbu ? 'Edit business unit' : 'New business unit';
    form.id.value = sbu ? sbu.id : '';
    if (sbu) {
      form.code.value = sbu.code;
      form.name.value = sbu.name;
      form.sector.value = sbu.sector || '';
      form.cost_centre.value = sbu.cost_centre || '';
      form.description.value = sbu.description || '';
      form.color.value = sbu.color;
      form.is_active.checked = !!sbu.is_active;
    } else {
      const used = state.sbus.map((s) => s.color);
      const next = state.reference.colors.filter((c) => used.indexOf(c) === -1)[0];
      form.color.value = next || state.reference.colors[0];
    }
    $('#sbu-modal').hidden = false;
    setTimeout(() => form.code.focus(), 50);
  }

  async function saveSbu() {
    const form = $('#sbu-form');
    const errorBox = $('#sbu-form-error');
    clearFieldErrors(form);
    errorBox.hidden = true;
    if (!checkRequired(form)) return;

    const data = collectForm(form);
    const id = form.id.value;
    delete data.id;

    const button = $('#btn-save-sbu');
    setBusy(button, 'Saving…');
    try {
      if (id) await API.updateSbu(id, data);
      else await API.createSbu(data);
      $('#sbu-modal').hidden = true;
      await refreshSbus();
      await refreshProperties();
      toast(id ? 'Business unit updated.' : 'Business unit added.');
    } catch (err) {
      showFormError(form, errorBox, err.message, err.field);
    } finally {
      setBusy(button, null);
    }
  }

  /* ---------- document form ---------- */

  // With a property id the document goes on that property; without one (from
  // the Documents module) the form asks which property it belongs to.
  async function openDocModal(propertyId) {
    const form = $('#doc-form');
    form.reset();
    clearFieldErrors(form);
    $('#doc-form-error').hidden = true;
    fillSelect(form.doc_type, optionsFrom(state.reference.documentTypes), { value: 'DEED' });
    form.property_id.value = propertyId || '';
    state.docs.fromModule = !propertyId;

    const row = $('#doc-property-row');
    const pick = form.property_pick;
    row.hidden = !!propertyId;
    pick.disabled = !!propertyId;
    if (!propertyId) {
      let list;
      try {
        list = (await API.listProperties({})) || [];
      } catch (err) {
        toast('Could not load properties: ' + err.message, true);
        return;
      }
      list.sort((a, b) => String(a.property_code).localeCompare(String(b.property_code)));
      fillSelect(pick, list.map((p) => ({
        value: p.id,
        label: p.property_code + ' — ' + p.name + (p.sbu_code ? '  (' + p.sbu_code + ')' : '')
      })), { placeholder: 'Choose a property…', value: '' });
    }

    renderFileState();
    $('#doc-modal').hidden = false;
    setTimeout(() => (propertyId ? form.doc_type : pick).focus(), 50);
  }

  async function saveDocument() {
    const form = $('#doc-form');
    const errorBox = $('#doc-form-error');
    clearFieldErrors(form);
    errorBox.hidden = true;
    if (!checkRequired(form)) return;
    if (!checkNumbers(form, ['amount'])) return;

    const issue = form.issue_date.value;
    const expiry = form.expiry_date.value;
    if (issue && expiry && expiry < issue) {
      fieldError(form, 'expiry_date', 'Expiry date cannot be before the issue date.');
      return;
    }

    const file = form.elements.file.files[0];
    const fileProblem = file ? checkFile(file) : null;
    if (fileProblem) {
      fieldError(form, 'file', fileProblem);
      return;
    }

    const propertyId = form.property_id.value || form.property_pick.value;
    const formData = new FormData();
    ['doc_type', 'title', 'reference_no', 'issue_date', 'expiry_date',
     'counterparty', 'notes'].forEach(function (name) {
      const value = (form.elements[name].value || '').trim();
      if (value) formData.append(name, value);
    });
    const amount = parseNumber(form.amount.value);
    if (amount.value !== null) formData.append('amount', String(amount.value));
    if (file) formData.append('file', file, file.name);

    const button = $('#btn-save-doc');
    setBusy(button, file ? 'Uploading…' : 'Saving…');
    try {
      await API.addDocument(propertyId, formData);
      $('#doc-modal').hidden = true;
      // From the Documents module, stay on the list; elsewhere show the property.
      if (!state.docs.fromModule) await openDrawer(propertyId);
      await refreshProperties();
      loadAlerts();
      toast(file ? 'Document and file attached.' : 'Document recorded.');
    } catch (err) {
      showFormError(form, errorBox, err.message, err.field);
    } finally {
      setBusy(button, null);
    }
  }

  /* ---------- the file drop zone ---------- */

  const IMAGE_TYPES = ['.jpg', '.jpeg', '.png', '.gif', '.webp'];

  function extensionOf(name) {
    const dot = name.lastIndexOf('.');
    return dot === -1 ? '' : name.slice(dot).toLowerCase();
  }

  // Returns a reason the file can't be uploaded, or null.
  function checkFile(file) {
    const ext = extensionOf(file.name);
    const allowed = state.reference.allowedExtensions || [];
    if (allowed.length && allowed.indexOf(ext) === -1) {
      return (ext ? ext.slice(1).toUpperCase() + ' files' : 'Files without an extension') +
        ' can\u2019t be attached. Use PDF, an image, Word, Excel or ZIP.';
    }
    if (file.size > state.reference.maxUploadBytes) {
      return 'That file is ' + Fmt.fileSize(file.size) + '; the limit is ' +
        Fmt.fileSize(state.reference.maxUploadBytes) + '.';
    }
    if (file.size === 0) return 'That file is empty.';
    return null;
  }

  function renderFileState() {
    const form = $('#doc-form');
    const input = form.elements.file;
    const file = input.files[0];
    const zone = $('#doc-dropzone');
    const warn = $('#doc-file-warn');
    clearFieldErrors(form);
    zone.querySelector('.dz-empty').hidden = !!file;
    zone.querySelector('.dz-file').hidden = !file;
    zone.classList.toggle('has-file', !!file);
    warn.hidden = true;
    if (!file) return;

    zone.querySelector('.dz-name').textContent = file.name;
    zone.querySelector('.dz-size').textContent = Fmt.fileSize(file.size);
    const problem = checkFile(file);
    if (problem) {
      fieldError(form, 'file', problem);
    } else if (form.doc_type.value === 'PHOTOGRAPH' && IMAGE_TYPES.indexOf(extensionOf(file.name)) === -1) {
      warn.textContent = 'This will be saved, but only an image file (JPG, PNG, GIF or WebP) ' +
        'becomes the property\u2019s cover picture.';
      warn.hidden = false;
    }
  }

  function wireDropzone() {
    const form = $('#doc-form');
    const input = form.elements.file;
    const zone = $('#doc-dropzone');

    input.addEventListener('change', renderFileState);
    form.doc_type.addEventListener('change', renderFileState);
    $('#doc-file-clear').addEventListener('click', function () {
      input.value = '';
      renderFileState();
      input.focus();
    });

    ['dragenter', 'dragover'].forEach((type) => zone.addEventListener(type, function (event) {
      event.preventDefault();
      zone.classList.add('is-drag');
    }));
    ['dragleave', 'dragend'].forEach((type) => zone.addEventListener(type, function (event) {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove('is-drag');
    }));
    zone.addEventListener('drop', function (event) {
      event.preventDefault();
      zone.classList.remove('is-drag');
      const dropped = event.dataTransfer && event.dataTransfer.files;
      if (!dropped || !dropped.length) return;
      const one = new DataTransfer();
      one.items.add(dropped[0]);        // one document, one file
      input.files = one.files;
      renderFileState();
    });
  }

  /* ---------- views & layout ---------- */

  function switchView(view) {
    state.view = view;
    document.body.dataset.view = view;
    closePopovers();
    $$('.nav-pill .tab').forEach((tab) => {
      const on = tab.dataset.view === view;
      tab.classList.toggle('is-active', on);
      tab.setAttribute('aria-selected', on);
    });
    $$('.view').forEach((section) =>
      section.classList.toggle('is-active', section.id === 'view-' + view));
    if (view === 'portfolio' && state.mode === 'map') MapView.invalidate();
    if (view === 'dashboard') renderDashboard();
    if (view === 'documents') renderDocuments();
    if (view === 'masters') Masters.show();
    writeHash();
  }

  function setMode(mode) {
    state.mode = mode;
    const body = $('#portfolio-body');
    body.classList.remove('mode-map', 'mode-grid', 'mode-table');
    body.classList.add('mode-' + mode);
    $$('#mode-toggle button').forEach((b) => {
      const on = b.dataset.mode === mode;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-selected', on);
    });
    if (mode === 'map') MapView.invalidate();
    else MapView.hideCard();
    writeHash();
  }

  function setExpanded(on) {
    state.expanded = on;
    $('#portfolio-body').classList.toggle('map-expanded', on);
    const button = $('#map-expand');
    button.querySelector('use').setAttribute('href', on ? '#i-collapse' : '#i-expand');
    button.title = on ? 'Show the property cards' : 'Expand map';
    button.setAttribute('aria-label', button.title);
    MapView.invalidate();
  }

  function locate(propertyId) {
    closeDrawer();
    if (state.view !== 'portfolio') switchView('portfolio');
    if (state.mode !== 'map') setMode('map');
    MapView.invalidate();
    setTimeout(function () {
      if (!MapView.focus(propertyId)) {
        toast('That property is hidden by the current filters.', true);
      }
    }, 180);
  }

  /* ---------- events ---------- */

  let searchTimer = null;

  function wireEvents() {
    wireTheme();
    $$('.nav-pill .tab').forEach((tab) =>
      tab.addEventListener('click', function () {
        if (tab.dataset.view === 'sbus') closeSbuPage();
        switchView(tab.dataset.view);
      }));
    $$('#mode-toggle button').forEach((b) =>
      b.addEventListener('click', () => setMode(b.dataset.mode)));
    $$('#tenure-tabs button').forEach((b) =>
      b.addEventListener('click', () => setTenure(b.dataset.tenure)));
    $('#map-expand').addEventListener('click', () => setExpanded(!state.expanded));

    $('#sort-by').addEventListener('change', function (event) {
      state.sort = event.target.value;
      renderCards();
      renderTable();
    });

    $('#search').addEventListener('input', function (event) {
      clearTimeout(searchTimer);
      const value = event.target.value;
      searchTimer = setTimeout(function () {
        state.filters.q = value.trim();
        refreshProperties();
      }, 250);
    });

    // Filter popover
    $('#btn-filters').addEventListener('click', (e) => {
      e.stopPropagation(); togglePopover('#btn-filters', '#filter-pop');
    });
    $('#btn-alerts').addEventListener('click', (e) => {
      e.stopPropagation(); togglePopover('#btn-alerts', '#alerts-pop');
    });
    $('#btn-filters-done').addEventListener('click', closePopovers);

    [['#filter-district', 'district'], ['#filter-status', 'status'],
     ['#filter-type', 'property_type'], ['#filter-entity', 'legal_entity_id'],
     ['#filter-location', 'location_id']].forEach(function (pair) {
      $(pair[0]).addEventListener('change', function (event) {
        state.filters[pair[1]] = event.target.value;
        refreshProperties();
      });
    });
    $('#filter-tenure').addEventListener('change', (e) => setTenure(e.target.value));

    $('#btn-reset-filters').addEventListener('click', resetFilters);
    $('#btn-sbu-all').addEventListener('click', function () {
      state.selectedSbus = null;
      renderSbuFilters();
      refreshProperties();
    });
    $('#sbu-filters').addEventListener('click', function (event) {
      const chip = event.target.closest('[data-sbu-chip]');
      if (chip) toggleSbu(Number(chip.dataset.sbuChip));
    });

    $('#kpi-strip').addEventListener('click', function (event) {
      const card = event.target.closest('[data-kpi]');
      if (card) goFromKpi(card.dataset.kpi);
    });

    $('#map-legend').addEventListener('click', function (event) {
      const chip = event.target.closest('[data-legend-sbu]');
      if (!chip) return;
      const id = Number(chip.dataset.legendSbu);
      const solo = state.selectedSbus && state.selectedSbus.length === 1 && state.selectedSbus[0] === id;
      state.selectedSbus = solo ? null : [id];
      renderSbuFilters();
      refreshProperties();
    });

    $('#active-chips').addEventListener('click', function (event) {
      const button = event.target.closest('[data-chip-clear]');
      if (!button) return;
      if (button.dataset.chipClear === 'all') { resetFilters(); return; }
      const chip = currentChips[Number(button.dataset.chipClear)];
      if (chip) { chip.clear(); refreshProperties(); }
    });

    // Cards open the drawer; their buttons are handled by the delegated handler.
    $('#property-cards').addEventListener('click', function (event) {
      if (event.target.closest('button, a')) return;
      const card = event.target.closest('.pcard');
      if (card) openDrawer(Number(card.dataset.card));
    });
    $('#property-cards').addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      const card = event.target.closest('.pcard');
      if (card && event.target === card) openDrawer(Number(card.dataset.card));
    });

    $('#btn-new-property').addEventListener('click', () => openPropertyModal(null));
    $('#btn-new-sbu').addEventListener('click', () => openSbuModal(null));
    $('#btn-new-entity').addEventListener('click', () => openEntityModal(null));
    $('#btn-save-property').addEventListener('click', saveProperty);
    $('#btn-save-sbu').addEventListener('click', saveSbu);
    $('#btn-save-entity').addEventListener('click', saveEntity);
    $('#entity-form').addEventListener('submit', (e) => { e.preventDefault(); saveEntity(); });
    $('#btn-save-doc').addEventListener('click', saveDocument);

    // Documents module controls.
    $('#btn-new-doc').addEventListener('click', () => openDocModal(null));
    fillSelect($('#doc-type-filter'), optionsFrom(state.reference.documentTypes),
      { placeholder: 'All types', value: '' });
    $('#doc-tabs').addEventListener('click', function (event) {
      const tab = event.target.closest('[data-doc-status]');
      if (!tab) return;
      state.docs.status = tab.dataset.docStatus;
      writeHash();
      renderDocuments();
    });
    $('#doc-type-filter').addEventListener('change', function (event) {
      state.docs.type = event.target.value;
      renderDocuments();
    });
    $('#doc-sort').addEventListener('change', function (event) {
      state.docs.sort = event.target.value;
      renderDocuments();
    });
    $('#docs-banner').addEventListener('click', function (event) {
      if (event.target.closest('[data-clear-filters]')) resetFilters();
    });
    // A row opens the document; its links and buttons do their own thing.
    $('#doc-rows').addEventListener('click', function (event) {
      if (event.target.closest('button, a')) return;
      const row = event.target.closest('tr[data-doc-id]');
      if (row) openDocPanel(Number(row.dataset.docId));
    });

    // Business units: a card opens the unit's page.
    $('#sbu-cards').addEventListener('click', function (event) {
      if (event.target.closest('button, a')) return;
      const tile = event.target.closest('[data-sbu-open]');
      if (tile) openSbuPage(Number(tile.dataset.sbuOpen), 'properties');
    });
    $('#sbu-cards').addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const tile = event.target.closest('[data-sbu-open]');
      if (!tile || event.target !== tile) return;
      event.preventDefault();
      openSbuPage(Number(tile.dataset.sbuOpen), 'properties');
    });
    $('#sbu-detail').addEventListener('click', onSbuPageClick);
    $('#sbu-detail').addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      const row = event.target.closest('tr[tabindex]');
      if (row && event.target === row) row.click();
    });

    $('#btn-close-doc').addEventListener('click', closeDocPanel);
    $('#doc-drawer').addEventListener('click', function (event) {
      const t = event.target.closest('[data-doc-property-open]');
      if (!t) return;
      event.preventDefault();
      const id = Number(t.dataset.docPropertyOpen);
      closeDocPanel();
      openDrawer(id);
    });
    wireDropzone();

    // Typing into a flagged field clears its error.
    document.addEventListener('input', function (event) {
      const field = event.target;
      if (!field.classList || !field.classList.contains('is-invalid')) return;
      field.classList.remove('is-invalid');
      field.removeAttribute('aria-invalid');
      const host = field.closest('label') || field.closest('.field-block');
      const msg = host && host.querySelector('.field-msg');
      if (msg) msg.remove();
    });
    $('#btn-close-drawer').addEventListener('click', closeDrawer);
    $('#scrim').addEventListener('click', function () { closeDrawer(); closeDocPanel(); });

    $('#property-form').addEventListener('submit', (e) => { e.preventDefault(); saveProperty(); });
    $('#sbu-form').addEventListener('submit', (e) => { e.preventDefault(); saveSbu(); });
    $('#doc-form').addEventListener('submit', (e) => { e.preventDefault(); saveDocument(); });

    const propertyForm = $('#property-form');
    propertyForm.extent_unit.addEventListener('change', function () {
      if (areaLink) propertyForm.building_area_unit.value = propertyForm.extent_unit.value;
      updateAreas();
    });
    propertyForm.building_area_unit.addEventListener('change', function () {
      areaLink = propertyForm.building_area_unit.value === propertyForm.extent_unit.value;
      updateAreas();
    });
    propertyForm.extent_value.addEventListener('input', updateAreas);
    propertyForm.building_area_value.addEventListener('input', updateAreas);
    propertyForm.latitude.addEventListener('change', validateCoords);
    propertyForm.longitude.addEventListener('change', validateCoords);
    propertyForm.district.addEventListener('change', function (event) {
      const district = state.reference.districts
        .filter((d) => d.district === event.target.value)[0];
      propertyForm.province.value = district ? district.province : '';
      if (district) MapView.centerPicker(district.lat, district.lng, 11);
    });

    propertyForm.location_id.addEventListener('change', function (event) {
      const location = state.locations
        .filter((l) => String(l.id) === event.target.value)[0];
      if (!location) return;

      if (location.district) {
        propertyForm.district.value = location.district;
        propertyForm.province.value = location.province || '';
      }
      if (location.city && !propertyForm.city.value) {
        propertyForm.city.value = location.city;
      }
      // The location centroid is a starting point, not the property's own pin:
      // only fill coordinates that are still blank, then let the user drag it.
      const hasCoords = propertyForm.latitude.value && propertyForm.longitude.value;
      if (!hasCoords && location.latitude && location.longitude) {
        propertyForm.latitude.value = Number(location.latitude).toFixed(6);
        propertyForm.longitude.value = Number(location.longitude).toFixed(6);
        validateCoords();
        MapView.setPickerPoint(location.latitude, location.longitude, true);
        toast('Coordinates set to the ' + location.name +
              ' centroid — drag the pin to the exact spot.');
      } else if (location.latitude && location.longitude) {
        MapView.centerPicker(location.latitude, location.longitude, 13);
      }
    });

    $('#btn-paste-coords').addEventListener('click', function () {
      const input = window.prompt(
        'Paste coordinates copied from Google Maps, e.g.  6.927079, 79.861244');
      if (!input) return;
      const match = input.match(/(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)/);
      if (!match) { toast('Could not read a coordinate pair from that text.', true); return; }
      propertyForm.latitude.value = match[1];
      propertyForm.longitude.value = match[2];
      if (validateCoords()) {
        MapView.setPickerPoint(Number(match[1]), Number(match[2]), true);
      }
    });

    $$('[data-close-modal]').forEach((button) =>
      button.addEventListener('click', function () {
        button.closest('.modal').hidden = true;
      }));

    // Enter on a focusable row that opens a property (dashboard lists).
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      const row = event.target.closest('li[data-open][tabindex]');
      if (row && event.target === row) openDrawer(Number(row.dataset.open));
    });

    // Escape unwinds one layer at a time: popover, modal, drawer, map card.
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      if (anyPopoverOpen()) { closePopovers(); return; }
      const openModal = $$('.modal').filter((m) => !m.hidden)[0];
      if (openModal) { openModal.hidden = true; return; }
      if (!$('#drawer').hidden) { closeDrawer(); return; }
      if (!$('#doc-drawer').hidden) { closeDocPanel(); return; }
      if (MapView.isCardOpen()) MapView.hideCard();
    });

    // Delegated actions for dynamically rendered buttons.
    document.addEventListener('click', function (event) {
      if (anyPopoverOpen() && !event.target.closest('.pop-anchor')) closePopovers();

      const target = event.target.closest('[data-open],[data-locate],[data-edit],[data-delete],' +
        '[data-add-doc],[data-delete-doc],[data-edit-sbu],[data-delete-sbu],' +
        '[data-edit-entity],[data-delete-entity],[data-go]');
      if (!target) return;
      const d = target.dataset;

      if (d.go !== undefined) { event.preventDefault(); closePopovers(); switchView(d.go); }
      else if (d.open !== undefined) { event.preventDefault(); openDrawer(Number(d.open)); }
      else if (d.locate !== undefined) locate(Number(d.locate));
      else if (d.edit !== undefined) openPropertyModal(Number(d.edit));
      else if (d.delete !== undefined) removeProperty(Number(d.delete));
      else if (d.addDoc !== undefined) openDocModal(Number(d.addDoc));
      else if (d.deleteDoc !== undefined) removeDocument(Number(d.deleteDoc));
      else if (d.editSbu !== undefined) openSbuModal(Number(d.editSbu));
      else if (d.deleteSbu !== undefined) removeSbu(Number(d.deleteSbu));
      else if (d.editEntity !== undefined) openEntityModal(Number(d.editEntity));
      else if (d.deleteEntity !== undefined) removeEntity(Number(d.deleteEntity));
    });
  }

  async function removeProperty(propertyId) {
    const property = state.currentProperty && state.currentProperty.id === propertyId
      ? state.currentProperty
      : state.properties.filter((p) => p.id === propertyId)[0];
    const name = property ? property.property_code + ' — ' + property.name : 'this property';
    const docs = property && property.documents ? property.documents.length
      : (property ? property.document_count : 0);
    const warning = docs
      ? '\n\nIts ' + docs + ' document record(s) and any uploaded files will also be deleted.'
      : '';
    if (!window.confirm('Delete ' + name + '?' + warning + '\n\nThis cannot be undone.')) return;
    try {
      await API.deleteProperty(propertyId);
      closeDrawer();
      await refreshSbus();
      await refreshProperties();
      loadAlerts();
      toast('Property deleted.');
    } catch (err) { toast(err.message, true); }
  }

  async function removeDocument(documentId) {
    if (!window.confirm('Remove this document and its uploaded file?')) return;
    const propertyId = state.currentProperty ? state.currentProperty.id : null;
    try {
      await API.deleteDocument(documentId);
      if (propertyId) await openDrawer(propertyId);
      await refreshProperties();
      loadAlerts();
      toast('Document removed.');
    } catch (err) { toast(err.message, true); }
  }

  async function removeSbu(sbuId) {
    const sbu = state.sbus.filter((s) => s.id === sbuId)[0];
    if (!sbu) return;
    if (!window.confirm('Delete business unit "' + sbu.name + '"?')) return;
    try {
      await API.deleteSbu(sbuId);
      await refreshSbus();
      await refreshProperties();
      toast('Business unit deleted.');
    } catch (err) { toast(err.message, true); }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
