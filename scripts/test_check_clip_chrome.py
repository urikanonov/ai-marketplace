"""Unit tests for the published-clip chrome scan (SITE-VIDEO-17).

The scan itself needs ffmpeg and a real clip, so what is worth pinning here is the DECISION logic:
which frames it agrees to judge, and what it calls a leak. That logic is where the subtlety lives -
the clip cross-fades between a terminal and a browser, and an earlier cut of this check flagged every
fade frame (a false alarm nobody would keep) while a symmetric settle window skipped the END of a
segment, which is precisely where the real leak sat.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_clip_chrome as ccc


def _frames(kinds, spreads):
    """Build the two parallel measurement lists the scanner consumes.

    `kinds` is a string of 't' (terminal) and 'b' (browser) frames; `spreads` the luminance spread
    of each frame's title strip.
    """
    strip = [{"t": i * 0.04, "YMIN": 0.0, "YMAX": s} for i, s in enumerate(spreads)]
    kind = [{"YAVG": 20.0 if k == "t" else 200.0} for k in kinds]
    return strip, kind


class ScanDecisionTests(unittest.TestCase):
    def _scan(self, kinds, spreads, monkeypatch_pairs=None):
        strip, kind = _frames(kinds, spreads)
        calls = iter([strip, kind])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            return ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original

    def test_text_deep_inside_a_terminal_segment_is_reported(self):
        # A settled terminal frame whose strip is not flat is the leak this exists to catch.
        n = 60
        spreads = [0.0] * n
        spreads[40] = 148.0
        bad = self._scan("t" * n, spreads)
        self.assertEqual([round(t, 2) for t, _ in bad], [round(40 * 0.04, 2)])

    def test_a_flat_strip_never_reports(self):
        self.assertEqual(self._scan("t" * 60, [0.0] * 60), [])

    def test_a_browser_frame_is_not_judged(self):
        # A browser page has no window chrome, so its bright content is not a leak.
        self.assertEqual(self._scan("b" * 60, [200.0] * 60), [])

    def test_the_fade_in_tail_is_not_judged(self):
        # Frames just after a browser->terminal cut still ghost; judging them cried wolf on every
        # transition, which is how a real alarm would end up ignored.
        kinds = "b" * 30 + "t" * 30
        spreads = [0.0] * 30 + [50.0] * 5 + [0.0] * 25
        self.assertEqual(self._scan(kinds, spreads), [])

    def test_the_end_of_a_segment_is_still_judged(self):
        # The regression that shipped: the mask stopped early, so the LAST frames of a terminal
        # segment carried the command. A symmetric settle window would skip exactly these.
        kinds = "t" * 40 + "b" * 20
        spreads = [0.0] * 40 + [0.0] * 20
        spreads[33] = 148.0
        bad = self._scan(kinds, spreads)
        self.assertEqual([round(t, 2) for t, _ in bad], [round(33 * 0.04, 2)])

    def test_a_spread_under_tolerance_is_not_reported(self):
        # Compression noise on a flat box is not text.
        n = 60
        spreads = [0.0] * n
        spreads[40] = ccc.FLAT_TOLERANCE - 1
        self.assertEqual(self._scan("t" * n, spreads), [])


class WiringTests(unittest.TestCase):
    def test_the_scan_refuses_a_frame_count_mismatch(self):
        # The two measurement passes must line up frame for frame, or every verdict is off by
        # however far they drifted.
        strip, kind = _frames("t" * 10, [0.0] * 10)
        calls = iter([strip, kind[:-1]])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            with self.assertRaises(SystemExit):
                ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original

    def test_an_empty_decode_is_an_error_not_a_pass(self):
        calls = iter([[], []])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            with self.assertRaises(SystemExit):
                ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original


if __name__ == "__main__":
    unittest.main()
