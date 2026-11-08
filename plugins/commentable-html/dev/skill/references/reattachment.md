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

New selectors also remember quote/block/identity/context uniqueness across raw exact and normalized
prose recovery (`normalizedEvidence`); code evidence stays raw and raw code copies still count.
Whole-block identity includes its tag. Removing one of previously
equivalent copies cannot make the survivor a safe replacement. Historical block uniqueness helps
only while the block still matches; a shared ancestor ID alone cannot distinguish repeated quotes
inside it. Otherwise occurrence-specific identity or historically unique, fully preserved flanks
must survive. This also permits supported edits to repeated selections without guessing.
Older selectors without this historical or normalization-aware evidence still use their available
quote/context; they cannot reconstruct whether a deleted equivalent copy used to exist.

Sorting can scatter a multi-row highlight into noncontiguous fragments. Its saved selectors then
require an intact raw/normalized quote match, never an approximate interval that encloses unrelated
rows. Live unsorting and canonical exports can restore genuinely contiguous offsets; otherwise the
comment becomes Detached with its original evidence and unavailable offsets retained.

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

Verified unchanged positions also carry an additive layout `basis`: matching source/identity and
layout fingerprints avoid rescanning historical evidence, while changes to code or block structure
still refresh it. An intact complete block with a unique current ID and historical occurrence
identity can verify its selected text locally. Shared or changed blocks do not qualify for that
shortcut. Normalization maps and block indexes are ephemeral, rebuilt from the displayed document,
and never add a new storage format or relax the existing recovery limits.
All roots resolve before current evidence is recaptured from the remaining shared budget.
Unchecked uniqueness is conservative across changed revision/layout evidence, so an exhausted
capture cannot authorize a later surviving duplicate; an intact stable block can still prove
its occurrence identity locally.
Legacy context backfill shares an immutable per-pass text/layout scan without replacing
historical fields. Highlight restoration updates its local text-node index when wrapping splits
nodes, and rebuilds it after failed-wrap cleanup. Neither index is persisted or reused in a later
capture/restore operation.

## Compatibility

Legacy comments with no saved quote preserve their initial offset-only behavior; there is no
historical text evidence with which to verify an older revision. Once migrated, a matching
revision/offset fingerprint preserves unchanged reloads, including selections beyond the quote
snapshot limit, and restores saved positions if that verified revision returns. Changed revisions
still require recovery evidence. Malformed known-version selectors can fall
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
selectors in `cmAnchor`; already offsetless scattered-table comments retain unavailable offsets.
Old offset-only runtimes leave both shapes listed without a guessed highlight.
The prior runtime is archived as `tests/fixtures/legacy-offset-runtime.js.gz` and exercised against
new exported files, rather than replacing it with a synthetic compatibility implementation.

An unmodified older runtime does not understand Detached labels or manual/automatic reattachment.
It cannot protect comments against further revisions. Runtimes predating the existing compressed
`::z` slot also cannot read that slot; use embedded Shareable comments for a portable handoff.
Additive metadata cannot retroactively fix old runtime code. Upgrade the layer for the new behavior.
