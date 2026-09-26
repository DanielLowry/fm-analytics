"""The Scouting page's client script: live filtering, sort controls, \"Show more\".

Kept apart from ``rendering.py`` because it is a self-contained unit with one
reader (``scouting_pages.py``). It computes nothing: every number it shows comes
from the server fragment it fetches.
"""

from __future__ import annotations


# Real-time re-filtering for the Scouting page. Server-side only: it fetches
# the same `_scouting_results_block` computation `/scouting` itself renders
# (see `SquadWebHandler._scouting_results_fragment`), just as a fragment, so
# typing never invents a lighter-weight client-side filter that could disagree
# with the page's own numbers. `form.filters`' fields already carry every
# active filter, including the position/role selects and dynamic `fact.*`
# selects, so serializing the whole form on each change keeps them all in
# sync without hand-listing field names here. A no-JS browser falls back to
# the form's ordinary GET submit, unaffected by this script.
#
# The role select is narrowed to the chosen position's eligible roles from
# `#position-roles-data` (see `_scouting_filters_form`) -- a structural fact
# from the catalogue, not a score, so reading it here does not duplicate any
# analytics computation. With no position chosen it lists every role: a role is
# a perfectly good place to start.
#
# The "Sort by" select lists only the columns of the table now showing. Which
# table that is follows from the tactic and role fields (a tactic gives the
# XI-gain table, else a role gives that role's targets, else the ranking), and
# each option's `data-modes` says which tables have its column. The server
# applies the same rule (`analytics.sort_for_mode`), so this only keeps the
# control honest between requests.
_SCOUTING_LIVE_FILTER_SCRIPT = """
<script>
(function () {
  var form = document.querySelector('form.scouting-filters');
  var results = document.getElementById('scouting-results');
  if (!form || !results) return;

  function field(name) { return form.elements[name] || null; }
  var positionSelect = field('position');
  var roleSelect = field('role');
  var tacticSelect = field('tactic');
  var sortSelect = field('sort');
  var dirInput = field('dir');
  var limitInput = field('limit');
  var rawBox = field('includeRawPositions');

  var rolesByPosition = {};
  var roleData = document.getElementById('position-roles-data');
  if (roleData) {
    try { rolesByPosition = JSON.parse(roleData.textContent); }
    catch (error) { rolesByPosition = {}; }
  }

  function refreshRoleOptions() {
    if (!positionSelect || !roleSelect) return;
    var previous = roleSelect.value;
    var roles = rolesByPosition[positionSelect.value] || rolesByPosition[''] || [];
    roleSelect.innerHTML = '';
    var blank = document.createElement('option');
    blank.value = '';
    blank.textContent = 'Any role';
    roleSelect.appendChild(blank);
    roles.forEach(function (pair) {
      var option = document.createElement('option');
      option.value = pair[0];
      option.textContent = pair[1];
      if (pair[0] === previous) option.selected = true;
      roleSelect.appendChild(option);
    });
    if (!roleSelect.value) roleSelect.value = '';
  }

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

  var timer = null;
  var inflight = null;
  var sequence = 0;
  function apply() {
    var params = new URLSearchParams(new FormData(form));
    Array.from(params.keys()).forEach(function (key) {
      if (params.get(key) === '') params.delete(key);
    });
    var query = params.toString();
    var mine = ++sequence;
    if (inflight) inflight.abort();
    inflight = window.AbortController ? new AbortController() : null;
    results.setAttribute('aria-busy', 'true');
    results.classList.add('loading');
    fetch('/scouting/results?' + query, inflight ? { signal: inflight.signal } : undefined)
      .then(function (response) { return response.text(); })
      .then(function (text) {
        if (mine !== sequence) return; // a newer request has superseded this one
        results.innerHTML = text;
      })
      .catch(function (error) {
        if (mine !== sequence || (error && error.name === 'AbortError')) return;
        var note = document.createElement('p');
        note.className = 'warn';
        note.textContent = 'Could not update the results; showing the previous ones.';
        results.insertBefore(note, results.firstChild);
      })
      .then(function () {
        if (mine !== sequence) return;
        results.removeAttribute('aria-busy');
        results.classList.remove('loading');
      });
    history.replaceState(null, '', '/scouting?' + query);
  }

  function changed() {
    // Any change to what is being asked for starts again from the top of the list.
    if (limitInput) limitInput.value = '';
    clearTimeout(timer);
    apply();
  }

  if (positionSelect) positionSelect.addEventListener('change', refreshRoleOptions);
  [tacticSelect, roleSelect, rawBox].forEach(function (control) {
    if (control) control.addEventListener('change', syncSortOptions);
  });
  if (sortSelect && dirInput) {
    // Choosing a column from the list means "that column, its natural way round".
    sortSelect.addEventListener('change', function () { dirInput.value = ''; });
  }
  refreshRoleOptions();
  syncSortOptions();

  form.addEventListener('input', function (event) {
    if (event.target.tagName === 'SELECT' || event.target.type === 'checkbox') return; // 'change' below
    if (limitInput) limitInput.value = '';
    clearTimeout(timer);
    timer = setTimeout(apply, 250);
  });
  form.addEventListener('change', changed);
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    changed();
  });

  // Column headers re-sort on the server, so the top of a long list is the
  // true top by that column rather than the top of what was on screen. The
  // hidden `dir` field carries the current direction; clicking the active
  // column flips it, clicking another starts from that column's natural one.
  results.addEventListener('click', function (event) {
    var sortButton = event.target.closest('button.sort-btn');
    if (sortButton && sortSelect && dirInput) {
      var key = sortButton.getAttribute('data-sort');
      if (sortSelect.value === key) {
        dirInput.value = dirInput.value === 'desc' ? 'asc' : 'desc';
      } else {
        sortSelect.value = key;
        dirInput.value = sortButton.getAttribute('data-default');
      }
      changed();
      return;
    }
    var more = event.target.closest('.show-more button');
    if (more && limitInput) {
      limitInput.value = more.getAttribute('data-limit');
      clearTimeout(timer);
      apply();
    }
  });
})();
</script>
"""
