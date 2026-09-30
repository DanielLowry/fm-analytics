# FM Analytics frontend

This directory contains the source for the packaged web shell.  It takes a
small, purpose-built subset of TailAdmin's visual language; the application
does not vendor the upstream dashboard or its optional dependencies.

```sh
npm install
npm run build
```

The build writes `app.css` and `app.js` to `src/fm_analytics/web/static/`.
Those compiled assets are committed because the Python web server serves them
directly and has no Node runtime in production.

## UI review and remaining acceptance work

The [30 September 2026 review](../docs/ui-review-2026-09-30.md) records the
remaining dark-theme, responsive-layout, navigation and consistency work,
including evidence and acceptance criteria. The shell is implemented; the
review's follow-up checklist is still open. Follow the shared-component
direction there when changes are scheduled, and rebuild the committed assets
after editing these sources.
