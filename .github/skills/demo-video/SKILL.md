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

A capture is bounded by `--max-mb` (48 by default). Everything recorded is held in memory, because
the raw stream is never written to disk unscrubbed; at the limit the session is ended cleanly and the
cast is still written from what was captured, so a long run degrades into a shorter clip rather than
an out-of-memory crash that loses the recording. The ceiling is set by FINALISATION - scrubbing and
serialising peak at roughly 25x the captured size - not by what can be held, so raise it only with
that multiplier in mind. A real 24 minute Copilot session is a few megabytes.

A capture ALWAYS finalizes - it can never hang holding the session. That was not free: a capture used
to wait on the session's own exit with no bound, so a TUI that printed its answer and then never
exited held a ninety minute run in memory and wrote nothing (one sat for seventeen hours), and Ctrl+C
- the only way out - exited before writing anything. Three things now guarantee a cast:

- **A signal writes the cast.** The first SIGINT/SIGTERM ends the session and finalizes, warning that
  the ending may not be the one the recipe asked for. A second one exits immediately, so an operator
  who will not wait for the write is still not stuck. One caveat worth knowing: while a capture is
  attached to your terminal it puts stdin in RAW MODE, so Ctrl+C is a byte the SESSION receives (that
  is what lets you cancel a turn inside the TUI being filmed) and never reaches the capture. The
  escape hatch there is **Ctrl+\\**, which ends the capture and writes the cast; from another shell,
  `kill <pid>` does the same.
- **The wall clock is authoritative** (`--exit-grace`, 120 seconds). Once a `--script` has sent its
  last turn, the session gets that long to exit on its own; then it is killed and the cast is written
  regardless of what the stream is doing. Nothing here trusts quiet: a TUI repaints, so "the stream
  went silent" is not a signal that anything finished. The grace applies only to a SCRIPTED capture -
  an interactive one has an operator sitting in front of it and is never killed for being quiet.
  Every other forced ending - the size limit, a script that cannot continue - goes through the same
  supervisor, so none of them can kill the child and then wait for a session that is already gone.
- **A stalled capture says so** (`--progress`, every 60 seconds; `0` turns it off). The line names
  elapsed time, how long the session has been silent, how much has been captured, and the step being
  waited on - or, once the last turn has been sent, that it is waiting for the session to exit. It
  goes to stderr and only when stdout is NOT a terminal, because drawing a status line into a live
  TUI corrupts the very screen the clip is of - the unattended run whose log nobody is watching is
  the case that needs it.

An ending the clock or the operator forced is reported in the closing lines and exits non-zero, so a
capture that did not end the way the recipe asked can never read like a clean take.

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

## Re-record a published clip

A published clip is an unattended capture that can run for an hour and a half, so the ask is not
retyped from memory - it is committed. `--script` drives the session from a recipe, and each step
waits for its cue (a file that this run produced, a marker in the output, or a window of quiet)
before sending, so the capture survives an agent that pauses mid-thought.

Run it from a SCRATCH directory, never from a checkout. `capture` spawns the session with the
current working directory, so filming from inside the repo puts repository paths on screen in a
published video - which is why the commands below `cd` out first and address the tool, the recipe and
the output by absolute path:

```powershell
cd C:\demo                              # a scratch dir, NOT a checkout
$repo  = "C:\path\to\ai-marketplace"    # the only line to edit
$skill = "$repo\.github\skills\demo-video"

# multi-duck: --script examples/duck-session.json
node "$skill\tools\record_demo.mjs" capture --cols 120 --rows 30 `
  --script "$skill\examples\duck-session.json" `
  --out "$repo\tmp\demo-video\duck.cast.json" `
  -- copilot --banner --no-remote --allow-all --disable-builtin-mcps
```

The multi-duck clip is that one command. The commentable-html round trip is TWO phases that run
against each other, and the capture is only half of it: the recipe's `paste` step blocks on a review
bundle at `C:\demo\review.md`, which the BROWSER phase writes. Start the capture, wait for the agent
to write `C:\demo\report.html`, then drive the montage in a second shell - `--review-out` is what
closes the loop, writing the bundle (atomically, so the capture can never paste a half-written file)
to exactly the path the recipe waits on:

```powershell
# shell 1: --script examples/loop-session.json - the agent writes the report, then waits for review
node "$skill\tools\record_demo.mjs" capture --cols 120 --rows 30 `
  --script "$skill\examples\loop-session.json" `
  --out "$repo\tmp\demo-video\loop.cast.json" `
  -- copilot --banner --no-remote --allow-all --disable-builtin-mcps

# shell 2, once C:\demo\report.html exists: film the review and hand it back
node "$skill\tools\record_demo.mjs" report --example "C:\demo\report.html" `
  --review-out "C:\demo\review.md" --snapshot-out "C:\demo\report-before.html"
