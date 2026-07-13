# AI-driven UX audit workflow for commentable HTML

A repeatable way to audit the *experience* of any commentable HTML document (a deck or a flat
document) with a browser and screenshots, then have an AI agent review the result and drive
improvements. It is deterministic and parameterised, so several agents can run the same audit -
on the same document for consensus, or on different documents / aspects - and their findings can
be compared. This is dev-only tooling; it is never shipped.

## The harness

`dev/tools/audit.mjs` opens a target HTML in headless Chromium and drives a scripted tour:

- Loads the document at three viewports (desktop 1440x900, laptop 1280x720, mobile 390x844) in
  both light and dark colour schemes, screenshotting each.
- Detects a deck (`window.__cmhDeck`) vs a flat document and runs the matching tour once on the
  laptop/light pass: for a deck it walks the slides, enters comment mode, adds a sample comment,
  and exercises the deck-aware card jump; for a flat document it scrolls, adds a text comment, and
  opens Help.
- Records machine observations: console errors/warnings, uncaught page errors, external network
  requests (egress), and layout overflow.

Run it from `plugins/commentable-html/dev`:

```bash
node tools/audit.mjs --target <file.html> --out <dir> [--label NAME] [--max-slides N]
```

Outputs under `<dir>`:

- `screenshots/*.png` - the numbered tour screenshots.
- `observations.json` - the machine-readable record (isDeck, slideCount, console, pageErrors,
  externalRequests, issues, and every step with its screenshot path).
- `report.md` - a human/agent-readable summary that lists the screenshots and observations and
  states what the reviewing agent should judge.

The harness exits 0 even when it finds problems: issues are DATA, not a test failure. It exits
non-zero only when it cannot run (bad target, browser launch failure).

## The agent review loop

1. **Run** the harness on the target, to a fresh `--out` directory.
2. **Read** `observations.json` (or `report.md`). Flag anything mechanical first: any `pageErrors`,
   any `console` errors, unexpected `externalRequests` (an Export-Offline deck should have none),
   and `overflow` issues.
3. **Look** at every screenshot (open each PNG). Judge the experience against a rubric:
   - Does chrome (toolbar, sidebar, menus) overlap or cover the content?
   - Is text legible and correctly sized; is a deck's stage scaled and letterboxed, not clipped?
   - Is navigation clear (a slide counter, Prev/Next) and is the mode obvious (present vs comment)?
   - Do light and dark both read well? Is the mobile viewport usable?
4. **Write findings**: a ranked list of `severity | where (screenshot) | problem | concrete fix`.
   Prefer producing the audit itself as a commentable HTML so the findings can be reviewed and
   iterated with the same skill (dogfooding).
5. **Fix and re-audit**: apply the safe fixes, regenerate the document, re-run the harness, and
   confirm the screenshots improved and the observations are clean.

## Running with multiple agents

Because the harness is deterministic, fan it out:

- **Consensus**: several agents each run the harness on the same target and independently write
  findings; agreement across agents is a strong signal (like a visual multi-duck).
- **Prisms**: split the rubric - one agent owns legibility/overflow, one owns chrome/overlap, one
  owns navigation/modes, one owns light/dark + mobile - each reviewing the same screenshots for its
  aspect.
- **Fleet**: point different agents at different documents (each `--out` its own directory) and
  aggregate the reports.

Consolidate the per-agent findings the same way `multi-duck` does: cluster, rank by severity and
agreement, auto-apply the safe fixes, and defer judgement-heavy ones.

## Worked example (this is how the deck present mode was found)

The first audit of a scaffolded deck showed `externalRequests: 17` and, in the screenshots, the
comment sidebar/toolbar covering ~32% of the slide on desktop and the entire viewport on mobile.
The fix (present mode hides the comment UI until the user enters comment mode) was applied, the
deck re-scaffolded, and a re-audit confirmed a clean full-screen presentation on desktop and a
correctly letterboxed, usable deck on mobile. The 17 external requests are the layer's eager
mermaid CDN load; on a deck that guarantee is deferred to Export Offline, and lazy-loading mermaid
only when a diagram is present is a tracked future improvement.
