# FM Analytics

Manager-visible analytics for Football Manager 2020: recommends tactics, XIs,
and recruitment targets using only information a human manager could see —
never hidden Current Ability, Potential Ability, or other internal values.

## Layout

```
src/fm_analytics/            CLI, the reporting path, the bridge contract
src/fm_analytics/analytics/  role/tactic scoring, catalogue, depth, weaknesses, opponent — see analytics/CLAUDE.md
src/fm_analytics/bridge/     HTTP boundary onto the game process — see bridge/CLAUDE.md
src/fm_analytics/domain/     Player/Squad/GameState and Visibility — the shared vocabulary
src/fm_analytics/api/        HTTP client for the bridge
src/fm_analytics/imports/    parses manager-visible FM20 HTML exports
src/fm_analytics/persistence/  SQLite stores: the squad capture (versioned, migrated from its
                             v4 baseline forward only -- older files are refused, not
                             reconstructed), and the player-knowledge and match histories
                             (append-only from v1, migrations required, one shared step-runner
                             in migrations.py that all three stores' migrations reuse)
src/fm_analytics/knowledge_ingest.py  scouting capture -> player-knowledge history (fm-knowledge)
src/fm_analytics/match_ingest.py      FM match capture -> match history, and the review (fm-matches)
src/fm_analytics/experiment_ingest.py stored matches for tactic experiments (fm-experiments): only
                             what the manager asks for, in data/experiments.sqlite3, never the history
src/fm_analytics/reporting.py  the ONE "compute a squad recommendation" path
src/fm_analytics/web/        read-only browser view over reporting.py
tools/                       low-level FM20 probe/monitor utilities (research-only)
tests/                       unittest-based tests, one module per source area
docs/                        architecture, delivery phases, contracts — see docs/README.md
data/                        local runtime captures — gitignored, absent on a fresh clone
```

## The one rule that matters most

`fm_analytics.reporting.build_recommendation_bundle` is the single full
recommendation computation used by the CLI (`fm-analytics --recommend`) and
the Tactics/Depth web views. `build_squad_role_matrix` is the deliberately
lighter shared computation for the Squad roster: it must not evaluate tactics.
**Never duplicate scoring logic into the CLI or web layers** — a number shown
on a page and a number printed by the CLI must be the same number, computed
the same way. Add or reuse a reporting helper rather than recomputing
analytics inside a handler. The match review follows the same rule:
`reporting.build_match_review` is the one computation behind both
`fm-matches review` and the Matches page, and `reporting.build_season_export`
the one behind `fm-matches export` and the web's `/api/export`.
`reporting.build_match_export` is the one behind a match page's "Copy match
to clipboard": that match's verbose season-export entry plus what only one
match has room for, its Diagnosis included, built from the same
`build_match_report` and `build_match_diagnosis` the page shows. A match's
mentality is the manager's record (`domain/mentality.py`, its own table that
reading FM never writes) and reaches every view through `MatchSummary.mentality`.
`reporting.build_matches_export` is the one behind the Matches page's "Copy all
match data" (`/api/matches-export`): every match the page's filters select,
each exactly as its own page's copy has it.
`reporting.build_match_diagnosis` is the one behind a match page's Diagnosis and
the same section of `fm-matches show`: that match against the usual range of
the other competitive matches, by the season diagnosis's own model, and its
"Result vs chances" (`analytics/match_chances.py`: the chances each side made,
valued by `analytics/chance_value.py`, against the score).
`reporting.build_match_breakdowns` is the one behind the Matches page's "By the
score", "By period", "How the goals came", "Against each formation", "Your
players" and "By mentality" panels, the same lines of `fm-matches review` and the exports' `breakdowns`
(`analytics/match_breakdowns.py`); a match's own split by the score comes with its
`build_match_report` timeline.
`reporting.build_experiment_report` is the one behind the Experiments pages and
`fm-experiments compare`: stored matches compared label by label
(`docs/match-experiments.md`); `reporting.build_stored_match_report` is a stored
match's own page, and `reporting.build_experiment_export` the one behind a group
page's "Copy all match data" and `fm-experiments export`: that comparison plus
each stored match exactly as its own page's copy has it.
`reporting.build_penalty_record` is the one behind the Matches page's "Penalties
you gave away" and the same lines of `fm-matches review`: the penalties scored
against us in the selected matches and who the manager recorded giving each away
(FM doesn't say; the record is kept in its own table, which reading FM never touches).
`reporting.build_contract_review` is the one computation behind `/contracts`
and the squad player report's Contract plan panel.
`reporting.build_league_comparison` is the one behind `/league` and its team
pages, deliberately without recent form (it exists only for our players), and
`reporting.league_scope` decides which earlier read a new one is compared with.
`reporting.build_appearance_coverage` is the one behind `fm-matches coverage`:
which appearances have a known tactic, position and role with its duty, and
`reporting.build_player_form` the one behind `fm-matches form`: each player's
recent form in each of those exact jobs. `reporting.squad_form` is the one way
that form reaches `build_recommendation_bundle` (web, `fm-analytics
--recommend` and the export alike), and only from the same club's history.

## Running things

```bash
uv run python -m unittest discover -s tests -v      # full test suite
uv run fm-analytics --fixture src/fm_analytics/fixtures/sample-game.json --recommend
uv run fm-web --fixture src/fm_analytics/fixtures/sample-game.json        # http://127.0.0.1:8766
uv run fm-matches capture && uv run fm-matches review   # needs FM running; read-only
uv run fm-matches export --detail basic|standard|verbose  # season JSON -> data/exports/
uv run fm-matches coverage [--days N | --all]   # which appearances could count towards form
uv run fm-matches form                          # each player's recent form in each job
uv run --extra research python tools/fm20_league_capture.py   # whole league -> data/league-capture.json (FM running)
```

No third-party packages are required for the core path (`frida` is an
optional dependency for research tooling only). CI (`.github/workflows/ci.yml`)
also compiles every source file and runs a bridge fixture smoke test — worth
checking before assuming a change is done.

## Getting a squad worth testing against

`fixtures/sample-game.json` is three players. It exercises the code paths but
tells you nothing about cost or about how a recommendation reads, so don't
judge either from it. Everything realistic lives in `data/`, which is
gitignored and will not exist on a fresh clone: the scouting pages fall back
to no candidates at all when it's missing (`web/server.py:_default_scouting_path`
tries three filenames in order), and `--snapshot-db` raises a bare
`RuntimeError` if the local capture predates the current `SCHEMA_VERSION` —
there are no migrations, so an old capture is simply unreadable.

