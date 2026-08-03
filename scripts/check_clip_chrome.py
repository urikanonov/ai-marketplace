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

  * a frame is JUDGED when the traffic lights are drawn, unfaded, at their canonical position AND
    the chrome's empty gutter - the padding row between the title and the terminal - is flat, which
    together mean the strip beside the lights IS the title bar and nothing is painted over it;
  * on such a frame the title strip must be FLAT - a solid masked box, or empty chrome. Rendered
    text is high-contrast against that background, so any real spread in luminance means text;
  * a frame skipped for occlusion is still LOOKED AT, at a coarser tolerance no report ghost can
    reach, so a fade can never excuse a title that is plainly drawn (see OCCLUDED_LEAK_TOLERANCE),
    and a clip that is MOSTLY skipped is refused rather than passed on the remainder.

It is deliberately not a text recogniser. "The strip is not flat" is the property that matters and
it cannot be argued with, whereas an OCR pass would invite a debate about confidence thresholds.

The published POSTERS are scanned too, and they are the surface a reader sees FIRST - a poster loads
on first paint, so whatever is in it is seen without anyone pressing play, and the command shipped in
one already. A poster is a whole frame of its clip, uniformly downscaled (864x540 -> 800x500 and
1078x620 -> 800x460 are both isotropic), so it gets no geometry of its own: it is scaled BACK to its
clip's frame and measured by the very probes above, at the very same tolerances. A second pass then
asks whether it still DEPICTS a frame of that clip, because a re-record keeps the clip's filename and
left the old poster in place with nothing failing (see poster_similarity).

