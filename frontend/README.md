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
