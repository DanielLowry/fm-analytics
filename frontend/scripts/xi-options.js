export function initXiOptions() {
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
