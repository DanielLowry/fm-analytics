# Medium task: background scouting refresh

**Active-plan status:** parked (see [Parked](../active-plan.md#parked)). Old
review item 3.2.

**Prerequisite:** the active plan schedules this item. If anyone has
uncommitted changes to `tools/fm20_scouting_feed.py`, coordinate with them;
the recommended design below avoids editing that tool.

## Why we are doing this

**Refresh scouting data** blocks the browser for the whole refresh: about 31 s
for the feed plus about 3.5 s to record player knowledge (measured on 27
September 2026). Worse, it holds `_scouting_refresh_lock`, which
`SquadWebServer.scouting()` also takes, so every other Scouting request waits
too.

## Current behaviour

- `POST /scouting/refresh` calls `SquadWebServer.refresh_scouting()` inside
  the request. That runs `_scouting_refresh_command` (`web/rendering.py`): a
  `uv run … tools/fm20_scouting_feed.py --output <capture> [--base-feed
  <capture> --replace]` subprocess with a 240 s timeout.
- The tool writes the output file in place (`open("w")` then `json.dump`),
  which is why reads are locked out while it runs.
- On success the server records knowledge (which never fails the refresh) and
  warms rankings in a thread.
- The squad refresh already runs in the background (`request_refresh`,
  `_refresh_snapshot`, `_refreshing`, shown by `status_html`). Follow that
  pattern.

## Scope

- One job state: idle, running, succeeded or failed, with start and end times,
  the result message and any error. A second start while running is rejected.
- The POST returns straight away (303 to `/scouting?refresh=started`).
- The page keeps serving the last good feed during a refresh, and shows the
  job state and the capture's age.
- Atomic replacement: run the tool with `--output <capture>.tmp --base-feed
  <capture>` (no `--replace`), then `os.replace` it into place on success.
  Reads then never need the lock for the whole refresh, and the research tool
  is unchanged.
- After the swap: record knowledge, then warm rankings, as today.

## High-level change outline

1. A small job object on the server, guarded by its own lock.
2. A worker thread that runs the command, swaps the file and records
   knowledge.
3. Narrow `_scouting_refresh_lock` to the swap only.
4. Render the state on the Scouting page. Choose a small poll in
   `scouting_script.py` or a reload link.
5. Tests with a fake refresh command: duplicate start, failure keeps the old
   feed, success swaps and records, reads during a run return the old feed,
   and shutdown with a running job.

## Decisions reserved for review

- Poll or manual reload.
- What happens to a running subprocess when the server stops.

## Success criteria

- The POST returns in well under a second.
- A second start while running is refused with a clear message.
- A failed or timed-out refresh leaves the previous feed in use, with the
  error shown.
- A reader never sees a partly written feed.
- Knowledge recording still happens once per successful refresh and still
  never fails it.
- Focused web tests and the full suite pass.

## Likely code and tests

- `src/fm_analytics/web/server.py`
- `src/fm_analytics/web/rendering.py` (`_scouting_refresh_command`)
- `src/fm_analytics/web/scouting_pages.py`, `scouting_script.py`
- `tests/test_web_scouting.py`, `tests/test_web_server.py`
