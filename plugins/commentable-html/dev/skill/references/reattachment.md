# Text comments across revisions

Comment placement and review lifecycle are separate. Moving an anchor never handles an edit,
answers a question or edits a message. Copy one thread or Copy selected is sufficient: the runtime
relocates remaining browser-local comments without the agent knowing about them.

## Both review scenarios

When an agent handles only some comments, only those handled IDs are pruned. Unsent comments follow
identifiable content when the updated document loads. When a reviewer adds comments to the old
revision still displayed while the agent edits the file, those saved comments carry evidence from
the displayed DOM, not the newer file on disk, and relocate on refresh too.

Retain `data-comment-key` across revisions of one document. Different browser origins or a changed
identity do not share local storage. Use Shareable export to move browser-only comments to another
browser; the agent cannot read a reviewer's local storage. Save a draft before refreshing.

## Attachment and Detached

Text selectors combine a verified position, selected quote, raw surrounding context, section/block
identity and bounded original block text. Exact moved quotes, normalized typography/whitespace and
supported small edits can recover. Repeated matches need distinguishing evidence; a first match,
nearest offset or ordinal alone is not permission to guess. Substantial rewrites or missing evidence
may remain Detached: no algorithm can infer a reviewer's intended location from arbitrary new prose.

New selectors also remember quote/block uniqueness and whether the quote was unique within its
identified block or ancestor. Removing one of previously indistinguishable copies cannot make
the surviving copy a safe replacement: a shared ancestor ID alone cannot distinguish them.
Older selectors without this historical evidence still use their available quote/context;
they cannot reconstruct whether a deleted duplicate used to exist.

A Detached comment retains its message, original quote/context, author and replies. It remains
searchable by its review text, copyable, exportable and eligible for automatic recovery when its
content becomes identifiable again. Copy, Markdown and print label its historical attachment.

Click Reattach on the card, select commentable text and choose Attach comment. This explicitly
replaces the location of the same thread. Existing highlights cannot be overlapped. Cancel or Escape
leaves the comment unchanged. Saving failures are reported; an export can preserve the session's
reattached comment even when browser persistence is blocked.

Recovery snapshots are bounded (4096 code units), matching work is budgeted, and larger or ambiguous
rewrites can require manual selection. Very large review payloads remain subject to browser quota:
the writer never compresses beyond its reader's 8-million-character bound. A reported unsaved
session remains exportable; no message or foreign selector is silently discarded to fit.
Automatic recovery warns at startup too if quota pressure prevents saving the refreshed locations.

## Compatibility

Legacy comments with no saved quote preserve their offset-only behavior; there is no historical
text evidence with which to verify an older revision. Malformed known-version selectors can fall
back to valid legacy quote/context. Unknown future selectors stay Detached automatically, but an
explicit manual selection adopts current selectors and retains the foreign object under
`cmAnchor.previousSelector`.

The comment array and legacy `id`, `quote`, `note`, `start`, `end`, context, author and timestamp
fields remain present. Recovery evidence is additive `cmAnchor` metadata and `detached` state.
Legacy comments use their available quote/context and are upgraded only after an attachment is
established. Missing optional authored IDs do not make a document incompatible.

Attached comments have current legacy offsets, so old offset readers can highlight them. Automatic
relocation retains the historical quote while current matching evidence lives in `cmAnchor`.
Detached comments use equal, finite out-of-document sentinel offsets, retaining recoverable
selectors in `cmAnchor`; old offset-only runtimes leave them listed without a guessed highlight.
The prior runtime is archived as `tests/fixtures/legacy-offset-runtime.js.gz` and exercised against
new exported files, rather than replacing it with a synthetic compatibility implementation.

An unmodified older runtime does not understand Detached labels or manual/automatic reattachment.
It cannot protect comments against further revisions. Runtimes predating the existing compressed
`::z` slot also cannot read that slot; use embedded Shareable comments for a portable handoff.
Additive metadata cannot retroactively fix old runtime code. Upgrade the layer for the new behavior.