Judging on the lights replaced a mid-frame luminance probe that stood in for "is this the terminal".
That proxy both dropped ~10% of plainly-terminal frames on the busiest clip (dense output raised the
mid-frame mean past its cut-off, and those are precisely the frames whose strip is most crowded) and
admitted cross-fade frames where the report slides OVER the chrome. The lights answer the real
question directly: they are only fully saturated at that spot when the chrome is on screen and
settled. What they cannot see is the END of a fade, where they are back to full saturation while the
report is still faintly painted on top - so the gutter answers that half separately (see GUTTER).
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
# The chrome's EMPTY GUTTER: the full-width band of its bottom padding, between the row a title is
# drawn on and the terminal's first row. Nothing is ever drawn there on a settled frame, whatever
# the terminal is printing - so content there means something is painted OVER the window. (A title
# long enough to WRAP would reach it, at a measured y of 31 against a band at 24-25; that is not a
# hole, because an occluded frame is still inspected at OCCLUDED_LEAK_TOLERANCE and a wrapped
# title's first line reads far above it.)
#
# That is the one thing the lights cannot see. They reach full saturation at the END of a cross-fade
# while the report panel is still faintly painted on top, so the strip beside them carries a ghost
# of report content and was judged anyway: on the published loop clip the worst judged frame read a
# spread of 33 against a tolerance of 40, at exactly the browser-to-terminal fade, while the
# non-cross-fade frames read a median of 7. The margin the tolerance was widened to 40 to buy was
# being spent on frames that are not the title bar at all. Excluding them is the fix; widening the
# tolerance further is the direction this gate exists to refuse.
#
# The band is written EVEN - an even y offset and an even height - because these clips are yuv420p,
# where the chroma planes are half resolution, and ffmpeg snaps an odd crop to the nearest even one.
# `crop=iw:3:0:24` measures rows 24-25, not 24-26, and a band written at y=23 silently measures the
# same rows as one written at y=22. Say what is actually measured rather than what was intended.
GUTTER = "crop=iw:2:0:24"
# Luminance spread above which the gutter is carrying something painted over the window. Measured
# over the loop clip's 598 judged frames: at most 19 on a settled frame, 24-44 while the report is
# still on top, and nothing in between. Unlike the strip's tolerance this one can afford to be
# tight - dropping a settled frame costs one frame of coverage out of hundreds, while calling a
# clean frame a leak sends the operator hunting for text that is not there. It sits in the MIDDLE of
# the empty band rather than beside either edge, so neither a slightly noisier settled frame nor a
# slightly fainter ghost is the first thing to cross it.
GUTTER_TOLERANCE = 21.0
# Luminance spread above which a frame's strip is carrying a real title EVEN THOUGH its chrome is
# occluded, so it is reported rather than exempted by the fade it happened to land on. An occluded
# frame is not the title bar and is not judged, but "not judged" must not mean "not looked at": the
# #815 leak sat on the last frames of a segment, which is exactly where a transition begins, and a
# leaked title long enough to wrap would itself put ink in the gutter and so exempt its own frame.
#
# Both bounds are arithmetic on the overlay, not a guess. The overlay is FAINT wherever the lights
# still read as drawn - past about 15% it drags their saturation under LIGHTS_PRESENT - so with the
# composite `out = (1-a)*window + a*report` and a <= 0.15: a ghost on flat chrome cannot spread more
# than 0.15*255 = 38 (measured worst: 33), and a real title cannot spread LESS than
# 0.85*167 - 0.15*255 = 104 even if the report's own content lands exactly out of phase with it
# (measured unattenuated: 167). This sits between those two worst cases rather than beside either.
OCCLUDED_LEAK_TOLERANCE = 70.0
# Share of chrome-showing frames that may be skipped as occluded before the clip's verdict means
# nothing. A transition is a small fraction of any real clip - the loop clip, the only published one
# with a report fading over the window, skips 3.5% - so a clip half painted over was not measured,
# it was guessed at, and passing it would be a gate reporting a pass it did not earn. The comparison
# is inclusive: exactly half skipped is already implausible for a clip whose transitions are seconds
# out of a minute.
MAX_OCCLUDED_SHARE = 0.5
# Frames that must show the chrome, as a share of the frames that could plausibly have shown it,
# before the clip was scanned at all. The lights finding the chrome on a HANDFUL of frames is not
# the innocent case that `LIGHTS_ABSENT` covers - it is a clip whose geometry these offsets nearly
# miss, and judging those few would report a confident OK on a scan of almost nothing. The
# denominator takes whichever is larger of the frames that LOOK like a terminal and the frames whose
# lights are at least partly lit, so neither axis can collapse quietly: measured, the published
# clips sit at 1.18 and 1.11 against the first, and 93% and 99.6% against the second.
MIN_CHROME_SHARE = 0.5
# A patch from the MIDDLE of the frame. It no longer decides which frames to JUDGE - the lights do -
# but it still answers one question they cannot: is there a terminal in this clip at all? Judging on
# the lights means a clip whose chrome sits somewhere else entirely (rendered at a much SMALLER
# scale, so the lights fall outside the crop) would otherwise read as "no chrome here" and pass
# unchecked, with its title equally far from the strip. A dark middle says a terminal IS on screen,
# so failing to find the chrome is a geometry problem rather than a browser-only clip.
KIND = "crop=400:200:200:200"
TERMINAL_MAX_MEAN = 38.0
# Saturation at which the lights are fully drawn. Measured on the published clips: the drawn
# population reads 81-94 on the loop clip and 80-100 on the multi-duck clip, and any cross-fade or
# overlay drops it well below. On the loop clip, admitting frames at 60 let the report panel's white
# edge into the strip (spread 86); at this value the same clip's worst judged frame measures 11.
# The dimmest drawn frame sits ON this threshold, so drift costs coverage rather than correctness -
# and coverage is floored below (MIN_CHROME_SHARE), which is what makes that trade safe.
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
# A poster and the clip it was cut from, which sit beside each other in the published assets:
# `poster-multi-duck.jpg` is a frame of `demo-multi-duck.webm`. The pairing is by NAME because the
# poster carries no record of where it came from, and both halves of the poster gate are questions
# asked of the clip - the frame size to measure the poster at, and the frames it must still depict.
POSTER_PREFIX = "poster-"
POSTER_SUFFIXES = (".jpg", ".jpeg")
CLIP_PREFIX = "demo-"
CLIP_SUFFIX = ".webm"
# How far a poster's width and height scales may disagree before it is not a WHOLE frame of its clip
# any more. Scaling it back only recovers the clip's geometry because one factor produced it; a
# cropped or letterboxed poster stretches under that scale and carries its chrome somewhere the
# offsets do not describe, so the flatness it then measured would mean nothing. The published pairs
# agree to within 0.0003 (1078/800 = 1.34750 against 620/460 = 1.34783), which is integer rounding
# in the publish step rather than a shape difference.
#
# This does NOT catch a crop that happens to keep the clip's aspect ratio, and it does not need to:
# the freshness match below is far more sensitive to a crop than to a frame choice, because a crop
# misaligns every structure in the picture at once. Measured on the multi-duck clip, cropping just
# 1% and rescaling drops the best match to 0.7624 (5%: 0.7517) - below anything a real pair reads -
# while a poster cut from a DIFFERENT frame of its own clip still scores 0.978+. A centred crop
# additionally drags the terminal's first row into the strip and reports THAT, and a large one moves
# the lights off their probe and is refused as a scale mismatch. All three refuse; none passes.
POSTER_ASPECT_TOLERANCE = 0.01
# Structural similarity below which a poster no longer depicts any frame of the clip it ships beside.
# Measured with ffmpeg's ssim filter over every frame of each published clip: the three real pairs
# score 0.9894, 0.9900 and 0.9906, while a poster paired with the wrong clip scores 0.7406, 0.7576
# and 0.7970. This sits in that gap, nearer the mismatched side - a re-encode of the SAME frame at
# another JPEG quality still scores 0.98, so the tolerance an operator needs is small, while the
# thing being caught is a poster left over from a recording that no longer exists.
POSTER_MATCH_MIN = 0.95
# Frames the freshness pass must have compared before its verdict means anything. It reads the
# poster against EVERY frame of the clip, so a run that compared a handful did not answer the
# question - it answered a different, much easier one, and could pass a stale poster that happens
# to resemble the clip's opening frame. This is not hypothetical: writing the same comparison with
# `shortest=1` compared exactly ONE frame and reported a best match of 0.44 on a poster that in
# fact matches at 0.99. A second of video is far below any published clip (the shortest is 769
# frames) and far above that degenerate case.
POSTER_MATCH_MIN_FRAMES = 25
# What to do about an artifact this gate could not read, which is a different instruction for each
# surface. A clip is RENDERED, so it is re-rendered or re-recorded; a poster is not rendered at all -
# it is CUT from a clip - so telling its operator to "re-render it with --scale 0.6" names a knob
# the poster does not have and points at the wrong file. The whole reason these messages exist is to
# say which artifact to go and fix, so the two are kept apart rather than sharing clip-only wording.
RENDER_ADVICE = {
    "clip": "Re-render it with --scale %s (see the demo-video SKILL.md)." % PUBLISH_SCALE,
    "poster": "Cut it again from a full frame of its clip, which must itself be rendered with "
              "--scale %s (see the demo-video SKILL.md)." % PUBLISH_SCALE,
}
SETTLE_ADVICE = {
    "clip": "Re-record it, or check that its transitions settle.",
    "poster": "Cut it from a SETTLED frame of its clip - this one is mid-transition.",
}
RECORDER_ADVICE = {
    "clip": "Re-scan a clip from the current recorder, or re-record this one.",
    "poster": "Cut it from a settled frame of a clip filmed by the current recorder.",
}


