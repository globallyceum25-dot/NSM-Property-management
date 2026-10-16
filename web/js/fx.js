/* Motion: a few small effects that explain change rather than decorate.
 *
 *   transition(fn)  module switches cross-fade (View Transitions API)
 *   countUp(...)    figures run from their old value to the new one
 *   rise(el)        a container's items arrive one after another
 *   draw(el)        charts draw themselves in, once per visit
 *   spotlight       a soft glow follows the pointer across summary cards
 *   scroll shadow   the header lifts once content scrolls beneath it
 *
 * Everything is skipped when the device asks for reduced motion.
 */
window.Fx = (function () {
  'use strict';

  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const calm = () => reduce.matches;

  /* ---------- module switches ---------- */

  function transition(update) {
    if (calm() || !document.startViewTransition) { update(); return; }
    document.startViewTransition(update);
  }

  /* ---------- figures that count ---------- */

  const shown = new Map();     // last value shown, per figure, so a filter tweens from it
  const NUM = new Intl.NumberFormat('en-LK', { maximumFractionDigits: 0 });

  function countUp(root, selector) {
    if (!root) return;
    root.querySelectorAll(selector).forEach(function (el, i) {
      const text = el.textContent.trim();
      if (!/^\d[\d,]*$/.test(text)) return;   // whole numbers only; units stay as written
      const to = Number(text.replace(/,/g, ''));
      const key = selector + '#' + i;
      const from = shown.has(key) ? shown.get(key) : 0;
      shown.set(key, to);
      if (calm() || from === to) return;
      const start = performance.now();
      const duration = 700;
      el.textContent = NUM.format(from);
      (function frame(now) {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 3);
        el.textContent = NUM.format(from + (to - from) * eased);
        if (t < 1) requestAnimationFrame(frame);
        else el.textContent = text;            // finish on the exact original text
      })(start);
    });
  }

  /* ---------- items arriving in turn ---------- */

  function rise(container, limit) {
    if (!container || calm()) return;
    const items = Array.prototype.filter.call(container.children, (el) => !el.hidden);
    items.forEach((el) => el.classList.remove('fx-rise'));
    void container.offsetWidth;                // one reflow, so the animation restarts
    items.forEach(function (el, i) {
      el.style.setProperty('--fx-i', Math.min(i, limit || 12));
      el.classList.add('fx-rise');
      el.addEventListener('animationend', () => el.classList.remove('fx-rise'), { once: true });
    });
  }

  /* ---------- charts drawing in ---------- */

  function draw(root) {
    if (!root || calm()) return;
    root.classList.remove('fx-draw');
    void root.offsetWidth;
    root.classList.add('fx-draw');
    clearTimeout(root.__fxDraw);
    root.__fxDraw = setTimeout(() => root.classList.remove('fx-draw'), 1800);
  }

  /* ---------- the pointer spotlight ---------- */

  const SPOT = '.kpi, .signal, .tile';

  document.addEventListener('pointermove', function (event) {
    if (event.pointerType !== 'mouse') return;
    const el = event.target.closest && event.target.closest(SPOT);
    if (!el) return;
    const box = el.getBoundingClientRect();
    el.style.setProperty('--mx', (event.clientX - box.left) + 'px');
    el.style.setProperty('--my', (event.clientY - box.top) + 'px');
  }, { passive: true });

  /* ---------- the header's shadow once content scrolls under it ---------- */

  let ticking = false;
  document.addEventListener('scroll', function (event) {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      ticking = false;
      const bar = document.querySelector('.topbar');
      if (!bar) return;
      const target = event.target === document ? document.scrollingElement : event.target;
      const scrolled = (target && target.scrollTop > 4) ||
        (document.scrollingElement && document.scrollingElement.scrollTop > 4);
      bar.classList.toggle('is-scrolled', !!scrolled);
    });
  }, { capture: true, passive: true });

  return { calm: calm, transition: transition, countUp: countUp, rise: rise, draw: draw };
})();
