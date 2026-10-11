# Match-stat capture coverage

Verified 11 October 2026. This is the extractor's coverage, not a claim that
every selectable FM statistic has been mapped. A match marked `full_stats`
has a detail record; that flag does **not** mean every FM column is captured.

| Category | Captured per player | Gaps / limits |
|---|---|---|
| Passing | Attempts, completions, key passes | Detailed pass locations, lengths and types are not captured. |
| Crossing | Attempts and completions, added 11 October 2026 | Old captures omit both fields. Delivery locations, minutes, and open play versus set pieces are not distinguished by these totals. |
| Heading | Attempts and headers won | Key headers are not mapped. Headers lost can be calculated as attempts minus won. |
| Tackling | Attempts and tackles won | Key tackles and interceptions are not mapped. Tackles lost can be calculated as attempts minus won. |
| Shooting | Shots, on target, blocked, goals, clear-cut chances | Off-target counts can be calculated as shots minus on target minus blocked. Shot origins are not captured; the existing shot coordinates describe the goal plane. |
| Creation / other | Assists, chances created, dribbles, fouls, corners taken, goalkeeper goals conceded | These are not substitutes for crossing counts. Other selectable player-stat columns still need individual verification. |
| Appearance | Position, starting position, role family, selected verified duties, rating, substitutions, minutes and distance | In-match instruction changes and OIs are not captured. The duty record's general timing limitation remains documented separately. |

Cards and goal events are captured through the timeline/result records,
rather than a complete set of player-stat columns. Set-piece identification
remains incomplete. See [replay extraction](match-replay-extraction.md).

## Crossing verification

The manager read the following from **Hungerford 1–1 Woking, 10 October
2020** in the save:

- Ben Jefford: **4 attempts, 25% completion** → 1 completion.
- Josh Casey: **22 attempts, 27% completion** → 6 completions.

Casey's displayed whole percentage alone does not determine a count without
a rounding convention. The extracted count of six gives 27.27%, consistent
with the displayed 27%; Jefford gives exactly 25%.

The archived player fields are offsets **76 and 77** relative to the short
ID. Their live equivalents are **0x8f and 0x90**. All **28 played player
records**, in three live copies of that same match, agreed field for field.
The summed counts are **33/5 for Hungerford, 58/10 for Woking**. The live
team counters at **0xd6/0xd8** agree with those sums. The archive reader
derives team crossing totals from its player records. Capture validation
rejects live player/team disagreements and completions exceeding attempts.

Local evidence is retained in
`data/research/matches/woking-cross-verification-2026-10-11.json`.
Regression checks cover pinned player fields, team sums, standard/single
match exports, and missing-versus-zero coverage.

A fresh read-only capture of the **currently loaded FM checkpoint** into a
temporary file recovered **84 match records, 80 with detail**. A temporary history database and the shared
standard-export function produced both teams' crossing counts and every
played player's crossing counts for all 80, with no missing crossing keys.
The standard and single-match exports reproduce Jefford **4/1 (25%)** and
Casey **22/6 (27.3%, shown as 27% in FM)**. These verification exports are
retained at `data/exports/crossing-validation-season-standard-2026-10-11.json`
and `data/exports/crossing-validation-woking-match-2026-10-11.json`.
This validation did not write either of the user's existing match databases.
It is an extraction check, not a replacement for the recorded actual season:
the loaded checkpoint is earlier than the history's latest recorded date
and includes a replay of Hampton. Load the actual season save before the
production recapture so experimental results do not replace real fixtures.

Validation: **175 targeted tests pass**. The full suite ran **1,788 tests**;
the only two failures are repository file-size checks (`reporting.py` over
1,000 lines and the 99th-percentile file count over its target). These are
outside the crossing/export files changed here. Python compilation and
whitespace checks pass. The live app was gracefully restarted with its
existing `--direct-live` command, and its standard-export endpoint was
verified to return both teams' recorded player stats and coverage metadata.

## Exports and recapture

Both the **standard season export** and the **individual match / all-matches
copy** include both teams' panels and both teams' recorded player counts.
Verbose exports include the same counts with additional detail. Basic
exports remain compact. The standard export previously omitted most
per-match player counts and the opponent's lines, even where the database
already held them; that omission is now corrected.

Player `stats_recorded` lists the actual keys captured. Existing non-cross
zero counts can remain omitted from the compact `stats` dictionary; a key
in `stats_recorded` identifies a known zero. A key absent from
`stats_recorded` was not measured. Recorded crossing zeros remain explicit.
Team/player crossing percentages are derived from the two counts.
Season player crossing summaries include `crossing_coverage` (observed
appearances and minutes), and crossing per-90 rates use only those observed
minutes. Older missing crosses do not become artificial zeros.

To backfill the actual season, **load the actual season save, Read matches
from FM, then export again**.
Exporting alone cannot recover a field missing from a saved capture. FM must
still retain an identifiable archive or live record for each match.
Recapture uses the existing versioned match-history path; no SQLite schema
change or replacement of the experiment records is needed.

## Earlier experiments

At the investigation checkpoint, the current archive matched only **run 75**
uniquely against the stored replays' existing player-stat fingerprints.
No matching archive record for **74** was found. The old experiment JSON
contains decoded stats, not the original undecoded stat bytes, so adding a
decoder cannot reconstruct missing crosses from those JSON records alone.
This is not a general claim that FM can never retain replays: other save or
archive copies might help, but recovery is not established for those runs.

The earlier shots, clear-cut chances and key-pass comparisons remain
measurements of those outcomes. They do not establish whether pressing
reduced crossing frequency or completion. Preserve the results and this
limitation in the [Hampton experiment record](hampton-experiments.md).
