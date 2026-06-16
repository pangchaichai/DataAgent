/**
 * Client-side hash router for DataAgent multi-page SPA.
 * Routes: #/dashboard, #/sources, #/rules, #/chat, #/audit
 */
const Router = (() => {
  const _routes = {};
  let _currentRoute = null;
  let _mountEl = null;
  let _onNavigate = null;

  function init(mountId, defaultRoute) {
    _mountEl = document.getElementById(mountId);
    window.addEventListener('hashchange', _handleHash);
    if (!location.hash || location.hash === '#' || location.hash === '#/') {
      location.hash = defaultRoute || '#/chat';
    } else {
      _handleHash();
    }
  }

  function register(path, renderFn) {
    _routes[path] = renderFn;
  }

  function onNavigate(fn) {
    _onNavigate = fn;
  }

  function navigateTo(path) {
    location.hash = path;
  }

  function current() {
    return _currentRoute;
  }

  function _handleHash() {
    const hash = location.hash.replace('#', '') || '/chat';
    if (hash === _currentRoute) return;
    const renderFn = _routes[hash];
    if (!renderFn) {
      console.warn('[Router] Unknown route:', hash);
      return;
    }
    _currentRoute = hash;
    if (typeof ST !== 'undefined') ST.currentRoute = hash;
    if (_onNavigate) _onNavigate(hash);
    renderFn(_mountEl);
    _updateNavActive(hash);
  }

  function _updateNavActive(route) {
    document.querySelectorAll('.nav-item').forEach(el => {
      const href = el.dataset.route;
      if (href === route) {
        el.classList.add('active');
      } else {
        el.classList.remove('active');
      }
    });
  }

  return { init, register, onNavigate, navigateTo, current };
})();
