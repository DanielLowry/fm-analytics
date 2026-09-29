(() => {
  const root = document.documentElement;
  const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  const sidebarClose = document.querySelector("[data-sidebar-close]");
  const overlay = document.querySelector("[data-sidebar-overlay]");
  const themeToggle = document.querySelector("[data-theme-toggle]");

  const setSidebar = (open) => {
    root.dataset.sidebarOpen = String(open);
    sidebarToggle?.setAttribute("aria-expanded", String(open));
    if (open) sidebarClose?.focus();
  };

  sidebarToggle?.addEventListener("click", () => setSidebar(root.dataset.sidebarOpen !== "true"));
  sidebarClose?.addEventListener("click", () => setSidebar(false));
  overlay?.addEventListener("click", () => setSidebar(false));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") setSidebar(false); });

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
