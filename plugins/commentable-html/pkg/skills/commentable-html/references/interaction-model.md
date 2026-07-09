# Interaction model

Detailed reference content moved out of `SKILL.md` to keep the core skill under the governance line limit.

## Leaving comments (interaction model)

Every add-comment affordance uses the same **"Add Comment"** control (one accent-pill button with a hover effect, shown as a popup on a text selection and as a floating button on an image / diff line / mermaid node), and the layer avoids duplicate comments on the same anchor:

- **Prose / code blocks:** select the text and click **Add Comment** (or right-click). Selecting the **exact same range** that already has a comment re-opens that comment for editing instead of creating a duplicate; a **different range** (even one that overlaps) makes a new comment. Multiple comments per paragraph are fine.
- **Code review diff lines:** select a **region within a single diff line** (just like prose) and comment it - the highlight is a `<mark>` around exactly that substring, so one line can carry several region comments. Selecting the same region re-opens its comment; the floating **Add Comment** button (or <kbd>Enter</kbd> on a focused line) comments the whole line.
- **Mermaid nodes and diagrams:** hover a node, gantt task label/bar, or sequence/gantt text and click **Add Comment**; hover empty diagram area and click **Comment on diagram** for a whole-diagram anchor. Pie slices and actors use the whole-diagram path.
- **Headings:** hover a heading and click **Add Comment** to comment the whole heading text; plain click still deep-links to that heading.
- **Images and charts:** hover or focus an image or a chart canvas and click **Add Comment**; whole-image/whole-chart anchor, multiple comments allowed.

Every comment lands in the sidebar and round-trips through **Copy all**, **Export as Portable**, and the `handledCommentIds` prune contract identically, regardless of anchor type.

