# Scouting workspace

`/scouting` is the external-player workspace. It intentionally consumes a
separate manager-visible candidate feed, rather than treating the owned squad
or FM's raw player structures as a recruitment universe.

## What it does

- filters candidates by position and role, then scores the selected role;
- shows a score **floor / estimate / ceiling** whenever the manager sees a
  range rather than an exact attribute;
- marks an eligible player with no known role attributes as **Scout first**;
- lists the highest-impact role attributes to scout next for partial profiles;
- keeps an exactly-known profile distinct from a range and an unknown value;
- filters safely supplied age, club, nationality, footedness, transfer status,
  availability, and any additional captured Player Search facts.

“Scout first” is an information recommendation, not a prediction that an
unknown player is good. Unknown attributes receive a conservative central score
while retaining their possible ceiling, so they neither leapfrog known players
on an invented rating nor disappear from the shortlist.

## Candidate-feed contract

Capture a manager-rooted Player Search pool through Frida, then start the web
app with that JSON feed:

```bash
uv run --extra research python tools/fm20_scouting_feed.py \
  --output data/scouting-capture.json
```

```bash
fm-web --direct-live --scouting-json data/scouting-capture.json
```

When either `data/scouting-capture.json` or the richer
`data/scouting-capture-hydrated.json` exists in this project, `fm-web` loads it
automatically. `--scouting-json` still overrides that choice.

The feed does not reproduce the filters currently open in FM. It takes the
manager's Player Search pool, removes the managed club's own contracted
players, and leaves all remaining filtering to this page.

### How the pool is obtained, and why it is gated

FM keeps this pool in process memory and builds it as you play, so the normal
path reads it with no native call at all -- the same read-only footing as every
other page. A capture taken this way records
`source.transport: read-only-process-memory`.

The pool is empty until FM builds it, which means it is empty after every FM
launch. Running FM's own builder to fill it executes FM code inside the live
game, and that is the step suspected of producing saves that write successfully
and then fail to load. So the capture tool will not do it unless asked:

- Without `--allow-rebuild`, an empty pool exits **3**, changes nothing, and
  reports that Player Search has not been opened yet.
- With `--allow-rebuild`, FM's builder runs and the capture records
  `source.poolRebuiltByCapture: true`.

On `/scouting`, the Refresh button never carries that consent. If the pool is
empty the page returns 409 and offers two routes: open Player Search in FM once
(recommended, no native call), or approve the rebuild with its warning. The
resulting page states which route produced the data, so the risky one is never
silent. Opening Player Search is needed once per FM session, not once per
refresh.

The first automatic feed has identity coverage only. Its candidates are shown
as **Scout first** and have no position match until external position and
attribute visibility have been proven. This is intentional: it is useful for
building the manager's true discovery queue, without pretending to know more
than FM has safely supplied.

### Accepted raw external-position gap

The product owner has accepted a documented short-term exception for
non-owned position data. Every scouting capture records the derived labels:

```bash
uv run --extra research python tools/fm20_scouting_feed.py \
  --output data/scouting-capture.json
```

This derives position labels from raw non-owned familiarity data and stores
them as `rawPositions`, separate from manager-visible `positions`. It does not
store individual raw familiarity ratings. On `/scouting`, tick **Use raw
external positions (accepted visibility gap)** to display and use those labels
for role and position filtering. The page warns that the data can reveal
secondary positions FM has not shown the manager. The checkbox does nothing
until the feed has been recaptured with the command above.

To hydrate a small set of known candidates with all of FM's manager-visible
attribute values and footedness, repeat `--hydrate-player-id` (up to 64 players). This is
bounded deliberately while the external-player route is validated:

```bash
uv run --extra research python tools/fm20_scouting_feed.py \
  --hydrate-player-id 9214 \
  --output data/scouting-capture-hydrated.json
```

Use `--base-feed` to retain previously captured visible fields. To update that
same known capture, pair it with `--replace` and name the exact output file.

The Scouting page can also start with a separately captured, manager-visible
JSON feed:

```bash
fm-web --direct-live --scouting-json data/scouting-capture.json
```

The document is either a player array or an object with a `players` array.
Each player must have an ID, name, positions, and an optional `attributes`
object using the normal visibility contract:

```json
{
  "players": [
    {
      "id": "12345",
      "name": "Example Striker",
      "positions": ["ST"],
      "age": 22,
      "club": "Example FC",
      "nationality": "England",
      "footedness": "Right",
      "transferStatus": "Listed",
      "availability": "available",
      "attributes": {
        "finishing": {"visibility": "range", "minimum": 11, "maximum": 15},
        "pace": {"visibility": "unknown"}
      },
      "facts": {
        "contract": "Full-time",
        "division": "Vanarama National League"
      }
    }
  ]
}
```

`facts` is the extension point for the wider FM Player Search filter set. Each
proven, manager-visible field is displayed as a filter automatically when it
appears in a capture. This avoids pretending a field is known before its
extractor is verified, while allowing the page to gain the full in-game filter
set without a UI redesign.

## Visibility boundary

The feed must be derived from a verified discoverability capture. Manager-
visible values are the default. `rawPositions` is the sole current exception:
it is permitted only through the explicit, documented accepted-gap path above,
and stays opt-in in the page. Footedness is displayed only when its external-
player visibility route is verified.

The page is ready for the Frida Player Search result-ID collector described in
[Frida and player discoverability](frida-discoverability.md). That collector
will become the candidate-feed producer; it must first prove exact agreement
with FM's visible Player Search results.
