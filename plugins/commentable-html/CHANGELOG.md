# Changelog

All notable changes to the `commentable-html` plugin are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-07-11

### Added

- Author-time syntax highlighting (`tools/highlight_code.py`) now covers many more popular languages:
  Rust, Ruby, PHP, Swift, Kotlin, Scala, Dart, R, Perl, PowerShell, Lua, TOML, CSS, Groovy, Elixir,
  Haskell, and Objective-C, plus Windows Batch (`batch`, with `bat` and `cmd` aliases), with the usual
  aliases (`rs`, `rb`, `kt`, `pl`, `ps1`, `ps`, `objc`, `hs`, `ex`, `exs`). Shell scripts were already
  covered via the existing `shell` and `sh` aliases for `bash`. Run
  `python tools/highlight_code.py --list` for the full set.
- The in-browser diff highlighter now recognizes the same expanded language set (CSS, Groovy, Elixir,
  Haskell, Objective-C, Lua, PowerShell, and Windows Batch, plus their aliases), so review diffs in
  those languages render with token colors instead of plain text.

### Fixed

- Keywords are now matched case-sensitively except in genuinely case-insensitive languages (SQL, Batch,
  PowerShell, HTML, CSS). Previously a global case-insensitive match mis-colored ordinary identifiers as
  keywords (for example C# `String`, Python `true`/`none`, Rust `Fn`).
- String tokenization is now linear time. Pathological input (a long run of escaped quotes) previously
  drove superlinear rescanning; the string patterns use an unrolled form that stays fast.
- Strings keep a backslash-newline line continuation inside the string, unterminated block comments and
  strings still highlight (to end of input / end of line), Swift and Dart triple-quoted strings and TOML
  literal (single-quoted) strings are recognized, and a Windows Batch `rem` comment is matched on a word
  boundary (so `rem`, `rem<TAB>`, and a bare `rem` are comments, but `remark` is not).

## [1.2.2] - 2026-07-11

### Changed

- Clarified the NonPortable asset-location wording in the skill reference: the default companion
  files are referenced by a relative path (the skill's `dist/` folder by default), not "beside the
  document"; the document sits beside its companions only when they are copied there.

## [1.2.1] - 2026-07-11

### Changed

- Documentation wording now describes the NonPortable default accurately. The skill reference and the
  plugin README no longer call a generated document "single-file" or "Portable" by default: the default
  NonPortable document loads its CSS/JS from companion files, while Export as Portable (or `--portable`)
  produces the one self-contained file.

## [1.2.0] - 2026-07-11

### Fixed

- Mobile responsiveness of generated documents. Wide tables now scroll horizontally inside their own
  box on narrow screens instead of forcing the whole page to overflow. The Kusto query caption stacks
  the cluster title and the "Run in Azure Data Explorer" link onto separate lines below 700px so they
  no longer cramp. The floating Copy/language pills reserve top headroom over every code block (KQL
  figures included) so they no longer overlap the first line of code. Figures use symmetric vertical
  margins with no side indent so embedded images and charts get the full content width.
- On touch / coarse-pointer devices the browser's native selection menu (Copy, Share, Look up) is left
  intact; the reader can copy selected text again, while the floating "Add comment" popup still handles
  commenting.

### Changed

- `docs/TUTORIAL.md` now references the running example with a skill-root-relative display path that links
  to the local file, so the reference reads cleanly without any `..` path traversal.

## [1.1.3] - 2026-07-11

### Fixed

- Documentation accuracy from the agency review pass: the generated-document header comment (and the
  two shipped example reports) now name the Export as Portable download `<stem>-portable.html`, matching
  the current UI (it previously said `<stem>-comments.html`); and `references/design-decisions.md` now
  states correctly that a `<canvas>` renders when either the Chart.js loader OR an inline `getContext`
  draw is present, so a hand-drawn non-Chart.js canvas is accepted and only a canvas with neither is
  flagged (matching `validate.py` E3).

### Notes

- Documentation-only changes; no code or runtime behavior change.

## [1.1.2] - 2026-07-11

### Fixed

- `chart_block.py`: self-validation writes its temporary file to the system temp directory instead of
  the current working directory, so it works from a read-only directory (matching `new_document.py`).
- `kql_highlight.py`: added a `--` end-of-flags separator so a positional value that begins with `--`
  is taken literally instead of being rejected as an unknown flag.

### Notes

- Follow-up robustness fixes from the agency review pass; no change to the runtime review behavior.

## [1.1.1] - 2026-07-11

### Fixed

- `new_document.py`: corrected docstrings that referenced a removed CLI export tool; `--assets-href "/"`
  now produces root-relative companion references instead of dropping the prefix; a cross-drive `--out`
  gives an actionable message instead of a raw `relpath` error; `--copy-assets` copies the companions
  before writing the HTML so a failed copy never leaves a broken file; the write path reports `OSError`
  cleanly; `--copy-assets` / `--assets-href` warn when combined with `--portable`; a custom `--template`
  defers the companion existence check (it previously always failed self-validation); and self-validation
  no longer writes its temp file under the current working directory, so it works from a read-only
  directory.
- `validate.py`: the NonPortable remote-URL and absolute-path checks always run (they are structural),
  and only the on-disk existence check is gated on `base_dir`, so an `--assets-href` remote/absolute path
  is caught at generation time. Added direct `base_dir` unit tests.
- `inline_images.py`: a missing or unreadable input file now reports a clean error and exits 1 instead
  of raising an uncaught `OSError`.

### Notes

- Fixes surfaced by a 6-model rubber-duck review panel on the NonPortable-first change, plus a
  plugin-description wording tidy-up (drop "single-file" now that NonPortable is the default). No change
  to the runtime review behavior.

## [1.1.0] - 2026-07-11

### Added

- Resizable comments sidebar with a keyboard-focusable drag handle, persisted width, viewport clamps, and matching reserved page space.
- Problem statement plus self-review, peer-review, and reviewer-side review-loop documentation for the generated review surface.
- Documentation that explains when to use NonPortable for fast local iteration and when to Export as Portable for sharing or long-term storage.

### Changed

- Runtime left navigation side menu now labels itself as "Navigation" while leaving author-authored table-of-contents titles alone.
- Sidebar header actions wrap into narrower rows instead of overflowing when the viewport or resized sidebar is narrow.

### Fixed

- Chart.js canvases, including pie and doughnut charts, stay bounded inside `figure.chart` at narrow widths.

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
