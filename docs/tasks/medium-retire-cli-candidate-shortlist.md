# Medium task: retire the CLI candidate shortlist

**Active-plan status:** parked (see [Parked](../active-plan.md#parked)). Old
review items 2.2 and 3.3.

**Prerequisite:** the product owner confirms the plan's proposed resolution:
treat the web `ScoutingCandidate` path as canonical, and retire the CLI HTML
shortlist rather than merge the two.

## Why we are doing this

Recruitment exists twice. `fm-analytics --recommend --candidate-html …` loads
Player Search HTML exports into `imports.VisibleExportPlayer` and calls
`analytics.recruitment.shortlist_candidates` for each of `bundle.briefs`.
`/scouting` ranks `ScoutingCandidate` from the JSON feed and is where every new
feature is going. Keeping both means each feature is missing on one side.

## Scope

**Remove:**

- the CLI options `--candidate-html` and `--candidate-player-count`, and their
  code path in `cli.py`;
- `shortlist_candidates`, `RecruitmentCandidate`, `RecruitmentShortlist` and
  `CandidateVerdict`, if nothing else uses them, with their exports from
  `analytics/__init__.py`;
- the shortlist tests; and
- any Player Search-only HTML parsing left unused afterwards.

**Keep:**

- `build_recruitment_briefs` and `RecruitmentBrief`. `reporting.py` builds
  `bundle.briefs` for every bundle, the CLI prints them, and the
  [weakest-slot service](../archive/tasks/medium-weakest-slot-service.md) may reuse them.
- `VisibleExportPlayer` and `imports/fm_html.py`. The `--fm-html` squad
  overlay uses them, and the set-piece quick win depends on that overlay.

## High-level change outline

1. Trace every use of the names to remove, with `grep`, before deleting.
2. Delete the path. Have the CLI print one line pointing to `fm-web`'s
   `/scouting` where the shortlist used to appear.
3. Update the documents: the "Recruitment currently exists twice" paragraph in
   `CLAUDE.md`, the [Phase 06](../phases/06-recruitment/README.md) status, and
   the active plan's parked entry.

## Decisions reserved for review

- Retire rather than merge (the plan calls it proposed, not decided).
- Whether the CLI keeps printing briefs.

## Success criteria

- `fm-analytics --recommend` output is unchanged apart from the removed
  shortlist section.
- `--fm-html` squad overlay and set-piece dedicated ratings still work, with
  their tests unchanged.
- No remaining references to the removed names.
- CI compile step and full suite pass.

## Likely code and tests

- `src/fm_analytics/cli.py`
- `src/fm_analytics/analytics/recruitment.py`, `analytics/__init__.py`
- `src/fm_analytics/imports/fm_html.py`, check only
- `tests/test_recruitment.py`, `tests/test_cli_recommendation.py`
- `CLAUDE.md`, `docs/phases/06-recruitment/README.md`, `docs/active-plan.md`
