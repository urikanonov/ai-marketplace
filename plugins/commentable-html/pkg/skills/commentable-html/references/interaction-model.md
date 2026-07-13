# Interaction model

## Problem and review loops

AI often produces rich HTML artifacts because they can show spatial layouts, diffs, Mermaid diagrams, Chart.js charts, collapsible sections, and other structure that Markdown cannot express as well. Without this layer, review means switching between the rendered HTML and chat, then describing every requested change in prose.

Commentable HTML keeps review in the artifact. The reviewer comments in place, copies or exports structured state, and returns to chat only when it is time for the agent to act. You stay in the loop; the loop gets tighter.

**Self review loop:** generate the artifact, comment in place, click **Copy all**, paste the bundle to the agent, let the agent update the source and mark handled ids, then reload so handled comments are pruned.

**Peer review loop:** run the self review loop first, click **Export as Portable**, share the downloaded file with a peer, receive the peer's Portable HTML with embedded comments, and feed those comments back to the agent.

**Reviewer loop:** when someone sends Markdown or HTML, convert or retrofit it, review inline, and send back a
Portable HTML file with comments embedded.

## End-to-end interaction walkthrough

1. The user selects text in the document.
2. An **Add Comment** popup appears below the selection; right-click on a selection opens the same popup as a fallback.
3. A composer popover appears. The top drag handle uses a grip icon plus "drag to move" so the composer can be moved
   away from covered text.
4. Multiple composers can stay open. Selecting another range and choosing **Add Comment** creates another composer
   without closing the first. If a new composer would overlap an existing one, it staggers by 28px, and the focused
   composer rises to the front.
5. Saving wraps the selection in a highlighted span and adds a sidebar card.
6. Clicking a highlight opens its card. When a highlight wraps a link or another clickable element, hovering the
   highlight shows the `#hlBubble`; clicking the bubble opens the comment without triggering the underlying link.
7. Comments persist in `localStorage` under the document key and can be embedded into the HTML through
   **Export as Portable**.
8. **Copy all** emits a Markdown bundle plus `HANDLED_IDS_JSON: [...]`.
9. The agent acts on the comments and appends processed ids to `<script id="handledCommentIds">`; on reload those ids
   are pruned from `localStorage`, highlights disappear, and only unresolved comments remain.

The HTML file is the durable source of truth for handled ids. `localStorage` is a browser cache. When
`<script id="embeddedComments">` is non-empty, the runtime merges that in-file snapshot into `localStorage` by id; the
entry with the later `updatedAt`, falling back to `createdAt`, wins.

## Handled comments stay handled

Once a comment id is in `<script id="handledCommentIds">`, it must never resurface. The runtime enforces this at every
read path:

- On load, `pruneHandled()` filters handled ids out of the in-memory comment list and writes the survivors back to
  `localStorage`.
- **Copy all** filters through `withoutHandled(comments)` before building the bundle, so handled comments are absent
  from Markdown, `HANDLED_IDS_JSON`, and the copied count.

The agent's edit to `handledCommentIds` is the final word on what is gone.

## Leaving comments (interaction model)

Every add-comment affordance uses the same **"Add Comment"** control (one accent-pill button with a hover effect, shown as a popup on a text selection and as a floating button on an image / diff line / mermaid node), and the layer avoids duplicate comments on the same anchor:

- **Prose / code blocks:** select the text and click **Add Comment** (or right-click). Selecting the **exact same range** that already has a comment re-opens that comment for editing instead of creating a duplicate; a **different range** (even one that overlaps) makes a new comment. Multiple comments per paragraph are fine.
- **Code review diff lines:** select a **region within a single diff line** (just like prose) and comment it - the highlight is a `<mark>` around exactly that substring, so one line can carry several region comments. Selecting the same region re-opens its comment; the floating **Add Comment** button (or <kbd>Enter</kbd> on a focused line) comments the whole line.
- **Mermaid nodes and diagrams:** hover a node, gantt task label/bar, or sequence/gantt text and click **Add Comment**; hover empty diagram area and click **Comment on diagram** for a whole-diagram anchor. Pie slices and actors use the whole-diagram path.
- **Headings:** hover a heading and click **Add Comment** to comment the whole heading text; plain click still deep-links to that heading.
- **Images and charts:** hover or focus an image or a chart canvas and click **Add Comment**; whole-image/whole-chart anchor, multiple comments allowed.

Every comment lands in the sidebar and round-trips through **Copy all**, **Export as Portable**, and the `handledCommentIds` prune contract identically, regardless of anchor type.
