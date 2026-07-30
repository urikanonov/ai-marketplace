# Changelog

All notable changes to the `commentable-html` plugin are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.276.0] - 2026-07-29

### Fixed

- The two author-time scans that locate code blocks - the syntax-highlighting guardrail
  (CMH-VAL-11) and the runnable-KQL rule (CMH-KQL-08) - now read PARSED elements instead of
  matching text over a masked copy of the document. The mask closed the two real defects it was
  built for, but a text scan still drew the block boundary in four places a browser does not, and
  each one could hide a real raw block from a guardrail that exists to catch it:
  - every HTML raw-text / RCDATA element holds text, not markup, yet only `<script>` and `<style>`
    were treated that way. A `<pre>`/`<code>` written inside a `<textarea>`, `<title>`, `<xmp>`,
    `<iframe>`, `<noembed>`, `<noframes>` or `<noscript>` was read as authored markup, and its
    unpaired opener could swallow the author's real block that followed;
  - a `<![CDATA[ ... ]]>` section in foreign content (`<svg>`/`<math>`) is a declaration whose
    content is character data, so a block quoted there was both flagged on its own and able to hide
    a later real one;
  - the legacy comment close `--!>` was not recognized, so a comment ending that way stayed "open"
    to the document's next `-->` - which the layer always supplies - blanking every authored block
    in between;
  - matching attributes up to the first `>` ended a tag inside a QUOTED attribute value, so
    `<code title="a > b" class="language-python">` lost its language label entirely and a
    `data-cmh-kql-no-cluster` marker written after such a value was invisible.

  All four now fall out of a shared tolerant tokenizer (`checks/parsing.code_block_spans`), which
  records the offsets of every real `<pre>`/`<code>` element; the `figure.cmh-kql` exemption comes
  from real ancestry (matched case-insensitively) and the no-cluster marker from parsed attributes.
  Because the host interpreter's own rules differ, every boundary is applied explicitly rather than
  inherited, so the same document validates identically on every Python the skill runs on: the
  raw-text set; the raw-text closer (`</script data-x>`, `</script/>`, which only Python 3.13+
  honours); the comment closes (`-->`, `--!>`, `<!-->`, `<!--->` - and NOT `-- >`, which the
  pre-3.13 delegate wrongly accepted); an unterminated comment running to the end of the document
  rather than resuming after the next `>`;   and CDATA, which is a section only when the CURRENT NODE is a foreign (`<svg>`/`<math>`)
  element - under an HTML integration point (`foreignObject`, `desc`, `title`, an
  `annotation-xml` with an HTML `encoding`, or a MathML text integration point) or after an HTML
  breakout start tag such as `<p>` or `<div>`, which pops the open foreign elements, it is a
  bogus comment ending at the first `>`, exactly as it is in ordinary HTML. Payloads are still
  sliced from the
  ORIGINAL document, so the language, the emptiness test and the highlight classification are
  decided on the bytes that ship, and the fail-closed warning for a code block whose structure a raw
  `<script>`/`<style>`/`<!--` destroyed is unchanged. If the parse itself fails, no blocks are
  reported at all and both checks refuse the document instead of passing it on an empty result.

## [1.275.0] - 2026-07-29

### Fixed

- The Offline export's two script strips now treat every executable JavaScript MIME type as
  runnable, not only the modern three. `_stripOfflineRichRenderers` and `_stripOfflineNetworkLoads`
  returned early for any `type` outside empty / `module` / `text/javascript` /
  `application/javascript`, but a browser also executes `text/ecmascript`, `application/ecmascript`,
  `application/x-javascript`, `text/x-javascript`, `text/jscript`, `text/livescript`, and
  `text/javascript1.0` through `1.5` - so a script carrying one of those types kept its remote
  dynamic import, and a stale mermaid or Chart.js loader shim survived the renderer strip. Both
  strips now share the one runnable-script-type predicate the evidence scan already used. The
  strict validator carried the same narrow set in its own independent Python copy, so such a file
  also passed `validate.py --strict` as offline-clean; it now mirrors the runtime predicate, and a
  parity test pins the two implementations together in both directions. The zero-network CSP
  blocked the fetch either way, so this is defense in depth; the strip is the primary guarantee and
  no longer leans on the CSP.
- Re-running `Export Offline` on an already-offline document that contains a mermaid diagram (or a
  chart the built-in renderer does not draw) now produces a working download instead of an
  "Offline export is missing the vendored mermaid bundle" error toast. An Offline export consumes
  the vendored payload and removes it, so the file it produces carries the libraries inline and no
  payload at all; the exporter now reads those already-inlined copies and their MIT notices before
  the strip removes them and re-emits them, so a re-export reuses what is already local. Because
  re-emitting a captured script grants it execution and the document being exported is untrusted,
  the `data-cmh-offline-lib` marker alone is not taken as proof this exporter wrote it: a captured
  copy must sit in the head, carry exactly the attribute shape the exporter emits (which rules out
  `src`, any `type` - so inert data and a non-executing MIME-parameter type are never promoted to
  code - and `nomodule`, whose body never ran), pass the same network-import check the loader strip
  applies to every other surviving script, and carry no byte sequence that would open a script-data
  escape. An adjacent MIT notice naming the same library is required as a licensing condition, so
  the library and its notice always travel together. A document that has neither a payload nor a
  qualifying inlined copy still fails loudly.
## [1.273.0] - 2026-07-29

### Fixed

- The live chart renderer, the comment layer, and the Offline export no longer disagree about
  what a chart is. A bare data-bearing canvas (`data-cmh-chart-points` or
  `data-cmh-chart-source` with no `cmh-chart` class and no `figure.chart` wrapper) drew nothing
  at load - only a window resize revived it - was not commentable, and was invisible to the
  Offline export, so a document that attached its own Chart.js to such a canvas exported without
  the library and showed an empty canvas. It now draws at load, is commentable like any other
  chart canvas, and the export recognises it, so the evidence-based Chart.js decision applies to
  it too: the library travels only when the document actually needs it.

### Changed

- The chart and diagram selectors are declared ONCE, in a new `assets/js/03-selectors.js`
  module, and the renderer, the image comment layer, the mermaid layer, the Offline exporter,
  and the author-time rich-libraries payload detector all derive from it, so the lists can no
  longer drift. The detector's former deliberate superset (any `data-cmh-chart*` attribute) is
  now exact parity with the runtime.

## [1.271.0] - 2026-07-29

### Fixed

- The validator no longer classifies a document as NonPortable because its own authored CONTENT
  demonstrates the companion markup. It decided the mode by looking for a
  `<link href="commentable-html.css">` / `<script src="commentable-html.js">` ANYWHERE in the
  file, so a genuinely self-contained Portable document about commentable-html - one that quotes
  the legacy loading markup in prose, which `to_portable.py` now deliberately preserves when it
  migrates such a file - failed validation with `commentableHtmlLayer.mode must be "nonportable"`,
  no runtime script found, a missing `#cmhAssetBanner`, and a companion file that does not exist.
  The mode determination and every check that follows from it now read the LAYER's own markup:
  the authored region is excluded, because the layer's references always sit outside it (the
  stylesheet in `<head>` before it, the runtime scripts at the end of `<body>` after it). The
  region comes from the PARSE, not from marker offsets in the text, so it is exactly the region a
  browser would agree on - real comment markers, inside the live `#commentRoot`, outside an inert
  `<template>`, never inside CDATA - and a misplaced marker or a `<style>` straddling one cannot
  steer the validator into ignoring the real layer instead. It holds in the other direction too:
  an authored demonstration can never STAND IN for a real reference, so a NonPortable document
  whose bootstrap banner, watchdog, version meta, or companion reference exists only inside its
  prose still reports the same error it always did, and a real NonPortable document is classified
  and checked exactly as before. Because the layer view is only as trustworthy as the region it is
  derived from, the validator also errors when the CONTENT markers are present in the text exactly
  once each and in order but the document does not parse with a well-formed region - a marker
  swallowed by a `<script>`/`<style>` body or an inert `<template>`, a marker outside
  `#commentRoot`, or unbalanced markup closing `#commentRoot` mid-region - instead of guessing
  which side of the broken boundary the markup after it belongs to.

## [1.270.0] - 2026-07-29

### Fixed

- `tools/blocks/chart_block.py` no longer prints chart fragments it could not check. The tool's one
  promise is that what it emits validates, and it self-validates before printing - but when the
  sibling `validate` module could not be imported (a broken or partial install) the self-check
  returned "unknown", which the CLI read as success and printed the fragments anyway. So the single
  protection disappeared exactly on the installs where something was already wrong. It now fails
  closed for every "could not check" shape - an unimportable validator, a partial install where
  `validate.py` is present but one of its own dependencies is not, a truncated `validate.py` that
  raises on import, a `validate` module resolved from outside the skill's own tools directory
  (refused before its module body runs), a missing or corrupt validation template, a validator that
  crashes, and a validator that answers in an unexpected shape - writing nothing and naming the
  actual cause. A caller who knowingly wants unchecked output passes the new
  `--allow-unvalidated-output`, which emits the fragments with a warning on stderr; it never
  suppresses a real validation failure, and the CMH-VAL-18 advisory split still applies.

## [1.269.0] - 2026-07-29

### Fixed

- The author-time syntax-highlighting guardrail is no longer blind in a Portable document. The
  check scanned the whole file for `<pre>` blocks, so in a Portable document - which inlines the
  layer CSS and JS, both full of prose mentioning `<pre>` and `<code>` - a match starting inside
  one of those bodies swallowed the author's real code block and the check reported nothing at
  all. A raw `language-XXX` block therefore shipped unhighlighted with no warning, and
  `retrofit.py --no-highlight` exited 0 instead of failing closed. Blocks are now LOCATED in a
  masked view of the document (`<script>`/`<style>` bodies and HTML comments blanked to
  same-length spaces) and every payload is read from the original bytes, so the language,
  emptiness and highlight state are still decided on what actually ships. The mask is one
  left-to-right pass over an alternation, so a `<script` named inside a comment cannot open a
  mask that runs to the document's next real `</script>` - the same one-pass masking now backs
  the KQL runnable scan, which had that hole too.

### Changed

- Validator warnings now have one shared fatal/advisory split (`validate.ADVISORY_PREFIXES`,
  `is_advisory()`, `partition_warnings()`), honoured by `retrofit.py`, `content_replace.py`,
  `chart_block.py` and the `--strict` and stamping paths of `finalize.py`, `upgrade.py` and
  `validate.py`. An advisory names something the author cannot clear, so it is always reported
  but never blocks a fail-closed tool and never withholds the `commentable-html-validated` stamp.
  Today the set holds exactly one prefix: a code block carrying deliberately hand-written INERT
  markup, which the authoring tools pass through verbatim by design - without this, the scan fix
  above would have made such a document impossible to write back or stamp. Markup that is not
  inert stays FATAL: inertness is decided by a whole-tag allowlist (every `<` must open a
  well-formed inline formatting tag carrying at most a quoted `class`), so a raw `<script>`, an
  `<iframe>`, any `style`/`is`/`data-*`/event attribute, an unquoted attribute, or a stray `<`
  keeps blocking - a `<pre>` body is parsed as markup and that content executes. Text between
  the tags is escaped source and is never inspected, so a code sample that merely mentions
  `onclick=` or `javascript:` is not flagged. The check also fails CLOSED when a raw `<script>`
  or `<!--` opened inside a code block swallows its `</code></pre>`: it reports the unpaired
  `<pre>` rather than silently inspecting nothing. The theme-contrast advisory is deliberately
  not in the advisory set - its near-miss band ships a concrete `--suggest` fix, so it is
  clearable and still fails `--strict`; `retrofit.py` keeps its own long-standing carve-out for
  it, and now fails closed (every warning fatal) if the validator cannot be imported.
  `upgrade.py --strict` likewise aborts instead of committing when the validator is unavailable,
  and `deck_validate.py --strict` - the command the skill tells deck authors to finish with -
  shares the same contract, so an advisory-only deck no longer exits 1.

## [1.268.0] - 2026-07-29

### Fixed

- An Offline export no longer inlines Chart.js for a document that never calls it. The exporter
  decided by SHAPE - any `figure.chart canvas` or `canvas.cmh-chart` - but a canvas carrying
  `data-cmh-chart-points` / `data-cmh-chart-source` is drawn by the runtime's own 2D renderer and
  never touches Chart.js, so a report whose charts are all built-in shipped roughly a megabyte of
  dead library in every offline file (and, with no diagram either, the vendored payload with it).
  The decision is now made on EVIDENCE: the library travels only when the document has a chart
  canvas the built-in renderer will not draw, or a surviving script that mentions the `Chart`
  global. The superset selector stays load-bearing - an author who attaches their own Chart.js to
  any canvas, including one that also carries the built-in attributes, still gets the library
  inlined, and the evidence match is deliberately loose (it covers indirect construction such as
  `const C = window.Chart; new C(...)` and every executable script MIME type) because a false
  positive only costs bytes while a false negative would ship a chart that never renders.
- An offline re-export can no longer accumulate a second copy of an inlined library. The libraries
  the exporter injects now carry a marker it removes them by, instead of being recognized by their
  own bundled text. A script that merely names a bundle file (in a comment, say) but uses the
  `Chart` global is also no longer removed as if it were a loader shim, and a chart script placed in
  the document head is moved below the inlined library so it cannot run before it.

## [1.265.0] - 2026-07-28

### Added

- `tools/authoring/to_portable.py` migrates an existing NonPortable document into a
  self-contained Portable one, preserving its authored content, its embedded comments, and its
  handled ids - the point of migrating rather than regenerating is that review state travels
  with the document. It is the counterpart to `upgrade.py`, which deliberately refuses a
  NonPortable file. Running it twice is a no-op, and a file that is not a commentable-html
  document is refused rather than rewritten.

### Changed

- Portable is now the ONLY mode generated, by every creation route. `new_document.py` follows the
  resolved TEMPLATE rather than a flag, so the two can never disagree: the default is
  `dist/PORTABLE.html`, and a caller that genuinely needs a legacy NonPortable document asks for
  it explicitly with `--template <dist>/NONPORTABLE.html`, which still gets the full
  companion-reference handling. `retrofit.py` also produces a Portable document by default; a
  legacy one now requires an explicit `--nonportable` or one of the companion-href options.
  `--nonportable` on `new_document.py` is accepted but ignored, and `--portable` on either tool
  now simply names the default, so existing callers keep working.
- NonPortable documents are opened, validated and finalized PERMANENTLY, with no deprecation
  deadline. The NonPortable runtime and its companions (`NONPORTABLE.html`,
  `commentable-html.{css,js,assets.js}`) stay shipped for exactly that reason: existing
  documents reference them by bare name and would break on the next auto-update if they were
  dropped. Only CREATING a new NonPortable document by default has gone away.

### Security

- `to_portable.py` neutralizes any raw-text terminator in the companion bytes it inlines, so a
  stylesheet supplied through `--dist` can no longer close its `<style>` element and have the
  rest parse as live markup - control of a stylesheet used to escalate to arbitrary script
  execution in a document holding authored content and reviewer comments. The payload is
  escaped, never silently dropped.
- The migration writes through a staged temp file swapped in with `os.replace` (the crash-safe
  helper `content_replace.py` already used, now shared as `_atomic_io.py`). The destination used
  to be truncated before the replacement bytes existed, so an interrupted or failing write
  destroyed the document being migrated - reproduced as a 1.4 MB file reduced to zero bytes.
- The CONTENT region that decides which companion reference is the real one is now located from
  line-anchored HTML-comment markers and required to be unique, so reviewer text quoting the
  marker can no longer invert the region and send the stylesheet into the author's markup; an
  ambiguous document is refused rather than guessed at. The mode transition parses the layer
  descriptor as JSON and requires exactly one nonportable-to-portable transition, so a
  reformatted descriptor can no longer be reported as migrated while still marked nonportable.
- Every anchor is resolved against the document's original bytes and applied in one pass of
  non-overlapping edits, and elements are matched in a view with HTML comments and raw-text
  bodies blanked. Untrusted companion text can no longer aim a later step, and a commented-out
  or quoted copy of a companion reference or of the layer descriptor is never the one rewritten.
  A companion is matched by the BASENAME of the URL its element points at, so the absolute
  `file://` references the CLI produced by default, the `--assets-relative` / `--copy-assets` /
  `--assets-href` prefixes and `?v=` cache-busters all migrate rather than being refused; CRLF
  documents migrate too. Migration finally refuses to write a result that would still reference
  a companion, so it can never report success on a document that is not self-contained.

## [1.264.0] - 2026-07-28

### Fixed

- A wide table no longer breaks words mid-token. Table cells used `overflow-wrap: anywhere`,
  which participates in intrinsic (min-content) sizing, so every cell reported a min-content
  width of roughly one character and the table layout algorithm collapsed a column to that and
  shredded its text even while other columns still had spare room - a 14-column table rendered
  `NAMESPACE MOVE` as `NAMES` / `PACE` / `MOVE`. Cells now use `overflow-wrap: break-word`,
  which breaks identically once a line is being laid out but is ignored for min-content, so a
  cell keeps its longest-word width and is only broken when there is genuinely nowhere left to
  go.
- A table that is genuinely too wide for the page now scrolls horizontally inside its own box
  instead of pushing the whole document sideways. This is the other half of the fix above:
  `break-word` is ignored for min-content sizing, which is exactly what stops a column being
  shredded, but it also means a table whose columns cannot fit reports a min-content width
  larger than its container and escapes it. Every table is therefore rendered inside a
  `.cmh-table-scroll` box - the containment narrow screens already had, now at every width. The
  wrapper is a real element rather than `display: block; overflow-x: auto` on the table itself,
  because `display: block` wraps the rows in an anonymous table box that shrink-to-fits and
  collapsed a narrow table's columns to their content width (a 2-column table measured 99px
  instead of 400px) - which also means narrow screens no longer suffer that collapse. A wrapper
  that actually scrolls is keyboard-focusable and labelled, so it can be scrolled without a
  mouse, while a table that fits adds no tab stop. A table built at runtime by an author script
  is contained too, and a table inside a flex or grid parent keeps its width and its placement.
  A focused scroll box owns the arrow keys in a deck, so its clipped columns stay reachable by
  keyboard instead of the arrows changing slides. Printing is unaffected: the wrapper reverts to
  `overflow: visible` so a wide table is never clipped out of a PDF.

## [1.262.0] - 2026-07-28

### Changed

- A document now carries the vendored rich-libraries payload (the gzip+base64 mermaid and
  Chart.js bundle the Offline export inlines) only when its content actually uses a diagram or a
  chart, and never in the document head. It used to be stamped into every document
  unconditionally: measured on the shipped examples it is 1,363 KB, 55 to 61 percent of a 2.3 MB
  file, and it sat on line 7 - so a prose-and-code review document paid for a renderer it could
  never call, and any tool that reads the head of a file hit a megabyte-long line immediately. A
  prose report now goes from 2,301 KB to 938 KB (59 percent smaller) and its longest line from
  1,396,078 characters to 631.
- The decision is re-evaluated on every finalize rather than made once when the document is
  created, so a document that GAINS a diagram after the payload was dropped gets it back and its
  Offline export keeps working. A document whose content region cannot be located is left alone
  entirely - never stripped, and never grown.

## [1.261.0] - 2026-07-27

### Changed

- `finalize` now reads the document once, threads it through the phase transforms in memory, and
  writes once. Each phase previously re-read and re-wrote the whole file, so a 1.4 - 2.5 MB document
  paid a read/write pair plus an independent full-document parse per phase - and because
  `content_replace` finalizes on every write-back, the agent edit loop paid that on every iteration.
  The phase order and every transform are unchanged, so the output is byte-identical. The per-phase
  entry points are REMOVED rather than kept: nothing called them once the pipeline threaded the
  document in memory, and leaving them would let a caller silently reintroduce the per-phase I/O
  this removes.
- Validation and the validated provenance stamp now work on that same in-memory document, so a
  clean `finalize --strict` run costs one read and one write end to end, instead of re-reading the
  file to validate it and then re-reading and re-writing it to stamp it. `validate.validate()`
  takes an optional `html=` argument for callers that already hold the document.

### Fixed

- A quadratic scan in the KQL tokenizer. Deciding whether an identifier was a function call sliced
  the entire remaining query on every token, so cost grew with the square of the query length. It is
  now a bounded lookahead. A newline before the paren still does not make a call, so highlighted
  output is unchanged.

## [1.260.0] - 2026-07-27

### Fixed

- A diff labelled `config.xml`, `page.html` or `main.dart` now highlights. `_EXT_LANG` had no entry
  for those extensions, so extension inference resolved to no language and the diff rendered
  monochrome unless the author passed `data-diff-lang` explicitly - even though both highlighters
  fully support them. A guard test now fails when any supported language has an obvious extension the
  table does not map, so the next language cannot ship with the same hole (CMH-HL-13).
- The runtime `sql` family accepts double-quoted strings, matching its author-time config
  (`string_styles` is `sql_single` plus `double`). A double-quoted SQL identifier previously rendered
  as a string when baked and as plain text at runtime. The other dedicated families' string styles are
  now spot-checked against their configs by the same guard (CMH-HL-15).

### Changed

- Runtime keyword lookup is per LANGUAGE rather than one broad bucket shared by 23 languages. The
  `hash` and `c` families shared a single approximate set, which both over-colored (a lowercase
  `true` in Python, `true`/`false`/`null` in R, `bool` in Objective-C) and under-colored (Python's
  capitalized `True`/`False`/`None` never matched the case-sensitive lookup). Measured cost of
  splitting, on the built `commentable-html.js` rather than on the raw keyword text: 9,346 bytes
  (736,669 -> 746,015, about 1.27 percent), against a divergence visible in every Python block. Each
  set is compared to its author-time config by test, so a future drift fails there instead of shipping
  as a block that renders one way baked and another way live (CMH-HL-14).

## [1.259.0] - 2026-07-27

### Fixed

- Editing a KQL query no longer leaves its **Run in Azure Data Explorer** button executing the
  PRE-EDIT query. The query is encoded inside the link's href, so re-highlighting only the code
  left a stale payload behind - silently, since nothing validated it. `refresh_block()` now recovers
  the cluster and database from the existing link and rebuilds both the code and the href, preserving
  the figure frame, caption and cluster copy affordance; the agent edit loop applies it to every KQL
  figure it writes back (CMH-KQL-10).
- The validator classifies a code block through the shared strict scanner instead of probing for the
  `cmh-code-` substring, so a nested, malformed or hand-edited span is reported rather than silently
  accepted as highlighted (CMH-HL-12).

### Changed

- `language-kusto` / `language-kql` blocks are baked by the same document highlight pass as every
  other language rather than being skipped. Only the dispatch and the emission are shared - KQL keeps
  its own tokenizer and `cmh-kql-*` class vocabulary - so output bytes are unchanged, and the agent
  edit loop can now serve KQL blocks like any other code (CMH-KQL-09).

## [1.258.0] - 2026-07-27

### Added

- Content-scoped editing for the agent review loop. `tools/authoring/content_extract.py` prints ONLY
  the fragment between the CONTENT markers - the 0.1 to 1.3 percent of a document an agent actually
  edits - instead of making it read a 1.4 to 2.5 MB file, and hands back de-highlighted SOURCE so the
  agent never has to hand-maintain token spans. A code block the highlight inverse refuses
  (hand-written markup inside a `<pre><code>`) is passed through verbatim, so the loop never stalls on
  the very blocks it exists to repair (CMH-CONTENT-01).
- `tools/authoring/content_replace.py` writes a fragment back as ONE atomic transaction: check, swap,
  re-bake (typography, section cards, highlighting, an existing TOC), strict-validate, re-stamp the
  content-bound validated hash, and optionally mark Copy-all ids handled. Either every step succeeds
  or the original file is left byte-for-byte unchanged with no temporary file surviving - there is no
  half-finished state and no follow-up step to remember. A replacement that changes nothing does not
  touch the file at all (CMH-CONTENT-02).
- A content edit is LOCAL: a section the agent did not touch keeps a byte-identical hash, so its
  Mark-reviewed marker survives, while an edited section hashes differently (CMH-CONTENT-03).
- `tools/authoring/extract_comments.py` prints the embedded comment snapshot as JSON or fenced text
  for the peer-review path, where a returned Portable file carries comments nobody pasted. It reports
  what is baked into the file, never "all current comments" - a reviewer's newer edits can still sit
  in browser `localStorage`, which no command-line tool can read - and it wraps every reviewer note in
  an untrusted-note fence so a downstream agent treats it as data, not instructions (CMH-CONTENT-04).

