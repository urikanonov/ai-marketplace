#!/usr/bin/env python3
"""Fail if a published demo clip's video is not VP9.

The clips are published VP9 on purpose: at the same picture (SSIM 0.99) the three of them are
7,011,625 bytes rather than the 13,260,684 Chromium's recorder writes - 47% off - and the site
fetches a whole clip the moment a thumbnail is pressed (SITE-VIDEO-03).

That compression used to be an ACCIDENT. Two of the clips were VP9 only because a hand-applied
ffmpeg mask happened to re-encode them on its way past; when the recorder stopped needing that mask
the clips silently reverted to Chromium's VP8, well over half again as heavy, and nothing noticed -
while two documents went on claiming they were VP9 (#866). A property nobody checks is a property
that only holds until the next re-record, so this makes the codec an explicit gate on the FINAL
published bytes.

It reads the WebM container directly rather than shelling out to ffprobe: the codec is written in
plain text in the track header (`V_VP9`), so checking it needs no decoder, no PATH lookup and no
skip path. A gate with no way to be skipped cannot go green having checked nothing.

Because failing CLOSED is the whole point, the reader is strict rather than
forgiving. It walks the one path that can legitimately hold a codec name - EBML header, then
Segment / Tracks / TrackEntry / CodecID - and refuses anything that does not fit: a file that does
not start with an EBML header, an element that declares more bytes than its parent contains (a
truncated clip whose codec name is only half there would otherwise read as VP9), a header that
crosses its parent's end, a track entry that does not name exactly one codec, or an unknown-size
element that is not one of the masters it descends into. Every one of those is a container it
cannot vouch for, and vouching is the entire job.

What it does NOT do is decode. A container can label a VP8 stream `V_VP9` and this reader - like
`ffprobe` - will believe it. That is not the regression this exists to catch (Chromium's recorder
writes an honest `V_VP8`), and the required `site` job runs `check_clip_chrome.py --require-ffmpeg`
over the same bytes immediately afterwards, which does decode every frame. Keep that pairing: this
gate is the cheap, unskippable half, not a substitute for it.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Both the bytes the site serves and the committed source the build copies them FROM. Checking only
# the served copy would pass a tree whose source is still VP8, and the next site rebuild would
# quietly re-publish it.
CLIP_DIRS = (os.path.join("site", "dist", "assets"), os.path.join("site", "src"))
EXPECTED_CODEC = "V_VP9"
# Matroska spells a video track's codec `V_...` and an audio track's `A_...`. The gate is about the
# picture, so a clip that ever ships with sound is judged on its video track rather than failed for
# carrying an Opus one.
VIDEO_PREFIX = "V_"

# The EBML ids on the path from the file down to the codec name. Everything else (the SeekHead,
# the Cues, and the megabytes of Clusters) is stepped over by its declared size.
EBML_HEADER = 0x1A45DFA3
DOC_TYPE = 0x4282
SEGMENT = 0x18538067
TRACKS = 0x1654AE6B
TRACK_ENTRY = 0xAE
CODEC_ID = 0x86
# The only nesting this reader accepts: each key is the element it is currently inside (None at the
# top of the file) and the value is the one child it will descend into. Anything else is skipped by
# its size, so a codec name found off this path is not counted - a seven-byte file holding nothing
# but a bare `CodecID: V_VP9` is not a WebM and must not pass. The map is also what bounds the
# recursion: it is three links long and TrackEntry descends no further, so a malformed file cannot
# drive this deeper than a real track header goes.
DESCEND_INTO = {None: SEGMENT, SEGMENT: TRACKS, TRACKS: TRACK_ENTRY}


class ClipFormatError(Exception):
    """The file is not a WebM this reader understands, so its codec cannot be asserted.

    Raised rather than returning "no codec found": an unreadable clip that reported nothing would
    pass a gate whose whole job is to prove what was published.
    """


def _read_element_id(fh, remaining):
    """Return `(id, width)` with the length-marker bits KEPT, which is how EBML ids are written.

    `remaining` bounds the read at the parent's end. Without it a header sitting near that boundary
    reads on into the FOLLOWING sibling and yields a fabricated id and size - a malformed region
    parsed as a plausible element instead of being refused.
    """
    if remaining <= 0:
        return None, 0
    head = fh.read(1)
    if not head:
        return None, 0
    first = head[0]
    if first == 0:
        raise ClipFormatError("element id wider than 8 bytes")
    width = 9 - first.bit_length()
    if width > remaining:
        raise ClipFormatError("element id runs past the end of its parent")
    rest = fh.read(width - 1)
    if len(rest) != width - 1:
        raise ClipFormatError("truncated element id")
    return int.from_bytes(head + rest, "big"), width


def _read_element_size(fh, remaining):
    """Return `(size, width)`; size is None for the "unknown, runs to the end" encoding."""
    if remaining <= 0:
        raise ClipFormatError("truncated element size")
    head = fh.read(1)
    if not head:
        raise ClipFormatError("truncated element size")
    first = head[0]
    if first == 0:
        raise ClipFormatError("element size wider than 8 bytes")
    width = 9 - first.bit_length()
    if width > remaining:
        raise ClipFormatError("element size runs past the end of its parent")
    rest = fh.read(width - 1)
    if len(rest) != width - 1:
        raise ClipFormatError("truncated element size")
    value = first & (0xFF >> width)
    # At width 8 the first byte carries no value bits at all (`0xFF >> 8` is 0), so `unknown`
    # starts True and it is the tail loop below that has to clear it. That is the width every
    # published clip actually uses, ffmpeg reserving a full 8-byte Segment size.
    unknown = value == (0xFF >> width)
    for byte in rest:
        unknown = unknown and byte == 0xFF
        value = (value << 8) | byte
    return (None if unknown else value), width


def _scan(fh, start, end, parent):
    """Collect the CodecID of every TrackEntry under `[start, end)`, stopping after Tracks."""
    codecs = []
    pos = start
    while pos < end:
        fh.seek(pos)
        element, id_width = _read_element_id(fh, end - pos)
        if element is None:
            break
        size, size_width = _read_element_size(fh, end - pos - id_width)
        body = pos + id_width + size_width
        descend = DESCEND_INTO.get(parent) == element
        if size is None:
            # Only the Segment may legitimately go unsized here: a live recorder streaming to disk
            # cannot know the length yet. (Nothing this repo publishes does - ffmpeg reserves a real
            # 8-byte Segment size - but the shape is legal EBML.) Anything ELSE with an unknown size
            # cannot be stepped over, and guessing where it ends would let the rest of the file go
            # unread while a verdict was still reported.
            if element != SEGMENT or not descend:
                raise ClipFormatError(
                    "element 0x%X at byte %d declares an unknown size, which only the Segment may "
                    "do, so the rest of the file cannot be trusted. Re-encode the clip with the "
                    "publish recipe in .github/skills/demo-video/SKILL.md." % (element, pos))
            stop = end
        else:
            stop = body + size
            if stop > end:
                raise ClipFormatError(
                    "element 0x%X at byte %d declares %d bytes, which runs past the %d that remain "
                    "in its parent" % (element, pos, size, end - body))
        if element == CODEC_ID and parent == TRACK_ENTRY:
            fh.seek(body)
            raw = fh.read(stop - body)
            if len(raw) != stop - body:
                raise ClipFormatError("truncated codec name at byte %d" % body)
            codecs.append(raw.rstrip(b"\x00").decode("ascii", "replace"))
        elif descend:
            found = _scan(fh, body, stop, element)
            if element == TRACK_ENTRY and len(found) != 1:
                raise ClipFormatError("the track entry at byte %d names %d codecs, not one"
                                      % (pos, len(found)))
            codecs.extend(found)
            if element == TRACKS:
                # The verdict is on the FIRST Tracks; the bytes after it are never read. That is
                # deliberate: reading on would walk into the Clusters, and a live recorder writes
                # those with an unknown size, so a legal recording would be refused.
                return codecs
        pos = stop
    return codecs


def _doc_type(fh, start, end):
    """Return the EBML header's DocType string, or None when it names none."""
    pos = start
    while pos < end:
        fh.seek(pos)
        element, id_width = _read_element_id(fh, end - pos)
        if element is None:
            break
        size, size_width = _read_element_size(fh, end - pos - id_width)
        if size is None:
            raise ClipFormatError("the EBML header holds an unknown-size element")
        body = pos + id_width + size_width
        stop = body + size
        if stop > end:
            raise ClipFormatError("an EBML header element runs past the header")
        if element == DOC_TYPE:
            fh.seek(body)
            return fh.read(size).rstrip(b"\x00").decode("ascii", "replace")
        pos = stop
    return None


