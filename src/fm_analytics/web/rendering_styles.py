"""Inline shell styles for the web UI."""

from __future__ import annotations

_STYLE = """
<style>
  body { font-family: system-ui, sans-serif; margin: 0; color: #1a1a1a; background: #fafafa; }
  body > nav { display: flex; align-items: flex-start; gap: 1rem; background: #1a2b3c; padding: 0.75rem 1.5rem; }
  .nav-links { display: flex; flex: 1; flex-wrap: wrap; gap: 0.45rem 1.25rem; }
  body > nav a { color: #cdd8e3; text-decoration: none; font-size: 0.95rem; }
  body > nav a.active, body > nav a:hover { color: #ffffff; font-weight: 600; }
  .fm-status { flex: 0 0 auto; color: #cdd8e3; font-size: 0.72rem; line-height: 1.35; text-align: right; }
  .fm-status b { color: #ffffff; }
  .fm-status form { display: inline-block; margin: 0.25rem 0 0 0.3rem; }
  .fm-status button { font-size: 0.72rem; cursor: pointer; }
  main { padding: 1.5rem 2rem; max-width: 1100px; margin: 0 auto; }
  main.wide { max-width: 1600px; }
  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
  h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 0.25rem; }
  table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; font-size: 0.9rem; }
  th, td { text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid #e5e5e5; }
  th { background: #f0f2f5; }
  th.sort-header { cursor: pointer; user-select: none; }
  th.sort-header::after { content: ' \\2195'; color: #9aa5b1; }
  th[aria-sort=ascending]::after { content: ' \\25B2'; color: inherit; }
  th[aria-sort=descending]::after { content: ' \\25BC'; color: inherit; }
  .muted { color: #666; }
  .warn { color: #9a4a00; }
  .error { color: #a30000; font-weight: 600; }
  .badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 0.75rem; font-size: 0.8rem; }
  .badge-persistent { background: #fde2e2; color: #8a1f1f; }
  .badge-occasional { background: #fff2d6; color: #8a5a00; }
  .badge-ok { background: #e3f3e1; color: #1e6b1e; }
  .tag { display: inline-block; padding: 0.1rem 0.5rem; margin: 0 0.25rem 0.25rem 0; border-radius: 0.75rem; font-size: 0.75rem; background: #eef1f4; color: #445; }
  code { background: #eef1f4; padding: 0.05rem 0.3rem; border-radius: 0.25rem; }
  details { margin: 0.4rem 0; border: 1px solid #e5e5e5; border-radius: 0.3rem; padding: 0.3rem 0.6rem; }
  details summary { cursor: pointer; font-weight: 600; }
  details table { margin-top: 0.5rem; }
  ul.legend { color: #555; font-size: 0.85rem; margin: 0.25rem 0 0.75rem; padding-left: 1.2rem; }
  form.filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 0.65rem; padding: 1rem; background: #f0f2f5; border-radius: 0.4rem; }
  form.filters label { display: grid; gap: 0.2rem; font-size: 0.78rem; color: #455; }
  form.filters input, form.filters select { min-width: 0; padding: 0.35rem; border: 1px solid #bbc3cc; border-radius: 0.25rem; background: white; }
  form.filters .check { display: flex; align-items: end; gap: 0.35rem; color: #1a1a1a; }
  form.filters button { align-self: end; padding: 0.45rem 0.65rem; border: 0; border-radius: 0.25rem; background: #1a2b3c; color: white; cursor: pointer; }
  .opponent-panel { margin: 1rem 0 1.5rem; padding: 0.9rem 1rem 1rem; border: 1px solid #d8dee5; border-radius: 0.4rem; background: #f5f7f9; }
  .opponent-panel h2 { margin-top: 0; }
  form.opponent-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.85rem 1.25rem; }
  .opponent-choice { display: grid; gap: 0.35rem; font-size: 0.85rem; }
  .opponent-choice select { padding: 0.45rem; border: 1px solid #bbc3cc; border-radius: 0.25rem; background: white; }
  .opponent-slider { display: grid; gap: 0.35rem; }
  .opponent-slider > span:first-child { display: flex; justify-content: space-between; gap: 0.75rem; font-size: 0.85rem; }
  .opponent-slider output { color: #566; text-align: right; }
  .opponent-range { display: grid; grid-template-columns: minmax(80px, 1fr) minmax(120px, 1.5fr) minmax(80px, 1fr); align-items: center; gap: 0.4rem; }
  .opponent-range small:last-child { text-align: right; }
  .opponent-range input { width: 100%; accent-color: #1a2b3c; }
  .opponent-details { grid-column: 1 / -1; background: white; padding: 0.65rem 0.8rem; }
  .opponent-details > summary { padding: 0.15rem 0; }
  .opponent-details fieldset { margin: 0.8rem 0 0; border: 1px solid #d8dee5; border-radius: 0.3rem; }
  .opponent-details legend { padding: 0 0.35rem; font-weight: 600; color: #34495e; }
  .opponent-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0.55rem 0.8rem; }
  .opponent-detail { display: grid; grid-template-columns: minmax(0, 1fr) minmax(105px, 0.9fr); align-items: center; gap: 0.45rem; font-size: 0.8rem; }
  .opponent-detail select { min-width: 0; padding: 0.35rem; border: 1px solid #bbc3cc; border-radius: 0.25rem; background: white; }
  .opponent-actions { grid-column: 1 / -1; display: flex; align-items: center; gap: 0.65rem; }
  .opponent-actions button { padding: 0.45rem 0.7rem; border: 0; border-radius: 0.25rem; background: #1a2b3c; color: white; cursor: pointer; }
  .button-link.secondary { background: #e1e6ea; color: #1a2b3c; }
  .opponent-summary { margin: 0.75rem 0 1rem; padding: 0.75rem 0.9rem; border-left: 4px solid #5c849f; background: #eef3f7; border-radius: 0.3rem; line-height: 1.5; }
  form.filters.scouting-filters { display: block; padding: 0; overflow: hidden; }
  .scouting-filters fieldset { border: 0; margin: 0; padding: 0.9rem 1rem 1rem; min-width: 0; }
  .scouting-filters legend { padding: 0; margin-bottom: 0.5rem; font-weight: 600; color: #1a2b3c; }
  .filter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.65rem; }
  .scouting-filters details.filter-group { margin: 0; border: 0; border-top: 1px solid #dfe3e7; border-radius: 0; padding: 0.55rem 1rem; }
  .scouting-filters details.filter-group[open] { padding-bottom: 0.9rem; }
  .scouting-filters details.filter-group > summary { font-size: 0.85rem; color: #34495e; }
  .scouting-filters details.filter-group > .filter-grid { margin-top: 0.65rem; }
  .filter-count { margin-left: 0.4rem; padding: 0.05rem 0.5rem; border-radius: 0.75rem; background: #1a2b3c; color: white; font-size: 0.7rem; font-weight: 500; }
  .filter-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 0.75rem; padding: 0.7rem 1rem; border-top: 1px solid #dfe3e7; }
  .filter-actions .spacer { flex: 1; }
  .filter-actions .reset { font-size: 0.85rem; }
  .filter-actions button { padding: 0.45rem 0.9rem; }
  p.intro { color: #455; max-width: 75ch; margin: 0.25rem 0 0.75rem; }
  .refresh-panel { margin: 0.5rem 0 1rem; padding: 0.15rem 0.9rem; border: 1px solid #e0e4e8; border-radius: 0.4rem; background: white; }
  .refresh-panel details { border: 0; padding: 0; margin: 0 0 0.5rem; }
  .refresh-panel details summary { font-weight: 500; font-size: 0.85rem; color: #456; }
  .refresh-panel form.refresh { margin: 0.5rem 0; flex-wrap: wrap; }
  .chip { display: inline-block; min-width: 1.35rem; padding: 0.05rem 0.3rem; border-radius: 0.25rem; font-size: 0.75rem; font-weight: 700; text-align: center; color: white; }
  .chip-W { background: #2e7d32; } .chip-D { background: #8d8d8d; } .chip-L { background: #b23b2e; }
  .form-strip { display: inline-flex; gap: 2px; flex-wrap: wrap; max-width: 16rem; }
  .form-strip .chip { min-width: 0.9rem; padding: 0.05rem 0.2rem; font-size: 0.65rem; }
  tr.thin td { color: #8a949e; }
  tr.thin td .chip { opacity: 0.55; }
  .thin-note { font-size: 0.72rem; color: #8a949e; display: block; }
  .versus { display: grid; grid-template-columns: 2.6rem 4.5rem 2.6rem; align-items: center; gap: 0.3rem; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .versus .us { text-align: right; font-weight: 600; } .versus .them { color: #66707a; }
  .versus .bars { display: flex; height: 0.5rem; border-radius: 0.25rem; overflow: hidden; background: #e6e9ec; }
  .versus .bars .b-us { background: #1a2b3c; } .versus .bars .b-them { background: #c9a227; }
  .share { display: inline-block; height: 0.5rem; background: #1a2b3c; border-radius: 0.25rem; vertical-align: middle; margin-right: 0.35rem; }
  .period-chart { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 0.4rem; align-items: end; height: 8rem; margin: 0.75rem 0 0.25rem; }
  .period-chart .col { display: flex; gap: 2px; align-items: end; justify-content: center; height: 100%; }
  .period-chart .bar-for { width: 40%; background: #2e7d32; border-radius: 2px 2px 0 0; }
  .period-chart .bar-against { width: 40%; background: #b23b2e; border-radius: 2px 2px 0 0; }
  .period-labels { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 0.4rem; font-size: 0.75rem; color: #556; text-align: center; }
  .key-for::before, .key-against::before { content: ''; display: inline-block; width: 0.7rem; height: 0.7rem; margin: 0 0.3rem 0 0.8rem; vertical-align: -1px; border-radius: 2px; }
  .key-for::before { background: #2e7d32; } .key-against::before { background: #b23b2e; }
  .match-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0.9rem; margin: 0.75rem 0 1.25rem; }
  .match-card { padding: 0.8rem 1rem; border: 1px solid #e0e4e8; border-radius: 0.4rem; background: white; }
  .match-card h3 { margin: 0 0 0.45rem; font-size: 0.95rem; }
  .match-card ol { margin: 0; padding-left: 1.2rem; font-size: 0.88rem; line-height: 1.55; }
  td.nowrap { white-space: nowrap; }
  .note-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.65rem; padding: 1rem; background: #f0f2f5; border-radius: 0.4rem; }
  .note-form label { display: grid; gap: 0.2rem; font-size: 0.78rem; color: #455; }
  .note-form select, .note-form textarea { padding: 0.35rem; border: 1px solid #bbc3cc; border-radius: 0.25rem; background: white; font: inherit; }
  .note-form textarea { grid-column: 1 / -1; min-height: 3.5rem; }
  .note-form button, form.inline button { padding: 0.45rem 0.8rem; border: 0; border-radius: 0.25rem; background: #1a2b3c; color: white; cursor: pointer; }
  form.inline { display: inline-flex; gap: 0.4rem; align-items: center; margin: 0; }
  form.inline select { padding: 0.3rem; border: 1px solid #bbc3cc; border-radius: 0.25rem; }
  #scouting-results { transition: opacity 0.15s; }
  #scouting-results.loading { opacity: 0.5; }
  .results-summary { margin: 0.3rem 0; color: #455; }
  details.explain { border: 0; padding: 0; margin: 0.2rem 0 0.4rem; }
  details.explain > summary { font-size: 0.85rem; font-weight: 500; color: #456; }
  .table-scroll { overflow-x: auto; margin: 0.6rem 0 1rem; border: 1px solid #e5e5e5; border-radius: 0.4rem; background: white; }
  .table-scroll table { margin: 0; }
  table.results td { vertical-align: top; }
  table.results th { vertical-align: bottom; }
  table.results th[aria-sort] { background: #e2e8ef; }
  table.results th[aria-sort]::after { content: none; }
  table.results td.rec { min-width: 14rem; }
  table.results .nw, table.results details.sheet summary { white-space: nowrap; }
  .show-more { display: flex; align-items: center; gap: 0.75rem; margin: 0 0 1.5rem; }
  .show-more button { padding: 0.45rem 0.9rem; border: 0; border-radius: 0.25rem; background: #1a2b3c; color: white; cursor: pointer; }
  form.refresh { margin: 0.75rem 0; display: flex; align-items: center; gap: 0.65rem; }
  form.refresh button { padding: 0.45rem 0.65rem; border: 0; border-radius: 0.25rem; background: #1a2b3c; color: white; cursor: pointer; }
  form.refresh button.danger { background: #8a2b12; }
  nav.scouting-tabs { display: flex; gap: 0.5rem; margin: 0.5rem 0 1rem; padding: 0; background: none; }
  nav.scouting-tabs a { padding: 0.4rem 0.8rem; border-radius: 0.25rem; text-decoration: none; color: #1a2b3c; background: #e8ecef; }
  nav.scouting-tabs a.tab-active { background: #1a2b3c; color: white; }
  .dropped-warning { color: #8a2b12; font-weight: bold; }
  details.sheet summary { cursor: pointer; color: #1a2b3c; }
  .sheet-groups { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 0.4rem; }
  .sheet-group h4 { margin: 0 0 0.2rem; font-size: 0.8rem; text-transform: uppercase; color: #566; }
  .attr { display: flex; justify-content: space-between; gap: 0.8rem; min-width: 10rem; font-size: 0.85rem; }
  .attr-hidden { color: #9aa; }
  .bar { position: relative; display: inline-block; width: 110px; height: 0.8rem; background: #e8ecef; border-radius: 0.2rem; vertical-align: middle; }
  .bar-fill { position: absolute; top: 0; bottom: 0; background: #9fb6cf; border-radius: 0.2rem; }
  button.sort-btn { all: unset; cursor: pointer; font-weight: 600; white-space: nowrap; }
  button.sort-btn:hover { text-decoration: underline; }
  .bar-mark { position: absolute; top: -2px; bottom: -2px; width: 3px; margin-left: -1px; background: #1a2b3c; }
  .badge-scout { background: #fff2d6; color: #805400; }
  .badge-history { background: #e8e4f3; color: #4a3a7a; }
  .attr-historical { font-style: italic; color: #4a3a7a; }
  .attr-historical b::after { content: " *"; font-weight: normal; }
  .history-banner { margin: 0.75rem 0; padding: 0.6rem 0.9rem; background: #f3f0fa; border-left: 4px solid #4a3a7a; border-radius: 0.3rem; }
  .badge-proven { background: #e3f3e1; color: #1e6b1e; }
  .badge-unlikely { background: #eee; color: #555; }
  .attribute-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.35rem; }
  .attribute-grid div { border: 1px solid #e5e5e5; padding: 0.35rem; border-radius: 0.25rem; }
  .attribute-grid b { display: block; font-size: 0.75rem; color: #667; }
  .tactic-hero { margin: 1rem 0 1.5rem; padding: 1rem 1.2rem; background: #eef3f7; border-left: 4px solid #1a2b3c; border-radius: 0.3rem; }
  .tactic-hero h2 { margin: 0.2rem 0; border: 0; padding: 0; font-size: 1.35rem; }
  .tactic-hero p { margin: 0.45rem 0; }
  .tactic-headline { font-weight: 600; }
  .eyebrow { color: #566; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }
  .button-link { display: inline-block; padding: 0.4rem 0.7rem; border-radius: 0.25rem; background: #1a2b3c; color: white; text-decoration: none; }
  .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 0.65rem; margin: 1rem 0; }
  .metric-grid div { display: grid; gap: 0.2rem; padding: 0.75rem; border: 1px solid #dfe3e7; border-radius: 0.3rem; background: white; }
  .metric-grid span { color: #667; font-size: 0.8rem; }
  .metric-grid b { font-size: 1.15rem; }
  .score-summary { display: grid; grid-template-columns: minmax(150px, 0.7fr) minmax(0, 2.3fr); gap: 1rem; margin: 1rem 0 0.6rem; padding: 1rem; background: white; border: 1px solid #dfe3e7; border-radius: 0.4rem; }
  .overall-score { display: grid; align-content: center; border-right: 1px solid #dfe3e7; padding-right: 1rem; }
  .overall-score span, .score-driver span, .score-drivers-title span { color: #667; font-size: 0.8rem; }
  .overall-score b { font-size: 2.4rem; line-height: 1.1; color: #1a2b3c; }
  .overall-score small, .score-driver small { color: #667; font-size: 0.75rem; }
  .score-drivers { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 0.6rem; }
  .score-drivers-title { grid-column: 1 / -1; display: flex; justify-content: space-between; gap: 1rem; }
  .score-driver { display: grid; grid-template-columns: 1fr auto; gap: 0.15rem 0.5rem; }
  .score-driver b { font-size: 1.2rem; }
  .score-driver small, .score-driver i { grid-column: 1 / -1; }
  .score-driver i { height: 0.3rem; overflow: hidden; background: #e8ecef; border-radius: 1rem; }
  .score-driver i em { display: block; height: 100%; background: #5c849f; border-radius: inherit; }
  .score-breakdown, .tactic-rationale { margin: 0.6rem 0; background: white; }
  .score-detail-grid, .score-guide-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.6rem; margin: 0.65rem 0; }
  .assessment-card, .score-guide-grid article { display: grid; gap: 0.2rem; padding: 0.7rem; border: 1px solid #dfe3e7; border-radius: 0.3rem; background: #fbfcfd; }
  .assessment-card span, .assessment-card small { color: #667; font-size: 0.78rem; }
  .assessment-card b { font-size: 1.25rem; color: #1a2b3c; }
  .assessment-card.inactive { opacity: 0.7; }
  .technical-formula { margin-top: 0.65rem; font-size: 0.85rem; background: #f7f8fa; }
  .score-guide-grid article b { color: #1a2b3c; }
  .score-guide-grid article span { color: #667; font-size: 0.84rem; line-height: 1.4; }
  .selection-flow { display: grid; grid-template-columns: repeat(auto-fit, minmax(105px, 1fr)); gap: 0.4rem; margin: 0.5rem 0 0.7rem; }
  .selection-flow > div { display: grid; gap: 0.15rem; padding: 0.55rem; border: 1px solid #dfe3e7; border-radius: 0.3rem; background: white; }
  .selection-flow span, .selection-flow small { color: #667; font-size: 0.74rem; }
  .selection-flow b { font-size: 1.05rem; }
  .selection-flow .selection-result { background: #eef3f7; border-color: #9fb6cf; }
  .coverage-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(215px, 1fr)); gap: 0.5rem; margin-top: 0.7rem; }
  .coverage-card { display: grid; grid-template-columns: auto 1fr; gap: 0.2rem 0.5rem; padding: 0.65rem; border: 1px solid #dfe3e7; border-radius: 0.3rem; background: white; }
  .coverage-card > span { color: #667; font-size: 0.82rem; align-self: center; }
  .coverage-card > div { grid-column: 1 / -1; display: grid; gap: 0.1rem; font-size: 0.86rem; }
  .coverage-card small { color: #667; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.03em; }
  .tactic-rationale-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0.55rem; margin: 0.6rem 0; }
  .tactic-rationale-grid > p { margin: 0; padding: 0.65rem; border-left: 3px solid #dfe3e7; background: #fbfcfd; line-height: 1.45; font-size: 0.88rem; }
  .tactic-rationale-grid > details { grid-column: 1 / -1; }
  .tactic-rationale ul { columns: 2; }
  .advisory-banner { margin: 1rem 0; padding: 0.85rem 1rem; border-left: 4px solid #b36b00; background: #fff4df; border-radius: 0.3rem; }
  .advisory-banner b { display: block; margin-bottom: 0.2rem; }
  .in-possession-section { margin: 1rem 0; }
  .in-possession-section h3 { font-size: 0.95rem; margin: 0 0 0.4rem; }
  .in-possession-section .subhead { color: #667; font-size: 0.78rem; margin: 0 0 0.5rem; }
  .instruction-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.5rem; margin-bottom: 0.6rem; }
  .instruction-pill { padding: 0.5rem 0.7rem; border-radius: 0.3rem; background: #f0f2f5; border-left: 3px solid #8894a3; }
  .instruction-pill.unset { background: #fff4df; border-left-color: #b36b00; color: #6b4a00; }
  .instruction-pill span { display: block; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.03em; color: #667; }
  .instruction-pill.unset span { color: #8a5a00; }
  .instruction-pill b { font-size: 0.9rem; }
  .instruction-pill.fallback { background: #eef1f4; border-left-color: #9aa5b1; }
  .instruction-pill.fallback span::after { content: " (fallback)"; text-transform: none; letter-spacing: normal; }
  .set-piece-hero { margin: 1rem 0; padding: 1rem 1.2rem; color: white; background: linear-gradient(135deg, #18364b, #315f68); border-radius: 0.45rem; }
  .set-piece-hero .eyebrow { color: #c8dde0; }
  .set-piece-hero h2 { margin: 0.15rem 0; padding: 0; border: 0; font-size: 1.35rem; }
  .set-piece-hero p { margin: 0.35rem 0 0; color: #e5eff0; }
  .set-piece-controls { margin-bottom: 1rem; }
  .set-piece-controls > input[type=hidden] { display: none; }
  .set-piece-data-warning { margin: 0 0 1rem; padding: 0.75rem 0.9rem; color: #6b4300; background: #fff4df; border-left: 4px solid #b36b00; border-radius: 0.3rem; }
  .set-piece-data-warning b { display: block; margin-bottom: 0.15rem; }
  .set-piece-section-heading h2 { margin-bottom: 0; }
  .set-piece-section-heading p { margin: 0.35rem 0 0.8rem; color: #667; }
  .set-piece-assignments { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0.65rem; margin: 0.8rem 0; }
  .set-piece-assignment-card { grid-column: span 2; padding: 0.75rem 0.85rem; border: 1px solid #d8e0e4; border-top: 3px solid #4f7e85; border-radius: 0.35rem; background: white; }
  .set-piece-assignment-card:nth-last-child(-n+2) { grid-column: span 3; }
  .set-piece-assignment-card h3 { margin: 0 0 0.6rem; color: #1a2b3c; font-size: 0.9rem; }
  .set-piece-choice { display: grid; grid-template-columns: 4.2rem minmax(0, 1fr); gap: 0.12rem 0.5rem; padding: 0.45rem 0; border-top: 1px solid #e7ebee; }
  .set-piece-choice:first-of-type { border-top: 0; padding-top: 0; }
  .set-piece-choice > span { color: #667; font-size: 0.76rem; }
  .set-piece-choice > b { color: #1a2b3c; font-size: 0.9rem; }
  .set-piece-choice > small { grid-column: 2; color: #667; font-size: 0.72rem; }
  .set-piece-choice > small.choice-warning { color: #7a4d00; }
  .taker-evidence, .operating-notes { margin: 0.8rem 0; padding: 0.65rem 0.8rem; background: white; }
  .taker-evidence > summary, .operating-notes > summary { color: #284e5a; }
  .taker-evidence > details { margin: 0.55rem 0; background: #fbfcfd; }
  .inline-warning { display: block; margin-top: 0.15rem; color: #8a5a00; font-weight: 400; }
  .routine-switcher { display: flex; align-items: center; flex-wrap: wrap; gap: 0.45rem 1rem; margin: 0.75rem 0; }
  nav.routine-tabs { display: flex; gap: 0.25rem; margin: 0; padding: 0; background: transparent; }
  nav.routine-tabs a { margin: 0; padding: 0.4rem 0.7rem; color: #31545c; background: #e8eef0; border-radius: 1rem; font-size: 0.85rem; text-decoration: none; }
  nav.routine-tabs a[aria-current=page] { color: white; background: #315f68; font-weight: 600; }
  nav.routine-tabs.primary { padding-right: 1rem; border-right: 1px solid #ccd5d9; }
  .set-piece-routine { overflow: hidden; margin: 0.75rem 0 1rem; border: 1px solid #d6dee2; border-radius: 0.4rem; background: white; }
  .routine-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; padding: 0.85rem 1rem; background: #edf3f4; }
  .routine-heading h3 { margin: 0; color: #1a2b3c; font-size: 1rem; }
  .routine-heading p { margin: 0.25rem 0 0; color: #556; font-size: 0.85rem; }
  .routine-heading > span { flex: 0 0 auto; color: #5b6c72; font-size: 0.78rem; }
  .routine-assignments { padding: 0.2rem 1rem; }
  .routine-assignment { display: grid; grid-template-columns: minmax(9rem, 0.8fr) minmax(12rem, 1.7fr) auto; align-items: center; gap: 0.7rem; padding: 0.6rem 0; border-bottom: 1px solid #e8ecef; }
  .routine-assignment:last-child { border-bottom: 0; }
  .routine-assignment > b { color: #1a2b3c; }
  .routine-assignment > span:not(.set-piece-unit) { display: grid; gap: 0.1rem; }
  .routine-assignment small { color: #667; }
  details.routine-assignment-note { grid-column: 1 / -1; margin: -0.15rem 0 0; padding: 0; border: 0; background: transparent; }
  details.routine-assignment-note > summary { width: max-content; color: #31545c; font-size: 0.76rem; font-weight: 600; }
  .routine-assignment-reason { margin-top: 0.45rem; padding: 0.65rem 0.75rem; border-left: 3px solid #9fb6cf; border-radius: 0.25rem; background: #f7f9fa; }
  .routine-assignment-reason p { margin: 0 0 0.45rem; font-size: 0.82rem; }
  .routine-assignment-reason dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 0.45rem; margin: 0 0 0.45rem; }
  .routine-assignment-reason dt { color: #667; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; }
  .routine-assignment-reason dd { margin: 0.08rem 0 0; font-size: 0.8rem; }
  .routine-assignment-reason > small { display: block; font-size: 0.72rem; line-height: 1.4; }
  details.routine-evidence { margin: 0; padding: 0.7rem 1rem; border: 0; border-top: 1px solid #d6dee2; border-radius: 0; background: #fbfcfd; }
  details.routine-evidence > summary { color: #31545c; }
  details.routine-evidence table { min-width: 760px; margin-bottom: 0; }
  .set-piece-unit { display: inline-block; white-space: nowrap; padding: 0.15rem 0.4rem; border-radius: 0.8rem; color: #31545c; background: #e3eef0; font-size: 0.75rem; }
  .check-summary { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.75rem 0; }
  .check-summary span { padding: 0.35rem 0.6rem; background: #eef1f4; border-radius: 1rem; font-size: 0.82rem; }
  .role-combination { display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0.55rem 0; }
  .role-combination span { padding: 0.2rem 0.45rem; background: #eef1f4; border-radius: 0.25rem; font-size: 0.78rem; }
  .check-failures { margin: 0.3rem 0 0.4rem; padding-left: 1.2rem; color: #713900; font-size: 0.86rem; }
  @media (max-width: 700px) {
    body > nav { display: block; padding: 0.75rem 1rem; }
    .nav-links { gap: 0.4rem 1rem; }
    .fm-status { margin-top: 0.7rem; padding-top: 0.65rem; border-top: 1px solid #405365; text-align: left; }
    .fm-status form { display: inline-block; margin: 0.4rem 0.35rem 0 0; }
    main, main.wide { padding: 1rem; }
    form.opponent-form { grid-template-columns: 1fr; }
    .set-piece-assignments { grid-template-columns: 1fr; }
    .set-piece-assignment-card, .set-piece-assignment-card:nth-last-child(-n+2) { grid-column: auto; }
    .routine-switcher { align-items: flex-start; flex-direction: column; }
    nav.routine-tabs.primary { padding: 0 0 0.45rem; border-right: 0; border-bottom: 1px solid #ccd5d9; }
    .routine-heading { display: grid; }
    .routine-heading > span { white-space: normal; }
    .routine-assignment { grid-template-columns: 1fr auto; gap: 0.25rem 0.6rem; }
    .routine-assignment > span:not(.set-piece-unit) { grid-column: 1; }
    .routine-assignment > .set-piece-unit { grid-column: 2; grid-row: 1; }
    .taker-evidence .table-scroll { overflow-x: auto; }
    .taker-evidence table { min-width: 760px; }
  }
  @media (max-width: 600px) { .score-summary { grid-template-columns: 1fr; } .overall-score { border-right: 0; border-bottom: 1px solid #dfe3e7; padding: 0 0 0.75rem; } .opponent-range { grid-template-columns: 1fr; } .opponent-range small:last-child { text-align: left; } }
  tr.explanation-row td { padding: 0 0.6rem 0.55rem; background: #fcfcfc; }
  tr.explanation-row details { margin: 0; }
  .score-path { line-height: 1.8; }
  .tactic-link { white-space: nowrap; }
</style>
"""