```

`loop-session.json` hardcodes `C:\demo` (`report.html`, `review.md`), so that scratch path is
load-bearing for this clip: a different directory works for the duck recipe but silently breaks the
round trip. `--snapshot-out` keeps the report AS REVIEWED, because the agent edits it in place and
without the copy the "before" side of the round trip is gone.

### Capture budgets (where each timeout came from)

Steps wait in SEQUENCE and every timer starts fresh, so a recipe's worst case is the sum of its
timeouts - which is where the hour and a half above comes from. The number worth arguing about is
the longest single wait, because that is the one an operator sits through before a stalled capture
admits it is stalled, and it is derived from a MEASURED run rather than picked from memory. Change a
timeout and change the row: `DEMO-SCRIPT-12` fails a budget that lives only in the JSON.

| Recipe | Longest wait | Where that number came from |
| --- | --- | --- |
| `duck-session.json` | 60 minutes | The cast the published clip is rendered from ran 36 minutes and reached its PANEL SUMMARY, so 60 leaves two thirds again as long before the backstop fires. The subject is deliberately cheap - one `slugify.mjs` with a few tests, reviewed by 4 fast ducks - because the earlier subject (`md2html.mjs` plus a `PLAN.md`, on an unconstrained panel) ran past two hours and hit its 90 minute `quit` timeout rather than finishing, and two further attempts died around twenty minutes in with no cast at all. A panel is the thing being demonstrated, not the code it reviews, so the clip still shows both rounds and ends on the consolidated table. |
| `loop-session.json` | 40 minutes | The `paste` step is idle until the BROWSER phase in the second shell writes `C:\demo\review.md`, so this budget covers a human driving that phase as well as the agent writing the report - it is a handover window, not an agent's working time. The `quit` step then allows 25 more minutes for the fix-up the clip ends on. |

Capturing is only half the job - the three clips are then RENDERED from what those phases produced,
and each takes different flags:

```powershell
# demo-commentable-html.webm - the browser montage on its own, at publish length and scale
node "$skill\tools\record_demo.mjs" report --example "C:\demo\report.html" `
  --seconds 30 --scale 0.6 `
  --out "$repo\tmp\rerecord-review\demo-commentable-html.webm"

# demo-commentable-html-loop.webm - the round trip. --example is the report AS REVIEWED and
# --example-after the one the agent then fixed.
node "$skill\tools\record_demo.mjs" loop --cast "$repo\tmp\demo-video\loop.cast.json" `
  --example "C:\demo\report-before.html" --example-after "C:\demo\report.html" `
  --scale 0.6 --out "$repo\tmp\rerecord-review\demo-commentable-html-loop.webm"

# demo-multi-duck.webm - the duck cast, with the summary left at its natural pace
node "$skill\tools\record_demo.mjs" render --cast "$repo\tmp\demo-video\duck.cast.json" `
  --seconds 42.7 --idle 900 --hold 320 --head 60 --tail 60 --scale 0.6 `
  --out "$repo\tmp\rerecord-review\demo-multi-duck.webm"