class Unscannable(Exception):
    """A clip no frame of which could be judged, so its verdict would mean nothing.

    Not a SystemExit: `main` scans a LIST, and aborting the whole run on the first bad clip hides
    every later clip's independent leak until the first is fixed and the gate rerun.
    """


class ScaleMismatch(Unscannable):
    """A clip whose geometry these offsets do not describe, so its measurements mean nothing."""


class ChromeOccluded(Unscannable):
    """A clip whose chrome is painted over on all, or implausibly many, of the frames showing it."""


class PosterUnpaired(Unscannable):
    """A poster with no clip beside it, so neither question this gate asks can be answered."""


class ProbeFailed(Unscannable):
    """A probe of ONE file that ffmpeg could not complete, so that file has no verdict.

    An `Unscannable` rather than a `SystemExit` because it is a fact about the file, not about the
    tool: a poster ffmpeg cannot read must not stop the run before a LATER poster - possibly a
    leaking one - has been looked at. It still fails the run, exactly like every other Unscannable.
    """


class StalePoster(Unscannable):
    """A poster that no longer depicts any frame of the clip it is published beside."""


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
    """A full ffmpeg build. Playwright bundles a VP8-only one that cannot decode the published
    clips, so it is deliberately not used here - it fails with 'no decoder found for: vp9'.

    That the clips ARE VP9 is not left to chance: `scripts/check_clip_codec.py` gates it, because
    they reverted to VP8 once when the pass that happened to encode them went away (#866). Scan the
    FINAL published bytes rather than the render they came from - the compression pass is what a
    published clip actually ships."""
    override = os.environ.get("DEMO_CLIP_FFMPEG")
    if override:
        return override if os.path.isfile(override) else None
    return shutil.which("ffmpeg")


def _measure(ffmpeg, clip, crop, keys, prefix=""):
    """Return a list of per-frame dicts of the requested signalstats keys.

    `prefix` is filter text applied BEFORE the crop, and it is how a poster is measured by the
    clip's own offsets: scaled back to the clip's frame, the poster is a one-frame clip.

    Read from ffmpeg's stderr rather than `metadata=print:file=`: a Windows path needs escaping
    inside a filter description, which is a portability trap for no benefit here."""
    chain = "%s%s,signalstats,metadata=print" % (prefix, crop)
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


