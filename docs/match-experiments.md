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
  `data/experiment-capture.json`, never the match history's capture. It
  reads the latest match alone, in about 2.5 seconds (see "Replays in FM's
  archive" below). If that quick read cannot vouch for the match's stats it
  falls back to reading every match, about 15 seconds more. It never stores
  an older match in place of the latest.
- **Any match page** under Matches: *Store this match for experiments* copies
  that match as recorded.
- **The command line:** `uv run fm-experiments store` (FM), `store-history
  KEY`, `group create|add|remove|rename|delete`, `relabel`, `withdraw`,
  `restore`, `delete`, `list`, `compare [GROUP]` and `export [GROUP]`.

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
match from comparisons, restoring it and group membership changes are all
later rows: nothing is overwritten.

## Tidying up

- **Delete a stored match** from its own page, from *Edit* on a group's
  page, or tick several on the Experiments page. Each takes two clicks
  (*Delete…*, then *Delete permanently*), and `fm-experiments delete ID...`
  does the same. It is gone for good, from every group. To keep a match but
  leave it out of comparisons, **withdraw** it instead, which can be undone.
  The number of the latest match stored can be given to the next one.
- **Rename a group** or change its note on the group's page
  (`fm-experiments group rename NAME --to NEW [--note TEXT]`); its matches
  stay in it.
- **Delete a group** there too (`fm-experiments group delete NAME`). Its
  matches stay stored, and in any other group they are in.

These are the only changes to the store that remove or rewrite rows, and
only when you ask.

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

## Exporting a group

*Copy all match data* on a group's page (and on *Compare all stored
matches*) copies the group as JSON, as the Matches page's button of the same
name copies the matches its filters select. `fm-experiments export [GROUP]
[--output FILE]` writes the same document. It is built by
`reporting.build_experiment_export` (`experiment_export.py`) and holds:

- **`variants`** and **`comparisons`**: the comparison the page shows. Each
  label also has its own `breakdowns` (by the score, by period, how the goals
  came, formations faced) and `players` (each player's figures in that
  label's matches), so a player can be compared from one label to the next.
- **`breakdowns`** and **`players`**: the same over the whole group.
- **`matches`**: every stored match with its label, notes, tags and groups,
  its comparison `figures`, and its `match`, exactly what that match's own
  page would copy (team panels, every player's line with role and rating,
  timeline, every shot, unused substitutes, saved tactics, league table at
  kickoff). A match stored from the history exports the same `match` as its
  page under Matches does. Replays of one fixture share a date, so
  `stored_match_id` tells them apart.

Withdrawn matches are listed (`withdrawn: true`, no `figures`) but counted in
none of the comparison, breakdowns or player figures.

## Replays in FM's archive

FM keeps every match's full stats in archive files on disk, one chunk per
match, and the managed club's matches are kept in the order played.
**Reloading a save does not roll that archive back**: after a reload on
10 October 2026, FM's results ended at the Woking match but the archive
still ended with the discarded Hampton playthrough. So a replayed fixture
leaves a chunk per playthrough.

The quick read takes the club's last archived chunk, the playthrough just
played. It uses that chunk only when it is the same fixture, its timeline
gives the score, and its goals and sendings-off match FM's result: the same
players at the same minutes. Those agreed in all 81 matches of the save
that have both. A chunk from a discarded playthrough fails these checks
unless every goal and red card fell the same way, so the quick read refuses
it rather than storing the wrong playthrough. The full read
(`fm20_match_archive.chunk_for_players`) instead picks the chunk whose
player records match the match still in FM's memory.

Discarded playthroughs stay in the archive after you carry on. When the
season's own read (*Read matches from FM* on the Matches page) finds more
chunks for a fixture than meetings, it keeps only a chunk that fits one
meeting alone, so a replayed fixture's stats can go missing from the match
history. They never come from the wrong playthrough.
