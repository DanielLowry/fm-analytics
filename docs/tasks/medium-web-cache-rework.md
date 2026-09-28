# Medium task: web cache rework

**Active-plan status:** parked (see [Parked](../active-plan.md#parked)). Old
review items 1.5 and additional findings 1–2.

**Prerequisite:** the active plan schedules this item. Do it before the
[dashboard answer page](medium-dashboard-answer-page.md), which depends on it.

## Why we are doing this

The cache is now mainly a correctness problem. Opponent sliders already vary
the analysis, and the plan requires the cache key to include the pinned
tactics and opponent profile, not just time. Separately, two cold requests can
each pay for the same multi-second build.

## Current behaviour (`web/server.py`)

- `read()` keeps the provider result until an explicit **Refresh squad data**.
  `cache_ttl_seconds` is stored but deliberately unused
  (`test_read_is_not_recomputed_when_the_legacy_ttl_elapses`). The
  `--cache-ttl-seconds` help text still says it controls recomputation, which
  is now false.
- `bundle(opponent)` is an eight-entry LRU keyed by `OpponentProfile` only. The
  build runs outside `_lock`, so concurrent cold requests for one profile each
  build it.
- Pinned tactics are fixed for the server's lifetime, so they are not in the
  key. A comment in `__init__` says they must join it if they ever become
  editable.
- `_refresh_snapshot` swaps the read result and bundles together at the end and
  keeps the last good result on failure. Keep that.
- `scouting_rank_cache` checks candidate identity, so it is already safe
  across scouting refreshes.

## Scope

- **Single flight:** at most one build per key. Other requests for the same key
  wait for that build (a future or condition), rather than starting their own.
- **Key:** snapshot identity + opponent profile + pinned tactics.
- **Freshness:** every page can show the snapshot's game date, build time and
  the last refresh error; a last-good result after a failed refresh is labelled
  stale.
- **Legacy TTL:** remove `cache_ttl_seconds` and `--cache-ttl-seconds`, or fix
  their help text, per the reserved decision.
- Keep the tactic drill-down cache consistent with bundle eviction.

## High-level change outline

1. Introduce a small cache record: key, bundle or in-progress future, build
   time, error.
2. Give snapshots an identity: a generation counter bumped on refresh, or a
   public canonical fingerprint helper. Do not call the private
   `SnapshotStore._fingerprint` from web code.
3. Move `bundle()` and `tactic_report()` onto the record.
4. Add a concurrency test: a slow fake builder and several threads must
   produce exactly one build per key.
5. Update the tests that pass `cache_ttl_seconds`.

## Decisions reserved for review

- Generation counter or content fingerprint as snapshot identity.
- Remove the TTL flag, or keep it with honest help text.
- The LRU size.

## Success criteria

- N concurrent cold requests for one key cause one build.
- Different opponents or pins never share a bundle.
- A failed refresh leaves the last good result visible and labelled stale.
- Output is unchanged: the same bundle as a direct
  `build_recommendation_bundle` call.
- Focused web tests and the full suite pass.

## Likely code and tests

- `src/fm_analytics/web/server.py`
- `src/fm_analytics/web/rendering.py` for the freshness line
- `tests/test_web_server.py`
