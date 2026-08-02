"""Unit tests for the published-clip chrome scan (SITE-VIDEO-17).

The scan itself needs ffmpeg and a real clip, so what is pinned here is the DECISION logic: which
frames it agrees to judge, what it calls a leak, and how it behaves when its own inputs are not
trustworthy. That is where the subtlety lives - earlier cuts of this check either flagged every
cross-fade frame (an alarm nobody would keep) or skipped the END of a segment, which is precisely
where the real leak sat.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_clip_chrome as ccc


def _frames(kinds, spreads):
    """Build the two parallel measurement lists the scanner consumes.

    `kinds` is a string of 't' (settled chrome on screen), 'f' (mid cross-fade, so the lights are
    part-faded or shifted) and 'b' (no chrome at all - a browser page); `spreads` is the luminance
    spread of each frame's title strip.
    """
    strip = [{"t": i * 0.04, "YMIN": 0.0, "YMAX": s, "SATMAX": 10.0} for i, s in enumerate(spreads)]
    # Measured on real clips: the lights read 83-93 fully drawn, drop well under the threshold at
    # any fade, and read ~2 on a page that has no window chrome.
    saturation = {"t": 88.0, "f": 55.0, "b": 2.0}
    lights = [{"SATMAX": saturation[k]} for k in kinds]
    return strip, lights


class ScanDecisionTests(unittest.TestCase):
    def _scan(self, kinds, spreads):
        strip, lights = _frames(kinds, spreads)
        calls = iter([strip, lights])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            return ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original

    def test_text_on_a_terminal_frame_is_reported(self):
        spreads = [0.0] * 20
        spreads[10] = 148.0
        bad = self._scan("t" * 20, spreads)
        self.assertEqual([round(t, 2) for t, _ in bad], [0.40])

    def test_a_flat_strip_never_reports(self):
        self.assertEqual(self._scan("t" * 20, [0.0] * 20), [])

    def test_a_browser_frame_is_not_judged(self):
        # A browser page has no window chrome, so its bright content is not a leak.
        self.assertEqual(self._scan("b" * 20, [200.0] * 20), [])

    def test_a_cross_fade_frame_is_not_judged(self):
        # Mid-fade the whole terminal scales and the report slides over it, so a fixed crop
        # straddles chrome and content and every transition frame looks "not flat". Judging them
        # cried wolf on every cut. Some chrome frames must exist or this is a geometry failure.
        self.assertEqual(self._scan("f" * 19 + "t", [200.0] * 19 + [0.0]), [])

    def test_the_very_last_frame_of_a_segment_is_judged(self):
        # THE regression that shipped (#815): the mask stopped early, so the final frames of a
        # terminal segment carried the command. Any positional settle window skips exactly these,
        # so the classifier must be strict enough that no window is needed.
        kinds = "t" * 10 + "f" * 3 + "b" * 7
        spreads = [0.0] * 20
        spreads[9] = 148.0
        bad = self._scan(kinds, spreads)
        self.assertEqual([round(t, 2) for t, _ in bad], [0.36])

    def test_a_spread_under_tolerance_is_not_reported(self):
        # Compression noise on a flat box is not text.
        spreads = [0.0] * 20
        spreads[10] = ccc.FLAT_TOLERANCE - 1
        self.assertEqual(self._scan("t" * 20, spreads), [])

    def test_a_clip_whose_chrome_never_settles_is_refused_not_passed(self):
        # Judging on the lights means a clip whose chrome never lands where the offsets expect it
        # judges NOTHING - and silently reporting OK there would be a gate that checked nothing
        # while claiming it had, the exact failure this script replaced.
        with self.assertRaises(ccc.ScaleMismatch) as caught:
            self._scan("f" * 20, [200.0] * 20)
        self.assertIn("--scale", str(caught.exception))

    def test_a_clip_with_no_window_chrome_at_all_is_a_legitimate_pass(self):
        # The browser-only demo carries no title bar to leak from; its lights region peaks at 2.
        self.assertEqual(self._scan("b" * 20, [200.0] * 20), [])


class UntrustworthyInputTests(unittest.TestCase):
    """The scan must never report a pass it did not earn."""

    def _measure_returning(self, *results):
        calls = iter(results)
        return lambda *a, **k: next(calls)

    def test_the_scan_refuses_a_frame_count_mismatch(self):
        strip, kind = _frames("t" * 10, [0.0] * 10)
        original = ccc._measure
        ccc._measure = self._measure_returning(strip, kind[:-1])
        try:
            with self.assertRaises(SystemExit):
                ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original

    def test_an_empty_decode_is_an_error_not_a_pass(self):
        original = ccc._measure
        ccc._measure = self._measure_returning([], [])
        try:
            with self.assertRaises(SystemExit):
                ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original

    def test_a_frame_missing_its_measurements_is_fatal(self):
        # A parse that finds frames but not their numbers would sail through everything downstream:
        # a missing YAVG reads as "browser, skip" and a missing YMAX as "perfectly flat". That is
        # the silent-failure mode this script exists to replace.
        proc = type("P", (), {"returncode": 0,
                              "stderr": "frame:0 pts_time:0\nframe:1 pts_time:0.04\n"})()
        original = ccc.subprocess.run
        ccc.subprocess.run = lambda *a, **k: proc
        try:
            with self.assertRaises(SystemExit) as caught:
                ccc._measure("ffmpeg", "clip.webm", "crop=1:1:0:0", ("YMIN", "YMAX"))
            self.assertIn("YMIN", str(caught.exception))
        finally:
            ccc.subprocess.run = original


class FfmpegAvailabilityTests(unittest.TestCase):
    def test_ci_fails_closed_when_ffmpeg_is_missing(self):
        # A green gate that scanned nothing reads as proof the clips were checked.
        original = ccc.find_ffmpeg
        ccc.find_ffmpeg = lambda: None
        try:
            with self.assertRaises(SystemExit) as caught:
                ccc.main(["clip.webm", "--require-ffmpeg"])
            self.assertIn("FAILED", str(caught.exception))
        finally:
            ccc.find_ffmpeg = original

    def test_a_local_run_skips_loudly_instead(self):
        original = ccc.find_ffmpeg
        ccc.find_ffmpeg = lambda: None
        try:
            self.assertEqual(ccc.main(["clip.webm"]), 0)
        finally:
            ccc.find_ffmpeg = original


#: The renderer's chrome CSS, parsed out of the page builders so this file cannot drift from them.
#: Duplicating the geometry as literals is what these tests exist to prevent: the gate and the
#: renderer encode the SAME numbers, and a chrome tweak that moved one silently invalidated the
#: other with every test still green - the recorder-vs-gate disagreement this whole change removes.
RECORDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".github", "skills", "demo-video", "tools", "record_demo.mjs")


def chrome_css():
    """`{prop: px}` for the chrome rules the strip geometry is derived from."""
    with open(RECORDER, encoding="utf-8") as handle:
        text = handle.read()

    def rule(selector, prop, index=0):
        block = re.search(r"%s\s*\{([^}]*)\}" % re.escape(selector), text)
        if not block:
            raise AssertionError("no %s rule in the recorder" % selector)
        found = re.search(r"(?:^|[;\s])%s:\s*([^;}]+)" % prop, block.group(1))
        if not found:
            raise AssertionError("%s has no %s" % (selector, prop))
        lengths = re.findall(r"(-?[\d.]+)px", found.group(1))
        if len(lengths) <= index:
            raise AssertionError("%s %s has no length #%d" % (selector, prop, index))
        return float(lengths[index])

    return {
        "pad_top": rule(".wrap", "padding", 0),
        "pad_side": rule(".wrap", "padding", 1),
        "dot": rule(".dot", "height"),
        "gap": rule(".chrome", "gap"),
        "chrome_pad_bottom": rule(".chrome", "padding-bottom"),
        "title_margin": rule(".title", "margin-left"),
    }


def strip_box():
    """`(x, top, bottom)` of the configured strip, in video pixels."""
    found = re.match(r"crop=iw-(\d+):(\d+):(\d+):(\d+)$", ccc.STRIP)
    if not found:
        raise AssertionError("STRIP is not the expected crop shape: %r" % ccc.STRIP)
    inset, height, x, top = (int(g) for g in found.groups())
    return x, top, top + height, inset


class CropGeometryTests(unittest.TestCase):
    """The offsets are VIDEO pixels at the publish scale, and must not chase the frame size.

    The window chrome is styled in fixed CSS pixels, so it lands on the same video pixels whatever
    the terminal grid is: the 864x540 and 1078x620 published clips put their traffic lights on
    exactly the same pixels. Scaling these offsets by the frame width therefore MOVES them off the
    chrome, which is a real trap - an attempt at exactly that rejected the 1078x620 clip outright.

    Every assertion below reads the CONFIGURED strip and the LIVE recorder CSS. An earlier cut
    restated `top, height = 1, 22` as local literals and asserted them against themselves, so it
    would have passed whatever the gate actually did.
    """

    def test_the_strip_starts_right_of_the_traffic_lights_and_no_later_than_the_title(self):
        css = chrome_css()
        x, _, _, _ = strip_box()
        lights_end = css["pad_side"] + 3 * css["dot"] + 2 * css["gap"]
        title_start = lights_end + css["title_margin"]
        # Left of this the lights' colour reads as text; right of the title's start a leaked title
        # begins outside the strip entirely.
        self.assertGreaterEqual(x, lights_end * ccc.PUBLISH_SCALE)
        self.assertLessEqual(x, title_start * ccc.PUBLISH_SCALE)

    def test_the_strip_covers_the_whole_row_a_title_is_drawn_on(self):
        css = chrome_css()
        _, top, bottom, _ = strip_box()
        # The title is a 12px font on the lights' row; its line box is taller than the 11px dots, so
        # the dots alone are not the bound - a strip that cleared them could still clip the glyphs.
        row_top = css["pad_top"]
        row_bottom = css["pad_top"] + css["dot"]
        self.assertLessEqual(top, row_top * ccc.PUBLISH_SCALE)
        self.assertGreaterEqual(bottom, row_bottom * ccc.PUBLISH_SCALE)

    def test_the_strip_clears_the_terminal_with_room_to_spare(self):
        # THE finding from the round-1 panel. Run to the bottom of the chrome block the strip
        # overlapped the terminal's first row and flagged 14 frames of a clean clip; merely touching
        # its edge left a measured margin of 2.0 against a tolerance of 12.0, so the next re-record
        # with slightly brighter top-row output would fail with "re-mask the whole segment". The
        # separation, not the strip height, is what has to be generous.
        css = chrome_css()
        _, _, bottom, _ = strip_box()
        terminal_top = (css["pad_top"] + css["dot"] + css["chrome_pad_bottom"]) * ccc.PUBLISH_SCALE
        self.assertGreaterEqual(terminal_top - bottom, 4.0,
                                "the terminal starts %.1f video px below the strip; the panel "
                                "measured that a smaller gap bleeds into it" % (terminal_top - bottom))


class ScaleGuardTests(unittest.TestCase):
    """A clip rendered at another scale is measured in the wrong place, and must say so."""

    def _scan(self, satmax):
        strip = [{"t": 0.4, "YMIN": 0.0, "YMAX": 1.0, "SATMAX": satmax}]
        lights = [{"SATMAX": 88.0}]
        calls = iter([strip, lights])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            return ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original

    def test_colour_in_the_strip_is_reported_as_a_scale_problem_not_a_leak(self):
        # At scale 1 the traffic lights sit inside the strip, so EVERY terminal frame "leaks". That
        # phantom reads exactly like the real thing; saying "re-mask or re-record" sent a reviewer
        # hunting for text that was not there.
        with self.assertRaises(ccc.ScaleMismatch) as caught:
            self._scan(200.0)
        self.assertIn("--scale 0.6", str(caught.exception))

    def test_a_grey_chrome_strip_is_scanned_normally(self):
        self.assertEqual(self._scan(10.0), [])

    def test_the_guard_clears_the_colour_real_clips_carry(self):
        # Measured on the published clips, a judged frame's strip peaks at SATMAX 15 while the
        # traffic lights themselves read 83-93. The threshold has to sit in that gap with room on
        # both sides, or it either cries scale on a clean clip or misses a genuinely mis-scaled one.
        self.assertGreater(ccc.LIGHTS_SATURATION, 15.0 * 2)
        self.assertLess(ccc.LIGHTS_SATURATION, 83.0 * 0.9)

    def test_the_flatness_tolerance_separates_a_real_leak_from_clean_chrome(self):
        # Measured end to end at the publish scale, rendering the SAME cast both ways: a real
        # leaked title (`--show-command`) reads 167, a clean terminal-only clip 8, and the loop
        # clip - whose report cross-fades over the window - 12. Sitting ON the noise ceiling (the
        # old value of 12) left a clean re-record one unit from failing for no safety gain.
        self.assertGreater(ccc.FLAT_TOLERANCE, 12.0 * 2)
        self.assertLess(ccc.FLAT_TOLERANCE, 167.0 / 2)

    def test_one_mis_scaled_clip_does_not_abandon_the_others(self):
        # `main` scans a LIST. Aborting the whole run on the first bad clip hides every later clip's
        # independent leak until the first is fixed and the gate rerun - and the operator workflow
        # in SKILL.md passes all the new clips at once.
        seen = []

        def fake(ffmpeg, clip):
            seen.append(clip)
            if clip == "bad.webm":
                raise ccc.ScaleMismatch("bad.webm was not rendered at the publish scale")
            return []

        original_scan, original_find = ccc.scan_clip, ccc.find_ffmpeg
        ccc.scan_clip, ccc.find_ffmpeg = fake, lambda: "ffmpeg"
        try:
            code = ccc.main(["bad.webm", "good.webm"])
        finally:
            ccc.scan_clip, ccc.find_ffmpeg = original_scan, original_find
        self.assertEqual(seen, ["bad.webm", "good.webm"])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