## [1.257.0] - 2026-07-26

### Added

- Syntax highlighting is now reversible. A new shared highlight core exposes `dehighlight()`, which
  recovers the exact source a highlighted code block was built from, for every language including
  KQL. The inverse is a LEFT inverse over newline-normalized input, because both emitters fold CRLF
  and lone CR to LF; for content already stored highlighted, dehighlight followed by re-highlight is
  byte-identical, so an untouched block never churns bytes. Escaped entities, a literal `</span>`
  inside a string, multi-line tokens (docstrings, block comments, KQL verbatim strings), tabs and
  astral Unicode all survive the round trip (CMH-HL-09).
- The inverse is a strict single-pass scanner, so content the highlighters did not produce is
  REFUSED rather than corrupted: hand-written markup in a code block, a nested or malformed span,
  extra attributes, an unknown token kind, or non-canonical escaping the emitters never write
  (`&quot;`, `&#x3C;`, `&eacute;`, a bare `&`) all return `None` from `dehighlight()`, and
  `classify()` reports `raw` / `highlighted` / `hand-written` so callers can pass such a block
  through untouched. The exact-escaping rule also makes an accidental double application refuse
  instead of silently decoding source that legitimately contains `&amp;`. A repeated-substitution
  loop is deliberately not used - it would peel nested spans from the inside out and hand back
  plausible but corrupted source (CMH-HL-10).

### Changed

- The code highlighter and the KQL highlighter now share one emission point and one newline
  normalizer, so the reversibility guarantee covers every language instead of being reimplemented
  per tokenizer. The two tokenizers stay separate (their grammars genuinely differ) and both the
  `cmh-code-*` and `cmh-kql-*` class vocabularies are retained, so output bytes are unchanged and
  already-generated documents keep rendering exactly as before. Emitter output is now asserted flat,
  pinning the property the inverse depends on (CMH-HL-11).

## [1.256.0] - 2026-07-27

### Fixed

- The runtime tokenizer now gives every language family that has its own comment/string patterns its
  own KEYWORD set, mirroring the author-time list in `tools/blocks/highlight_code.py`. Those
  families used to fall back to one broad, general-purpose keyword set, which both under-colored and
  over-colored them: an unbaked `language-sql` block rendered `SELECT`, `INSERT`, `JOIN`, `GROUP`
  and `ORDER` as plain text (only the handful of words that happen to exist for other languages,
  like `FROM` and `WHERE`, were colored) while the same block baked at author time colored them all,
  and `css`, `batch`, `powershell`, `haskell` and `lua` had the same gap - `auto`/`inherit`,
  `echo`/`setlocal`, `param`/`begin`, `data`/`instance` and `local`/`end` were all plain. The shared
  set also tinted words the author-time tool never treats as keywords in those languages (`class` in
  Lua, `def` in Haskell). XML is now its own family instead of riding along with HTML, which used to
  color `<div>` and an uppercase `<ROOT>` in an XML block that the baked output leaves plain, and
  three stale words (`deriving`, `newtype`, `none`) left over from before Haskell and CSS had their
  own sets no longer mis-color identifiers in every other language. CSS now matches keywords
  case-insensitively at runtime too, as the author-time tool already did. The broad shared set is
  otherwise unchanged, so a SQL-only word like `insert` still stays a plain identifier in C, Python
  and everything else.

## [1.255.0] - 2026-07-26

### Fixed

- The authoring validator's single-pass script scanner now models REGEX LITERALS. A `/.../` literal
  containing a backtick, a single quote, or a double quote used to flip the scanner into a phantom
  string/template state that blanked the rest of the script, hiding real code from every check that
  reads it - a Markdown fence regex holding a backtick made the shipped showcase deck fail with
  "a `<canvas>` is present but no renderer was found" because the chart's `.getContext(` had been
  blanked. A `/` inside a `[...]` character class no longer ends the literal, escapes are honored,
  and division is told apart from a literal by the usual prev-significant-token heuristic (ambiguity
  and an unterminated literal both resolve to division, so the scanner never blanks live code). A
  `new Chart(` that appears only inside a regex is correctly not counted as executable init.
  (CMH-VAL-17)

### Changed

- The Markdown fence regex in the runtime highlighter spells its backtick literally again; the
  `\x60` workaround that the old scanner limitation forced is no longer needed.
### Added

- A fenced code block inside a Markdown block is now highlighted in its OWN language instead of being
  colored as one flat run: the first word of the fence info string selects the language (aliases
  resolved, so a `py` label and a `python title="x.py"` label both select Python), and an unknown or
  absent label keeps the previous opaque body. The body is highlighted as a whole, so a multi-line
  construct inside it (a block comment, a triple-quoted string) reads exactly as it would in a
  standalone block of that language. A `markdown`-labelled body re-reads as Markdown up to a small
  depth bound and stays opaque past it, so a hostile document cannot drive unbounded recursion.
  (CMH-HL-07, CMH-HL-08)
- The author-time highlighter now knows the common short labels `js`, `jsx`, `mjs`, `py`, `ts` and
  `tsx`. They were runtime-only, so a `js`-labelled block was highlighted by the runtime but baked as
  plain text - and, with nested fences, would have nested on one path and stayed flat on the other. A
  second drift guard now fails in that direction too, so the author-time and runtime label sets
  cannot diverge again. (CMH-HL-03)

## [1.254.0] - 2026-07-26

### Changed

- Editing a comment note now happens INLINE, where the reviewer already is, instead of jumping them
  somewhere else. The sidebar card's `edit` action opens an editor inside that card (exactly like a
  reply), so the document is no longer scrolled to the anchor and no floating composer opens.
  (CMH-THREAD-10)
- `Edit` in the inline comment dialog (opened from the orange "Open comment" hover bubble) turns that
  dialog into an editor in place, so the note is edited right where the reader clicked. While it is
  being edited the dialog stays open (an outside click or the anchor scrolling away no longer discards
  the draft), Escape cancels back to the note view, and a second Escape closes it. (CMH-CORE-16)
- The orange "Open comment" hover bubble is bigger (28px with a 16px glyph), so it is an easier click
  target. (CMH-UI-12)

### Fixed

- Clicking inside an inline reply or note editor no longer also fires the comment card's
  jump-to-anchor, which scrolled the document away mid-edit. (CMH-THREAD-10)
- A comment is now editable in exactly one place at a time: opening a second editor for a note that
  already has an unsaved draft elsewhere (the panel card, the in-document dialog, another highlight's
  dialog, or the floating composer reached by re-selecting the text) hands the reader back to the
  draft instead of duplicating it - previously two editors could exist and the last save silently
  overwrote the other. (CMH-CORE-16)

## [1.253.0] - 2026-07-26

### Added

- A fenced code block inside a Markdown block is now highlighted in its OWN language instead of being
  colored as one flat run: the first word of the fence info string selects the language (aliases
  resolved, so a `py` label and a `python title="x.py"` label both select Python), and an unknown or
  absent label keeps the previous opaque body. The body is highlighted as a whole, so a multi-line
  construct inside it (a block comment, a triple-quoted string) reads exactly as it would in a
  standalone block of that language. A `markdown`-labelled body re-reads as Markdown up to a small
  depth bound and stays opaque past it, so a hostile document cannot drive unbounded recursion.
  (CMH-HL-07, CMH-HL-08)
- The author-time highlighter now knows the common short labels `js`, `jsx`, `mjs`, `py`, `ts` and
  `tsx`. They were runtime-only, so a `js`-labelled block was highlighted by the runtime but baked as
  plain text - and, with nested fences, would have nested on one path and stayed flat on the other. A
  second drift guard now fails in that direction too, so the author-time and runtime label sets
  cannot diverge again. (CMH-HL-03)

## [1.252.0] - 2026-07-26

### Fixed

- The floating `Add Comment` popup no longer jumps to the bottom-right of the following block. A
  whole-line or whole-paragraph selection (a double-click on the trailing word, a triple-click, or a
  drag past the end of the block) is normalized by the browser past the end of that block, so the raw
  range's last client rect covered the ENTIRE next element - a chart figure, an image, a table - and
  the popup landed hundreds of pixels below the selected words. The popup now anchors to the last
  RENDERED character the selection covers, measured rather than guessed from the character class, so
  a preformatted space, a non-breaking space and a narrow no-break space all still anchor it while
  collapsed and zero-width characters do not. It works on both the desktop `mouseup` path and the
  coarse-pointer `selectionchange` (touch) path, and stays clamped to the viewport. (CMH-SEL-03)

## [1.249.0] - 2026-07-26

### Added

- Markdown is now a supported syntax-highlighting language (`markdown`, aliases `md`, `mdown`, `mkd`).
  Markdown carries no keywords, so it gets a dedicated line-oriented tokenizer that reuses the six
  shipped token classes: headings, setext underlines, bold and a fence info string read as keywords;
  emphasis, strikethrough and HTML comments read as comments; inline code spans, fenced-code bodies,
  autolinks and link destinations read as strings; link text, reference labels and footnote references
  read as function names; ordered-list digits read as numbers; and fence delimiters, blockquote markers,
  list bullets, task checkboxes, thematic breaks, table pipes, link brackets and inline HTML tags read
  as punctuation. An intraword underscore (`some_long_name`) never starts emphasis, a backslash-escaped
  marker stays literal, an unterminated marker is left plain, and a fenced body is opaque. (CMH-HL-07)
- The runtime mirrors the same Markdown tokenizer, so an unbaked `language-markdown` block self-heals
  on load and a `.md` / `.markdown` / `.mkd` file in a unified diff is highlighted from its filename.
  (CMH-HL-08)
- The showcase demo report ships a highlighted Markdown block (the volunteer handbook page), and the
  showcase deck's supported-syntax slide lists Markdown. (CMH-DEMO-07)

## [1.248.0] - 2026-07-26

### Fixed

- The floating per-link `Add Comment` button that appears when hovering a commentable link now wears
  the shared crimson accent pill (background, label color, rounded shape, shadow, hover and active
  states) like every other add-comment affordance. `.cm-link-add` had been left out of the shared pill
  rule, so the link button rendered as a plain default browser button. (CMH-UI-04)

## [1.247.0] - 2026-07-26

### Fixed

- A `jsonc` code block is highlighted instead of rendering as plain monochrome text. `jsonc` was not a
  known label on either path - it was missing from the author-time highlighter's alias table and from
  the runtime tokenizer's language map - so a `language-jsonc` block was baked as escaped plain text and
  the runtime fallback declined to touch it. It is now a first-class label that resolves to `json`.
  (CMH-HL-05)
- A `/* ... */` block comment in a JSON/JSONC block is highlighted as a comment. The author-time `json`
  config declared only `//` line comments, so a block comment was tokenized as operators plus plain text
  - and silently disagreed with the runtime, which did treat it as a comment. (CMH-HL-05)
- A comment that directly abuts an operator, with no whitespace between them, is highlighted as a
  comment. The author-time tokenizer's greedy operator run absorbed the comment's opener (`{/*` became
  one operator token), so the comment BODY was then highlighted as live code - which the new JSON block
  comments made visible as `{/* "a": 1 */}` colouring `"a"` as a property key. The operator run is now
  guarded per language by that language's own comment prefixes, so `x=1;/*c*/`, `int x=1;//n`,
  `f x={-c-}`, `$a=1<#c#>` and `x=1--c` all highlight correctly while an operator pair that is not a
  comment in that language (Python floor division `//`) is untouched. (CMH-HL-06)

### Added

- JSON property keys are tinted apart from string values. A double-quoted string whose next
  non-whitespace character is `:` now emits a `cmh-code-key` token instead of `cmh-code-str`, so a JSON
  document reads the way every mainstream JSON highlighter renders it rather than as one wall of green
  strings. The token ships colors for the light theme, the dark theme, deck mode, and the dark-theme
  print re-light, and it is JSON-only - no other language gains a key token. (CMH-HL-05)

### Changed

- The runtime/author-time highlighter drift guard now also requires the runtime to know every author-time
  ALIAS, not just every canonical language. `diffLangKnown()` looks the raw `language-XXX` label up with
  no alias resolution, so an alias-only language was highlightable at author time and monochrome at
  runtime - the exact hole that let `jsonc` ship unhighlighted. (CMH-HL-03)

## [1.246.0] - 2026-07-25

### Fixed

- The shipped example reports and the showcase deck now report the build's release date on the sidebar
  "Generated on" line, stamped by `build.py` from the current version's dated `CHANGELOG.md` heading.
  Previously the date was an authored in-story value that was wrong and out of sync across examples (the
  NYC Taxi report showed `Dec 31, 2014`, the deck showed `Jul 14, 2026`, some reports showed no date at
  all); every example now shows the same, correct build date. (CMH-BUILD-15)
- The sidebar "Generated on" line now renders a date-only value (`YYYY-MM-DD`) as a calendar date in the
  viewer's local time with no time-of-day, so it shows the same day in every timezone. Previously a bare
  date was parsed as UTC midnight and shifted to the previous evening for viewers west of UTC (the
  spurious "..., 02:00" / previous-day display), which would have undercut the release-date stamp above.
  (CMH-SIDE-03)

### Changed

- The sidebar now draws a divider rule above the "Generated on" / "Last comment" metadata block,
  separating it from the Copy all / Export button row and mirroring the header's own rule under the
  "Commenting as" identity line. (CMH-SIDE-03)

## [1.245.0] - 2026-07-25

### Changed

- Deck showcase: the "Act 1 - The loop" slide now illustrates the generate -> review -> comment ->
  copy-all/paste/Enter cycle as a top-down Mermaid diagram that fans out and loops back, so it fills
  the 16:9 stage (full height and width) instead of rendering as one thin, wide band that wasted the
  top and bottom of the slide and clipped its right-most node. (CMH-DECK-41)
- Deck layout: every deck the skill produces now keeps a stable header baseline - the deck CSS reserves
  a consistent title band (em-sized) so a slide's subtitle/body starts at the same height regardless of
  whether the title is one or two lines, and content slides top-align so the title starts at the same
  height on every slide; the header no longer jumps when navigating. Showcase content slides pin that
  header at the top and center the body in the space below it, so a light slide no longer leaves a large
  empty band at the bottom. Section/divider slides still center. (CMH-DECK-42, CMH-DECK-SHOWCASE-12)

## [1.244.0] - 2026-07-25

### Changed

- The identity edit-mode `Save` button is now the crimson primary (matching `Copy all`) and `Cancel`
  a themed secondary button, instead of the browser's default button chrome.
- Moved the `Export` control into the prominent primary row beside `Copy all` and moved `Search` into
  the compact action ribbon, since Export is the more important action. The More menu now anchors to
  its own toggle so it stays clear of the Export button.
- The comment search field is now hidden by default and appears only when the reader opens it with the
  `Search` button (previously it appeared automatically whenever comments existed).

## [1.243.0] - 2026-07-25

### Fixed

- Print / Save-as-PDF single continuous page is now generic across ALL print destinations, not just
  Chromium's native "Save as PDF". Previously it forced the body to the on-screen reading-column width
  (~1280px on a wide screen) and sized a giant custom `@page` to match. Chromium's native vector
  "Save as PDF" honors that custom page, but a driver that ignores it (Microsoft Print to PDF, physical
  printers, browsers without custom-`@page` support) paginated onto standard paper while the body
  stayed forced to ~1280px, so it downscaled to fit (poor quality), left wide side whitespace, and
  stranded tall diagrams. The single page is now sized to a portable standard page (US Letter, 816px)
  and, crucially, the print CSS uses `width: auto` with the inset provided by the `@page` margin
  instead of a forced body width: a browser that honors the custom `@page` fills it as one tall page,
  while any driver that ignores it reflows the content into its OWN real Letter/A4 printable area and
  paginates normally, never downscaled. The height is measured at the exact content width the page
  renders at, so it is accurate (fixing a box-model skew and a double-counted page margin that had
  bloated the page and, on a multi-diagram document, spilled a near-blank overflow page). A document
  with genuinely wide content (a wide table) still grows the page so nothing is clipped.

## [1.242.0] - 2026-07-25

### Changed

- Replaced the two sidebar Sort arrows with a single `Sort` button that cycles document order ->
  newest first -> oldest first -> document order; its icon and tooltip reflect the current state and
  what the next click does.
- Reworded the export "Retain authoring session provenance" checkbox to "Keep AI session id in
  exports" and added a tooltip explaining it (exports strip the AI session/agent id by default).
- Restyled the Export and More dropdown menus as clean, content-width menu items (matching the
  collapsed toolbar menu) instead of full-ribbon-width bordered buttons.
- The author pill now aligns to the note's text bottom so there is no whitespace gap beneath it, and
  the three metadata lines (Generated, Last comment, Commenting as) are evenly spaced.

### Added

- Each export action now shows a centered toast naming which export is running.

## [1.241.0] - 2026-07-25

### Fixed

- Deck: a comments-off (present-only) deck no longer silently re-enables commenting when a review
  NOTE is edited, a CHECKLIST item is toggled, or a widget layout changes. While in the comments-off
  mode a deck no longer auto-opens the sidebar on such a non-comment change (it still does in a
  non-deck document, and in a comments-enabled deck it surfaces the change card); the change is still
  tracked. The deck comment-model observer was also hardened so that neither slide movement nor an
  incidental sidebar open from a non-comment change re-enables commenting - such an incidental open is
  reverted rather than flipping `off` to `open`. Two things still leave `off`: an explicit
  comment-options re-selection, and a real comment actually landing while off (a composer left open
  when off was chosen, then saved) - because `off` is only valid at zero comments, that comment exits
  to `open` so it is not stranded. (CMH-DECK-25, issue #659)

## [1.240.0] - 2026-07-25

### Changed

- Showcase deck polish. Link pills (`.show-link-pill`) keep their rounded pill shape on hover in deck
  comment mode - the authored deck CSS overrides the runtime link-comment hover so the dashed outline
  hugs the pill instead of squaring it (deck-wide, e.g. "View Live Demo" and the install/link pills).
  The primary "View Live Demo" label gains a subtle text-shadow for legibility on the crimson accent,
  and the four slide-9 feature cards lift on hover (translateY + shadow), matching the pill lift.
- Rebalanced the code / notes / decide slides so each uses its space: the "Supported syntax labels"
  card moved onto the "Code, KQL, and diffs" slide, the review checklist moved beside the notes demo,
  and the decision-board slide gained a short widget caption. (CMH-DECK-SHOWCASE-08, CMH-DECK-SHOWCASE-19)

## [1.238.0] - 2026-07-25

### Added

- The showcase deck (`examples/deck-showcase.html`) now demonstrates the full set of user-facing
  areas: a new "Discuss, find, and keep it tidy" slide covers threaded inline replies and colored
  author pills, rich-text comment formatting, per-section review badges plus the section menu and
  search/filter, and the storage manager plus commentable widgets - each framed as a live "Try it"
  invitation, since the deck runs the real runtime. This closes the gap between the deck and the
  documented feature set. (CMH-DECK-SHOWCASE-18)

### Changed

- Governance: the doc-surface registry in `dev/SPEC.md` now tracks a required `Deck` dimension
  alongside the reader-doc surface. Every new user-facing feature must declare that it is demonstrated
  on a showcase-deck slide (`deck`) or record an explicit `opt-out: <reason>`, checked by
  `scripts/check_doc_surfaces.py` (run in the required validate job and the pre-push hook) and encoded
  in AGENTS.md, so the deck stays a fourth documentation surface that cannot silently fall behind.

## [1.237.0] - 2026-07-25

### Changed

- Document links now ALWAYS open in a new tab: the runtime overrides an author-set `target`
  (`_self`/`_top`/a named frame) on a `#commentRoot` document reference (`http`/`https`/`file`) to
  `target="_blank"`, so opening a reference never navigates the reviewer away from the report and
  their comments (CMH-LINK-01). Non-document schemes (`mailto:`/`tel:`/`javascript:`/`data:`),
  same-page `#` fragments, and `.cm-skip` chrome stay excluded.

### Added

- Validator: a warning when an author `<a href>` document reference inside `#commentRoot` sets an
  explicit `target` other than `_blank` (it would open in the same tab), so a same-tab link is
  caught before handoff (CMH-LINK-05).

## [1.236.0] - 2026-07-25

### Changed

- Updated the in-runtime Help/About panel and the guided tutorial (`docs/TUTORIAL.md`) to describe the
  redesigned composite header: the captioned action ribbon (Export, Sort, More, Help, Hide), the
  Copy all / Search split, and the More menu that now holds Manage storage and Clear all comments
  (previously described as living in the Export menu).
- Regenerated every tutorial screenshot that shows the comments panel so it reflects the new header;
  the full-page shots (Copy all, dark theme, saved comment, thread, and others) had lagged behind
  because a whole-page screenshot dilutes the header-region change below the screenshot-check tolerance.

## [1.235.0] - 2026-07-24

### Changed

- Redesigned the comment panel header into a composite layout: a top row with the title, count, and
  the portability badge + version; a captioned action ribbon (Export, Sort, More, Help, Hide); a
  half-and-half Copy / Search row where the Search button reveals and focuses the filter field; and
  stacked Generated / Last comment / identity metadata rows.
- Moved Manage storage and Clear all comments into a new sidebar More menu (kebab); the Export menu
  now holds only the five file formats.

## [1.234.0] - 2026-07-24

### Added

- Rendered mermaid diagrams are now keyboard-commentable, mirroring the image keyboard path: focusing a
  diagram reveals the whole-diagram "Comment on diagram" button and Enter opens the whole-diagram
  composer, so a keyboard-only user never has to tab to the disjointed floating button. Every diagram
  gets exactly one comment tab stop - a standalone host, or the card inside a `.cmh-diagram-gallery`
  (fitting or overflowing, desktop or mobile). A bubbled Enter/Space from a descendant control (a
  `figcaption` link/button) keeps its native action, and on an overflowing gallery card Space and the
  arrow keys are left to native horizontal scrolling (WCAG 2.1.1). (CMH-MMD-11)

## [1.233.0] - 2026-07-24

### Added

- Help/About now documents recently shipped features: a new "Threads, replies and author names" topic
  (set your name via Commenting as, colored author pills, inline Word-style replies, and that Copy all
  and the exports keep each thread together), the storage manager's pie-chart breakdown and
  per-document Share table with per-comment browsing in "Managing storage", and a corrected count-bubble
  description that counts open comment threads plus unresolved note and checklist changes.
  (CMH-HELP-COUNT-01, CMH-HELP-THREADS-01, CMH-HELP-STORE-01)
- The guided tutorial now covers the Manage storage pie-chart breakdown and that the toolbar count
  badge counts note and checklist changes, so no user-facing feature is left off every doc surface.

### Changed

- New governance: every new user-facing feature must declare its documentation surface (tutorial, site,
  or help) - or record an explicit opt-out with a reason - in the SPEC "Doc-surface registry".
  `scripts/check_doc_surfaces.py` (run in the required validate job and the pre-push hook) fails a PR
  whose newly added feature ids lack a doc-surface entry.

## [1.232.0] - 2026-07-24

### Changed

- Comment replies are now composed and edited INLINE in the sidebar thread card (a Word-style
  experience) instead of in a floating popup. Clicking Reply opens an EMPTY editor inside the thread -
  it is never prepopulated with the text of the comment being replied to, and there is no "reply to:"
  quote header; the reply is simply appended to the thread. Editing an existing reply edits it in
  place, prefilled with that reply's own text. (CMH-THREAD-01, CMH-THREAD-05, CMH-THREAD-06,
  CMH-THREAD-07)
- The first reply made without a reviewer name set now reveals the identity editor so the reply can
  be attributed (a non-blocking prompt); the reply still saves unattributed if declined.
  (CMH-THREAD-08)

## [1.231.0] - 2026-07-24

### Changed

- The open-comment count badge (toolbar and sidebar) now includes pending note and checklist changes,
  not just comment threads. A reviewer who only edited an editable note or ticked a checklist item
  previously saw the count stay at 0, as if nothing had been captured; now each changed note (one per
  note) and each changed checklist (one per list) is counted, so the badge reflects that there is
  something to hand back. Widget/layout state changes remain a non-comment signal and are still not
  counted (CMH-STATE-01 unchanged). (CMH-NOTE-04, CMH-CHECK-06)

## [1.230.0] - 2026-07-24

### Changed

