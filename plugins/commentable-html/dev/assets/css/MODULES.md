# commentable-html CSS modules

The layer CSS ships as `NN-topic.css` partials in this directory. `build.py` assembles them by
DIRECTORY SORT (numeric prefix) into one stylesheet; the sort order is the load-bearing cascade.
Edit the owning partial - never recreate a `commentable-html.css` monolith (a test enforces its
absence). `tests/test_module_coverage.py` checks every partial is listed here and every listed area
is a real, test-backed area in `dev/SPEC.md`.

| Module | SPEC areas | Purpose |
| --- | --- | --- |
| `00-base.css` | CMH-THEME, CMH-CORE, CMH-DENSITY | Theme tokens (`--cp-*`) and base element styling. |
| `10-layout.css` | CMH-CORE, CMH-RESP, CMH-DENSITY | Layout recipe, toolbar, and core chrome. |
| `20-chrome.css` | CMH-SIDE, CMH-HELP, CMH-FOOT, CMH-DENSITY | Attribution footer, sidebar meta, help dialog, TOC chrome. |
| `30-mermaid.css` | CMH-MMD, CMH-DENSITY | Mermaid commenting layer + NonPortable controls. |
| `40-diff.css` | CMH-DIFF | Diff / code-review layer. |
| `50-content.css` | CMH-CONTENT | Default content styling (sections, tables, badges). |
| `60-images.css` | CMH-IMG | Image comment layer. |
| `70-kql.css` | CMH-KQL | Kusto query figure + KQL token styling. |
| `80-focus.css` | CMH-A11Y | Shared themed focus ring for interactive controls. |
| `85-checklist.css` | CMH-CHECK | Layered checklist controls, hierarchy indentation, and the per-list change card. |
| `86-notes.css` | CMH-NOTE | Editable notes fields: the textarea, label chip, single/multi-line toggle, and the per-note change card. |
| `87-validation-banner.css` | CMH-STAMP | Unvalidated-document fallback banner (amber, dismissible, light + dark). |
| `90-deck.css` | CMH-DECK | Deck profile (`data-cmh-mode="deck"`) overrides. |
| `92-print.css` | CMH-PRINT | Print/PDF stylesheet for flat documents plus one-slide-per-page deck print flow. |
| `95-reduced-motion.css` | CMH-A11Y | `prefers-reduced-motion` reset: clamps non-essential animations/transitions to near-zero. |
