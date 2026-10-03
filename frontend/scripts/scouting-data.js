const fold = (value) => value.trim().toLowerCase().replaceAll('ß', 'ss').replaceAll('ς', 'σ');
const number = (params, key) => params.has(key) ? Number(params.get(key)) : null;
export function matchesSnapshotRow(row, params) {
  const former = params.get('everScouted') === '1';
  if (params.get('view') === 'scouted' && !row.scouted) return false;
  if ((!row.current || (row.dropped && (params.get('view') === 'scouted' || !row.search))) && !former) return false;
  if (row.rejected && params.get('showRejected') !== '1') return false;
  for (const key of ['name', 'club']) if (params.get(key) && !row[key].includes(fold(params.get(key)))) return false;
  for (const key of ['nationality', 'footedness', 'transferStatus', 'availability']) if (params.get(key) && params.get(key) !== row[key]) return false;
  for (const key of ['transferInterest', 'loanInterest']) {
    if (params.get(key) === 'interested' && !row[key]) return false;
    if (params.get(key) === 'not_interested' && row[key]) return false;
  }
  for (const [key, value] of params) if (key.startsWith('fact.') && value && row.facts[key.slice(5)] !== value) return false;
  const minAge = number(params, 'minAge'), maxAge = number(params, 'maxAge'), maxValue = number(params, 'maxValue');
  if (minAge !== null && (row.age === null || row.age < minAge)) return false;
  if (maxAge !== null && (row.age === null || row.age > maxAge)) return false;
  if (maxValue !== null && (row.value === null || row.value > maxValue)) return false;
  const months = number(params, 'expiringMonths') ?? 6;
  const expiring = row.months !== null && row.months <= months;
  const market = params.get('market') || 'any';
  if (market === 'free' && !row.free || market === 'listed' && !row.listed || market === 'expiring' && !expiring || market === 'gettable' && !row.free && !row.listed && !expiring) return false;
  const visibility = params.get('visibility') || 'any';
  const minKnown = number(params, 'minKnown');
  if (minKnown !== null && row.known + row.ranged < minKnown) return false;
  if (params.get('scoutMore') === '1' && (!row.captured || !row.known && !row.ranged || !row.ranged && !row.unknown)) return false;
  if (visibility !== 'any' && !row.captured) return false;
  if (visibility === 'known' && (row.ranged || row.unknown) || visibility === 'partial' && !row.ranged || visibility === 'unknown' && (row.known || row.ranged)) return false;
  const floor = number(params, 'minFloor'), ceiling = number(params, 'minCeiling');
  if (floor !== null && row.floor < floor) return false;
  if (ceiling !== null && row.ceiling < ceiling && params.get('includeUnlikely') !== '1') return false;
  if (params.get('sort') === 'trial_priority' && !row.trial) return false;
  return true;
}

export function orderedSnapshotRows(data, params, byId = new Map(data.rows.map(row => [row.id, row]))) {
  const sort = params.get('sort');
  const direction = params.get('dir') || (['name', 'age', 'value', 'role'].includes(sort) ? 'asc' : 'desc');
  const ceiling = number(params, 'minCeiling');
  const order = data.orders[sort]?.[direction] || data.rows.map((row) => row.id);
  let rows = order.map((id) => byId.get(id)).filter((row) => matchesSnapshotRow(row, params));
  // Changing a ceiling changes the role's recommendation, not its score.
  if (data.mode === 'role' && sort === 'priority' && ceiling !== null) {
    const priority = (row) => row.ceiling < ceiling ? 3 : !row.known && !row.ranged ? 1 : row.ranged || row.unknown ? 2 : 0;
    rows.sort((a, b) => (priority(a) - priority(b) || b.floor - a.floor || b.ceiling - a.ceiling || (a.name > b.name ? 1 : a.name < b.name ? -1 : 0) || (a.id > b.id ? 1 : a.id < b.id ? -1 : 0)) * (direction === 'desc' ? 1 : -1));
  }
  return rows;
}
