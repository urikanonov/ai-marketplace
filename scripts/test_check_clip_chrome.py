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
import contextlib
import io
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_clip_chrome as ccc


def _frames(kinds, spreads, gutters=None):
    """Build the four parallel measurement lists the scanner consumes.

    `kinds` is a string of 't' (settled chrome on screen), 'f' (mid cross-fade, so the lights are
    part-faded or shifted), 'o' (LATE cross-fade: the lights are fully saturated again while the
    report is still faintly painted over the window) and 'b' (no chrome at all - a browser page);
    `spreads` is the luminance spread of each frame's title strip. `gutters` overrides the gutter
    spread per frame, which is how a case at the decision boundary is expressed.
    """
    strip = [{"t": i * 0.04, "YMIN": 0.0, "YMAX": s, "SATMAX": 10.0} for i, s in enumerate(spreads)]
    # Measured on real clips: the lights read 83-93 fully drawn, drop well under the threshold at
    # any fade, and read ~2 on a page that has no window chrome. At the END of a fade they are back
    # to full saturation while the report is still on top, which is what 'o' stands for.
    saturation = {"t": 88.0, "f": 55.0, "o": 88.0, "b": 2.0}
    lights = [{"SATMAX": saturation[k]} for k in kinds]
    # The chrome's empty gutter: flat whenever nothing is painted over the window, and carrying the
    # report's ghost while it is. Measured on the loop clip: 19 at worst settled, 24-44 mid-fade.
    gutter_spread = {"t": 6.0, "f": 44.0, "o": 44.0, "b": 6.0}
    values = gutters if gutters is not None else [gutter_spread[k] for k in kinds]
    gutter = [{"YMIN": 0.0, "YMAX": v} for v in values]
    # A terminal is on screen for anything but a browser frame.
    means = {"t": 30.0, "f": 30.0, "o": 30.0, "b": 200.0}
    kind = [{"YAVG": means[k]} for k in kinds]
    for i, row in enumerate(strip):
        # The scanner pairs the four probes by index and checks that their timestamps agree, so the
        # fixture has to carry the same timestamp on every probe, exactly as ffmpeg reports it.
        for other in (lights, gutter, kind):
            other[i]["t"] = row["t"]
    return strip, lights, gutter, kind


