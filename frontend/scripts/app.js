import { initScouting } from "./scouting.js";
import { initTables } from "./tables.js";
(() => {
  initTables();
  initScouting();
  const openSection = () => {
    if (!location.hash) return;
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch { return; }
    if (!target) return;
    for (let node = target; node; node = node.parentElement) if (node.tagName === 'DETAILS') node.open = true;
    target.scrollIntoView();
  };
  window.addEventListener('hashchange', openSection);
  document.addEventListener('click', (event) => { const link = event.target.closest('a[href^="#"]'); if (link && link.hash === location.hash) openSection(); });
  openSection();
  const root = document.documentElement;
  const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  const sidebarClose = document.querySelector("[data-sidebar-close]");
  const overlay = document.querySelector("[data-sidebar-overlay]");
  const themeToggle = document.querySelector("[data-theme-toggle]");

  const sidebar = document.getElementById('primary-navigation');
  const desktop = window.matchMedia('(min-width: 1024px)');
  const setSidebar = (open, restoreFocus = true) => {
    root.dataset.sidebarOpen = String(open);
    sidebarToggle?.setAttribute('aria-expanded', String(open));
    if (sidebar) sidebar.inert = !desktop.matches && !open;
    if (open && !desktop.matches) sidebarClose?.focus();
    else if (restoreFocus && !desktop.matches) sidebarToggle?.focus();
  };
  setSidebar(false, false);
  desktop.addEventListener('change', () => { setSidebar(false); if (desktop.matches && document.activeElement === sidebarClose) sidebar.querySelector('a')?.focus(); });
  sidebarToggle?.addEventListener('click', () => setSidebar(root.dataset.sidebarOpen !== 'true'));
  sidebarClose?.addEventListener('click', () => setSidebar(false));
  overlay?.addEventListener('click', () => setSidebar(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && root.dataset.sidebarOpen === 'true') setSidebar(false);
    if (event.key === 'Tab' && !desktop.matches && root.dataset.sidebarOpen === 'true') {
      const focusable = [...sidebar.querySelectorAll('a[href], button')].filter((node) => !node.disabled && node.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });

  const applyTheme = (theme) => {
    const dark = theme === "dark";
    root.classList.toggle("dark", dark);
    root.dataset.theme = theme;
    themeToggle?.setAttribute("aria-pressed", String(dark));
    themeToggle?.setAttribute("aria-label", dark ? "Use light theme" : "Use dark theme");
  };

  const savedTheme = (() => {
    try { return window.localStorage.getItem("fm-theme"); } catch { return null; }
  })();
  applyTheme(savedTheme || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  themeToggle?.addEventListener("click", () => {
    const nextTheme = root.classList.contains("dark") ? "light" : "dark";
    try { window.localStorage.setItem("fm-theme", nextTheme); } catch { /* Theme still applies for this visit. */ }
    applyTheme(nextTheme);
  });
})();
