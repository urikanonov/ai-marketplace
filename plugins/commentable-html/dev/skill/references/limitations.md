# Limitations


## Limitations to call out

- **Diff region (sub-line) comments are mouse-driven.** Selecting a region within a diff line to comment it requires a mouse selection; the keyboard path (focus a line, press <kbd>Enter</kbd>) comments the **whole line**. Keyboard-only users can still comment every line, just not sub-line regions.
- **Cross-structural selections** that span structural boundaries (e.g., selecting from inside a `<table>` cell into the surrounding text) sometimes fail to anchor cleanly. The composer shows an error toast in that case; the user retries with a tighter selection.
- **Re-rendering of content breaks anchors.** Comment positions are character offsets into `#commentRoot.textContent`. If the page re-renders content after a comment is placed (e.g., the user changes a filter that swaps DOM), restored highlights may land in the wrong place on next load. Treat any HTML that has accepted comments as effectively read-only: regenerate the document only with full awareness that anchors will reset.
- **Mermaid diagrams that change source between renders** invalidate node keys. If you edit the diagram so a node renamed from `AsmGate` to `AsmCheck`, the comment's `nodeKey="AsmGate"` no longer resolves and the highlight is dropped (the comment stays in the list and the agent still sees the original node label in the copy bundle). Treat diagram source as part of the anchor.
- **Mermaid re-renders are not re-attached.** The layer attaches once per host, when mermaid first finishes rendering. If the host page later re-runs `mermaid.run()` on the same block (e.g., theme switch), highlights and hover handlers are lost until the next page reload. Theme switches in commentable HTML should require a reload.
- **`localStorage` is origin-scoped.** `file://` works but each file has its own bucket. If the user moves the HTML to a server, comments do not follow.
- **Clipboard API requires a user gesture.** `Copy all` falls back to a hidden `textarea` + `execCommand`, and finally a `prompt()` window if both fail. Per-block copy actions (code-block Copy buttons and the Kusto cluster-name chip) use `navigator.clipboard` then `execCommand`; if both fail they show a `Copy failed` toast and do NOT open a prompt (only `Copy all` has the prompt fallback).


