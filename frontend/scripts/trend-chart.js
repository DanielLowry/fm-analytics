// Hover for the Matches page's "Results against chances" charts. The server draws
// the charts and writes out every match's figures (web/season_chances_render.py);
// this only moves the crosshair to the match under the pointer and shows them.
// Every figure is also in the "Every match" table, so nothing depends on hovering.

const row = (value, label, key) => {
  const line = document.createElement('div');
  if (key) {
    const swatch = document.createElement('i');
    swatch.className = key;
    line.append(swatch);
  }
  const strong = document.createElement('b');
  strong.textContent = value;
  const span = document.createElement('span');
  span.textContent = label;
  line.append(strong, span);
  return line;
};

const contents = (match) => {
  const title = document.createElement('p');
  title.textContent = match.match;
  const lines = [title, row(match.worth, 'chances worth')];
  if (match.ours) lines.push(row(match.ours, 'yours, last 5', 'ours'), row(match.theirs, 'theirs, last 5', 'theirs'));
  lines.push(row(match.points, 'points'), row(match.running, 'running total'));
  return lines;
};

export function initTrendCharts(scope = document) {
  scope.querySelectorAll('[data-fm-trend]').forEach((trend) => {
    let matches;
    try { matches = JSON.parse(trend.querySelector('.fm-trend-data').textContent); } catch { return; }
    const tip = document.createElement('div');
    tip.className = 'fm-trend-tip';
    tip.hidden = true;
    trend.append(tip);
    const crosses = [...trend.querySelectorAll('.fm-trend-cross')];
    const hide = () => {
      tip.hidden = true;
      crosses.forEach((cross) => cross.classList.remove('shown'));
    };
    trend.querySelectorAll('svg').forEach((svg) => {
      svg.addEventListener('pointermove', (event) => {
        const hit = event.target.closest('.fm-trend-hit');
        const match = hit && matches[Number(hit.dataset.i)];
        if (!match) { hide(); return; }
        crosses.forEach((cross) => {
          cross.setAttribute('x1', hit.dataset.x);
          cross.setAttribute('x2', hit.dataset.x);
          cross.classList.add('shown');
        });
        tip.replaceChildren(...contents(match));
        tip.hidden = false;
        const box = trend.getBoundingClientRect();
        const left = event.clientX - box.left + 14;
        const fits = left + tip.offsetWidth < box.width;
        tip.style.left = `${fits ? left : Math.max(0, event.clientX - box.left - tip.offsetWidth - 14)}px`;
        tip.style.top = `${event.clientY - box.top + 14}px`;
      });
      svg.addEventListener('pointerleave', hide);
    });
  });
}
