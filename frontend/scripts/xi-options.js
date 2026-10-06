export function initXiOptions() {
  // Excluding or restoring a player reloads this page with a re-picked XI.
  document.querySelectorAll('[data-xi-exclusion]').forEach(link => link.addEventListener('click', event => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const status = document.querySelector('[data-xi-status]');
    if (status) status.textContent = 'Re-optimizing XI…';
  }));
  document.querySelectorAll('[data-xi-options]').forEach(form => {
    const toggles = [...form.querySelectorAll('input[type="checkbox"]')];
    const copies = [...(form.closest('.fm-starting-xi') || document).querySelectorAll('[data-player-copy] button')];
    const status = form.querySelector('[data-xi-status]');
    form.addEventListener('submit', () => {
      copies.forEach(button => { button.disabled = true; });
      status.textContent = 'Re-optimizing XI…';
    });
    toggles.forEach(toggle => toggle.addEventListener('change', () => form.requestSubmit()));
    // A browser-back restore must match the options that produced this page.
    window.addEventListener('pageshow', () => {
      toggles.forEach(toggle => { toggle.checked = toggle.defaultChecked; });
      copies.forEach(button => { button.disabled = false; });
      status.textContent = '';
    });
  });
}
