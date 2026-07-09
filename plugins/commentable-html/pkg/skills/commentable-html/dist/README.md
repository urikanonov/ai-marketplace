# dist/ - generated economy bundle (do not hand-edit)

Build output of `python tools/build.py`, derived from `assets/`. These are the
files a consumer copies next to an **economy-mode** document. Never edit them by
hand; `python tools/build.py --check` fails if they drift from the sources.

| File | Role |
| --- | --- |
| `ECONOMY.html` | the economy starting shell (references the companions via `<link>` / `<script src>`). |
| `commentable-html.v<V>.css` | the external layer stylesheet. |
| `commentable-html.v<V>.js` | the external runtime. |
| `commentable-html.v<V>.assets.js` | the asset registry (css + js as strings) used by "Export standalone" to rebuild a single portable file. |
| `manifest.json` | the version and a SHA-256 per companion. |

The inline / standalone template is the root `TEMPLATE.html` (also generated). For
the source files these are built from, see `assets/`.
