/* Progressive enhancements: motion preference, short reveals, project filter.
   Every feature is optional; pages stay usable when this file or Motion fails. */
(function () {
  'use strict';

  var root = document.documentElement;
  var STORAGE_KEY = 'aw-motion-preference';
  var media = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var stored = '';

  try {
    stored = window.localStorage.getItem(STORAGE_KEY) || '';
  } catch (error) {
    stored = '';
  }

  var prefersReduced = stored === 'reduce';

  function reduceMotion() {
    return Boolean((media && media.matches) || prefersReduced);
  }

  function applyMotionPreference() {
    var reduced = reduceMotion();
    root.classList.toggle('reduce-motion', reduced);
    document.querySelectorAll('[data-motion-toggle]').forEach(function (toggle) {
      toggle.setAttribute('aria-checked', reduced ? 'true' : 'false');
      if (media && media.matches) {
        toggle.setAttribute('title', '系统已启用减弱动效');
      } else {
        toggle.removeAttribute('title');
      }
      var state = toggle.querySelector('[data-motion-state]');
      if (state) {
        state.textContent = reduced ? '开' : '关';
      }
    });
  }

  function connectMotionToggle() {
    document.querySelectorAll('[data-motion-toggle]').forEach(function (toggle) {
      toggle.addEventListener('click', function () {
        if (media && media.matches) {
          applyMotionPreference();
          return;
        }
        prefersReduced = !prefersReduced;
        try {
          window.localStorage.setItem(STORAGE_KEY, prefersReduced ? 'reduce' : 'full');
        } catch (error) {
          /* Private mode may refuse storage; the in-page preference still applies. */
        }
        applyMotionPreference();
      });
    });
  }

  function canAnimate() {
    return !reduceMotion()
      && typeof window.Motion !== 'undefined'
      && typeof window.Motion.animate === 'function';
  }

  function reveal(selector, distance) {
    if (!canAnimate()) {
      return;
    }
    var nodes = Array.prototype.slice.call(document.querySelectorAll(selector));
    if (!nodes.length) {
      return;
    }
    try {
      var options = { duration: 0.24, ease: 'easeOut' };
      if (typeof window.Motion.stagger === 'function') {
        options.delay = window.Motion.stagger(0.035);
      }
      window.Motion.animate(nodes, { opacity: [0, 1], y: [distance || 8, 0] }, options);
    } catch (error) {
      /* Content is already visible; never block on animation. */
    }
  }

  function connectProjectFilter() {
    var search = document.getElementById('project-search');
    var status = document.getElementById('status-filter');
    var list = document.getElementById('project-list');
    var empty = document.getElementById('project-empty');
    var count = document.getElementById('project-count');
    var reset = document.getElementById('clear-filters');

    if (!search || !status || !list) {
      return;
    }

    var items = Array.prototype.slice.call(list.querySelectorAll('.project-item'));
    if (!items.length) {
      return;
    }

    function applyFilter() {
      var term = search.value.trim().toLowerCase();
      var state = status.value;
      var visible = 0;

      items.forEach(function (item) {
        var name = (item.getAttribute('data-search') || item.getAttribute('data-name') || '').toLowerCase();
        var itemState = item.getAttribute('data-status') || '';
        var matches = (!term || name.indexOf(term) !== -1)
          && (state === 'all' || state === itemState);
        item.hidden = !matches;
        if (matches) {
          visible += 1;
        }
      });

      if (count) {
        count.textContent = (term || state !== 'all')
          ? visible + ' / ' + items.length + ' 个项目'
          : items.length + ' 个项目';
      }
      if (empty) {
        empty.hidden = visible !== 0;
      }
    }

    search.addEventListener('input', applyFilter);
    status.addEventListener('change', applyFilter);
    if (reset) {
      reset.addEventListener('click', function () {
        search.value = '';
        status.value = 'all';
        applyFilter();
        search.focus();
      });
    }
  }

  function init() {
    applyMotionPreference();
    connectMotionToggle();
    connectProjectFilter();
    reveal('.page-alerts .alert', 4);
    reveal('.content > .card, .content > .home-grid > .card, .content > .grid > .card', 8);
    reveal('.project-list > .project-item', 6);
    reveal('.auth-card', 6);
  }

  if (media) {
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', applyMotionPreference);
    } else if (typeof media.addListener === 'function') {
      media.addListener(applyMotionPreference);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
