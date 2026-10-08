import { copyText } from './table-copy.js';

// A copy button whose text is fetched on click (data-copy-url): for exports
// too large to embed in the page. ClipboardItem takes the pending fetch, so
// browsers that only allow a copy straight after a click still allow it.
async function fetchText(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const text = await response.text();
  if (!response.ok) {
    let message = `the server answered ${response.status}`;
    try { message = JSON.parse(text).error || message; } catch { /* not JSON: keep the status */ }
    throw new Error(message);
  }
  return text;
}

export function initFetchCopies() {
  document.querySelectorAll('[data-fetch-copy]').forEach(panel => {
    const button = panel.querySelector('button');
    const status = panel.querySelector('[role="status"]');
    const url = panel.dataset.copyUrl;
    button.disabled = false;
    button.addEventListener('click', async () => {
      button.disabled = true; status.textContent = 'Preparing…';
      const text = fetchText(url);
      text.catch(() => {});
      try {
        try {
          if (!window.ClipboardItem || !navigator.clipboard?.write) throw new Error('ClipboardItem unavailable');
          const blob = text.then(value => new Blob([value], { type: 'text/plain' }));
          await navigator.clipboard.write([new ClipboardItem({ 'text/plain': blob })]);
        } catch {
          await copyText(await text);
        }
        status.textContent = panel.dataset.copySuccess || 'Copied!';
      } catch (error) {
        status.textContent = '';
        const link = document.createElement('a');
        link.href = url; link.textContent = 'open the JSON';
        status.append(`Could not copy (${error.message}). You can `, link, ' instead.');
      } finally { button.disabled = false; }
    });
  });
}
