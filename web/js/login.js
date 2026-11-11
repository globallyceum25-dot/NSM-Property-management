/* The sign-in page: sign in, or, on a new register, create the first Super Admin. */
(function () {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const params = new URLSearchParams(location.search);
  // Only an in-app link (#portfolio, #property/12 ...) may be where we go after
  // signing in, so this page can never send anyone to another site.
  const next = /^#[\w\-/]*$/.test(params.get('next') || '') ? params.get('next') : '';
  const home = '/' + next;

  $('#year').textContent = new Date().getFullYear();

  async function call(method, url, body) {
    const response = await fetch(url, {
      method: method,
      credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined
    });
    let data = {};
    try { data = await response.json(); } catch (e) { /* not JSON */ }
    if (!response.ok) {
      const err = new Error(data.error || 'Something went wrong. Please try again.');
      err.field = data.field;
      throw err;
    }
    return data;
  }

  function show(el, text) {
    el.textContent = text || '';
    el.hidden = !text;
  }

  function busy(button, text) {
    if (text) {
      button.dataset.idle = button.textContent;
      button.textContent = text;
      button.disabled = true;
      button.classList.add('is-busy');
    } else {
      button.textContent = button.dataset.idle || button.textContent;
      button.disabled = false;
      button.classList.remove('is-busy');
    }
  }

  function markInvalid(input, on) {
    const box = input.closest('.field-box');
    if (box) box.classList.toggle('is-invalid', on);
    input.setAttribute('aria-invalid', on ? 'true' : 'false');
  }

  function shake(form) {
    form.classList.remove('shake');
    void form.offsetWidth;
    form.classList.add('shake');
  }

  // Why the person is here, when another page sent them.
  if (params.get('expired')) show($('#login-note'), 'Your session has ended. Sign in again to carry on.');
  else if (params.get('signedout')) show($('#login-note'), 'You have signed out.');

  // Already signed in? Go straight in. A brand-new register? Set it up.
  call('GET', '/api/auth/status').then(function (status) {
    if (status.signedIn) { location.replace(home); return; }
    if (status.needsSetup) {
      $('#signin-view').hidden = true;
      $('#setup-view').hidden = false;
      $('#s-name').focus();
    }
  }).catch(function () { /* the form still works */ });

  // Show / hide a password.
  document.querySelectorAll('[data-reveal]').forEach(function (button) {
    button.addEventListener('click', function () {
      const input = document.getElementById(button.dataset.reveal);
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      button.setAttribute('aria-pressed', String(!showing));
      button.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
      button.querySelector('use').setAttribute('href', showing ? '#i-eye' : '#i-eye-off');
      input.focus();
    });
  });

  // Caps Lock: the commonest reason a right password is "wrong".
  ['keydown', 'keyup'].forEach(function (type) {
    $('#password').addEventListener(type, function (event) {
      if (event.getModifierState) $('#caps-warning').hidden = !event.getModifierState('CapsLock');
    });
  });

  $('#btn-forgot').addEventListener('click', function () {
    const help = $('#forgot-help');
    help.hidden = !help.hidden;
    this.setAttribute('aria-expanded', String(!help.hidden));
  });

  document.querySelectorAll('input').forEach(function (input) {
    input.addEventListener('input', function () { markInvalid(input, false); });
  });

  /* ---------- sign in ---------- */

  $('#login-form').addEventListener('submit', async function (event) {
    event.preventDefault();
    const form = event.target;
    const email = form.email.value.trim();
    const password = form.password.value;
    show($('#login-alert'), '');
    show($('#login-note'), '');
    if (!email || !password) {
      const missing = !email ? form.email : form.password;
      markInvalid(missing, true);
      show($('#login-alert'), !email ? 'Enter your email address.' : 'Enter your password.');
      missing.focus();
      return;
    }
    const button = $('#btn-signin');
    busy(button, 'Signing in…');
    try {
      await call('POST', '/api/auth/login', { email: email, password: password, remember: form.remember.checked });
      button.textContent = 'Welcome';
      location.replace(home);
    } catch (err) {
      busy(button, null);
      show($('#login-alert'), err.message);
      markInvalid(form.password, true);
      shake(form);
      form.password.select();
      form.password.focus();
    }
  });

  /* ---------- first run: the first Super Admin ---------- */

  function score(password) {
    let s = 0;
    if (password.length >= 10) s += 1;
    if (password.length >= 14) s += 1;
    const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(password)).length;
    if (kinds >= 2) s += 1;
    if (kinds >= 3 && password.length >= 12) s += 1;
    return password.length < 10 ? Math.min(s, 1) : s;
  }

  $('#s-password').addEventListener('input', function () {
    const value = this.value;
    const s = value ? score(value) : 0;
    const meter = $('#strength');
    meter.dataset.score = String(s);
    meter.querySelector('i').style.width = (s / 4 * 100) + '%';
    meter.querySelector('.label').textContent = !value
      ? 'At least 10 characters. A short sentence works well.'
      : (value.length < 10 ? (10 - value.length) + ' more characters needed.'
        : ['Weak', 'Weak', 'Fair', 'Good', 'Strong'][s] + '.');
  });

  $('#setup-form').addEventListener('submit', async function (event) {
    event.preventDefault();
    const form = event.target;
    const alert = $('#setup-alert');
    show(alert, '');
    const required = ['name', 'email', 'password', 'confirm', 'setupCode'];
    const empty = required.map((n) => form.elements[n]).filter((el) => !el.value.trim())[0];
    if (empty) {
      markInvalid(empty, true);
      show(alert, 'Fill in every field.');
      empty.focus();
      return;
    }
    if (form.password.value !== form.confirm.value) {
      markInvalid(form.confirm, true);
      show(alert, 'The two passwords do not match.');
      form.confirm.focus();
      return;
    }
    const button = $('#btn-setup');
    busy(button, 'Creating the account…');
    try {
      await call('POST', '/api/auth/setup', {
        name: form.name.value, email: form.email.value, password: form.password.value,
        confirm: form.confirm.value, setupCode: form.setupCode.value
      });
      location.replace('/');
    } catch (err) {
      busy(button, null);
      show(alert, err.message);
      const field = err.field && form.elements[err.field];
      if (field) { markInvalid(field, true); field.focus(); }
      shake(form);
    }
  });
})();
