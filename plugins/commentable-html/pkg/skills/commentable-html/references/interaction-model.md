# Interaction model

## Problem and review loops

AI now often produces rich HTML artifacts because they can show spatial layouts, diffs, Mermaid diagrams, Chart.js charts, collapsible sections, and other structure that Markdown cannot express as well. Without this layer, review means switching between the rendered HTML and chat, then describing every requested change in prose.

Commentable HTML keeps review in the artifact. The reviewer comments in place, copies or exports structured state, and returns to chat only when it is time for the agent to act. You stay in the loop; the loop gets tighter.

**Self review loop:** generate the artifact, comment in place, click **Copy all**, paste the bundle to the agent, let the agent update the source and mark handled ids, then reload so handled comments are pruned.

**Peer review loop:** run the self review loop first, click **Export as Portable**, share the downloaded file with a peer, receive the peer's Portable HTML with embedded comments, and feed those comments back to the agent.

## Leaving comments (interaction model)

Every add-comment affordance uses the same **"Add Comment"** control (one accent-pill button with a hover effect, shown as a popup on a text selection and as a floating button on an image / diff line / mermaid node), and the layer avoids duplicate comments on the same anchor:

- **Prose / code blocks:** select the text and click **Add Comment** (or right-click). Selecting the **exact same range** that already has a comment re-opens that comment for editing instead of creating a duplicate; a **different range** (even one that overlaps) makes a new comment. Multiple comments per paragraph are fine.
- **Code review diff lines:** select a **region within a single diff line** (just like prose) and comment it - the highlight is a `<mark>` around exactly that substring, so one line can carry several region comments. Selecting the same region re-opens its comment; the floating **Add Comment** button (or <kbd>Enter</kbd> on a focused line) comments the whole line.
- **Mermaid nodes and diagrams:** hover a node, gantt task label/bar, or sequence/gantt text and click **Add Comment**; hover empty diagram area and click **Comment on diagram** for a whole-diagram anchor. Pie slices and actors use the whole-diagram path.
- **Headings:** hover a heading and click **Add Comment** to comment the whole heading text; plain click still deep-links to that heading.
- **Images and charts:** hover or focus an image or a chart canvas and click **Add Comment**; whole-image/whole-chart anchor, multiple comments allowed.

Every comment lands in the sidebar and round-trips through **Copy all**, **Export as Portable**, and the `handledCommentIds` prune contract identically, regardless of anchor type.