- The Manage storage dialog now shows storage consumption ONLY as a four-slice pie chart with a short
  bullet legend beside it, replacing both the previous prose usage summary and the "About X used
  across N documents" total line. The slices are This document,
  Other commentable-html documents (only other real documents), Other (all remaining same-origin data
  - non-commentable-html apps plus commentable-html's shared registry index and preferences), and
  Free (remaining headroom in the assumed ~5 MB budget); the four slices sum to the whole disc. Each
  legend bullet names its slice with a human-readable size and percentage (the accessible text
  alternative), and the pie SVG carries a brief role/aria-label plus a per-slice title as a non-color
  cue. (CMH-STORE-13)

## [1.228.0] - 2026-07-24

### Fixed

- Deck: a right-click on non-interactive slide text now reliably opens the deck comment menu again,
  even when it lands immediately after an empty-space advance click (CMH-DECK-31). The advance
  click's still-pending deferred mouseup selection cleanup could clobber the freshly opened menu, so
  the menu now cancels that pending cleanup when it opens. The menu stays suppressed on `cm-skip`
  deck chrome and on interactive targets. (CMH-DECK-40)

## [1.227.0] - 2026-07-24

### Changed

- Hardened the diagram-gallery legibility tests (CMH-CONTENT-19) to also cover HTML labels. Non-deck
  mermaid diagrams (flowchart, state, class, er) render their node labels as HTML in `<foreignObject>`,
  which the previous svg-`<text>` legibility checks did not measure - so a crushed or transparent HTML
  label would have looked empty in a real browser while every geometry and svg-text assertion stayed
  green. The demo test (`tests/53-more-examples.spec.js`) and the diverse-types hermetic test
  (`tests/76-diagram-gallery.spec.js`) now measure each `foreignObject` label's rendered height and
  paint visibility and assert a legibility floor, and the demo test asserts the demo genuinely includes
  HTML-label diagrams so the check is never vacuously skipped. Documented in `references/mermaid-diagrams.md`
  that an extreme-tall (very high aspect-ratio) diagram is scaled down by the fixed-height gallery and
  reads better as a standalone diagram outside it.

## [1.226.0] - 2026-07-24

### Changed

- The `.cmh-diagram-gallery` helper (CMH-CONTENT-19) now lays diagrams out as a centred FLEX-WRAP of
  UNIFORM-HEIGHT, content-HUGGING cards instead of a grid of uniform fixed-size cards. Every diagram is
  rendered at one fixed HEIGHT with its WIDTH derived from the mermaid viewBox aspect ratio (at natural,
  readable size, with no width clamp), and each card SHRINKS to hug that width up to a generous cap.
  This fixes the cases a fixed-card layout could not: a tall-narrow diagram (a vertical
  `stateDiagram-v2`) no longer slivers into a thin ribbon in an empty wide card - it gets a narrow
  full-height card - and every diagram now fills its card in BOTH dimensions at readable size (no
  letterbox). A diagram too wide for the card keeps its full height and SCROLLS horizontally inside its
  card rather than being crushed into an unreadable strip. Sizing is pure deterministic CSS anchored on
  a definite height, so it renders consistently (geometry-identical) across Chromium, Firefox, and
  WebKit and has no JS-measurement race; the layer's narrow/wide scale-up is disabled inside the
  gallery because it was measurement-timing dependent and rendered diagrams tiny in a real browser
  (while passing headless). A
  `<figure>` card is `width:fit-content` so it hugs its diagram for a short caption, and for a caption
  LONGER than a narrow diagram it grows only to a bounded readable width (`figcaption{max-width:22rem}`)
  with the caption wrapping there and the diagram CENTRED above it (`margin-inline:auto`) - so a long
  caption neither stretches the card to its full length (marooning the diagram in dead space) nor
  collapses to the tiny diagram width (towering into a many-line vertical strip). The caption is itself
  `margin-inline:auto` centred, so a short caption under a diagram wider than the 22rem cap sits centred
  rather than pinned to the card's start edge. When a wide diagram
  makes the figure its own horizontal scroll container, the caption is `position:sticky;
  inset-inline-start:0` so it stays PINNED in the visible card while the diagram scrolls beneath it
  (a static caption scrolled off-screen and stranded the reader without the label); the logical
  `inset-inline-start` pins the correct edge in both LTR and RTL. A diagram wider than the card cap scrolls horizontally with `align-items:flex-start`
  so its start edge stays reachable (a centered over-wide diagram is pushed to a negative
  offset the scroll range excludes, clipping its start), and an overflowing card is made
  keyboard-focusable (WCAG 2.1.1) with a visible focus ring. The gallery tests now assert each diagram FILLS its card in BOTH dimensions (a
  `Math.max`-based single-axis check could not catch a sliver), that no painted content is clipped or
  painted invisible, that text stays legible, that the card height stays at its design size (catching a
  uniform downscale), that an extreme-wide diagram scrolls at full height, that a wide figure's caption
  stays pinned in view (and never overlaps the diagram) while scrolling, and that a long caption wraps
  to a bounded readable width with no tower and the diagram centred - each mutation-verified
  to fail on a reverted/broken render. Documented in `references/mermaid-diagrams.md`.

## [1.225.0] - 2026-07-24

### Fixed

- Markdown export: a `<blockquote>` now recursively serializes its block children (paragraphs,
  lists, code fences, nested blockquotes) so every output line is prefixed with `> `, preserving
  the full GFM structure. Previously `_mdCollapse(_mdInlineText(el))` flattened all block children
  to a single line, losing the nested structure and changing the document's meaning. (CMH-MD-08)
## [1.224.0] - 2026-07-23

### Changed

- Markdown review-note exports now carry an untrusted-data preamble and non-forgeable dynamic fences,
  and strip bidi/invisible formatting controls from note text.
- Portable, Offline, and Plain HTML exports strip authoring session-id and agent provenance by default;
  an explicit retain option preserves it when deliberately requested.

## [1.223.0] - 2026-07-23

### Added

- Accessibility: the text-selection context menu is now a keyboard-operable ARIA menu. Its container
  carries `role="menu"` and each action carries `role="menuitem"` with a roving `tabindex="-1"` (only
  one item is focusable at a time, so Tab does not step through them); opening it moves focus to the
  first visible item, ArrowUp/ArrowDown (and Home/End) rove focus with wrap-around, Tabbing out
  dismisses it cleanly, and Escape closes it and restores focus to the control that was focused when it
  opened.
- Accessibility: the floating per-link add-comment button and the collapsible-section caret now show the
  shared themed `:focus-visible` outline ring, so keyboard focus on either control is clearly visible.
- Accessibility: a sortable table's header cell now reflects the active sort direction via `aria-sort`
  (`ascending` / `descending`) on the `<th>`, removed when the column resets or another column takes the
  sort, so assistive tech announces which column is sorted and how.

## [1.222.0] - 2026-07-23

### Fixed

- Comment search now Unicode-normalizes note text and queries and uses locale-aware casing, so
  canonically equivalent text and Turkish/Azeri dotted or dotless I case pairs match correctly.
  Localized card, popover, and board-summary timestamps isolate the date from any LTR suffix under
  RTL locales, and the inline image tool accepts safe paths whose canonical casing differs on
  case-insensitive filesystems.
  (CMH-SEARCH-06, CMH-SEARCH-07, CMH-SIDE-10, CMH-TOOL-21)

## [1.221.0] - 2026-07-23

### Changed

- Resource-safety hardening across the runtime and tools so large or attacker-controlled input can no
  longer exhaust memory/disk or freeze the tab (issue #619):
  - The session-hook zip extractor (`pkg/hooks/extract_resources.py`) now preflights
    `skill-resources.zip` against entry-count, per-entry size, total-size, and compression-ratio caps
    before writing anything, and streams each member under a per-entry actual-byte cap, so a tampered
    or decompression-bomb archive fails closed (previous version untouched, no marker).
  - The interactive chart derives its y-axis ticks by a bounded integer index (capped at
    `MAX_CHART_TICKS`), so a tiny/zero `data-cmh-chart-step` against a large max can no longer drive an
    unbounded synchronous loop.
  - Large code blocks are bounded like diffs: above `CMH_CODE_MAX_LINES` lines the per-line gutter is
    skipped, and above `CMH_CODE_MAX_CHARS` characters the runtime highlighter leaves the block plain
    (the text stays readable and commentable).
  - The deck `--pptx` local extractor lowers its archive caps, size-caps a single inlined image
    (`MAX_PPTX_IMAGE_BYTES`) and degrades an oversize image gracefully - dropping its extracted temp
    path (never emitting a dangling `assets/...` reference) and replacing it with a visible
    placeholder carrying the alt text so the fragment stays self-contained - and runs the vendored
    extractor subprocess under a hard wall-clock timeout (`PPTX_EXTRACT_TIMEOUT_SECONDS`) that fails
    closed.
  - Comment restore/backfill at startup reuse ONE `getTextNodes()` scan across per-comment
    `rangeFromOffsets()` lookups (rebuilding only after a DOM-mutating wrap) and cap context capture at
    `CMH_MAX_BACKFILL`, so a flood of finite-but-unresolvable comments no longer does
    O(comment_count x document_size) work.
## [1.220.0] - 2026-07-23

### Changed

- The Manage storage dialog is clearer and more capable (CMH-STORE-13..16). Documents are now shown
  in a column-headed table (Document, Comments, Size, Share, Actions) where the Share column is each
  document's percentage of commentable-html storage. A usage summary reports total local storage in
  use as a percentage of the assumed ~5 MB budget, the commentable-html share of the storage in use,
  and this document's percentage of commentable-html storage. Each document row has a lazy "Show
  comments" toggle that lists every stored comment (quote, note, author, and an approximate
  per-comment size), each deletable - deleting a comment in the current document routes through the
  live delete path (tombstoning embedded ids and re-rendering the sidebar), while deleting another
  document's comment rewrites only that document's stored slot. A Close button was added in a footer
  at the bottom of the dialog.

## [1.215.0] - 2026-07-23

### Added

- A shipped `.cmh-diagram-gallery` layout helper for showing several diagrams/figures of very
  different aspect ratios robustly (CMH-CONTENT-19). It is a plain CSS grid of uniform,
  height-bounded, framed cards: every card is the same height (no marooning of a short diagram
  beside a tall one), a diagram taller than its card scrolls inside it instead of being shrunk (no
  sliver), and there is no CSS multi-column (which is fragile with mermaid's dynamic sizing and
  produced tiny/empty diagrams in a real browser). Documented in `references/mermaid-diagrams.md`.

### Changed

- The visuals-matrix demo (`report-metrics.html`) Mermaid gallery now uses `.cmh-diagram-gallery`
  instead of a hand-rolled per-document grid/masonry, retiring the layout that failed repeatedly
  (marooning in #597, sliver/masonry in #602/#610). This is the durable, tested fix for the demo's
  gallery rendering (CMH-DEMO-06).

## [1.214.0] - 2026-07-22

### Added

- Flat (non-deck) documents now print / Save-as-PDF as a SINGLE continuous no-break page instead of
  paginating onto A4/Letter sheets, so no page break cuts through a section, table, chart, diagram,
  or code block. On print the runtime measures the full content height (proactively, under stable
  screen media, since Chromium locks the print `@page` size at `beforeprint`) and sizes a dynamic
  `@page` to the content, collapsing a multi-page report onto one tall page. Documents that contain a
  block-stacking container - a multi-column chart gallery or a grid/flex widget such as a kanban
  board - are left on normal pagination, because their print-time grid-to-block reflow and
  asynchronous chart resize cannot be measured before the page size is locked; their content still
  prints in full on standard pages. Decks are unchanged (one landscape 16:9 page per slide). Relies
  on the browser honoring a CSS `@page` size (Chromium's native print/PDF). (CMH-PRINT-06)

## [1.213.0] - 2026-07-22

### Changed

- Guarded sibling-tool imports in the shipped tools are never SILENT anymore. The #584 root cause was
  a deferred `import doc_stamp` swallowed by `except (OSError, ImportError): pass`, so a broken
  sibling import degraded a whole feature with no signal. Now every guarded import fallback across the
  tools (`new_document.py`, `deck_scaffold.py`, `retrofit.py`, `upgrade.py`, `deck_theme.py`,
  `deck_validate.py`, `chart_block.py`, `highlighting.py`, and `validate.py`'s `cmhval` and
  validated-stamp guards) emits a one-line stderr warning via a new `_toolpath.warn_missing_tool` (or
  unconditionally re-raises / recovers by re-importing), so a degraded run is visible. A guard test
  (`test_tool_imports.py`) additionally proves every guarded sibling import RESOLVES in the shipped
  layout (a missing/renamed sibling fails CI loudly) and structurally forbids any future silent
  import fallback - covering `except ImportError`, `ModuleNotFoundError`, and import-guarding broad /
  bare `except` handlers across the whole shipped tools tree. (CMH-TOOL-IMPORTS-01)

## [1.212.0] - 2026-07-22

### Fixed

- The runtime footer is now flush with the content column when the side table-of-contents
  navigation pane is present and the comments sidebar is closed. Previously, on viewports where the
  pane's left inset shrank the content shell below its max width, the footer spanned wider than the
  content column (about 1.5rem past it on each side). The footer now insets to match the content box
  in that layout.

## [1.211.0] - 2026-07-22

### Added

- Manage storage: a near-full-screen dialog (from the overflow / sidebar menu) that lists every
  commentable-html document's data stored in this browser, with a human-readable size and comment
  count, and lets you delete another document's data to reclaim space. On `file://` all documents
  share one browser storage budget, so this is how you free room when it fills up. The current
  document is marked and offers "Clear all comments" instead of Delete; deletion is scoped to
  commentable-html's own keys, so unrelated site data is never touched. (CMH-STORE-04, CMH-STORE-05,
  CMH-STORE-06, CMH-STORE-08)
- If saving a comment fails because storage is full, the Manage storage dialog now opens
  automatically; freeing space retries the save so the comment is not lost. Notes, checklists, and
  section-review saves that hit the same limit surface a "Manage storage" action on their warning
  toast, and closing the dialog while any save is still pending re-offers that recovery action so
  nothing is lost silently. (CMH-STORE-07)

### Changed

- Comments are now stored compressed (lz-string, packed into UTF-16) when that is smaller than plain
  JSON, so far more documents' reviews fit in the shared browser storage. The format is backward
  compatible: documents last saved by an older version still load and are migrated on the next save,
  and a stored value that cannot be read (a corrupt or newer-version format) is left untouched with a
  recovery notice rather than being overwritten. (CMH-STORE-01, CMH-STORE-02, CMH-STORE-03)

## [1.210.0] - 2026-07-22

### Added

- The runtime footer now ends with a "Report an issue" link, placed to the right of the
  "Help & about" control, that opens the plugin's GitHub issue form in a new tab. Like the rest of
  the footer it is `cm-skip` chrome, so it never leaks into a Plain HTML export.

### Changed

- On wide screens with the comments sidebar open, the document content column now targets a wider
  1600px column (up from 1300px), so the body fills more of the space between the navigation pane
  and the sidebar instead of leaving a large empty gutter. When the side table-of-contents
  navigation pane is present, the layout now subtracts that pane's width so the content still
  reaches its full width between the pane and the sidebar rather than being squeezed. The runtime
  footer tracks the same widened column so it stays flush with the content.

### Fixed

- The footer session-id copy control no longer renders two separator dots next to each other
  (`Generated . . [copy]`); the copy button and its separator now read `Generated . [copy] . Help`.

## [1.209.0] - 2026-07-22

### Fixed

- `validate.py` now actually stamps a document when run as a standalone CLI subprocess. It
  previously put only its own `validate/` directory on `sys.path`, so `_stamp_validated_file`'s
  `import doc_stamp` silently failed and a clean `python tools/validate/validate.py <file>` left the
  document unstamped - the runtime kept showing the amber "not validated" banner even though
  validation passed. `validate.py` now loads the sibling `authoring/` tools via the shared bootstrap,
  so both `validate.py` and `finalize.py` stamp on a strict-clean pass. (CMH-STAMP-02, part of #584)

### Added

- The validated stamp is now CONTENT-BOUND to the document's authored TEXT. On a strict-clean pass
  `validate.py`/`finalize.py` also write `commentable-html-validated-hash`, a whole content-root text
  hash computed with the shared section-hash contract, and the runtime reproduces it byte for byte
  (`window.__cmhReview.docHash()`). The amber "not validated" banner therefore returns after a
  post-validation edit to the visible authored text and clears again on re-validation, instead of
  relying only on timestamps - so "validated" now tracks the CURRENT text. It is a stable-text
  fingerprint (a strong nudge, not a cryptographic seal): it does not track attribute-only edits or
  edits inside the excluded rendered blocks (mermaid/diff/KQL/chart/notes). A document with no
  content root keeps a timestamp-only stamp and the runtime falls back to the timestamp signal, so it
  never false-positives; a reader's persisted table sort is canonicalized so it does not falsely
  invalidate. Only a FULL clean validation stamps (a `--charts-only`/`--layer-only` partial run never
  does). `finalize.py` also prints a guardrail reminder on a strict-fail that the fix must end with a
  clean strict pass to re-stamp. (CMH-STAMP-05, CMH-STAMP-03, CMH-STAMP-02, closes #584)

## [1.208.0] - 2026-07-22

### Added

- Review comment notes now support lightweight rich text (WhatsApp / Office style), rendered safely
  wherever a note is shown (sidebar card, inline popover, print appendix): `**bold**`, `*italic*`,
  `__underline__`, `~~strikethrough~~`, inline code, `- ` bullet lists, markdown-style links
  (http/https/mailto only), and bare `http(s)://` URLs auto-linked as clickable, new-tab, safe
  anchors. A single-pass tokenizer escapes all input first and only emits its own fixed tags, so a
  note can never inject markup; unsafe link schemes and hostile input are handled safely.
- The comment composer gained a formatting toolbar (bold, italic, underline, strikethrough, code,
  link, list) that wraps the current selection, plus keyboard shortcuts `Ctrl/Cmd+B` / `I` / `U`
  and `Ctrl/Cmd+K` (link). The stored note stays plain-text source, so Copy all still hands the
  agent the exact markers and old notes remain loadable without any migration. A new "Formatting
  your comment" Help topic and a tutorial section document the markers and shortcuts.

## [1.206.0] - 2026-07-22

### Fixed

- Printing a document or deck to PDF (Save as PDF / Ctrl+P) now renders correctly instead of
  clipping and stranding content. Decks print one landscape 16:9 page per slide (a named `@page`
  sized to the native slide, so a fixed-size slide is never cut off by a portrait page) with each
  slide keeping its authored grid/flex layout and no phantom trailing blank page. Reports no longer
  strand a section heading on a near-blank page: headings stay with their content, whole sections
  flow across pages, multi-column galleries and draggable widgets (kanban boards) block-stack so
  their items flow, and a tall mermaid diagram is scaled to fit one page instead of splitting a node
  across a page break. Chrome injected inside the document (sort controls, section-review badges, the
  widget reset control) is hidden in print. The paper size does not need to be A4/Letter - the goal
  is simply that nothing is clipped and every page carries content. (CMH-PRINT-01, CMH-PRINT-03,
  CMH-PRINT-04)
- A document printed while dark theme is active now prints on light paper: the color-scheme is reset
  to light (so the browser no longer paints the page canvas / margins dark) and syntax-highlighted
  code/KQL/diff tokens are re-lit to a legible palette on the white background. A deck instead keeps
  its own designed dark code backgrounds and bright tokens. (CMH-PRINT-05)
- Added real rendered-PDF CI checks (`tests/70-print-pdf.spec.js`, `CMH-PRINT-03`/`CMH-PRINT-04`/`CMH-PRINT-05`):
  they drive the browser's native print (`page.pdf`) and inspect the produced PDF - page count,
  page geometry, and per-page ink coverage - so a print-layout regression fails CI. The prior print
  tests only checked `@media print` computed styles and never paginated a real PDF.

## [1.204.0] - 2026-07-21

### Changed

- Consolidated the always-loaded `SKILL.md` capability, tool-routing, deterministic-helper, and pre-handoff guidance into one dense tool index while keeping critical triggers and tool routes covered by tests. Deep deck workflow guidance now lives in the on-demand deck references. (CMH-DOC-18)

## [1.203.0] - 2026-07-21

### Fixed

- Copy all now strips Unicode bidirectional formatting controls from reviewer notes, document text,
  the document label, and the document source before emitting the agent payload, so invisible
  direction overrides cannot visually span the trusted fences or metadata lines. Machine-readable
  JSON identifiers escape those controls so note/checklist apply tools still round-trip ids.
  (CMH-COPY-09)

## [1.202.0] - 2026-07-21

### Fixed

- Deleting an embedded comment now retries the tombstone write after saving the smaller comments
  array, so a near-quota browser can free space and persist the delete marker. If the retry still
  fails, the reviewer gets an assertive warning that the embedded comment may reappear after reload
  instead of a silent resurrection. (CMH-PERSIST-05)

## [1.201.0] - 2026-07-21

### Fixed

- Keyboard users can now tab from a focused heading to the floating heading Add Comment button, keep it visible while focused, and continue through the next valid heading controls or links without getting trapped on disabled, inert, or programmatic-only candidates. (CMH-A11Y-08)

## [1.200.0] - 2026-07-21

### Fixed

- Image comments now share one index-plus-src anchor resolver across reload restoration,
  jump-to-comment, edit-composer positioning, and section-review lookup, with image metadata
  disambiguation for duplicate-source images and labelled chart canvases, so a stale image index after
  a document reorders images no longer sends the scroll target or editor to the wrong image.
  (CMH-IMG-07)

## [1.199.1] - 2026-07-21

### Fixed

- Prevented sortable-table reloads from restoring discontiguous multi-row text highlights over unrelated rows while keeping the comment listed and recoverable.

## [1.199.0] - 2026-07-21

### Added

- Collaborative threaded comments with author attribution. A reviewer sets a display name once
  (stored per-browser in `localStorage`, seedable by the author via `data-cm-author`); the sidebar
  "Commenting as" control lets them change it at any time, applying to new comments only. Every
  attributed comment and reply shows a hashed-color author pill at the start of its note. A new
  Reply action threads comments: a thread is an initial comment plus a flat, chronological list of
  replies (single-level), each individually editable and deletable. Deleting a thread root removes
  the whole thread; deleting a reply removes only that reply. Copy all emits each thread as an
  initial comment followed by clearly-labelled refinements (author names neutralized so they cannot
  forge the untrusted-note fence or the machine trailer) and includes every reply id in
  HANDLED_IDS_JSON so a thread is handled and pruned together. Threads round-trip through Export as
  Portable / embedded comments, and orphan replies (missing root) are pruned at load. Markdown
  export and the print appendix are thread-aware. (CMH-AUTHOR-01, CMH-AUTHOR-02, CMH-AUTHOR-03,
  CMH-THREAD-01, CMH-THREAD-02, CMH-THREAD-03, CMH-THREAD-04, CMH-THREAD-05, CMH-THREAD-06)

## [1.198.0] - 2026-07-21

### Added

- A discoverable **Save as PDF** action makes the existing browser-native print/PDF layout reachable
  without knowing a keyboard shortcut. It appears in the toolbar overflow ("More actions") menu and
  in the sidebar Export menu, and triggers the browser's own `window.print()` - zero PDF
  dependencies (no jsPDF or html2canvas). The printout hides the review UI, prints on a clean light
  theme, expands collapsed sections, and appends the current comments. It deliberately does not
  intercept `Ctrl/Cmd+P`, so the browser's own print/PDF shortcut still works unchanged.

## [1.197.0] - 2026-07-21

### Fixed

- Screen readers now announce the FIRST toast of a session. The `#toast` element ships as a live
  region (`role="status"`/`aria-live="polite"`) so it is already live before any toast fires, and
  `showToast` sets the role/politeness before mutating the toast text (a live region added in the
  same tick as its first text change is not announced by most screen readers). (CMH-A11Y-03)
- Marking a section reviewed now warns when the marker cannot be persisted (localStorage full or
  blocked) with an assertive toast, instead of silently painting `Reviewed` and letting it revert on
  reload - symmetric with the existing un-review warning. (CMH-REVIEW-15)

## [1.196.0] - 2026-07-20

### Fixed

- The floating "Add Comment" affordance is now unified across the structural-anchor layers (image,
  mermaid, diff, link, widget, heading): only one button is ever visible at a time. A nested
  `<a><img></a>` (a common clickable thumbnail or logo) previously left both the image and link
  buttons showing at once; now the innermost element owns the affordance deterministically,
  independent of hover-event order, and a dismissed inner button no longer suppresses the enclosing
  layer. (CMH-ANCHOR-01)

## [1.195.0] - 2026-07-20

### Fixed

- The `<head>` mermaid-loader scan used by `tools/authoring/upgrade.py` (when re-emitting the loader
  into an existing document) and by the example build is now comment-aware: a commented-out
  `<head>` or `<script>` block placed before or around the real document head is no longer mistaken
  for the head or the loader, so upgrade/regeneration always targets the real loader and never
  rewrites a decoy inside an HTML comment. The real loader's own preceding `<!-- Mermaid loader -->`
  comment is still detected and stays part of the swapped block. (CMH-MMD-09)

## [1.194.0] - 2026-07-20

### Fixed

- Code and KQL line-number gutters now stay aligned to the text even when a report, deck, or theme
  gives the block an ambient `line-height` of the keyword `normal`. Every code/KQL `<pre>` now
  carries a deterministic numeric `line-height`, so the gutter always reads a stable px line-height
  instead of falling back to a hardcoded `20px` (which left the numbers sitting above the text and
  drifting down a tall block). (CMH-CODE-07)

## [1.193.0] - 2026-07-20

### Fixed

- A standalone built-in canvas chart (`canvas.cmh-chart` with inline `data-cmh-chart-points`/`-source`)
  placed directly in a shrink-to-fit container (`width: max-content`, an `inline-block`, a float, or an
  auto-sized `inline-flex`/grid item) - rather than inside the shipped definite-width `figure.chart >
  .chart-wrap` - no longer renders `dpr x` oversized on a HiDPI screen (`devicePixelRatio > 1`). The
  renderer now measures the chart's logical size against a bitmap reset to the authored size (which is
  devicePixelRatio-independent, so the canvas's own dpr-scaled bitmap cannot drive its container's width
  - the feedback loop - and which preserves the aspect ratio so an auto-height chart is not squared),
  falls back to the authored `width`/`height` attributes when the container collapses without the canvas,
  and pins the box so the chart displays at its intended size; the shipped definite-width chart pattern
  is unaffected (CMH-CHART-10).

## [1.192.0] - 2026-07-20

### Fixed

- Report (non-deck) Mermaid diagrams in the shipped example reports and the deployed-site demos no
  longer collapse to a tiny frozen bar when their section is hidden at load. The examples carried the
  OLD naive in-place `mermaid.run()` loader (a diagram whose section was `display:none` at load
  rendered a degenerate ~16px SVG that never re-measured), because `build.py`'s `regen_example` swaps
  only the CSS / COMMENT UI / JS layer regions and never re-emitted the shell-baked `<head>` mermaid
  loader. `regen_example` now re-emits the canonical loader from `PORTABLE.html` into every example
  (the same `<head>`-scoped, ambiguity-guarded, vendored-safe re-emit `upgrade.py` does), so an
  example single-sources the loader and honors CMH-MMD-07 (CMH-MMD-09).

### Changed

- Report (non-deck) Mermaid diagrams whose natural width is well under the content column now scale
  up toward the column instead of being marooned by mermaid's intrinsic-width inline `max-width`. A
  `cmh-diagram-narrow` class (set by `updateMermaidWidthClass` with hysteresis, so scaling a diagram
  taller cannot flip it back and forth on the reveal/resize observer) grows the SVG to a capped
  `min(100%, natural * 1.4)`, centered, for both `pre.mermaid` and `div.mermaid` hosts. Wide diagrams
  (which scroll) and deck diagrams (own fit) are unaffected (CMH-MMD-10).

## [1.191.0] - 2026-07-20

### Fixed

- The full-screen demo reports on the site (and the shipped `report-taxi.html` /
  `report-community-garden.html` examples) now carry the commentable-html favicon, so a browser
  tab shows the CMH mark instead of the generic globe. Those two example sources predated the
  shell-baked favicon and were the only ones missing it.

### Added

- The validator now warns (an error under `--strict`, the mandatory finalize path) when a document
  has no `<link rel="icon">` favicon in its head, so a missing favicon is caught before handoff
  (CMH-KIND-05). `retrofit.py` injects the CMH favicon when the host head has none, and
  `upgrade.py` adds it when migrating a pre-favicon document (neither duplicates an existing one).
## [1.190.0] - 2026-07-20

### Fixed

- `Clear all comments` now also resets a note-only change. Its early-return guard checked comments,
  widget-state, and checklist changes but omitted `notesChanges()`, so on a document whose only
  pending change was an edited `data-cmh-note` field (no comments, no checklist/widget changes)
  clicking Clear all was a silent no-op and left the note edit in place. The guard now includes note
  changes, and the confirm dialog names the widget, checklist, and note resets it performs.
  (CMH-NOTE-06)

## [1.189.0] - 2026-07-20

### Added

- Each side-TOC review-filter button (All / Reviewed / Unreviewed / Commented / Changed) now shows a
  live per-state count as an inline `(N)` beside its label - `All` shows the total section count and
  the four states partition it, so at a glance you see how many sections are in each state. The count
  refreshes as sections are marked reviewed, commented, or changed. The count span is `aria-hidden`
  and its number is folded into each button's accessible name so it is announced once, and the label
  and count stay on one line per button (the group wraps into rows without overflowing the sidebar,
  even with two-digit counts) (CMH-REVIEW-14).

## [1.188.0] - 2026-07-20

### Fixed

- Showcase deck: the Act 1 Mermaid loop diagram no longer paints solid black blobs. Deck flowchart
  edge connectors are now stroked with `fill: none` (only the arrowhead markers keep a fill), so a
  curved back-edge is drawn as a thin line instead of filling the area under its curve with the dark
  slide color. The fix is both in the runtime deck default (`assets/css/90-deck.css`) and in the
  showcase deck's own parchment mermaid theme (CMH-DECK-09).

### Changed

- Showcase deck slide 12 ("Code and notes") now demonstrates the notes feature with REAL live,
  editable notes (`data-cmh-note` fields the runtime upgrades into editable, change-tracked
  textareas) instead of a static mockup (CMH-DECK-SHOWCASE-08). A note change card's `jump` is now
  deck-aware: `jumpToNote()` activates the note's owning slide before scrolling. To support live
  notes on a slide, the notes authoring validator (`validate.py`) no longer flags a note on a deck
  slide - a slide, unlike a checklist/diff/widget substrate, does not `cm-skip` its descendant text;
  a note nested inside a checklist/diff/widget is still flagged (CMH-NOTE-15).
- Showcase deck slide 18 ("Three portability modes") now tags each part with a colorful source pill
  (folder / CDN / inlined / storage / seed), matching the site's "Three portability modes" theme,
  instead of plain table text; the Portable and Offline handoffs keep both the seed and storage
  pills (CMH-DECK-SHOWCASE-17).

## [1.187.0] - 2026-07-20

### Fixed

- Typing in an editable note (`data-cmh-note`) no longer freezes a large document. The note `input`
  handler used to re-render the whole sidebar synchronously on every keystroke, and that render runs
  two full-document tree walks (a `getTextNodes` walk plus the section-review scan), so each
  keystroke cost O(document) work (hundreds of ms on a report with tens of thousands of text nodes).
  The typing path now persists the edit synchronously but coalesces a keystroke burst into a single
  debounced re-render (a note's document position does not move while its text is edited). The
  lightweight UI (portability badge, Copy-all affordance, first-change sidebar auto-open) updates
  synchronously but only on the note-dirty transition, so a burst does no per-keystroke document
  scan; per-keystroke cost is bounded independent of document size. Programmatic reset / clear-all
  still render immediately. (CMH-NOTE-17)

## [1.185.0] - 2026-07-20

### Changed

- `SKILL.md` now opens with a single upfront `## Capabilities` list (above the detailed Steps) that
  names the tested tool or contract for every capability - create/retrofit/upgrade, the document
  kinds (including the flat `slides` kind vs a real deck), the review surface (including per-section
  "Mark reviewed" tracking), highlighted code, KQL, diffs, mermaid, charts, images, the layout tools,
  layered checklists and editable notes fields (scaffold and apply), commentable widgets, animated
  decks, output modes, and theming (including deck theme presets) - and directs the agent to use the
  named tool rather than invent a novel mechanism. This closes a discovery gap where an agent missed
  that CMH already supports editable notes fields and considered building its own. A companion
  `## Always validate before handoff (MUST)` section states the mandatory
  `finalize.py --strict` + `validate.py --strict` (plus `deck_validate.py --strict` for decks) pass
  upfront so it cannot be missed. (CMH-DOC-17)

## [1.182.0] - 2026-07-20

### Fixed

- Saving a text comment on a selection that overlaps an existing text highlight is now rejected with
  the "Comment was not saved" toast instead of silently nesting a `mark.cm-hl` inside the existing one.
  A nested highlight made the OUTER comment effectively unclickable (click/hover/popover handlers
  resolve to the innermost mark), contradicting CMH-CORE-11. The composer's text-save path now runs a
  `rangeOverlapsHighlight` pre-check (in `assets/js/15-context.js`) BEFORE wrapping - it derives each
  existing highlight's LIVE character interval from a single text-node walk and rejects the save when
  the new selection overlaps one (a half-open test, so it stays correct even when a comment's stored
  offsets are stale relative to the DOM - for example after a table sort leaves a multi-row highlight
  discontiguous - and a touching, non-overlapping adjacent selection is still allowed). `restoreHighlights` (`assets/js/95-startup.js`) applies persisted text comments sorted by
  start and skips wrapping any whose range overlaps one already highlighted (an O(n) sweep), so a
  legacy/crafted overlapping set keeps only the first-applied highlight - mirroring the diff sub-range
  guard - while the overlapping comment stays listed in the sidebar. Editing the existing comment on
  the same range (CMH-CORE-10) is unaffected (CMH-CORE-11).

## [1.181.0] - 2026-07-20

### Fixed

- A built-in canvas chart (a `canvas.cmh-chart` / `figure.chart canvas` with inline
  `data-cmh-chart-points`/`-source`) authored inside a collapsible `<section>` that is collapsed
  (`display:none`) at load now re-renders at its real column width the moment its section is revealed,
  instead of staying blurry until the next window resize (CMH-CHART-09). While collapsed the canvas
  reads `clientWidth` 0 and draws its bitmap to the width fallback (the `width` attribute, else 760),
  so it was sized for the wrong width; a reveal `ResizeObserver` on each chart canvas re-draws it once
  on the transition from zero-size to visible (mirroring the Mermaid width-class observer from
  CMH-MMD-07). It is a one-shot reveal hook, not a perpetual size mirror, so a standalone
  `canvas.cmh-chart` in a shrink-to-fit container on a HiDPI screen cannot keep enlarging its own
  bitmap; genuine window resizes stay handled by the existing resize listener. This is the same
  render-while-hidden class as #430 (Mermaid).
- Pinned that code/KQL line-number gutters stay aligned when a collapsed section is revealed
  (CMH-CODE-06). Unlike the canvas chart above, the gutter needs no reveal recompute: the browser
  resolves a numeric `line-height` to a px value via `getComputedStyle` even for a `display:none`
  block, so the gutter offsets laid down while collapsed already match the visible line-height after
  reveal. A regression test locks that invariant in.

## [1.180.0] - 2026-07-20

### Changed

- The comments sidebar `Hide` button is now accent-tinted (an accent-soft background with accent text
  and border, and a solid-accent hover) so it stands out clearly and reads as distinct from the neutral
  `Help & About` button beside it (CMH-SIDE-09).

### Added

- The overflow (`...`) menu header now shows the running layer version (`v<version>`) between the
  portability badge and the brand icon; the version is decorative text and does not change the menu
  button tab order (CMH-MENU-ICON-03).

## [1.178.0] - 2026-07-20

### Added

- Deck mode now accepts `Backspace` as a "previous slide" key, alongside `ArrowLeft` and `PageUp`, so
  presenters can step one slide back with the key many slide tools use (CMH-DECK-05). It respects the
  same guards as the other navigation keys: it does not move slides while a comment field or other
  editable target is focused, or while the comment-options menu or other blocking deck chrome is open.
  Because `Backspace` uniquely carries a legacy browser "history back" default, the deck suppresses that
  default whenever it owns the key (including at the first-slide boundary, where the step back is a
  no-op) so a viewer is never navigated away from the deck.

## [1.175.0] - 2026-07-19

### Fixed

- `tools/authoring/upgrade.py` now re-emits the shell-baked mermaid loader bootstrap from the template,
  so the deck label fix (CMH-MMD-08) and any future change to the loader in
  `assets/template.shell.html` reach already-generated documents on upgrade (CMH-MMD-09). The bootstrap
  is baked into the document `<head>` at scaffold time, OUTSIDE the swappable CSS / COMMENT UI / JS
  regions, so a region swap alone never touched it: a deck generated before CMH-MMD-08 kept its old
  bootstrap after an upgrade and its mermaid labels still clipped. The swap replaces the `<head>`
  `<script type="module">` mermaid loader (and its `<!-- Mermaid loader -->` comment); it is scoped to
  `<head>` so authored body/CONTENT can never be mistaken for the loader, identifies the loader by a
  mermaid `import("...mermaid...")` so loaders predating the `pre.mermaid, div.mermaid` guard match
  too, preserves a hand-vendored offline loader (a local/relative mermaid import; a protocol-relative
  `//host` import counts as remote) rather than re-pointing it at the CDN, is document-kind-agnostic
  (the `.deck-stage` gate is a runtime check, so a non-deck report keeps HTML labels) and idempotent,
  and `--check` now flags a stale bootstrap. The Export Offline re-init is not shell-baked (it lives in
  the swapped JS region) and was already refreshed by the JS swap.

## [1.174.0] - 2026-07-19

### Changed

- Deck mermaid diagrams now scale to fill the available slide AREA using both width and height
  (contain-to-fit), not just the width (CMH-DECK-35, building on CMH-DECK-26), and are bounded to the
  slide so they never overflow or clip (even when nested in wrappers). A slide whose only non-text
  content is a single diagram and that is not laid out as a `.cmh-cols-2` is auto-detected as a diagram
  slide (`cmh-deck-diagram-slide`) and laid out as a flex column, and the runtime sizes the rendered
  SVG to the largest aspect-preserving box that fits the slide's fixed content area. A slide the author
  laid out as two columns keeps that layout - the automatic rule never flattens a `.cmh-cols-2`; the
  opt-in `.cmh-slide-diagram` recipe forces the fill and un-confines a lone diagram from its half column
  to the full slide width. The fit recomputes on resize and on slide activation, composes with
  CMH-MMD-08 (`htmlLabels: false`) so labels stay crisp, and survives Export Offline.

## [1.172.0] - 2026-07-19

### Fixed

- Deck mermaid node/edge labels no longer clip mid-word (CMH-MMD-08). A deck renders its slides inside
  a CSS-scaled 1920x1080 stage, and mermaid's default HTML (`<foreignObject>`) labels are re-laid-out
  by the browser against that scale, so a node box sized from the unscaled measurement is too small and
  wider labels (for example `You comment on the exact spot`) were cut off. On a deck the mermaid loader
  now initializes with `htmlLabels: false`, rendering labels as SVG `<text>` that scales with the
  diagram and never re-flows, so every label stays fully visible inside its node box. Reports keep the
  richer HTML labels. The same choice is applied by the live loader and the Export Offline re-init.
- Deck mermaid comment labels keep the space at a wrapped-line boundary. mermaid splits an SVG `<text>`
  label into per-line `tspan` rows with no separator, so the anchor key, comment quote, and Copy all
  had dropped the wrap-point space (`exact spot` -> `exactspot`); `mermaidNodeLabel()` now rejoins the
  rows with a space.

## [1.171.0] - 2026-07-19

### Added

- Link handling for author-facing references (CMH-LINK-01..04): at render time every external
  `<a href>` in the document is stamped `target="_blank"` + `rel="noopener noreferrer"` so a
  reference opens in a new tab and the reader keeps their place (same-page `#` fragments, `.cm-skip`
  UI chrome, and `javascript:` links are left untouched, and an author-set `target` is respected).
  Each link is now commentable like an image or mermaid node: hovering or keyboard-focusing a link
  reveals a floating `Add Comment` affordance that anchors an `anchorType: "link"` comment to that
  link (by index + href/text) without navigating - a normal click (or Enter) still follows the link,
  while the floating button or the non-navigating `Alt+Enter` chord opens the composer. Links are
  classified by their normalized protocol (only `http`/`https`/`file`), so control-char-obfuscated
  `javascript:`, `mailto:`/`tel:`, and `data:` links are never stamped or made commentable, and the
  `_blank` rel-enforcement is case-insensitive (reverse-tabnabbing defense). Link comments ring the
  link, list a card, flash on jump, and survive reload, Copy all, Export Markdown, and Export Offline.

## [1.170.0] - 2026-07-19

### Changed

- Deck comment-scope menu now stacks its options vertically with "Comment on deck" above
  "Comment on slide" (CMH-DECK-34).
- In deck mode a plain click on EMPTY slide space advances to the next slide in BOTH present and
  review-panel-open modes; a click on text (or any interactive target) never advances, so text
  stays selectable for commenting. "Empty" is decided by hit-testing the click POINT against the
  slide's text rects, so a wrapper/slide carrying loose text no longer blocks advancing, and a
  keyboard activation of a focused control never advances (CMH-DECK-31).
- Saved text highlights and the composing preview both paint a band slightly shorter than the line
  box (zero horizontal padding, no reflow), so a highlight that wraps across two lines now shows
  visible vertical spacing between the lines (CMH-SEL-02).
- Deck pills lift on hover: the reusable `.cmh-pill` recipe gains a hover-lift for all decks
  (CMH-DECK-RECIPE-05), and the showcase byline pills lift on hover (CMH-DECK-SHOWCASE-16).

### Showcase deck

- Refreshed the title and Act 1 promise copy: the title reads "Plan with AI, visually rich review
  inline, repeat.", the Act 1 paragraph is rephrased, the redundant "reviewed end to end" pill is
  removed, and the "Copy all" control is emphasized in its pill (CMH-DECK-SHOWCASE-13).
- The Chat / Markdown / HTML comparison table now marks the Commentable HTML row's winning cells
  with a distinct green fill and check glyph so the differentiators stand out (CMH-DECK-SHOWCASE-14).
- The title slide embeds a real screenshot of a document with selected text and the Add-comment
  popup, so the review workflow is visible up front (CMH-DECK-SHOWCASE-15).
- The top-right site logo sits further into the corner and its tooltip reads just "Commentable
  HTML" (CMH-DECK-SHOWCASE-10).

## [1.169.0] - 2026-07-19

### Added

- Code blocks can carry an optional filename/description caption line: add `data-code-caption` to a
  `<pre>` (for example `data-code-caption="trigger.kql"`) and the runtime renders a `cm-skip`,
  non-selectable caption bar above the code, laid out like the KQL caption bar (filename on the left,
  the language pill and Copy button inline on the right) so no language-label width overlaps the
  filename. It is styled consistently in report and deck modes, leaves the language pill, Copy
  button, syntax highlighting, and commenting on the code intact (a caption-crossing drag cannot
  leak the filename into a comment's quote), never doubles a KQL figure's own caption, and survives
  Export Offline (the caption re-renders from the surviving attribute on reopen). (CMH-CODE-05)

## [1.168.0] - 2026-07-19

### Changed

- The validator now ERRORS in NonPortable mode when a baked absolute or `file://` companion
  reference resolves inside an OS temporary directory that is not the document's own folder
  (CMH-VAL-16). Such a document validates clean at creation but silently loses its whole comment
  layer once the OS reaps the temp directory - the exact failure behind a shared document whose
  CSS/JS 404'd after handoff. Temp detection is cross-platform and root-anchored (`TMPDIR`/`TEMP`/
  `TMP` and `tempfile.gettempdir()`, symlink-resolved via `realpath`, plus `/tmp`, `/var/tmp`,
  `/var/folders`, `/windows/temp`, and per-user `AppData/Local/Temp`), so a durable project folder
  named `tmp` is never mis-flagged; relative refs and a companion sitting beside the document are
  never flagged. The message points at a Portable single-file export or copying `dist/` to a
  durable folder.

## [1.167.0] - 2026-07-19

### Added

- Preview highlight while composing a text comment (CMH-CORE-17): opening a new text-comment
  composer immediately shows the selected text as a live amber preview highlight
  (`mark.cm-preview`) so the reviewer sees exactly what the comment will anchor to. Saving turns
  it into the real persisted highlight over exactly the previewed text; cancelling via the Cancel
  button or Escape removes it and stores nothing. The preview is transient chrome (no `data-cid`,
  never persisted, excluded from export and print), stays in the text-offset space so a concurrent
  composer's anchors never cross, is fully cleaned up if wrapping throws, and is re-applied if a
  save cannot complete so the still-open composer keeps its anchor cue.

## [1.166.0] - 2026-07-19

### Added

- CMH-ASCII-01: the document producers now rewrite AI "smart" typography - em/en dashes, the
  ellipsis glyph, curly quotes, and non-breaking / zero-width spaces - to plain ASCII in visible
  prose, leaving code, script, style, and HTML comments verbatim. `finalize.py` (reports/plans) and
  `deck_scaffold.py` (deck slide prose) run the new shared `normalize_typography.py` normalizer by
  default; opt out with `--no-normalize`. This keeps every report, plan, and deck on the plain-ASCII
  house style without a hand pass.

### Changed

- Deck hover is smoother (CMH-DECK-21, CMH-DECK-RECIPE-02): table-cell, metric-tile, and
  reference-pill hovers no longer animate `box-shadow` (a per-frame repaint) and table cells no
  longer apply a `transform` lift (which relayouts the table). Cells ease only the cheap
  `background-color` and the highlight ring snaps; tiles and pills keep their lift via the
  compositor-friendly `transform`. Sweeping the mouse across a large deck table no longer lags.

## [1.165.0] - 2026-07-19

### Added

- Third-party MIT license notices for the vendored rich-content libraries (mermaid, Chart.js). The
  upstream license texts are vendored under `dev/assets/vendor/*.LICENSE`, `build.py` assembles them
  into a shipped `THIRD_PARTY_NOTICES.md` (copied unzipped beside the plugin LICENSE and gated by
  `build.py --check`), and `Export Offline` now embeds each bundled library's MIT notice as an HTML
  comment beside the inlined library, so a redistributed offline artifact carries the required
  copyright and permission notice.

## [1.163.0] - 2026-07-19

### Changed

- Documented the online mermaid CDN import as a by-design accepted supply-chain risk (CMH-SEC-04):
  the runtime loads mermaid from a version-pinned jsDelivr URL (single-sourced from the mermaid
  dependency), with a zero-network vendored fallback via Export Offline. Credited the third-party
  rich-content libraries the plugin renders with - mermaid and Chart.js, both MIT - in the plugin
  README, the marketplace README, the site plugin page, and the vendored-libraries provenance doc.

## [1.162.0] - 2026-07-19

### Added

- Deck comment scoping: an empty right-click on a slide now offers BOTH "Comment on slide" (a comment
  tied to that specific slide, whose sidebar card names the slide and whose jump navigates to it) and
  "Comment on deck" (the deck-wide comment, the relabelled document-wide comment). (CMH-DECK-33)
- Deck click-to-advance: in present mode (comment panel closed), a plain left-click on non-interactive
  slide content advances to the next slide; links, buttons, form controls, comment anchors, and deck
  chrome keep their own behavior, and the open review panel is never yanked forward. (CMH-DECK-31)

### Changed

- Deck edge navigation arrows now reveal across a wide left/right hover band (not only a thin edge
  strip), stay reliably visible, and are a larger, comfortably clickable target. (CMH-DECK-32)

## [1.161.0] - 2026-07-19

### Added

- Deck layer recipe classes so a themed deck needs no per-deck CSS for common needs (CMH-DECK-RECIPE-01/02/03/04):
  - Status-pill variants `.cmh-pill.is-available` (green), `.is-wip` (amber), `.is-planned` (slate), each with white text at AA contrast.
  - Metric tiles (`.cmh-metric`) hover-lift, and the metric value is capped at a fixed stage size with `overflow-wrap: break-word` so long word-labels no longer overflow the card.
  - A reference-row recipe (`.cmh-refs` + `.cmh-refs-label`) that renders reference links as a horizontal row of pills; on a `.cmh-slide-flow` flex-column content slide its `margin-top: auto` pins the row to the bottom of the fixed slide box.
  - Deck-scoped default prose spacing (paragraphs collapse their top margin, list items gain bottom spacing, lists get a 1.5 line-height) so a deck reads as spaced bullets-over-prose without per-deck CSS; non-deck documents are unaffected.
- `deck_validate.py` now also gates the reference-pill contrast pair (`--slide-link` over `--cmh-deck-code-bg`), so a custom theme cannot ship low-contrast reference links.

## [1.160.1] - 2026-07-19

### Security

- Source provenance now stores only the source filename in `data-doc-source`, Copy all, and every
  preserved export. Authoring tools and runtime fallbacks strip directories, drive letters,
  usernames, and internal project paths while leaving the document comment key, session id, and
  generated timestamp unchanged (CMH-SEC-03, part of #438).

## [1.160.0] - 2026-07-19

### Added

- The deck slide-overview navigator now has a search box at the top that filters the slide list by
  title as you type; keyboard navigation and the count follow the filter, and reopening the overview
  resets it (CMH-DECK-30).
- Clicking the "Open comment" hover bubble now also opens an inline on-screen comment dialog next to
  the highlight, showing the note and an Edit button that opens the composer; clicking elsewhere closes
  the dialog, and a pointer click there is swallowed so it performs no other action (for example it does
  not follow a link the highlight sits on) while a keyboard activation still reaches its target. The
  existing sidebar jump still happens alongside it (CMH-CORE-16, closes #450).

## [1.159.0] - 2026-07-19

### Changed

- Section review now stays out of the way until you start reviewing: the per-section review badges
  and the side table-of-contents review-status filter are dormant on a freshly opened document and
  activate only after you mark a section reviewed or add the first comment (the hover "Mark reviewed"
  affordance on any heading remains available as the entry point). Each side-TOC entry now shows a
  single-character status badge - R (reviewed), C (commented), ! (changed), or a hollow badge for
  unreviewed - rendered as a pseudo-element so it never pollutes the entry text. The reviewed state
  continues to bake into Portable and Offline exports and now re-activates the review UI when an
  exported file is reopened. Export also prunes markers for headings that no longer exist, so a shared
  copy never carries stale review metadata for a removed section.

## [1.158.0] - 2026-07-19

### Fixed

- A Mermaid diagram authored inside a collapsible section that is collapsed (`display:none`) at load
  no longer renders as a tiny, broken graph. Drawing a diagram in place with `mermaid.run()` while its
  container has a zero-size box produced a degenerate `~16px` viewBox with the nodes stacked on top of
  each other, and mermaid never re-measured it, so it stayed broken once the section was revealed. The
  loader now renders each hidden diagram by running mermaid on an OFF-SCREEN CLONE (a `1000px`
  sandbox) and moving the rendered SVG into the real element - reusing mermaid's own source extraction
  (so `<br/>` labels and entities match a visible diagram) and error handling (a malformed diagram
  leaves no stray SVG in the page). Every diagram is therefore laid out correctly at load - correct the
  moment its section is revealed and also correct if the collapsed section is printed. Renders are
  serialized so rendering many diagrams at once cannot corrupt them, and one malformed diagram does not
  starve its siblings (CMH-MMD-07). Deck slides (hidden with `visibility:hidden`, not `display:none`)
  keep their existing eager render. On reveal the wide/scroll-fade classification is recomputed against
  the diagram's now-real container width, and the loader exposes `window.__cmhMermaidReady` for
  print/screenshot automation. The Export Offline vendored-inline re-init carries the same logic, so
  offline-exported reports render collapsed-section diagrams correctly with zero network.

## [1.157.0] - 2026-07-19

### Fixed

- The `upgrade.py` and `retrofit.py` authoring tools now preserve the input file's dominant newline
  (detected from the raw bytes) through the transform, so a Windows-authored (CRLF) portable or host
  HTML file is no longer silently normalized to LF on upgrade/retrofit (CMH-TOOL-08, CMH-TOOL-15,
  closes #437).

### Changed

- The shipped `pkg/` root now carries its own `LICENSE` (matching the repository root LICENSE) so the
  always-shipped session hooks are covered by a license even before `skill-resources.zip` is
  extracted (CMH-PKG-13).

## [1.156.0] - 2026-07-18

### Security

- PPTX deck imports now preflight ZIP central-directory metadata before starting the vendored
  extractor, rejecting archives with excessive expanded size, entry count, or compression ratio
  to prevent zip-bomb memory exhaustion (CMH-DECK-29, closes #410).

## [1.155.0] - 2026-07-19

### Security

- Copy all agent bundle: hardened against untrusted-document / prompt-injection. Each free-text
  reviewer note is now wrapped verbatim in a dynamic, tilde-sized `UNTRUSTED REVIEWER NOTE` fence
  (sized longer than any tilde run in the note), and a read-first AGENT INSTRUCTIONS block frames
  reviewer notes as untrusted, document-scoped change requests the agent may act on only as edits to
  the document under review - as data, never as agent or system instructions, and never as a trigger
  for tool use beyond the documented handled-id update (CMH-COPY-08). The document `data-doc-source`
  is emitted single-line so an embedded newline cannot forge a standalone machine line (CMH-COPY-08).
- Copy all machine trailer: all machine-readable JSON (`HANDLED_IDS_JSON`, `NOTES_STATE_JSON`,
  `CHECKLIST_STATE_JSON`) now lives only inside ONE unconditional final
  `=== CMH MACHINE TRAILER (do not edit) ===` block (canonical empty values when there are no
  changes). The `notes_apply.py`, `checklist_apply.py`, and `mark_handled.py` tools read JSON only
  from within that fenced trailer, so a forged trailer or state line inside a note body or the
  document source is ignored rather than winning a last-match over the whole bundle (CMH-COPY-09,
  CMH-HANDLED-01).

## [1.154.0] - 2026-07-18

### Security

- Checklist and notes state maps (`_clOverrides`, the `::cl` save/load maps, `_noteOverrides`) are
  now built with `Object.create(null)` at every assignment site; `_clLoad` additionally re-homes
  the parsed outer map and each per-checklist inner map onto a null-prototype copy before reading
  them, and the checklist token lookup uses a `hasOwnProperty` guard. As a result, a checklist
  authored with `data-cmh-checklist="__proto__"`/`"constructor"` (or a crafted `::cl` localStorage
  payload using `__proto__`/`constructor` keys or codes) can no longer write onto or return
  `Object.prototype`. A checklist id or item key of `constructor`/`__proto__` still works as
  ordinary data; no behavior changed for legitimate documents (CMH-SEC-02).

## [1.153.0] - 2026-07-18

### Added

- Section review tracking: hover or keyboard-focus any heading (h1-h6) to mark that section
  reviewed. A badge to the right of the title shows one of four states - Reviewed (green),
  Changed - re-review (amber, when the section content changed since it was reviewed), Commented
  (blue, when the section has an open comment), or unreviewed. Change detection uses a deterministic
  content hash of the section (heading to the next same-or-higher heading, excluding runtime chrome);
  a one-click re-review on a Changed/Commented badge re-stamps it. The side table-of-contents gains a
  per-entry state dot and an All / Reviewed / Unreviewed / Commented / Changed filter that collapses
  the sections it hides. Markers persist in localStorage (with tombstones for cleared baked markers)
  and bake into Portable/Offline exports via a dedicated `reviewedSections` block (kept out of the
  Copy-all bundle; stripped from Plain export). New `tools/authoring/mark_reviewed.py` bakes markers
  from the CLI, and `section_hash.py` shares the byte-identical hash contract with the runtime
  (pinned equal by a JS/Python golden and an end-to-end extractor-parity test).

## [1.149.0] - 2026-07-18

### Security

- Bounded `mergeCommentSets()` against a pathological `embeddedComments` array or a
  poisoned cross-document `localStorage` array under a matching `data-comment-key`:
  the merged comment count is now capped at a generous `CMH_MAX_COMMENTS` bound, and
  any comment whose `start`/`end` is present but not a finite, non-negative, ordered,
  in-range offset is dropped, so startup's `backfillContext()`/`restoreHighlights()`
  per-comment document walk can no longer be driven into unbounded
  O(comment_count x document_size) work by untrusted input. Normal documents with
  realistic comment counts and offsets are unaffected (CMH-PERSIST-04).

## [1.145.0] - 2026-07-18

### Changed

- Deck comment-options menu (all decks): the menu surface is now a 3-state RADIO GROUP of mutually
  exclusive options - `Comments off`, `Comments on, panel closed`, and `Comments on, panel open` -
  of which exactly one is selected (`menuitemradio`, `aria-checked`), so choosing one is clearly a
  single pick rather than a set of independent toggles. `Comments off` stays disabled while any
  comment exists (so feedback is never stranded), the site link remains a menu item, and full
  keyboard navigation is preserved (opening focuses the checked option) (CMH-DECK-11).
- The showcase deck's top-right brand mark is now the official Commentable HTML logo rendered as a
  plain image (an inlined, offline-safe `data:` SVG) instead of a bordered card with a hand-drawn
  glyph; it still links to the project site with a clear tooltip (CMH-DECK-SHOWCASE-10).

## [1.144.0] - 2026-07-18

### Changed

- Decks now show a dismissible "Best viewed in landscape" hint on narrow portrait phones only, leaving landscape and non-deck documents unchanged (CMH-DECK-28).
- The comments sidebar now uses one Export menu for Portable, Offline, Markdown, and Plain HTML actions instead of four always-visible export buttons, while keeping the same export handlers and downloads (CMH-EXP-13).
- Mobile mermaid diagrams now use a width-based classifier: small diagrams fit the viewport, genuinely wide diagrams keep a scrollable min-width, and overflowing diagrams show an edge-fade cue (CMH-RESP-09).

## [1.143.0] - 2026-07-17

### Changed

- Redesigned the deck comment-mode control into a 3-state selector persisted per-deck. The corner brand icon now opens a small menu with three states: comments on with the panel closed (the new default, so a reviewer can select text / right-click and Add Comment on any slide without first entering a mode), comments on with the review panel open, and commenting disabled (present-only). "Disable commenting" is only offered when the deck has zero comments, so existing feedback can never be stranded. Adding a comment or opening the panel keeps the persisted state in step. The corner icon now keeps a legible surface background in every state (the old accent-filled "on" state hid the accent-coloured icon), and a small caret marks it as a menu (CMH-DECK-11, CMH-DECK-25). This single menu control supersedes the separate comment-mode toggle and brand link from 1.142.0, so the distinct-toggle-icons behaviour (was CMH-DECK-23) is removed with its test.
- Replaced the deck slide-overview thumbnail grid with a readable numbered list of slide titles (the 1920x1080-to-chip thumbnails were unreadable and rendered canvas/hero content as black blocks) (CMH-DECK-16). This retires the overview thumbnail-snapshot behaviour (was CMH-DECK-24) with its test, since there are no longer any thumbnails to render.
- Deck Mermaid diagrams now scale to fill the slide width instead of rendering at a tiny intrinsic size with a large empty band, and sortable-table sort chevrons on a coloured deck header now use the header foreground colour so they stay legible (CMH-DECK-26, CMH-DECK-27).
- Showcase deck polish: slide content is vertically centered to use the full stage (less bottom whitespace), the amber title highlight now hugs the letters instead of bleeding into the line above, and every slide carries a Commentable HTML brand mark at its top-right linking to the plugin site (CMH-DECK-SHOWCASE-10, CMH-DECK-SHOWCASE-11, CMH-DECK-SHOWCASE-12).

## [1.142.0] - 2026-07-17

### Changed

- Mobile and chrome polish from a full visual audit of the example set (the new `.github/skills/visual-audit` skill drove every example in desktop and mobile viewports; issue #353). On narrow viewports a page title flush to the top no longer renders under the fixed toolbar pill (CMH-RESP-03), the comments sidebar opens as a full-width sheet with the resize handle removed so no document sliver shows behind it (CMH-RESP-04), and the floating scroll-progress bubble is hidden so it never overlaps content (CMH-RESP-05). The compact checklist state control gains a `>=44px` invisible touch target without enlarging its glyph (CMH-RESP-06). The control that reopens the comments panel is now labeled `Comments` instead of the ambiguous `Show` that duplicated the top-bar pill (CMH-CHROME-11), and a disabled deck navigation button keeps a readable contrast instead of near-invisible gray (CMH-DECK-NAV-01).
- Follow-up polish from the visual audit (issue #360), each with a covering test in `tests/72-followups.spec.js`:
  - A leading lede/card (not just a bare title) also clears the fixed toolbar on mobile (CMH-RESP-03).
  - The notes fold/toggle controls and the sidebar comment-card action buttons (jump/edit/delete) get `>=44px` touch targets on mobile without changing their look (CMH-RESP-07). Dense checklist rows also keep enough vertical rhythm (table rows via `td` padding) that adjacent tap targets never overlap into a neighbouring row (CMH-RESP-06).
  - Small charts fit the mobile viewport instead of being force-widened to 560px, which had clipped pie/doughnut legends; wide mermaid diagrams still scroll (CMH-RESP-08).
- `report-checklist` no longer repeats its document title verbatim as its first section heading; the first section is now `About this example`, so the sidebar breadcrumb is not doubled (CMH-CONTENT-17).

### Fixed

- The sidebar/Copy-all context preview no longer glues adjacent elements into a run-on ("18open incidents"): it inserts a separator at non-inline box boundaries. Display-only - the comment-anchoring offset space is unchanged (CMH-CTX-01).
- The deck comment-mode toggle now uses a distinct annotate icon instead of the brand speech-bubble the site link uses, so the two top-corner controls are no longer identical (CMH-DECK-11, CMH-DECK-23).
- The deck overview grid renders faithful thumbnails: slide canvases are snapshotted into images (a cloned canvas is blank), and each cloned SVG's ids are namespaced per clone (with `url(#id)`, `href`, and aria idref references rewritten) so a thumbnail's gradient/mask/filter refs resolve to its OWN defs - fixing the slide-1 logo rendering black, without duplicating a document id when two slides reuse the same id (CMH-DECK-24).

## [1.141.0] - 2026-07-17

### Changed

- `tools/authoring/upgrade.py` now restamps the `<head>` `<meta name="commentable-html-version">` to the template's runtime version during an upgrade (inserting it when a pre-version legacy document lacks it), so an upgraded document no longer self-reports the old version while running the new runtime. The restamp is scoped to `<head>`, so the marker-like JS export regex literal (`content="[^"]+"`) is never matched or rewritten. Post-upgrade validator warnings are now surfaced instead of discarded, and a new opt-in `--strict` flag treats them as a failure (leaving the target unchanged and exiting non-zero); the default still commits so a version-only upgrade is never blocked by a pre-existing content warning (CMH-TOOL-08, closes #359).

## [1.140.0] - 2026-07-17

### Fixed

- Made the vendored rich-libraries blob (the inline gzip+base64 mermaid/Chart.js payload) reproducible across zlib implementations. `build.py` previously gzipped the libraries live via `deterministic_gzip`, but gzip DEFLATE output is not identical between stock zlib and zlib-ng (which Python 3.14 ships), so a dist built on Python 3.14 produced a different blob than CI's stock-zlib build and failed the required `dist-in-sync`/`plugin-tests` checks with no source change. The build now reads a committed `assets/vendor/<lib>.gz` artifact and only base64-encodes it (deterministic on every machine); `build.py --regen-vendor-gz` regenerates those artifacts when a vendored library changes, and `build.py --check` verifies each committed `.gz` decompresses to the current source (decompression is deterministic across zlib impls, so the guard never recompresses) (CMH-BUILD-11, closes #372).

## [1.139.0] - 2026-07-17

### Changed

- Ship the skill as a compact `skills/commentable-html/skill-resources.zip` (only `SKILL.md`,
  `LICENSE`, and the zip in the shipped skill dir) that a SessionStart hook unpacks on first run per
  version. This drastically cuts the number of files the plugin installer writes, working around the
  Windows Defender install failure (`Access is denied. (os error 5)`) where the installer aborts on
  the first transiently locked file - the extractor retries each member with backoff, which the
  installer does not. An update ships a new zip and self-heals on the next session (the version
  marker invalidates), which largely fixes the auto-updater silently never updating on Defender
  machines: it now rewrites just the one zip instead of ~178 files, shrinking the transient-lock
  surface dramatically (a lock on that single file is still possible and simply retries next
  session). The large tutorial (`docs/`) and worked examples (`examples/`) are no longer installed;
  they moved to the plugin top level and are linked online. `build.py` gains `--pkg-dir` /
  `--examples-dir` and assembles the deterministic zip, and the editable + built skill tree now
  lives under `dev/skill/`.

### Fixed

- Harden the first-run extractor and packager (review round): the extractor now refuses to write the
  success marker for a zip that carries no installable runtime directory (a truncated/empty/wrong
  zip self-heals next session instead of caching a broken install); a fully-successful swap that
  then hits a locked orphan backup still writes the marker (the backup is reclaimed next run rather
  than forcing a needless re-extract); `_make_writable` restores the directory execute bit on POSIX
  (not `S_IWRITE` only) so a cleared-bit tree can still be removed; and its NTFS retry set is pinned
  (`WinError 5/32/33/145`). The packager now fails the build if any required runtime dir is missing
  or empty, and `--check` flags a duplicated zip member (which a name-to-bytes map would silently
  collapse). The Windows launcher's `$PSScriptRoot` anchoring and the `-c pass` interpreter probe
  are pinned by tests, plus a Windows-junction packager-guard test.
- Round-7 review hardening: the version-marker fast path now tests for a real FILE (`isfile`, not
  `exists`) and `clear_markers` removes a marker-named directory, so a directory that somehow shares
  the marker name can no longer permanently skip extraction or block the marker write. Added tests
  pin the orphan-backup-cleanup survival, the rename-aside rollback branch, absolute/drive-letter
  zip-member rejection, the stale-lock sidecar cleanup, `.ok.tmp` cleanup, deterministic-zip
  host-neutral metadata, and text LF-normalization.
- Round-8 review hardening: the hook HOT-PATH marker check is now FILE-specific (bash `-f`, PowerShell
  `-PathType Leaf`) so a marker-named directory cannot short-circuit the launcher before Python and
  suppress extraction (previously the `isfile` guard in run() was unreachable behind the launchers'
  `-e`/`Test-Path`). Cleanup now unlinks a symlink/junction as itself instead of following a reparse
  point into its target (os.path.islink misses Windows junctions; matters on Python < 3.12). An
  in-place upgrade prunes the obsolete `docs/` and `examples/` dirs the package no longer ships so the
  runtime converges to the minimal tree. The packager fails closed if a required shipped file
  (`SKILL.md`/`LICENSE`) is missing from the stage. Added tests execute the shipped bash hook commands
  end-to-end (cold/warm/marker-dir) and pin the junction cleanup, the legacy prune, and the missing-file
  guards.
- Round-9 review hardening (junction/reparse robustness): `_make_writable` now prunes reparse points
  from its `os.walk` in place so it never DESCENDS into a junction's external target (a bare `continue`
  did not stop the walk); cleanup/swap use `os.path.lexists` so a BROKEN junction (which `os.path.exists`
  and `os.path.islink` both miss) is detected and removed instead of causing a later `os.replace` to
  fail with WinError 5; and the marker temp file is pid-unique so a leftover locked `.tmp` cannot block
  the marker write. Added tests: no-descend-into-junction, broken-junction removal, pid-suffixed `.tmp`
  cleanup, an executable PowerShell-launcher smoke test (cold/marker-dir), and a canary proving the warm
  hot path spawns no Python. Repointed remaining stale pre-relocation doc paths.
- Round-10 review hardening: cleanup now unlinks a junction NESTED inside a directory being removed
  before calling `shutil.rmtree`, so rmtree can never traverse a nested junction into its external
  target (Python < 3.12 lacked that protection - bpo-31818); a test pins it. Fixed the `.githooks/pre-push`
  layer-dist check, which still targeted the pre-relocation `--out-dir` and always failed; made the
  `40-package.py` build part self-contained (explicit `os`/`re` imports); and added a plugin-level
  `.gitignore` so the extractor unpacking into the source tree during local testing can never stage a
  polluted (non-minimal) shipped skill dir.
- Round-11 review hardening: made the nested-junction protection robust to an unlink FAILURE.
  `_prune_nested_reparse` now returns whether the tree is truly free of nested reparse points, and its
  three callers only proceed to `shutil.rmtree` when it is - so a junction that could not be unlinked
  (e.g. a transient lock) makes the removal retry (or skip) instead of ever letting `shutil.rmtree`
  traverse the survivor into its external target on Python < 3.12. A mock-based test pins the
  unlink-failure path.
- Round-12 review hardening: `_prune_nested_reparse` also fails closed when `os.walk` cannot scan a
  subtree (a junction could hide there unseen) via an `onerror` callback, so `shutil.rmtree` never runs
  on an incompletely-inspected tree. And a crash-recovery backup restore that cannot complete now aborts
  the extraction rather than swallowing the error and then letting the swap delete the very backup it
  meant to keep, so the last-known-good backup survives for the next session. Tests pin both.

## [1.138.0] - 2026-07-17

### Changed

- Slimmed the shipped plugin payload and site skill ZIP by relocating the agent-only `bold-template-pack` reference material into `dev/vendor/frontend-slides/`. The shipped frontend-slides runtime assets and tooling remain in `pkg/`, while separate SHA-256 manifests now keep both vendor trees pristine (CMH-DECK-07, closes #341).

## [1.137.0] - 2026-07-17

### Added

- Two LIGHT native deck theme presets alongside the dark `terminal`: `paper` (warm-cream, editorial-serif, crimson accent) and `editorial` (soft-cream serif, deep-teal accent), each adapted from a frontend-slides `STYLE_PRESETS.md` style (credited via `adaptedFrom` + `sourceCommit`). Both override the full component token set (the defaults are dark) and pass `_deck_theme.load` (composited effective-contrast + opaque `contrastPairs` self-check at AA) and the objective `theme_eval` harness with no validator error, no clipping advisory, and a bounded byte delta (CMH-DECK-THEME-06, issue #343). Scaffold a themed deck with `deck_scaffold.py --theme paper` (or `editorial`, `terminal`).
- Made the previously hard-coded-dark deck code-control surfaces themeable so light decks stay legible: the code/KQL language + copy badge background (`--cmh-deck-code-badge-bg`), the KQL run-link hover colour (`--cmh-deck-code-link-hover-fg`), and the Mermaid subgraph cluster fill/stroke (`--cmh-deck-mermaid-cluster-fill`/`-stroke`), each with byte-exact dark defaults so unthemed and `terminal` decks are unchanged.

## [1.136.0] - 2026-07-17

### Changed

- Recorded the verified license and commit for the vendored `bold-template-pack` in `vendor/frontend-slides/UPSTREAM.md` and added an explicit `bold-template-pack/LICENSE`. The pack originates from `zarazhangrui/beautiful-html-templates` (MIT, Zara Zhang, commit `e5e204fb`), a different upstream repo than frontend-slides; both are MIT by the same author, so adapting a bold template into a native CMH deck preset is now license-cleared (unblocks the Phase 2 bold presets; issue #337).

## [1.135.0] - 2026-07-16

### Added

- Native deck theme presets that incorporate the frontend-slides design system directly into the deck engine, replacing per-deck hand-translation of vendored reference material. A preset is a named JSON profile under `tools/deck/themes/<name>.theme.json` of allowlisted, system-font, contrast-safe deck tokens; `deck_scaffold.py --theme <name>` builds a fully styled deck and the new `deck_theme.py apply --theme <name>` re-themes an existing deck in place. Re-theming is idempotent and comment-safe: the theme block is `cm-skip`, so it never shifts stored comment offsets. Ships the `terminal` preset (dark/technical, system monospace), adapted from the frontend-slides "Terminal Green" style (Zara Zhang, MIT). Deck component colours (syntax tokens, table headers, diff, mermaid) and the link/border are now themeable via `var(--token, <default>)` with byte-exact defaults, plus reusable recipe classes (`.cmh-slide-section`, `.cmh-slide-lede`, `.cmh-cols-2`, `.cmh-metric-grid`, `.cmh-pill`) so a themed deck needs no per-deck CSS. `deck_validate.py` gates every themed contrast pair (compositing the translucent diff rows for a faithful check). Supersedes the vendor-first deck design routing from issue #208; the vendored `frontend-slides` subtree is retained as design provenance and the maintainer refresh source (CMH-DECK-THEME-01/02/03, CMH-DECK-14; issue #334).

## [1.134.0] - 2026-07-16

### Changed

- Polished the showcase deck with a concrete Copy all bundle specimen in the technical section, a tighter medium-comparison table, and a corrected Mermaid-node callback so the pitch is more informative without changing the deck contract (CMH-DECK-SHOWCASE-09, closes #244).

## [1.132.0] - 2026-07-16

### Added

- Deck design playbook: a new CHM-specific `references/deck-design.md` (fill the fixed stage, capture-safe motion, wayfinding, pain-before-mechanism narrative, review-surface patterns, card variety, contrast/clip discipline) plus SKILL.md "ask first" up-front questions that route deck planning to it, salvaged from the corrupted #279 branch (CMH-DECK-22, closes #332).

## [1.131.0] - 2026-07-16

### Added

- Offline export now embeds vendored copies of the rich-content JavaScript libraries (mermaid, Chart.js) so an exported Offline artifact renders diagrams and interactive charts with zero network access (issue #296).

## [1.130.0] - 2026-07-16

### Changed

- Deck showcase polish: added the linked Commentable HTML brand button, distinct Overview/counter nav chrome, a static "make it clearer" comment mockup on the Act 1 After card, richer point-at/install pills, and a supported-languages plus notes-demo slide while preserving the restructured deck flow, the interactive chart, and the new edge-navigation runtime.

## [1.129.0] - 2026-07-16

### Fixed

- Dark KQL caption surfaces now keep the `Run in Azure Data Explorer` link at AA contrast in both
  report dark theme and deck mode, and deck Mermaid connectors/arrows now render darker and thicker
  so they stay readable on the light parchment slides. (CMH-KQL-04, CMH-DECK-09, CMH-DECK-13)

### Added

- `tools/validate/cmhval/contrast.py` now resolves computed descendant text/background pairs and
  low-contrast connector strokes, so `deck_validate.py` catches the old red-on-dark KQL link and
  washed-out diagram arrows before publish. (CMH-DECK-12)

## [1.126.0] - 2026-07-16

### Fixed

- Mermaid checker (`cmhval/mermaid.py`, CMH-SYN-01): flag a `sequenceDiagram` message whose `;` leaves an arrow-free tail (a bare word or ordinary prose, e.g. `A->>B: hi; take entities as-is`), not only an arrow-without-colon tail. Once the first `;`-segment is a real signal, any tail that is not another full signal, a keyword-led statement, or empty is a broken second statement the real parser rejects; the broadened rule stays zero-false-positive (proven against the real-parser corpus). Fixes issue #324.

## [1.125.0] - 2026-07-16

### Changed

- Simplified the showcase deck copy: shorter install guidance, plain-language prompts,
  clearer "paste Copy all and press Enter" review flow, and fewer repeated account/server
  comparisons. (deck issue #290)

## [1.124.0] - 2026-07-16

### Added

- Deck charts can now render from inline canvas data without a remote chart library: the
  showcase deck's watering chart is drawn by the shipped runtime, hovering a bar shows a
  clipped-safe tooltip with the bed label and exact value, and the rendered canvas still
  snapshots cleanly for Offline export. (CMH-DECK-20)
- Deck table cells now animate a subtle hover highlight that keeps the cell text readable
  while making individual review targets easier to spot in the slide. (CMH-DECK-21)
## [1.119.0] - 2026-07-16

### Fixed

- Deck runtime: commenting across the two cards on the "Authoring is deterministic" slide no longer paints an empty highlight over the grid gap (issue #294).
- Deck triage board: the Locked-column Add Comment affordance no longer overlaps the Reset moves button (issue #294).

## [1.118.0] - 2026-07-16

### Added

- Deck navigation: dimmed edge hover-arrows for previous/next slide and Enter/Space to advance when the deck stage is focused (issue #292).

## [1.117.1] - 2026-07-16

### Changed

- Split the shipped layer validator check module into focused assembled topic parts while preserving the public `check_layer` entry point and validation behavior.

## [1.117.0] - 2026-07-16

### Added

- Document-overview strip for report/plan documents: a `cm-skip` `div.cmh-doc-stats` placed
  directly under the `<h1>` title shows the section count, word count, and approximate reading time
  (words / 200 wpm, rounded up). `tools/authoring/doc_stats.py` computes and injects it, and
  `new_document.py`, `finalize.py`, and `retrofit.py` bake it by default for report/plan documents
  (opt out with `--no-stats`). It is idempotent (counts refresh in place), excluded from its own
  word count, and baked into the content so it survives Plain / Standalone export. (CMH-STATS-01)
- Per-version upgrade anti-regression corpus under `dev/upgrade-corpus/`: `tests/test_upgrade_corpus.py`
  upgrades each checked-in fully layered snapshot with the current `tools/authoring/upgrade.py` and
  asserts a strict-clean, idempotent result, so a layer or tool change that breaks upgrading a
  document produced by an older version fails the gate. Snapshots are added per change when a
  version warrants one. (CMH-TOOL-20)

### Fixed

- The generated table of contents no longer double-numbers author-numbered sections. When a heading
  already begins with a section number (for example `1. Executive summary`), `generate_toc.py` strips
  the redundant leading number from the ordered-list entry so the `<ol>` supplies the single number,
  and `finalize.py` / `retrofit.py` de-dup an existing author `<ol>` `.cm-toc` in place. A `<ul>`
  `.cm-toc` (where the author supplies the number deliberately) is left untouched. (CMH-TOC-10)

## [1.116.0] - 2026-07-16

### Changed

- Reworked the showcase deck's Act 4 "behind the scenes" run so it now teaches the
  deterministic region split, the website-style portability model, how the skill is
  assembled from `SKILL.md`, on-demand references, and authoring/validation tools,
  plus the cross-platform Playwright-and-Python validation methodology behind the
  shipped experience. (CMH-DECK-SHOWCASE-06)

## [1.115.0] - 2026-07-16

### Added

- The runtime footer now shows a small copy icon that copies the creating AI agent's
  session id to the clipboard when the document carries a `commentable-html-session-id`
  provenance stamp; the button's accessible label and tooltip name the agent (Copilot or
  Claude), and the control never leaks into a Plain HTML export. (CMH-FOOT-04)
- The document-producing tools (`new_document.py`, `deck_scaffold.py`) stamp that session
  id by default, taking it from `--session-id` or, when absent, an auto-detected
  environment variable (`COPILOT_AGENT_SESSION_ID` for Copilot, `CLAUDE_CODE_SESSION_ID`
  for Claude). `--agent` overrides the label and `--no-session-id` opts out. When several
  agents' session ids are visible at once (a nested launch), the agent actually running the
  tool wins. A local, non-CI live check that drives the real `copilot`/`claude` CLIs is at
  `dev/tests/copilot_e2e_check.py` and `dev/tests/claude_e2e_check.py`. (CMH-STAMP-04)

## [1.108.1] - 2026-07-16

### Changed

- Restructured the showcase deck's narrative flow: added a dedicated header/pitch slide,
  moved the website-style medium comparison and shipped-example prompts earlier, removed
  the redundant recap slide, and replaced the close with a "What's next?" hub plus a
  trailing "Questions?" slide while keeping the shipped widget defaults unchanged.
  (CMH-DECK-SHOWCASE-05)
## [1.107.0] - 2026-07-16

### Changed

- Hardened the information-density advisory (CMH-VAL-15) for authoring edge cases: an inline
  `cm-skip` inside a paragraph now excludes only its own text instead of splitting the paragraph;
  sections are tracked as a heading stack so nested and headless sections are labeled by their own
  heading and two distinct prose walls are each reported; a stray or unmatched `</section>` no
  longer suppresses a genuine wall; and a `<section>` embedded in a layout block no longer reframes
  the enclosing prose section. (CMH-VAL-15)

## [1.106.0] - 2026-07-16

### Added

- `deck/deck_validate.py` now emits a non-fatal per-slide or board-card overload advisory
  when authored content exceeds tunable line or element budgets, helping authors split dense deck
  content before sharing. (CMH-DECK-19)

## [1.105.0] - 2026-07-16

### Changed

- Split the Chart.js reference into focused embedding/tooltips and recipes/data-hygiene guides, leaving `charts.md` as a thin router so agents can load only the chart guidance they need. (CMH-DOC-16)

## [1.104.0] - 2026-07-16

### Added

- `npm run shots` now regenerates all tutorial screenshots from the community-garden example with
  pinned capture state, and `npm run shots:check` plus `rebuild_all.py --check` catch missing or
  stale committed tutorial screenshots before the site syncs them. (CMH-TUT-SHOTS-01)

## [1.102.0] - 2026-07-16

### Added

- The validator now emits a non-fatal information-density advisory for `report` and `plan`
  documents: it warns when a section is a wall of four or more consecutive long paragraphs with no
  table, list, figure, diff, chart, or diagram to break it up, nudging authors toward a real
  skimmable layout. The check uses a dedicated density pass scoped to `#commentRoot`, ignores
  `cm-skip` and paragraphs nested inside layout blocks, resets at any layout block, heading, or
  section boundary, and runs only for `report` and `plan` (`slides`, `board`, `generic`, and a
  missing or unknown kind are exempt). Its thresholds are tunable. (CMH-VAL-15)

## [1.101.0] - 2026-07-16

### Added

- The flat-document validator now checks authored `--cp-*` theme overrides for WCAG contrast,
  evaluating the light and dark theme environments separately so a token overridden only in one
  theme is judged against that theme's value. It runs only on tokens changed from the shipped
  defaults (the accepted defaults are never flagged): text and link pairs use a 4.5:1 target (a
  3.0-4.49:1 near-miss is an advisory warning, below 3.0:1 is an error) and non-text UI pairs use
  a 3.0:1 bar. An override that cannot be resolved to two concrete colors is reported as
  'not evaluated' (a static check, no computed-style parity). A new `--suggest` flag prints a
  compliant nudged value when one is reachable, and the near-miss/unresolved advisories stay out of
  `retrofit.py`'s hard-fail path unless the contrast is actually bad. (CMH-THEME-02)

## [1.100.0] - 2026-07-16

### Added

- Added `tools/deck/deck_fix_fonts.py` to strip copied remote deck font loaders and
  deterministically map web-font stacks to approved system stacks before deck validation.
  (CMH-DECK-18)

## [1.98.0] - 2026-07-16

### Added

- `new_document.py`, `retrofit.py`, and `deck_scaffold.py` now accept `--brand brand.json`
  to stamp validated `--cp-*` theme tokens plus optional local data-URI font faces into
  generated documents, reject unknown or injection-shaped token values, and print a
  low-contrast advisory for unsafe brand color pairs. (CMH-TOOL-19)

## [1.96.0] - 2026-07-16

### Fixed

- Clear now restores slot-level draggable boards to their load-time sibling order,
  including interleaved non-part nodes, while clean boards are left untouched.
  (CMH-BOARD-05)

## [1.94.0] - 2026-07-16

### Added

- Authors can set `data-cm-density="compact"` or `data-cm-density="comfortable"` on
  `#commentRoot` to tune review chrome spacing and font scale through shared
  `--cp-chrome-*` tokens, while documents without the attribute keep the existing
  default density. (CMH-DENSITY-01)

## [1.93.0] - 2026-07-16

### Added

- `tools/authoring/recommend_kind.py` now recommends `--kind report`, `--kind plan`, or
  `--kind slides` from filename and content signals, prints the evidence behind the
  recommendation, and emits advisory mismatch warnings when an explicit kind contradicts
  the signals without changing the chosen kind. (CMH-KIND-04)

## [1.92.0] - 2026-07-16

### Added

- Deck documents now deep-link by stable `data-slide-id`: loading a slide hash opens that slide,
  slide navigation updates the URL hash with `history.replaceState`, and browser hash changes
  navigate without adding runtime history entries. (CMH-DECK-17)

## [1.88.0] - 2026-07-16

### Added

- Flat commentable documents now print and export to PDF cleanly: print media hides runtime chrome,
  expands collapsed sections, resets fixed or shadowed UI into a readable paper flow, appends current
  comments as a print-only appendix, and keeps decks at one slide per page. (CMH-PRINT-01)

## [1.87.0] - 2026-07-16

### Added

- The layer now honors the operating-system "reduce motion" setting
  (`prefers-reduced-motion: reduce`): non-essential animations and transitions (the composer flash,
  the mermaid and diff pulses, the checklist and notes flashes) - including their delays and
  repeat loops - are clamped to a near-instant single pass so they do not animate for
  motion-sensitive readers, while everything still lands in its final state. Programmatic smooth
  scrolls (jump-to-comment, scroll-to-top/bottom, deep links) also become instant under the
  preference. (The deck slide stage keeps the vendored slide engine's own reduced-motion rule for
  its essential slide transition.) (CMH-A11Y-07)

## [1.86.0] - 2026-07-16

### Fixed

- `new_document.py --out` now preserves an existing target by writing the first free
  `-2` / `-3` suffixed sibling unless `--force` is supplied, and derives `--key auto`
  from that final resolved path so colliding document creations do not share keys.
  (CMH-TOOL-18)

## [1.85.0] - 2026-07-16

### Fixed

- Updated stale shipped-doc tool paths, including the plugin README's validation,
  document-creation, and handled-comment paths, to the current `tools/<topic>/...` buckets.
  Added a docs test so future tool-layout refactors cannot leave stale README paths behind.
  (CMH-DOC-15)

## [1.82.0] - 2026-07-16

### Added

- The shipped skill now carries the MIT `LICENSE` at its root, so every copy that ships (the
  Copilot/Claude `plugin install` source subtree and the Claude Desktop skill ZIP) redistributes the
  code with its required license notice. (CMH-DOC-14)

## [1.81.0] - 2026-07-16

### Added

- Callouts now carry a non-color cue so their meaning survives grayscale printing,
  color-blindness, and screen readers: each variant (info/success/warning/danger) shows a distinct
  leading glyph, and the runtime stamps `role="note"` with a variant label. An authored leading
  `<strong>` label (or an explicit `aria-label`) is respected so the variant is not announced twice.
  (CMH-CALLOUT-03)

## [1.80.0] - 2026-07-15

### Added

- The wide-screen side navigation menu now has a filter box that searches AS a filter over the
  document: typing hides each matching entry's section (for section-wrapped content) and always its
  menu entry, Escape clears it, and following a link or comment jump to a filtered-out section reveals
  and expands it instead of scrolling to nothing. Filtered sections are hidden with `display:none`
  (comment offsets are unaffected) and are never marked current by the scroll-spy. (CMH-TOC-09)
- The side-navigation scroll-spy now marks the current section's link with
  `aria-current="location"` (kept unique and cleared from the others), so screen readers announce
  the reader's location instead of relying on the visual highlight alone. (CMH-TOC-08)

## [1.79.0] - 2026-07-15

### Changed

- The shipped plugin `README.md` now documents the dual-agent install story (both Claude Code and the
  GitHub Copilot CLI, with the marketplace-add and install commands for each), matching the SKILL.md,
  the marketplace manifests, and the site.

## [1.78.0] - 2026-07-15

### Changed

- Deck presentation chrome is cleaner and stays out of the way. The corner comment-mode toggle now
  hides at every width while the comment side panel is open (its accent colour read poorly over a
  slide, and the panel has its own header controls); hiding the panel brings it back so present mode
  stays reachable. The comments action toolbar (Copy all / Show / ...) no longer appears in a deck at
  all: only the single corner icon and the slide nav bar show. When the panel is hidden in comment
  mode the slide stage spans the full screen width again instead of leaving a reserved black bar.
  (CMH-DECK-15)
- The split-screen slide overview is easier to read and use. Its panel now has a light accent-tinted
  (red-ish) background, the Close button uses the regular accent fill, and the slide count appears
  next to the "Slide overview" title. Clicking the main deck area (outside the panel) closes the
  overview, the grid scrolls reliably when the slides overflow the viewport height, and thumbnails
  force-reveal animated slide content so each one previews the slide's final rendered state.
  (CMH-DECK-16)

## [1.77.0] - 2026-07-15

### Changed

- SKILL.md now states the plugin installs into both Claude Code and the GitHub Copilot CLI and is
  invokable from each agent's CLI and Desktop app, so the dual-agent support is visible in the
  shipped skill doc (its output was always a portable, agent-agnostic HTML file). (CMH-DOC-12)

## [1.76.0] - 2026-07-15

### Changed

- Reworked the showcase deck (`examples/deck-showcase.html`) into a light "Parchment and Amber"
  five-act pitch (pinned `data-theme="light"`, raspberry accent, amber decorative highlight on key
  title words, indigo ink body) that threads a single community-garden plan as its one running
  example instead of unrelated feature samples. Acts 1 to 3 speak to a non-technical viewer and end
  on the primary call to action, Act 4 is the engineers-only deep dive (chart, diff, code, KQL,
  triage board, checklist), and Act 5 is a room-wide close. Retitled the slides to outcome-focused
  headings and rebuilt the shipped and site copies. (CMH-DECK-SHOWCASE-01, CMH-DECK-SHOWCASE-02)
- Rethemed the deck's rich content for the light parchment slides: the chart, Mermaid diagram, code
  diff, syntax-highlighted code and KQL, drag-and-drop triage board, table headers, and layered
  checklist all stay legible and pass the strict contrast validator on the new theme.
  (CMH-DECK-08, CMH-DECK-09, CMH-DECK-10, CMH-DECK-13)

### Added

- Early install call to action: the deck now surfaces both agents' exact install commands (Copilot
  and Claude `plugin marketplace add` plus `plugin install commentable-html@urikan-ai-marketplace`)
  as code blocks on an Act 2 slide well before the close, alongside the live-demo, GitHub, and
  tutorial links, and again as the primary CTA and the closing slide - so a viewer can act within
  the first few minutes rather than only at the end. (CMH-DECK-SHOWCASE-03)

## [1.75.0] - 2026-07-15

### Added

- Section-card auto-wrap for report/plan documents - the deterministic fix for the CMH-VAL-14
  flat-section warning. `tools/authoring/wrap_sections.py` wraps each bare top-level `<h2>` block
  (the heading plus the siblings up to the next top-level `<h2>`) in
  `<section aria-labelledby="the-h2-id">` so a `report`/`plan` renders as boxed section cards
  (`#commentRoot > section`), leaving the title/lede above the cards. It is idempotent, a no-op when
  a top-level `<section>` already exists, and scopes to the `#commentRoot` element for a full
  document or the fragment root for a bare fragment. `new_document.py` (report/plan fragments) and
  `finalize.py` (full docs, gated on the kind meta) run it by default; opt out with
  `--no-wrap-sections`. (CMH-TOOL-17)

### Fixed

- `build.py` now re-stamps the version into the Claude Code manifests (`.claude-plugin/plugin.json`
  and `.claude-plugin/marketplace.json`) alongside the Copilot ones, so a version bump no longer
  leaves the Claude mirror behind (which previously required a manual bump and could fail the
  claude-manifest / version-bump guards). (CMH-TOOL-06)

## [1.74.0] - 2026-07-15

### Added

- Validator warning (non-fatal) when a report/plan/generic document has two or more top-level
  `<h2>` headings with no `<section>` wrapper, so authors restore the boxed section-card
  layout (`#commentRoot > section`). Sectioned content, single-heading docs, and slides/boards
  do not warn. (CMH-VAL-14)

## [1.73.0] - 2026-07-15

### Changed

- Deck authoring: the SKILL.md deck section now routes deck planning (not only the fill step) to
  the vendored frontend-slides design system - shortlist templates from `selection-index.json` and
  read `STYLE_PRESETS.md` / `html-template.md` / `animation-patterns.md` to choose the outline
  and theme before scaffolding. (CMH-DECK-14)

## [1.72.0] - 2026-07-15

### Added

- Claude Code compatibility. The plugin now ships a `.claude-plugin/plugin.json` alongside the
  Copilot `plugin.json`, and the repo publishes a `.claude-plugin/marketplace.json`, so
  commentable-html installs in Claude Code (`claude plugin marketplace add ...` then
  `claude plugin install commentable-html@urikan-ai-marketplace`) as well as the GitHub Copilot
  CLI. A new `scripts/validate_claude_compat.py` validates the Claude manifests structurally and,
  when the `claude` CLI is on PATH, runs `claude plugin validate --strict` on the marketplace and
  each plugin. (CMH-CLAUDE-01)

## [1.71.0] - 2026-07-15

### Changed

- Pitch: the plugin `README.md` and the site plugin page now surface two value props of the existing
  review flow. First, comments persist in the browser's `localStorage` and survive a browser restart
  or a machine reboot while you iterate, so in-progress review work is not lost (a new "Comments
  survive a restart" card in "What you get"). Second, one `Copy all` returns every comment at once,
  so the agent makes a single coordinated, coherent edit across all your notes instead of a fragile
  one-at-a-time pass (the README `Copy all` bullet and the site "Round-trip to the agent" card now
  say so). No runtime behavior changed; this is documentation and pitch copy for behavior that
  already ships.

## [1.70.0] - 2026-07-15

### Added

- A visible, human-readable version line in the shipped `SKILL.md` and `dist/README.md`, so a reader
  who opens the skill or its `dist/` folder can see which version they have without decoding
  `manifest.json`. The line (`**Version:** ` + a code span) is single-sourced from `dev/VERSION`:
  `build.py` re-stamps it and `--check` fails when either file is stale.

## [1.66.0] - 2026-07-15

### Added

- Provenance stamps and a runtime fallback banner so a document that skipped validation is visible.
  The document-producing tools stamp `commentable-html-created`, and `validate.py` / `finalize.py`
  stamp `commentable-html-validated` only on a strict-clean pass (`--no-stamp` keeps a run read-only).
  On load, the runtime shows a small dismissible amber banner when a document carries a created stamp
  but no current validated stamp - a produced-but-never-strict-validated document. A strict-validated
  document (and any document with no created stamp) shows nothing. This is a last-resort signal; the
  skill MUST always finalize and strict-validate before handoff.

## [1.65.0] - 2026-07-15

### Added

- Editable notes fields: an authored `data-cmh-note` element becomes an editable plain-text
  `<textarea>` (with a single/multi-line toggle) whose baseline is its authored text. A reviewer's
  edit is tracked as a minimal `localStorage` delta, surfaces as a per-note change card (jump +
  reset, searchable), flips the badge to Not portable, is written into the Copy-all bundle as
  `NOTES_STATE_JSON`, and is baked into the source on export. `tools/notes/notes_scaffold.py`
  generates the markup and `tools/notes/notes_apply.py` deterministically cements an edit back into
  the source HTML, so the reviewer-edit round-trip is closed and covered end to end. The global
  Clear all comments also reverts note edits. Ships a `report-notes.html` demo. See the editable
  notes-field contract reference (`references/notes-contract.md`) in the skill. Notes can be marked
  foldable (`data-cmh-note-foldable`) to render as a `+`/`-` disclosure that reveals the field on the
  line below.

## [1.64.0] - 2026-07-15

### Changed

- KQL code blocks must now be runnable or explicitly marked clusterless. A bare
  `<pre><code class="language-kusto">` block that is not framed in a `figure.cmh-kql` with a
  Run in Azure Data Explorer link is now a hard validation error unless the `<pre>` carries an
  explicit `data-cmh-kql-no-cluster` marker (declaring there is genuinely no cluster to run it on).
  Previously a bare KQL block was silently exempt, so a query could ship with no way to run it and
  no cluster. Prefer providing a real cluster; `kql_highlight.py --code-only` now stamps the
  `data-cmh-kql-no-cluster` marker for the rare clusterless case.
- The showcase deck's KQL slide now uses a full runnable figure on the public
  `help.kusto.windows.net` cluster instead of a bare highlighted block.

## [1.63.0] - 2026-07-15

### Changed

- The document-producing tools now bake syntax highlighting by default and surface validator
  warnings instead of discarding them, so a freshly created document is never raw. Previously baking
  lived only in the separate, manual `finalize.py` step, so a document that skipped finalize shipped
  with monochrome code. `new_document.py`, `retrofit.py`, and `deck_scaffold.py` all bake highlighting
  by default (opt out with `--no-highlight`); `new_document.py` and `deck_scaffold.py` print validator
  warnings, and `retrofit.py` continues to fail closed on any warning so it never writes a raw document.
- `SKILL.md` now states as a MUST that every produced HTML is finalized and strict-validated before
  handoff, since the runtime and validator both depend on that final pass.

## [1.62.0] - 2026-07-15

### Fixed

- Raw `language-html` and `language-xml` code blocks that shipped without baked highlighting now
  self-highlight at runtime like every other supported language. The runtime fallback tokenizer only
  fired for languages it knew, and the markup family (html/xml) was missing from that set, so an
  unbaked markup block rendered as plain monochrome text (css/js blocks already self-healed). The
  runtime now colors tag names, attribute-value strings, and `<!-- -->` comments for markup.

### Added

- A drift guard test asserts the runtime tokenizer knows every language the author-time highlighter
  supports, so a supported language can never again ship without runtime highlighting.

## [1.61.0] - 2026-07-15

### Changed

- The comments panel can no longer be dragged so narrow that its controls clip. The resize floor
  is now 256px (was 192px on wide screens and 144px on narrow), the empirically measured minimum at
  which the two-per-row export button labels (`Portable`, `Offline`, `Markdown`, `Plain HTML`) and
  the `Search comments` placeholder stay fully legible; the CSS `min-width` floor matches so the pane
  never renders narrower.
- Widened the comment search field by trimming its side padding and the shown/total count reserve, so
  the full `Search comments` placeholder fits even at the minimum panel width.

## [1.60.0] - 2026-07-15

### Fixed

- Validator now warns when normal `<pre>` or `<pre><code>` blocks carry `cm-skip`, which would make their code content non-commentable.
- Validator now rejects a live `#commentRoot` that still uses the documentation example key `my-doc`, while allowing the commented-out example.

## [1.59.0] - 2026-07-15

### Changed

- Reduced the always-loaded `SKILL.md` token footprint by replacing reference-duplicated guidance with concise pointers to the existing on-demand reference docs while keeping routing, validation, trust-boundary, iteration-loop, and deck invariants in the entry point.

## [1.58.0] - 2026-07-15

### Added

- Replaced the weak roadmap deck demo with a themed, in-depth Commentable HTML showcase deck and a reusable one-shot authoring prompt that prescribes the full slide outline and feature coverage.
- Added the showcase deck to the live site demo tabs so visitors can open the deck-mode review experience directly.

### Fixed

- Deck code, KQL, and diff blocks now use dark, readable surfaces, distinct syntax token colors, and readable add/delete row tints on dark deck slides.

## [1.57.0] - 2026-07-15

### Added

- Added a shipped `tools/validate/cmhval/contrast.py` WCAG contrast helper and wired
  `deck_validate.py` to fail decks whose explicit inline or same-rule CSS text/background color
  pairs fall below the configurable 4.5:1 default threshold, with diagnostics that name the
  selector or element and both colors.

### Fixed

- Hardened the contrast helper so malformed or non-finite `rgb()`/`rgba()` values are skipped
  instead of crashing, semi-transparent backgrounds are skipped, background shorthand follows
  declaration order, and colors embedded only inside `url(...)` or quoted strings do not create
  false positives.

## [1.56.0] - 2026-07-14

### Added

- Added a deck slide-overview navigator with a split-screen thumbnail grid, slide-title tooltips, click-to-jump navigation, and keyboard open, close, and select support in present and comment modes.
- Replaced the deck comment-mode text toggle with the commentable-html brand icon while preserving the Comment Mode tooltip, accessible name, and aria-pressed toggle behavior.
- Hardened the overview so thumbnail clones stay out of the tab order, preserve nested highlight markup, do not receive background deck navigation keys, and are stripped from offline exports.

## [1.55.0] - 2026-07-14

### Added

- Added the Commentable HTML brand icon to the toolbar overflow menu header as a decorative
  top-right mark that does not change the menu's keyboard order.
- Added a Help and About changelog link to the commentable-html plugin changelog.

### Changed

- Copy all now exposes a disabled, tooltip-backed state when there is no copyable review state, and
  re-enables automatically once comments are available.
- Clear now restores checklist state edits and draggable board moves to their authored baselines in
  addition to deleting comments.
- The Help and About author link now has a visible underline and accent color so it reads as a link.

## [1.54.0] - 2026-07-14

### Fixed

- Deck roadmap risk board cards can be dragged between columns inside the scaled deck stage.
- Mermaid diagrams on dark deck slides now render with high-contrast nodes, labels, and connectors.
- Deck table headers now keep readable label contrast on dark slides.

## [1.53.0] - 2026-07-14

### Changed

- Split the 1,959-line `tools/validate/validate.py` into focused, single-purpose modules under a new
  `tools/validate/checks/` package (`parsing`, `resources`, `kind`, `charts`, `checklist`,
  `highlighting`, `layer`), leaving `validate.py` as a thin entry point and orchestrator that
  re-exports each module's public names. The content-syntax checks continue to live in the sibling
  `cmhval/` package. This is a pure internal refactor with no behavior change: every existing test
  passes unchanged and the validator's output on every shipped example and template is identical.
- Decomposed the ~460-line `check_layer` into a 94-line orchestrator plus focused per-check helpers
  (region markers, content root, state JSON blocks, element ids, self-contained resources, KQL, diff
  blocks, headings, and more), so each layer invariant is its own small, testable function.

### Development

- Added CLI tests for `validate.py`'s `-h`/`--help` output and the `--` end-of-options separator
  (`ValidateMainTests`), and refreshed the `CMH-VAL-11` / `CMH-CONTENT-16` spec source pointers to the
  new module paths.


## [1.52.0] - 2026-07-14

### Changed

- Comment search now filters by the comment note text only. A query that appears solely in the
  quoted anchor content (or the section path / pin) no longer keeps a card visible, so reviewers
  filter by what they wrote rather than by the surrounding quote. A query present in the note still
  matches, and the case-insensitive substring, shown/total count, clear button, and no-results
  behaviors are unchanged.

## [1.51.0] - 2026-07-14

### Changed

- Grouped the shipped runtime tools into per-topic buckets under `tools/<topic>/` (`deck`, `kusto`,
  `checklist`, `blocks`, `authoring`, `validate`), moving the former top-level `deck/` under
  `tools/deck/`. A shared `tools/_toolpath.py` bootstrap puts the tools root and every topic
  subdirectory on `sys.path` and exposes `SKILL_ROOT`, so a tool imports its siblings and resolves
  shipped resources (`dist/`, `vendor/`) regardless of which bucket it lives in. Invocation paths in
  `SKILL.md` and the references move to `tools/<topic>/<tool>.py`; there is no runtime behavior change.

## [1.50.0] - 2026-07-14

### Added

- Content-syntax validation in `tools/validate.py`, so a document with a broken mermaid diagram
  or invalid embedded JSON now FAILS validation instead of shipping and rendering as mermaid's
  "Syntax error in text" bomb:
  - Mermaid: a `sequenceDiagram` message that a `;` splits into a dangling statement (the text
    after the `;` carries a message arrow but no `:` message) is an error. The check is calibrated
    to zero false positives against a broad, real-parser-labeled corpus - a valid multi-signal
    (`A->>B: x; C->>D: y`), an arrow inside message text, a `participant ... as "a->b"` alias, an
    `accTitle:`/`accDescr:` directive, and an inline `%%{init}%%` directive or a `%%`, single `%`,
    or `#` comment are never flagged (all confirmed against the real mermaid v11 parser). Only
    `sequenceDiagram` is deep-checked in Python; every other diagram family (flowchart, class,
    state, ...) is delegated to the repo-side real-parser oracle, so a flowchart label with a `%%`
    or a literal quote is never a false positive. An empty mermaid block (which renders as
    mermaid's "No diagram type detected" error) is also flagged.
  - Embedded JSON: an empty or invalid `<script type="application/json">` data block (whose
    `JSON.parse()` would throw at runtime, including a `NaN`/`Infinity` literal or a raw
    `</script>` that truncates the block) is an error when no chart canvas owns it; the chart
    checks continue to own chart-data JSON when a canvas is present.
- The new checks live in a `tools/cmhval/` package (`mermaid.py`, `jsonblocks.py`) so the
  validator does not grow into one giant script; `tools/validate.py` stays the entry point.

### Development

- A repo-side real-parser oracle (`dev/tools/validate_render.mjs`, never shipped) validates every
  mermaid diagram and Chart.js config in the shipped example reports with the real mermaid and
  Chart.js in a headless browser, and re-verifies the differential corpus labels, so the repo
  cannot ship a diagram or chart that renders as a syntax-error bomb and the Python checker's
  zero-false-positive guarantee is gated by the authoritative parser in CI. The oracle also flags
  an empty/whitespace-only `<pre class="mermaid">` host (which the real parser rejects as "No
  diagram type detected") rather than silently skipping it.
- If the sibling `tools/cmhval/` package cannot be imported (a broken/partial install),
  `tools/validate.py` now fails CLOSED for content it would have inspected - a mermaid block or a
  non-layer JSON data block makes validation error instead of silently passing - while a document
  with no such content still validates and `--charts-only` is unaffected.

## [1.49.0] - 2026-07-14

### Changed

- Consolidated the skill's docs assets: the review-loop diagram and the tutorial screenshots now
  live together under `docs/assets/` (previously split across `docs/images/` and
  `docs/tutorial-images/`). Shipped references in `SKILL.md`, `README.md`, `TUTORIAL.md`, and the
  file inventory point at the new location; there is no runtime behavior change.

## [1.48.0] - 2026-07-14

### Added

- Prevent code blocks from shipping without syntax highlighting, in three layers:
  - Runtime fallback: the runtime now highlights any commentable `<pre><code class="language-XXX">`
    block that shipped without highlight spans, on load, so a labelled block never renders as plain
    monochrome text even when highlighting was never baked. It is idempotent, only fires for a
    language the tokenizer knows, and keeps line numbers and comment anchoring consistent.
  - `tools/highlight_document.py`: bakes highlighting into every raw, language-labelled code block
    of a file in one pass (with a `--check` mode). `tools/finalize.py` runs it by default (opt out
    with `--no-highlight`), so the standard finalization bakes highlighting.

## [1.47.0] - 2026-07-14

### Added

- The validator now catches a code block that was labelled with a language but never highlighted.
  `tools/validate.py` warns when a `<pre><code class="language-XXX">` block declares a language the
  author-time highlighter supports (resolving aliases like `cs` to `csharp`) but carries no
  `cmh-code-*` spans, so it renders as plain monochrome text. Inline code, non-highlightable labels
  (`language-text`, `language-kusto`), and already-highlighted blocks are not flagged.

### Fixed

- The showcase demo's Python code block is now syntax-highlighted (it previously shipped as a plain
  `language-python` block, which the new validator check flags).

## [1.46.0] - 2026-07-14

### Added

- Search within comments. The comments panel now has a single search field (with a leading
  magnifier and a clear X button) that filters the comment cards to only those whose text - the
  note, the quoted content, the section path, and the pin - matches the query case-insensitively.
  A shown/total count sits beside the field, a no-results note appears when nothing matches, and
  the filter re-applies after every render so it survives adding, editing, or sorting comments.

## [1.45.0] - 2026-07-14

### Changed

- The comments panel resizes narrower. The drag/keyboard minimum width dropped to 3/5 of the former
  floor - 192px on wide screens (was 320px) and 144px on narrow screens under 700px (was 240px) - so
  the panel can take less horizontal space and leave more room for the document. The panel's CSS
  `min-width` floor was lowered to match, and the width still clamps to the viewport and persists
  across reloads.

## [1.44.0] - 2026-07-14

### Added

- Layered checklists. A `data-cmh-checklist` container turns a nested list (or a table) into
  interactive four-state item checkboxes (blank / check / cross / question) drawn with inline-SVG
  icons. A branch item aggregates over its direct children (all-same shows that state, any
  disagreement shows a neutral mixed marker), and clicking a branch propagates its next state to
  every descendant leaf. Item labels stay ordinary commentable content; only the injected icon
  control is `cm-skip`. Hierarchy comes from DOM nesting for lists, or an explicit `data-cmh-parent`
  reference for tables, which cannot nest rows and may be sorted.
- Minimal checklist persistence. Only leaves whose state differs from their authored `data-cmh-state`
  baseline are stored, as one-character codes under `COMMENT_KEY + "::cl"`; returning a leaf to its
  baseline prunes its entry, so a large checklist with a few edits costs a few bytes.
- Per-list checklist change card. The sidebar renders one non-comment card per checklist with
  changes, placed by document order, with a jump button and a Reset button that reverts that
  checklist to its authored state. Copy all gains a `## Checklist "<id>"` section plus a
  machine-readable `CHECKLIST_STATE_JSON` line, an unsaved change flips the badge to Not portable,
  and every export bakes the current states into `data-cmh-state`. A checklist that loads with a
  persisted change opens the sidebar so the card is seen.
- Two checklist tools. `tools/checklist_scaffold.py` generates list or table markup with stable ids
  from an indented outline, and `tools/checklist_apply.py` cements the reviewer's states from a
  Copy-all bundle (or `--state-json`) back into the source HTML. `validate.py` gains checklist checks
  (duplicate ids, invalid tokens, empty lists, unresolved parents) that a checklist-free document
  ignores. See the bundled `references/checklist-contract.md` for the authoring contract.
- A shipped demo report `examples/report-checklist.html` (Release readiness review) that showcases both
  checklist shapes - a nested-list sign-off checklist and a sortable-table component audit linked by
  `data-cmh-parent` - with its companion authoring prompt `examples/prompt-checklist.md`.

## [1.43.0] - 2026-07-14

### Changed

- Clarify the README privacy wording: the document and comments are "never uploaded, transmitted, or
  sent to any external service - not to us, and not to anyone else", dropping the confusing "not to
  the agent" (you do paste the Copy all bundle to your agent yourself, so listing the agent among the
  never-sent destinations read as contradictory).

## [1.40.0] - 2026-07-14

### Added

- A "Privacy and compliance" section in the packaged README and a "Private by design" section on
  the plugin site page (linked from the nav), emphasizing that the document and every comment stay
  local - in the browser's `localStorage` or embedded in your own HTML file - are never uploaded or
  sent to any external service, and that only the Mermaid/Chart.js rendering libraries load from a
  CDN (not your data) while Export Offline strips even that for air-gapped, sensitive, or regulated
  use.

## [1.39.0] - 2026-07-14

### Changed

- The Help & About panel now links the author's name, "Uri Kanonov", to
  `https://github.com/urikanonov` (opens in a new tab), reusing the existing brand-link style.
- Help panel text now names the triage board's `Reset moves` button and the board-moves comment
  card's `Reset changes` button, and refers to the Help toggle by its exact on-screen label,
  `Help & About`, instead of the shorthand `Help`.

## [1.38.0] - 2026-07-14

### Added

- A shipped example deck `examples/deck-roadmap.html` (Autumn Roadmap Review) plus its companion
  authoring prompt `examples/prompt-roadmap.md`. The deck is a `kind=slides` document with a
  fixed 1920x1080 stage of six commentable slides (title, current-state stats, themes table,
  mermaid architecture diagram, three-column risk board, and the ask), giving reviewers a real
  deck target for the same commenting workflow the report demos exercise.
- `build.py`'s example pipeline now covers `deck-*.html` sources alongside `report-*.html`, so a
  deck source in `dev/examples-src/` regenerates its shipped copy under `pkg/**/examples/` and
  `build.py --check` catches a hand-edit or a stale/clobbered deck example. The site demos list
  syncs the deck under `site/commentable-html/demo/` next to the report demos.

## [1.37.0] - 2026-07-14

### Fixed

- The diff-line Add Comment hover button (`#diffAddBtn`) is now vertically centered on the hovered
  row, so moving the pointer to click no longer jumps to the line above.

### Added

- Commentable code blocks, including KQL query blocks, now show per-line numbers in a
  `.cmh-code-gutter` overlay via CSS-generated counters. The numbers are visible in the UI but
  excluded from text selection and clipboard output, including each block's Copy button.

## [1.36.0] - 2026-07-14

### Added

- The `cmh` shorthand now discovers the skill: it is a `plugin.json` and marketplace keyword, and
  the `SKILL.md` front-matter discovery description ends with an explicit `Also triggers on the
  shorthand cmh.` clause, so typing `cmh` auto-triggers the skill and matches it in marketplace
  search.

## [1.35.0] - 2026-07-14

### Added

- Triage-board (and any `[data-cm-widget][data-cm-draggable]` widget) Reset controls. A moved board
  now grows a runtime-injected "Reset moves" button in its corner whenever its layout differs from
  the load-time baseline; clicking it returns every card to its original slot and order, and the
  button disappears once there are no moves. Static (non-draggable) widgets never get the button.
- Per-widget layout-change state cards. The sidebar now renders one "Layout change" card per widget
  that has moves, each with a jump button that scrolls to and flashes that board and a "Reset
  changes" button that restores only that widget. Each card mirrors a regular comment card's shape:
  an `in: <board>` title (the widget aria-label, else its name) and a meta line showing the
  first-change datetime, alongside the existing explanatory note.

### Fixed

- A chart caption sitting directly below a tall `cm-skip` chart is now commentable. The desktop
  `mouseup` handler evaluates the selection before bailing on a `cm-skip` target, so selecting a
  short caption still offers Add Comment even when the pointer releases over the adjacent chart
  canvas.
- The runtime footer no longer spans wider than the content column. Its box now aligns to the
  `#commentRoot` content width in both the normal and the sidebar-open layout.

## [1.34.0] - 2026-07-13

### Changed

- The shipped example reports (`examples/report-*.html`) are now pure build artifacts assembled
  from an independent content source in `dev/examples-src/`. `build.py --check` compares each
  shipped example to a fresh assembly, so a hand-edit or a stale/clobbered example - of its content
  as well as its layer - now fails the build instead of comparing equal to itself. Edit demo content
  in `dev/examples-src/`, not in the shipped file.

### Accessibility

- The comments-panel toggle and the overflow-menu trigger now declare the element they control with
  `aria-controls` (`#sidebar` and `#toolbarMenu`), so assistive technology can associate each toggle
  with its target.

## [1.33.0] - 2026-07-13

### Fixed

- Export as Portable no longer corrupts a comment whose body contains `$&`, `$1`, `` $` ``, `$'`, or
  `$$`: the saved-HTML builder now uses a function replacer so `String.replace` cannot expand those
  `$`-patterns from the comment text.
- Export as Plain now recognizes region markers with any number of `=` fill characters (matching the
  validator's grammar) when stripping the comment-UI, embedded-comments, and script regions, and the
  post-export leak guard now matches `id="handledCommentIds"` / `id="embeddedComments"` regardless of
  quote style, so a Plain export cannot silently ship comment data.
- The strict validator now rejects a report whose top-level lede exists but is empty: a document must
  carry a non-empty top-level `<h1>` title, not just the lede wrapper class.

### Added

- The plugin site page now showcases the commentable-decks capability in the "What you get" section.

### Changed

- The deck authoring guide runs the deck validator with `--strict`, and the tutorial's Show/Hide
  wording matches the actual toolbar behavior.

## [1.32.0] - 2026-07-13

### Added

- Commentable decks: a built-in deck capability powered by a curated, pristine subset of the frontend-slides skill (MIT, (c) 2025 Zara Zhang) vendored under `vendor/frontend-slides/`. The Vercel deploy script and the PDF-export script are excluded, and a required CI gate (`dev/tools/check_vendor.py` plus a SHA-256 `MANIFEST.sha256`) fails on any unknown, changed, removed, or reintroduced file. See `vendor/frontend-slides/UPSTREAM.md` and `dev/frontend-slides-upstream-sync.md`.
- Author-time deck tools under `deck/`: `deck_scaffold.py` builds a create-only, commentable-native fixed-stage deck with legible presentation defaults (light slide text and presentation-scale typography on the dark stage, overridable by a design pass) - each slide carries a stable `data-slide-id`, the inline editor and localStorage autosave are stripped, and fonts are self-hosted - and fails closed on the deck contract before writing; `pptx_to_fragment.py` HTML-escapes extracted slide text, schema-validates the input, vets every image path as local-relative, and fails closed without `python-pptx` (speaker notes are not supported); `deck_validate.py` enforces the deck contract fail-closed using an HTML parser (robust to solidus, entity-encoded, unquoted, and SVG bypasses), rejecting remote fonts/media/CSS, active content, and `javascript:`/`../` URLs while allowing external hyperlinks. The runtime interface both sides build against is documented in `references/deck-contract.md`.
- A "Deck capability (frontend-slides)" flow in `SKILL.md`: detect a presentation request and confirm, optionally convert a `.pptx` (preferring the Anthropic `pptx` skill when installed, else the local extractor), scaffold, fill, validate, then comment on the live deck and iterate in place. Mermaid and Chart are supported; Export Offline produces the network-silent shareable artifact.
- A runtime deck profile in the commentable-html layer, activated only by `data-cmh-mode="deck"` on the real content root: it exposes a `window.__cmhDeck` controller, scales the fixed 1920x1080 stage (refit via a `ResizeObserver`), and replaces the flow-document chrome (heading anchors, collapsible carets, side TOC, footer, scroll progress) with a full-screen presentation - a **present mode** that hides the comment sidebar/toolbar plus a slide-oriented control bar (Prev, a live `N / total` slide counter, Next, with WCAG-2.5.3 aria-labels and boundary-disabled buttons) and keyboard / id navigation (guarded against out-of-range and editable-target keypresses). A **comment mode** toggle reveals the sidebar, insets and force-reveals the stage, and gates the navigation keys; a comment card jumps to (activates) its owning slide with highlights restoring on hidden slides. Non-deck documents are unaffected.
- Dev tooling: `dev/tools/audit.mjs`, an AI-driven UX audit harness that tours any commentable HTML across viewports and colour schemes and emits screenshots plus machine observations for one or many agents to review (see `dev/AUDIT.md`). Not shipped.

### Changed

- The mermaid CDN import is now gated on the presence of a `pre.mermaid` / `div.mermaid` element, so a diagram-free document (including a deck) makes no external network request at all. A document that contains a diagram still loads and renders mermaid.

## [1.31.0] - 2026-07-13

### Changed

- In the sidebar's narrow layout the export buttons now pack two per row (Portable | Offline, then Markdown | Plain HTML) instead of one full-width button per row, so the actions take less vertical space and are quicker to scan. The Clear button keeps its own full-width row so the destructive action stays visually apart.

## [1.30.0] - 2026-07-13

### Fixed

- Hardening pass from a multi-model audit of the day's merged changes. Six latent robustness and correctness defects are fixed, each covered by a test that reproduces the defect before the fix. No shipped example, template, or fixture changed behavior; they all still validate clean.
- `tools/validate.py` KQL run-link rule (`CMH-KQL-07`) now treats a framed `figure.cmh-kql` whose `cmh-kql-run` link points anywhere other than `https://dataexplorer.azure.com/` as a hard error instead of a warning. The href is HTML-entity decoded and URL-parsed (not substring-matched), so a `javascript:`, `data:`, non-ADX, or look-alike-host link fails validation. The "has a run link" check now looks for a real `<a>` element carrying the `cmh-kql-run` class token, so a figure whose query text merely mentions `cmh-kql-run` no longer passes as if it had a link. A bare `<pre>` KQL block stays exempt.
- `tools/validate.py` transient-body-class guard (`CMH-VAL-10`) now inspects the REAL parsed `<body>` element instead of the first raw `<body ...>` token in the file, so a decoy `<body class="sidebar-open">` inside a `<head>` script or comment can no longer hide a dirty real body or trigger a false positive.
- `tools/validate.py` report/plan title rule (`CMH-KIND-01`) now requires a TOP-LEVEL `<h1>` (a direct child of `#commentRoot`, or a lede-wrapped `<header class="cmh-lede"><h1>`), matching `new_document.py`. An `<h1>` nested only inside a deeper `<section>` no longer satisfies the rule.
- `assets/commentable-html.js` document-comment context menu (`CMH-DOCCMT-02`) no longer vanishes on a macOS-style Ctrl-click: the `mouseup` cleanup is suppressed for any context-menu gesture (`button === 2 || ctrlKey`), not right-click alone.
- `assets/commentable-html.js` export body-class normalizer (`CMH-EXP-09`) now operates only on the first `<body>` open tag, handles double-quoted, single-quoted, and unquoted class values, matches whole class tokens (a superstring like `x-sidebar-open` is preserved), and removes an emptied class attribute, so it can no longer mutate a `<body class=...>` literal that appears later in page content or a script.
- `tools/upgrade.py` and `tools/retrofit.py` kind-meta handling (`CMH-KIND-02`, `CMH-KIND-03`) now detect an existing `commentable-html-kind` meta by parsing head metadata order-independently (including a non-canonical `content`/`name` attribute order). `upgrade.py` no longer appends a duplicate meta to a document that already declares a kind, and `retrofit.py --kind` replaces an existing kind meta in place instead of appending a second one.

### Changed

- `references/validation.md` error list now documents the mandatory/unknown `commentable-html-kind` meta (with the report/plan top-level `<h1>` sub-rule) and the transient body-state class guard, matching the authoritative error list `SKILL.md` points to.

## [1.29.0] - 2026-07-13

### Fixed

- The template and shipped example reports no longer bake the transient runtime `sidebar-open` body class into `<body>`. `sidebar-open` is a UI-state class the layer toggles on `document.body` as the panel opens and closes; hardcoding it in `assets/template.shell.html` meant every generated document, both `dist/` templates, and all four `examples/report-*.html` shipped with `<body class="sidebar-open">`, which rendered a fresh document full width with an empty reserved right gutter (the `body.sidebar-open .app` layout rule) even when the sidebar panel is not shown. The template and examples now ship a plain `<body>`, and the runtime derives the sidebar state on load (open when the document has restored comments, closed otherwise). Where 1.28.0 stripped the class on export, this removes it at the source.

### Added

- `tools/validate.py` now errors when a document's `<body>` open tag carries a transient runtime UI-state class (`sidebar-open`, `cm-sidebar-resizing`, or `cm-widget-dragging`), so a persisted transient state can never ship. The check inspects only the `<body>` open tag, so a legitimate CSS/JS reference to `sidebar-open` is not flagged. New specs `CMH-BUILD-06` (no shipped document bakes the class) and `CMH-VAL-10` (the validator guard), covered by `dev/tests/test_build.py`, `dev/tests/test_new_document.py`, `dev/tests/test_examples.py`, and `dev/tests/test_validate.py`.

## [1.28.0] - 2026-07-13

### Fixed

- Exports no longer bake transient runtime body-state classes into the saved file. Every export path (Save, Export as Portable, Export Offline, and Export to Plain HTML) now strips `sidebar-open`, `cm-sidebar-resizing`, and `cm-widget-dragging` from the exported `<body>` open tag, so a stale or open-sidebar source can no longer persist that state and propagate it across re-exports. A stuck `sidebar-open` made the document render full width with an empty right gutter (the `body.sidebar-open .app` layout rule) for a sidebar that is not shown. Non-transient body classes are preserved, and the live layer re-derives the sidebar state on load. The normalization is centralized in `_getBaseHtml()` (covering the on-disk and `file://` snapshot bases) and shared with the Plain export via a new `_stripTransientBodyClasses()` helper. New spec `CMH-EXP-09` and `dev/tests/54-export-body-normalize.spec.js` cover all four export paths.

## [1.27.0] - 2026-07-13

### Added

- Every shipped example report now has a companion example-prompt file. Added `examples/prompt-triage.md` and `examples/prompt-metrics.md` (matching the existing `prompt-community-garden.md` and `prompt-taxi.md` format) so all four examples document the one-paragraph prompt that generates them.
- Full interaction coverage for the incident triage board and commentable visuals matrix examples: a new `dev/tests/53-more-examples.spec.js` exercises both reports over http with prose commenting, widget/part commenting, UI-control clicks, and a seeded randomized monkey pass, asserting no uncaught page errors and comment persistence across reload. Each of the four shipped examples is now covered by validation, monkey, commenting, and clicking.
- New spec guards: `CMH-DEMO-02` (every report has a companion prompt with the standard headings and a non-empty blockquote) and `CMH-DEMO-03` (each example is exercised by the interaction/monkey suite), plus an example-scoped assertion under `CMH-BUILD-05` that no shipped example carries the removed "TEMPLATE / DEMO" header phrases.

## [1.26.0] - 2026-07-13

### Changed

- The "Run in Azure Data Explorer" deep link is now mandatory on a framed KQL figure. `tools/validate.py` rejects a `figure.cmh-kql` that has no `cmh-kql-run` link as a hard error (non-zero exit in the default, non-strict mode) instead of a warning, so a framed KQL block can never ship without the reader's one-click path into Azure Data Explorer. Build the link with `tools/kusto_link.py`. A purely illustrative query with no real cluster/database should use a plain `<pre>` code block, which remains exempt from the rule.

## [1.25.0] - 2026-07-13

### Changed

- Generated documents no longer carry the leading "Commentable HTML - TEMPLATE / DEMO" documentation comment. That guidance duplicated the skill references and mislabeled real reports as a template or demo, so every shipped report and generated document is now leaner and cleaner without it.

## [1.24.0] - 2026-07-13

### Changed

- Aligned the skill with Anthropic's Agent Skills authoring guidelines (documentation only, no runtime or tool behavior change). Rewrote the `SKILL.md` front-matter description into a what-plus-when discovery string with an explicit `Use when ...` trigger clause scoped to HTML artifacts, linked `references/forward-compatible-layout.md` directly from `SKILL.md` so every reference is one level deep, added a `## Contents` table of contents to each reference longer than 100 lines (charts, exports, document-layout, comment-data-shape, retrofitting), documented the Markdown-to-HTML reviewer path, removed legacy UI-label and past-version wording from the Charts and Exports references, and removed a time-relative phrase from the Interaction-model reference. The repository `README.md` plugin row was aligned with the new description.
- Added spec-covered guards for the above (`CMH-DOC-05` reference tables of contents, `CMH-DOC-06` front-matter description, `CMH-DOC-07` direct reference links, `CMH-DOC-08` SKILL/marketplace description consistency), each validated by a covering test in `dev/tests/test_docs_diagrams.py`.
- Deferred: trimming the `SKILL.md` body toward Anthropic's ~5k-token soft cap is intentionally left to a focused follow-up, because the body carries pinned generation contracts (`CMH-DOC-02`/`CMH-DOC-03`) that a de-duplication pass should not churn in the same change.

## [1.23.0] - 2026-07-13

### Fixed

- A real desktop right-click on empty document space no longer flashes the document-comment menu open and then hides it: the right-button `mouseup` no longer runs the text-selection cleanup that queued a `hideMenu()` clobbering the just-opened menu.

### Changed

- The sidebar Copy all button is larger and bolder so the most-used action is easier to find and click.

## [1.22.0] - 2026-07-13

### Added

- Documents now declare their kind in a mandatory `<meta name="commentable-html-kind">` (report, plan, slides, board, or generic). The validator requires it and enforces per-type rules: report and plan must carry a top-level `<h1>` title, while slides, board, and generic do not.
- `new_document.py` and `retrofit.py` require `--kind` and stamp the meta; report and plan auto-add a title from `--label` when the fragment has none, while slides and board do not.

### Changed

- `upgrade.py` now adds a default `generic` kind meta to a document that predates kinds, so upgrading an older document produces one that still validates.

## [1.21.0] - 2026-07-13

### Added

- Added `tools/retrofit.py` to deterministically inject the commentable layer into existing unlayered HTML with validation-before-write, root selection, Portable output, companion-asset options, and host chrome skip selectors.

### Changed

- Trimmed `SKILL.md` by moving runtime UI, interaction, NonPortable, network, and manual retrofit details into existing references while keeping generation-time routing, caveats, and commands inline.

## [1.20.0] - 2026-07-12

### Fixed

- Offline export now blocks form submissions in CSP, removes remote form targets, keeps benign inline scripts with non-network dynamic import comments, and preserves custom canvas renderers that are not chart snapshots.
- Strict offline validation now requires the restrictive CSP and rejects network form targets, meta refresh redirects, and network CSS `url(...)` values in style blocks or inline styles.
- Offline validation now ignores non-fetching remote links such as canonical and alternate metadata while still blocking fetching link relations.
- Region marker guards in validation, upgrade, build, and runtime export now count only comment-delimited infra markers, so marker text inside prose or code blocks no longer causes duplicate-region failures.

## [1.19.0] - 2026-07-12

### Fixed

- Offline export now adds a zero-network CSP, removes event-handler attributes, strips same-origin absolute media and additional preload/media/SVG/CSS/refresh egress vectors, and validates offline documents with no Chart.js CDN exemption.
- Region replacement tools and runtime export slicers now reject duplicate BEGIN or END markers instead of risking content loss.
- Validator hardening now rejects protocol-relative and non-file companion refs, descriptor id decoys, and commented `data-id="commentRoot"` false positives.
- Save, Portable, and Offline exports now filter handled comments so resolved feedback cannot reappear in exported embedded comment JSON.
- Markdown export now summarizes offline chart snapshots by label instead of embedding base64 chart images.

## [1.18.0] - 2026-07-12

### Added

- Documented widget drag opt-in, the Offline badge state, Export Offline, and when to use NonPortable, Portable, or Offline outputs.

### Fixed

- Exporting after widget moves now refreshes plain-text comment offsets against the exported widget layout, so comments near moved cards reopen on the intended text.
- Floating chart, mermaid, diff, widget, and text-comment bubbles now respect horizontally clipped rich-content containers instead of drifting outside scrolled charts, tables, diagrams, or raw diffs.
- Document-type badges now announce Portable, Offline, and Not portable state changes through a polite live region and expose the reason through `aria-label`.
- The dependency cooldown gate now diffs lockfiles by package name and version, uses lockfile entry names for aliases, discovers package-lock files dynamically, deduplicates registry lookups by package name, applies a global deadline, and warns when changed non-registry dependencies are not cooldown-checked.
- The forward-compatible layout reference now clarifies that `validate.py --strict` validates the current contract only and legacy pre-1.15 documents must be regenerated or upgraded before validation.

## [1.17.0] - 2026-07-12

### Fixed

- Offline export now preserves embedded comment data scripts even when comment text mentions remote imports, strips bare remote module imports, neutralizes remote media attributes, and keeps descriptor decoys from stealing the real offline mode update.
- Widget drag-and-drop now treats drops onto nested slots inside the dragged part as no-ops, always clears drag state, preserves click-to-comment behavior below the drag threshold, avoids reporting origin-slot no-ops as moves, and saves moved widget layouts into Portable exports.
- Example regeneration now rejects duplicate region BEGIN markers instead of silently slicing through authored content.
- The dependency cooldown gate now fails open when npm registry packuments have a null or malformed `time` map.
- The dependency cooldown gate and related test helpers now emit stable sorted failure output.
- The mobile rich-content test now proves genuinely wide chart or mermaid blocks can scroll horizontally instead of relying on tautological scroll metrics.
- Plain export and layer retargeting now ignore `data-id="commentableHtmlLayer"` decoys when locating the real descriptor.

## [1.16.0] - 2026-07-12

### Added

- Offline exports now declare descriptor mode `offline`, reopen with an Offline badge, preserve that mode when
  edited, and validate offline chart snapshots as first-class portable artifacts.
- Triage board cards can opt in to mouse drag-and-drop with `data-cm-draggable`, and moved cards are copied as
  widget layout changes.

### Fixed

- Mermaid diagrams and chart figures now stay inside narrow mobile viewports by scrolling wide rich content inside
  their own blocks.
- Shipped prose now refers to the user-facing skill as Commentable HTML while preserving the `commentable-html`
  identifier in commands, paths, and code.

## [1.15.0] - 2026-07-12

### Added

- Generated documents now publish a machine-readable `commentableHtmlLayer` descriptor that records the
  layer version, output mode, and infra region marker names in document order.
- `#commentRoot` now carries `data-cmh-content-root`, giving future tooling a stable hook for content roots.
- The forward-compatible content/infra layout contract is documented in `references/forward-compatible-layout.md`.

## [1.14.0] - 2026-07-12

### Changed

- Top-level prose is no longer width-capped. Ordinary paragraphs (and the lede) now fill the full
  content column, the same width as tables, figures, code, and callouts, so prose no longer renders
  narrow next to full-width content in wide reports. The previous 72ch readable-measure cap is removed.

## [1.13.0] - 2026-07-12

### Added

- Added two shipped live demo reports: an incident triage board with commentable widget columns and cards, and a
  visuals matrix covering flowchart, sequence, gantt, state, class, ER, and pie mermaid diagrams, four Chart.js
  chart kinds, a code-review diff, a KQL block, and an SVG figure.
- Export to Markdown now preserves `data-cm-widget` boards as a widget note plus a GFM table, so the triage board
  survives Markdown export instead of being skipped as `cm-skip` chrome.

## [1.12.0] - 2026-07-12

### Added

- Added **Export Offline**, which builds a Portable export with current comments, snapshots rendered
  mermaid diagrams as inline SVG, snapshots chart canvases as PNG data images, removes remote rich-content
  loaders, and produces a strict-valid zero-network HTML handoff.

## [1.9.1] - 2026-07-12

### Added

- The shipped plugin `README.md` and `SKILL.md` now explain why commentable-html beats planning in chat, a
  Markdown file, or plain HTML - a medium-comparison table plus a reference to Anthropic's "unreasonable
  effectiveness of HTML" blog post - so the motivation matches the project website.

## [1.9.0] - 2026-07-12

### Added

- `new_document.py` now defaults NonPortable companion references to absolute `file://` URLs that point at
  the installed skill `dist/`, so the generated HTML can move anywhere on the same machine without losing
  its CSS/JS. Use `--assets-relative` to restore the old relative-path behavior for a movable folder bundle.
- The NonPortable asset banner now has an accessible `Dismiss` button. A dismissed version warning stays
  hidden across reloads for that document key and page/runtime version pair.
- The SKILL.md documents the page/runtime compatibility contract: same-major newer runtimes can open older
  same-major pages without warning, and breaking page/runtime changes require a major version bump.

### Changed

- The NonPortable version handshake is now semver-aware. Same-major older pages no longer show a scary
  mismatch banner after a safe skill update, newer same-major pages show a soft update notice, and
  different-major pages show the incompatible-runtime warning.
- `validate.py` treats only `http://` and `https://` companion refs as remote/CDN URLs. Local `file://` refs
  and absolute filesystem paths are accepted, while plain absolute filesystem paths still warn that they are
  local-only.

## [1.8.0] - 2026-07-12

### Added

- Two mermaid diagrams in `references/exports.md` (linked from the SKILL.md Output modes section)
  showing what is bundled in the file versus fetched from where: Portable inlines the layer CSS/JS,
  NonPortable loads the `commentable-html.{css,js,assets.js}` companions from the skill `dist/`, and both
  keep the plan content and comments inline while fetching optional mermaid/Chart.js from a CDN.
- The `analysis`, `plan`, and `report` keywords, and the "drastically shortens the AI planning and
  iteration loop" framing in the SKILL.md intro and the plugin READMEs. The marketplace category is now
  `planning and analysis`.
- The brand mark now links to the project site
  (`https://urikanonov.github.io/ai-marketplace/commentable-html/`) in a new tab, in the footer (icon plus
  versioned name) and on the sidebar meta-row brand icon. The link is chrome, so it never leaks into a Plain
  HTML export.
- The Help modal title now includes the running layer version (`Commentable HTML v<version> - Help`).
- Each overflow (`...`) menu item (Show, Export as Portable, Export to Plain HTML, Export to Markdown,
  Help & About) now carries a leading decorative icon matching the chrome icon style.

### Changed

- `Export to Markdown` is now download-only: it downloads the `.md` file and no longer writes the clipboard.
  The toast, Help topic, button tooltips, SKILL.md, and `references/exports.md` were updated to drop the
  clipboard claim.

### Fixed

- On touch / coarse-pointer devices the "Add Comment" popup now appears when a text selection settles.
  Selecting text on a phone drags the native handles and never fires `mouseup`, so the popup previously
  never showed; a debounced `selectionchange` now raises the same popup (and hides it when the selection
  collapses). Desktop mouse behavior is unchanged.

## [1.7.0] - 2026-07-11

### Fixed

- Export on `file://` no longer drops content authored after the layer script. The export base is now
  captured from the fully parsed DOM at export time (then re-stripped of runtime artifacts) instead of a
  snapshot taken before late content (for example a `chart_block` chart placed after the layer) was parsed.
- `Export as Portable/Standalone` finds the embedded-comments script regardless of its attribute order, and
  aborts with a clear error when the companion assets version does not match the running runtime.
- `Export to Markdown` now serializes `<strong>`/`<em>`/`<a>`/`<code>`/`<img>` that are direct children of a
  list item, and its URL allowlist keeps only image data URLs (a bare `data:` destination is neutralized
  while `data:image` is preserved).
- Image/canvas comment highlights clear and flash correctly on `<canvas>` widgets, not just `<img>`.
- Duplicate persisted comment ids are de-duplicated on load so a corrupted store cannot render twin cards.
- `generate_toc.py` and `validate.py` reset the `#commentRoot` scope on the root's closing tag, so a heading
  or cross-reference in a later footer or sibling container is no longer collected into the TOC or validated
  as document content.
- `validate.py` accepts cache-busted companion references, stripping a `?query`/`#fragment` before the
  `.js`/`.css` suffix and the on-disk existence check.
- `diff_block.py` preserves a file-final-newline-only difference and emits the standard
  `\ No newline at end of file` marker instead of silently dropping it.
- `new_document.py` refuses NonPortable output to stdout unless `--assets-href` is given, because bare
  companion names written to a stream are unreachable; its `--key-from-source` help no longer claims a
  `--label` fallback.
- `chart_block.py` adds its own tools directory to `sys.path` on import so the sibling `validate` module is
  importable and self-validation is never silently skipped.
- `--help`/`-h` now exits 0 with usage on every shipped tool (`validate.py`, `kql_highlight.py`,
  `kusto_link.py`, `mark_handled.py`, and the rest), instead of treating the flag as a filename.
- `new_document.py --key auto` derives the comment key from the output/source path identity rather than the
  label, so two documents that share a title no longer collide and leak comments across each other.
- The lede/intro block is no longer clamped by the 72ch prose measure, so it renders at the section width.
- The confirm dialog always traps Tab and pulls escaped focus back to Cancel; Escape closing the toolbar
  overflow menu or the add-comment menu restores focus and no longer discards an open composer draft; the
  side-TOC highlights the last section once the page is fully scrolled.

### Added

- Headings are keyboard-focusable with a visible focus style and Enter/Space activation for the deep-link /
  add-comment affordance, matching the mouse-only behavior.
- Generated documents carry a visible themed document title (`#commentRoot > h1`); `new_document.py` adds a
  visible `<h1>` from `--label` unless the fragment already has one or `--no-title` is passed.
- The trust boundary is documented in `SKILL.md` and `new_document.py --help`: authored content is trusted
  HTML and is not sanitized; callers must sanitize untrusted host HTML before wrapping it.
- A `new_document.py` quickstart example in the plugin README; `retrofitting.md` documents the
  `window.__cmh*` / `__commentable*` introspection globals.

### Changed

- `validate.py` requires `headingAddBtn`, `widgetAddBtn`, and `menuDocComment`, and its stale version note
  now points at the correct removal version.
- `upgrade.py` matches its replace regions by exact begin/end markers; the composer placeholder documents the
  `Ctrl/Cmd+Enter` save shortcut; `kusto_link.py` and the dev tests use public/generic cluster, path, and
  database names in place of internal ones.
- `build.py` now regenerates the example reports' layer regions and version stamps from the freshly built
  dist and covers them in `--check`.
- Both export modes download `<stem>-portable.html`; the NonPortable "Export as Portable" no longer emits a
  `<stem>.standalone.html` filename.

## [1.6.1] - 2026-07-11

### Added

- The Help `Getting started` topic now embeds the review-loop diagram (the agent-to-you-and-back
  loop) beneath the four steps, themed with the framework's light/dark variables so it follows the
  active theme.
- A `Website and live demo` link in the Help About block, pointing at the plugin's GitHub Pages page.

### Changed

- Merged the `The review workflow` and `Getting started` help topics into a single, default-open
  `Getting started` topic, removing the overlap between them.
- Reworded the `Self-contained and privacy` help topic: comments are stored in this browser's
  `localStorage` (private, never uploaded, no account), and the review layer travels inside the file
  only in Portable mode - a Not portable file references small companion resources. It no longer
  implies the layer is always bundled into the file.

## [1.6.0] - 2026-07-11

### Changed

- Adopted mermaid 11: the shipped page templates (`dist/PORTABLE.html`, `dist/NONPORTABLE.html`) and the
  example reports now load `mermaid@11.16.0` from the CDN, and the commenting layer is verified to render,
  anchor, and comment on mermaid 11 diagrams (full Playwright suite green against mermaid 11). This rode in
  on a dev/test-only dependency bump (mermaid 11.16.0, chart.js 4.5.1, adm-zip 0.6.0); none of those dev
  dependencies ship in the plugin.

## [1.5.1] - 2026-07-11

### Changed

- Polished the review-loop diagram (`docs/images/review-loop.svg` and its site twin): the step labels use
  consistent casing ("1. Generates HTML", "2. Comment Inline"), and the "reload and repeat" caption became
  a fourth curved arrow from the AI agent back to you, so the loop reads as a closed cycle.

## [1.5.0] - 2026-07-11

### Added

- Commentable widgets and SVG nodes. A generic opt-in contract (`data-cm-widget`, `data-cm-part`,
  optional `data-cm-part-label`, and `data-cm-slot`) makes individual parts of an interactive widget
  or a labeled SVG `<g>` node commentable, with a hover/keyboard Add Comment affordance and a
  `widget` anchor type that restores across reloads and exports.
- Widget layout-change tracking. When parts sit in `data-cm-slot` containers, drag/drop moves are
  detected against the load-time baseline and surfaced as a synthetic sidebar card and a "Widget
  layout changes" section in the Copy-all bundle; the document is flagged Not portable until it is
  re-exported.
- Document-wide comments. Right-clicking empty space adds an unanchored, whole-document comment
  (`document` anchor type) that carries no highlight and copies as a document-wide anchor.
- Export to Markdown. A new sidebar and overflow-menu action copies the document content to the
  clipboard and downloads a `.md` file via a deterministic, block-by-block conversion (headings,
  lists, GFM tables, fenced code / diff / mermaid / kusto, callouts as GitHub alerts, charts and
  SVG figures as caption notes), with the current comments appended as a section. Untrusted text,
  attributes, and comment notes are escaped so the exported Markdown cannot inject raw HTML or
  forge document structure.

### Changed

- The overflow-menu portability badge now shares the sidebar badge's coloring and tooltip
  (via `data-doc-type`), so both convey the same Portable / Not portable semantics.
- Authoring guidance: content-conventions now covers shaping content in real layouts, an
  anti-default-look taste checklist, a readable prose measure (top-level paragraphs are capped while
  tables, figures, and code keep full width), and mapping a product's design tokens onto the
  `--cp-*` variables.

## [1.4.0] - 2026-07-11

### Added

- Help & About: a "Tips and shortcuts" topic for power users (right-click to comment, re-select the same
  text to reopen a comment, multiple and draggable composers, sort back to document order, the Expand and
  Collapse controls, the diff Syntax toggle, and the keyboard shortcuts), plus "Request a feature" and
  "Contribute" links in the About block alongside the existing source and issue links.
- A review-loop diagram (`docs/images/review-loop.svg`) embedded in a new "Review workflow" section of the
  plugin README, showing the agent-to-you-and-back loop and naming the self, peer, and reviewer variants.

### Changed

- Help & About now orients a first-time reviewer. The review-workflow topic points a recipient who was
  sent a file straight to leaving a comment (no agent or account needed), the "Getting started" topic is
  retitled for reviewing a shared file, and the search box suggests "shortcuts".
- `docs/TUTORIAL.md` gained a short "you were sent a file to review" quick start and a pointer to the new
  Tips and shortcuts help topic.

## [1.3.1] - 2026-07-11

### Fixed

- Single-quoted string styles now require their closing quote, so a lone `'` in valid code (a Rust
  lifetime like `&'static str`, an apostrophe like `don't`, or a C++ digit separator `1'000`) is no
  longer swallowed as a string to the end of the line. Double-quoted and backtick strings still
  highlight when unterminated, and string scanning stays linear time.
- CSS highlighting now treats only the CSS-wide keywords (`auto`, `none`, `inherit`, `initial`,
  `unset`, `revert`, `important`) as keywords, so class selectors such as `.block` or `.center` are no
  longer colored as keywords.
- The in-browser diff highlighter matches the case-insensitive keywords of SQL, Batch, and PowerShell
  (uppercase keywords now color), scans strings and comments in linear time for the newly added
  languages, maps the `.m` extension to Objective-C, and no longer over-colors common identifiers
  (`data`, `local`, `end`, and similar) as keywords in unrelated diffs.

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
