"""Unit tests for the published-clip codec gate (SITE-VIDEO-22).

Two halves. The EBML reader is pinned against hand-built containers, because it has to survive the
shape Chromium actually writes (an unknown-size Segment, since a live recorder cannot know the
length yet) as well as the tidy known-size one ffmpeg produces - and, more importantly, because a
gate that exists to fail CLOSED has to be shown failing on every container it cannot vouch for. Each
rejection below is a way a malformed file used to read as `V_VP9`. The second half points the reader
at the REAL published clips, so the gate is the assertion rather than a description of one: the
codec regressed in the first place because nothing ever looked (#866).
"""

import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_clip_codec as ccc

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _vint(value, width=None):
    """Encode an EBML unsigned length with its leading marker bit."""
    if width is None:
        width = 1
        while value >= (1 << (7 * width)) - 1:
            width += 1
    data = value.to_bytes(width, "big")
    marker = 1 << (8 - width)
    return bytes([data[0] | marker]) + data[1:]


def _raw_id(element_id):
    return element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")


def _element(element_id, payload, unknown_size=False, declared=None, size_width=None):
    """Build one EBML element. `declared` overrides the size field without changing the payload."""
    if unknown_size:
        size = b"\xff" if size_width is None else bytes([1 << (8 - size_width)]) + b"\xff" * (size_width - 1)
    else:
        size = _vint(len(payload) if declared is None else declared, size_width)
    return _raw_id(element_id) + size + payload


def _header(doc_type=b"webm"):
    # The header's DocType is what says WHICH Matroska profile this is; the gate requires `webm`.
    return _element(ccc.EBML_HEADER, _element(ccc.DOC_TYPE, doc_type))


def _tracks(codecs):
    return _element(ccc.TRACKS, b"".join(
        _element(ccc.TRACK_ENTRY, _element(ccc.CODEC_ID, name.encode("ascii")))
        for name in codecs))


def _webm(codecs, unknown_segment=False, body=None, doc_type=b"webm"):
    """A minimal container carrying one TrackEntry per codec name."""
    # A Cluster ahead of the Tracks: the reader must step over the bulk of the file by size rather
    # than searching it, which is also what keeps a 6 MB clip cheap to check.
    filler = _element(0x1F43B675, b"\x00" * 64)
    payload = filler + (_tracks(codecs) if body is None else body)
    return _header(doc_type) + _element(ccc.SEGMENT, payload, unknown_size=unknown_segment)


