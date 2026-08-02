"""Unit tests for the published-clip chrome scan (SITE-VIDEO-17).

The scan itself needs ffmpeg and a real clip, so what is pinned here is the DECISION logic: which
frames it agrees to judge, what it calls a leak, and how it behaves when its own inputs are not
trustworthy. That is where the subtlety lives - earlier cuts of this check either flagged every
cross-fade frame (an alarm nobody would keep) or skipped the END of a segment, which is precisely
where the real leak sat.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_clip_chrome as ccc


def _frames(kinds, spreads):
    """Build the two parallel measurement lists the scanner consumes.

    `kinds` is a string of 't' (settled terminal), 'f' (mid cross-fade) and 'b' (browser) frames;
    `spreads` is the luminance spread of each frame's title strip.
    """
    strip = [{"t": i * 0.04, "YMIN": 0.0, "YMAX": s, "SATMAX": 10.0} for i, s in enumerate(spreads)]
    means = {"t": 30.0, "f": 60.0, "b": 200.0}
    kind = [{"YAVG": means[k]} for k in kinds]
    return strip, kind


class ScanDecisionTests(unittest.TestCase):
    def _scan(self, kinds, spreads):
        strip, kind = _frames(kinds, spreads)
        calls = iter([strip, kind])
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
        # Mid-fade the whole terminal scales, so a fixed crop straddles chrome and content and every
        # transition frame looks "not flat". Judging them cried wolf on every cut.
        self.assertEqual(self._scan("f" * 20, [200.0] * 20), [])

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


class CropGeometryTests(unittest.TestCase):
    """The offsets are VIDEO pixels at the publish scale, and must not chase the frame size.

    The window chrome is styled in fixed CSS pixels, so it lands on the same video pixels whatever
    the terminal grid is: the 864x540 and 1078x620 published clips put their traffic lights on
    exactly the same pixels. Scaling these offsets by the frame width therefore MOVES them off the
    chrome, which is a real trap - an attempt at exactly that rejected the 1078x620 clip outright.
    """

    def test_the_strip_stops_before_the_terminal(self):
        # Running the strip to the bottom of the chrome BLOCK (video y=25) overlapped the terminal's
        # first row, and that row's antialiased top read as a strip that is not flat - 14 frames of
        # a clean clip flagged with no text anywhere near the title bar.
        top, height = 1, 22
        self.assertEqual(ccc.STRIP, "crop=iw-66:%d:46:%d" % (height, top))
        self.assertLess(top + height, 25)

    def test_the_strip_still_covers_where_a_title_would_be_drawn(self):
        # The lights span video y=11..18 and a title is set on that row, starting at x=46. Narrowing
        # the strip to dodge the terminal must not narrow it past the thing it exists to catch.
        top, height = 1, 22
        self.assertLessEqual(top, 11)
        self.assertGreaterEqual(top + height, 18)


class ScaleGuardTests(unittest.TestCase):
    """A clip rendered at another scale is measured in the wrong place, and must say so."""

    def _scan(self, satmax):
        strip = [{"t": 0.4, "YMIN": 0.0, "YMAX": 1.0, "SATMAX": satmax}]
        kind = [{"YAVG": 30.0}]
        calls = iter([strip, kind])
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
        with self.assertRaises(SystemExit) as caught:
            self._scan(200.0)
        self.assertIn("--scale 0.6", str(caught.exception))

    def test_a_grey_chrome_strip_is_scanned_normally(self):
        self.assertEqual(self._scan(10.0), [])


if __name__ == "__main__":
    unittest.main()
