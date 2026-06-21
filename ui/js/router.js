// router.js — Hash-based SPA router
const Router = {
  _routes: {},
  _current: null,

  register(path, page) {
    this._routes[path] = page;
  },

  init() {
    window.addEventListener('hashchange', () => this._onHash());
    this._onHash();
  },

  navigateTo(path) {
    if (window.location.hash === '#' + path) {
      this._onHash();
    } else {
      window.location.hash = path;
    }
  },

  back() {
    if (history.length > 1) history.back();
    else this.navigateTo('/chat');
  },

  currentPath() {
    return this._current;
  },

  _onHash() {
    let hash = window.location.hash.replace('#', '') || '/chat';
    if (!this._routes[hash]) hash = '/chat';

    if (this._current === hash) return;
    const prev = this._current;
    this._current = hash;

    if (prev && this._routes[prev] && this._routes[prev].onLeave) {
      this._routes[prev].onLeave();
    }

    Object.keys(this._routes).forEach(path => {
      const el = document.getElementById('page-' + path.slice(1));
      if (el) el.classList.toggle('active', path === hash);
    });

    if (this._routes[hash] && this._routes[hash].onEnter) {
      this._routes[hash].onEnter();
    }

    if (typeof setNavActive === 'function') setNavActive(hash);

    ST.currentPage = hash;
  },
};
