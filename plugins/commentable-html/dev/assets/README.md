# assets/ - canonical sources (edit these)

The hand-edited single source of truth for the commentable-html layer. Everything
else - the root `TEMPLATE.html` and the whole `dist/` bundle - is **generated** from
these files by `python tools/build.py`; never hand-edit the generated outputs.

| File | Role |
| --- | --- |
| `commentable-html.css` | the layer stylesheet (the CSS region body). |
| `commentable-html.js` | the runtime (the JS region body). Its `CMH_VERSION` constant is the single source of the version used across dist filenames, the handshake `<meta>`, and the manifest. |
| `template.shell.html` | the page shell with `{{CMH_CSS}}` / `{{CMH_JS}}` placeholders, the five-region scaffolding, the toolbar/sidebar UI, and the demo content. |

After editing, run `python tools/build.py` (then `node tests/fixtures/generate.mjs`)
to regenerate. See `docs/DEVELOPMENT.md`.
