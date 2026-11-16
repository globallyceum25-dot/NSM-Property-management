/* Test data: the Real data / Test data switch, and the banner shown while
 * looking at test data. The server keeps the two apart; this only switches
 * which one the signed-in person sees, then reloads so every page follows. */
window.TestData = (function () {
  'use strict';

  const $ = (s) => document.querySelector(s);
  let notify = function () {};
  let on = false;

  function init(toastFn, state) {
    notify = toastFn || notify;
    on = !!(state.user && state.user.testMode);
    document.body.classList.toggle('test-mode', on);
    document.querySelectorAll('#data-switch [data-mode]').forEach(function (b) {
      const mine = (b.dataset.mode === 'test') === on;
      b.classList.toggle('is-on', mine);
      b.setAttribute('aria-checked', mine);
      b.addEventListener('click', function () { if (!mine) switchTo(b.dataset.mode === 'test', b); });
    });
    $('#btn-test-off').addEventListener('click', function () { switchTo(false, this); });
    $('#btn-test-load').addEventListener('click', function () { load(this, false); });
    $('#btn-test-reset').addEventListener('click', function () { load(this, true); });
    $('#btn-test-remove').addEventListener('click', remove);
    if (on) banner();
  }

  async function banner() {
    $('#test-banner').hidden = false;
    let s;
    try { s = await API.testData(); } catch (err) { return; }
    $('#test-banner-text').innerHTML = s.properties
      ? '<b>Test data.</b> You are looking at ' + s.properties + ' test properties, ' + s.documents + ' documents and ' +
        s.entries + ' finance entries. Real data is hidden, and anything you add now is saved as test data.'
      : '<b>Test data.</b> There is no test data yet.' + (s.canManage ? ' Load a ready-made set to try every section.'
        : ' Ask an administrator to load it.');
    $('#btn-test-load').hidden = !s.canManage || !!s.properties;
    $('#btn-test-reset').hidden = !s.canManage || !s.properties;
    $('#btn-test-remove').hidden = !s.canManage || !s.properties;
  }

  function busy(button, text) {
    button.disabled = true;
    button.textContent = text;
  }

  async function switchTo(test, button) {
    if (button) button.disabled = true;
    try {
      await API.setTestMode(test);
      location.reload();
    } catch (err) {
      if (button) button.disabled = false;
      notify(err.message, true);
    }
  }

  async function load(button, reset) {
    if (reset && !window.confirm('Reset the test data? Every test property, document and finance entry is replaced ' +
        'with a fresh set — including anything added while testing. Real data is not touched.')) return;
    busy(button, reset ? 'Resetting…' : 'Loading…');
    try {
      await API.loadTestData();
      location.reload();
    } catch (err) {
      button.disabled = false;
      notify(err.message, true);
    }
  }

  async function remove() {
    if (!window.confirm('Remove all test data? Every test property with its documents, files and finance entries is ' +
        'deleted. Real data is not touched.')) return;
    busy($('#btn-test-remove'), 'Removing…');
    try {
      await API.removeTestData();
      location.reload();
    } catch (err) {
      $('#btn-test-remove').disabled = false;
      notify(err.message, true);
    }
  }

  return { init: init };
})();
