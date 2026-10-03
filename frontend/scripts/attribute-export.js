import { copyText } from './table-copy.js';
import { attributeExport } from './attribute-export-data.js';

export function initAttributeExports(panel, getRows) {
  if (!panel) return () => {};
  const data = JSON.parse(panel.querySelector('[data-export-schema]').textContent);
  const buttons = [...panel.querySelectorAll('[data-export-family]')];
  const status = panel.querySelector('[role="status"]');
  buttons.forEach(button => {
    const label = button.textContent;
    button.dataset.exportLabel = label;
    button.addEventListener('click', async () => {
      const rows = getRows();
      if (!rows) return;
      const family = button.dataset.exportFamily, format = button.dataset.exportFormat;
      const result = attributeExport(rows, data.schema, family, format);
      if (!result.count) return;
      button.disabled = true; status.textContent = '';
      try {
        if (format === 'tsv') await copyText(result.text);
        else {
          const url = URL.createObjectURL(new Blob(['\uFEFF', result.text], { type: 'text/csv;charset=utf-8' }));
          const link = document.createElement('a'); link.href = url; link.download = `fm-${family}-attributes.csv`;
          document.body.append(link); link.click(); link.remove();
          window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        }
        status.textContent = `${format === 'tsv' ? 'Copied' : 'Downloaded'} ${result.count} ${family} player${result.count === 1 ? '' : 's'}.`;
      } catch { status.textContent = 'Export failed. Try downloading CSV if copying is unavailable.'; }
      finally { refresh(); }
    });
  });
  const refresh = () => {
    const rows = getRows();
    buttons.forEach(button => {
      const count = rows?.filter(row => row.families.includes(button.dataset.exportFamily)).length || 0;
      button.disabled = !count;
      button.textContent = button.dataset.exportLabel + (rows ? ` (${count})` : '');
    });
  };
  refresh();
  return () => { status.textContent = ''; refresh(); };
}

export function initPlayerAttributeExports() {
  document.querySelectorAll('[data-attribute-export]').forEach(panel => {
    const data = JSON.parse(panel.querySelector('[data-export-schema]').textContent);
    if (data.rows) initAttributeExports(panel, () => data.rows);
  });
}