class _TempDirTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name
        self.addCleanup(self._dir.cleanup)

    def _write(self, blob, name="clip.webm"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(blob)
        return path

    def _codecs(self, blob):
        return ccc.read_codecs(self._write(blob))


class ReaderTests(_TempDirTest):
    def test_a_known_size_segment_reports_its_codec(self):
        self.assertEqual(self._codecs(_webm(["V_VP9"])), ["V_VP9"])

    def test_an_unknown_size_segment_reports_its_codec(self):
        # A live recorder streaming to disk cannot know the Segment length yet. Nothing this repo
        # publishes is written that way, but the shape is legal EBML and is accepted.
        self.assertEqual(self._codecs(_webm(["V_VP8"], unknown_segment=True)), ["V_VP8"])

    def test_every_track_is_reported_not_just_the_first(self):
        self.assertEqual(self._codecs(_webm(["V_VP9", "A_OPUS"])), ["V_VP9", "A_OPUS"])

    def test_a_file_with_no_track_header_is_refused(self):
        # Reporting "nothing found" would PASS a gate whose job is to prove what was published.
        with self.assertRaises(ccc.ClipFormatError):
            self._codecs(b"not a webm at all")

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(ccc.ClipFormatError):
            ccc.read_codecs(os.path.join(self.tmp, "absent.webm"))

    def test_a_bare_codec_id_with_no_container_around_it_is_refused(self):
        # Seven bytes that say V_VP9 and nothing else are not a clip. Counting a codec name found
        # off the Segment/Tracks/TrackEntry path would let this pass as a published video.
        with self.assertRaises(ccc.ClipFormatError):
            self._codecs(_element(ccc.CODEC_ID, b"V_VP9"))

    def test_a_codec_id_outside_a_track_entry_is_not_counted(self):
        # Same shape, but wrapped in a real Segment and Tracks - still not a track's codec.
        with self.assertRaises(ccc.ClipFormatError):
            self._codecs(_webm([], body=_element(ccc.TRACKS, _element(ccc.CODEC_ID, b"V_VP9"))))

    def test_a_track_entry_with_no_codec_name_is_refused(self):
        with self.assertRaises(ccc.ClipFormatError):
            self._codecs(_webm([], body=_element(ccc.TRACKS, _element(ccc.TRACK_ENTRY, b""))))

    def test_a_child_declaring_more_bytes_than_its_parent_holds_is_refused(self):
        # The fail-open this gate was nearly shipped with: the codec name declares 10 bytes but
        # only carries `V_VP9`, and a reader that clamps the overrun to the parent's end reads
        # those 5 bytes and reports a healthy VP9 clip. Assert on the MESSAGE, so the test cannot
        # go green through some other refusal (an earlier cut of it passed via "no track codec
        # found" while the overrun path did not raise at all).
        entry = _element(ccc.TRACK_ENTRY, _element(ccc.CODEC_ID, b"V_VP9", declared=10))
        with self.assertRaisesRegex(ccc.ClipFormatError, "runs past"):
            self._codecs(_webm([], body=_element(ccc.TRACKS, entry)))

    def test_a_dropped_trailing_track_is_refused_rather_than_half_reported(self):
        # Tracks declares two entries but the file holds the first plus a stub of the second.
        # Reporting ['V_VP9'] here would be the gate vouching for a track it never read.
        first = _element(ccc.TRACK_ENTRY, _element(ccc.CODEC_ID, b"V_VP9"))
        second = _element(ccc.TRACK_ENTRY, _element(ccc.CODEC_ID, b"V_VP8"))
        tracks = (_raw_id(ccc.TRACKS) + _vint(len(first) + len(second))
                  + first + second[:len(second) - 4])
        with self.assertRaisesRegex(ccc.ClipFormatError, "runs past"):
            self._codecs(_webm([], body=tracks))

    def test_an_element_header_may_not_cross_its_parents_end(self):
        # A one-byte Tracks payload holds an element id but no size field. Reading on regardless
        # would take the FOLLOWING sibling's bytes as this element's size.
        with self.assertRaisesRegex(ccc.ClipFormatError, "truncated element size"):
            self._codecs(_webm([], body=_element(ccc.TRACKS, b"\xae") + _tracks(["V_VP9"])))

    def test_an_element_id_may_not_cross_its_parents_end(self):
        # Two bytes of a four-byte id. The id must be refused rather than completed from whatever
        # follows the parent.
        with self.assertRaisesRegex(ccc.ClipFormatError, "element id runs past"):
            self._codecs(_webm([], body=_element(ccc.TRACKS, b"\x16\x54") + _tracks(["V_VP9"])))

    def test_a_width_eight_size_field_is_read_correctly(self):
        # The width every published clip actually carries: ffmpeg reserves a full 8-byte Segment
        # size. It is also the trickiest arm of the size decoder - at width 8 the first byte holds
        # no value bits, so "unknown" starts out true and only the tail can clear it. The Cluster
        # here is what makes the test bite: it is SKIPPED by its width-8 size, so decoding that
        # size as "unknown" would refuse the file rather than quietly still finding the Tracks.
        cluster = _element(0x1F43B675, b"\x00" * 64, size_width=8)
        payload = cluster + _tracks(["V_VP9"])
        blob = _header() + _element(ccc.SEGMENT, payload, size_width=8)
        self.assertEqual(self._codecs(blob), ["V_VP9"])

    def test_a_width_eight_unknown_size_is_still_recognised_as_unknown(self):
        payload = _tracks(["V_VP9"])
        blob = _header() + _element(ccc.SEGMENT, payload, unknown_size=True, size_width=8)
        self.assertEqual(self._codecs(blob), ["V_VP9"])

    def test_a_truncated_file_is_refused(self):
        blob = _webm(["V_VP9"])
        with self.assertRaises(ccc.ClipFormatError):
            self._codecs(blob[:len(blob) - 40])

    def test_an_unknown_size_element_that_is_not_the_segment_is_refused(self):
        # Only the Segment may go unsized. Any other element's end cannot be computed, so
        # everything after it would go unread while the scan still returned a verdict.
        cluster = _element(0x1F43B675, b"\x00" * 8, unknown_size=True)
        with self.assertRaisesRegex(ccc.ClipFormatError, "unknown size"):
            self._codecs(_header() + _element(ccc.SEGMENT, cluster + _tracks(["V_VP9"])))

    def test_an_unknown_size_tracks_element_is_refused(self):
        # Unsized is legal for the Segment alone; accepting it for a Tracks element would let an
        # illegal container through on the very path the codec name is read from.
        tracks = _element(ccc.TRACKS, _element(
            ccc.TRACK_ENTRY, _element(ccc.CODEC_ID, b"V_VP9")), unknown_size=True)
        with self.assertRaisesRegex(ccc.ClipFormatError, "unknown size"):
            self._codecs(_webm([], body=tracks))

    def test_an_unknown_size_track_entry_cannot_hide_the_track_after_it(self):
        # The exact fail-open this rule closes: an unsized TrackEntry swallows the rest of Tracks,
        # so the VP8 track that follows is never counted and the clip passes as VP9.
        hider = _element(ccc.TRACK_ENTRY, _element(ccc.CODEC_ID, b"V_VP9"), unknown_size=True)
        real = _element(ccc.TRACK_ENTRY, _element(ccc.CODEC_ID, b"V_VP8"))
        with self.assertRaisesRegex(ccc.ClipFormatError, "unknown size"):
            self._codecs(_webm([], body=_element(ccc.TRACKS, hider + real)))

    def test_a_matroska_doc_type_is_refused(self):
        # A `matroska` DocType decodes fine but is not the profile the site claims to serve, so an
        # accurate codec inside it is still the wrong container.
        with self.assertRaisesRegex(ccc.ClipFormatError, "DocType"):
            self._codecs(_webm(["V_VP9"], doc_type=b"matroska"))

    def test_a_header_naming_no_doc_type_is_refused(self):
        blob = _element(ccc.EBML_HEADER, b"") + _element(ccc.SEGMENT, _tracks(["V_VP9"]))
        with self.assertRaisesRegex(ccc.ClipFormatError, "DocType"):
            self._codecs(blob)


class VerdictTests(_TempDirTest):
    def _run(self, blob):
        path = self._write(blob)
        out = io.StringIO()
        stdout, sys.stdout = sys.stdout, out
        try:
            return ccc.main([path]), out.getvalue()
        finally:
            sys.stdout = stdout

    def test_vp9_passes(self):
        status, _ = self._run(_webm(["V_VP9"]))
        self.assertEqual(status, 0)

    def test_vp8_fails_and_names_what_it_found(self):
        status, output = self._run(_webm(["V_VP8"]))
        self.assertEqual(status, 1)
        self.assertIn("V_VP8", output)
        self.assertIn("V_VP9", output)

    def test_an_unreadable_clip_fails_rather_than_being_skipped(self):
        status, _ = self._run(b"still not a webm")
        self.assertEqual(status, 1)

    def test_an_audio_track_alongside_vp9_video_is_not_a_failure(self):
        # The clips are silent today (the publish recipe passes -an), but the property being gated
        # is the PICTURE. Failing a legitimate clip for carrying sound would be a false alarm.
        self.assertIsNone(ccc.wrong_codec(["V_VP9", "A_OPUS"]))

    def test_a_clip_with_no_video_track_is_a_failure(self):
        self.assertIsNotNone(ccc.wrong_codec(["A_OPUS"]))

    def test_a_clip_with_two_video_tracks_is_a_failure(self):
        # A published clip is one picture; two says the file is not what the site thinks it serves.
        self.assertIsNotNone(ccc.wrong_codec(["V_VP9", "V_VP9"]))


class PublishedClipTests(unittest.TestCase):
    """The gate itself. Every clip the site serves, and the source each is copied from, is VP9."""

    def _clips(self, *parts):
        directory = os.path.join(REPO_ROOT, *parts)
        names = sorted(n for n in os.listdir(directory) if n.endswith(".webm"))
        self.assertTrue(names, "no clips found under %s" % os.path.join(*parts))
        return [os.path.join(directory, n) for n in names]

    def test_every_published_clip_is_vp9(self):
        for clip in self._clips("site", "dist", "assets"):
            with self.subTest(clip=os.path.basename(clip)):
                self.assertIsNone(ccc.wrong_codec(ccc.read_codecs(clip)))

    def test_every_clip_source_is_vp9(self):
        # site/src is what the build copies, so a VP8 source would re-publish itself on the next
        # site rebuild even after the served copy had been fixed.
        for clip in self._clips("site", "src"):
            with self.subTest(clip=os.path.basename(clip)):
                self.assertIsNone(ccc.wrong_codec(ccc.read_codecs(clip)))


if __name__ == "__main__":
    unittest.main()
