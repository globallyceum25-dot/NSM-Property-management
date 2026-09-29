/* Leaflet wrappers: the main property map and the coordinate picker. */
window.MapView = (function () {
  const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  let map = null;
  let layer = null;
  let markers = {};          // property id -> marker
  let onSelect = null;
  let onEdit = null;
  let bounds = null;

  function tileLayer() {
    return L.tileLayer(TILE_URL, { attribution: ATTRIBUTION, maxZoom: 19 });
  }

  function init(elementId, reference, handlers) {
    onSelect = handlers.onSelect;
    onEdit = handlers.onEdit;
    bounds = reference.bounds;

    map = L.map(elementId, { zoomControl: true, attributionControl: true })
      .setView(reference.mapCenter, reference.mapZoom);
    tileLayer().addTo(map);

    // Keep the user roughly over Sri Lanka without locking the map down hard.
    const sl = L.latLngBounds(
      [bounds.min_lat - 1.2, bounds.min_lng - 1.2],
      [bounds.max_lat + 1.2, bounds.max_lng + 1.2]
    );
    map.setMaxBounds(sl);
    map.setMinZoom(6);

    layer = L.layerGroup().addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    window.__map = map;   // handy from the browser console when debugging
    return map;
  }

  function popupHtml(p) {
    const parts = [];
    parts.push('<div class="popup-code">' + Fmt.esc(p.property_code) + '</div>');
    parts.push('<div class="popup-title">' + Fmt.esc(p.name) + '</div>');
    const meta = [p.sbu_name, p.city, p.district].filter(Boolean).join(' &middot; ');
    parts.push('<p class="popup-meta">' + meta + '<br>' +
      Fmt.coords(p.latitude, p.longitude) +
      ' &middot; ' + p.document_count + ' document' + (p.document_count === 1 ? '' : 's') +
      '</p>');
    parts.push('<div class="popup-actions">' +
      '<button class="btn btn-ghost btn-sm" data-popup-open="' + p.id + '">Open</button>' +
      '<button class="btn btn-ghost btn-sm" data-popup-edit="' + p.id + '">Edit</button>' +
      '</div>');
    return parts.join('');
  }

  function render(properties) {
    if (!map) return;
    layer.clearLayers();
    markers = {};
    const latlngs = [];

    properties.forEach(function (p) {
      const marker = L.circleMarker([p.latitude, p.longitude], {
        radius: 8,
        color: '#ffffff',
        weight: 2,
        fillColor: p.sbu_color || '#1f77b4',
        fillOpacity: 0.95
      });
      marker.bindTooltip(p.property_code + ' — ' + p.name, { direction: 'top', offset: [0, -6] });
      marker.bindPopup(popupHtml(p), { minWidth: 210 });
      marker.on('popupopen', function (event) {
        const root = event.popup.getElement();
        const open = root.querySelector('[data-popup-open]');
        const edit = root.querySelector('[data-popup-edit]');
        if (open) open.addEventListener('click', () => onSelect && onSelect(p.id));
        if (edit) edit.addEventListener('click', () => onEdit && onEdit(p.id));
      });
      marker.addTo(layer);
      markers[p.id] = marker;
      latlngs.push([p.latitude, p.longitude]);
    });

    if (latlngs.length > 1) {
      map.fitBounds(L.latLngBounds(latlngs), { padding: [45, 45], maxZoom: 13 });
    } else if (latlngs.length === 1) {
      map.setView(latlngs[0], 14);
    }
  }

  function focus(propertyId) {
    const marker = markers[propertyId];
    if (!marker) return false;
    map.setView(marker.getLatLng(), Math.max(map.getZoom(), 14), { animate: true });
    marker.openPopup();
    return true;
  }

  function invalidate() {
    if (map) setTimeout(() => map.invalidateSize(), 60);
  }

  /* ----- coordinate picker used inside the property form ----- */

  let picker = null;
  let pickerMarker = null;

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
      pickerMarker = L.marker([lat, lng], { draggable: true }).addTo(picker);
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
    initPicker: initPicker, setPickerPoint: setPickerPoint,
    clearPickerPoint: clearPickerPoint, centerPicker: centerPicker,
    invalidatePicker: invalidatePicker
  };
})();