def scan_clip(ffmpeg, clip, prefix="", surface="clip"):
    """Return `(bad, judged, occluded)` - frames whose title strip is not flat, how many frames were
    judged, and how many showed the chrome with something painted over it.

    `prefix` is filter text applied before every probe (see `_measure`); the poster path uses it to
    put a poster back on its clip's frame and luminance scale, so both surfaces are read by one
    implementation. `surface` only chooses which instruction a refusal ends with - a poster is cut,
    not rendered, so clip-only advice would name a knob it does not have.

    On a POSTER there is exactly one frame, which sharpens two of the rules below: the coverage
    floor (`MIN_CHROME_SHARE`) can never fire, since one frame is never under half of one, and the
    occlusion floor becomes all-or-nothing - a single frame whose gutter is not clear is the whole
    clip's worth of occlusion, so it is refused rather than averaged away. Both harden rather than
    loosen, and the second is why a poster must be cut from a SETTLED frame."""
    render_advice = RENDER_ADVICE[surface]
    name = display_name(clip)
    strip = _measure(ffmpeg, clip, STRIP, ("YMIN", "YMAX", "SATMAX"), prefix)
    lights = _measure(ffmpeg, clip, LIGHTS, ("SATMAX",), prefix)
    gutter = _measure(ffmpeg, clip, GUTTER, ("YMIN", "YMAX"), prefix)
    kind = _measure(ffmpeg, clip, KIND, ("YAVG",), prefix)

    if not strip:
        raise SystemExit("no frames decoded from %s" % clip)
    if not len(strip) == len(lights) == len(gutter) == len(kind):
        raise SystemExit("frame count mismatch reading %s (%d, %d, %d, %d)"
                         % (clip, len(strip), len(lights), len(gutter), len(kind)))
    # Equal lengths are not alignment. The four probes are four independent decodes, and they are
    # combined BY INDEX, so a run that dropped one frame and duplicated another would line the
    # gutter of one frame up with the strip of its neighbour - and judge the wrong pair with no
    # symptom at all. Each probe reports its own presentation timestamp, so make them agree.
    for i, row in enumerate(strip):
        for other in (lights, gutter, kind):
            if abs(other[i]["t"] - row["t"]) > 1e-6:
                raise SystemExit("frame %d of %s carries different timestamps across the probes "
                                 "(%.3f vs %.3f), so the measurements cannot be matched up"
                                 % (i, clip, row["t"], other[i]["t"]))

    drawn = [row["SATMAX"] >= LIGHTS_PRESENT for row in lights]
    brightest = max(row["SATMAX"] for row in lights)
    # Frames where the chrome is at least PARTLY lit. A frame whose lights fall just under
    # LIGHTS_PRESENT is not judged and not counted as occluded either, so without this the coverage
    # floor below would be blind on that axis: a clip whose chrome reads as faded almost everywhere
    # would pass on the handful that made it through, which is the same 5%-coverage pass the
    # occlusion floor exists to stop.
    lit_frames = sum(1 for row in lights if row["SATMAX"] >= LIGHTS_ABSENT)
    terminal_frames = sum(1 for row in kind if row["YAVG"] <= TERMINAL_MAX_MEAN)
    if not any(drawn):
        # The chrome was never found where these offsets expect it. That is only innocent when there
        # is no terminal in the clip at all - the browser-only demo, whose lights region peaks at 2.
        # Otherwise every measurement above was taken somewhere meaningless, and passing would be a
        # gate that checked nothing while reporting OK. Note this catches a clip rendered SMALLER
        # than the publish scale, where the lights fall outside the crop entirely and the leaked
        # title falls left of the strip - the mirror of the over-scaled case below.
        if terminal_frames == 0 and brightest < LIGHTS_ABSENT:
            return [], 0, 0
        if terminal_frames == 0:
            # Chrome is on screen but never settles: naming the scale here would be the wrong
            # diagnosis for a clip that is all transition.
            raise ChromeOccluded(
                "%s never shows its window chrome settled (its traffic lights peak at %.0f, under "
                "the %.0f a drawn light reads), so no frame could be judged. %s"
                % (name, brightest, LIGHTS_PRESENT, SETTLE_ADVICE[surface]))
        raise ScaleMismatch(
            "%s shows a terminal on %d frame(s) but its window chrome never appears where these "
            "offsets expect it (lights peak at %.0f), so no frame could be judged: it was not "
            "rendered at the publish scale. %s"
            % (name, terminal_frames, brightest, render_advice))

    bad = []
    suspect = []
    judged = 0
    occluded = 0
    worst_occluded = 0.0
    coloured = None
    for i, row in enumerate(strip):
        # EVERY frame showing settled, unoccluded chrome is judged, with no positional window. A
        # cross-fade frame is excluded because its chrome is faded or painted over, not because of
        # where it sits - so the last frames of a segment are still checked, and that is precisely
        # where the mask ran out and the command was published.
        if not drawn[i]:
            continue
        spread = row["YMAX"] - row["YMIN"]
        # The lights are fully saturated again at the END of a cross-fade while the report is still
        # painted faintly over the window, so the strip is not the title bar on such a frame - what
        # it carries is a ghost of report content, and judging it spends the flatness margin on
        # something that is not chrome at all.
        gutter_spread = gutter[i]["YMAX"] - gutter[i]["YMIN"]
        if gutter_spread > GUTTER_TOLERANCE:
            occluded += 1
            worst_occluded = max(worst_occluded, gutter_spread)
            # Not judged is not the same as not looked at. The overlay is faint wherever the lights
            # still read as drawn, so a real title keeps most of its contrast - and a leaked title
            # long enough to wrap would put ink in the gutter and exempt its own frame. Report it
            # rather than let a fade excuse it. This runs whatever the strip's colour says: colour
            # is a hint about SCALE, and letting it short-circuit the check would hand a leak the
            # one exemption this branch exists to deny.
            if spread > OCCLUDED_LEAK_TOLERANCE:
                suspect.append((row["t"], spread))
            if row["SATMAX"] > LIGHTS_SATURATION:
                # Colour here is either a mis-scaled clip (the lights inside the strip) or a
                # coloured ghost. Do not decide from one frame: remember it, and let the verdict
                # below say "scale" only if the whole clip turned out to be unreadable.
                coloured = coloured if coloured is not None else row["t"]
            continue
        # These offsets hold at the publish scale only. Rendered larger, the traffic lights land
        # inside the strip and every terminal frame "leaks" - a phantom that reads exactly like the
        # real thing and sends the operator hunting for text that is not there. Say so instead.
        if row["SATMAX"] > LIGHTS_SATURATION:
            raise ScaleMismatch(
                "%s has colour in its title strip at t=%.2fs, which means the traffic lights are "
                "inside it: it was not rendered at the publish scale. %s Then scan it again."
                % (name, row["t"], render_advice))
        judged += 1
        if spread > FLAT_TOLERANCE:
            bad.append((row["t"], spread))
    chrome_frames = judged + occluded
    scannable = max(terminal_frames, lit_frames)
    if suspect and len(suspect) * 2 >= occluded:
        # A title-sized spread on the ODD skipped frame is weak evidence - on a clip whose geometry
        # this gate does not describe it is as likely to be terminal output bleeding into the strip.
        # On MOST of them it is a signature: that is what a leaked title long enough to wrap looks
        # like, since its own ink is what dirties the gutter. Promote it to the verdict.
        bad.extend(suspect)
        suspect = []
    # A leak found on a JUDGED frame outranks any complaint about coverage: both fail the run, but
    # only one of them tells the operator there is a command on screen, and swallowing that into a
    # generic "this clip could not be read" would bury the finding this gate exists to make. A hit
    # on a SKIPPED frame is weaker evidence - the frame is not the title bar by definition - so it
    # does not overrule the diagnosis, but it is named in it rather than dropped.
    if not bad and (not judged
                    or occluded >= MAX_OCCLUDED_SHARE * chrome_frames
                    or chrome_frames < MIN_CHROME_SHARE * scannable):
        note = ""
        if suspect:
            note = (" %d of the skipped frame(s) carry a title-sized spread (worst %.0f at "
                    "t=%.2fs), so look at them by eye before trusting this clip."
                    % (len(suspect), max(s for _, s in suspect),
                       max(suspect, key=lambda hit: hit[1])[0]))
        # Every skipped frame is a frame not checked, so a clip MOSTLY skipped must fail rather than
        # print a bare OK on the handful that survived - the same rule the lights already follow
        # above. All-or-nothing would not do: the published loop clip of an older recorder, whose
        # chrome padding put the terminal's first row inside this band, judges 23 of its 448 chrome
        # frames and would otherwise pass at 5% coverage, which reads exactly like a clean scan.
        if coloured is not None:
            raise ScaleMismatch(
                "%s has colour in its title strip at t=%.2fs and its chrome reads as painted over "
                "on %d of %d frame(s): the probes are not landing on the chrome, which is what a "
                "clip rendered at another scale looks like. %s Then scan it again.%s"
                % (name, coloured, occluded, chrome_frames, render_advice, note))
        if chrome_frames < MIN_CHROME_SHARE * scannable:
            # The lights found the chrome, but on so few frames that judging them would report a
            # confident OK on a scan of almost nothing. Measured, the published clips show settled
            # chrome on more frames than look like a terminal and on 93-99% of the frames whose
            # lights are lit at all, so this is a geometry problem rather than a clip that simply
            # has few terminal moments.
            raise ScaleMismatch(
                "%s could have shown its window chrome on %d frame(s) but it is only found settled "
                "on %d of them, so almost nothing could be scanned: these offsets are not landing "
                "on its chrome. %s%s"
                % (name, scannable, chrome_frames, render_advice, note))
        raise ChromeOccluded(
            "%s shows its window chrome on %d frame(s) but something is painted over it on %d of "
            "them (worst gutter spread %.0f), so %s. Either the chrome does not match the "
            "geometry this gate measures - an older recorder, or a hand-applied mask whose box "
            "crosses the chrome's bottom padding - or its transitions never settle. %s%s"
            % (name, chrome_frames, occluded, worst_occluded,
               "no frame could be judged" if not judged else "only %d could be judged" % judged,
               RECORDER_ADVICE[surface], note))
    return sorted(bad + suspect), judged, occluded