class ScanDecisionTests(unittest.TestCase):
    def _run(self, kinds, spreads, gutters=None):
        calls = iter(_frames(kinds, spreads, gutters))
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            return ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original

    def _scan(self, kinds, spreads, gutters=None):
        return self._run(kinds, spreads, gutters)[0]

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
        # cried wolf on every cut. Enough chrome frames must remain or this is a geometry failure.
        self.assertEqual(self._scan("f" * 5 + "t" * 15, [200.0] * 5 + [0.0] * 15), [])

    def test_the_very_last_frame_of_a_segment_is_judged(self):
        # THE regression that shipped (#815): the mask stopped early, so the final frames of a
        # terminal segment carried the command. Any positional settle window skips exactly these,
        # so the classifier must be strict enough that no window is needed.
        kinds = "t" * 10 + "f" * 3 + "b" * 7
        spreads = [0.0] * 20
        spreads[9] = 148.0
        bad = self._scan(kinds, spreads)
        self.assertEqual([round(t, 2) for t, _ in bad], [0.36])

    def test_a_late_cross_fade_frame_is_not_judged(self):
        # At the END of a fade the lights are fully saturated again while the report is still
        # faintly painted OVER the window, so the strip carries a ghost of report content and the
        # lights alone cannot tell. Judging it spent most of the flatness margin on the loop clip
        # (worst frame 33 against a tolerance of 40) for a frame that is not the title bar at all.
        kinds = "t" * 10 + "o" * 5 + "t" * 5
        bad, judged, occluded = self._run(kinds, [0.0] * 10 + [33.0] * 5 + [0.0] * 5)
        self.assertEqual(bad, [])
        self.assertEqual(judged, 15)
        self.assertEqual(occluded, 5)

    def test_a_late_cross_fade_ghost_is_not_reported_as_a_leak(self):
        # An occluded frame is not the title bar, so a report ghost on it is not a leak - reporting
        # one would send the operator hunting for text that is not in the chrome. A ghost stays
        # well under the coarse tolerance: measured, the worst reads 33 where a title reads 167.
        spreads = [0.0] * 10 + [ccc.OCCLUDED_LEAK_TOLERANCE - 1] * 5
        bad, judged, occluded = self._run("t" * 10 + "o" * 5, spreads)
        self.assertEqual(bad, [])
        self.assertEqual(judged, 10)
        self.assertEqual(occluded, 5)

    def test_a_title_drawn_under_an_overlay_is_still_reported(self):
        # Not judged must not mean not looked at. The overlay is faint wherever the lights still
        # read as drawn, so a real title keeps most of its contrast - and a leaked title long
        # enough to wrap would put ink in the gutter and so exempt its OWN frame. The #815 leak sat
        # on the last frames of a segment, which is exactly where a transition starts.
        spreads = [0.0] * 10 + [167.0] * 2 + [0.0] * 8
        bad, judged, occluded = self._run("t" * 10 + "o" * 2 + "t" * 8, spreads)
        self.assertEqual([round(t, 2) for t, _ in bad], [0.40, 0.44])
        self.assertEqual((judged, occluded), (18, 2))

    def test_a_title_under_a_coloured_overlay_is_still_reported(self):
        # Colour in the strip is a hint about SCALE, not a licence: letting it short-circuit the
        # coarse check would hand a leak the one exemption that branch exists to deny. A report is
        # an arbitrary HTML page, so its ghost can perfectly well be coloured.
        strip, lights, gutter, kind = _frames("t" * 10 + "o" * 1, [0.0] * 10 + [167.0])
        strip[10]["SATMAX"] = 120.0
        calls = iter([strip, lights, gutter, kind])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            bad, judged, occluded = ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original
        self.assertEqual([round(t, 2) for t, _ in bad], [0.40])
        self.assertEqual((judged, occluded), (10, 1))

    def test_a_leak_outranks_a_complaint_about_coverage(self):
        # Both fail the run, but only one of them says there is a command on screen. Swallowing a
        # found leak into a generic "this clip could not be read" buries the finding.
        spreads = [167.0] * 5 + [0.0] * 15
        bad, judged, occluded = self._run("t" * 5 + "o" * 15, spreads)
        self.assertEqual(len(bad), 5)
        self.assertEqual((judged, occluded), (5, 15))

    def test_a_title_sized_spread_on_a_skipped_frame_is_named_in_the_refusal(self):
        # A hit on the ODD skipped frame is weaker evidence than one on a judged frame - the frame
        # is not the title bar by definition, and on a clip whose geometry this gate does not
        # describe it is as likely to be terminal output bleeding into the strip. It must not
        # overrule the diagnosis, and it must not be dropped either.
        spreads = [0.0] * 5 + [167.0] * 2 + [0.0] * 13
        with self.assertRaises(ccc.ChromeOccluded) as caught:
            self._scan("t" * 5 + "o" * 15, spreads)
        self.assertIn("title-sized spread", str(caught.exception))

    def test_a_title_on_most_skipped_frames_is_the_verdict_not_a_footnote(self):
        # A wrapped title dirties the gutter with its OWN ink, so the frames it leaks on are the
        # frames that read as painted over. Reporting that as "your chrome geometry is wrong" would
        # send the operator re-recording a clip whose real problem is a command on screen.
        spreads = [0.0] * 5 + [167.0] * 15
        bad, judged, occluded = self._run("t" * 5 + "o" * 15, spreads)
        self.assertEqual(len(bad), 15)
        self.assertEqual((judged, occluded), (5, 15))

    def test_the_occluded_share_floor_is_honoured_at_its_boundary(self):
        # Pin the floor to its constant rather than to two samples far from it, so it cannot drift.
        total = 20
        at_floor = int(round(ccc.MAX_OCCLUDED_SHARE * total))
        with self.assertRaises(ccc.ChromeOccluded):
            self._scan("t" * (total - at_floor) + "o" * at_floor, [0.0] * total)
        _, judged, occluded = self._run("t" * (total - at_floor + 1) + "o" * (at_floor - 1),
                                        [0.0] * total)
        self.assertEqual(occluded, at_floor - 1)

    def test_a_clip_whose_chrome_is_found_on_almost_no_frames_is_refused(self):
        # The lights finding the chrome on a HANDFUL of frames is not the innocent browser-only
        # case: it is a clip these offsets nearly miss, and judging those few would report a
        # confident OK on a scan of almost nothing.
        with self.assertRaises(ccc.ScaleMismatch) as caught:
            self._scan("t" * 1 + "f" * 19, [0.0] * 20)
        self.assertIn("only found settled", str(caught.exception))

    def test_a_clip_whose_chrome_never_settles_is_not_blamed_on_the_scale(self):
        # Chrome on screen but never settled is not a scale problem, and saying "it shows a terminal
        # on 0 frames but its chrome never appears" contradicts itself.
        strip, lights, gutter, kind = _frames("f" * 20, [0.0] * 20)
        for row in kind:
            row["YAVG"] = 200.0
        calls = iter([strip, lights, gutter, kind])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            with self.assertRaises(ccc.ChromeOccluded) as caught:
                ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original
        self.assertIn("never shows its window chrome settled", str(caught.exception))

    def test_a_clip_whose_chrome_is_settled_on_almost_no_lit_frame_is_refused(self):
        # The occlusion floor guards one axis only. A clip whose chrome reads as FADED on nearly
        # every frame is the same 5%-coverage pass on the other axis, so the denominator counts
        # frames whose lights are lit at all, not just the settled ones.
        strip, lights, gutter, kind = _frames("t" * 2 + "f" * 18, [0.0] * 20)
        for row in kind:
            row["YAVG"] = 200.0
        calls = iter([strip, lights, gutter, kind])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            with self.assertRaises(ccc.ScaleMismatch) as caught:
                ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original
        self.assertIn("only found settled", str(caught.exception))

    def test_a_mostly_painted_over_clip_is_refused_not_passed_on_the_remainder(self):
        # An older recorder's chrome padding puts the terminal's first row inside the gutter band,
        # so the published loop clip of that era judges 23 of its 448 chrome frames. Passing on the
        # survivors reads exactly like a clean scan, which is the failure this gate exists to
        # replace, so a clip mostly skipped is refused.
        with self.assertRaises(ccc.ChromeOccluded) as caught:
            self._scan("t" * 5 + "o" * 15, [0.0] * 20)
        self.assertIn("older recorder", str(caught.exception))

    def test_a_clip_with_a_transition_or_two_is_not_refused(self):
        # The refusal is a coverage floor, not a ban on transitions: the loop clip skips 3.5%.
        _, judged, occluded = self._run("t" * 16 + "o" * 4, [0.0] * 20)
        self.assertEqual((judged, occluded), (16, 4))

    def test_the_gutter_tolerance_is_honoured_at_its_boundary(self):
        # Pin the comparison itself, not just values far from it: a frame exactly AT the tolerance
        # is judged and one a unit above is skipped. The measured population is pinned too - the
        # settled ceiling (19) must be judged and the faintest ghost (24) skipped - so widening the
        # constant past either of them fails here rather than silently changing what is scanned.
        gutters = [ccc.GUTTER_TOLERANCE] * 5 + [19.0] * 5 + [ccc.GUTTER_TOLERANCE + 1] * 3 + [24.0] * 2
        _, judged, occluded = self._run("t" * 15, [0.0] * 15, gutters)
        self.assertEqual((judged, occluded), (10, 5))

    def test_a_faded_frame_is_not_counted_as_painted_over(self):
        # A mid-fade frame is skipped on the lights, before the gutter is consulted, so it must not
        # inflate the skipped count - which is the number the coverage floor is measured against.
        _, judged, occluded = self._run("t" * 10 + "f" * 5 + "o" * 5, [0.0] * 20)
        self.assertEqual((judged, occluded), (10, 5))

    def test_the_settled_frames_before_a_fade_are_still_judged(self):
        # The occlusion gate must not become the positional settle window in disguise: the frames
        # right up to the transition are still the end of a settled segment, and that is where the
        # #815 leak sat.
        spreads = [0.0] * 20
        spreads[9] = 148.0
        bad = self._scan("t" * 10 + "o" * 4 + "b" * 6, spreads)
        self.assertEqual([round(t, 2) for t, _ in bad], [0.36])

    def test_a_clip_whose_chrome_is_never_unoccluded_is_refused_not_passed(self):
        # Every frame skipped for occlusion is a frame not checked, so a clip where that is ALL of
        # them must fail rather than print a bare OK - the same rule the lights already follow.
        with self.assertRaises(ccc.Unscannable) as caught:
            self._scan("o" * 20, [0.0] * 20)
        self.assertIn("painted over it", str(caught.exception))

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

    def test_a_terminal_clip_whose_lights_are_nowhere_is_refused(self):
        # An UNDER-scaled clip puts the lights outside the crop entirely, so they read as absent -
        # and its title falls left of the strip too, so nothing would be measured. Without the
        # terminal check that reads exactly like the browser-only clip and passes unchecked.
        strip, lights, gutter, kind = _frames("t" * 20, [200.0] * 20)
        for row in lights:
            row["SATMAX"] = 1.0
        calls = iter([strip, lights, gutter, kind])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            with self.assertRaises(ccc.ScaleMismatch) as caught:
                ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original
        self.assertIn("terminal", str(caught.exception))

    def test_a_clip_with_no_window_chrome_at_all_is_a_legitimate_pass(self):
        # The browser-only demo carries no title bar to leak from; its lights region peaks at 2 and
        # no frame shows a terminal, so judging nothing is the honest answer.
        strip, lights, gutter, kind = _frames("b" * 20, [200.0] * 20)
        calls = iter([strip, lights, gutter, kind])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            self.assertEqual(ccc.scan_clip("ffmpeg", "clip.webm"), ([], 0, 0))
        finally:
            ccc._measure = original

    def test_the_judged_count_is_reported_so_coverage_can_be_audited(self):
        strip, lights, gutter, kind = _frames("t" * 12 + "b" * 8, [0.0] * 20)
        calls = iter([strip, lights, gutter, kind])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            self.assertEqual(ccc.scan_clip("ffmpeg", "clip.webm"), ([], 12, 0))
        finally:
            ccc._measure = original


    def test_the_skipped_count_is_reported_so_dropped_frames_are_visible(self):
        # A frame skipped for occlusion is a frame NOT checked. Reporting only the judged count
        # would hide how much of a clip the gate quietly declined to look at.
        out = self._report(([], 577, 21))
        self.assertIn("judged 577", out)
        self.assertIn("skipped 21", out)

    def test_a_clip_with_nothing_skipped_says_so_by_saying_nothing(self):
        # The clean case must not grow a "skipped 0" clause; a report that always mentions skipping
        # trains the reader to ignore the number that matters.
        out = self._report(([], 1135, 0))
        self.assertIn("judged 1135", out)
        self.assertNotIn("skipped", out)

    def test_the_leak_advice_survives_an_unreadable_clip_in_the_same_run(self):
        # The advice is tied to the clip that earned it. Gating it on "nothing was unscannable"
        # meant one unreadable clip swallowed the instruction for a DIFFERENT clip that really did
        # leak, which is the one line telling the operator what to do about a published command.
        def fake(ffmpeg, clip):
            if clip == "unreadable.webm":
                raise ccc.ChromeOccluded("unreadable.webm could not be read")
            return [(1.0, 167.0)], 5, 0

        original_scan, original_find = ccc.scan_clip, ccc.find_ffmpeg
        ccc.scan_clip, ccc.find_ffmpeg = fake, lambda: "ffmpeg"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = ccc.main(["unreadable.webm", "leaky.webm"])
        finally:
            ccc.scan_clip, ccc.find_ffmpeg = original_scan, original_find
        self.assertNotEqual(code, 0)
        self.assertIn("showing its launch command", out.getvalue())

    def _report(self, result):
        original_scan, original_find = ccc.scan_clip, ccc.find_ffmpeg
        ccc.scan_clip, ccc.find_ffmpeg = (lambda ffmpeg, clip: result), lambda: "ffmpeg"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = ccc.main(["clip.webm"])
        finally:
            ccc.scan_clip, ccc.find_ffmpeg = original_scan, original_find
        self.assertEqual(code, 0)
        return out.getvalue()


