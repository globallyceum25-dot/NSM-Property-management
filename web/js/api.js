/* Thin fetch wrapper + shared formatting helpers. */
window.API = (function () {
  async function request(method, url, body, isForm) {
    const options = { method: method, headers: {} };
    if (isForm) {
      options.body = body;                 // let the browser set the boundary
    } else if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(url, options);
    const text = await response.text();
    let payload = null;
    if (text) {
      try { payload = JSON.parse(text); } catch (e) { payload = { error: text }; }
    }
    if (!response.ok) {
      const err = new Error((payload && payload.error) || ('Request failed (' + response.status + ')'));
      err.status = response.status;
      err.field = payload && payload.field;
      throw err;
    }
    return payload;
  }

  function qs(params) {
    const parts = [];
    Object.keys(params).forEach(function (key) {
      const value = params[key];
      if (value !== undefined && value !== null && value !== '') {
        parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(value));
      }
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  return {
    reference: () => request('GET', '/api/reference'),
    listSbus: () => request('GET', '/api/sbus'),
    createSbu: (data) => request('POST', '/api/sbus', data),
    updateSbu: (id, data) => request('PUT', '/api/sbus/' + id, data),
    deleteSbu: (id) => request('DELETE', '/api/sbus/' + id),

    listEntities: () => request('GET', '/api/legal-entities'),
    createEntity: (data) => request('POST', '/api/legal-entities', data),
    updateEntity: (id, data) => request('PUT', '/api/legal-entities/' + id, data),
    deleteEntity: (id) => request('DELETE', '/api/legal-entities/' + id),

    listProperties: (filters) => request('GET', '/api/properties' + qs(filters || {})),
    getProperty: (id) => request('GET', '/api/properties/' + id),
    createProperty: (data) => request('POST', '/api/properties', data),
    updateProperty: (id, data) => request('PUT', '/api/properties/' + id, data),
    deleteProperty: (id) => request('DELETE', '/api/properties/' + id),

    addDocument: (propertyId, formData) =>
      request('POST', '/api/properties/' + propertyId + '/documents', formData, true),
    deleteDocument: (id) => request('DELETE', '/api/documents/' + id),

    stats: () => request('GET', '/api/stats')
  };
})();

window.Fmt = (function () {
  const NUM = new Intl.NumberFormat('en-LK');

  function num(value, digits) {
    if (value === null || value === undefined || value === '') return '';
    const n = Number(value);
    if (!isFinite(n)) return '';
    return n.toLocaleString('en-LK', {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits === undefined ? 2 : digits
    });
  }

  function money(value, currency) {
    if (value === null || value === undefined || value === '') return '';
    return (currency || 'LKR') + ' ' + num(value, 2);
  }

  function coords(lat, lng) {
    if (lat === null || lng === null) return '';
    return Number(lat).toFixed(5) + ', ' + Number(lng).toFixed(5);
  }

  function extent(value, unit, labels) {
    if (value === null || value === undefined || value === '') return '';
    return num(value) + ' ' + (labels[unit] || unit || '').toLowerCase();
  }

  function date(value) {
    if (!value) return '';
    const d = new Date(value + 'T00:00:00');
    if (isNaN(d.getTime())) return value;
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  }

  function daysUntil(value) {
    if (!value) return null;
    const target = new Date(value + 'T00:00:00');
    if (isNaN(target.getTime())) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((target - today) / 86400000);
  }

  function fileSize(bytes) {
    if (!bytes && bytes !== 0) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function esc(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  return { num: num, money: money, coords: coords, extent: extent, date: date,
           daysUntil: daysUntil, fileSize: fileSize, esc: esc, NUM: NUM };
})();
