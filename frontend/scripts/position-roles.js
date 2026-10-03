// Use the same catalogue eligibility on Squad and Scouting. Updating choices
// is synchronous; choosing a position never needs a request for role labels.
export function roleOptionsUpdater(form, { blankLabel = 'Any role', requiresPosition = false } = {}) {
  const position = form.elements.namedItem('position');
  const role = form.elements.namedItem('role');
  const source = document.getElementById('position-roles-data');
  if (!position || !role || !source) return () => {};
  let choices;
  try { choices = JSON.parse(source.textContent); } catch { return () => {}; }
  return () => {
    const previous = role.value;
    const disabled = requiresPosition && !position.value;
    const pairs = disabled ? [] : choices[position.value] || [];
    const blank = new Option(disabled ? 'Choose a position first' : blankLabel, '');
    role.replaceChildren(blank, ...pairs.map(([key, name]) => new Option(name, key)));
    role.value = pairs.some(([key]) => key === previous) ? previous : '';
    role.disabled = disabled;
    return { cleared: !!previous && !role.value, count: pairs.length };
  };
}

export function initSquadFilters() {
  const form = document.querySelector('form.squad-filters');
  if (!form) return;
  const refresh = roleOptionsUpdater(form, { blankLabel: 'Best role at this position', requiresPosition: true });
  const status = document.createElement('span'); status.className = 'sr-only'; status.setAttribute('role', 'status');
  form.append(status);
  form.elements.position.addEventListener('change', () => {
    const result = refresh();
    if (!result) return;
    status.textContent = form.elements.position.value
      ? `${result.count} roles available for ${form.elements.position.value}.${result.cleared ? ' Previous role cleared.' : ''}`
      : 'Choose a position to see compatible roles.';
  });
  refresh();
  window.addEventListener('pageshow', refresh);
}
