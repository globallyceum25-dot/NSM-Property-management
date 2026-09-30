/* Master sheets module.
 *
 * Entirely generic: the sheet list, the grid and the add/edit form are all built
 * from the column metadata the server sends, so a new master sheet needs no
 * changes here. Self-contained -- it touches no other part of the app.
 */
window.Masters = (function () {
  'use strict';

  const $ = (selector) => document.querySelector(selector);

  let sheets = [];
  let current = null;       // {key,label,columns,rows,refs,editable,...}
  let filter = '';
  let loaded = false;
  let notify = function () {};
  let onChange = function () {};       // lets the host app re-read the masters

  function init(toastFn, changeFn) {
    notify = toastFn || notify;
    onChange = changeFn || onChange;

    $('#btn-new-master-row').addEventListener('click', () => openRow(null));
    $('#btn-save-master').addEventListener('click', saveRow);
    $('#master-form').addEventListener('submit', (e) => { e.preventDefault(); saveRow(); });
    $('#master-search').addEventListener('input', function (event) {
      filter = event.target.value.toLowerCase();
      renderGrid();
    });

    $('#master-rows').addEventListener('click', function (event) {
      const button = event.target.closest('[data-master-edit],[data-master-delete]');
      if (!button) return;
      if (button.dataset.masterEdit !== undefined) openRow(Number(button.dataset.masterEdit));
      else deleteRow(Number(button.dataset.masterDelete));
    });
  }

  /* ---------- sheet list ---------- */

  async function show() {
    if (!loaded) {
      try {
        sheets = await API.listMasters();
      } catch (err) {
        notify('Could not load master sheets: ' + err.message, true);
        return;
      }
      loaded = true;
      renderNav();
      await select(sheets[0].key);
    } else {
      renderNav();
    }
  }

  function renderNav() {
    const host = $('#masters-nav');
    host.innerHTML = '';
    let lastGroup = null;
    sheets.forEach(function (sheet) {
      if (sheet.group !== lastGroup) {
        const heading = document.createElement('h3');
        heading.textContent = sheet.group;
        host.appendChild(heading);
        lastGroup = sheet.group;
      }
      const button = document.createElement('button');
      button.className = 'master-link' +
        (current && current.key === sheet.key ? ' is-active' : '');
      button.innerHTML = '<span class="ml-label">' + Fmt.esc(sheet.label) + '</span>' +
        '<span class="count">' + sheet.rowCount + '</span>' +
        (sheet.editable ? '' : '<span class="lock" title="System list">&#128274;</span>');
      button.addEventListener('click', () => select(sheet.key));
      host.appendChild(button);
    });
  }

  async function select(key) {
    try {
      current = await API.getMaster(key);
    } catch (err) {
      notify(err.message, true);
      return;
    }
    filter = '';
    $('#master-search').value = '';
    $('#master-title').textContent = current.label;
    $('#master-description').textContent = current.description;
    $('#btn-new-master-row').hidden = !current.editable;
    renderNav();
    renderGrid();
  }

  /* ---------- grid ---------- */

  function gridColumns() {
    return current.columns.filter((c) => c.in_grid !== false);
  }

  function cellText(row, column) {
    if (column.type === 'ref') return row[column.name + '_label'] || '';
    const value = row[column.name];
    if (column.type === 'bool') return value ? 'Yes' : 'No';
    if (value === null || value === undefined || value === '') return '';
    if (column.type === 'number') return String(value);
    return String(value);
  }

  function renderGrid() {
    const columns = gridColumns();
    $('#master-head').innerHTML =
      columns.map((c) => '<th>' + Fmt.esc(c.label) + '</th>').join('') +
      (current.editable ? '<th></th>' : '');

    const rows = current.rows.filter(function (row) {
      if (!filter) return true;
      return columns.some((c) => cellText(row, c).toLowerCase().indexOf(filter) !== -1);
    });

    const body = $('#master-rows');
    body.innerHTML = rows.map(function (row) {
      const cells = columns.map(function (column) {
        const text = Fmt.esc(cellText(row, column));
        if (column.type === 'color') {
          return '<td><span class="sbu-pill"><span class="swatch" style="background:' +
            Fmt.esc(row[column.name]) + '"></span>' + text + '</span></td>';
        }
        if (column.type === 'bool') {
          return '<td>' + (row[column.name]
            ? '<span class="badge ACTIVE">Yes</span>'
            : '<span class="badge">No</span>') + '</td>';
        }
        return '<td>' + text + '</td>';
      }).join('');

      const used = row._used || 0;
      const actions = current.editable
        ? '<td class="row-actions">' +
            '<button class="btn btn-ghost btn-sm" data-master-edit="' + row.id + '">Edit</button> ' +
            '<button class="btn btn-danger btn-sm" data-master-delete="' + row.id + '"' +
              (used ? ' title="Used by ' + used + ' record(s)"' : '') + '>Delete</button>' +
          '</td>'
        : '';
      return '<tr>' + cells + actions + '</tr>';
    }).join('');

    const empty = $('#master-empty');
    empty.hidden = rows.length > 0;
    empty.textContent = current.rows.length
      ? 'No rows match "' + filter + '".'
      : 'This sheet is empty.' + (current.editable ? ' Use + New row to add one.' : '');
  }

  /* ---------- add / edit ---------- */

  function fieldHtml(column, value) {
    const id = 'mf-' + column.name;
    const required = column.required ? ' required' : '';
    const label = '<label for="' + id + '">' + Fmt.esc(column.label) +
      (column.required ? ' <span class="req">*</span>' : '');
    const hint = column.hint ? '<span class="hint">' + Fmt.esc(column.hint) + '</span>' : '';
    const safe = (value === null || value === undefined) ? '' : String(value);

    if (column.type === 'bool') {
      return '<label class="checkbox"><input type="checkbox" id="' + id + '" name="' +
        column.name + '"' + (value ? ' checked' : '') + '> ' + Fmt.esc(column.label) + '</label>';
    }
    if (column.type === 'textarea') {
      return label + '<textarea id="' + id + '" name="' + column.name + '" rows="3"' +
        (column.maxlength ? ' maxlength="' + column.maxlength + '"' : '') + '>' +
        Fmt.esc(safe) + '</textarea>' + hint + '</label>';
    }
    if (column.type === 'enum') {
      return label + '<select id="' + id + '" name="' + column.name + '"' + required + '>' +
        '<option value="">&mdash;</option>' +
        column.options.map((o) => '<option value="' + Fmt.esc(o) + '"' +
          (o === safe ? ' selected' : '') + '>' + Fmt.esc(o) + '</option>').join('') +
        '</select>' + hint + '</label>';
    }
    if (column.type === 'ref') {
      const options = (current.refs[column.ref] || []);
      return label + '<select id="' + id + '" name="' + column.name + '"' + required + '>' +
        '<option value="">&mdash;</option>' +
        options.map((o) => '<option value="' + o.id + '"' +
          (String(o.id) === safe ? ' selected' : '') + '>' + Fmt.esc(o.label) + '</option>').join('') +
        '</select>' + hint + '</label>';
    }
    const type = column.type === 'color' ? 'color'
      : (column.type === 'number' ? 'text' : 'text');
    return label + '<input id="' + id + '" type="' + type + '" name="' + column.name +
      '" value="' + Fmt.esc(safe) + '"' + required +
      (column.readonly ? ' readonly' : '') +
      (column.maxlength ? ' maxlength="' + column.maxlength + '"' : '') +
      (column.type === 'number' ? ' inputmode="decimal"' : '') + '>' + hint + '</label>';
  }

  function openRow(rowId) {
    if (!current.editable) return;
    const row = rowId ? current.rows.filter((r) => r.id === rowId)[0] : null;
    $('#master-modal-title').textContent =
      (row ? 'Edit ' : 'New ') + current.label.replace(/s$/, '').toLowerCase();
    $('#master-form-error').hidden = true;
    $('#master-form').id_value = null;
    $('#master-form').elements.id.value = row ? row.id : '';

    $('#master-fields').innerHTML = current.columns.map(function (column) {
      const value = row ? row[column.name] : column.default;
      return fieldHtml(column, value === undefined ? '' : value);
    }).join('');

    // District drives province, mirroring the property form.
    const driver = current.columns.filter((c) => c.fills)[0];
    if (driver) {
      const select = $('#master-form').elements[driver.name];
      const target = $('#master-form').elements[driver.fills];
      if (select && target) {
        select.addEventListener('change', function () {
          const found = (window.__districts || []).filter(
            (d) => d.district === select.value)[0];
          target.value = found ? found.province : '';
        });
      }
    }

    $('#master-modal').hidden = false;
    const first = $('#master-fields').querySelector('input,select,textarea');
    if (first) setTimeout(() => first.focus(), 50);
  }

  async function saveRow() {
    const form = $('#master-form');
    const errorBox = $('#master-form-error');
    errorBox.hidden = true;
    form.querySelectorAll('.is-invalid').forEach((el) => el.classList.remove('is-invalid'));
    const missing = Array.prototype.slice.call(form.elements)
      .filter((el) => el.name && el.type !== 'hidden' && !el.checkValidity())[0];
    if (missing) {
      const label = (missing.closest('label') && missing.closest('label').firstChild.textContent || missing.name)
        .replace(/\*/g, '').trim();
      showError(form, errorBox, { message: label + ' is required.', field: missing.name });
      return;
    }

    const data = {};
    current.columns.forEach(function (column) {
      const field = form.elements[column.name];
      if (!field) return;
      data[column.name] = column.type === 'bool' ? field.checked : field.value;
    });

    const id = form.elements.id.value;
    const button = $('#btn-save-master');
    button.disabled = true;
    button.textContent = 'Saving\u2026';
    try {
      if (id) await API.updateMaster(current.key, id, data);
      else await API.createMaster(current.key, data);
      $('#master-modal').hidden = true;
      await reload();
      notify(id ? 'Row updated.' : 'Row added.');
    } catch (err) {
      showError(form, errorBox, err);
    } finally {
      button.disabled = false;
      button.textContent = 'Save';
    }
  }

  // Mark the field the server named and bring it into view, so the message is
  // never hidden below the fold of a long form.
  function showError(form, errorBox, err) {
    form.querySelectorAll('.is-invalid').forEach((el) => el.classList.remove('is-invalid'));
    errorBox.textContent = err.message;
    errorBox.hidden = false;
    const field = err.field && form.elements[err.field];
    if (field) {
      field.classList.add('is-invalid');
      field.setAttribute('aria-invalid', 'true');
      field.scrollIntoView({ block: 'center', behavior: 'smooth' });
      field.focus({ preventScroll: true });
    } else {
      errorBox.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  async function deleteRow(rowId) {
    const row = current.rows.filter((r) => r.id === rowId)[0];
    if (!row) return;
    const display = row.name || row.code || row.short_code || ('row ' + rowId);
    if (!window.confirm('Delete "' + display + '" from ' + current.label + '?')) return;
    try {
      await API.deleteMaster(current.key, rowId);
      await reload();
      notify('Row deleted.');
    } catch (err) { notify(err.message, true); }
  }

  async function reload() {
    sheets = await API.listMasters();
    const key = current.key;
    current = await API.getMaster(key);
    renderNav();
    renderGrid();
    try { await onChange(key); } catch (e) { /* host refresh is best-effort */ }
  }

  return { init: init, show: show };
})();
