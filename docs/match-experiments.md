# Tactic experiments

Added 10 October 2026. Store the matches you choose, group them, and compare
what you tried, label by label.

## Why

FM's match engine is random, and a season's matches each have a different
opponent, venue and squad, so a season says little about one tactical change.
Replaying a fixture is the closest FM comes to a controlled experiment: save
before a match, play it, store it with a label for what you tried, reload and
play it again with one thing changed. Only that one thing differs.

## What is stored, and when

**Nothing, unless you ask.** Reading matches from FM never adds to it.

- **The Experiments page** (`/experiments`), with fm-web run `--direct-live`:
  *Read FM and store the match I've just played* reads FM read-only into
  `data/experiment-capture.json`, never the match history's capture, and
  keeps the latest match with full stats.
- **Any match page** under Matches: *Store this match for experiments* copies
  that match as recorded.
- **The command line:** `uv run fm-experiments store` (FM), `store-history
  KEY`, `group create|add|remove`, `relabel`, `withdraw`, `restore`, `list`,
  `compare [GROUP]` and `export [GROUP]`.

Each stored match is a copy of FM's whole record of it (stats, players,
timeline, shots, saved tactic), kept in `data/experiments.sqlite3`
(`persistence/experiments.py`), apart from the match history: a replay is
not a match the season had, and recording one in the history would make it
that match's current version. While replaying a fixture, don't use *Read
matches from FM* on the Matches page; once you carry on with the playthrough
you keep, read matches as usual and the history takes that one.

Each stored match carries **your label** (the variant it tried; blank takes
the name of the tactic FM saved with it), an optional catalogue tactic,
**notes** for anything FM can't record (a change at half-time, say) and
**tags** (`key=value`). **Groups** are your own collections; a match can be
in several, and join or leave one at any time. Relabelling, withdrawing a
match from comparisons, restoring it and group changes are all later rows:
nothing is ever overwritten.

## How a group is compared

`reporting.build_experiment_report` (`analytics/experiments.py`) is the one
computation behind a group's page, `fm-experiments compare` and the export.
It compares the group's matches label by label on **the balance of chances**,
what your shots were worth less what theirs were, valued as a match page
values them (`chance_value`, from your competitive matches), with record,
points, goals, shots, shots on goal, clear-cut chances, second-half shots and
possession beside it. A label's matches are averaged, and their **spread**
(standard deviation) says how much one replay differs from the next.

A label is judged against the best only with at least 3 matches of each. A
gap is **clear** when it is more than twice its standard error (about 19 times
in 20 it is not chance); otherwise the page says how many matches of each
would settle a gap that size, from how much these matches vary.

**How many replays.** Over the save's 64 competitive matches (different
opponents, so more varied than replays of one fixture) the balance of chances
varied by 0.75 a match: telling two labels apart by 0.8 takes about 14
matches of each, by 0.5 about 35. Results vary far more: a gap of a point a
game takes about 28 of each. That is why the comparison leads with chances,
not results.

Each stored match also has its own page (`/experiments/match/ID`), the full
match page as stored, without the forms that save to the match history.

## Replays in FM's archive

A replayed fixture can leave a chunk per playthrough in FM's match archive.
`fm20_match_archive.chunk_for_players` picks the one whose player records
match the match still in FM's memory, so a replay with the same score as an
earlier one keeps its shots and timeline. Not yet checked against real
replays; if a stored replay shows no shots, that is where to look.
