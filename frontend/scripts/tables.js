// Shared table behaviour. Work only with rendered data; keep explanation rows
// attached to their owning row, even when filtering or sorting a starting XI.
import { initTableCopies } from './table-copy.js';
export const POSITION_ORDER = ['GK', 'DL', 'DCL', 'DC', 'DCR', 'DR', 'WBL', 'DMCL', 'DMC', 'DM', 'DMCR', 'WBR', 'ML', 'MCL', 'MC', 'MCR', 'MR', 'AML', 'AMCL', 'AMC', 'AMCR', 'AMR', 'STL', 'STCL', 'STC', 'ST', 'STCR', 'STR'];
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
const empty = (value) => value === '' || /^(?:[?—–-]%?|not (?:yet )?captured|no eligible role|not selectable today)$/i.test(value);
export function compareValues(a, b, descending = false) {
  if (empty(a) || empty(b)) return Number(empty(a)) - Number(empty(b));
  const number = (value) => {
    const match = value.replace(/,/g, '').match(/^([+-]?\d+(?:\.\d+)?)(?:\s*%|\s|$)/);
    return match ? Number(match[1]) : null;
  };
  const na = number(a), nb = number(b);
  const result = na !== null && nb !== null ? na - nb : collator.compare(a, b);
  return descending ? -result : result;
}
export function positionValue(text) {
  const matches = text.toUpperCase().match(/\b(?:GK|D[LR]|DC[LR]?|WB[LR]|DM(?:C[LR]?)?|M[LR]|MC[LR]?|AM[LR]|AMC[LR]?|ST(?:C[LR]?|[LR])?)\b/g) || [];
  return Math.min(...matches.map((p) => POSITION_ORDER.indexOf(p)).filter((v) => v >= 0), POSITION_ORDER.length);
}
export function initTables(scope = document) {
  scope.querySelectorAll('table').forEach((table) => {
    if (table.dataset.fmTable || table.closest('#scouting-results')) return;
    table.dataset.fmTable = 'true';
    let headRow = table.tHead?.rows[0] || table.rows[0];
    if (!headRow) return;
    // Key/value tables still support filtering and sorting both columns.
    if (![...headRow.cells].some((cell) => cell.tagName === 'TH' && cell.scope !== 'row')) {
      const head = table.createTHead();
      headRow = head.insertRow();
      ['Statistic', 'Value'].forEach((label) => { const th = document.createElement('th'); th.textContent = label; headRow.append(th); });
    } else if (!table.tHead) {
      const head = table.createTHead();
      head.append(headRow);
    }
    const headers = [...headRow.cells];
    const groups = [];
    [...table.tBodies].forEach((body) => [...body.rows].forEach((row) => {
      if (row === headRow) return;
      if (row.classList.contains('explanation-row') && groups.length) groups.at(-1).rows.push(row);
      else groups.push({ row, body, rows: [row], index: groups.length, search: '' });
    }));
    if (!groups.length) return;
    groups.forEach((group) => { group.search = group.rows.map((row) => row.textContent).join(' ').toLocaleLowerCase(); });
    let container = table.parentElement;
    if (!container.matches('.table-scroll, .fm-table-card, .fm-player-table, .fm-alternative-table, .fm-table-scroll')) {
      container = document.createElement('div'); container.className = 'fm-table-scroll'; table.before(container); container.append(table);
    }
    container.classList.add('fm-table-scroll');
    const toolbar = document.createElement('div'); toolbar.className = 'fm-table-toolbar';
    const label = document.createElement('label'); label.textContent = 'Filter table';
    const search = document.createElement('input'); search.type = 'search'; search.placeholder = 'Search any column…'; label.append(search);
    const count = document.createElement('span'); count.setAttribute('role', 'status'); count.setAttribute('aria-live', 'polite');
    const reset = document.createElement('button'); reset.type = 'button'; reset.textContent = 'Reset';
    toolbar.append(label, count, reset); container.before(toolbar);
    const noResults = document.createElement('p'); noResults.className = 'fm-table-empty'; noResults.textContent = 'No rows match your search.'; noResults.hidden = true; container.after(noResults);
    const update = () => {
      const terms = search.value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
      let visible = 0;
      groups.forEach((group) => { const show = terms.every((term) => group.search.includes(term)); group.rows.forEach((row) => { row.hidden = !show; }); visible += Number(show); });
      count.textContent = `${visible} of ${groups.length} rows`; noResults.hidden = visible !== 0;
    };
    const append = (ordered) => { const fragments = new Map(); ordered.forEach((group) => { if (!fragments.has(group.body)) fragments.set(group.body, document.createDocumentFragment()); group.rows.forEach((row) => fragments.get(group.body).append(row)); }); fragments.forEach((fragment, body) => body.append(fragment)); };
    const positionColumn = headers.findIndex((th) => /^positions?$/.test(th.textContent.trim().toLowerCase()));
    // A roster's primary position determines its default order. Ranked score
    // tables keep their ranking unless position itself is the leading column.
    const defaultPosition = positionColumn >= 0 && (positionColumn === 0 || /^(player|name)$/i.test(headers[0].textContent.trim()));
    const original = defaultPosition ? [...groups].sort((a, b) => positionValue(a.row.cells[positionColumn].textContent) - positionValue(b.row.cells[positionColumn].textContent) || a.index - b.index) : groups;
    if (defaultPosition) append(original);
    headers.forEach((th, column) => {
      if (!th.textContent.trim() || th.colSpan > 1) return;
      th.scope = 'col'; th.classList.add('sort-header'); th.tabIndex = 0; th.setAttribute('aria-sort', defaultPosition && column === positionColumn ? 'ascending' : 'none');
      const sort = () => {
        const descending = th.getAttribute('aria-sort') === 'ascending';
        headers.forEach((header) => header.setAttribute('aria-sort', 'none')); th.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
        const value = (group) => { const cell = group.row.cells[column]; return cell?.getAttribute('data-sort') ?? cell?.textContent.trim() ?? ''; };
        append([...groups].sort((a, b) => {
          if (column === positionColumn) { const av = value(a), bv = value(b); if (empty(av) || empty(bv)) return Number(empty(av)) - Number(empty(bv)); const ap = positionValue(av), bp = positionValue(bv); if (ap === POSITION_ORDER.length || bp === POSITION_ORDER.length) return Number(ap === POSITION_ORDER.length) - Number(bp === POSITION_ORDER.length); const result = ap - bp; return (descending ? -result : result) || a.index - b.index; }
          return compareValues(value(a), value(b), descending) || a.index - b.index;
        }));
      };
      th.addEventListener('click', sort); th.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sort(); } });
    });
    search.addEventListener('input', update);
    reset.addEventListener('click', () => { search.value = ''; append(original); headers.forEach((th, col) => th.setAttribute('aria-sort', defaultPosition && col === positionColumn ? 'ascending' : 'none')); update(); });
    update();
  });
  initTableCopies(scope);
}
