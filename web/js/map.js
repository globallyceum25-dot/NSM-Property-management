/* Leaflet wrappers: the portfolio map and the coordinate picker. */
window.MapView = (function () {
  'use strict';

  const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  let map = null;
  let layer = null;
  let markers = {};          // property id -> L.marker
  let data = {};             // property id -> property row
  let handlers = {};
  let bounds = null;
  let panelEl = null;
  let cardEl = null;
  let pendingFit = false;    // a fit requested while the map was hidden
  let selectedId = null;     // property whose card is open
  let hoverId = null;        // property highlighted from the list
  let light = true;

  function tileLayer() {
    return L.tileLayer(TILE_URL, { attribution: ATTRIBUTION, maxZoom: 19 });
  }

  function esc(value) { return Fmt.esc(value); }

  /* ---------- set-up ---------- */

  function init(elementId, reference, opts) {
    handlers = opts || {};
    bounds = reference.bounds;
    panelEl = document.getElementById(elementId).parentElement;
    cardEl = document.getElementById('map-card');

    // Quarter-step zoom lets "fit all" use the panel fully instead of dropping
    // a whole level; the + / - buttons still move one full level.
    map = L.map(elementId, {
      zoomControl: false, attributionControl: false, zoomSnap: 0.25, zoomDelta: 1
    }).setView(reference.mapCenter, reference.mapZoom);
    tileLayer().addTo(map);
    L.control.attribution({ position: 'bottomright' }).addTo(map);
    L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

    // Keep the user roughly over Sri Lanka without locking the map down hard.
    map.setMaxBounds(L.latLngBounds(
      [bounds.min_lat - 1.2, bounds.min_lng - 1.2],
      [bounds.max_lat + 1.2, bounds.max_lng + 1.2]));
    map.setMinZoom(6);

    layer = L.layerGroup().addTo(map);
    setLight(true);

    map.on('zoomend moveend', declutter);
    map.on('click', hideCard);

    bind('map-zoom-in', () => map.zoomIn());
    bind('map-zoom-out', () => map.zoomOut());
    bind('map-fit', fitAll);
    bind('map-layers', () => setLight(!light));

    cardEl.addEventListener('click', function (event) {
      if (event.target.closest('[data-card-close]')) hideCard();
    });

    window.__map = map;   // handy from the browser console when debugging
    return map;
  }

  function bind(id, fn) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', fn);
  }

  /* Light grey (default) or the standard OpenStreetMap colours. The grey is a
     CSS filter on the same tiles, so no second tile provider is involved. */
  function setLight(on) {
    light = on;
    panelEl.classList.toggle('map-light', on);
    const button = document.getElementById('map-layers');
    if (button) {
      button.classList.toggle('is-colour', !on);
      button.title = on ? 'Switch to the colour map' : 'Switch to the light map';
    }
  }

  /* ---------- markers ---------- */

  function pinIcon(p) {
    return L.divIcon({
      className: 'pin-icon',
      iconSize: [16, 16],
      iconAnchor: [8, 8],
      html: '<div class="pin" style="--c:' + esc(p.sbu_color || '#f25c2a') + '">' +
              '<span class="pin-label">' + esc(p.property_code) + '</span>' +
              '<span class="pin-dot"></span>' +
            '</div>'
    });
  }

  function pinEl(id) {
    const marker = markers[id];
    const el = marker && marker.getElement();
    return el ? el.querySelector('.pin') : null;
  }

  function paintHot() {
    Object.keys(markers).forEach(function (id) {
      const hot = String(id) === String(selectedId) || String(id) === String(hoverId);
      const el = pinEl(id);
      if (el) el.classList.toggle('is-hot', hot);
      markers[id].setZIndexOffset(hot ? 1000 : 0);
    });
  }

  function render(properties) {
    if (!map) return;
    layer.clearLayers();
    markers = {};
    data = {};

    properties.forEach(function (p) {
      const marker = L.marker([p.latitude, p.longitude], {
        icon: pinIcon(p),
        title: p.property_code + ' — ' + p.name,
        riseOnHover: true
      });
      marker.on('click', function (event) {
        L.DomEvent.stopPropagation(event);
        select(p.id);
      });
      marker.on('mouseover', function () {
        hoverId = p.id; paintHot();
        if (handlers.onHover) handlers.onHover(p.id, true);
      });
      marker.on('mouseout', function () {
        if (String(hoverId) === String(p.id)) hoverId = null;
        paintHot();
        if (handlers.onHover) handlers.onHover(p.id, false);
      });
      marker.addTo(layer);
      markers[p.id] = marker;
      data[p.id] = p;
    });

    if (selectedId !== null && !data[selectedId]) hideCard();
    fitAll();
    paintHot();
    setTimeout(declutter, 0);
  }

  /* Show a code pill over every pin that has room for one, north first, so the
     map reads like a labelled plan at any zoom without pills overlapping. */
  // Controls, legend and floating card that sit over the map, as boxes in map
  // coordinates, so no code pill is drawn underneath them.
  function overlayBoxes() {
    const origin = map.getContainer().getBoundingClientRect();
    return Array.prototype.slice.call(
      panelEl.querySelectorAll('.map-ctl, .map-ctl-stack, .legend-chip, .map-card:not([hidden])'))
      .map(function (el) {
        const r = el.getBoundingClientRect();
        return { x1: r.left - origin.left, x2: r.right - origin.left,
                 y1: r.top - origin.top, y2: r.bottom - origin.top };
      })
      .filter((b) => b.x2 > b.x1 && b.y2 > b.y1);
  }

  function declutter() {
    if (!map) return;
    const size = map.getSize();
    if (!size.x || !size.y) return;
    const placed = overlayBoxes();

    Object.keys(markers)
      .sort((a, b) => data[b].latitude - data[a].latitude)
      .forEach(function (id) {
        const el = pinEl(id);
        if (!el) return;
        const pt = map.latLngToContainerPoint(markers[id].getLatLng());
        const w = 28 + 7.4 * String(data[id].property_code).length;
        const box = { x1: pt.x - w / 2, x2: pt.x + w / 2, y1: pt.y - 64, y2: pt.y + 10 };
        const inView = pt.x > 8 && pt.x < size.x - 8 && pt.y > 40 && pt.y < size.y - 8;
        const clash = placed.some((b) =>
          !(box.x2 + 6 < b.x1 || box.x1 - 6 > b.x2 || box.y2 < b.y1 || box.y1 > b.y2));
        const on = inView && !clash;
        el.classList.toggle('label-on', on);
        if (on) placed.push(box);
      });
  }

  /* ---------- selection & the floating card ---------- */

  function select(id) {
    const p = data[id];
    if (!p) return;
    selectedId = id;
    paintHot();
    showCard(p);
    if (handlers.onPick) handlers.onPick(id);
  }

  function showCard(p) {
    if (!handlers.cardHtml) return;
    cardEl.innerHTML = handlers.cardHtml(p);
    cardEl.hidden = false;
    panelEl.classList.add('card-open');
    declutter();
  }

  function hideCard() {
    if (cardEl.hidden) return;
    cardEl.hidden = true;
    cardEl.innerHTML = '';
    panelEl.classList.remove('card-open');
    const was = selectedId;
    selectedId = null;
    paintHot();
    declutter();
    if (handlers.onPick && was !== null) handlers.onPick(null);
  }

  function isCardOpen() { return !cardEl.hidden; }

  function highlight(id, on) {
    hoverId = on ? id : (String(hoverId) === String(id) ? null : hoverId);
    paintHot();
  }

  function focus(propertyId) {
    const marker = markers[propertyId];
    if (!marker) return false;
    map.setView(marker.getLatLng(), Math.max(map.getZoom(), 14), { animate: true });
    select(propertyId);
    return true;
  }

  /* ---------- viewport ---------- */

  function hasSize() {
    const size = map.getSize();
    return size.x > 0 && size.y > 0;
  }

  function fitAll() {
    if (!map) return;
    if (!hasSize()) { pendingFit = true; return; }
    const latlngs = Object.keys(markers).map((id) => markers[id].getLatLng());
    if (latlngs.length > 1) {
      // Extra room at the bottom and right keeps pins clear of the legend
      // and the zoom controls.
      map.fitBounds(L.latLngBounds(latlngs), {
        paddingTopLeft: [70, 70], paddingBottomRight: [80, 84], maxZoom: 13
      });
    } else if (latlngs.length === 1) {
      map.setView(latlngs[0], 14);
    }
  }

  function invalidate() {
    if (!map) return;
    setTimeout(function () {
      map.invalidateSize();
      if (pendingFit && hasSize()) { pendingFit = false; fitAll(); }
      declutter();
    }, 60);
  }

  /* ----- coordinate picker used inside the property form ----- */

  let picker = null;
  let pickerMarker = null;

  const pickerIcon = L.divIcon({
    className: 'picker-pin',
    html: '<span></span>',
    iconSize: [26, 26],
    iconAnchor: [13, 31]
  });

  function initPicker(elementId, reference, onMove) {
    if (picker) { picker.remove(); picker = null; pickerMarker = null; }
    picker = L.map(elementId, { zoomControl: true })
      .setView(reference.mapCenter, reference.mapZoom - 1);
    tileLayer().addTo(picker);
    picker.on('click', function (event) {
      setPickerPoint(event.latlng.lat, event.latlng.lng, false);
      onMove(event.latlng.lat, event.latlng.lng);
    });
    picker._onMove = onMove;
    return picker;
  }

  function setPickerPoint(lat, lng, recenter) {
    if (!picker) return;
    if (!isFinite(lat) || !isFinite(lng)) return;
    if (pickerMarker) {
      pickerMarker.setLatLng([lat, lng]);
    } else {
      pickerMarker = L.marker([lat, lng], { draggable: true, icon: pickerIcon }).addTo(picker);
      pickerMarker.on('dragend', function () {
        const pos = pickerMarker.getLatLng();
        if (picker._onMove) picker._onMove(pos.lat, pos.lng);
      });
    }
    if (recenter) picker.setView([lat, lng], Math.max(picker.getZoom(), 13));
  }

  function clearPickerPoint() {
    if (pickerMarker && picker) { picker.removeLayer(pickerMarker); pickerMarker = null; }
  }

  function centerPicker(lat, lng, zoom) {
    if (picker) picker.setView([lat, lng], zoom || 11);
  }

  function invalidatePicker() {
    if (picker) setTimeout(() => picker.invalidateSize(), 80);
  }

  return {
    init: init, render: render, focus: focus, invalidate: invalidate,
    highlight: highlight, hideCard: hideCard, isCardOpen: isCardOpen, fitAll: fitAll,
    initPicker: initPicker, setPickerPoint: setPickerPoint,
    clearPickerPoint: clearPickerPoint, centerPicker: centerPicker,
    invalidatePicker: invalidatePicker
  };
})();