def read_codecs(path):
    """Return the CodecID strings of every track in `path`, in file order."""
    try:
        with open(path, "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            first, id_width = _read_element_id(fh, size)
            if first != EBML_HEADER:
                raise ClipFormatError("%s does not begin with an EBML header, so it is not a WebM"
                                      % path)
            header_size, size_width = _read_element_size(fh, size - id_width)
            if header_size is None:
                raise ClipFormatError("%s declares an unknown-size EBML header" % path)
            header_body = id_width + size_width
            # The header says which Matroska profile this is. A `matroska` DocType decodes fine but
            # is not what the site claims to serve, and only `webm` guarantees the VP9-in-WebM
            # profile browsers accept - so an accurate codec on the wrong container is still wrong.
            doc = _doc_type(fh, header_body, min(header_body + header_size, size))
            if doc != "webm":
                raise ClipFormatError("%s declares DocType %r, not 'webm'"
                                      % (path, doc if doc is not None else "none"))
            codecs = _scan(fh, 0, size, None)
    except OSError as exc:
        raise ClipFormatError("cannot read %s (%s)" % (path, exc))
    if not codecs:
        raise ClipFormatError("no track codec found in %s; it is not a WebM this reader "
                              "understands, so what was published cannot be asserted" % path)
    return codecs


def wrong_codec(codecs):
    """Return why `codecs` is not a publishable set, or None when it is."""
    video = [c for c in codecs if c.startswith(VIDEO_PREFIX)]
    if len(video) != 1:
        return "carries %d video tracks, expected exactly one" % len(video)
    if video[0] != EXPECTED_CODEC:
        return "published as %s, expected %s" % (video[0], EXPECTED_CODEC)
    return None


def display_name(clip):
    """A short label that can never take the scan down (see check_clip_chrome.display_name)."""
    try:
        return os.path.relpath(clip, REPO_ROOT)
    except ValueError:
        return clip


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clips", nargs="*", help="clips to check (default: every published clip)")
    args = parser.parse_args(argv)

    clips = args.clips
    if not clips:
        for part in CLIP_DIRS:
            directory = os.path.join(REPO_ROOT, part)
            try:
                names = sorted(os.listdir(directory))
            except OSError as exc:
                raise SystemExit("cannot list %s (%s)" % (part, exc))
            clips.extend(os.path.join(directory, n) for n in names if n.endswith(".webm"))
    if not clips:
        raise SystemExit("no published clips found under %s" % " or ".join(CLIP_DIRS))

    failed = False
    for clip in clips:
        name = display_name(clip)
        try:
            codecs = read_codecs(clip)
        except ClipFormatError as problem:
            failed = True
            print("FAIL %s: %s" % (name, problem))
            continue
        problem = wrong_codec(codecs)
        if problem:
            failed = True
            print("FAIL %s: %s" % (name, problem))
        else:
            print("OK   %s (%s)" % (name, ", ".join(codecs)))
    if failed:
        print("\nA published clip is not VP9. Chromium's recorder writes VP8, so a re-recorded clip "
              "must be re-encoded before it is published - see the compression pass in "
              ".github/skills/demo-video/SKILL.md.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
