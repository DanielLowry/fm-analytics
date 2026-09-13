"""HTML for the local live-attribute proof page."""

ATTRIBUTE_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FM20 Live Attribute Proof</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #09130f; color: #e9f3ed; }
    main { width: min(1120px, calc(100% - 32px)); margin: 36px auto 72px; }
    a { color: #73e2a7; }
    h1 { margin: 8px 0 6px; font-size: clamp(2rem, 6vw, 4rem); letter-spacing: -.055em; }
    h2 { margin: 0; font-size: 1.2rem; }
    .eyebrow, label { color: #91ad9f; text-transform: uppercase; letter-spacing: .11em; font-size: .76rem; }
    .lede { color: #b9c9c0; max-width: 760px; }
    .panel, .player { margin-top: 22px; border: 1px solid #264438; border-radius: 16px; padding: 20px; background: #10221a; }
    .controls { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .field { display: grid; gap: 7px; }
    select, input, button { width: 100%; border: 1px solid #3b6955; border-radius: 9px; padding: 11px 12px; background: #122c21; color: #e9f3ed; font: inherit; }
    button { cursor: pointer; background: #24563f; font-weight: 700; }
    button:hover { background: #2d6b4e; }
    button:disabled { cursor: not-allowed; opacity: .45; }
    .mode { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
    .mode label, .ack label { display: flex; gap: 8px; align-items: center; color: #e9f3ed; text-transform: none; letter-spacing: 0; font-size: .92rem; }
    input[type=radio], input[type=checkbox] { width: auto; accent-color: #54e391; }
    .warning { display: none; margin: 14px 0; padding: 14px; border: 1px solid #a56a2a; border-radius: 10px; background: #35230e; color: #ffd49b; }
    .warning.visible { display: block; }
    .search { display: none; grid-template-columns: 1fr auto; gap: 10px; margin-bottom: 16px; }
    .search.visible { display: grid; }
    .search button { width: auto; }
    .status { min-height: 24px; margin-top: 14px; color: #91ad9f; }
    .error { color: #ff918c; }
    .badge { display: inline-block; margin-left: 8px; padding: 3px 7px; border-radius: 999px; background: #214b39; color: #9ff0c1; font-size: .72rem; vertical-align: middle; }
    .badge.full { background: #5a3017; color: #ffd49b; }
    .badge.discoverable { background: #1c3a52; color: #9fd6ff; }
    .meta { color: #91ad9f; margin-top: 6px; font-size: .86rem; }
    .attributes { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; margin-top: 16px; }
    .attribute { border: 1px solid #264438; border-radius: 9px; padding: 10px; background: #0b1a13; }
    .attribute-name { color: #91ad9f; font-size: .76rem; }
    .attribute-value { margin-top: 4px; font-size: 1.25rem; }
    @media (max-width: 680px) { .controls { grid-template-columns: 1fr; } }
  </style>
</head>
<body><main>
  <a href="/">← Monitor</a>
  <div class="eyebrow">Live read-only diagnostic</div>
  <h1>Attribute proof</h1>
  <p class="lede">Select a team and one player and query FM directly. In-game visibility is the safe default and now works for any loaded team, not just your own squad. Full visibility is an explicit diagnostic that can reveal information hidden from your manager.</p>

  <section class="panel">
    <div class="mode">
      <label><input type="radio" name="mode" value="in-game" checked> In-game visibility</label>
      <label><input type="radio" name="mode" value="full"> Full visibility</label>
      <label><input type="radio" name="mode" value="discoverable"> Discoverable (cold query)</label>
    </div>
    <div id="warning" class="warning">
      <strong>Hidden-data diagnostic.</strong> Full visibility exposes underlying exact attributes and must not feed recommendations.
      <div class="ack"><label><input id="ack" type="checkbox"> I understand this may reveal hidden information</label></div>
      <div class="meta">After acknowledgement, Bath City is loaded as the first external comparison team. You can search for any other loaded club.</div>
    </div>
    <div id="cross-team-notice" class="warning">
      <strong>Cross-team search.</strong> This searches every team loaded in memory, not just teams your manager has actually discovered &mdash; matching a team here does not confirm your manager could find it via Player Search. Attribute values shown are still the safe manager-visible ones (exact/range/unknown), the same source as your own squad and Discoverable mode, never hidden data.
      <div class="ack"><label><input id="cross-team-ack" type="checkbox"> I understand this searches beyond confirmed discoverability</label></div>
    </div>
    <div id="search" class="search">
      <input id="team-search" placeholder="Search loaded teams, e.g. Bath City">
      <button id="search-button" type="button">Search</button>
    </div>
    <div id="discover-panel" class="warning">
      <strong>Research diagnostic, not a verified production source.</strong> Lists players your manager could find via Player Search (FM's own search-filter logic), then reads each one's manager-visible attributes the same safe way as In-game visibility &mdash; never raw or hidden values. Known to miss a small number of high-profile players FM's UI lists; has shown no false inclusions in testing so far. Package and save-date sensitivity are not yet independently checked. Running the query makes many native calls to FM and can take one to two minutes.
      <div class="ack"><label><input id="discover-ack" type="checkbox"> I understand this is experimental and may take a while</label></div>
      <div style="margin-top:12px"><button id="run-discovery" type="button" style="width:auto">Run discoverability query</button></div>
      <div id="discover-status" class="meta"></div>
    </div>
    <div class="controls">
      <div id="team-field" class="field"><label for="team">Team</label><select id="team"></select></div>
      <div class="field"><label for="player">Player</label><select id="player"><option value="">Entire team</option></select></div>
    </div>
    <button id="reveal" type="button" style="margin-top:16px">Reveal attributes</button>
    <div id="status" class="status"></div>
    <div id="progress-container" hidden style="margin-top:10px">
      <div style="height:8px;border-radius:6px;background:#0b1a13;overflow:hidden">
        <div id="progress-bar" style="height:100%;width:0%;background:#54e391;transition:width .15s linear"></div>
      </div>
      <div id="progress-label" class="meta"></div>
    </div>
  </section>
  <section id="results"></section>
</main>
<script>
const get = id => document.getElementById(id);
const team = get('team'), player = get('player'), status = get('status');
const currentMode = () => document.querySelector('input[name=mode]:checked').value;
const acknowledged = () => get('ack').checked;
const discoverAcknowledged = () => get('discover-ack').checked;
const crossTeamAcknowledged = () => get('cross-team-ack').checked;
const searchAcknowledged = () => currentMode()==='full' ? acknowledged() : crossTeamAcknowledged();
let managedClubId = null;
async function request(path, body) {
  const options = body ? {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)} : {cache:'no-store'};
  const response = await fetch(path, options); const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`); return data;
}
async function requestWithProgress(path, body) {
  const progress=get('progress-container'), bar=get('progress-bar'), label=get('progress-label');
  progress.hidden=false; bar.style.width='0%'; label.textContent='Starting…';
  try {
    const response=await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!response.ok) { const data=await response.json().catch(()=>({})); throw new Error(data.error || `HTTP ${response.status}`); }
    const reader=response.body.getReader(); const decoder=new TextDecoder(); let buffer=''; let result=null;
    while (true) {
      const {done, value}=await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream:true});
      let newline;
      while ((newline=buffer.indexOf('\n')) !== -1) {
        const line=buffer.slice(0, newline); buffer=buffer.slice(newline+1);
        if (!line.trim()) continue;
        const event=JSON.parse(line);
        if (event.type==='start') { label.textContent=`0 / ${event.total} players`; }
        else if (event.type==='progress') { bar.style.width=`${Math.round(100*event.done/event.total)}%`; label.textContent=`${event.done} / ${event.total} players (${event.player})`; }
        else if (event.type==='error') { throw new Error(event.error); }
        else if (event.type==='result') { result=event; }
      }
    }
    if (!result) throw new Error('the query stream ended without a result');
    return result;
  } finally { progress.hidden=true; }
}
function option(value, text) { const node=document.createElement('option'); node.value=value; node.textContent=text; return node; }
function setTeams(items) { team.replaceChildren(); for (const item of items) team.appendChild(option(item.id, `${item.name} (${item.playerCount} players)`)); }
function setPlayers(items) { player.replaceChildren(option('', 'Entire team')); for (const item of items) player.appendChild(option(item.id, item.name)); }
function showStatus(message, error=false) { status.textContent=message; status.className=error?'status error':'status'; }
async function loadManaged() {
  showStatus('Reading managed squad…');
  try { const data=await request('/api/attributes/catalog'); managedClubId=data.team.id; setTeams([data.team]); setPlayers(data.players); showStatus('Ready.'); }
  catch (error) { showStatus(error.message, true); }
}
async function searchTeams() {
  const mode=currentMode();
  if (!searchAcknowledged()) return showStatus(mode==='full' ? 'Acknowledge the full-visibility warning first.' : 'Acknowledge the cross-team search notice first.', true);
  const query=get('team-search').value.trim(); if (!query) return showStatus('Enter a team search.', true);
  showStatus('Searching FM team index…');
  try { const data=await request('/api/attributes/teams', {mode, acknowledged:true, query}); setTeams(data.teams); setPlayers([]); showStatus(`${data.teams.length} matching teams.`); if (data.teams.length) await loadPlayers(); }
  catch (error) { showStatus(error.message, true); }
}
async function loadPlayers() {
  if (!team.value) return setPlayers([]);
  const mode=currentMode();
  if (mode==='discoverable') return;
  try {
    const data=await request('/api/attributes/players', {mode, acknowledged:true, teamId:team.value});
    setPlayers(data.players);
  } catch (error) { showStatus(error.message, true); }
}
const MODE_BADGE = {full: ['full', 'FULL / HIDDEN'], discoverable: ['discoverable', 'DISCOVERABLE'], 'in-game': ['', 'IN-GAME']};
function render(data) {
  const root=get('results'); root.replaceChildren();
  for (const item of data.players) {
    const card=document.createElement('article'); card.className='player';
    const title=document.createElement('h2'); title.textContent=item.name;
    const [badgeClass, badgeText]=MODE_BADGE[currentMode()];
    const badge=document.createElement('span'); badge.className=`badge ${badgeClass}`; badge.textContent=badgeText; title.appendChild(badge); card.appendChild(title);
    const meta=document.createElement('div'); meta.className='meta'; meta.textContent=`ID ${item.id} · ${item.positions.join(', ')} · condition ${item.condition_percent ?? '—'}% · match fitness ${item.match_fitness_percent ?? '—'}%`; card.appendChild(meta);
    const grid=document.createElement('div'); grid.className='attributes';
    for (const [name, observation] of Object.entries(item.attributes)) {
      const cell=document.createElement('div'); cell.className='attribute';
      const label=document.createElement('div'); label.className='attribute-name'; label.textContent=name;
      const value=document.createElement('div'); value.className='attribute-value'; value.textContent=observation.value ?? (observation.minimum!=null?`${observation.minimum}–${observation.maximum}`:'—');
      cell.append(label,value); grid.appendChild(cell);
    }
    card.appendChild(grid); root.appendChild(card);
  }
}
async function runDiscovery() {
  if (!discoverAcknowledged()) return showStatus('Acknowledge the discoverability warning first.', true);
  const status=get('discover-status'); status.textContent='Running cold discoverability query (this can take one to two minutes)…';
  get('run-discovery').disabled=true;
  try {
    const data=await request('/api/discoverability/query', {acknowledged:true});
    setPlayers(data.players.map(p => ({id:p.id, name:p.name || `Player ${p.id}`})));
    status.textContent=`${data.count} discoverable players (${data.excludedCount} excluded from ${data.sourceCount} candidates as of ${data.gameDate}). Select one and click Reveal attributes.`;
    showStatus(`Discoverability query loaded ${data.count} players.`);
  } catch (error) { status.textContent=''; showStatus(error.message, true); }
  finally { get('run-discovery').disabled=false; }
}
async function reveal() {
  const mode=currentMode();
  if (mode==='discoverable') {
    if (!player.value) return showStatus('Run the discoverability query and select a player first.', true);
    if (!discoverAcknowledged()) return showStatus('Acknowledge the discoverability warning first.', true);
    showStatus('Reading live FM data…'); get('reveal').disabled=true;
    try {
      const playerName=player.options[player.selectedIndex]?.textContent;
      const data=await request('/api/discoverability/attributes', {acknowledged:true, playerId:player.value, playerName});
      render(data); showStatus(`Loaded visible attributes for ${playerName}.`);
    } catch (error) { showStatus(error.message, true); } finally { get('reveal').disabled=false; }
    return;
  }
  if (!team.value) return showStatus('Select a team.', true);
  if (mode==='full' && !acknowledged()) return showStatus('Acknowledge the full-visibility warning first.', true);
  showStatus('Reading live FM data…'); get('reveal').disabled=true;
  try {
    const wholeExternalTeam = mode==='in-game' && !player.value && team.value !== managedClubId;
    const data = wholeExternalTeam
      ? await requestWithProgress('/api/attributes/query/team-stream', {teamId:team.value})
      : await request('/api/attributes/query', {mode, acknowledged:acknowledged(), teamId:team.value, playerId:player.value||null});
    render(data); showStatus(`Loaded ${data.players.length} player${data.players.length===1?'':'s'} from ${data.team.name}.`);
  }
  catch (error) { showStatus(error.message, true); } finally { get('reveal').disabled=false; }
}
function syncPanels() {
  const mode=currentMode(); const full=mode==='full'; const inGame=mode==='in-game'; const discoverable=mode==='discoverable';
  get('warning').classList.toggle('visible',full);
  get('cross-team-notice').classList.toggle('visible',inGame);
  get('search').classList.toggle('visible',full || inGame);
  get('discover-panel').classList.toggle('visible',discoverable);
  get('team-field').style.display=discoverable?'none':'';
}
for (const radio of document.querySelectorAll('input[name=mode]')) radio.addEventListener('change', () => {
  syncPanels();
  const mode=currentMode(); const full=mode==='full'; const inGame=mode==='in-game';
  get('results').replaceChildren();
  if (inGame) { loadManaged(); get('team-search').value=''; }
  else if (full) { setTeams([]); setPlayers([]); get('team-search').value='Bath City'; showStatus('Acknowledge the warning to load Bath City, or enter another team.'); if (acknowledged()) searchTeams(); }
  else { setTeams([]); setPlayers([]); get('discover-status').textContent=''; showStatus('Acknowledge the warning, then run the discoverability query to list players.'); }
});
get('ack').addEventListener('change', () => { if (currentMode()==='full' && acknowledged()) { if (!get('team-search').value.trim()) get('team-search').value='Bath City'; searchTeams(); } });
get('search-button').addEventListener('click',searchTeams); get('team-search').addEventListener('keydown',event=>{if(event.key==='Enter')searchTeams();});
get('run-discovery').addEventListener('click',runDiscovery);
team.addEventListener('change',loadPlayers); get('reveal').addEventListener('click',reveal);
syncPanels(); loadManaged();
</script></body></html>
"""
