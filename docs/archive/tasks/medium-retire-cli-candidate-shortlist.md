# Medium task: retire the CLI candidate shortlist

> **Complete; archived 29 September 2026.** Built 29 September 2026. The
> *Status* section at the end records what was built and the decision taken.
> Open work is listed in the [task briefs index](../../tasks/README.md).

**Active-plan status:** parked (see [Parked](../../active-plan.md#parked)). Old
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

## Status

**Built 29 September 2026**, with the product owner confirming retire-rather-
than-merge before starting.

- **Removed:** `--candidate-html`/`--candidate-player-count` and their
  validation in `cli.py::main`; `cli.py::load_html_import` (its only caller);
  the `shortlists` plumbing through `main` and `render_recommendation`;
  `CandidateVerdict`, `RecruitmentCandidate`, `RecruitmentShortlist` and
  `shortlist_candidates` from `analytics/recruitment.py`, and their exports
  from `analytics/__init__.py`; the two shortlist tests in
  `tests/test_recruitment.py` and the one CLI-level test in
  `tests/test_cli_recommendation.py` that exercised the removed flags. The
  generic `parse_fm_html_export`/`merge_fm_html_exports` Player Search parser
  in `imports/fm_html.py` was *not* removed: `tests/test_fm_html_import.py`
  and `tests/test_selection_input.py` still exercise it directly, and
  `test_selection_input.py` uses it to build `FmHtmlExport` fixtures for the
  `--fm-html` squad overlay, so it was not actually Player-Search-only-and-unused.
- **Kept, unchanged:** `RecruitmentBrief` and `build_recruitment_briefs`
  (`reporting.py` still computes `bundle.briefs` for every bundle);
  `VisibleExportPlayer`, `imports/fm_html.py`, and the `--fm-html` squad
  overlay path (`load_squad_html_import`, `overlay_squad_export`), which the
  set-piece dedicated-ratings feature depends on.
- **Decision on "does the CLI keep printing briefs":** yes. `render_recommendation`
  still prints the `Recruitment briefs` section unchanged, now followed by one
  line -- "For candidates against each brief, see fm-web's /scouting page." --
  where the candidate shortlist used to print. Briefs cost nothing extra to
  compute (`reporting.py` already builds them) and remain useful on their own
  without a shortlist attached.
- **Docs updated:** `CLAUDE.md`'s recruitment paragraph now describes one path
  instead of two unreconciled ones; `docs/phases/06-recruitment/README.md`'s
  "Implemented slices" section describes the web path as canonical and the
  retirement as done rather than proposed; `docs/active-plan.md`'s parked entry
  and its "previous review's items" table both point here as built.
- Tests: `tests/test_recruitment.py` (brief-generation test kept, shortlist
  tests removed), `tests/test_cli_recommendation.py` (removed-flag test
  deleted, remaining recommendation/briefs-output tests unchanged),
  `tests/test_fm_html_import.py` and `tests/test_selection_input.py`
  (untouched, still passing, confirming the generic HTML parser and the
  `--fm-html` overlay path are unaffected). `py_compile` across `src/` and a
  full-suite run confirm no dangling reference to any removed name.