class UntrustworthyInputTests(unittest.TestCase):
    """The scan must never report a pass it did not earn."""

    def _measure_returning(self, *results):
        calls = iter(results)
        return lambda *a, **k: next(calls)

    def test_the_scan_refuses_a_frame_count_mismatch(self):
        strip, lights, gutter, kind = _frames("t" * 10, [0.0] * 10)
        original = ccc._measure
        ccc._measure = self._measure_returning(strip, lights, gutter, kind[:-1])
        try:
            with self.assertRaises(SystemExit):
                ccc.scan_clip("ffmpeg", "clip.webm")
        finally:
            ccc._measure = original

    def test_the_scan_refuses_probes_whose_timestamps_disagree(self):
        # Equal lengths are not alignment. Four independent decodes are paired BY INDEX, so a run
        # that dropped one frame and duplicated another would judge one frame's gutter against its
        # neighbour's strip with no symptom at all.
        strip, lights, gutter, kind = _frames("t" * 10, [0.0] * 10)
        gutter[4]["t"] += 0.04
        original = ccc._measure
        ccc._measure = self._measure_returning(strip, lights, gutter, kind)
        try:
            with self.assertRaises(SystemExit) as caught:
                ccc.scan_clip("ffmpeg", "clip.webm")
            self.assertIn("timestamps", str(caught.exception))
        finally:
            ccc._measure = original

    def test_an_empty_decode_is_an_error_not_a_pass(self):
        original = ccc._measure
        ccc._measure = self._measure_returning([], [], [], [])
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


