# assets

Canonical hand-edited sources for the commentable-html layer.

- `css/NN-topic.css` - layer stylesheet partials (directory-sorted; the sort order is the cascade). See `css/MODULES.md`.
- `js/NN-topic.js` - runtime partials (directory-sorted; the sort order is the single-IIFE statement order); one partial declares the `CMH_VERSION` source of truth. See `js/MODULES.md`.
- `template.shell.html` - shell with placeholders and commentable regions.

Edit the owning partial - never recombine into a `commentable-html.js`/`.css` monolith (a test
enforces its absence). After edits, run the build from `dev/` and see `../README.md` for the full workflow.