def is_poster(path):
    """Whether a path names a published poster rather than a clip."""
    name = os.path.basename(path).lower()
    return name.startswith(POSTER_PREFIX) and name.endswith(POSTER_SUFFIXES)


def poster_clip(poster):
    """The clip a poster was cut from: `poster-X.jpg` pairs with `demo-X.webm` beside it.

    The stem is lower-cased, because `is_poster` matched the name that way: taking the stem in its
    original case would resolve `Poster-X.JPG` to `demo-X.webm` and fail as unpaired on a
    case-sensitive filesystem, which is the one place this runs in CI."""
    directory, name = os.path.split(poster)
    stem = os.path.splitext(name)[0].lower()[len(POSTER_PREFIX):]
    return os.path.join(directory, CLIP_PREFIX + stem + CLIP_SUFFIX)


def poster_prefix(clip_width, clip_height):
    """The filter text that puts a poster back on its clip's frame AND its clip's luminance scale.

    The scale-back is the point of the poster path, but it is not enough on its own. A published
    poster is a JPEG, so ffmpeg reads it as `yuvj420p` - FULL range, Y on 0-255 - while every
    published clip is `yuv420p(tv)`, LIMITED range on 16-235, which is the scale every tolerance in
    this file was measured against. Left alone, the poster is read 255/219 = 1.164x expanded:
    measured, the multi-duck poster's title strip reads 13-17 where the very same frame of its clip
    reads 28-31. That direction is safe for the flatness tolerance (it only makes it stricter) but
    not for the gutter: a settled frame near the clip's measured ceiling of 19 would land at 22,
    over `GUTTER_TOLERANCE`, and be refused as painted over - a false failure on a clean poster,
    made sharp by the fact that a poster is ONE frame with no other frames to average it out.

    `format=yuv420p` alone does NOT do it (measured: byte-identical readings), because it changes
    the pixel layout and not the range. The second `scale` stage with an explicit `out_range` is
    what converts, and it is written without an `in_range` so ffmpeg uses whatever the file itself
    declares rather than this code assuming. Applied to a clip that is already limited it is a
    no-op (verified: identical readings), so it says "measure on the clip's scale" rather than
    "convert a JPEG"."""
    return "scale=%d:%d,format=yuv420p,scale=out_range=limited," % (clip_width, clip_height)


