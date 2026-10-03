# Dated league capture, version 1

The League pages consume a supplied JSON file through `fm-web --league-json`.
This contract is implemented by `domain/leagues.py`; it is separate from the
bridge squad contract and from research-only league inventories.
`tools/fm20_league_capture.py` produces it live from FM, read-only (see
"Capture the live league" below); `tools/league_demo.py` produces a labelled
synthetic example.

## Envelope

| Field | Meaning |
|---|---|
| `format` | Exactly `fm-analytics/league-capture` |
| `formatVersion` | Integer `1` |
| `saveKey` | Explicit identity for the save branch; use a new key after reloading to an earlier date |
| `game` | Existing game state: game date, active human manager, managed club |
| `season` | Season label, for example `2020/21` |
| `competition` | Existing competition document: `id`, `name` |
| `membershipComplete` | Boolean: evidence covers every current participant, including before matches have been played |
| `membershipEvidence` | Required description of the visible source/validation for the participant list |
| `sourceKind` | `manager-visible` for verified observations; `fixture` for explicit synthetic examples |
| `teams` | Array containing every observed participant, including clubs with incomplete data |

Each team has `squad`, boolean `rosterComplete`, boolean `positionsComplete`,
required textual `evidence`, and optional `errors` as a list of strings.
The squad uses the existing club/player document fields. `otherTeams` must be
empty: this comparison covers first-team membership rather than pooling youth
and reserve squads.

All squad dates must equal the capture's game date. Club and player IDs must
be unique, and each player's `clubId` must equal its roster's club ID. Complete
membership must include the managed club. The web reader also checks the
date/manager/club against the active squad source and requires identical owned
first-team player observations, including same-day revisions. This prevents
the league from presenting a different owned score under the same date label.

## Visibility and missing evidence

Only the 41 proven, manager-visible attribute names in
`domain/attributes.py::VISIBLE_ATTRIBUTES` are accepted. An observation is the
existing `known`, `range`, or `unknown` attribute document. Known values and
range endpoints must be in 1–20. An omitted attribute means **Uncaptured**;
`{"visibility": "unknown"}` means FM's visible unknown was actually observed.
Neither form removes a player from the roster.

External `positions` must contain only positions supported by manager-visible
evidence. The live capture lists the positions FM itself shows: FM's own
position-knowledge check (`tools/fm20_visible_positions.py`) gives the lowest
rating it displays for that player (Natural only, 16 and above, or every
position), and only positions at or above it are listed. An empty array
records missing position knowledge, and requires `positionsComplete: false`. External numeric `positionFamiliarity` is refused:
current research demonstrates that internal familiarity can reveal positions
hidden in FM's interface. The existing eligibility fallback is shown as an
assumption. Owned familiarity can use the established owned capture path.

`availability: "unknown"` on a rival is provisionally treated as available
with a visible assumption; owned eligibility remains unchanged. Missing
condition/sharpness uses the existing readiness fallback, also labelled.
The resulting attribute score bands are conditional on these policies; they
do not purport to bound unseen readiness or eligibility values.

Incomplete rosters, incomplete position evidence, and no legal XI are distinct
team statuses. These clubs remain visible, but receive no comparable score or
league rank. Membership incompleteness is shown separately; positions always
refer to the stated number of scored clubs.

## History and refresh

`LeagueHistoryStore` uses a separate SQLite database, application ID `LEAG`
(`0x4C454147`), with sequential migrations beginning at version 1. It appends
complete capture documents, deduplicates identical content within a save key,
and accepts distinct revisions on the same game date. It refuses unrelated
databases, newer schemas, and new earlier-date captures in an existing branch.
`latest(..., as_of=...)` never returns a future observation.

Historical attributes are not merged into a new capture, and old rosters are
not used as today's membership. Changed files are read as a complete revision;
malformed replacements produce an error instead of a silently reused capture.
Producers should write a temporary file and replace the destination atomically.

The web computes a whole comparison revision in a single background job,
with at most one pending request and two cached reports. Previous completed
reports stay visible only within the same save/tactic scope, with an update
notice and their original date. A failed calculation exposes a retry.
A new revision recomputes only the clubs whose inputs changed: club results
are cached in memory, keyed without the game date.

Migration 2 adds `league_team_summaries`: each comparison's per-club result
(range, status, conservative system and XI), keyed by save, capture content
hash, scope and club. The scope is the tactic choice plus a fingerprint of the
catalogue's content and the selection policies, so reads are compared only
when the same model scored them. These are derived results kept to explain
the next read. They are never used as observations.

## Capture the live league

With FM running, start `uv run fm-web --direct-live` and press **Read the
league from FM** on `/league`. That runs the capture tool, which can also be
run directly:

```bash
uv run --extra research python tools/fm20_league_capture.py   # -> data/league-capture.json
```

In live mode the server's league file defaults to `data/league-capture.json`.
`--league-json` points it elsewhere.

The capture lists every first team whose league link is ours this season,
checked against any played league results. Our own row is read exactly as the
Squad page reads it. Rival availability is `unknown`. The file is replaced
whole, and the web picks up a new capture on the next page load. After the
game date moves on, the page shows **League out of date** with the button,
because a capture from another date is never compared with today's squad.

## Review an example

From the repository root:

```bash
uv run python -m tools.league_demo
uv run fm-web --fixture data/league-demo/squad.json --league-json data/league-demo/league.json
```

The generator writes a matching own squad and explicit synthetic league with
known, wholly unknown, and incomplete teams. All pages label it example data.
The league inventory recipe is diagnostic evidence and cannot be substituted
for this capture by changing a flag.