```

**Pass `--example-after`, or the loop clip ends on nothing.** A capture keeps recording until its
`quit` step fires, so the cast runs on past the last interesting output; without the resolved report
to cut to, the clip spends its closing seconds on an empty terminal tearing the session down. With it
the clip ends where the story does. `render` needs no `--ask` when the cast came from the committed
recipe - its `ask` mark is already one readable sentence, and the card quotes that.

**The published `demo-multi-duck.webm` quotes a LONGER ask than the recipe does, and that is
accepted.** It was captured with a 215-character ask; `DEMO-SCRIPT-07` then capped a recipe's ask at
200 characters (past that the card steps down to a smaller font), so `examples/duck-session.json`
carries the 178-character trim of the same sentence - "with 4 fast ducks, and finish with a PANEL
SUMMARY table of the findings" where the clip says "with 4 fast ducks at low reasoning effort, and
finish with a PANEL SUMMARY table of the consolidated findings". Nothing else differs (same subject,
same two rounds, same fast panel) and the shipped card is readable, so the clip was not re-recorded
for wording alone. Expect the trimmed sentence on the next re-record; it is not a sign the recipe
drifted from the clip.

**Render every publishable clip at `--scale 0.6`.** It is not only a file-size lever: the required
`site` gate (`scripts/check_clip_chrome.py`) reads the window chrome at fixed video pixels, which
hold at that scale. Rendered larger, the traffic lights land inside the strip it inspects and every
terminal frame reports a leak - the gate names the scale when it sees colour there, but it costs a
render either way. The three published clips are `demo-commentable-html.webm` (the `report` subject),
`demo-commentable-html-loop.webm` (the `loop` subject) and `demo-multi-duck.webm` (`render` over the
duck cast).

A freshly rendered clip needs NO hand-applied ffmpeg mask: the chrome draws no title and the loop's
phase caption clears it, so the strip is born flat.

It does need COMPRESSING. Chromium writes VP8, and the published clips are VP9 - roughly half the
bytes at the same picture (SSIM 0.99), which matters because the site fetches a whole clip the
moment a thumbnail is pressed. Re-encode each render before publishing it:

```powershell
ffmpeg -i "$repo\tmp\rerecord-review\<clip>.webm" `
  -c:v libvpx-vp9 -b:v 0 -crf 32 -g 125 -row-mt 1 -deadline good -cpu-used 2 `
  -pix_fmt yuv420p -an "$repo\tmp\rerecord-publish\<clip>.webm"
```

This pass is also what makes the clip SEEKABLE: a browser recording carries no duration and no
cues, so its scrub bar is dead until it is written out again (SITE-VIDEO-06). The VP9 compression
used to happen by accident - as a side effect of the mask pass above - so when the mask went away
the clips silently reverted to VP8 and grew by nearly half again with nobody choosing it (#866). It
is now a required gate: `python "$repo\scripts\check_clip_codec.py"` fails a published clip that is
not VP9, and it needs no ffmpeg at all because the codec is plain text in the container header.

Then check the FINAL published bytes - the re-encoded files, not the renders they came from - and
check the clips you are replacing too, so a regression is obvious:

```powershell
python "$repo\scripts\check_clip_chrome.py" --require-ffmpeg <the re-encoded clips...>
```

That needs a full ffmpeg build; Playwright's bundled one is VP8-only and cannot decode the VP9
clips this publishes. Point `DEMO_CLIP_FFMPEG` at a real build if `ffmpeg` is not on PATH. The scan
reports how many frames it judged, so read that number. It judges only the frames whose chrome is
drawn AND unoccluded, so a clip with transitions legitimately judges fewer frames than it has - the
loop clip skips the handful where the report is still painted over the window - and a skipped frame
is still inspected at a coarser tolerance, so a fade never excuses a title that is plainly drawn. A
clip MOSTLY skipped is refused outright rather than passed on the remainder: that is what a clip
from an older recorder looks like here, because its chrome padding puts the terminal's first row
inside the band this gate reads. Re-record such a clip with the current recorder rather than
trusting a partial scan of it.

**The posters are a published surface too, and no gate scans them.** `site/src/poster-*.jpg` is the
first thing a reader sees, it carries the window chrome, and the launch command shipped in one once
before. A re-record makes the old posters stale as well as unchecked, so regenerate each poster from
its NEW clip and look at it before publishing - the scan only reads `.webm`.

`--allow-all` is what keeps an unattended capture from stalling: it covers tools, paths and URLs, so
no permission dialog can appear with nobody there to answer it. Be clear-eyed that it is the BROAD
grant, not just the path prompt the skill's own reference files trigger - which is the other reason
the session belongs in a scratch directory with nothing in it worth reaching.

The `ask` step records the text it sent into the cast mark, and `render` quotes THAT on the title
card, so the card can never drift from the session - which is why the ask is kept to one sentence,
and why `--ask` is only an override for a card that would otherwise be unreadable. Give the ask
`submitMs` of at least a second: Enter has to be a separate write once the composer has settled, or
the TUI takes the return as typed text and the session sits on a full prompt line forever.

The prompt is the whole recipe: `render` cannot fabricate a summary the session never produced. Ask
for the artifact you want on screen at the end (a `PANEL SUMMARY` table, a review bundle) and let the
`quit` step wait for it - but only ever wait for something the AGENT produces. A marker the recipe
itself typed is echoed back by the terminal within seconds, which silently reduces the step to a bare
idle wait; `normalizeScript` refuses that recipe at parse time rather than letting it cost you the
session. An agent may simply never print the marker even after doing the work, so read the closing
lines of a capture: a step that gave up says so there, and that cast is not the ending you asked for.

A capture does not stop when the interesting part does: the session keeps recording until the `quit`
step fires, so a cast normally carries a long idle tail (the multi-duck recording sat idle for 26
minutes between the summary and the `/exit`). `--until` cuts it, and `render` reports what it
dropped:

```powershell
node "$skill\tools\record_demo.mjs" render --cast "$repo\tmp\demo-video\duck.cast.json" `
  --until "PANEL SUMMARY" --until-gap 10 --seconds 38 --scale 0.6
```

