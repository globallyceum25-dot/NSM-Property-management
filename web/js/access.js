/* Users & access: people, roles and permissions, and the activity log.
 *
 * Self-contained, like the Master sheets module. The host app passes in its
 * toast and its state (the signed-in person, their access, the property types
 * and companies). The server enforces every rule; this screen only offers what
 * the person may do and explains the rest.
 */
window.Access = (function () {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.prototype.slice.call(document.querySelectorAll(selector));
  const esc = (value) => Fmt.esc(value);

  let notify = function () {};
  let app = null;             // the host app's state
  let tab = 'people';
  let users = [];
  let usersLimited = false;
  let roleData = null;        // {modules, roles, assignable, canManage}
  let currentRole = null;     // code of the role in the editor
  let draft = null;           // its levels while being edited
  let comparing = false;
  let personId = null;        // the person open in the drawer
  let personDraft = null;
  let audit = { entries: [], next: null, people: [], loading: false };
  let searchTimer = null;

  function icon(name) {
    return '<svg class="ic"><use href="#i-' + name + '"/></svg>';
  }

  function level(key) {
    return (app.access && app.access.permissions[key]) || 'no';
  }

  function can(key) {
    return level(key) !== 'no';
  }

  function initials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '··';
    return ((parts[0][0] || '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
  }

  // A stable soft colour per person, so the same person looks the same everywhere.
  function hue(text) {
    let h = 0;
    String(text || '').split('').forEach((c) => { h = (h * 31 + c.charCodeAt(0)) % 360; });
    return h;
  }

  function avatar(person, size) {
    return '<span class="avatar' + (size ? ' ' + size : '') + '" style="--h:' + hue(person.email) + '">' +
      esc(initials(person.name)) + '</span>';
  }

  function when(iso) {
    if (!iso) return 'Never';
    const then = new Date(String(iso).replace(' ', 'T').replace(/Z?$/, 'Z'));
    const seconds = (Date.now() - then.getTime()) / 1000;
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return Math.floor(seconds / 60) + ' min ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + ' h ago';
    if (seconds < 172800) return 'Yesterday';
    if (seconds < 7 * 86400) return Math.floor(seconds / 86400) + ' days ago';
    return Fmt.date(then.toISOString().slice(0, 10));
  }

  function clock(iso) {
    const d = new Date(String(iso).replace(' ', 'T').replace(/Z?$/, 'Z'));
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function dayLabel(iso) {
    const d = new Date(String(iso).replace(' ', 'T').replace(/Z?$/, 'Z'));
    const today = new Date();
    const yesterday = new Date(Date.now() - 86400000);
    if (d.toDateString() === today.toDateString()) return 'Today';
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  }

  function setBusy(button, text) {
    if (text) {
      button.dataset.idle = button.innerHTML;
      button.textContent = text;
      button.disabled = true;
    } else {
      button.innerHTML = button.dataset.idle || button.innerHTML;
      button.disabled = false;
    }
  }

  function showError(el, err) {
    el.textContent = err ? err.message || String(err) : '';
    el.hidden = !err;
  }

  /* ---------- set up ---------- */

  function init(toastFn, appState) {
    notify = toastFn || notify;
    app = appState;

    $$('[data-atab]').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.atab)));
    $('#btn-add-person').addEventListener('click', openAddPerson);
    $('#btn-save-person').addEventListener('click', savePerson);
    $('#person-form').addEventListener('submit', (e) => { e.preventDefault(); savePerson(); });
    $('#btn-new-role').addEventListener('click', openNewRole);
    $('#btn-save-role').addEventListener('click', saveNewRole);
    $('#role-form').addEventListener('submit', (e) => { e.preventDefault(); saveNewRole(); });
    $('#btn-close-person').addEventListener('click', closePerson);
    $('#scrim').addEventListener('click', function () { if (!$('#person-drawer').hidden) closePerson(); });
    $('#btn-change-password').addEventListener('click', openPasswordModal);
    $('#btn-my-access').addEventListener('click', openMyAccess);
    $('#btn-save-password').addEventListener('click', savePassword);
    $('#password-form').addEventListener('submit', (e) => { e.preventDefault(); savePassword(); });

    $('#people-search').addEventListener('input', renderPeople);
    $('#people-role').addEventListener('change', renderPeople);
    $('#people-status').addEventListener('change', renderPeople);
    $('#people-rows').addEventListener('click', function (event) {
      const tr = event.target.closest('[data-person]');
      if (tr) openPerson(Number(tr.dataset.person));
    });
    $('#people-rows').addEventListener('keydown', function (event) {
      const tr = event.target.closest('[data-person]');
      if (tr && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        openPerson(Number(tr.dataset.person));
      }
    });

    $('#roles-nav').addEventListener('click', function (event) {
      const b = event.target.closest('[data-role]');
      if (b) selectRole(b.dataset.role);
      if (event.target.closest('[data-compare]')) { comparing = !comparing; renderRoles(); }
    });
    $('#role-editor').addEventListener('click', onEditorClick);
    $('#role-editor').addEventListener('input', function (event) {
      if (event.target.name === 'role-name' || event.target.name === 'role-description') renderSaveBar();
    });

    ['#audit-category', '#audit-person', '#audit-days'].forEach((s) =>
      $(s).addEventListener('change', () => loadAudit(true)));
    $('#audit-search').addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadAudit(true), 250);
    });
    $('#btn-audit-more').addEventListener('click', () => loadAudit(false));

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !$('#person-drawer').hidden && $$('.modal:not([hidden])').length === 0) {
        closePerson();
      }
    });
  }

  function tabs() {
    return [
      ['people', can('users.view')],
      ['roles', can('users.view') || can('roles.manage')],
      ['activity', can('audit.view')]
    ].filter((t) => t[1]).map((t) => t[0]);
  }

  function show() {
    const open = tabs();
    if (open.indexOf(tab) === -1) tab = open[0] || 'people';
    $$('[data-atab]').forEach(function (b) {
      b.hidden = open.indexOf(b.dataset.atab) === -1;
    });
    switchTab(tab);
  }

  function switchTab(name) {
    tab = name;
    $$('[data-atab]').forEach(function (b) {
      const on = b.dataset.atab === name;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-selected', on);
    });
    $('#access-people').hidden = name !== 'people';
    $('#access-roles').hidden = name !== 'roles';
    $('#access-activity').hidden = name !== 'activity';
    $('#btn-add-person').hidden = name !== 'people' || !can('users.create');
    $('#btn-new-role').hidden = name !== 'roles' || !can('roles.manage');
    if (name === 'people') loadPeople();
    if (name === 'roles') loadRoles();
    if (name === 'activity') loadAudit(true);
  }

  async function loadRoleData() {
    roleData = await API.listRoles();
    return roleData;
  }

  function roleOf(code) {
    return roleData && roleData.roles.filter((r) => r.code === code)[0];
  }

  /* ---------- people ---------- */

  async function loadPeople() {
    try {
      const [list] = await Promise.all([API.listUsers(), loadRoleData()]);
      users = list.users;
      usersLimited = list.limited;
    } catch (err) {
      notify(err.message, true);
      return;
    }
    const roleSelect = $('#people-role');
    const chosen = roleSelect.value;
    roleSelect.innerHTML = '<option value="">All roles</option>' + roleData.roles.map((r) =>
      '<option value="' + esc(r.code) + '">' + esc(r.name) + '</option>').join('');
    roleSelect.value = chosen;
    $('#people-limited').hidden = !usersLimited;
    renderPeople();
    if (personId && !$('#person-drawer').hidden) {
      const fresh = users.filter((u) => u.id === personId)[0];
      if (fresh) renderPerson(fresh);
    }
  }

  function statusOf(u) {
    if (u.status === 'off') return { key: 'off', label: 'Switched off' };
    if (u.status === 'locked') return { key: 'locked', label: 'Locked' };
    if (u.mustChangePassword) return { key: 'pending', label: 'Must set a password' };
    return { key: 'active', label: 'Active' };
  }

  function roleUsesScope(code) {
    const role = roleOf(code);
    if (!role) return false;
    return Object.keys(role.permissions).some((k) => role.permissions[k] === 'limited');
  }

  function scopeHtml(u) {
    if (!roleUsesScope(u.role)) return '<span class="muted-inline">All properties</span>';
    const labels = u.scopeLabels.types.map((t) => t.label).concat(u.scopeLabels.companies.map((c) => c.label));
    if (!labels.length) return '<span class="scope-warn">' + icon('shield') + 'Nothing assigned</span>';
    const shown = labels.slice(0, 2).map((l) => '<span class="mini-chip">' + esc(l) + '</span>').join('');
    return shown + (labels.length > 2 ? '<span class="mini-chip more">+' + (labels.length - 2) + '</span>' : '');
  }

  function renderPeople() {
    const term = $('#people-search').value.trim().toLowerCase();
    const role = $('#people-role').value;
    const status = $('#people-status').value;
    const counts = { active: 0, pending: 0, locked: 0, off: 0 };
    users.forEach((u) => { counts[statusOf(u).key] += 1; });

    $('#people-stats').innerHTML = [
      ['active', 'Active', counts.active],
      ['pending', 'Must set a password', counts.pending],
      ['locked', 'Locked', counts.locked],
      ['off', 'Switched off', counts.off]
    ].map((s) => '<button class="stat-chip' + (status === s[0] ? ' is-on' : '') + '" data-status="' + s[0] +
      '"><span class="dot ' + s[0] + '"></span><b>' + s[2] + '</b>' + esc(s[1]) + '</button>').join('');
    $$('#people-stats [data-status]').forEach((b) => b.addEventListener('click', function () {
      $('#people-status').value = $('#people-status').value === b.dataset.status ? '' : b.dataset.status;
      renderPeople();
    }));

    const rows = users.filter(function (u) {
      if (role && u.role !== role) return false;
      if (status && statusOf(u).key !== status) return false;
      if (term && (u.name + ' ' + u.email).toLowerCase().indexOf(term) === -1) return false;
      return true;
    });
    $('#people-rows').innerHTML = rows.map(function (u) {
      const st = statusOf(u);
      return '<tr data-person="' + u.id + '" tabindex="0" class="' + (u.status === 'off' ? 'is-off' : '') + '">' +
        '<td><div class="person-cell">' + avatar(u) + '<div><b>' + esc(u.name) +
          (u.isYou ? ' <span class="you-chip">You</span>' : '') + '</b><small>' + esc(u.email) + '</small></div></div></td>' +
        '<td><span class="role-pill' + (u.protected ? ' is-protected' : '') + '">' +
          (u.protected ? icon('shield') : '') + esc(u.roleLabel) + '</span></td>' +
        '<td class="scope-cell">' + scopeHtml(u) + '</td>' +
        '<td><span class="status-dot ' + st.key + '"><span class="dot ' + st.key + '"></span>' + esc(st.label) + '</span></td>' +
        '<td class="muted-cell">' + esc(when(u.lastLoginAt)) + '</td>' +
        '<td class="row-actions"><span class="circle-btn sm" aria-hidden="true">' + icon('chevron') + '</span></td>' +
      '</tr>';
    }).join('');
    const empty = $('#people-empty');
    empty.hidden = rows.length > 0;
    empty.textContent = users.length ? 'No one matches these filters.' : 'No one has an account yet.';
  }

  /* ---------- one person ---------- */

  function openPerson(id) {
    const u = users.filter((x) => x.id === id)[0];
    if (!u) return;
    personId = id;
    renderPerson(u);
    $('#person-drawer').hidden = false;
    $('#scrim').hidden = false;
  }

  function closePerson() {
    $('#person-drawer').hidden = true;
    if ($('#drawer').hidden) $('#scrim').hidden = true;
    personId = null;
  }

  function roleSummary(code) {
    // As the workbook's Role summary: per module, Full / View only / Partial / No access.
    const role = roleOf(code);
    if (!role) return '';
    return '<ul class="role-summary">' + roleData.modules.map(function (m) {
      const allowed = m.actions.filter((a) => role.permissions[a.key] !== 'no');
      let label = 'No access';
      let cls = 'none';
      if (allowed.length === m.actions.length && allowed.every((a) => role.permissions[a.key] === 'yes')) {
        label = 'Full'; cls = 'full';
      } else if (allowed.length === 1 && /\.view$/.test(allowed[0].key)) {
        label = 'View only'; cls = 'view';
      } else if (allowed.length) { label = 'Partial'; cls = 'partial'; }
      return '<li><span>' + esc(m.label) + '</span><b class="lvl-tag ' + cls + '">' + label + '</b></li>';
    }).join('') + '</ul>';
  }

  function roleSelectHtml(selected, name, disabled) {
    const options = roleData.roles.filter((r) => roleData.assignable.indexOf(r.code) !== -1 || r.code === selected);
    return '<label>Role <span class="req" aria-hidden="true">*</span>' +
      '<select name="' + name + '"' + (disabled ? ' disabled' : '') + '>' +
        (selected ? '' : '<option value="">Choose a role…</option>') +
        options.map((r) => '<option value="' + esc(r.code) + '"' + (r.code === selected ? ' selected' : '') + '>' +
          esc(r.name) + '</option>').join('') +
      '</select></label>' +
      '<p class="role-desc" data-role-desc>' + esc(selected && roleOf(selected) ? roleOf(selected).description : '') + '</p>';
  }

  function scopePickerHtml(scope, disabled, roleCode) {
    const types = app.sbus || [];
    const companies = app.entities || [];
    const chip = (kind, id, label, colour) => {
      const on = scope[kind].indexOf(id) !== -1;
      return '<button type="button" class="chip' + (on ? '' : ' is-off') + '" data-scope="' + kind + '" data-id="' + id + '"' +
        (disabled ? ' disabled' : '') + ' aria-pressed="' + on + '">' +
        (colour ? '<i style="background:' + esc(colour) + '"></i>' : '') + '<span>' + esc(label) + '</span></button>';
    };
    const relevant = roleUsesScope(roleCode);
    return '<fieldset class="scope-box' + (relevant ? '' : ' is-muted') + '"><legend>Data scope</legend>' +
      '<p class="scope-help">' + (relevant
        ? 'Where this role is <b>Limited</b>, the person works only on properties of these property types ' +
          '<b>and</b> owned by these companies. Leave a list empty to allow all of it; with both empty, nothing is in scope.'
        : 'This role reaches every property, so the scope is not used. It is kept in case the role changes.') + '</p>' +
      '<div class="scope-group"><span class="scope-label">Property types</span><div class="chip-set">' +
        (types.map((t) => chip('types', t.id, t.name, t.color)).join('') || '<span class="muted-inline">None defined</span>') +
      '</div></div>' +
      '<div class="scope-group"><span class="scope-label">Owning companies</span><div class="chip-set">' +
        (companies.map((c) => chip('companies', c.id, c.short_code + (c.name !== c.short_code ? ' — ' + c.name : ''))).join('') ||
          '<span class="muted-inline">None defined</span>') +
      '</div></div></fieldset>';
  }

  function wireScope(host, scope, onChange) {
    host.querySelectorAll('[data-scope]').forEach(function (b) {
      b.addEventListener('click', function () {
        const list = scope[b.dataset.scope];
        const id = Number(b.dataset.id);
        const at = list.indexOf(id);
        if (at === -1) list.push(id); else list.splice(at, 1);
        b.classList.toggle('is-off', at !== -1);
        b.setAttribute('aria-pressed', at === -1);
        if (onChange) onChange();
      });
    });
  }

  function renderPerson(u) {
    const st = statusOf(u);
    personDraft = { name: u.name, email: u.email, role: u.role,
                    scope: { types: u.scope.types.slice(), companies: u.scope.companies.slice() } };
    const editable = u.canEdit;
    $('#person-head').innerHTML = avatar(u, 'xl') +
      '<div><h2 id="person-name">' + esc(u.name) + (u.isYou ? ' <span class="you-chip">You</span>' : '') + '</h2>' +
      '<p>' + esc(u.email) + '</p>' +
      '<span class="status-dot ' + st.key + '"><span class="dot ' + st.key + '"></span>' + esc(st.label) +
        (u.lockedUntil ? ' until ' + esc(clock(u.lockedUntil)) : '') + '</span></div>';

    const lockNote = !editable && u.protected
      ? '<p class="access-note">' + icon('shield') + 'Only a Super Admin can change a ' + esc(u.roleLabel) + '.</p>' : '';
    $('#person-body').innerHTML = lockNote +
      '<form class="person-form" id="person-edit" novalidate>' +
        '<div class="grid-2">' +
          '<label>Full name<input name="name" value="' + esc(u.name) + '"' + (editable ? '' : ' disabled') + '></label>' +
          '<label>Email<input name="email" type="email" value="' + esc(u.email) + '"' + (editable ? '' : ' disabled') + '></label>' +
        '</div>' +
        roleSelectHtml(u.role, 'role', !editable || u.isYou) +
        (u.isYou ? '<p class="form-hint">You cannot change your own role; another administrator can.</p>' : '') +
        '<details class="role-summary-box"><summary>What this role can do</summary><div data-role-summary>' +
          roleSummary(u.role) + '</div></details>' +
        '<div data-scope-host>' + scopePickerHtml(personDraft.scope, !editable, u.role) + '</div>' +
        '<p class="form-error" id="person-edit-error" hidden></p>' +
      '</form>' +
      '<section class="detail-section"><h3>Sign-in &amp; security</h3><dl class="detail-grid">' +
        '<dt>Last sign-in</dt><dd>' + esc(u.lastLoginAt ? when(u.lastLoginAt) : 'Never signed in') + '</dd>' +
        '<dt>Signed in now</dt><dd>' + (u.sessions ? u.sessions + ' device' + (u.sessions === 1 ? '' : 's') : 'Nowhere') + '</dd>' +
        '<dt>Password</dt><dd>' + (u.mustChangePassword ? 'Temporary — they must choose their own' : 'Set by them') + '</dd>' +
        '<dt>Account added</dt><dd>' + esc(u.createdAt ? Fmt.date(String(u.createdAt).slice(0, 10)) : '') + '</dd>' +
      '</dl>' +
      (editable && !u.isYou
        ? '<div class="security-actions">' +
            '<button type="button" class="btn btn-ghost btn-sm" data-act="reset">' + icon('key') + 'Reset password</button>' +
            (u.sessions ? '<button type="button" class="btn btn-ghost btn-sm" data-act="signout">' + icon('logout') + 'Sign out everywhere</button>' : '') +
            (u.status === 'locked' ? '<button type="button" class="btn btn-ghost btn-sm" data-act="unlock">' + icon('unlock') + 'Unlock</button>' : '') +
          '</div>'
        : '') +
      '</section>' +
      (u.canDeactivate
        ? '<section class="detail-section danger-zone"><h3>' + (u.isActive ? 'Switch off access' : 'Switch access back on') + '</h3>' +
            '<p>' + (u.isActive
              ? 'They are signed out at once and cannot sign in. Their name stays on everything they did, for the audit trail.'
              : 'They can sign in again with their existing password, with the role and scope above.') + '</p>' +
            '<button type="button" class="btn ' + (u.isActive ? 'btn-danger' : 'btn-dark') + ' btn-sm" data-act="' +
              (u.isActive ? 'off' : 'on') + '">' + icon('power') + (u.isActive ? 'Switch off' : 'Switch on') + '</button>' +
          '</section>'
        : '');

    $('#person-foot').innerHTML = editable
      ? '<span class="save-note" id="person-dirty"></span>' +
        '<button class="btn btn-ghost" data-act="close">Close</button>' +
        '<button class="btn btn-dark" data-act="save" disabled>Save changes</button>'
      : '<button class="btn btn-ghost" data-act="close">Close</button>';

    const form = $('#person-edit');
    const refresh = () => renderPersonDirty(u);
    form.addEventListener('input', function (event) {
      if (event.target.name in personDraft) personDraft[event.target.name] = event.target.value;
      if (event.target.name === 'role') {
        form.querySelector('[data-role-desc]').textContent = roleOf(event.target.value) ? roleOf(event.target.value).description : '';
        form.querySelector('[data-role-summary]').innerHTML = roleSummary(event.target.value);
        form.querySelector('[data-scope-host]').innerHTML = scopePickerHtml(personDraft.scope, !editable, event.target.value);
        wireScope(form.querySelector('[data-scope-host]'), personDraft.scope, refresh);
      }
      refresh();
    });
    form.addEventListener('submit', (e) => { e.preventDefault(); savePersonEdit(u); });
    wireScope(form.querySelector('[data-scope-host]'), personDraft.scope, refresh);
    $('#person-body').querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => personAction(u, b)));
    $('#person-foot').querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => personAction(u, b)));
  }

  function sameList(a, b) {
    return a.slice().sort().join(',') === b.slice().sort().join(',');
  }

  function personChanges(u) {
    const n = [];
    if (personDraft.name.trim() !== u.name) n.push('name');
    if (personDraft.email.trim().toLowerCase() !== u.email) n.push('email');
    if (personDraft.role !== u.role) n.push('role');
    if (!sameList(personDraft.scope.types, u.scope.types) || !sameList(personDraft.scope.companies, u.scope.companies)) n.push('scope');
    return n;
  }

  function renderPersonDirty(u) {
    const changes = personChanges(u);
    const save = $('#person-foot [data-act="save"]');
    if (save) save.disabled = !changes.length;
    const note = $('#person-dirty');
    if (note) note.textContent = changes.length ? 'Unsaved: ' + changes.join(', ') : '';
  }

  async function savePersonEdit(u) {
    const changes = personChanges(u);
    if (!changes.length) return;
    const body = {};
    changes.forEach(function (key) { body[key] = key === 'scope' ? personDraft.scope : personDraft[key]; });
    const button = $('#person-foot [data-act="save"]');
    setBusy(button, 'Saving…');
    try {
      await API.updateUser(u.id, body);
      notify('Saved. Changes apply to ' + u.name.split(' ')[0] + ' straight away.');
      await loadPeople();
    } catch (err) {
      setBusy(button, null);
      showError($('#person-edit-error'), err);
    }
  }

  async function personAction(u, button) {
    const act = button.dataset.act;
    if (act === 'close') { closePerson(); return; }
    if (act === 'save') { savePersonEdit(u); return; }
    try {
      if (act === 'reset') {
        if (!window.confirm('Reset ' + u.name + '’s password?\n\nThey are signed out everywhere and get a new temporary password, which you pass on.')) return;
        setBusy(button, 'Resetting…');
        const result = await API.resetPassword(u.id);
        showSecret(u, result.temporaryPassword, 'New temporary password');
      } else if (act === 'signout') {
        setBusy(button, 'Signing out…');
        await API.signOutUser(u.id);
        notify(u.name + ' is signed out everywhere.');
      } else if (act === 'unlock') {
        setBusy(button, 'Unlocking…');
        await API.unlockUser(u.id);
        notify(u.name + ' can try signing in again.');
      } else if (act === 'off' || act === 'on') {
        if (act === 'off' && !window.confirm('Switch off ' + u.name + '’s access?\n\nThey are signed out at once and cannot sign in until switched back on.')) return;
        setBusy(button, act === 'off' ? 'Switching off…' : 'Switching on…');
        await API.updateUser(u.id, { isActive: act === 'on' });
        notify(act === 'off' ? u.name + ' can no longer sign in.' : u.name + ' can sign in again.');
      }
      await loadPeople();
    } catch (err) {
      setBusy(button, null);
      notify(err.message, true);
    }
  }

  function secretHtml(u, password) {
    return '<p class="temp-lead">Give this to <b>' + esc(u.name) + '</b> in person or by phone — not by email or chat. ' +
      'It works once: when they sign in, they choose their own password.</p>' +
      '<div class="temp-box"><code id="temp-code">' + esc(password) + '</code>' +
        '<button type="button" class="btn btn-ghost btn-sm" id="btn-copy-temp">' + icon('copy') + 'Copy</button></div>' +
      '<dl class="temp-meta"><dt>Sign in at</dt><dd>' + esc(location.origin) + '/login</dd>' +
      '<dt>Email</dt><dd>' + esc(u.email) + '</dd></dl>' +
      '<p class="form-hint">' + icon('shield') + 'This password is not stored anywhere readable and will not be shown again.</p>';
  }

  function wireCopy(host) {
    const copy = host.querySelector('#btn-copy-temp');
    if (!copy) return;
    copy.addEventListener('click', async function () {
      const text = host.querySelector('#temp-code').textContent;
      try {
        await navigator.clipboard.writeText(text);
        copy.innerHTML = icon('check') + 'Copied';
      } catch (e) {
        const range = document.createRange();
        range.selectNodeContents(host.querySelector('#temp-code'));
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
    });
  }

  function showSecret(u, password, title) {
    $('#secret-title').textContent = title;
    $('#secret-body').innerHTML = secretHtml(u, password);
    wireCopy($('#secret-body'));
    $('#secret-modal').hidden = false;
  }

  /* ---------- add a person ---------- */

  let newScope = { types: [], companies: [] };

  async function openAddPerson() {
    if (!roleData) await loadRoleData();
    const form = $('#person-form');
    form.reset();
    form.hidden = false;
    $('#person-created').hidden = true;
    $('#person-modal-foot').hidden = false;
    $('#person-modal-title').textContent = 'Add a person';
    showError($('#person-form-error'), null);
    newScope = { types: [], companies: [] };
    const start = roleData.assignable.indexOf('VIEWER') !== -1 ? 'VIEWER' : '';
    $('#person-role-pick').innerHTML = roleSelectHtml(start, 'role', false) +
      '<details class="role-summary-box"><summary>What this role can do</summary><div data-role-summary>' +
      roleSummary(start) + '</div></details>';
    renderNewScope(start);
    $('#person-role-pick select').addEventListener('change', function (event) {
      const code = event.target.value;
      $('#person-role-pick [data-role-desc]').textContent = roleOf(code) ? roleOf(code).description : '';
      $('#person-role-pick [data-role-summary]').innerHTML = roleSummary(code);
      renderNewScope(code);
    });
    $('#person-modal').hidden = false;
    form.elements.name.focus();
  }

  function renderNewScope(code) {
    $('#person-scope-pick').innerHTML = scopePickerHtml(newScope, false, code);
    wireScope($('#person-scope-pick'), newScope);
  }

  async function savePerson() {
    const form = $('#person-form');
    const data = {
      name: form.elements.name.value.trim(),
      email: form.elements.email.value.trim(),
      role: form.querySelector('select[name="role"]').value,
      scope: newScope
    };
    if (!data.name || !data.email || !data.role) {
      showError($('#person-form-error'), new Error('Enter the name and email, and choose a role.'));
      return;
    }
    const button = $('#btn-save-person');
    setBusy(button, 'Adding…');
    try {
      const result = await API.createUser(data);
      setBusy(button, null);
      form.hidden = true;
      $('#person-modal-title').textContent = result.user.name + ' is added';
      $('#person-created').innerHTML = secretHtml(result.user, result.temporaryPassword) +
        '<div class="modal-foot inline"><button class="btn btn-dark" data-close-modal>Done</button></div>';
      $('#person-created').querySelector('[data-close-modal]').addEventListener('click', () => { $('#person-modal').hidden = true; });
      wireCopy($('#person-created'));
      $('#person-created').hidden = false;
      $('#person-modal-foot').hidden = true;
      loadPeople();
    } catch (err) {
      setBusy(button, null);
      showError($('#person-form-error'), err);
    }
  }

  /* ---------- roles & permissions ---------- */

  async function loadRoles() {
    try {
      await loadRoleData();
    } catch (err) {
      notify(err.message, true);
      return;
    }
    if (!currentRole || !roleOf(currentRole)) currentRole = roleData.roles[0].code;
    draft = Object.assign({}, roleOf(currentRole).permissions);
    renderRoles();
  }

  function editable(role) {
    return roleData.canManage && !role.locked;
  }

  function dirtyKeys() {
    const role = roleOf(currentRole);
    return Object.keys(draft).filter((k) => draft[k] !== role.permissions[k]);
  }

  function selectRole(code) {
    if (code === currentRole && !comparing) return;
    if (dirtyKeys().length && !window.confirm('Discard your unsaved changes to ' + roleOf(currentRole).name + '?')) return;
    currentRole = code;
    comparing = false;
    draft = Object.assign({}, roleOf(code).permissions);
    renderRoles();
  }

  function countLevels(perms) {
    const out = { yes: 0, limited: 0, no: 0 };
    Object.keys(perms).forEach((k) => { out[perms[k]] += 1; });
    return out;
  }

  function renderRoles() {
    $('#roles-nav').innerHTML =
      roleData.roles.map(function (r) {
        const c = countLevels(r.permissions);
        return '<button class="role-link' + (r.code === currentRole && !comparing ? ' is-active' : '') + '" data-role="' + esc(r.code) + '">' +
          '<span class="role-link-name">' + (r.protected ? icon('shield') : '') + esc(r.name) + '</span>' +
          '<span class="role-link-meta">' + r.users + ' ' + (r.users === 1 ? 'person' : 'people') +
            ' · ' + (c.yes + c.limited) + ' of ' + Object.keys(r.permissions).length + ' allowed' +
            (r.isSystem ? '' : ' · <em>Custom</em>') + '</span></button>';
      }).join('') +
      '<button class="role-link compare' + (comparing ? ' is-active' : '') + '" data-compare>' +
        '<span class="role-link-name">' + icon('grid') + 'Compare all roles</span>' +
        '<span class="role-link-meta">The whole matrix, side by side</span></button>';
    if (comparing) { renderCompare(); return; }
    renderEditor();
  }

  function levelButtons(action, value, readOnly) {
    return '<div class="lvl" role="radiogroup" aria-label="' + esc(action.label) + '">' +
      [['no', 'No'], ['limited', 'Limited'], ['yes', 'Yes']].map(function (opt) {
        const disabled = readOnly || (opt[0] === 'limited' && !action.limited);
        return '<button type="button" role="radio" class="lvl-' + opt[0] + (value === opt[0] ? ' is-on' : '') + '"' +
          ' aria-checked="' + (value === opt[0]) + '" data-key="' + action.key + '" data-level="' + opt[0] + '"' +
          (disabled ? ' disabled' : '') +
          (opt[0] === 'limited' && !action.limited ? ' title="Only Yes or No for this action"' : '') + '>' + opt[1] + '</button>';
      }).join('') + '</div>';
  }

  function renderEditor() {
    const role = roleOf(currentRole);
    const readOnly = !editable(role);
    const banner = role.locked
      ? '<p class="access-note">' + icon('lock') + 'Super Admin always has every permission. It cannot be narrowed, so the register can never be locked out.</p>'
      : (!roleData.canManage
        ? '<p class="access-note">' + icon('lock') + 'You can see the roles; only a Super Admin can change them.</p>' : '');
    const head = '<div class="role-head">' +
        '<div class="role-fields">' +
          (readOnly
            ? '<h2>' + esc(role.name) + '</h2><p class="role-desc">' + esc(role.description) + '</p>'
            : '<input class="role-name-input" name="role-name" value="' + esc(role.name) + '" aria-label="Role name" maxlength="60">' +
              '<textarea class="role-desc-input" name="role-description" rows="2" maxlength="400" aria-label="What the role is for">' +
                esc(role.description) + '</textarea>') +
        '</div>' +
        '<div class="role-head-side">' +
          '<span class="role-count">' + role.users + ' ' + (role.users === 1 ? 'person has' : 'people have') + ' this role</span>' +
          (roleData.canManage && !role.isSystem
            ? '<button class="btn btn-ghost btn-sm danger-text" data-delete-role>' + icon('trash') + 'Delete role</button>' : '') +
        '</div>' +
      '</div>';

    const modules = roleData.modules.map(function (m) {
      const rows = m.actions.map(function (a) {
        const value = draft[a.key];
        const changed = value !== role.permissions[a.key];
        return '<div class="perm-row' + (changed ? ' is-changed' : '') + '">' +
          '<div class="perm-text"><b>' + esc(a.label) +
            (a.status === 'coming' ? ' <span class="soon-chip">Not built yet</span>' : '') + '</b>' +
            '<span>' + esc(a.description) + '</span>' +
            (value === 'limited' ? '<span class="limited-note">' + icon('shield') + 'Limited: ' + esc(a.limited) + '</span>' : '') +
          '</div>' + levelButtons(a, value, readOnly) + '</div>';
      }).join('');
      const on = m.actions.filter((a) => draft[a.key] !== 'no').length;
      return '<section class="perm-module"><header><div><h3>' + esc(m.label) + '</h3><p>' + esc(m.description) + '</p></div>' +
        '<span class="perm-count' + (on ? '' : ' is-zero') + '">' + on + ' / ' + m.actions.length + '</span>' +
        (readOnly ? '' : '<div class="perm-bulk"><button type="button" data-module-all="' + m.key + '" data-level="yes">All</button>' +
          '<button type="button" data-module-all="' + m.key + '" data-level="no">None</button></div>') +
        '</header>' + rows + '</section>';
    }).join('');

    $('#role-editor').innerHTML = banner + head + '<div class="perm-legend">' +
        '<span><i class="lvl-dot yes"></i><b>Yes</b> for everything in reach</span>' +
        '<span><i class="lvl-dot limited"></i><b>Limited</b> to their scope or their own uploads</span>' +
        '<span><i class="lvl-dot no"></i><b>No</b> — not offered</span></div>' +
      modules + '<div class="save-bar" id="role-save-bar" hidden></div>';
    renderSaveBar();
  }

  function renderSaveBar() {
    const bar = $('#role-save-bar');
    if (!bar) return;
    const role = roleOf(currentRole);
    const nameInput = $('#role-editor [name="role-name"]');
    const descInput = $('#role-editor [name="role-description"]');
    const textChanged = nameInput && (nameInput.value.trim() !== role.name || descInput.value.trim() !== role.description);
    const n = dirtyKeys().length;
    bar.hidden = !n && !textChanged;
    bar.innerHTML = '<span>' + (n ? n + ' permission' + (n === 1 ? '' : 's') + ' changed' : 'Details changed') +
        ' · applies to ' + role.users + ' ' + (role.users === 1 ? 'person' : 'people') + ' at once</span>' +
      '<button class="btn btn-ghost btn-sm" data-discard>Discard</button>' +
      '<button class="btn btn-dark btn-sm" data-save-role>Save changes</button>';
  }

  async function onEditorClick(event) {
    const lvl = event.target.closest('[data-key][data-level]');
    if (lvl && !lvl.disabled) {
      draft[lvl.dataset.key] = lvl.dataset.level;
      keepScroll(renderEditor);
      return;
    }
    const bulk = event.target.closest('[data-module-all]');
    if (bulk) {
      const m = roleData.modules.filter((x) => x.key === bulk.dataset.moduleAll)[0];
      m.actions.forEach((a) => { draft[a.key] = bulk.dataset.level; });
      keepScroll(renderEditor);
      return;
    }
    if (event.target.closest('[data-discard]')) {
      draft = Object.assign({}, roleOf(currentRole).permissions);
      renderEditor();
      return;
    }
    if (event.target.closest('[data-save-role]')) { saveRole(event.target.closest('[data-save-role]')); return; }
    if (event.target.closest('[data-delete-role]')) deleteRole();
  }

  function keepScroll(fn) {
    const host = document.getElementById('view-access');
    const top = host ? host.scrollTop : 0;
    fn();
    if (host) host.scrollTop = top;
  }

  async function saveRole(button) {
    const role = roleOf(currentRole);
    const body = { permissions: {} };
    dirtyKeys().forEach((k) => { body.permissions[k] = draft[k]; });
    const nameInput = $('#role-editor [name="role-name"]');
    if (nameInput) {
      body.name = nameInput.value.trim();
      body.description = $('#role-editor [name="role-description"]').value.trim();
    }
    setBusy(button, 'Saving…');
    try {
      await API.updateRole(role.code, body);
      notify(role.name + ' is saved. It applies to its people straight away.');
      await loadRoles();
    } catch (err) {
      setBusy(button, null);
      notify(err.message, true);
    }
  }

  async function deleteRole() {
    const role = roleOf(currentRole);
    if (!window.confirm('Delete the ' + role.name + ' role?')) return;
    try {
      await API.deleteRole(role.code);
      notify('Deleted the ' + role.name + ' role.');
      currentRole = null;
      await loadRoles();
    } catch (err) {
      notify(err.message, true);
    }
  }

  function renderCompare() {
    const mark = { yes: '<span class="cmp yes" title="Yes">' + icon('check') + '</span>',
                   limited: '<span class="cmp limited" title="Limited">L</span>',
                   no: '<span class="cmp no" title="No">–</span>' };
    const head = '<tr><th>Module and action</th>' + roleData.roles.map((r) =>
      '<th><button class="link-btn" data-role="' + esc(r.code) + '">' + esc(r.name) + '</button></th>').join('') + '</tr>';
    const body = roleData.modules.map(function (m) {
      return '<tr class="cmp-module"><th colspan="' + (roleData.roles.length + 1) + '">' + esc(m.label) + '</th></tr>' +
        m.actions.map((a) => '<tr><td>' + esc(a.label) + (a.status === 'coming' ? ' <span class="soon-chip">Not built yet</span>' : '') +
          '</td>' + roleData.roles.map((r) => '<td>' + mark[r.permissions[a.key]] + '</td>').join('') + '</tr>').join('');
    }).join('');
    $('#role-editor').innerHTML = '<div class="role-head"><div class="role-fields"><h2>All roles, side by side</h2>' +
        '<p class="role-desc">' + mark.yes + ' Yes &nbsp; ' + mark.limited + ' Limited &nbsp; ' + mark.no + ' No. ' +
        'Choose a role name to edit it.</p></div></div>' +
      '<div class="table-wrap"><table class="grid cmp-table"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
    $('#role-editor').querySelectorAll('[data-role]').forEach((b) => b.addEventListener('click', () => selectRole(b.dataset.role)));
  }

  function openNewRole() {
    const form = $('#role-form');
    form.reset();
    showError($('#role-form-error'), null);
    $('#role-copy-from').innerHTML = '<option value="">No access (start empty)</option>' +
      roleData.roles.filter((r) => !r.locked).map((r) => '<option value="' + esc(r.code) + '">' + esc(r.name) + '</option>').join('');
    $('#role-modal').hidden = false;
    form.elements.name.focus();
  }

  async function saveNewRole() {
    const form = $('#role-form');
    const button = $('#btn-save-role');
    setBusy(button, 'Creating…');
    try {
      const role = await API.createRole({
        name: form.elements.name.value.trim(),
        description: form.elements.description.value.trim(),
        copyFrom: form.elements.copyFrom.value
      });
      setBusy(button, null);
      $('#role-modal').hidden = true;
      notify('Created the ' + role.name + ' role. Set what it may do, then save.');
      currentRole = role.code;
      comparing = false;
      await loadRoles();
    } catch (err) {
      setBusy(button, null);
      showError($('#role-form-error'), err);
    }
  }

  /* ---------- activity ---------- */

  const ACTION_TEXT = {
    'auth.sign_in': 'signed in', 'auth.sign_out': 'signed out', 'auth.failed': 'sign-in failed',
    'auth.locked': 'account locked', 'auth.password_change': 'changed their password',
    'user.create': 'added a person', 'user.update': 'changed a person', 'user.activate': 'switched access on',
    'user.deactivate': 'switched access off', 'user.password_reset': 'reset a password',
    'user.sign_out': 'signed a person out', 'user.unlock': 'unlocked an account',
    'role.create': 'created a role', 'role.update': 'changed a role', 'role.delete': 'deleted a role',
    'property.create': 'added a property', 'property.update': 'changed a property', 'property.delete': 'deleted a property',
    'document.upload': 'attached a document', 'document.delete': 'deleted a document',
    'bulk.import': 'imported properties', 'type.create': 'added a property type', 'type.update': 'changed a property type',
    'type.delete': 'deleted a property type', 'company.create': 'added a company', 'company.update': 'changed a company',
    'company.delete': 'deleted a company', 'master.create': 'added a master row', 'master.update': 'changed a master row',
    'master.delete': 'deleted a master row'
  };
  const CATEGORY_ICON = { auth: 'key', user: 'users', role: 'shield', property: 'home', document: 'file',
                          bulk: 'upload', type: 'building', company: 'landmark', master: 'database' };

  async function loadAudit(reset) {
    if (audit.loading) return;
    audit.loading = true;
    const filters = {
      category: $('#audit-category').value, user_id: $('#audit-person').value,
      days: $('#audit-days').value, q: $('#audit-search').value.trim(), limit: 60
    };
    if (!reset && audit.next) filters.before = audit.next;
    try {
      const result = await API.listAudit(filters);
      audit.entries = reset ? result.entries : audit.entries.concat(result.entries);
      audit.next = result.nextBefore;
      const select = $('#audit-person');
      const chosen = select.value;
      select.innerHTML = '<option value="">Anyone</option>' + result.people.map((p) =>
        '<option value="' + p.id + '">' + esc(p.name) + '</option>').join('');
      select.value = chosen;
      renderAudit();
    } catch (err) {
      notify(err.message, true);
    } finally {
      audit.loading = false;
    }
  }

  function renderAudit() {
    let lastDay = '';
    $('#audit-list').innerHTML = audit.entries.map(function (e) {
      const category = e.action.split('.')[0];
      const day = dayLabel(e.at);
      const header = day !== lastDay ? '<li class="audit-day">' + esc(day) + '</li>' : '';
      lastDay = day;
      const bad = /failed|locked|delete|deactivate/.test(e.action);
      const who = e.userName
        ? avatar({ name: e.userName, email: e.userEmail || e.userName }, 'sm') + '<b>' + esc(e.userName) + '</b>'
        : '<span class="avatar sm anon">?</span><b>Someone</b>';
      return header + '<li class="audit-item' + (bad ? ' is-alert' : '') + '">' +
        '<span class="audit-icon cat-' + esc(category) + '">' + icon(CATEGORY_ICON[category] || 'activity') + '</span>' +
        '<div class="audit-main"><p class="audit-line">' + who + ' ' + esc(ACTION_TEXT[e.action] || e.action) +
          (e.target ? ' <span class="audit-target">' + esc(e.target) + '</span>' : '') + '</p>' +
          (e.detail ? '<p class="audit-detail">' + esc(e.detail) + '</p>' : '') + '</div>' +
        '<span class="audit-when" title="' + esc(e.at) + (e.ip ? ' · from ' + esc(e.ip) : '') + '">' + esc(clock(e.at)) + '</span>' +
      '</li>';
    }).join('');
    $('#audit-empty').hidden = audit.entries.length > 0;
    $('#btn-audit-more').hidden = !audit.next;
  }

  /* ---------- your own access ---------- */

  const LEVEL_TAG = {
    yes: '<span class="my-lvl yes">' + '<svg class="ic"><use href="#i-check"/></svg>Yes</span>',
    limited: '<span class="my-lvl limited"><svg class="ic"><use href="#i-shield"/></svg>Limited</span>',
    no: '<span class="my-lvl no">No</span>'
  };

  // The catalog describes "the person"; here it is about the reader.
  function forYou(text) {
    return String(text || '').replace(/the person's/g, 'your').replace(/\btheir\b/g, 'your')
      .replace(/\bthey\b/g, 'you');
  }

  function moduleTag(actions) {
    const allowed = actions.filter((a) => a.level !== 'no');
    if (!allowed.length) return '<b class="lvl-tag none">No access</b>';
    if (allowed.length === actions.length && allowed.every((a) => a.level === 'yes')) return '<b class="lvl-tag full">Full</b>';
    if (allowed.length === 1 && /\.view$/.test(allowed[0].key)) return '<b class="lvl-tag view">View only</b>';
    return '<b class="lvl-tag partial">Partial</b>';
  }

  function myScopeHtml(mine) {
    if (!mine.usesScope) {
      return '<div class="my-scope is-all">' + icon('check') +
        '<div><b>Every property</b><span>Nothing in your role is limited to a scope.</span></div></div>';
    }
    const types = mine.scope.types.map((t) => '<span class="mini-chip">' + esc(t.label) + '</span>').join('');
    const companies = mine.scope.companies.map((c) => '<span class="mini-chip">' + esc(c.label) + '</span>').join('');
    if (!types && !companies) {
      return '<div class="my-scope is-empty">' + icon('shield') +
        '<div><b>No scope assigned yet</b><span>Where your role says <em>Limited</em>, you can’t reach any property ' +
        'until your administrator assigns you property types or owning companies.</span></div></div>';
    }
    return '<div class="my-scope">' + icon('shield') + '<div><b>Your scope</b>' +
      '<span>Where your role says <em>Limited</em>, you work on properties of</span>' +
      '<div class="my-scope-row"><small>Property types</small>' + (types || '<span class="muted-inline">any type</span>') + '</div>' +
      '<div class="my-scope-row"><small>Owned by</small>' + (companies || '<span class="muted-inline">any company</span>') + '</div>' +
      '</div></div>';
  }

  async function openMyAccess() {
    document.querySelectorAll('.popover').forEach((p) => { p.hidden = true; });
    const body = $('#my-access-body');
    body.innerHTML = '<p class="empty">Loading your access…</p>';
    $('#my-access-modal').hidden = false;
    let mine;
    try {
      mine = await API.myAccess();
    } catch (err) {
      body.innerHTML = '<p class="form-error">' + esc(err.message) + '</p>';
      return;
    }
    const all = [].concat.apply([], mine.modules.map((m) => m.actions)).filter((a) => a.status !== 'coming');
    const yes = all.filter((a) => a.level === 'yes').length;
    const limited = all.filter((a) => a.level === 'limited').length;
    body.innerHTML =
      '<div class="my-role">' + avatar(app.user, 'xl') +
        '<div><span class="my-kicker">Your role</span><h3>' + esc(mine.role.name) + '</h3>' +
        '<p>' + esc(mine.role.description) + '</p></div></div>' +
      myScopeHtml(mine) +
      '<p class="my-count">You can do <b>' + (yes + limited) + ' of ' + all.length + '</b> things in the register' +
        (limited ? ': ' + yes + ' everywhere, ' + limited + ' within your scope.' : '.') + '</p>' +
      mine.modules.map(function (m) {
        const actions = m.actions.filter((a) => a.status !== 'coming');
        if (!actions.length) return '';
        return '<section class="my-module"><header><h4>' + esc(m.label) + '</h4>' + moduleTag(actions) + '</header>' +
          '<ul>' + actions.map((a) => '<li class="' + (a.level === 'no' ? 'is-no' : '') + '">' +
            '<div><b>' + esc(a.label) + '</b><span>' + esc(a.description) + '</span>' +
            (a.level === 'limited' ? '<span class="limited-note">' + icon('shield') + esc(forYou(a.limited)) + '</span>' : '') +
            '</div>' + LEVEL_TAG[a.level] + '</li>').join('') + '</ul></section>';
      }).join('');
  }

  /* ---------- your own password ---------- */

  function openPasswordModal() {
    const form = $('#password-form');
    form.reset();
    form.elements.username.value = app.user ? app.user.email : '';
    showError($('#password-form-error'), null);
    document.querySelectorAll('.popover').forEach((p) => { p.hidden = true; });
    $('#password-modal').hidden = false;
    form.elements.current.focus();
  }

  async function savePassword() {
    const form = $('#password-form');
    const data = { current: form.elements.current.value, password: form.elements.password.value,
                   confirm: form.elements.confirm.value };
    if (data.password !== data.confirm) {
      showError($('#password-form-error'), new Error('The two new passwords do not match.'));
      return;
    }
    const button = $('#btn-save-password');
    setBusy(button, 'Changing…');
    try {
      await API.changePassword(data);
      setBusy(button, null);
      $('#password-modal').hidden = true;
      notify('Password changed. Your other devices are signed out.');
    } catch (err) {
      setBusy(button, null);
      showError($('#password-form-error'), err);
    }
  }

  return { init: init, show: show };
})();
