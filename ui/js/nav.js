// nav.js — Main navigation rail collapse/expand + active state
function toggleNav() {
  const shell = document.getElementById('appShell');
  if (!shell) return;
  shell.classList.toggle('nav-expanded');
  localStorage.setItem('nav-expanded', shell.classList.contains('nav-expanded') ? '1' : '0');
}

function initNav() {
  const shell = document.getElementById('appShell');
  if (!shell) return;
  if (localStorage.getItem('nav-expanded') === '1') {
    shell.classList.add('nav-expanded');
  }
}

function setNavActive(path) {
  document.querySelectorAll('.nav-item[data-route]').forEach(item => {
    item.classList.toggle('active', item.dataset.route === path);
  });
}

function navClick(path) {
  Router.navigateTo(path);
}
