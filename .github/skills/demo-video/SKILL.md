---
name: demo-video
description: Record short, publishable demo clips of what this repo ships - a paced montage of a commentable-html report driven in a real browser, or a real Copilot CLI terminal session (multi-duck rounds and all) replayed with the slow parts fast-forwarded. Captures live, scrubs secrets before anything touches disk, and writes only to the gitignored tmp/. Use when asked to record a demo video, make a clip for the site, film the skill in action, show multi-duck running, screen-record a session, or re-record an existing demo. Trigger on - demo video, record a clip, screen recording, film the demo, show it in action, video for the site, fast-forward the session, terminal recording, webm.
---

# demo-video

Records short clips of the things this repo ships, so a reader can SEE them instead of reading about
them. Two subjects, one video pipeline (Chromium via Playwright), so both come out as the same
`.webm`.

**Nothing it produces is committed.** Casts, transcripts and clips all land in `tmp/demo-video/`,
which is gitignored. The tool is checked in so a clip can be re-recorded; the clips are not.

## Before you start

```bash
cd .github/skills/demo-video && npm install     # only needed for the terminal subject
```

Playwright is reused from the commentable-html dev install (`python scripts/setup_dev.py`), so the
`report` subject needs no install here at all. `node-pty` is a native module - if `npm install`
leaves it unbuilt (npm may hold its install scripts back), run `npm approve-scripts node-pty` then
`npm rebuild node-pty`.

Both dependencies are pinned to exact versions in `package.json` and no lockfile is committed: this
is ad-hoc tooling, and a lockfile generated behind a corporate npm proxy records that private feed's
URLs, which nobody else can resolve. Use `npm install`, not `npm ci`.

## Record a commentable-html montage

```bash
node tools/record_demo.mjs report --seconds 10 --out ../../../tmp/demo-video/report.webm
node tools/record_demo.mjs report --list        # print the beat plan, no browser
```

Drives a real example (the community-garden report by default) through selection, the composer,
saving an anchored comment, replying in a thread, search, the table of contents, the export menu and
a code diff - with a synthetic cursor so a viewer can follow the clicks. `--seconds` is a target: the
beats are apportioned by weight to fill it, but real UI interactions have a floor, so the clip
usually lands within about a second of the ask.

Every beat is best-effort. A beat that cannot find its affordance prints a warning and the montage
continues, so a runtime change degrades one moment instead of failing the whole capture. Read the
warnings - they are how you learn the demo drifted.

## Record a terminal session (Copilot CLI, multi-duck, anything)

This is two steps on purpose: a live recording cannot fast-forward time that has not happened yet,
and splitting it means one real session can be re-rendered at any length without running it again.

```bash
# 1. Run the REAL session. stdin and stdout are proxied, so it is fully interactive.
node tools/record_demo.mjs capture --cols 120 --rows 30 -- copilot

# 2. Read the transcript it wrote. Then render it.
node tools/record_demo.mjs render --cast ../../../tmp/demo-video/session-<stamp>.cast.json --seconds 45
```

`render` replays the cast into a real terminal emulator (xterm.js) on a compressed clock: any gap
longer than the idle threshold collapses to a short hold with a visible "skipping ahead Ns" badge, so
the model thinking, the test run and the duck panel do not cost the viewer the wall clock. Gaps below
the threshold are left exactly alone, so streaming output still looks real. `--seconds` picks the
threshold that best fits and then stretches the hold to spend the budget; `--idle`/`--hold` override
it directly, and pinning `--idle` alongside `--seconds` is what protects a `--head`/`--tail` span
from being pre-compressed by a threshold chosen for the total.

The shape that works for a long panel run is a readable title card, a hard-compressed middle, and
the summary at its natural pace:

```bash
node tools/record_demo.mjs render --cast <file.cast.json> \
  --seconds 22.6 --idle 900 --hold 320 --head 60 --tail 620 \
  --intro 4 --end-hold 4 --scale 0.6 --ask "<the short version of the ask>"
```

`--head`/`--tail` are spans of RAW SESSION time, not clip time, so size them from the transcript
(where the summary starts) rather than from the previous render. `--scale` records smaller than the
layout to cut the file size.

## Check what you filmed

```bash
node tools/record_demo.mjs scan   --cast <file.cast.json>   # findings, with context
node tools/record_demo.mjs frames --clip <file.webm>        # stills you can actually look at
```

A video is the one artifact you cannot grep, so `frames` is how a human (or an agent) reviews what
was really on screen.

## Secrets: what is automatic and what is on you

A real session is full of things a published clip must not carry, so:

- Output is scrubbed BEFORE it is written - the raw stream is never persisted. Tokens (GitHub,
  OpenAI/Anthropic, AWS, Slack, Google), JWTs, `Authorization` headers, private key blocks,
  credentials embedded in URLs (`https://user:pass@host` in a git remote or proxy setting), and
  keyword-anchored assignments (`password=`, `*_SECRET=`, `SECRET_KEY=`, `AccountKey=`) are replaced,
  and so are your home path and account name.
- Scrubbing survives the ways a terminal mangles a credential: split across PTY chunk boundaries,
  painted with ANSI colour codes mid-token, or hard-wrapped across two lines by the application.
- A redaction keeps the column width it replaced, so a boxed or aligned TUI frame is not shifted.
- `render` REFUSES a cast that still scans dirty, and says so loudly if a cast was not captured by
  this tool (it was never scrubbed at source, and the home/account rules are per-machine).
- The browser subject records comments as "Demo Reviewer" rather than the identity in your install.

**None of that is the gate. You are.** Pattern matching cannot understand a session. In particular
these are NOT covered, and only your own eyes will catch them:

- **Anything the repo or the model says.** File contents, paths, branch and issue text, error
  messages, stack traces, `gh` output - a demo of an agent working is a demo of your code.
- **Other people's names and email addresses** from `git log`, `git blame`, or PR comments.
- **Hostnames, internal domains, org and customer identifiers**, and unusual credential shapes no
  rule knows about.
- **A credential you typed with a backspace**, or one a full-screen TUI draws out of stream order:
  the scrubber reads the byte stream, while the viewer reads the rendered grid.

Read the transcript, then look at the frames, before anything is published. If the net misses a
shape, add a rule to `tools/redact.mjs` with a test - do not just re-run.

## Layout

```
tools/record_demo.mjs    the CLI: report | capture | render | scan | frames
tools/timeline.mjs       pure core: beat scheduling and idle compression (unit tested)
tools/redact.mjs         pure core: scrub/scan rules and the chunk-safe scrubber (unit tested)
tools/report-beats.mjs   what the commentable-html montage shows, in order
tests/                   node --test units over the pure core; run by the validate CI job
SPEC.md                  the feature rows these tests cover
```
