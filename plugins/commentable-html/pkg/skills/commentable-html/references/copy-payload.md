# Copy payload format

Detailed reference content moved out of `SKILL.md` to keep the core skill under the governance line limit.

## Copy payload format

When the user clicks **Copy all**, this is what hits the clipboard:

```
# <data-doc-label> (N comments)
Source: <data-doc-source>

## Comment 1
Id: c<timestamp><random>
When: Jun 4, 2026, 11:41
Where: H1 "Migration Plan" > H2 "P0 Targets" > H3 "Authoring Detectors"
Pinpoint: <li> - match 2 of 4 in section
Offsets: [1234, 1267]

Quoted text:
> the selected text, line by line

In context:
> ...some text before "the selected text" some text after...

Containing <li>:
> Full text of the containing list-item, paragraph, or table cell so the agent can grep-locate the source line precisely.

Comment:
the user's note

---

## Comment 2 (mermaid)
Id: c<timestamp><random>
When: Jun 4, 2026, 11:43
Where: H1 "Migration Plan" > H2 "Processor flow"
Anchor: mermaid diagram #1, node "AsmGate"
Node label: ASM machine?

Comment:
the user's note about this mermaid node

---

AGENT INSTRUCTIONS:
After acting on the comments above, append every processed id
to the JSON array inside the `<script id="handledCommentIds">`
block of `<data-doc-source>`. Existing entries must be preserved. On
the next page load those comments are pruned from localStorage
and their highlights are dropped.

HANDLED_IDS_JSON: ["c1...", "c2...", ...]
```

Mermaid comments use the `## Comment N (mermaid)` header so the agent can branch on anchor type without parsing the body. They emit `Anchor:` and `Node label:` lines instead of `Pinpoint:` / `Offsets:` / `Quoted text:` / `Containing <...>:`. The `Where:` heading path and the trailing `HANDLED_IDS_JSON` line are identical to text comments, so the handled-id contract is unchanged.

The `HANDLED_IDS_JSON` line is the machine-readable contract. Always parse it; do not regenerate ids from the human-readable section.


## What the agent does when the user pastes the bundle back

1. **Read** the comments (quoted text + note) and act on each in order. If a comment is ambiguous, ask the user to clarify before marking it handled.
2. **Parse** the `HANDLED_IDS_JSON: [...]` line at the end of the bundle.
3. **Read** the current `<script type="application/json" id="handledCommentIds">` block from the HTML file.
4. **Merge:** append every id from `HANDLED_IDS_JSON` to the existing array. Preserve existing ids. Deduplicate (a `Set` round-trip is fine).
5. **Write** the new JSON array back into the same `<script>` block. Keep it on its own line for diff-friendliness:

   ```html
   <script type="application/json" id="handledCommentIds">
   ["c1abc","c2def","c3ghi"]
   </script>
   ```

6. **Tell the user** to reload the page (Ctrl+F5 to bust any cache). The processed comments will be pruned automatically and a toast will say `"N previously-handled comments cleared by the agent."`

Never edit the user's `localStorage` directly. Only the HTML file is the agent's surface.


