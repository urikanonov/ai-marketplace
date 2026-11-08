## Local text reattachment

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| CMH-REATTACH-01 | Startup resolves every locally retained text root before context backfill and highlight restore, independently of which comments the editing agent received. Anchor migration preserves original quote/context, note, timestamps, request state, replies and unknown fields. Composer captures additive selectors only after a real highlight succeeds. Storage remains the existing comment array and compression format. | `tests/100-reattachment.spec.js` - `reattaches all locally retained roots after long insertion (CMH-REATTACH-01)` |
| CMH-REATTACH-02 | Verified positions are trusted only with the matching local revision fingerprint and quote. Unique exact passages recover across inserted and moved blocks without relying on distance or occurrence ordinal. No authored revision attribute or network service is required. | `tests/100-reattachment.spec.js` - `finds moved exact passages without ordinal or distance guesses (CMH-REATTACH-02)` |
| CMH-REATTACH-03 | Prose whitespace and typographic quote/dash variants match through an original-code-unit offset map. Matching never folds case or numbers. Code whitespace and newlines remain significant. The original selected quote is retained even when its current spelling differs. | `tests/100-reattachment.spec.js` - `maps typography and prose whitespace to original offsets (CMH-REATTACH-03)` |
| CMH-REATTACH-04 | Bounded local block snapshots and stable block/heading evidence support small-edit alignment, including changed selected phrases, unchanged text after edits and whole selected paragraphs. Recovery requires sufficient unchanged selected text and strong flanks, not an id on wholly rewritten text. Successful matches refresh current selectors for later revisions while retaining original evidence. | `tests/100-reattachment.spec.js` - `recovers small block edits and changed selections with strong evidence (CMH-REATTACH-04)` |
| CMH-REATTACH-05 | Raw/normalized prefix, suffix, heading and block evidence disambiguates repeated text. Current selectors record bounded quote/block uniqueness evidence: deleting one of historically indistinguishable copies does not make its remaining duplicate a safe match without stable identity. Revised indistinguishable copies are Detached even if previous offsets still spell the quote. No first/nearest tie guesses. | `tests/100-reattachment.spec.js` - `disambiguates short repeats but detaches indistinguishable revised copies (CMH-REATTACH-05)`, `deleting one historically identical paragraph cannot bind its comment to the surviving copy (CMH-REATTACH-05)` |
| CMH-REATTACH-06 | Deleted or unresolvable passages become Detached with backward-readable `start=end=1000000000` offsets. Original offsets remain in additive selectors, and original content/context is retained for later automatic recovery without changing handled state or timestamps. | `tests/100-reattachment.spec.js` - `detaches deletion and recovers when original evidence returns (CMH-REATTACH-06)` |
| CMH-REATTACH-07 | Legacy quote-less comments retain valid current offsets. Quote-bearing legacy roots can recover without offsets. Structural anchors and replies are not text roots, and replies inherit root Detached state. Malformed known-version selectors fall back to valid legacy evidence; unknown future versions remain Detached while preserving foreign fields. Older discontiguous-table exports with ellipsis quotes and no offsets keep their legacy shape absent strong recovery evidence. | `tests/100-reattachment.spec.js` - `preserves legacy and future metadata and skips structural roots and replies (CMH-REATTACH-07)` |
| CMH-REATTACH-08 | Indexing shares source `cm-skip` exclusion and one revision index across roots. Snapshots, cached heading hashes, block normalization and alignment work are bounded; oversized candidates are rejected before slicing, and edit distances cannot overflow. Over-budget matching leaves unresolved roots Detached instead of guessing. | `tests/100-reattachment.spec.js` - `excludes skipped source text and bounds snapshots and matcher work (CMH-REATTACH-08)`, `a huge rewrite cannot overflow small-block edit alignment into a false attachment (CMH-REATTACH-08)`, `large-block evidence work is bounded before normalization and alignment slicing (CMH-REATTACH-08)`, `large headings cannot multiply full-document hashing across every indexed block (CMH-REATTACH-08)` |
| CMH-REATTACH-09 | Highlight restoration retains non-overlap safeguards and marks unresolved overlapping or failed-wrap roots Detached. Failed partial marks are removed, while original comment data remains listed and recoverable. | `tests/100-reattachment.spec.js` - `marks overlaps and failed wraps Detached without changing comment data (CMH-REATTACH-09)` |

Selectors use additive `cmAnchor` version 1 and a root `detached` boolean. Malformed known-version
selectors fall back to valid legacy evidence; unknown future versions remain Detached until explicit
manual selection adopts supported selectors and archives the foreign object. Legacy quote-less
comments preserve their previous offset-only behavior; without historical text evidence their old
revision cannot be independently verified. Original quote and existing
context fields are not replaced by automatic migration. A bounded original quote/context copy
survives explicit manual capture, with truncation flagged for unusually large evidence. Current selectors contain a revision hash,
verified offsets, raw flanks, heading identity, code flag and a bounded local block snapshot. The
revision fingerprint uses source text and ordered unique element identities, not block fragments that
highlight insertion can split. Explicit
manual capture refreshes current selectors but keeps `cmAnchor.original`.

Bounds: at most 8 million source code units in an index, 4096 code units per block snapshot/current
exact selector, 128 occurrences per matcher, 64 million scanned/alignment units per resolution pass,
16 candidate blocks for fuzzy recovery and 1 million alignment cells per block comparison.
Strong exact flanks also bound a local alignment when an edit lies inside a long block whose
snapshot cannot be aligned in full.
Alignment allows at most 20 percent small edits, requires at least 45 percent unchanged selected
characters and, except for whole-block selections, strong unchanged surrounding text. Long or
ambiguous rewrites can therefore need manual reattachment. No semantic, case-folding or numeric
equivalence is inferred.
