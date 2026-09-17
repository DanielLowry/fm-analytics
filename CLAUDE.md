# FM Analytics

Manager-visible analytics for Football Manager 2020: recommends tactics, XIs,
and recruitment targets using only information a human manager could see —
never hidden Current Ability, Potential Ability, or other internal values.

## Layout

```
src/fm_analytics/            domain models, CLI, bridge client
src/fm_analytics/analytics/  role/tactic scoring, catalogue, depth, weaknesses — see analytics/CLAUDE.md
src/fm_analytics/bridge/     HTTP boundary onto the game process — see bridge/CLAUDE.md
src/fm_analytics/reporting.py  the ONE "compute a squad recommendation" path
src/fm_analytics/web/        read-only browser view over reporting.py
tools/                       low-level FM20 probe/monitor utilities (research-only)
tests/                       unittest-based tests, one module per source area
docs/                        architecture, delivery phases, contracts — see docs/README.md
```

## The one rule that matters most

`fm_analytics.reporting.build_recommendation_bundle` is the single computation
both the CLI (`fm-analytics --recommend`) and the web view (`fm-web`) call.
**Never duplicate scoring logic into the CLI or web layers** — a number shown
on a page and a number printed by the CLI must be the same number, computed
the same way. If a page-specific view needs a derived value, derive it from
the `RecommendationBundle` the reporting path already returns, in the caller
(e.g. `web/server.py`), not by recomputing analytics there.

## Running things

```bash
uv run python -m unittest discover -s tests -v      # full test suite
uv run fm-analytics --fixture src/fm_analytics/fixtures/sample-game.json --recommend
uv run fm-web --fixture src/fm_analytics/fixtures/sample-game.json        # http://127.0.0.1:8766
```

No third-party packages are required for the core path (`frida` is an
optional dependency for research tooling only). CI (`.github/workflows/ci.yml`)
also compiles every source file and runs a bridge fixture smoke test — worth
checking before assuming a change is done.

## Before editing

- `src/fm_analytics/web/` is split by concern: `server.py` (the caching
  HTTP server + CLI arg-parsing), `handlers.py` (one `_xxx_page` method per
  route), `rendering.py` (shared HTML helpers), `providers.py` (data
  sources). Find the route you're changing in `handlers.py` first rather
  than starting from `server.py`.
- `src/fm_analytics/analytics/xi_selection.py` contains a beam search with a
  correctness property that looks like dead weight until you remove it — read
  `analytics/CLAUDE.md` before touching it.
- Scoring code is a transparent, reviewable POC, not a reproduction of FM's
  hidden match engine. It's fine to be wrong for football reasons; it must
  never be wrong because it read data a manager couldn't see.

For product/design rationale (why a feature exists, what's deliberately
deferred), see [docs/README.md](docs/README.md) rather than re-deriving it —
it's kept current and is more reliable than inferring intent from code.
