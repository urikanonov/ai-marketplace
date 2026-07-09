# Commentable HTML tutorial: Planning a Community Garden

This walkthrough uses `examples/community-garden.html` as the running example. The file is standalone and includes prose, tables, KQL, a Chart.js chart, images, Mermaid diagrams, and a unified diff.

The source images live in `examples/images/`. The example build inlines them with `tools/inline_images.py`, so the finished HTML can be shared as one file.

The screenshots in this tutorial are generated deterministically from the example with `node tools/capture_tutorial.mjs examples/community-garden.html docs/tutorial-images garden`; re-run it after a UI change to refresh them.

## 1. Open the example

1. Open `examples/community-garden.html` in a modern browser.
2. If the comments panel is not already open, click **Show** in the floating toolbar (upper right) to open it. (That toggle reads **Hide** while the panel is open and **Show** while it is closed.)
3. Scroll through the plan once so you can see the 9 sections and the in-page Contents list.

![The community garden plan open in a browser, with the Contents list and the floating toolbar](docs/tutorial-images/garden-01-top-light.png)

## 2. Read the document-type bubble and version

1. In the sidebar header, look at the document-type bubble.
2. For a self-contained inline file it reads **Portable**. While the file has live comments that are not yet embedded, it reads **Not portable** (a hover tooltip explains why). Once every comment is embedded into the file (see Export), it reads **Portable** again.
3. Economy documents use the same UI, but the bubble reads **Economy** when the file still depends on companion assets.
4. Next to the bubble, read the version indicator. It appears as `v<x.y.z>` and tells you which commentable-html runtime produced the file.

## 3. Open Help

1. Click **Help** in the sidebar meta row.
2. Read the modal for a summary of controls, gestures, keyboard shortcuts, the type bubble, exports, and the TOC side menu.
3. Close it with the X button, Escape, or by clicking the backdrop.

![The Help modal, listing controls, gestures, and shortcuts](docs/tutorial-images/garden-07-help.png)

## 4. Leave a comment on prose

1. Go to **Overview**.
2. Select the phrase `underused corner lot`.
3. Click **Add Comment** in the small popup below the selection.
4. Type a note, then click Save or press Ctrl+Enter.
5. The selected text becomes highlighted and a card appears in the sidebar.

![The comment composer open on a selected phrase, with the quoted text and a note field](docs/tutorial-images/garden-05-composer.png)

## 5. Leave a comment on a table cell

1. Go to **Garden Layout**.
2. In the bed allocation table, select the text `Use a removable trellis`.
3. Click **Add Comment**.
4. Save a note. The sidebar pinpoint includes the table cell context so the comment can be found later.

## 6. Leave a comment on the KQL block

1. Go to **Planting Schedule**.
2. In the KQL card, select `EventType in` or another short span inside the query.
3. Click **Add Comment**.
4. Save a note. The copied bundle will preserve the selected KQL as a fenced code quote.

![A highlighted KQL block with a Run in Kusto link and a Copy button](docs/tutorial-images/garden-02-kql.png)

## 7. Leave a comment on the Chart

1. Stay in **Planting Schedule** and find the watering-needs chart.
2. Move the mouse over the bars to see the Chart.js tooltip.
3. To comment on the chart, select text in the chart caption: `Estimated liters of water needed per week`.
4. Click **Add Comment** and save a note. The chart canvas itself is inside a `cm-skip` wrapper so hover tooltips work and chart pixels do not disrupt text anchoring.

![The Chart.js bar chart of weekly watering needs with a commentable caption](docs/tutorial-images/garden-03-chart.png)

## 8. Leave a comment on an image

1. Go to **Site Selection** or **Garden Layout**.
2. Hover the raised beds image or the garden layout image.
3. Click the floating **Add Comment** button at the image corner.
4. Save a note. The comment is anchored to the whole image and uses the image alt text as its quote.

## 9. Leave a comment on a Mermaid node

The Mermaid diagrams render by default when you open the file online (offline, they stay
as readable source text).

1. Go to **Risks & Mitigations** and find the planting decision flowchart.
2. Hover a node such as `Frost forecast in next 72 hours?`.
3. Click the floating **Add Comment** button on the node.
4. Save a note. The node gets a colored ring, and the comment anchors to the Mermaid node key instead of a text offset.

## 10. Leave a comment on a diff line

1. In **Risks & Mitigations**, find the `watering_schedule.py` diff.
2. Hover the added line `+    if rainfall_mm >= 8:`.
3. Click the floating **Add Comment** button to comment on the whole line.
4. Alternatively, select a substring within a single diff line and click **Add Comment** to comment on only that region.
5. Use the diff header button to switch between **Side-by-side view** and **Inline view**. The comment stays attached.

![The unified diff block with side-by-side toggle and a syntax highlight toggle](docs/tutorial-images/garden-04-diff.png)

## 11. Use the left TOC side menu

1. Use a wide browser window, at least 1400px wide.
2. A generated section menu appears on the left. It is separate from the author Contents list near the top of the document.
3. Scroll the document. The active section updates as scroll-spy follows the nearest heading.
4. Click a section name to jump to it.
5. Click **Back to top** to return to the top of the plan.
6. Use the collapse control to hide or show the side menu.

## 12. Copy all comments and inspect the Markdown bundle

1. Add several comments using the steps above.
2. Click **Copy all** in the sidebar or floating toolbar.
3. Paste into a text editor.
4. The bundle is Markdown. It includes the document label, source, each comment, each anchor detail, and a final `HANDLED_IDS_JSON: [...]` line for the agent.
5. Text, code, KQL, image, Mermaid, and diff comments all travel through the same bundle.

## 13. Export comments or a portable file

1. Click **Export as Portable** in the sidebar.
2. The browser downloads a copy with current comments embedded in the `embeddedComments` block, so they travel with the file.
3. In economy documents, the same action rebuilds one portable file with the runtime and comments embedded.
4. The open page is not overwritten. Keep the downloaded copy or replace the original manually.

## 14. Export to Plain HTML

1. Click **Export to Plain HTML**.
2. The downloaded `.plain.html` file keeps the report content and styling, including tables, KQL, charts, Mermaid, images, and diffs.
3. It removes the comment toolbar, sidebar, composers, stored comment blocks, and comment runtime.

## 15. Clear comments

1. Click **Clear Comments** in the sidebar.
2. A confirm dialog opens. The safe default is Cancel.
3. Choose Cancel or press Escape to keep comments.
4. Choose OK only when you intentionally want to delete every local comment for this document.

## 16. Run the KQL in Kusto

1. Go back to **Planting Schedule**.
2. In the KQL card caption, click **Run in Kusto**.
3. A new tab opens Azure Data Explorer with the query loaded against `help.kusto.windows.net` and the `Samples` database.
4. The link contains the query text in encoded form, so do not use this pattern for secrets or private data.

## 17. Light and dark themes

The layer follows the OS color scheme by default and can be forced with a query parameter (`?clawpilotTheme=dark`, `light`, or `auto`). Every surface - prose, tables, KQL, charts, diffs, and the review chrome - is themed in both modes.

![The same plan rendered in dark theme](docs/tutorial-images/garden-08-top-dark.png)
