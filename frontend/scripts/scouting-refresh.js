// A small status request never loads the candidate feed or computes rankings.
export function initScoutingRefresh() {
  const panel = document.getElementById('scouting-refresh-progress');
  if (!panel) return;
  const forms = [...document.querySelectorAll('form[action="/scouting/refresh"]')];
  const label = panel.querySelector('[data-refresh-label]');
  const detail = panel.querySelector('[data-refresh-detail]');
  const summary = panel.querySelector('[data-refresh-summary]');
  const bar = panel.querySelector('progress');
  let generation = Number(panel.dataset.generation);
  let running = panel.dataset.status === 'running';
  let timer;
  let stopped = false;
  let controller;
  let sequence = 0;
  const buttons = (disabled) => forms.forEach(form => form.querySelectorAll('button[type="submit"], button:not([type])').forEach(button => { button.disabled = disabled; }));
  const update = (state) => {
    const wasRunning = running;
    running = state.status === 'running';
    panel.dataset.status = state.status;
    panel.hidden = state.status === 'idle';
    bar.value = state.percent;
    buttons(running);
    const count = state.total ? ` · ${state.completed.toLocaleString()} / ${state.total.toLocaleString()} players` : '';
    const eta = state.remaining_seconds === null ? 'Estimating time remaining…' : `About ${state.remaining_seconds}s remaining`;
    label.textContent = running ? state.label : state.status === 'succeeded' ? 'Scouting results ready' : 'Scouting refresh failed';
    detail.textContent = running ? `${state.detail || state.label}${count} · ${eta} · ${state.elapsed_seconds}s elapsed` : `${state.elapsed_seconds}s elapsed`;
    if (state.status === 'failed') summary.textContent = `Refresh failed: ${state.error}. Previous results remain available.`;
    summary.classList.toggle('warn', state.status === 'failed');
    if (state.status === 'succeeded') {
      summary.textContent = 'Refresh succeeded. New scouting data and rankings are ready.';
      const note = document.querySelector('[data-scouting-knowledge]');
      if (note) { note.textContent = state.knowledge_note?.[0] || ''; note.className = state.knowledge_note?.[1] === false ? 'warn' : 'muted'; }
      const recovery = document.querySelector('[data-scouting-recovery]');
      if (recovery) recovery.hidden = true;
    }
    if (state.status === 'succeeded' && (state.generation !== generation || wasRunning)) {
      document.dispatchEvent(new CustomEvent('scouting:refreshed', { detail: state }));
    }
    if (state.status === 'failed' && wasRunning && state.needs_player_search) location.reload();
    generation = state.generation;
  };
  const poll = async () => {
    if (stopped) return;
    const mine = ++sequence;
    controller = new AbortController();
    try {
      const response = await fetch('/scouting/refresh/status', { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('Status unavailable');
      const state = await response.json();
      if (mine === sequence) update(state);
    } catch (error) {
      if (mine === sequence && running && error.name !== 'AbortError') detail.textContent = 'Checking refresh status… Connection interrupted; retrying.';
    } finally {
      if (!stopped && mine === sequence) timer = window.setTimeout(poll, running ? 1000 : 5000);
    }
  };
  forms.forEach(form => form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (running) return;
    buttons(true);
    panel.hidden = false;
    label.textContent = 'Starting scouting refresh';
    detail.textContent = 'Estimating time remaining…';
    summary.textContent = 'Previous results remain available while refreshing.';
    bar.value = 0;
    clearTimeout(timer);
    sequence++;
    controller?.abort();
    try {
      const response = await fetch(form.action, { method: 'POST', body: new URLSearchParams(new FormData(form)), headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error('Could not start refresh');
      update(await response.json());
    } catch {
      detail.textContent = 'Could not confirm the refresh started. Checking its status…';
    } finally { clearTimeout(timer); poll(); }
  }));
  window.addEventListener('pagehide', () => { stopped = true; sequence++; clearTimeout(timer); controller?.abort(); });
  window.addEventListener('pageshow', event => { if (event.persisted) { stopped = false; poll(); } });
  buttons(running);
  poll();
}