def _poster_frames(strip_spread, lights=96.0, gutter=9.0, mid=30.0, strip_sat=5.0):
    """The four probes for a SINGLE frame - which is all a poster is.

    The defaults are the published multi-duck poster measured at its clip's frame size: its chrome
    is drawn (lights 96), its title strip is flat (spread 4), its gutter is clear (9) and its
    middle is a terminal (mean 30).
    """
    strip = [{"t": 0.0, "YMIN": 0.0, "YMAX": strip_spread, "SATMAX": strip_sat}]
    return (strip,
            [{"t": 0.0, "SATMAX": lights}],
            [{"t": 0.0, "YMIN": 0.0, "YMAX": gutter}],
            [{"t": 0.0, "YAVG": mid}])


class PosterTests(unittest.TestCase):
    """The posters are a published surface, and they are the one a reader sees FIRST.

    They carry the same window chrome as the clip they are cut from - `site/src/poster-multi-duck.jpg`
    plainly shows the traffic lights and the strip beside them - and the launch command shipped in a
    poster once already. A poster is a whole frame of its clip, uniformly downscaled (864x540 ->
    800x500 and 1078x620 -> 800x460, both isotropic), so it needs no geometry of its own: scaled back
    to its clip's frame it IS a one-frame clip, and every offset and tolerance carries over.
    """

    def _scan(self, frames, clip_size=(1078, 620), poster_size=(800, 460), similarity=0.99):
        sizes = {"poster-x.jpg": poster_size, "demo-x.webm": clip_size}
        calls = iter(frames)
        with mock.patch.object(ccc, "_measure", lambda *a, **k: next(calls)), \
                mock.patch.object(ccc, "_dimensions", lambda ffmpeg, path: sizes[os.path.basename(path)]), \
                mock.patch.object(ccc, "poster_similarity", lambda *a, **k: similarity), \
                mock.patch("os.path.isfile", lambda path: True):
            return ccc.scan_poster("ffmpeg", os.path.join("assets", "poster-x.jpg"))

    def test_a_poster_names_the_clip_it_is_cut_from(self):
        self.assertEqual(ccc.poster_clip(os.path.join("a", "poster-multi-duck.jpg")),
                         os.path.join("a", "demo-multi-duck.webm"))

    def test_the_frame_size_is_read_from_the_input_not_the_filtered_output(self):
        # ffmpeg repeats a frame size on its output and stream-mapping lines, and after a filter
        # has run that size is the FILTER's. A poster whose own size were read off the scaled
        # output would agree with its clip's shape no matter what shape it really was, which is
        # exactly the check that would then never fire.
        proc = type("P", (), {"returncode": 0, "stdout": "", "stderr": (
            "  Stream #0:0: Video: mjpeg (Baseline), yuvj420p(pc), 800x460 [SAR 1:1 DAR 40:23], "
            "25 fps, 25 tbr, 25 tbn\n"
            "Stream mapping:\n"
            "  Stream #0:0 -> #0:0 (mjpeg (native) -> wrapped_avframe (native))\n"
            "  Stream #0:0: Video: wrapped_avframe, yuv420p, 1078x620, q=2-31, 25 fps\n")})()
        with mock.patch.object(ccc.subprocess, "run", lambda *a, **k: proc):
            self.assertEqual(ccc._dimensions("ffmpeg", "poster-x.jpg"), (800, 460))

    def test_a_file_whose_frame_size_ffmpeg_did_not_report_is_fatal(self):
        proc = type("P", (), {"returncode": 1, "stdout": "", "stderr": "not a media file\n"})()
        with mock.patch.object(ccc.subprocess, "run", lambda *a, **k: proc):
            with self.assertRaises(SystemExit) as caught:
                ccc._dimensions("ffmpeg", "poster-x.jpg")
        self.assertIn("poster-x.jpg", str(caught.exception))

    def test_a_poster_with_no_clip_beside_it_is_refused(self):
        # Both halves of this gate are asked OF THE CLIP: the frame size the poster is measured at,
        # and the frames it must still depict. Without the clip there is nothing to answer them
        # with, and scanning the poster at a guessed size is exactly the confident-verdict-on-
        # nothing this file exists to refuse.
        with mock.patch("os.path.isfile", lambda path: False):
            with self.assertRaises(ccc.Unscannable) as caught:
                ccc.scan_poster("ffmpeg", os.path.join("assets", "poster-x.jpg"))
        self.assertIn("demo-x.webm", str(caught.exception))

    def test_a_poster_is_measured_at_its_clips_frame_size(self):
        # The offsets are video pixels at the publish scale and do NOT chase the frame size
        # (SITE-VIDEO-18), so the poster is scaled back to the frame it was cut from rather than
        # the offsets being scaled down to the poster. That way there is no second geometry to
        # keep in step - the poster is measured by the very probes the clip is.
        seen = {}

        def fake_scan(ffmpeg, path, prefix=""):
            seen["prefix"] = prefix
            return [], 1, 0

        with mock.patch.object(ccc, "scan_clip", fake_scan), \
                mock.patch.object(ccc, "_dimensions",
                                  lambda ffmpeg, path: (1078, 620) if path.endswith(".webm") else (800, 460)), \
                mock.patch.object(ccc, "poster_similarity", lambda *a, **k: 0.99), \
                mock.patch("os.path.isfile", lambda path: True):
            ccc.scan_poster("ffmpeg", os.path.join("assets", "poster-x.jpg"))
        self.assertEqual(seen["prefix"], "scale=1078:620,")

    def test_a_leaked_title_in_a_poster_is_reported(self):
        # The negative control, measured end to end: a terminal frame with the terminal's own
        # rendered text pasted into its title strip, published at the poster's 800x460, reads a
        # spread of 246 where the real poster reads 4. That is the same 25x separation the clip
        # scan enjoys, because it IS the clip scan.
        bad, judged, occluded, _ = self._scan(_poster_frames(246.0))
        self.assertEqual(judged, 1)
        self.assertEqual(occluded, 0)
        self.assertEqual([round(spread) for _, spread in bad], [246])

    def test_a_clean_terminal_poster_passes(self):
        bad, judged, _, similarity = self._scan(_poster_frames(4.0))
        self.assertEqual(bad, [])
        self.assertEqual(judged, 1)
        self.assertEqual(similarity, 0.99)

    def test_a_browser_frame_poster_has_no_chrome_to_check(self):
        # Two of the three published posters are frames of the report in a browser: no window
        # chrome, so no title bar to read. Measured, their lights read 2 and their middle 234-245.
        bad, judged, occluded, _ = self._scan(_poster_frames(200.0, lights=2.0, mid=234.0))
        self.assertEqual((bad, judged, occluded), ([], 0, 0))

    def test_a_poster_that_is_not_a_whole_frame_of_its_clip_is_refused(self):
        # Scaling back only works because a poster is the WHOLE frame, scaled by one factor. A
        # cropped or letterboxed poster stretches under that scale, which moves the chrome off
        # every offset - and the flatness it then measured would mean nothing at all.
        with self.assertRaises(ccc.ScaleMismatch) as caught:
            self._scan(_poster_frames(4.0), poster_size=(800, 400))
        self.assertIn("whole frame", str(caught.exception))

    def test_a_poster_must_depict_a_frame_of_its_current_clip(self):
        # Staleness is the other half. A re-record keeps the clip's filename, so nothing failed
        # when the poster beside it went on showing the OLD recording. Measured with ffmpeg's ssim
        # over every frame: the three published pairs score 0.9894-0.9906, and a poster paired with
        # the wrong clip scores 0.7406-0.7970.
        with self.assertRaises(ccc.StalePoster) as caught:
            self._scan(_poster_frames(4.0), similarity=0.80)
        self.assertIn("demo-x.webm", str(caught.exception))

    def test_the_similarity_floor_sits_between_a_matched_and_a_mismatched_poster(self):
        self.assertGreater(ccc.POSTER_MATCH_MIN, 0.80)
        self.assertLess(ccc.POSTER_MATCH_MIN, 0.9894)

    def test_the_freshness_pass_takes_the_best_match_over_every_frame(self):
        # Which frame was cut is not recorded anywhere, so the question is whether the poster
        # matches ANY frame - the best one over the whole clip, not the first or the last.
        stdout = "".join("n:%d Y:0.5 U:0.9 V:0.8 All:%.6f (4.6)\n" % (i, s)
                         for i, s in enumerate([0.41, 0.99, 0.62] + [0.30] * 30))
        proc = type("P", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()
        with mock.patch.object(ccc.subprocess, "run", lambda *a, **k: proc):
            self.assertAlmostEqual(
                ccc.poster_similarity("ffmpeg", "poster-x.jpg", "demo-x.webm", 800, 460), 0.99)

    def test_a_freshness_pass_that_compared_almost_nothing_is_fatal(self):
        # Writing this comparison with `shortest=1` compared exactly ONE frame and reported 0.44
        # for a poster that matches at 0.99. Reported as a stale poster that would send the
        # operator re-cutting a poster whose only problem is that ffmpeg was not understood, and
        # the mirror of it - one frame that happens to match - would be a pass on nothing.
        proc = type("P", (), {"returncode": 0,
                              "stdout": "n:1 All:0.438956 (3.5)\n", "stderr": ""})()
        with mock.patch.object(ccc.subprocess, "run", lambda *a, **k: proc):
            with self.assertRaises(SystemExit) as caught:
                ccc.poster_similarity("ffmpeg", "poster-x.jpg", "demo-x.webm", 800, 460)
        self.assertIn("1 frame(s)", str(caught.exception))

    def test_a_leaking_poster_is_reported_before_its_freshness_is_even_asked(self):
        # A leak outranks staleness: both replace the poster, but only one says there is a command
        # on screen. Answering "and it is stale too" would bury that, and the freshness pass is a
        # whole extra decode of the clip for a poster that is being replaced anyway.
        asked = []
        frames = iter(_poster_frames(246.0))
        with mock.patch.object(ccc, "_measure", lambda *a, **k: next(frames)), \
                mock.patch.object(ccc, "_dimensions",
                                  lambda ffmpeg, path: (1078, 620) if path.endswith(".webm") else (800, 460)), \
                mock.patch.object(ccc, "poster_similarity", lambda *a, **k: asked.append(1) or 0.5), \
                mock.patch("os.path.isfile", lambda path: True):
            bad, _, _, similarity = ccc.scan_poster("ffmpeg", os.path.join("assets", "poster-x.jpg"))
        self.assertTrue(bad)
        self.assertIsNone(similarity)
        self.assertEqual(asked, [])


class PosterRunTests(unittest.TestCase):
    """What the default run covers, and what it refuses to report as a pass."""

    def _run(self, files, scan_poster=None):
        out = io.StringIO()
        with mock.patch.object(ccc, "find_ffmpeg", lambda: "ffmpeg"), \
                mock.patch.object(ccc, "scan_clip", lambda ffmpeg, clip: ([], 5, 0)), \
                mock.patch.object(ccc, "scan_poster",
                                  scan_poster or (lambda ffmpeg, poster: ([], 1, 0, 0.99))), \
                contextlib.redirect_stdout(out):
            code = ccc.main(files)
        return code, out.getvalue()

    def test_a_poster_passed_by_name_is_scanned_as_a_poster(self):
        code, out = self._run([os.path.join("assets", "poster-x.jpg")])
        self.assertEqual(code, 0)
        self.assertIn("poster-x.jpg", out)
        self.assertIn("OK", out)

    def test_a_leaking_poster_fails_the_run_and_says_what_to_do(self):
        def leaking(ffmpeg, poster):
            return [(0.0, 246.0)], 1, 0, None

        code, out = self._run([os.path.join("assets", "poster-x.jpg")], scan_poster=leaking)
        self.assertNotEqual(code, 0)
        self.assertIn("FAIL", out)
        self.assertIn("showing its launch command", out)

    def test_an_unreadable_poster_does_not_hide_a_later_one(self):
        def fussy(ffmpeg, poster):
            if poster.endswith("poster-a.jpg"):
                raise ccc.StalePoster("poster-a.jpg no longer depicts its clip")
            return [(0.0, 246.0)], 1, 0, None

        code, out = self._run([os.path.join("assets", "poster-a.jpg"),
                               os.path.join("assets", "poster-b.jpg")], scan_poster=fussy)
        self.assertNotEqual(code, 0)
        self.assertIn("poster-a.jpg", out)
        self.assertIn("poster-b.jpg", out)

    def test_the_default_run_covers_the_posters_beside_the_clips(self):
        scanned = {"clips": [], "posters": []}
        listing = ["demo-x.webm", "poster-x.jpg", "styles.css"]
        out = io.StringIO()
        with mock.patch.object(ccc, "find_ffmpeg", lambda: "ffmpeg"), \
                mock.patch.object(ccc.os, "listdir", lambda directory: listing), \
                mock.patch.object(ccc, "scan_clip",
                                  lambda ffmpeg, clip: scanned["clips"].append(clip) or ([], 5, 0)), \
                mock.patch.object(ccc, "scan_poster",
                                  lambda ffmpeg, poster: scanned["posters"].append(poster) or ([], 1, 0, 0.99)), \
                contextlib.redirect_stdout(out):
            self.assertEqual(ccc.main([]), 0)
        self.assertEqual([os.path.basename(p) for p in scanned["clips"]], ["demo-x.webm"])
        self.assertEqual([os.path.basename(p) for p in scanned["posters"]], ["poster-x.jpg"])

    def test_a_run_that_found_no_poster_to_scan_is_an_error_not_a_pass(self):
        # The posters ARE the surface this covers, so a default run that quietly scanned only the
        # clips would report the same OK it reports when both are clean - a gate that goes green
        # having checked nothing, which is the failure mode this whole script is written against.
        out = io.StringIO()
        with mock.patch.object(ccc, "find_ffmpeg", lambda: "ffmpeg"), \
                mock.patch.object(ccc.os, "listdir", lambda directory: ["demo-x.webm"]), \
                mock.patch.object(ccc, "scan_clip", lambda ffmpeg, clip: ([], 5, 0)), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                ccc.main([])
        self.assertIn("no published posters", str(caught.exception))

    def test_a_file_that_is_neither_a_clip_nor_a_poster_is_refused(self):
        with mock.patch.object(ccc, "find_ffmpeg", lambda: "ffmpeg"):
            with self.assertRaises(SystemExit) as caught:
                ccc.main([os.path.join("assets", "styles.css")])
        self.assertIn("styles.css", str(caught.exception))


#: The renderer's chrome CSS, parsed out of the page builders so this file cannot drift from them.
#: Duplicating the geometry as literals is what these tests exist to prevent: the gate and the
#: renderer encode the SAME numbers, and a chrome tweak that moved one silently invalidated the
#: other with every test still green - the recorder-vs-gate disagreement this whole change removes.
RECORDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".github", "skills", "demo-video", "tools", "record_demo.mjs")