`--until` cuts at the LAST occurrence of the marker, and it looks only AFTER the `ask` mark
(`--until-after` names a different one) - searching the whole cast would match the ASK, because the
prompt that asks for an artifact contains the marker word itself, and the clip would end where it
began. `--until-gap` then extends the cut to the last event before the session goes quiet for that
long, since the terminal repaints for a moment after the summary lands and cutting on the marker
alone ends the clip abruptly; it also works on its own, measured from the mark. A marker that never
appears is refused rather than silently rendering the whole tail - which is the expensive mistake,
because the clip looks fine until you watch its ending.

Keep `--until-gap` well BELOW the recipe's `quit` idle gate (`duck-session.json` uses 30s, so 10
here). The gap is a threshold to STOP at: if it is larger than the silence before the driver's
`/exit`, nothing stops the walk and the trim runs on through the dead air it was meant to remove.
`render` warns when a trim dropped nothing, which is what that mistake looks like.

The safety scan runs on the WHOLE cast before any trim, so trimming can never decide what the gate
gets to see.

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
  this tool (it was never scrubbed at source, and the home/account rules are per-machine). The gate
  scans TWO surfaces - the cast, and the `--ask` you passed, which is published on the title card
  but never touches the cast - and names the one that fired, because they are fixed by opposite
  actions: a dirty cast is re-captured or gets a new redaction rule, a dirty `--ask` is retyped.
  Reproduce an ask finding with `scan --cast <file> --ask "<text>"`; a bare `scan --cast` cannot
  see it.
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

**Everything visible in the terminal chrome is published too, not just the output.** The window
title bar is part of the frame, and it used to hold the launch command. On a real machine that
command is an inventory of internal tooling - which MCP servers you disable, which hosts you point
at - and none of it is a secret by any rule, so redaction cannot catch it. The chrome therefore
draws NOTHING at all now: a safe label is still text, and `scripts/check_clip_chrome.py` fails a
published clip whose title strip is not flat, so a clip with any title had to be masked by hand
before it could ship. Rendered empty, a clip is born publishable. The safe reduction is still
computed - the PROGRAM NAME only (`copilot`), with the path, any leading `NAME=value` environment
assignment, and every flag dropped, degrading to `session` for anything that is not a plausible bare
program name - and it is what the title card falls back to. Pass `--show-command` when the
invocation genuinely is the story: it publishes the whole command in the chrome, and on the title
card too whenever the cast has no ask of its own to state. Expect to mask that clip by hand.

**`--show-command` arms BOTH surfaces, and the louder one is the title card.** The flag reads like a
title-bar control, but the card's last fallback IS the chrome label, so for a cast with no `ask` mark
and no `-p` prompt the whole invocation is painted across the card at up to 30px - the largest type
in the clip - as well as into the chrome. That is the flag doing what it says (it is an explicit
opt-in to publishing the command), not a bug: use it only when you have read the command you are
about to publish. A cast that has something to state is unaffected - an `--ask`, an `ask` mark, or a
`-p` prompt still wins over the fallback, so the flag only ever fills a card that would otherwise
carry the safe label - the program name, or `session` when the command's shape cannot be trusted.
`render` and `loop` say so when it happens, quoting what the card will read, so the trap is caught
even by an operator who never read this paragraph.

**The title card is the loudest surface of all** - it is the largest type in the clip. It states the
prompt that was actually typed, and it is bounded: a `-p` prompt ends at its closing quote (or at the
next flag when unquoted), so flags written after the prompt never ride onto it. With no prompt and
no `--ask` it degrades to the program name rather than painting the whole invocation.

**Posters are a first-class review surface.** A poster is a frame of the clip, and on a web page it
loads on FIRST PAINT - so whatever is in it is seen without anyone pressing play. Review the poster
with the same eyes as the clip. This is not hypothetical: the launch command shipped in every frame
of two clips on the public site AND in their posters, past two review rounds, because the eye reads
a title bar as chrome rather than as content.

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
