const initialized = new WeakSet();

// Keep each cell on one spreadsheet line. Copy displayed descriptions without
// duplicating nested tables or including closed explanation panels and controls.
export function tableText(table) {
  const styles = new WeakMap();
  const style = (node) => {
    if (!styles.has(node)) styles.set(node, getComputedStyle(node));
    return styles.get(node);
  };
  const hidden = (node) => node.hidden || style(node).display === 'none' || style(node).visibility === 'hidden';
  const text = (node) => {
    if (!node) return '';
    if (node.nodeType === Node.TEXT_NODE) return node.textContent;
    if (node.nodeType !== Node.ELEMENT_NODE || hidden(node) || node.matches('table, script, style, .fm-table-toolbar')) return '';
    if (node.tagName === 'BR') return ' ';
    if (node.tagName === 'DETAILS' && !node.open) return text(node.querySelector(':scope > summary'));
    const value = [...node.childNodes].map(text).join('');
    return /^(block|flex|grid|table|list-item|flow-root|inline-block|inline-flex|inline-grid)/.test(style(node).display) ? ` ${value} ` : value;
  };
  return [...table.rows].filter((row) => !hidden(row)).map((row) => [...row.cells].flatMap((cell) => {
    if (hidden(cell)) return [];
    let value = text(cell).replace(/\s+/g, ' ').trim();
    if (cell.tagName === 'TH') value = value.replace(/ [▲▼]$/, '');
    return [value, ...Array(cell.colSpan - 1).fill('')];
  }).join('\t')).join('\n');
}

function legacyCopy(value) {
  const focus = document.activeElement;
  const selection = window.getSelection();
  const ranges = selection ? Array.from({ length: selection.rangeCount }, (_, i) => selection.getRangeAt(i).cloneRange()) : [];
  const input = document.createElement('textarea');
  input.value = value; input.readOnly = true;
  input.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
  document.body.append(input);
  try {
    input.select();
    if (!document.execCommand('copy')) throw new Error('Copy unavailable');
  } finally {
    input.remove(); focus?.focus({ preventScroll: true });
    if (selection) { selection.removeAllRanges(); ranges.forEach((range) => selection.addRange(range)); }
  }
}

export async function copyText(value) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
    await navigator.clipboard.writeText(value);
  } catch { legacyCopy(value); }
}

export function initTableCopies(scope = document) {
  scope.querySelectorAll('table').forEach((table) => {
    if (initialized.has(table)) return;
    initialized.add(table);
    const container = table.parentElement.matches('.table-scroll, .fm-table-card, .fm-player-table, .fm-alternative-table, .fm-table-scroll') ? table.parentElement : table;
    let toolbar = container.previousElementSibling;
    if (!toolbar?.classList.contains('fm-table-toolbar')) {
      toolbar = document.createElement('div'); toolbar.className = 'fm-table-toolbar'; container.before(toolbar);
    }
    const button = document.createElement('button'); button.type = 'button'; button.className = 'fm-table-copy';
    button.textContent = 'Copy to clipboard'; button.title = 'Copy headers and visible rows in their current order';
    const status = document.createElement('span'); status.className = 'fm-table-copy-status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    toolbar.append(button, status);
    button.addEventListener('click', async () => {
      button.disabled = true; status.textContent = '';
      try {
        const value = tableText(table);
        await copyText(value);
        status.textContent = 'Copied!';
      } catch { status.textContent = 'Could not copy. Select the table and copy manually.'; }
      finally { button.disabled = false; }
    });
  });
}