def _dimensions(ffmpeg, path):
    """The frame size ffmpeg reports for a file's first video stream.

    Parsed from the INPUT header only: the output and stream-mapping lines repeat a size, and after
    a filter has run that size is the filter's, not the file's. A poster whose own size were read
    off the scaled output would agree with its clip no matter what shape it really was.

    The FIRST video stream is the right one to read because it is the one every filter chain here
    consumes - `[0:v]` and the default `-vf` mapping both take it - so this cannot disagree with
    what was actually measured. (A clip carrying a second video stream, an attached cover image
    say, is refused outright by `check_clip_codec.py`, which requires exactly one video track.)"""
    proc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "info", "-i", path,
                           "-frames:v", "1", "-f", "null", "-"], capture_output=True, text=True)
    for line in proc.stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("Output #") or stripped.startswith("Stream mapping"):
            break
        if ": Video: " not in line:
            continue
        hit = re.search(r"[ ,](\d{2,5})x(\d{2,5})[ ,]", line)
        if hit:
            width, height = int(hit.group(1)), int(hit.group(2))
            if width > 0 and height > 0:
                return width, height
    raise ProbeFailed("ffmpeg did not report a usable frame size for %s, so it cannot be measured: "
                      "%s" % (display_name(path), proc.stderr.strip()[-400:]))


