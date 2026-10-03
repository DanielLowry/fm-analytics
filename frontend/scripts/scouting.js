import { positionValue } from "./tables.js";
import { initTableCopies } from "./table-copy.js";
import { orderedSnapshotRows } from "./scouting-data.js";
import { roleOptionsUpdater } from "./position-roles.js";
// Display cached, server-scored candidates. No scoring runs in the browser.
export function initScouting() {
  const form = document.querySelector('form.scouting-filters');
  const results = document.getElementById('scouting-results');
  if (!form || !results) return;
  function field(name) { return form.elements[name] || null; }
  var positionSelect = field('position');
  var roleSelect = field('role');
  var tacticSelect = field('tactic');
  var sortSelect = field('sort');
  var dirInput = field('dir');
  var limitInput = field('limit');
  var rawBox = field('includeRawPositions');

  const refreshRoleOptions = roleOptionsUpdater(form);

  function tableMode() {
    if (tacticSelect && tacticSelect.value) return 'tactic';
    if (roleSelect && roleSelect.value) return 'role';
    return 'ranking';
  }

  // Enable exactly the sorts this table has; if the chosen one is not among
  // them, fall back to the table's default in its natural direction.
  function syncSortOptions() {
    if (!sortSelect) return;
    var mode = tableMode();
    var raw = !!(rawBox && rawBox.checked);
    Array.prototype.forEach.call(sortSelect.options, function (option) {
      var modes = (option.getAttribute('data-modes') || '').split(' ');
      var usable = modes.indexOf(mode) !== -1 && (raw || !option.hasAttribute('data-raw'));
      option.disabled = !usable;
      option.hidden = !usable;
    });
    var current = sortSelect.options[sortSelect.selectedIndex];
    if (!current || current.disabled) {
      var defaults = {};
      try { defaults = JSON.parse(sortSelect.getAttribute('data-defaults') || '{}'); }
      catch (error) { defaults = {}; }
      sortSelect.value = defaults[mode] || '';
      if (dirInput) dirInput.value = '';
    }
  }


  const snapshots = new Map();
  let activeKey = null;
  let controller = null;
  let requestKey = null;
  let sequence = 0;
  const status = document.createElement('p');
  status.className = 'fm-scouting-context'; status.setAttribute('role', 'status');
  results.before(status);
  const paramsForForm = () => {
    const params = new URLSearchParams(new FormData(form));
    [...params.keys()].forEach((key) => { const value = params.get(key).trim(); if (value === '') params.delete(key); else params.set(key, value); });
    return params;
  };
  const contextKey = (params) => JSON.stringify(['tactic', 'position', 'role', 'includeRawPositions'].map((key) => params.get(key) || ''));
  const number = (params, key) => params.has(key) ? Number(params.get(key)) : null;
  const render = (snapshot, params) => {
    const sort = params.get('sort') || sortSelect.value;
    const option = sortSelect.selectedOptions[0];
    const direction = params.get('dir') || option?.dataset.default || (['name', 'age', 'value', 'role'].includes(sort) ? 'asc' : 'desc');
    const minAge = number(params, 'minAge'), maxAge = number(params, 'maxAge');
    const floor = number(params, 'minFloor'), ceiling = number(params, 'minCeiling');
    if (minAge !== null && maxAge !== null && minAge > maxAge || floor !== null && ceiling !== null && floor > ceiling) {
      status.textContent = 'The minimum must not exceed the maximum.'; return;
    }
    const rows = orderedSnapshotRows(snapshot.data, params, snapshot.byId);
    const trial = sort === 'trial_priority';
    const scoutFirst = trial ? rows.filter((row) => !row.known && !row.ranged) : [];
    const scored = trial ? rows.filter((row) => row.known || row.ranged) : rows;
    const limit = Math.min(1000, Math.max(100, number(params, 'limit') || 100));
    if (results.dataset.context !== activeKey) {
      results.innerHTML = snapshot.frame;
      results.dataset.context = activeKey;
    }
    const table = results.querySelector('table.results');
    if (!table) { status.textContent = 'No candidates for this scoring context.'; history.replaceState(null, '', '/scouting?' + params); return; }
    const tbody = table.tBodies[0];
    tbody.innerHTML = scored.slice(0, limit).map((row) => row.html).join('');
    [...tbody.rows].forEach((tr, index) => {
      tr.cells[0].textContent = index + 1;
      const row = scored[index];
      if (snapshot.data.mode === 'role' && ceiling !== null && row.ceiling < ceiling) {
        const badge = tr.querySelector('.rec .badge');
        if (badge && row.captured) { badge.textContent = 'Unlikely'; badge.className = 'badge badge-unlikely'; const detail = tr.querySelector('.rec li'); if (detail) detail.textContent = 'Even the visible ceiling misses your filter.'; }
      }
      tr.querySelectorAll('a[href^="/scouting/player/"]').forEach((link) => { const url = new URL(link.href); url.searchParams.set('return', '/scouting?' + params.toString()); link.href = url.pathname + url.search + url.hash; });
    });
    results.querySelectorAll('.show-more, .fm-scout-first, .fm-table-empty').forEach((node) => node.remove());
    if (!scored.length) { const note = document.createElement('p'); note.className = 'fm-table-empty'; note.textContent = 'No scored candidates match these filters.'; table.parentElement.after(note); }
    const more = document.createElement('p'); more.className = 'show-more';
    if (scored.length > limit) { const button = document.createElement('button'); button.type = 'button'; button.dataset.limit = Math.min(1000, limit + 100); button.textContent = `Show ${Math.min(100, scored.length - limit)} more`; if (limit < 1000) more.append(button); }
    more.append(document.createTextNode(` Showing ${Math.min(limit, scored.length)} of ${scored.length}.`)); results.append(more);
    if (scoutFirst.length) {
      const panel = document.createElement('details'); panel.className = 'fm-scout-first';
      const summary = document.createElement('summary'); summary.textContent = `Scout first (${scoutFirst.length})`; panel.append(summary);
      const note = document.createElement('p'); note.textContent = 'No visible role attributes; no score or priority is claimed.'; panel.append(note);
      const groups = new Map();
      scoutFirst.forEach((row) => { if (!groups.has(row.slot)) groups.set(row.slot, []); groups.get(row.slot).push(row); });
      [...groups].sort((a, b) => positionValue(a[1][0].position) - positionValue(b[1][0].position) || a[0].localeCompare(b[0])).forEach(([slot, players]) => {
        const heading = document.createElement('h4'); heading.textContent = slot; panel.append(heading);
        const list = document.createElement('ul'); players.forEach((row) => { const li = document.createElement('li'); const link = document.createElement('a'); link.href = `/scouting/player/${encodeURIComponent(row.id)}`; link.textContent = row.displayName; li.append(link); list.append(li); }); panel.append(list);
      });
      results.append(panel);
    }
    table.querySelectorAll('th').forEach((th) => { const button = th.querySelector('.sort-btn'); th.removeAttribute('aria-sort'); if (button) { button.textContent = button.textContent.replace(/ [▲▼]$/, ''); if (button.dataset.sort === sort) { th.setAttribute('aria-sort', direction === 'desc' ? 'descending' : 'ascending'); button.textContent += direction === 'desc' ? ' ▼' : ' ▲'; } } });
    initTableCopies(results);
    const heading = results.querySelector('h2'); if (heading) heading.textContent = heading.textContent.replace(/ \(\d+\)$/, '') + ` (${rows.length})`;
    const summary = results.querySelector('.results-summary'); if (summary) summary.textContent = `Sorted by ${option?.textContent || sort} · ${direction === 'desc' ? 'high to low' : 'low to high'}. Scores retain uncertainty.`;
    status.textContent = `${rows.length} candidates · filters and sorting apply instantly.`;
    history.replaceState(null, '', '/scouting?' + params.toString());
    document.querySelectorAll('.fm-scouting-tabs a').forEach((link) => { const view = new URL(link.href).searchParams.get('view'); const next = new URLSearchParams(params); next.set('view', view || 'all'); link.href = '/scouting?' + next.toString(); });
  };
  const apply = async () => {
    const params = paramsForForm(), key = contextKey(params);
    if (snapshots.has(key)) { activeKey = key; render(snapshots.get(key), params); return; }
    if (requestKey === key && controller) return;
    requestKey = key;
    const mine = ++sequence;
    controller?.abort(); controller = new AbortController();
    results.setAttribute('aria-busy', 'true');
    status.textContent = 'Loading rankings for this position, role or tactic…';
    const request = new URLSearchParams();
    ['tactic', 'position', 'role', 'includeRawPositions'].forEach((name) => { if (params.get(name)) request.set(name, params.get(name)); });
    request.set('snapshot', '1');
    try {
      const response = await fetch('/scouting/results?' + request, { signal: controller.signal });
      if (!response.ok) throw new Error('Rankings unavailable');
      const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (mine !== sequence) return;
      const source = parsed.getElementById('scouting-snapshot');
      if (!source) {
        // A genuinely empty scoring context has no table or snapshot.
        if (parsed.querySelector('.warn')) throw new Error(parsed.querySelector('.warn').textContent);
        results.innerHTML = parsed.body.innerHTML; initTableCopies(results); status.textContent = 'No candidates for this scoring context.'; history.replaceState(null, '', '/scouting?' + paramsForForm()); return;
      }
      const data = JSON.parse(source.textContent); source.remove();
      const snapshot = { data, frame: parsed.body.innerHTML, byId: new Map(data.rows.map((row) => [row.id, row])) };
      if (snapshots.size >= 4) snapshots.delete(snapshots.keys().next().value);
      snapshots.set(key, snapshot); activeKey = key;
      render(snapshot, paramsForForm());
    } catch (error) {
      if (mine === sequence && error.name !== 'AbortError') status.textContent = 'Could not load these rankings. Previous results remain visible; use Apply filters to retry.';
    } finally { if (mine === sequence) { results.removeAttribute('aria-busy'); controller = null; requestKey = null; } }
  };
  const updateFilterCounts = () => {
    form.querySelectorAll('.filter-group').forEach((group) => {
      const count = [...group.querySelectorAll('input, select')].filter((control) => {
        if (control.name === 'expiringMonths') return control.value !== '6' && ['expiring', 'gettable'].includes(field('market')?.value);
        return control.type === 'checkbox' ? control.checked : control.value && control.value !== 'any';
      }).length;
      const summary = group.querySelector('summary');
      let badge = summary.querySelector('.filter-count');
      if (!count) { badge?.remove(); return; }
      if (!badge) { badge = document.createElement('span'); badge.className = 'filter-count'; summary.append(badge); }
      badge.textContent = `${count} set`;
    });
  };
  const changed = (resetLimit = true) => { updateFilterCounts(); if (resetLimit && limitInput) limitInput.value = ''; if (requestKey && contextKey(paramsForForm()) !== requestKey) { sequence++; controller?.abort(); controller = null; requestKey = null; results.removeAttribute('aria-busy'); } apply(); };
  positionSelect?.addEventListener('change', () => { refreshRoleOptions(); syncSortOptions(); });
  [tacticSelect, roleSelect, rawBox].forEach((control) => control?.addEventListener('change', syncSortOptions));
  sortSelect?.addEventListener('change', () => { if (dirInput) dirInput.value = ''; });
  refreshRoleOptions(); syncSortOptions();
  form.addEventListener('input', (event) => { if (event.target.tagName !== 'SELECT' && event.target.type !== 'checkbox') changed(); });
  form.addEventListener('change', changed);
  form.addEventListener('submit', (event) => { event.preventDefault(); changed(); });
  results.addEventListener('click', (event) => {
    const player = event.target.closest('a[href^="/scouting/player/"]');
    if (player) { const params = paramsForForm(); const url = new URL(player.href); url.searchParams.set('return', '/scouting?' + params); player.href = url.pathname + url.search + url.hash; try { sessionStorage.setItem('fm-scouting-scroll:' + '/scouting?' + params, String(window.scrollY)); } catch { /* Navigation still works. */ } }

    const button = event.target.closest('.sort-btn');
    if (button && sortSelect && dirInput) {
      const key = button.dataset.sort;
      dirInput.value = sortSelect.value === key ? ((dirInput.value || button.closest('th').getAttribute('aria-sort')?.replace('ending', '') || button.dataset.default) === 'desc' ? 'asc' : 'desc') : button.dataset.default;
      sortSelect.value = key; changed(); return;
    }
    const more = event.target.closest('.show-more button');
    if (more && limitInput) { limitInput.value = more.dataset.limit; apply(); }
  });
  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(location.search);
    if (positionSelect) positionSelect.value = params.get('position') || '';
    refreshRoleOptions();
    [...form.elements].forEach((control) => { if (!control.name || control.type === 'submit') return; if (control.type === 'checkbox') control.checked = params.get(control.name) === control.value; else control.value = params.get(control.name) || ''; });
    syncSortOptions(); changed(false);
  });
  apply().then(() => { try { const key = 'fm-scouting-scroll:' + location.pathname + location.search; const y = sessionStorage.getItem(key); if (y !== null && !location.hash) { sessionStorage.removeItem(key); window.scrollTo(0, Number(y)); } } catch { /* Scroll restoration is optional. */ } });
}
