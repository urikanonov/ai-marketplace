#!/usr/bin/env python3
"""Fail if any published demo clip shows text in its terminal title bar.

The window chrome holds the launch command, which on a real machine is an inventory of internal
tooling (see #809). The recorder no longer publishes it, but a clip filmed by the OLD recorder is
patched by masking that strip with ffmpeg - and a mask is a hand-set thing that has already been
wrong once: the window in #807 stopped 0.44s before its terminal segment ended, so ten frames of a
published clip carried the whole command (#815).

Reviewing that by eye does not work. It survived two review rounds and a frame-by-frame check the
first time, because the eye reads a title bar as chrome rather than as content. So this checks every
frame mechanically instead:

  * a frame is JUDGED when the traffic lights are drawn, unfaded, at their canonical position -
    which is exactly the condition under which the strip beside them IS the title bar;
  * on such a frame the title strip must be FLAT - a solid masked box, or empty chrome. Rendered
    text is high-contrast against that background, so any real spread in luminance means text.

It is deliberately not a text recogniser. "The strip is not flat" is the property that matters and
it cannot be argued with, whereas an OCR pass would invite a debate about confidence thresholds.

Judging on the lights replaced a mid-frame luminance probe that stood in for "is this the terminal".
That proxy both dropped ~10% of plainly-terminal frames on the busiest clip (dense output raised the
mid-frame mean past its cut-off, and those are precisely the frames whose strip is most crowded) and
admitted cross-fade frames where the report slides OVER the chrome. The lights answer the real
question directly: they are only fully saturated at that spot when the chrome is on screen, settled,
and unoccluded.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIP_DIR = os.path.join("site", "dist", "assets")

# The regions below are in VIDEO pixels at the publish scale (`--scale 0.6`, what SKILL.md
# documents and every published clip uses). They do NOT scale with the frame size: the window chrome
# is styled in fixed CSS pixels, so it lands on the same video pixels whatever the terminal grid is.
# Two published clips of different shapes (864x540 and 1078x620) put their traffic lights on exactly
# the same pixels, which is why anchoring these offsets to the frame WIDTH would be wrong.
#
# What the offsets DO depend on is the scale, so a clip rendered at another one is measured in the
# wrong place - at scale 1 the lights sit inside the strip. That is diagnosed explicitly rather than
# reported as a phantom leak (see LIGHTS_SATURATION); the numbers come from the page CSS in
# `.github/skills/demo-video/tools/record_demo.mjs`, scaled by 0.6:
#   .wrap    padding 18px 20px      -> chrome starts at y=18, content is inset 20px each side
#   .dot     11px, gap 8px, three   -> the lights span x=20..69   (video 12..41)
#   .title   margin-left 8px        -> a window title starts at x=77  (video 46)
#   .chrome  padding-bottom 20px    -> the terminal starts at y=49  (video 29)
#
# The strip stops SHORT of the terminal, and the chrome's bottom padding is what buys that room.
# Running the strip to the bottom of the chrome block overlapped the terminal's first row, and that
# row's antialiased top read as a strip that is not flat - 14 frames of a clean clip flagged with no
# text anywhere near the title bar. Merely touching its edge was not enough either: with 12px of
# padding the worst judged frame measured a spread of 10 against a tolerance of 12, so the next
# re-record with slightly brighter top-row output would have failed. The separation is the fix.
STRIP = "crop=iw-66:22:46:1"
# The traffic lights. A frame is JUDGED only when they are fully drawn here, which is precisely when
# the strip beside them is the title bar: settled, on screen, and not faded under an overlay.
LIGHTS = "crop=30:6:12:11"
# A patch from the MIDDLE of the frame. It no longer decides which frames to JUDGE - the lights do -
# but it still answers one question they cannot: is there a terminal in this clip at all? Judging on
# the lights means a clip whose chrome sits somewhere else entirely (rendered at a much SMALLER
# scale, so the lights fall outside the crop) would otherwise read as "no chrome here" and pass
# unchecked, with its title equally far from the strip. A dark middle says a terminal IS on screen,
# so failing to find the chrome is a geometry problem rather than a browser-only clip.
KIND = "crop=400:200:200:200"
TERMINAL_MAX_MEAN = 38.0
# Saturation at which the lights are fully drawn. Measured: 83-93 unoccluded, and any cross-fade or
# overlay drops it well below. On the loop clip, admitting frames at 60 let the report panel's white
# edge into the strip (spread 86); at this value the same clip's worst judged frame measures 12.
LIGHTS_PRESENT = 80.0
# Below this ANYWHERE in a clip the window chrome was never found, which is only a legitimate pass
# when no terminal appears either (the browser-only clip peaks at 2). See scan_clip.
LIGHTS_ABSENT = 20.0
# Luminance spread above which the strip is carrying something drawn rather than a flat fill.
# Measured end to end at the publish scale, rendering the SAME cast both ways: a real leaked title
# (`--show-command`) reads 167, a clean terminal-only clip reads 8, and the loop clip - whose report
# panel cross-fades over the window - reads 12. This sits in that 13x gap with room on both sides.
# It used to sit at 12, i.e. exactly on the noise ceiling with zero margin, which is why a clean
# re-record kept landing one unit from failing.
FLAT_TOLERANCE = 40.0
# Saturation above which the STRIP is holding something COLOURED. Nothing in the title bar is: the
# chrome is grey on near-black. Measured, a judged frame's strip peaks at 15 while the lights read
# 83-93, so this sits in that gap - it catches a clip whose scale pushed the lights into the strip,
# which otherwise surfaces as an unexplainable flatness failure, without crying scale on a clean clip.
LIGHTS_SATURATION = 60.0
# The scale every published clip is rendered at, and the one these offsets describe.
PUBLISH_SCALE = 0.6


class ScaleMismatch(Exception):
    """A clip whose geometry these offsets do not describe, so its measurements mean nothing.

    Not a SystemExit: `main` scans a LIST, and aborting the whole run on the first bad clip hides
    every later clip's independent leak until the first is fixed and the gate rerun.
    """



def display_name(clip):
    """A short label for a clip, chosen so it can never take the scan down.

    `os.path.relpath` raises on Windows when the two paths sit on different drives, and this is only
    a label. Scanning a clip from OUTSIDE the checkout is the normal case - SKILL.md has the operator
    render to a scratch directory and pass the new clips in - so on a machine whose temp directory is
    on another drive than the repo, naming a clip used to abort the whole run before any verdict.
    """
    try:
        return os.path.relpath(clip, REPO_ROOT)
    except ValueError:
        return clip


def find_ffmpeg():
    """A full ffmpeg build. Playwright bundles a VP8-only one that cannot decode these clips, so it
    is deliberately not used here - it fails with 'no decoder found for: vp9'."""
    override = os.environ.get("DEMO_CLIP_FFMPEG")
    if override:
        return override if os.path.isfile(override) else None
    return shutil.which("ffmpeg")


def _measure(ffmpeg, clip, crop, keys):
    """Return a list of per-frame dicts of the requested signalstats keys.

    Read from ffmpeg's stderr rather than `metadata=print:file=`: a Windows path needs escaping
    inside a filter description, which is a portability trap for no benefit here."""
    chain = "%s,signalstats,metadata=print" % crop
    proc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "info", "-i", clip,
                           "-vf", chain, "-f", "null", "-"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("ffmpeg could not read %s: %s" % (clip, proc.stderr.strip()[-400:]))
    frames = []
    current = None
    for line in proc.stderr.splitlines():
        stamp = re.search(r"pts_time:([\d.]+)", line)
        if stamp:
            current = {"t": float(stamp.group(1))}
            frames.append(current)
            continue
        hit = re.search(r"lavfi\.signalstats\.(\w+)=([\d.\-]+)", line)
        if hit and current is not None and hit.group(1) in keys:
            current[hit.group(1)] = float(hit.group(2))
    # A parse that finds frames but not their measurements would sail through every later check:
    # a missing YAVG would read as "browser, skip" and a missing YMIN/YMAX as "perfectly flat".
    # That is the silent-failure mode this whole script exists to replace, so it is fatal here.
    for index, frame in enumerate(frames):
        missing = [k for k in keys if k not in frame]
        if missing:
            raise SystemExit("ffmpeg produced no %s for frame %d of %s; the signalstats output was "
                             "not understood, so the scan cannot be trusted"
                             % (", ".join(missing), index, clip))
    return frames


def scan_clip(ffmpeg, clip):
    """Return `(bad, judged)` - frames whose title strip is not flat, and how many were judged."""
    strip = _measure(ffmpeg, clip, STRIP, ("YMIN", "YMAX", "SATMAX"))
    lights = _measure(ffmpeg, clip, LIGHTS, ("SATMAX",))
    kind = _measure(ffmpeg, clip, KIND, ("YAVG",))

    if not strip:
        raise SystemExit("no frames decoded from %s" % clip)
    if not len(strip) == len(lights) == len(kind):
        raise SystemExit("frame count mismatch reading %s (%d, %d, %d)"
                         % (clip, len(strip), len(lights), len(kind)))

    drawn = [row["SATMAX"] >= LIGHTS_PRESENT for row in lights]
    brightest = max(row["SATMAX"] for row in lights)
    terminal_frames = sum(1 for row in kind if row["YAVG"] <= TERMINAL_MAX_MEAN)
    if not any(drawn):
        # The chrome was never found where these offsets expect it. That is only innocent when there
        # is no terminal in the clip at all - the browser-only demo, whose lights region peaks at 2.
        # Otherwise every measurement above was taken somewhere meaningless, and passing would be a
        # gate that checked nothing while reporting OK. Note this catches a clip rendered SMALLER
        # than the publish scale, where the lights fall outside the crop entirely and the leaked
        # title falls left of the strip - the mirror of the over-scaled case below.
        if terminal_frames == 0 and brightest < LIGHTS_ABSENT:
            return [], 0
        raise ScaleMismatch(
            "%s shows a terminal on %d frame(s) but its window chrome never appears where these "
            "offsets expect it (lights peak at %.0f), so no frame could be judged: it was not "
            "rendered at the publish scale. Re-render it with --scale %s (see the demo-video "
            "SKILL.md)." % (clip, terminal_frames, brightest, PUBLISH_SCALE))

    bad = []
    judged = 0
    for i, row in enumerate(strip):
        # EVERY frame showing settled chrome is judged, with no positional window. A cross-fade
        # frame is excluded because its lights are not fully drawn, not because of where it sits -
        # so the last frames of a segment are still checked, and that is precisely where the mask
        # ran out and the command was published.
        if not drawn[i]:
            continue
        judged += 1
        # These offsets hold at the publish scale only. Rendered larger, the traffic lights land
        # inside the strip and every terminal frame "leaks" - a phantom that reads exactly like the
        # real thing and sends the operator hunting for text that is not there. Say so instead.
        if row["SATMAX"] > LIGHTS_SATURATION:
            raise ScaleMismatch(
                "%s has colour in its title strip at t=%.2fs, which means the traffic lights are "
                "inside it: this clip was not rendered at the publish scale. Re-render it with "
                "--scale %s (see the demo-video SKILL.md) and scan again." % (clip, row["t"], PUBLISH_SCALE))
        if row["YMAX"] - row["YMIN"] > FLAT_TOLERANCE:
            bad.append((row["t"], row["YMAX"] - row["YMIN"]))
    return bad, judged


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clips", nargs="*", help="clips to scan (default: every published clip)")
    parser.add_argument("--require-ffmpeg", action="store_true",
                        help="fail instead of skipping when ffmpeg is unavailable (used by CI, "
                             "where a skipped scan would be a green gate that checked nothing)")
    args = parser.parse_args(argv)

    ffmpeg = find_ffmpeg()
    clips = args.clips
    if not clips:
        directory = os.path.join(REPO_ROOT, CLIP_DIR)
        clips = [os.path.join(directory, n) for n in sorted(os.listdir(directory))
                 if n.endswith(".webm")]
    if not clips:
        raise SystemExit("no published clips found under %s" % CLIP_DIR)

    if not ffmpeg:
        message = ("no ffmpeg on PATH (set DEMO_CLIP_FFMPEG to override). Playwright's bundled "
                   "ffmpeg is VP8-only and cannot decode these clips.")
        if args.require_ffmpeg:
            # Fail CLOSED. A gate that goes green having scanned nothing is worse than no gate,
            # because it reads as proof the clips were checked.
            raise SystemExit("check_clip_chrome: FAILED - " + message)
        # Locally, degrade rather than fail, but say so loudly instead of reporting a pass.
        print("check_clip_chrome: SKIPPED - " + message)
        return 0

    failed = False
    mis_scaled = False
    for clip in clips:
        name = display_name(clip)
        try:
            bad, judged = scan_clip(ffmpeg, clip)
        except ScaleMismatch as problem:
            # Keep going: every clip gets its own verdict in one run, so a second problem elsewhere
            # is not hidden behind the first.
            failed = True
            mis_scaled = True
            print("FAIL %s: %s" % (name, problem))
            continue
        if bad:
            failed = True
            print("FAIL %s: %d of %d judged frame(s) show text in the terminal title bar"
                  % (name, len(bad), judged))
            for t, spread in bad[:8]:
                print("       t=%.2fs (luminance spread %.0f)" % (t, spread))
            if len(bad) > 8:
                print("       ... and %d more" % (len(bad) - 8))
        else:
            # Say what was inspected. A gate that will not report its own coverage cannot be
            # audited, and "judged 3" and "judged 1040" both used to print the same word.
            print("OK   %s (judged %d frame(s))" % (name, judged)
                  if judged else "OK   %s (no window chrome to check)" % name)
    if failed:
        if not mis_scaled:
            print("\nA published clip is showing its launch command. Re-mask the WHOLE terminal "
                  "segment (measure the boundaries, do not guess them), or re-record with the "
                  "current recorder.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
