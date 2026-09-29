/* Application controller: state, rendering and event wiring. */
(function () {
  'use strict';

  const state = {
    reference: null,
    sbus: [],
    properties: [],
    selectedSbus: null,          // null = all
    filters: { q: '', district: '', status: '', property_type: '' },
    labels: {},
    currentProperty: null,
    view: 'map'
  };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.prototype.slice.call(document.querySelectorAll(selector));

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
    MapView.init('map', state.reference, {
      onSelect: openDrawer,
      onEdit: (id) => openPropertyModal(id)
    });
    wireEvents();

    await refreshSbus();
    await refreshProperties();
  }

  function buildStaticSelects() {
    const ref = state.reference;
    const districtOptions = ref.districts.map((d) => ({
      value: d.district, label: d.district + ' (' + d.province + ')'
    }));

    fillSelect($('#filter-district'), districtOptions, { placeholder: 'All districts' });
    fillSelect($('#filter-status'), optionsFrom(ref.statuses), { placeholder: 'Any status' });
    fillSelect($('#filter-type'), optionsFrom(ref.propertyTypes), { placeholder: 'Any type' });

    const form = $('#property-form');
    fillSelect(form.status, optionsFrom(ref.statuses), { value: 'ACTIVE' });
    fillSelect(form.property_type, optionsFrom(ref.propertyTypes), { value: 'LAND' });
    fillSelect(form.ownership_type, optionsFrom(ref.ownershipTypes), { value: 'FREEHOLD' });
    fillSelect(form.extent_unit, optionsFrom(ref.extentUnits), { value: 'PERCH' });
    fillSelect(form.district, districtOptions, { placeholder: '—' });

    fillSelect($('#doc-form').doc_type, optionsFrom(ref.documentTypes), { value: 'DEED' });
    $('#doc-file-hint').textContent =
      'PDF, image, Word, Excel or ZIP up to ' +
      Math.round(ref.maxUploadBytes / (1024 * 1024)) + ' MB. Optional — you can record a ' +
      'document reference now and attach the scan later.';
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

  function activeFilters() {
    const filters = Object.assign({}, state.filters);
    if (state.selectedSbus && state.selectedSbus.length) {
      filters.sbu_id = state.selectedSbus.join(',');
    }
    return filters;
  }

  async function refreshProperties() {
    if (state.selectedSbus && state.selectedSbus.length === 0) {
      state.properties = [];
    } else {
      state.properties = await API.listProperties(activeFilters());
    }
    renderCount();
    renderTable();
    renderLegend();
    MapView.render(state.properties);
  }

  /* ---------- sidebar ---------- */

  function renderSbuFilters() {
    const host = $('#sbu-filters');
    host.innerHTML = '';
    state.sbus.forEach(function (sbu) {
      const checked = !state.selectedSbus || state.selectedSbus.indexOf(sbu.id) !== -1;
      const label = document.createElement('label');
      label.className = 'sbu-filter';
      label.innerHTML =
        '<input type="checkbox" value="' + sbu.id + '"' + (checked ? ' checked' : '') + '>' +
        '<span class="swatch" style="background:' + Fmt.esc(sbu.color) + '"></span>' +
        '<span class="name" title="' + Fmt.esc(sbu.name) + '">' + Fmt.esc(sbu.name) + '</span>' +
        '<span class="count">' + sbu.property_count + '</span>';
      label.querySelector('input').addEventListener('change', onSbuFilterChange);
      host.appendChild(label);
    });
  }

  function onSbuFilterChange() {
    const checked = $$('#sbu-filters input:checked').map((i) => Number(i.value));
    state.selectedSbus = (checked.length === state.sbus.length) ? null : checked;
    refreshProperties();
  }

  function renderCount() {
    $('#result-count').textContent = state.properties.length;
    $('#result-caption').textContent =
      state.properties.length === 1 ? 'property' : 'properties';
  }

  function renderLegend() {
    const host = $('#map-legend');
    const counts = {};
    state.properties.forEach(function (p) {
      counts[p.sbu_id] = (counts[p.sbu_id] || 0) + 1;
    });
    const rows = state.sbus
      .filter((s) => counts[s.id])
      .map((s) => '<div class="legend-row"><span class="swatch" style="background:' +
        Fmt.esc(s.color) + '"></span>' + Fmt.esc(s.name) +
        ' <span style="color:var(--text-muted)">(' + counts[s.id] + ')</span></div>');
    host.innerHTML = rows.length
      ? '<h3>Business units on map</h3>' + rows.join('')
      : '<h3>No properties shown</h3>';
  }

  /* ---------- property table ---------- */

  function renderTable() {
    const body = $('#property-rows');
    body.innerHTML = '';
    $('#list-empty').hidden = state.properties.length > 0;

    state.properties.forEach(function (p) {
      const tr = document.createElement('tr');
      tr.innerHTML =
        '<td class="code">' + Fmt.esc(p.property_code) + '</td>' +
        '<td><span class="prop-name">' + Fmt.esc(p.name) + '</span>' +
          '<span class="prop-sub">' + Fmt.esc([p.address_line1, p.city].filter(Boolean).join(', ')) + '</span></td>' +
        '<td><span class="sbu-pill"><span class="swatch" style="background:' +
          Fmt.esc(p.sbu_color) + '"></span>' + Fmt.esc(p.sbu_code) + '</span></td>' +
        '<td>' + Fmt.esc(labelFor('propertyTypes', p.property_type)) + '</td>' +
        '<td>' + Fmt.esc(p.district || '') + '</td>' +
        '<td>' + Fmt.esc(Fmt.extent(p.extent_value, p.extent_unit, state.labels.extentUnits)) + '</td>' +
        '<td><span class="badge ' + Fmt.esc(p.status) + '">' +
          Fmt.esc(labelFor('statuses', p.status)) + '</span></td>' +
        '<td class="doc-count' + (p.document_count ? '' : ' zero') + '">' + p.document_count + '</td>' +
        '<td class="coords">' + Fmt.coords(p.latitude, p.longitude) + '</td>' +
        '<td class="row-actions">' +
          '<button class="btn btn-ghost btn-sm" data-locate="' + p.id + '">Map</button> ' +
          '<button class="btn btn-ghost btn-sm" data-open="' + p.id + '">Open</button>' +
        '</td>';
      tr.addEventListener('click', function (event) {
        if (event.target.closest('button')) return;
        openDrawer(p.id);
      });
      body.appendChild(tr);
    });
  }

  /* ---------- SBU cards ---------- */

  function renderSbuCards() {
    const host = $('#sbu-cards');
    host.innerHTML = '';
    state.sbus.forEach(function (sbu) {
      const card = document.createElement('div');
      card.className = 'sbu-card';
      card.style.borderLeftColor = sbu.color;
      const sub = [sbu.sector, sbu.cost_centre ? 'CC ' + sbu.cost_centre : '']
        .filter(Boolean).join(' · ');
      card.innerHTML =
        '<h3>' + Fmt.esc(sbu.name) + ' <span class="code">' + Fmt.esc(sbu.code) + '</span></h3>' +
        (sub ? '<p class="sbu-sector">' + Fmt.esc(sub) + '</p>' : '') +
        '<p>' + Fmt.esc(sbu.description || 'No description.') + '</p>' +
        '<div class="sbu-foot">' +
          '<span class="n">' + sbu.property_count + ' propert' +
            (sbu.property_count === 1 ? 'y' : 'ies') + '</span>' +
          '<span><button class="btn btn-ghost btn-sm" data-edit-sbu="' + sbu.id + '">Edit</button> ' +
          '<button class="btn btn-danger btn-sm" data-delete-sbu="' + sbu.id + '">Delete</button></span>' +
        '</div>';
      host.appendChild(card);
    });
  }

  /* ---------- dashboard ---------- */

  async function renderDashboard() {
    const host = $('#dashboard');
    host.innerHTML = '<p class="empty">Loading…</p>';
    let stats;
    try {
      stats = await API.stats();
    } catch (err) {
      host.innerHTML = '<p class="empty">Could not load statistics: ' + Fmt.esc(err.message) + '</p>';
      return;
    }

    const t = stats.totals;
    const maxSbu = Math.max.apply(null, stats.bySbu.map((s) => s.property_count).concat([1]));
    const maxDistrict = Math.max.apply(null, stats.byDistrict.map((d) => d.n).concat([1]));

    function bars(rows, labelKey, valueKey, max, colorFor) {
      if (!rows.length) return '<p class="muted">Nothing recorded yet.</p>';
      return rows.map(function (row) {
        const width = Math.max(3, Math.round((row[valueKey] / max) * 100));
        return '<div class="bar-row">' +
          '<span class="label" title="' + Fmt.esc(row[labelKey]) + '">' + Fmt.esc(row[labelKey]) + '</span>' +
          '<span class="bar-track"><span class="bar-fill" style="width:' + width + '%;background:' +
            Fmt.esc(colorFor(row)) + '"></span></span>' +
          '<span class="n">' + row[valueKey] + '</span>' +
        '</div>';
      }).join('');
    }

    const expiring = stats.expiringSoon.length
      ? '<ul class="mini-list">' + stats.expiringSoon.map(function (d) {
          const days = Fmt.daysUntil(d.expiry_date);
          return '<li><span><a href="#" data-open="' + d.property_id + '">' +
            Fmt.esc(d.property_code) + '</a> — ' + Fmt.esc(d.title) + '</span>' +
            '<span class="when">' + Fmt.date(d.expiry_date) +
            (days !== null ? ' (' + days + 'd)' : '') + '</span></li>';
        }).join('') + '</ul>'
      : '<p class="muted">No leases, policies or permits expire in the next 180 days.</p>';

    host.innerHTML =
      '<div class="stat-row">' +
        '<div class="stat"><div class="v">' + t.properties + '</div><div class="k">Properties</div></div>' +
        '<div class="stat"><div class="v">' + t.sbus + '</div><div class="k">Business units</div></div>' +
        '<div class="stat"><div class="v">' + t.documents + '</div><div class="k">Documents</div></div>' +
        '<div class="stat"><div class="v">' + t.files + '</div><div class="k">Files stored</div></div>' +
        '<div class="stat' + (t.without_deed ? ' alert' : '') + '"><div class="v">' +
          t.without_deed + '</div><div class="k">Without deed / title</div></div>' +
      '</div>' +
      '<div class="dash-cols">' +
        '<div class="card"><h3>Properties by business unit</h3>' +
          bars(stats.bySbu, 'name', 'property_count', maxSbu, (r) => r.color) + '</div>' +
        '<div class="card"><h3>Properties by district</h3>' +
          bars(stats.byDistrict, 'district', 'n', maxDistrict, () => '#0b5d8f') + '</div>' +
        '<div class="card"><h3>By status</h3>' +
          bars(stats.byStatus.map((s) => ({ label: labelFor('statuses', s.status), n: s.n })),
               'label', 'n',
               Math.max.apply(null, stats.byStatus.map((s) => s.n).concat([1])),
               () => '#6b7784') + '</div>' +
        '<div class="card"><h3>Expiring within 180 days</h3>' + expiring + '</div>' +
      '</div>' +
      '<p class="muted" style="margin-top:14px">Land extent totals per business unit (in perches): ' +
        Fmt.esc(stats.bySbu.map((s) => s.code + ' ' + Fmt.num(s.extent_perches, 1)).join('  ·  ')) +
      '</p>';
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
    state.currentProperty = property;

    $('#drawer-code').textContent = property.property_code;
    $('#drawer-name').textContent = property.name;
    $('#drawer-body').innerHTML = detailHtml(property);
    $('#drawer').hidden = false;
    $('#scrim').hidden = false;
  }

  function closeDrawer() {
    $('#drawer').hidden = true;
    $('#scrim').hidden = true;
    state.currentProperty = null;
  }

  function row(label, value) {
    if (value === null || value === undefined || value === '') return '';
    return '<dt>' + Fmt.esc(label) + '</dt><dd>' + value + '</dd>';
  }

  function detailHtml(p) {
    const address = [p.address_line1, p.address_line2, p.city, p.postal_code]
      .filter(Boolean).map(Fmt.esc).join('<br>');

    const details =
      '<div class="detail-actions">' +
        '<button class="btn btn-primary btn-sm" data-edit="' + p.id + '">Edit property</button>' +
        '<button class="btn btn-ghost btn-sm" data-locate="' + p.id + '">Show on map</button>' +
        '<button class="btn btn-ghost btn-sm" data-add-doc="' + p.id + '">+ Add document</button>' +
        '<button class="btn btn-danger btn-sm" data-delete="' + p.id + '">Delete</button>' +
      '</div>' +
      '<section class="detail-section"><h3>Classification</h3><dl class="detail-grid">' +
        row('Business unit', '<span class="sbu-pill"><span class="swatch" style="background:' +
            Fmt.esc(p.sbu_color) + '"></span>' + Fmt.esc(p.sbu_code + ' — ' + p.sbu_name) + '</span>') +
        row('Sector', Fmt.esc([p.sbu_sector, p.sbu_cost_centre ? 'CC ' + p.sbu_cost_centre : '']
            .filter(Boolean).join(' · '))) +
        row('Type', Fmt.esc(labelFor('propertyTypes', p.property_type))) +
        row('Ownership', Fmt.esc(labelFor('ownershipTypes', p.ownership_type))) +
        row('Status', '<span class="badge ' + Fmt.esc(p.status) + '">' +
            Fmt.esc(labelFor('statuses', p.status)) + '</span>') +
        row('Current use', Fmt.esc(p.current_use)) +
      '</dl></section>' +

      '<section class="detail-section"><h3>Location</h3><dl class="detail-grid">' +
        row('Address', address) +
        row('District', Fmt.esc(p.district)) +
        row('Province', Fmt.esc(p.province)) +
        row('Coordinates', '<span style="font-variant-numeric:tabular-nums">' +
            Fmt.coords(p.latitude, p.longitude) + '</span>') +
      '</dl></section>' +

      '<section class="detail-section"><h3>Extent &amp; value</h3><dl class="detail-grid">' +
        row('Land extent', Fmt.esc(Fmt.extent(p.extent_value, p.extent_unit, state.labels.extentUnits))) +
        row('Building area', p.building_area_sqft ? Fmt.num(p.building_area_sqft) + ' sq ft' : '') +
        row('Assessment no.', Fmt.esc(p.assessment_no)) +
        row('Survey plan', Fmt.esc([p.plan_no, p.lot_no ? 'Lot ' + p.lot_no : ''].filter(Boolean).join(' · '))) +
        row('Acquired', Fmt.date(p.acquisition_date)) +
        row('Acquisition cost', Fmt.money(p.acquisition_cost, p.currency)) +
        row('Current value', Fmt.money(p.current_value, p.currency)) +
      '</dl></section>' +

      '<section class="detail-section"><h3>Custody</h3><dl class="detail-grid">' +
        row('Custodian', Fmt.esc(p.custodian)) +
        row('Contact', Fmt.esc(p.contact_phone)) +
        row('Notes', Fmt.esc(p.notes)) +
      '</dl></section>' +

      '<section class="detail-section"><h3>Documents (' + p.documents.length + ')</h3>' +
        documentsHtml(p.documents) +
      '</section>';
    return details;
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
        d.reference_no ? 'Ref ' + Fmt.esc(d.reference_no) : '',
        d.issue_date ? 'issued ' + Fmt.date(d.issue_date) : '',
        d.counterparty ? Fmt.esc(d.counterparty) : '',
        d.amount ? Fmt.money(d.amount, d.currency) : ''
      ].filter(Boolean).join(' · ');

      const fileBits = d.stored_name
        ? '<a class="btn btn-ghost btn-sm" href="/api/documents/' + d.id + '/file" target="_blank" rel="noopener">View</a>' +
          '<a class="btn btn-ghost btn-sm" href="/api/documents/' + d.id + '/file?disposition=attachment">Download</a>' +
          '<span class="no-file">' + Fmt.esc(d.file_name) + ' · ' + Fmt.fileSize(d.size_bytes) + '</span>'
        : '<span class="no-file">No file attached</span>';

      return '<div class="doc-item">' +
        '<div class="doc-top"><span class="doc-type ' + Fmt.esc(d.doc_type) + '">' +
          Fmt.esc(labelFor('documentTypes', d.doc_type)) + '</span>' +
          '<button class="btn btn-danger btn-sm" data-delete-doc="' + d.id + '">Remove</button></div>' +
        '<h4>' + Fmt.esc(d.title) + '</h4>' +
        '<p class="doc-meta">' + meta + expiryNote + '</p>' +
        (d.notes ? '<p class="doc-meta">' + Fmt.esc(d.notes) + '</p>' : '') +
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
    const form = $('#property-form');
    form.reset();
    $('#property-form-error').hidden = true;
    $('#coord-error').hidden = true;
    fillSelect(form.status, optionsFrom(state.reference.statuses), { value: 'ACTIVE' });
    fillSelect(form.property_type, optionsFrom(state.reference.propertyTypes), { value: 'LAND' });
    fillSelect(form.ownership_type, optionsFrom(state.reference.ownershipTypes), { value: 'FREEHOLD' });
    fillSelect(form.extent_unit, optionsFrom(state.reference.extentUnits), { value: 'PERCH' });
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
    }

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

  function collectForm(form, numericFields) {
    const data = {};
    Array.prototype.forEach.call(form.elements, function (field) {
      if (!field.name || field.type === 'file' || field.type === 'submit') return;
      if (field.type === 'checkbox') { data[field.name] = field.checked; return; }
      let value = field.value;
      if (typeof value === 'string') value = value.trim();
      if (numericFields && numericFields.indexOf(field.name) !== -1) {
        data[field.name] = value === '' ? null : Number(value);
      } else {
        data[field.name] = value === '' ? null : value;
      }
    });
    return data;
  }

  async function saveProperty() {
    const form = $('#property-form');
    const errorBox = $('#property-form-error');
    errorBox.hidden = true;

    if (!form.reportValidity()) return;
    if (!validateCoords()) {
      errorBox.textContent = 'Fix the coordinates before saving.';
      errorBox.hidden = false;
      return;
    }

    const data = collectForm(form, ['latitude', 'longitude', 'extent_value',
      'building_area_sqft', 'acquisition_cost', 'current_value', 'sbu_id']);
    const id = form.id.value;
    delete data.id;

    const button = $('#btn-save-property');
    button.disabled = true;
    try {
      const saved = id ? await API.updateProperty(id, data) : await API.createProperty(data);
      $('#property-modal').hidden = true;
      await refreshSbus();
      await refreshProperties();
      toast(id ? 'Property updated.' : 'Property ' + saved.property_code + ' added.');
      if (!id || (state.currentProperty && String(state.currentProperty.id) === String(id))) {
        openDrawer(saved.id);
      }
      MapView.focus(saved.id);
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.hidden = false;
      if (err.field && form.elements[err.field]) form.elements[err.field].focus();
    } finally {
      button.disabled = false;
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
    errorBox.hidden = true;
    if (!form.reportValidity()) return;

    const data = collectForm(form);
    const id = form.id.value;
    delete data.id;

    try {
      if (id) await API.updateSbu(id, data);
      else await API.createSbu(data);
      $('#sbu-modal').hidden = true;
      await refreshSbus();
      await refreshProperties();
      toast(id ? 'Business unit updated.' : 'Business unit added.');
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.hidden = false;
    }
  }

  /* ---------- document form ---------- */

  function openDocModal(propertyId) {
    const form = $('#doc-form');
    form.reset();
    $('#doc-form-error').hidden = true;
    fillSelect(form.doc_type, optionsFrom(state.reference.documentTypes), { value: 'DEED' });
    form.property_id.value = propertyId;
    $('#doc-modal').hidden = false;
    setTimeout(() => form.doc_type.focus(), 50);
  }

  async function saveDocument() {
    const form = $('#doc-form');
    const errorBox = $('#doc-form-error');
    errorBox.hidden = true;
    if (!form.reportValidity()) return;

    const propertyId = form.property_id.value;
    const formData = new FormData();
    ['doc_type', 'title', 'reference_no', 'issue_date', 'expiry_date',
     'counterparty', 'amount', 'notes'].forEach(function (name) {
      const value = (form.elements[name].value || '').trim();
      if (value) formData.append(name, value);
    });
    const file = form.elements.file.files[0];
    if (file) {
      if (file.size > state.reference.maxUploadBytes) {
        errorBox.textContent = 'That file is ' + Fmt.fileSize(file.size) + ' — the limit is ' +
          Fmt.fileSize(state.reference.maxUploadBytes) + '.';
        errorBox.hidden = false;
        return;
      }
      formData.append('file', file, file.name);
    }

    const button = $('#btn-save-doc');
    button.disabled = true;
    try {
      await API.addDocument(propertyId, formData);
      $('#doc-modal').hidden = true;
      await openDrawer(propertyId);
      await refreshProperties();
      toast('Document attached.');
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.hidden = false;
    } finally {
      button.disabled = false;
    }
  }

  /* ---------- view switching ---------- */

  function switchView(view) {
    state.view = view;
    $$('.tab').forEach((tab) => tab.classList.toggle('is-active', tab.dataset.view === view));
    $$('.view').forEach((section) =>
      section.classList.toggle('is-active', section.id === 'view-' + view));
    if (view === 'map') MapView.invalidate();
    if (view === 'dashboard') renderDashboard();
  }

  async function locate(propertyId) {
    switchView('map');
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
    $$('.tab').forEach((tab) =>
      tab.addEventListener('click', () => switchView(tab.dataset.view)));

    $('#search').addEventListener('input', function (event) {
      clearTimeout(searchTimer);
      const value = event.target.value;
      searchTimer = setTimeout(function () {
        state.filters.q = value;
        refreshProperties();
      }, 250);
    });

    ['district', 'status', 'type'].forEach(function (key) {
      const field = key === 'type' ? 'property_type' : key;
      $('#filter-' + key).addEventListener('change', function (event) {
        state.filters[field] = event.target.value;
        refreshProperties();
      });
    });

    $('#btn-reset-filters').addEventListener('click', function () {
      state.filters = { q: '', district: '', status: '', property_type: '' };
      state.selectedSbus = null;
      $('#search').value = '';
      $('#filter-district').value = '';
      $('#filter-status').value = '';
      $('#filter-type').value = '';
      renderSbuFilters();
      refreshProperties();
    });

    $('#btn-sbu-all').addEventListener('click', function () {
      state.selectedSbus = null;
      renderSbuFilters();
      refreshProperties();
    });

    $('#btn-new-property').addEventListener('click', () => openPropertyModal(null));
    $('#btn-new-sbu').addEventListener('click', () => openSbuModal(null));
    $('#btn-save-property').addEventListener('click', saveProperty);
    $('#btn-save-sbu').addEventListener('click', saveSbu);
    $('#btn-save-doc').addEventListener('click', saveDocument);
    $('#btn-close-drawer').addEventListener('click', closeDrawer);
    $('#scrim').addEventListener('click', closeDrawer);

    $('#property-form').addEventListener('submit', (e) => { e.preventDefault(); saveProperty(); });
    $('#sbu-form').addEventListener('submit', (e) => { e.preventDefault(); saveSbu(); });
    $('#doc-form').addEventListener('submit', (e) => { e.preventDefault(); saveDocument(); });

    const propertyForm = $('#property-form');
    propertyForm.latitude.addEventListener('change', validateCoords);
    propertyForm.longitude.addEventListener('change', validateCoords);
    propertyForm.district.addEventListener('change', function (event) {
      const district = state.reference.districts
        .filter((d) => d.district === event.target.value)[0];
      propertyForm.province.value = district ? district.province : '';
      if (district && !propertyForm.latitude.value) {
        MapView.centerPicker(district.lat, district.lng, 11);
      } else if (district) {
        MapView.centerPicker(district.lat, district.lng, 11);
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

    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      const openModal = $$('.modal').filter((m) => !m.hidden)[0];
      if (openModal) { openModal.hidden = true; return; }
      if (!$('#drawer').hidden) closeDrawer();
    });

    // Delegated actions for dynamically rendered buttons.
    document.addEventListener('click', function (event) {
      const target = event.target.closest('[data-open],[data-locate],[data-edit],[data-delete],' +
        '[data-add-doc],[data-delete-doc],[data-edit-sbu],[data-delete-sbu]');
      if (!target) return;
      const d = target.dataset;

      if (d.open !== undefined) { event.preventDefault(); openDrawer(Number(d.open)); }
      else if (d.locate !== undefined) locate(Number(d.locate));
      else if (d.edit !== undefined) openPropertyModal(Number(d.edit));
      else if (d.delete !== undefined) removeProperty(Number(d.delete));
      else if (d.addDoc !== undefined) openDocModal(Number(d.addDoc));
      else if (d.deleteDoc !== undefined) removeDocument(Number(d.deleteDoc));
      else if (d.editSbu !== undefined) openSbuModal(Number(d.editSbu));
      else if (d.deleteSbu !== undefined) removeSbu(Number(d.deleteSbu));
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
