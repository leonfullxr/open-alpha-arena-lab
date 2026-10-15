const path = window.location.pathname;
const entry = path === '/simulation' || path.startsWith('/simulation/')
  ? import('./simulation/main')
  : import('./landing/main');

void entry.then(({ mount }) => mount()).catch(() => {
  const root = document.getElementById('root');
  if (root) root.textContent = 'This page could not load. Refresh to try again.';
});