def poster_similarity(ffmpeg, poster, clip, width, height):
    """The best structural similarity between a poster and ANY frame of its clip.

    A poster is published beside a clip that keeps its filename across a re-record, so nothing used
    to fail when the recording changed and the poster went on showing the old one. Asking whether
    the poster still depicts SOME frame of the current clip is the mechanical form of that question,
    and it needs no record of which frame was cut: ffmpeg holds the poster still against every frame
    in one pass. Both sides are compared at the poster's own size, which is where the publish step
    made the comparison in the first place.

    The poster is a single-frame input and the CLIP drives the timeline: ssim's frame sync repeats
    the last frame of an input that has ended, so the comparison runs to the clip's last frame and
    stops there. `-loop 1` with `shortest=1` measures the same thing (verified: identical best match
    over 1600 frames) but takes three times as long and leans on two more options, one of which - a
    demuxer loop - runs forever if the other is not honoured."""
    chain = ("[0:v]scale=%d:%d,format=yuv420p[a];[1:v]format=yuv420p[b];"
             "[a][b]ssim=stats_file=-" % (width, height))
    proc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", clip,
                           "-i", poster, "-filter_complex", chain, "-f", "null", "-"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        # A run that failed PART WAY still printed the frames it got to, and a poster that matched
        # one of them would be reported fresh on a comparison that never reached the rest of the
        # clip. The frame floor below does not cover that: a decode that dies after a second is
        # already past it. So the exit status is checked first and on its own.
        raise ProbeFailed("ffmpeg failed comparing %s against %s (exit %d), so the poster's "
                          "freshness was not measured: %s"
                          % (display_name(poster), display_name(clip), proc.returncode,
                             proc.stderr.strip()[-400:]))
    best = None
    compared = 0
    for line in proc.stdout.splitlines():
        hit = re.search(r"\bAll:(\S+)", line)
        if not hit:
            continue
        try:
            value = float(hit.group(1))
        except ValueError:
            value = float("nan")
        # `inf` and `nan` are not scores. Skipping them silently would let a run of unusable
        # measurements still satisfy the frame floor below on whatever few rows did parse.
        if not -1.0 <= value <= 1.0:
            raise ProbeFailed("ffmpeg reported an unusable similarity (%s) comparing %s against "
                              "%s, so the poster's freshness cannot be trusted"
                              % (hit.group(1), display_name(poster), display_name(clip)))
        compared += 1
        best = value if best is None else max(best, value)
    if compared < POSTER_MATCH_MIN_FRAMES:
        # No verdict, or a verdict on almost nothing. Either way reporting a match would be the
        # pass-having-checked-nothing this whole script is written against, so it fails rather
        # than passes - and it is not reported as a stale poster, which would send the operator
        # re-cutting a poster whose only problem is that ffmpeg was not understood.
        raise ProbeFailed("ffmpeg compared %d frame(s) of %s against %s, under the %d a verdict on "
                          "the poster's freshness needs: %s"
                          % (compared, display_name(clip), display_name(poster),
                             POSTER_MATCH_MIN_FRAMES, proc.stderr.strip()[-400:]))
    return best


def scan_poster(ffmpeg, poster):
    """Return `(bad, judged, occluded, similarity)` for a published poster.

    A poster is a whole frame of its clip, scaled by one factor, so it is put BACK at that frame's
    size and handed to `scan_clip` unchanged. That is the point: the poster is measured by the
    offsets and tolerances the clip is measured by, and there is no second geometry to keep in step
    with the recorder's CSS. `similarity` is `None` when a leak was found, because that verdict
    replaces the poster whatever its freshness and the freshness pass is a whole extra decode."""
    clip = poster_clip(poster)
    if not os.path.isfile(clip):
        raise PosterUnpaired(
            "%s has no clip beside it (expected %s), so neither the frame size to measure it at nor "
            "the frames it must still depict can be answered. Scan a poster next to the clip it was "
            "cut from." % (display_name(poster), display_name(clip)))
    clip_width, clip_height = _dimensions(ffmpeg, clip)
    poster_width, poster_height = _dimensions(ffmpeg, poster)
    by_width = float(poster_width) / clip_width
    by_height = float(poster_height) / clip_height
    if abs(by_width - by_height) > POSTER_ASPECT_TOLERANCE * by_width:
        raise ScaleMismatch(
            "%s is %dx%d against its clip's %dx%d, so it is not a whole frame of it (the width "
            "scales by %.4f and the height by %.4f). A cropped or letterboxed poster stretches when "
            "it is scaled back, which moves the chrome off every offset this gate measures. Cut the "
            "poster from a full frame of %s."
            % (display_name(poster), poster_width, poster_height, clip_width, clip_height,
               by_width, by_height, display_name(clip)))
    bad, judged, occluded = scan_clip(ffmpeg, poster, prefix=poster_prefix(clip_width, clip_height),
                                      surface="poster")
    if bad:
        return bad, judged, occluded, None
    similarity = poster_similarity(ffmpeg, poster, clip, poster_width, poster_height)
    if similarity < POSTER_MATCH_MIN:
        raise StalePoster(
            "%s does not depict any frame of %s (best structural similarity %.4f, under the %.2f a "
            "poster cut from its own clip reads). A re-recorded clip keeps its filename, so a "
            "poster left over from the previous recording is published beside it with nothing "
            "failing. Re-cut this poster from the current clip."
            % (display_name(poster), display_name(clip), similarity, POSTER_MATCH_MIN))
    return bad, judged, occluded, similarity


