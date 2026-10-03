// Spreadsheet rows use captured observations, never role scores or midpoints.
const cell = (value) => {
  const text = String(value ?? '?').replace(/[\t\r\n]+/g, ' ').trim();
  // Treat ranges as text so spreadsheets cannot turn them into dates. Names
  // and other text must also remain text if they begin with a formula marker.
  return /^[=+@-]/.test(text) || /^\d+-\d+$/.test(text) ? "'" + text : text;
};

export function attributeExport(rows, schema, family, format = 'tsv') {
  const attributes = schema.attributes[family];
  if (!attributes || !['tsv', 'csv'].includes(format)) throw new Error('Unknown export format');
  const players = rows.filter(row => row.families.includes(family));
  const positions = [...schema.positions];
  // Retain any captured position outside the standard FM list too.
  const extras = [...new Set(players.flatMap(row => Object.keys(row.familiarity)))].filter(key => !positions.includes(key)).sort();
  positions.push(...extras);
  const headers = ['Name', 'Age', 'Club', 'Positions', 'Familiarity source', 'Attributes observed on', 'Historical attributes',
    ...positions.map(position => `Familiarity ${position} (0–20)`), ...attributes.map(([, label]) => label)];
  const table = [headers, ...players.map(row => [
    row.name, row.age, row.club, row.positions.join(', ') || '?', row.familiaritySource, row.observedOn,
    attributes.filter(([key]) => row.historical[key]).map(([key, label]) => `${label}: last seen ${row.historical[key]}`).join('; '),
    ...positions.map(position => row.familiarity[position]),
    ...attributes.map(([key]) => row.attributes[key]),
  ])];
  const encode = format === 'csv' ? value => '"' + cell(value).replaceAll('"', '""') + '"' : cell;
  return { count: players.length, text: table.map(row => row.map(encode).join(format === 'csv' ? ',' : '\t')).join(format === 'csv' ? '\r\n' : '\n') };
}