def chrome_css():
    """`{prop: px}` for the chrome rules the strip geometry is derived from.

    BOTH page builders are parsed and required to agree. `re.search` finds only the FIRST block, so
    an earlier cut of this validated `terminalPage` and let `stagePage` - which renders the loop
    clip, the one with the transitions - drift away unchecked.
    """
    with open(RECORDER, encoding="utf-8") as handle:
        text = handle.read()

    def rules(selector, prop, index=0):
        blocks = re.findall(r"%s\s*\{([^}]*)\}" % re.escape(selector), text)
        if not blocks:
            raise AssertionError("no %s rule in the recorder" % selector)
        seen = []
        for block in blocks:
            found = re.search(r"(?:^|[;\s])%s:\s*([^;}]+)" % prop, block)
            if not found:
                raise AssertionError("a %s rule has no %s" % (selector, prop))
            lengths = re.findall(r"(-?[\d.]+)px", found.group(1))
            if len(lengths) <= index:
                raise AssertionError("%s %s has no length #%d" % (selector, prop, index))
            seen.append(float(lengths[index]))
        if len(set(seen)) != 1:
            raise AssertionError("the page builders disagree on %s %s: %s" % (selector, prop, seen))
        return seen[0]

    def line_height():
        """The line height the title inherits, read from the page's `font:` shorthand.

        Restating it as a literal 1.4 would let a restyle move the title's line box - and with it
        the row a leaked title's descenders reach - while this file kept asserting against the old
        number, which is the drift these tests exist to prevent.
        """
        found = re.findall(r"html,\s*body\s*\{[^}]*font:\s*[^;}]*?\d+px/([\d.]+)", text)
        if not found:
            raise AssertionError("no inherited line-height in the recorder's html, body rule")
        if len(set(found)) != 1:
            raise AssertionError("the page builders disagree on the line height: %s" % found)
        return float(found[0])

    return {
        "pad_top": rules(".wrap", "padding", 0),
        "pad_side": rules(".wrap", "padding", 1),
        "dot": rules(".dot", "height"),
        "dot_width": rules(".dot", "width"),
        "gap": rules(".chrome", "gap"),
        "chrome_pad_bottom": rules(".chrome", "padding-bottom"),
        "title_margin": rules(".title", "margin-left"),
        "title_font": rules(".title", "font-size"),
        "line_height": line_height(),
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
        # The title is a 12px font in the inherited 1.4 line box, which is TALLER than the 11px
        # dots - so the dots alone are not the bound, and a strip that cleared them could still clip
        # the glyphs' descenders. Take whichever reaches lower.
        row_top = css["pad_top"]
        row_bottom = css["pad_top"] + max(css["dot"], css["title_font"] * css["line_height"])
        self.assertLessEqual(top, row_top * ccc.PUBLISH_SCALE)
        self.assertGreaterEqual(bottom, row_bottom * ccc.PUBLISH_SCALE)

    def test_the_lights_probe_actually_lands_on_the_traffic_lights(self):
        # The lights decide which frames are judged at all, so if this crop drifts off them nothing
        # is judged - and "judged nothing" is the one branch that can still pass. It was the only
        # piece of geometry not bound to the recorder's live CSS.
        css = chrome_css()
        found = re.match(r"crop=(\d+):(\d+):(\d+):(\d+)$", ccc.LIGHTS)
        self.assertTrue(found, "LIGHTS is not the expected crop shape: %r" % ccc.LIGHTS)
        width, height, x, y = (int(g) for g in found.groups())
        lights_left = css["pad_side"] * ccc.PUBLISH_SCALE
        lights_right = (css["pad_side"] + 3 * css["dot_width"] + 2 * css["gap"]) * ccc.PUBLISH_SCALE
        lights_top = css["pad_top"] * ccc.PUBLISH_SCALE
        lights_bottom = (css["pad_top"] + css["dot"]) * ccc.PUBLISH_SCALE
        self.assertGreaterEqual(x, lights_left - 1)
        self.assertLessEqual(x + width, lights_right + 1)
        self.assertGreaterEqual(y, lights_top - 1)
        self.assertLessEqual(y + height, lights_bottom + 1)

    def test_every_traffic_light_is_saturated_enough_to_be_found(self):
        # LIGHTS_PRESENT is measured against the dots' own colours. Restyling them to something
        # softer would stop every frame being judged while every test stayed green, so derive the
        # bound from the palette the recorder actually paints.
        with open(RECORDER, encoding="utf-8") as handle:
            text = handle.read()
        colours = set(re.findall(r'class="dot"[^>]*background:\s*(#[0-9a-fA-F]{6})', text))
        self.assertEqual(len(colours), 3, "expected three distinct traffic lights, got %s" % colours)
        for colour in colours:
            r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
            # ffmpeg signalstats SAT, in the same BT.601 chroma space it measures.
            cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
            cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
            saturation = ((cb - 128) ** 2 + (cr - 128) ** 2) ** 0.5
            self.assertGreaterEqual(saturation, ccc.LIGHTS_PRESENT,
                                    "%s reads SAT %.1f, under LIGHTS_PRESENT" % (colour, saturation))

    def test_the_present_threshold_sits_between_a_faded_and_a_drawn_light(self):
        # Measured: admitting frames at 60 let the report panel's white edge into the strip on the
        # loop clip (spread 86); the drawn population reads 81-94 there and 80-100 on the multi-duck
        # clip, so the threshold must not exceed the dimmest drawn light or real frames are dropped.
        self.assertGreater(ccc.LIGHTS_PRESENT, ccc.LIGHTS_ABSENT)
        self.assertGreater(ccc.LIGHTS_PRESENT, 60.0)
        self.assertLessEqual(ccc.LIGHTS_PRESENT, 80.0)

    def test_the_gutter_probe_lies_between_the_title_row_and_the_terminal(self):
        # The gutter is the chrome's own bottom padding: background on every settled frame whatever
        # the terminal prints, and a row a title can never be drawn on. Both bounds matter - drift
        # UP and it starts reading the title (an occlusion gate that could hide a real leak), drift
        # DOWN and it reads the terminal's antialiased first row on every frame (a gate that judges
        # nothing). The band the padding leaves is only 8.5 video px tall, so the clearances cannot
        # both be as generous as the strip's 4.0: the panel's answer is that the two sides fail
        # differently. Reading the title would be silent, and is guarded by the coarse leak check
        # that still inspects a skipped frame; reading the terminal only DECLINES frames, and a
        # clip that declines most of them is refused rather than passed (MAX_OCCLUDED_SHARE).
        css = chrome_css()
        found = re.match(r"crop=iw:(\d+):0:(\d+)$", ccc.GUTTER)
        self.assertTrue(found, "GUTTER is not the expected crop shape: %r" % ccc.GUTTER)
        height, top = (int(g) for g in found.groups())
        # These clips are yuv420p, so ffmpeg snaps an odd crop to an even one: a band written at
        # y=23 measures the same rows as one written at y=22, and the assertions below would then
        # be checking a band that is not the one being measured.
        self.assertEqual((top % 2, height % 2), (0, 0),
                         "GUTTER must be even-aligned or ffmpeg measures different rows than these "
                         "offsets describe")
        title_row_bottom = ((css["pad_top"] + max(css["dot"], css["title_font"] * css["line_height"]))
                            * ccc.PUBLISH_SCALE)
        terminal_top = (css["pad_top"] + css["dot"] + css["chrome_pad_bottom"]) * ccc.PUBLISH_SCALE
        self.assertGreaterEqual(top, title_row_bottom + 2.0,
                                "the gutter starts %.1f video px below the title's line box"
                                % (top - title_row_bottom))
        self.assertGreaterEqual(terminal_top - (top + height), 2.0,
                                "the terminal starts %.1f video px below the gutter"
                                % (terminal_top - (top + height)))

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

    def _scan(self, satmax, gutter_spread=6.0):
        strip = [{"t": 0.4, "YMIN": 0.0, "YMAX": 1.0, "SATMAX": satmax}]
        lights = [{"SATMAX": 88.0}]
        gutter = [{"YMIN": 0.0, "YMAX": gutter_spread}]
        kind = [{"YAVG": 30.0}]
        for row in (lights[0], gutter[0], kind[0]):
            row["t"] = 0.4
        calls = iter([strip, lights, gutter, kind])
        original = ccc._measure
        ccc._measure = lambda *a, **k: next(calls)
        try:
            return ccc.scan_clip("ffmpeg", "clip.webm")[0]
        finally:
            ccc._measure = original

    def test_a_mis_scaled_clip_says_scale_even_when_its_gutter_reads_as_painted_over(self):
        # At another scale nothing lands where these offsets expect it: the lights fall inside the
        # strip AND the gutter falls on the title row, so the clip reads as occluded everywhere.
        # Reporting "something is painted over the chrome" there would send the operator re-recording
        # a clip whose only problem is the scale it was rendered at, so the colour wins.
        with self.assertRaises(ccc.ScaleMismatch) as caught:
            self._scan(200.0, gutter_spread=ccc.GUTTER_TOLERANCE + 22)
        self.assertIn("--scale 0.6", str(caught.exception))

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

    def test_the_gutter_tolerance_separates_settled_chrome_from_a_ghosted_frame(self):
        # Measured over the published loop clip's 598 judged frames: the gutter reads at most 19 on
        # a settled frame and 24-44 while the report is still painted over the window, with nothing
        # in between. It must also be TIGHTER than the strip's leak tolerance, or it would admit
        # exactly the frames it exists to drop, and the coarse tolerance that still inspects a
        # skipped frame must sit ABOVE any measured ghost (33) and below a real title (167).
        self.assertGreater(ccc.GUTTER_TOLERANCE, 19.0)
        self.assertLess(ccc.GUTTER_TOLERANCE, 24.0)
        self.assertLess(ccc.GUTTER_TOLERANCE, ccc.FLAT_TOLERANCE)
        # The coarse tolerance is bounded by arithmetic on the overlay, not by one clip: with the
        # lights still reading as drawn the overlay is at most ~15%, so a ghost on flat chrome
        # cannot spread past 0.15*255 = 38, and a title cannot spread under 0.85*167 - 0.15*255.
        self.assertGreater(ccc.OCCLUDED_LEAK_TOLERANCE, 38.0)
        self.assertLess(ccc.OCCLUDED_LEAK_TOLERANCE, 0.85 * 167.0 - 0.15 * 255.0)
        self.assertGreater(ccc.OCCLUDED_LEAK_TOLERANCE, ccc.FLAT_TOLERANCE)

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
            return [], 5, 0

        original_scan, original_find = ccc.scan_clip, ccc.find_ffmpeg
        ccc.scan_clip, ccc.find_ffmpeg = fake, lambda: "ffmpeg"
        try:
            code = ccc.main(["bad.webm", "good.webm"])
        finally:
            ccc.scan_clip, ccc.find_ffmpeg = original_scan, original_find
        self.assertEqual(seen, ["bad.webm", "good.webm"])
        self.assertNotEqual(code, 0)

    def test_a_clip_on_another_drive_is_still_scanned(self):
        # `os.path.relpath` raises on Windows when the two paths are on different drives, and the
        # only thing it is used for here is a short LABEL. Scanning a clip outside the checkout is
        # the normal case, not a corner: SKILL.md tells the operator to render to a scratch
        # directory and pass the new clips in, and the script suite runs from a sandbox cwd. On the
        # CI Windows runner (checkout on D:, temp on C:) that killed the whole run with a ValueError
        # before a single clip got a verdict - a naming detail taking down the gate.
        scanned = []

        def fake(ffmpeg, clip):
            scanned.append(clip)
            return [], 5, 0

        original_scan, original_find = ccc.scan_clip, ccc.find_ffmpeg
        ccc.scan_clip, ccc.find_ffmpeg = fake, lambda: "ffmpeg"
        try:
            with mock.patch("os.path.relpath",
                            side_effect=ValueError("path is on mount 'C:', start on mount 'D:'")):
                code = ccc.main(["C:\\scratch\\demo.webm"])
        finally:
            ccc.scan_clip, ccc.find_ffmpeg = original_scan, original_find
        self.assertEqual(scanned, ["C:\\scratch\\demo.webm"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
