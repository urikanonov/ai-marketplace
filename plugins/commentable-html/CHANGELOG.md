# Changelog

All notable changes to the `commentable-html` plugin are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3] - 2026-07-11

### Fixed

- `new_document.py`: corrected the module and `make_document` docstrings that referenced a removed CLI
  export tool; `--assets-href "/"` now produces root-relative companion references instead of dropping
  the prefix; a cross-drive `--out` gives an actionable message instead of a raw `relpath` error;
  `--copy-assets` copies the companions before writing the HTML so a failed copy never leaves a broken
  file; the write path reports `OSError` cleanly; `--copy-assets` / `--assets-href` warn when combined
  with `--portable`; a custom `--template` defers the companion existence check (it previously always
  failed self-validation); and self-validation no longer writes its temp file under the current working
  directory, so it works from a read-only directory.
- `validate.py`: the NonPortable remote-URL and absolute-path checks always run (they are structural),
  and only the on-disk existence check is gated on `base_dir`, so an `--assets-href` remote/absolute
  path is caught at generation time rather than slipping through.
- `inline_images.py`: a missing or unreadable input file now reports a clean error and exits 1 instead
  of raising an uncaught `OSError`.

### Notes

- Fixes surfaced by a 6-model rubber-duck review panel on the 1.0.2 change, plus a plugin-description
  wording tidy-up. No change to the runtime review behavior.

## [1.0.2] - 2026-07-11

### Changed

- New documents are now **NonPortable by default** (`tools/new_document.py`): the layer CSS/JS load
  from companion files, so authoring and every regeneration during a review loop is materially
  smaller (about 89% less boilerplate re-emitted). Pass `--portable` for a single self-contained file.

### Added

- `tools/new_document.py` gains `--portable`, `--nonportable` (the default), `--copy-assets`, and
  `--assets-href` to control how a NonPortable document references its companion files, plus
  `active_root_attrs` and an `allow_reserved_key` option for re-stamping an existing document.
- `validate.validate()` accepts an optional `base_dir` so NonPortable companion references can be
  resolved against the file's final location, or the path checks skipped (structure only) when
  placement is deferred.

### Notes

- To hand someone a single shareable file, either regenerate with `--portable` (for a document that
  has no in-browser comments yet) or use the in-page **Export as Portable** button. The button is the
  only path that captures comments the user typed in the browser: those live in `localStorage`, which
  no CLI (even a headless browser) can read, so there is deliberately no CLI export.

## [1.0.1] - 2026-07-10

### Changed

- Hardened the CI version-bump gate (`scripts/check_version_bump.py`): it now diffs from the merge
  base so a PR is judged only on its own changes, fails closed on an invalid or unfetched base ref,
  normalizes source paths correctly, and requires a version bump when a plugin's source path changes.
- Hardened `build.py` version stamping and the build `--check` drift guard.

### Fixed

- Quality fixes surfaced by a multi-model (multi-duck) review of the 1.0.0 refactor, including a
  statically pinned Chart.js loader for a stable SRI hash and assorted tool and documentation
  polish. No change to the runtime review behavior.

## [1.0.0] - 2026-07-10

First official release.

### Added

- Offline, single-file commentable HTML review surface: reviewers select any paragraph, table cell,
  code block, KQL block, chart, image, or mermaid diagram and leave inline comments, then copy or
  export a bundle back to an agent, with no network dependency.
- Portable mode (one self-contained file) and NonPortable mode (companion CSS/JS files).
- Deterministic Python tooling (`new_document`, `inline_images`, `chart_block`, `upgrade`, `validate`,
  and more) plus a standard-library validator that enforces the structural invariants of a generated
  file.
- Rich, commentable content: tables, Chart.js charts, mermaid diagrams, KQL blocks, code-review diffs,
  and inlined images.
- Each generated file stamps the skill version that produced it in a
  `<meta name="commentable-html-version">` in the head and in the visible footer.

### Notes

- The injected layer is version-agnostic: the region markers, the companion filenames, and the demo
  storage keys no longer embed a version. The single source of truth for the release version is
  `dev/VERSION`; `build.py` stamps it into the layer constant, `plugin.json`, the marketplace entry,
  and each document's version `<meta>`, and `build.py --check` guards against drift.