def is_clip(path):
    """Whether a path names a published clip. Case-insensitive, exactly like `is_poster`: the two
    predicates decide the same question and are used on both the explicit-argument and the default
    discovery paths, so a name matched by one and missed by the other would be a silent gap in
    whichever path CI uses."""
    return os.path.basename(path).lower().endswith(CLIP_SUFFIX)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*",
                        help="clips and posters to scan (default: every published one)")
    parser.add_argument("--require-ffmpeg", action="store_true",
                        help="fail instead of skipping when ffmpeg is unavailable (used by CI, "
                             "where a skipped scan would be a green gate that checked nothing)")
    args = parser.parse_args(argv)

    ffmpeg = find_ffmpeg()
    directory = os.path.join(REPO_ROOT, CLIP_DIR)
    if args.files:
        clips = [f for f in args.files if is_clip(f)]
        posters = [f for f in args.files if is_poster(f)]
        unknown = [f for f in args.files if not is_clip(f) and not is_poster(f)]
        if unknown:
            raise SystemExit("not a published clip or poster: %s (clips are %s files, posters are "
                             "%s*%s)" % (", ".join(unknown), CLIP_SUFFIX, POSTER_PREFIX,
                                         POSTER_SUFFIXES[0]))
    else:
        names = sorted(os.listdir(directory))
        clips = [os.path.join(directory, n) for n in names if is_clip(n)]
        posters = [os.path.join(directory, n) for n in names if is_poster(n)]
        # Each surface is named separately, because "found nothing to scan" is indistinguishable
        # from "scanned it and it was clean" in the output, and the posters were the surface that
        # went ungated for as long as they did.
        if not clips:
            raise SystemExit("no published clips found under %s" % CLIP_DIR)
        if not posters:
            raise SystemExit("no published posters (%s*%s) found under %s; they are a published "
                             "surface too, and a run that quietly scanned only the clips would "
                             "report the same OK as a clean one"
                             % (POSTER_PREFIX, POSTER_SUFFIXES[0], CLIP_DIR))
    if not clips and not posters:
        raise SystemExit("no published clips or posters found under %s" % CLIP_DIR)

    if not ffmpeg:
        message = ("no ffmpeg on PATH (set DEMO_CLIP_FFMPEG to override). Playwright's bundled "
                   "ffmpeg is VP8-only and cannot decode the published VP9 clips.")
        if args.require_ffmpeg:
            # Fail CLOSED. A gate that goes green having scanned nothing is worse than no gate,
            # because it reads as proof the clips were checked.
            raise SystemExit("check_clip_chrome: FAILED - " + message)
        # Locally, degrade rather than fail, but say so loudly instead of reporting a pass.
        print("check_clip_chrome: SKIPPED - " + message)
        return 0

    failed = False
    leaked = False
    for clip in clips:
        name = display_name(clip)
        try:
            bad, judged, occluded = scan_clip(ffmpeg, clip)
        except Unscannable as problem:
            # Keep going: every clip gets its own verdict in one run, so a second problem elsewhere
            # is not hidden behind the first.
            failed = True
            print("FAIL %s: %s" % (name, problem))
            continue
        if bad:
            failed = True
            leaked = True
            print("FAIL %s: %d frame(s) show text in the terminal title bar (%d judged, %d skipped "
                  "with the chrome painted over)" % (name, len(bad), judged, occluded))
            for t, spread in bad[:8]:
                print("       t=%.2fs (luminance spread %.0f)" % (t, spread))
            if len(bad) > 8:
                print("       ... and %d more" % (len(bad) - 8))
        else:
            # Say what was inspected. A gate that will not report its own coverage cannot be
            # audited, and "judged 3" and "judged 1040" both used to print the same word. The
            # frames skipped as occluded are named too: they are frames NOT checked, and a count
            # that grows out of proportion to a clip's transitions is worth looking at.
            if not judged:
                print("OK   %s (no window chrome to check)" % name)
            elif occluded:
                print("OK   %s (judged %d frame(s), skipped %d with the chrome painted over)"
                      % (name, judged, occluded))
            else:
                print("OK   %s (judged %d frame(s))" % (name, judged))
    for poster in posters:
        name = display_name(poster)
        try:
            bad, judged, occluded, similarity = scan_poster(ffmpeg, poster)
        except Unscannable as problem:
            failed = True
            print("FAIL %s: %s" % (name, problem))
            continue
        if bad:
            failed = True
            leaked = True
            print("FAIL %s: its title bar is not empty (luminance spread %.0f), and a poster is "
                  "seen on first paint without anyone pressing play"
                  % (name, max(spread for _, spread in bad)))
        elif not judged:
            print("OK   %s (no window chrome to check, matches its clip at %.4f)"
                  % (name, similarity))
        else:
            print("OK   %s (title bar clear, matches its clip at %.4f)" % (name, similarity))
    if failed:
        # Tie the advice to the clip that earned it. Gating it on "nothing was unscannable" meant
        # one unreadable clip swallowed the instruction for a DIFFERENT clip that really did leak.
        if leaked:
            print("\nA published clip or poster is showing its launch command. Re-mask the WHOLE "
                  "terminal segment (measure the boundaries, do not guess them), or re-record with "
                  "the current recorder, and re-cut the posters from the new clips.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
