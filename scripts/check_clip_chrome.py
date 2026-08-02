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

  * a TERMINAL frame is identified by its dark background where a browser frame is light;
  * on such a frame the title strip must be FLAT - a solid masked box, or empty chrome. Rendered
    text is high-contrast against that background, so any real spread in luminance means text.

It is deliberately not a text recogniser. "The strip is not flat" is the property that matters and
it cannot be argued with, whereas an OCR pass would invite a debate about confidence thresholds.
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
#   .chrome  padding-bottom 12px    -> the terminal starts at y=41  (video 25)
#
# The strip stops SHORT of the terminal. Running it to the bottom of the chrome block overlapped the
# terminal's first row, and that row's antialiased top read as a strip that is not flat - 14 frames
# of a clean clip flagged with no text anywhere near the title bar.
STRIP = "crop=iw-66:22:46:1"
# A patch from the MIDDLE of the frame, used only to tell a terminal frame from a browser one: the
# terminal is near-black there, a browser page is light. It is deliberately far from the title strip
# - an earlier version sampled the strip's own row, so the command text raised the reading and the
# leaking frames scored closer to a fade than to the terminal they plainly were.
KIND = "crop=400:200:200:200"
# Luminance spread above which the strip is carrying something drawn rather than a flat fill. A
# masked box measures 0; antialiased text on this theme measures far above this.
FLAT_TOLERANCE = 12.0
# Mean luminance below which a frame is UNAMBIGUOUSLY the terminal. Measured: a settled terminal
# frame reads 29-36 and the cross-fade jumps straight to 42 and climbs, so this sits in the gap.
# Being strict is what lets every terminal frame be judged - including the LAST ones in a segment,
# which is exactly where the mask ran out and the command was published.
TERMINAL_MAX_MEAN = 38.0
# Saturation above which the strip is holding something COLOURED. Nothing in the title bar is: the
# chrome is grey on near-black. The traffic lights are vivid, so this catches a clip whose scale
# pushed them into the strip, which otherwise surfaces as an unexplainable flatness failure.
LIGHTS_SATURATION = 80.0



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
    """Return the list of (t, spread) for frames whose terminal title strip is not flat."""
    strip = _measure(ffmpeg, clip, STRIP, ("YMIN", "YMAX", "SATMAX"))
    kind = _measure(ffmpeg, clip, KIND, ("YAVG",))

    if not strip:
        raise SystemExit("no frames decoded from %s" % clip)
    if len(strip) != len(kind):
        raise SystemExit("frame count mismatch reading %s (%d vs %d)" % (clip, len(strip), len(kind)))

    dark = [row["YAVG"] <= TERMINAL_MAX_MEAN for row in kind]
    bad = []
    for i, row in enumerate(strip):
        # EVERY unambiguously-terminal frame is judged, with no positional window. A cross-fade
        # frame is excluded because it is not unambiguously terminal, not because of where it sits -
        # so the last frames of a segment are still checked, and that is precisely where the mask
        # ran out and the command was published.
        if not dark[i]:
            continue
        # These offsets hold at the publish scale only. Rendered larger, the traffic lights land
        # inside the strip and every terminal frame "leaks" - a phantom that reads exactly like the
        # real thing and sends the operator hunting for text that is not there. Say so instead.
        if row["SATMAX"] > LIGHTS_SATURATION:
            raise SystemExit(
                "%s has colour in its title strip at t=%.2fs, which means the traffic lights are "
                "inside it: this clip was not rendered at the publish scale. Re-render it with "
                "--scale 0.6 (see the demo-video SKILL.md) and scan again." % (clip, row["t"]))
        if row["YMAX"] - row["YMIN"] > FLAT_TOLERANCE:
            bad.append((row["t"], row["YMAX"] - row["YMIN"]))
    return bad


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
    for clip in clips:
        bad = scan_clip(ffmpeg, clip)
        name = os.path.relpath(clip, REPO_ROOT)
        if bad:
            failed = True
            print("FAIL %s: %d frame(s) show text in the terminal title bar" % (name, len(bad)))
            for t, spread in bad[:8]:
                print("       t=%.2fs (luminance spread %.0f)" % (t, spread))
            if len(bad) > 8:
                print("       ... and %d more" % (len(bad) - 8))
        else:
            print("OK   %s" % name)
    if failed:
        print("\nA published clip is showing its launch command. Re-mask the WHOLE terminal segment "
              "(measure the boundaries, do not guess them), or re-record with the current recorder.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