For performance work, generate a synthetic squad of the size you care about
rather than reaching for the fixture or a capture. Measure the full bundle
against the whole shipped catalogue (42 tactics, 84 roles, 265 legal role
versions in total): it evaluates every permitted role version for every tactic
and then solves the player assignment, so a change that does not improve that
end-to-end measurement has not improved the page load.

Cost is driven far more by how many slots each player is eligible for than by
the number of tactics, so **always state the squad generator with a timing** —
figures from different synthetic squads are not comparable. About half the time
is the assignment solver running tens of thousands of times, which is a
consequence of the 35% weakest-slot term in the fit objective, not of the solver
being slow. The measured cost model, its method and the ranked mitigations live
in [docs/tactical-model-upgrade-plan.md](docs/tactical-model-upgrade-plan.md)
§7.1 — read it before optimising, and update it there rather than copying
numbers into other documents.

## Before editing

- `src/fm_analytics/web/` is split by concern: `server.py` (the caching
  HTTP server + CLI arg-parsing), `handlers.py` (one `_xxx_page` method per
  route; the Scouting routes live in `scouting_pages.py` as a mixin), `rendering.py` (shared HTML helpers), `providers.py` (data
  sources). Find the route you're changing in `handlers.py` first rather
  than starting from `server.py`.
- `src/fm_analytics/analytics/xi_selection.py` expands only the explicitly
  allowed role versions of a tactic, then uses an exact player-to-slot
  assignment. Read `analytics/CLAUDE.md` before changing either half: the
  separation is what makes the recommendation both fast and complete.
- Recruitment has one path now: `analytics/recruitment.py::build_recruitment_briefs`
  turns weaknesses into `RecruitmentBrief`s, and `analytics/scouting.py` ranks
  `ScoutingCandidate` against them from the web's JSON feed (`/scouting`). The
  CLI's older shortlist against `imports.VisibleExportPlayer`
  (`--candidate-html`) was retired 29 September 2026 in favour of this one; the
  CLI still prints briefs and points to `/scouting` for candidates against
  them. Do not reintroduce a second shortlist path — extend `scouting.py`.
- Scoring code is a transparent, reviewable POC, not a reproduction of FM's
  hidden match engine. It's fine to be wrong for football reasons; it must
  never be wrong because it read data a manager couldn't see.

For product/design rationale (why a feature exists, what's deliberately
deferred), see [docs/README.md](docs/README.md) rather than re-deriving it —
it's kept current and is more reliable than inferring intent from code.
