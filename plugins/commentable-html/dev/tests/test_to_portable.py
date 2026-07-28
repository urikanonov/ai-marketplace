#!/usr/bin/env python3
"""NonPortable documents can be migrated to Portable, and stay readable forever (CMH-PORT-01/02).

Portable is now the ONLY mode this skill GENERATES, but a NonPortable document created by an
earlier release must keep working indefinitely - there is no deprecation deadline. Two promises
have to hold, and they pull in opposite directions, so both are pinned here:

1. MIGRATION. `to_portable.py` converts an existing NonPortable document into a self-contained
   Portable one, preserving its authored content, its embedded comments, and its handled ids.
   Without it, "we no longer generate NonPortable" would strand every document already out there.
2. PERMANENT COMPATIBILITY. A NonPortable document is still opened, validated, and finalized. The
   NonPortable runtime and its companion files are retained on purpose; only CREATING a new one
   goes away.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import new_document  # noqa: E402
import to_portable  # noqa: E402
import upgrade  # noqa: E402
import validate  # noqa: E402

_BOOTSTRAP_BEGIN_TEXT = "BEGIN: commentable-html - NONPORTABLE BOOTSTRAP"
_BOOTSTRAP_END_TEXT = "END: commentable-html - NONPORTABLE BOOTSTRAP"

FRAGMENT = ("<h1>Legacy</h1>\n<p>Authored prose that must survive the migration.</p>\n"
            "<pre><code class=\"language-python\">def keep(x):\n    return x\n</code></pre>")


def _read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


class _Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cmh-to-portable-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.nonportable = os.path.join(self.tmp, "legacy.html")
        template = _read(os.path.join(_paths.DIST, "NONPORTABLE.html"))
        _write(self.nonportable, new_document.make_document(
            template, FRAGMENT, key="legacy-doc", label="Legacy",
            source="legacy.html", kind="report"))
        # A NonPortable document references its companions by path; put them alongside so the
        # document is genuinely loadable and the validator's companion checks are meaningful.
        for name in ("commentable-html.css", "commentable-html.js", "commentable-html.assets.js"):
            shutil.copyfile(os.path.join(_paths.DIST, name), os.path.join(self.tmp, name))
        self.layer = to_portable.read_layer(_paths.DIST)
        self.layer_assets = _read(os.path.join(_paths.DIST, "commentable-html.assets.js"))


class MigrationTests(_Case):
    """CMH-PORT-01: to_portable.py migrates an existing NonPortable document."""

    def test_the_fixture_really_is_nonportable(self):
        html = _read(self.nonportable)
        self.assertTrue(to_portable.is_nonportable(html),
                        "fixture premise: the document must start out NonPortable")
        self.assertIn('"mode":"nonportable"', html.replace(" ", ""))

    def test_migration_produces_a_self_contained_portable_document(self):
        out, changed = to_portable.to_portable(_read(self.nonportable), self.layer)
        self.assertTrue(changed)
        self.assertFalse(to_portable.is_nonportable(out))
        self.assertIn('"mode":"portable"', out.replace(" ", ""))
        # No companion references may remain: that is what "self-contained" means.
        for name in ("commentable-html.css", "commentable-html.js", "commentable-html.assets.js"):
            self.assertNotIn('href="%s"' % name, out)
            self.assertNotIn('src="%s"' % name, out)

    def test_migration_preserves_the_authored_content(self):
        out, _ = to_portable.to_portable(_read(self.nonportable), self.layer)
        self.assertIn("Authored prose that must survive the migration.", out)
        self.assertIn("def keep(x):", out)

    def test_migration_preserves_embedded_comments_and_handled_ids(self):
        # The whole point of migrating rather than regenerating: review state travels with it.
        html = _read(self.nonportable)
        marked, n = re.subn(r'(id="handledCommentIds"[^>]*>\s*)\[\]', r'\g<1>["kept-id"]',
                            html, count=1)
        self.assertEqual(n, 1, "fixture premise: the handled-ids block must be present")
        note = {"id": "c-kept", "quote": "quoted text", "note": "a reviewer note that must live",
                "created": "2026-01-01T00:00:00.000Z"}
        marked, n = re.subn(r'(id="embeddedComments"[^>]*>\s*)\[\]',
                            lambda m: m.group(1) + json.dumps([note]), marked, count=1)
        self.assertEqual(n, 1, "fixture premise: the embedded-comments block must be present")
        out, _ = to_portable.to_portable(marked, self.layer)
        self.assertIn('"kept-id"', out, "handled ids must survive the migration")
        embedded = re.search(r'id="embeddedComments"[^>]*>\s*([\s\S]*?)</script>', out)
        self.assertIsNotNone(embedded, "the embedded-comments block must survive")
        self.assertEqual(json.loads(embedded.group(1)), [note],
                         "the embedded reviewer comments must survive byte for byte")

    def test_the_assets_registry_is_dropped_not_inlined(self):
        """It is a SECOND full copy of the CSS and JS, and Portable does not use it.

        `commentable-html.assets.js` defines `window.__COMMENTABLE_ASSETS__` purely so the
        in-page "Export standalone" action can turn a NonPortable document into a Portable one
        without fetch(). Once this tool has done that conversion the registry is dead weight,
        and a natively generated dist/PORTABLE.html does not carry it either - inlining it would
        have added about 937 KB of duplicated payload, roughly doubling the migrated file.
        """
        out, _ = to_portable.to_portable(_read(self.nonportable), self.layer)
        self.assertNotIn('src="commentable-html.assets.js"', out,
                         "the dropped companion must not still be referenced")
        # The decisive signal is SIZE, not a substring: the phrase "__COMMENTABLE_ASSETS__"
        # appears in BOTH a migrated and a native Portable document (the runtime references the
        # global, and quotes it in an error message), so a substring check proves nothing. What
        # inlining the registry would actually do is add its ~937 KB duplicate payload.
        registry_kb = len(self.layer_assets) / 1024.0
        self.assertGreater(registry_kb, 500,
                           "premise: the registry is a large duplicate payload (%.0f KB)"
                           % registry_kb)
        self.assertNotIn(self.layer_assets[:2000], out,
                         "the registry body must not be inlined into the migrated document")

    def test_migration_does_not_bloat_the_document(self):
        # Guards the test above with the number a reader cares about: the migrated file must be
        # in the same league as a natively generated Portable one, not ~937 KB larger.
        before = _read(self.nonportable)
        out, _ = to_portable.to_portable(before, self.layer)
        native = _read(os.path.join(_paths.DIST, "PORTABLE.html"))
        self.assertLess(len(out), len(native) + 300 * 1024,
                        "a migrated document must not be far larger than a native Portable one "
                        "(got %d vs native %d)" % (len(out), len(native)))

    def test_migrating_twice_is_a_no_op(self):
        once, _ = to_portable.to_portable(_read(self.nonportable), self.layer)
        twice, changed = to_portable.to_portable(once, self.layer)
        self.assertFalse(changed, "an already-Portable document must not be rewritten")
        self.assertEqual(twice, once)

    def test_the_migrated_document_validates(self):
        out, _ = to_portable.to_portable(_read(self.nonportable), self.layer)
        errors, _warnings = validate.validate(self.nonportable, html=out)
        self.assertEqual(errors, [])

    def test_the_cli_migrates_in_place_and_is_reported(self):
        code = subprocess.call(
            [sys.executable, os.path.join(_paths.TOOLS, "authoring", "to_portable.py"),
             self.nonportable],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(code, 0)
        self.assertFalse(to_portable.is_nonportable(_read(self.nonportable)))

    def test_the_cli_refuses_a_document_that_is_not_commentable_html(self):
        stray = os.path.join(self.tmp, "stray.html")
        _write(stray, "<html><body>not ours</body></html>\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(_paths.TOOLS, "authoring", "to_portable.py"), stray],
            capture_output=True)
        self.assertNotEqual(proc.returncode, 0, "a foreign file must not be silently rewritten")
        self.assertEqual(_read(stray), "<html><body>not ours</body></html>\n")


class AdversarialContentTests(unittest.TestCase):
    """CMH-PORT-01: authored content that DEMONSTRATES the runtime is never mistaken for it.

    Both cases here were found by review and were real. A document about commentable-html
    legitimately quotes the very markup this tool rewrites, and the naive rewrites did the wrong
    thing: one destructively, one silently.
    """

    def _doc(self, fragment):
        with io.open(os.path.join(_paths.DIST, "NONPORTABLE.html"), "r", encoding="utf-8",
                     newline="") as fh:
            template = fh.read()
        return new_document.make_document(template, fragment, key="adversarial",
                                          label="Adversarial", source="a.html", kind="report")

    def setUp(self):
        self.layer = to_portable.read_layer(_paths.DIST)

    def test_an_authored_script_reference_is_not_mistaken_for_the_real_one(self):
        # DESTRUCTIVE before the fix: the REAL companion script sits AFTER the content region,
        # so a first-occurrence replace spliced the entire ~746 KB runtime into the author's
        # markup and left the real reference dangling - the file stopped being self-contained,
        # failed validation, and (written in place) the original was gone.
        html = self._doc('<h1>Docs</h1>\n<p>Load it with:</p>\n'
                         '<script src="commentable-html.js"></script>\n')
        out, changed = to_portable.to_portable(html, self.layer)
        self.assertTrue(changed)
        begin = out.index("BEGIN: commentable-html - CONTENT")
        end = out.index("END: commentable-html - CONTENT")
        content = out[begin:end]
        self.assertIn('<script src="commentable-html.js"></script>', content,
                      "the authored demonstration must be preserved verbatim")
        self.assertLess(len(content), 100 * 1024,
                        "the runtime must not be spliced into the authored content")
        self.assertNotIn('<script src="commentable-html.js"></script>', out[end:],
                         "the REAL reference must have been inlined, not left dangling")

    def test_an_authored_mode_string_is_not_silently_rewritten(self):
        # SILENT before the fix: a whole-document replace rewrote the author's own text, and the
        # result still validated, so the loss was invisible.
        html = self._doc('<h1>Docs</h1>\n<p>The descriptor reads '
                         '<code>"mode":"nonportable"</code> in legacy files.</p>')
        out, _ = to_portable.to_portable(html, self.layer)
        begin = out.index("BEGIN: commentable-html - CONTENT")
        end = out.index("END: commentable-html - CONTENT")
        self.assertIn('<code>"mode":"nonportable"</code>', out[begin:end],
                      "the author's own text must not be rewritten")
        self.assertIn('"mode":"portable"', out.replace(" ", ""),
                      "the layer descriptor itself must still be switched")


class HostileLayerTests(_Case):
    """CMH-PORT-04: companion bytes can never break out of the element they are inlined into.

    `--dist` accepts any directory, so the companion text is not necessarily the shipped one.
    Inserted verbatim, a CSS companion carrying a case-insensitive `</style>` terminator closed
    the element early and everything after it parsed as markup - which turned control of a
    STYLESHEET into arbitrary script execution against a document holding authored content and
    reviewer comments. The payload is kept (nothing is silently dropped); it is made inert.
    """

    CSS_PAYLOAD = "body{}\n</StYlE><script>window.__cmhPwned=1;</script><style>\n"
    JS_PAYLOAD = ("\n;window.__cmhPwnedJs=1;\n"
                  "</ScRiPt><img src=x onerror=\"window.cmhPwnedAttrMarker=1\">\n")

    def _migrate(self, name, payload):
        layer = dict(self.layer)
        layer[name] = layer[name] + payload
        out, changed = to_portable.to_portable(_read(self.nonportable), layer, self.nonportable)
        self.assertTrue(changed)
        return out

    def _inert(self, out, tag, marker):
        """The marker must sit inside `tag` with no raw-text terminator between them."""
        at = out.index(marker)
        opened = out.rfind("<%s>" % tag, 0, at)
        self.assertNotEqual(opened, -1, "expected the payload inside an inlined <%s>" % tag)
        between = out[opened:at]
        self.assertIsNone(
            re.search(r"</%s(?=[\s/>])" % tag, between, re.IGNORECASE),
            "a raw-text terminator escaped the <%s> element, so the payload is live markup" % tag)

    def test_a_hostile_css_companion_cannot_escape_its_style_element(self):
        out = self._migrate("commentable-html.css", self.CSS_PAYLOAD)
        self.assertIn("window.__cmhPwned=1", out, "the payload must be kept, just neutralized")
        self._inert(out, "style", "window.__cmhPwned=1")

    def test_a_hostile_js_companion_cannot_escape_its_script_element(self):
        out = self._migrate("commentable-html.js", self.JS_PAYLOAD)
        self.assertIn("window.__cmhPwnedJs=1", out)
        self._inert(out, "script", "cmhPwnedAttrMarker")

    def test_the_cli_neutralizes_a_hostile_dist(self):
        dist = os.path.join(self.tmp, "hostile-dist")
        os.mkdir(dist)
        for name in ("commentable-html.css", "commentable-html.js", "commentable-html.assets.js"):
            shutil.copyfile(os.path.join(_paths.DIST, name), os.path.join(dist, name))
        css = os.path.join(dist, "commentable-html.css")
        _write(css, _read(css) + self.CSS_PAYLOAD)
        proc = subprocess.run(
            [sys.executable, os.path.join(_paths.TOOLS, "authoring", "to_portable.py"),
             "--dist", dist, self.nonportable], capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self._inert(_read(self.nonportable), "style", "window.__cmhPwned=1")


class ContentMarkerIntegrityTests(_Case):
    """CMH-PORT-04: only a genuine, unique CONTENT marker pair delimits the authored region.

    The rewrites are anchored on that region, so whoever controls where it appears to start and
    end controls which companion reference is rewritten. Reviewer notes are stored before the
    CONTENT region, so bare marker TEXT in a note used to invert the span and send the whole
    stylesheet into the author's markup while the real reference stayed behind.
    """

    def _with_note(self, html, note):
        marked, n = re.subn(r'(id="embeddedComments"[^>]*>\s*)\[\]',
                            lambda m: m.group(1) + json.dumps([{
                                "id": "c1", "quote": "q", "note": note, "created": "2026-01-01",
                            }]), html, count=1)
        self.assertEqual(n, 1, "fixture premise: the embedded-comments block must be present")
        return marked

    def test_reviewer_text_cannot_redirect_the_css_inlining(self):
        # The note forges the marker TEXT (a reviewer cannot forge a real HTML comment: notes are
        # serialized with '<' escaped), and the authored content legitimately demonstrates the
        # companion link. Before the fix the forged END preceded the genuine BEGIN, the span was
        # discarded, and the LAST match - the author's own link - was replaced with the CSS.
        template = _read(os.path.join(_paths.DIST, "NONPORTABLE.html"))
        html = new_document.make_document(
            template,
            '<h1>Docs</h1>\n<p>Legacy files load it with:</p>\n'
            '<p><code>&lt;link rel="stylesheet" href="commentable-html.css"&gt;</code></p>\n'
            '<link rel="stylesheet" href="commentable-html.css">\n',
            key="forged", label="Forged", source="a.html", kind="report")
        html = self._with_note(html, "BEGIN: commentable-html - CONTENT "
                                     "END: commentable-html - CONTENT -->")
        out, _ = to_portable.to_portable(html, self.layer, "forged.html")
        begin = out.index("BEGIN: commentable-html - CONTENT", out.index("</head>"))
        end = out.index("<!-- END: commentable-html - CONTENT")
        content = out[begin:end]
        self.assertIn('<link rel="stylesheet" href="commentable-html.css">', content,
                      "the authored demonstration must survive verbatim")
        self.assertLess(len(content), 100 * 1024,
                        "the stylesheet must not be inlined into the authored content")
        self.assertNotIn('<link rel="stylesheet" href="commentable-html.css">', out[end:],
                         "the REAL reference must have been inlined")
        self.assertNotIn('<link rel="stylesheet" href="commentable-html.css">', out[:begin],
                         "the head reference must have been inlined, not left behind")

    def test_a_forged_content_marker_comment_is_refused_rather_than_guessed(self):
        # Authored content CAN carry a literal marker comment (unlike a reviewer note). Then the
        # region is genuinely ambiguous, and a tool that writes in place must refuse rather than
        # pick one and corrupt the document.
        template = _read(os.path.join(_paths.DIST, "NONPORTABLE.html"))
        html = new_document.make_document(
            template,
            '<h1>Docs</h1>\n<!-- BEGIN: commentable-html - CONTENT (quoted in a doc) -->\n'
            '<p>Everything between those markers is yours.</p>\n',
            key="ambiguous", label="Ambiguous", source="a.html", kind="report")
        with self.assertRaises(ValueError) as caught:
            to_portable.to_portable(html, self.layer, "ambiguous.html")
        self.assertIn("CONTENT", str(caught.exception))


class DescriptorTests(_Case):
    """CMH-PORT-04: the mode transition is verified in the descriptor, not text-substituted."""

    def _descriptor(self, html):
        m = re.search(r'<script[^>]*id="commentableHtmlLayer"[^>]*>([\s\S]*?)</script>', html)
        self.assertIsNotNone(m, "the layer descriptor must be present")
        return json.loads(m.group(1))

    def test_a_descriptor_whose_json_is_reformatted_is_still_switched(self):
        # Valid JSON the runtime and validator both accept, but not the exact byte sequence a
        # lexical replace looked for. Migration used to report success and leave the mode alone.
        html = _read(self.nonportable)
        spaced = re.sub(r'"mode":"nonportable"', '"mode":\n  "nonportable"', html, count=1)
        self.assertNotEqual(spaced, html, "fixture premise: the descriptor was reformatted")
        out, changed = to_portable.to_portable(spaced, self.layer, self.nonportable)
        self.assertTrue(changed)
        self.assertEqual(self._descriptor(out)["mode"], "portable")

    def test_a_document_without_a_usable_descriptor_is_refused(self):
        html = _read(self.nonportable)
        broken = html.replace('id="commentableHtmlLayer"', 'id="commentableHtmlLayerGone"', 1)
        with self.assertRaises(ValueError) as caught:
            to_portable.to_portable(broken, self.layer, "broken.html")
        self.assertIn("descriptor", str(caught.exception).lower())


class SafeWriteTests(_Case):
    """CMH-PORT-04: a failed write never destroys the document being migrated.

    The destination used to be opened with "w", which truncates before the replacement bytes are
    safely on disk: interrupting a probe mid-write left a 1.4 MB document at zero bytes. The
    document is the user's only copy, so the write is staged and swapped into place instead.
    """

    def test_an_interrupted_write_leaves_the_original_document_intact(self):
        original = _read(self.nonportable)
        real_open = io.open

        def half_open(path, mode="r", *args, **kwargs):
            # Sabotage EVERY write, whichever file the implementation writes: the old code wrote
            # the target itself, the fixed one writes a staged temp file (and opens it by
            # descriptor, not by name), so a path-based condition would silently stop testing.
            fh = real_open(path, mode, *args, **kwargs)
            if "w" in mode:
                return _HalfWriter(fh)
            return fh

        with mock.patch("io.open", half_open):
            try:
                code = to_portable.main(["to_portable.py", self.nonportable])
            except (OSError, IOError):
                code = 1
        self.assertNotEqual(code, 0, "a failed write must be reported, not swallowed")
        self.assertEqual(_read(self.nonportable), original,
                         "the original document must survive a failed write byte for byte")
        leftovers = [n for n in os.listdir(self.tmp) if n.startswith(".cmh-")]
        self.assertEqual(leftovers, [], "a staged write must clean up after itself")


class _HalfWriter(object):
    """A file object that writes half of what it is given and then fails, like a full disk."""

    def __init__(self, fh):
        self._fh = fh

    def write(self, text):
        self._fh.write(text[:len(text) // 2])
        raise IOError("simulated disk-full")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._fh.close()
        return False

    def __getattr__(self, name):
        return getattr(self._fh, name)


class LegacyReferenceShapeTests(_Case):
    """CMH-PORT-01: the companion references real legacy documents carry are all migrated.

    A NonPortable document does NOT necessarily reference `commentable-html.css` by bare name -
    that is only what the test fixtures happen to produce. The CLI's own default was an ABSOLUTE
    `file://` URL to the installed skill dist/, and `--assets-relative`, `--copy-assets` and
    `--assets-href PREFIX` each produce a different prefix. Matching the bare byte sequence would
    refuse exactly the documents this tool exists to rescue.
    """

    def _build(self, name, extra_args):
        out = os.path.join(self.tmp, name)
        code = new_document.main([
            "new_document.py", "--template", os.path.join(_paths.DIST, "NONPORTABLE.html"),
            "--content", "-", "--out", out, "--key", "legacy-%s" % name.split(".")[0],
            "--label", "Legacy", "--source", name, "--kind", "report",
        ] + extra_args)
        self.assertEqual(code, 0)
        return out

    def _migrated(self, path):
        html = _read(path)
        self.assertTrue(to_portable.is_nonportable(html))
        out, changed = to_portable.to_portable(html, self.layer, path)
        self.assertTrue(changed)
        return out

    def setUp(self):
        _Case.setUp(self)
        self._stdin = sys.stdin
        sys.stdin = io.StringIO(FRAGMENT)
        self.addCleanup(lambda: setattr(sys, "stdin", self._stdin))

    def test_absolute_file_url_companion_refs_are_migrated(self):
        # The shape the CLI produced BY DEFAULT for every NonPortable document it ever made.
        out = self._migrated(self._build("absolute.html", []))
        self.assertNotIn("commentable-html.css\"", out)
        self.assertIsNone(re.search(r'<link\b[^>]*commentable-html[^>]*\.css', out, re.IGNORECASE),
                          "no stylesheet companion reference may survive")
        self.assertIsNone(re.search(r'<script\b[^>]*src=[^>]*commentable-html', out, re.IGNORECASE),
                          "no script companion reference may survive")

    def test_prefixed_companion_refs_are_migrated(self):
        sys.stdin = io.StringIO(FRAGMENT)
        out = self._migrated(self._build("prefixed.html", ["--assets-href", "assets/"]))
        self.assertNotIn('href="assets/commentable-html.css"', out)
        self.assertNotIn('src="assets/commentable-html.js"', out)
        self.assertNotIn('src="assets/commentable-html.assets.js"', out)


class LineEndingTests(_Case):
    """CMH-PORT-01: a CRLF document migrates. Windows-authored documents are CRLF throughout."""

    def test_a_crlf_document_migrates_and_keeps_its_line_endings(self):
        crlf = _read(self.nonportable).replace("\r\n", "\n").replace("\n", "\r\n")
        out, changed = to_portable.to_portable(crlf, self.layer, "crlf.html")
        self.assertTrue(changed, "a CRLF document must not be refused")
        self.assertFalse(to_portable.is_nonportable(out))
        begin = out.index("BEGIN: commentable-html - CONTENT", out.index("</head>"))
        end = out.index("<!-- END: commentable-html - CONTENT")
        self.assertIn("\r\n", out[begin:end],
                      "the document's own CRLF endings must survive in the authored region")
        self.assertIsNone(re.search(r"(?<!\r)\n", out[begin:end]),
                          "no authored line may be downgraded to a bare LF")


class AuthoredScaffoldingTests(_Case):
    """CMH-PORT-01: authored content that quotes the legacy scaffolding is not deleted."""

    def test_authored_text_quoting_the_loader_note_is_kept(self):
        note = "<!-- commentable-html - layer loaded from companion files (nonportable mode) -->"
        template = _read(os.path.join(_paths.DIST, "NONPORTABLE.html"))
        html = new_document.make_document(
            template, "<h1>Docs</h1>\n<p>Legacy files carry this note:</p>\n%s\n" % note,
            key="loader-note", label="Note", source="a.html", kind="report")
        out, _ = to_portable.to_portable(html, self.layer, "note.html")
        begin = out.index("BEGIN: commentable-html - CONTENT", out.index("</head>"))
        end = out.index("<!-- END: commentable-html - CONTENT")
        self.assertIn(note, out[begin:end], "the author's own quotation must survive")
        self.assertNotIn(note, out[:begin], "the real loader note must be gone")

    def test_a_companion_cannot_forge_the_bootstrap_anchor(self):
        # The companion bytes are untrusted (--dist takes any directory). If the bootstrap were
        # stripped AFTER they were inlined, this forged BEGIN - which lands in <head> ahead of
        # the real one, and is legal CSS (a CDO token) - would pair with the REAL END and delete
        # the span between them. Anchoring every edit on the document's original bytes is what
        # makes that impossible; revert that and this test corrupts the document.
        forged = "\n<!-- %s -->\nbody{}\n" % _BOOTSTRAP_BEGIN_TEXT
        layer = dict(self.layer)
        layer["commentable-html.css"] = layer["commentable-html.css"] + forged
        out, _ = to_portable.to_portable(_read(self.nonportable), layer, self.nonportable)
        self.assertIn("Authored prose that must survive the migration.", out)
        for region in ("CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"):
            self.assertEqual(
                len(upgrade._region_marker_matches(out, "BEGIN", region)), 1,
                "the %s region marker must survive exactly once" % region)
        errors, _warnings = validate.validate("forged.html", html=out)
        self.assertEqual(errors, [])


class LiveMarkupOnlyTests(_Case):
    """CMH-PORT-04: only LIVE markup is rewritten - commented-out or decoy elements are not.

    The document is a review surface for documents ABOUT this skill, so it legitimately contains
    commented-out and quoted copies of the very elements this tool rewrites. Picking one of those
    leaves the real companion reference behind and reports success on a broken document.
    """

    def test_a_commented_out_companion_reference_is_not_mistaken_for_the_real_one(self):
        html = _read(self.nonportable)
        html = html.replace(
            "</body>", "<!-- <script src=\"commentable-html.js\"></script> -->\n</body>", 1)
        out, _ = to_portable.to_portable(html, self.layer, "commented.html")
        self.assertIn("<!-- <script src=\"commentable-html.js\"></script> -->", out,
                      "the commented-out copy must be left alone")
        live = re.sub(r"<!--.*?-->", "", out, flags=re.DOTALL)
        self.assertNotIn('src="commentable-html.js"', live,
                         "the REAL reference must have been inlined")

    def test_a_commented_out_layer_descriptor_is_not_the_one_that_is_switched(self):
        html = _read(self.nonportable)
        decoy = ('<!-- <script type="application/json" id="commentableHtmlLayer">'
                 '{"version":"0.0.0","mode":"nonportable","regions":[]}</script> -->\n')
        html = html.replace("<head>", "<head>\n" + decoy, 1)
        out, _ = to_portable.to_portable(html, self.layer, "decoy.html")
        live = re.sub(r"<!--.*?-->", "", out, flags=re.DOTALL)
        m = re.search(r'id="commentableHtmlLayer"[^>]*>([\s\S]*?)</script>', live)
        self.assertIsNotNone(m, "the live descriptor must still be present")
        self.assertEqual(json.loads(m.group(1))["mode"], "portable")

    def test_a_data_prefixed_attribute_is_not_a_companion_reference(self):
        html = _read(self.nonportable)
        html = html.replace(
            "</body>",
            '<link rel="preload" data-href="commentable-html.css" href="host.css">\n</body>', 1)
        out, _ = to_portable.to_portable(html, self.layer, "decoy-attr.html")
        self.assertIn('data-href="commentable-html.css" href="host.css"', out,
                      "a data-* attribute must not be read as the companion reference")

    def test_two_live_companion_references_are_refused_rather_than_guessed(self):
        html = _read(self.nonportable)
        html = html.replace(
            "</body>", '<script src="commentable-html.js"></script>\n</body>', 1)
        with self.assertRaises(ValueError) as caught:
            to_portable.to_portable(html, self.layer, "ambiguous.html")
        self.assertIn("commentable-html.js", str(caught.exception))

    def test_a_companion_script_with_a_spaced_end_tag_still_migrates(self):
        # HTML end tags may carry ignored attributes and trailing space, so `</script >` really
        # does close the element. A matcher that only accepted `</script>` would stop seeing the
        # element - and then refuse a document that a browser loads perfectly well.
        html = _read(self.nonportable).replace(
            '<script src="commentable-html.js"></script>',
            '<script src="commentable-html.js"></script >', 1)
        out, changed = to_portable.to_portable(html, self.layer, "spaced.html")
        self.assertTrue(changed)
        live = re.sub(r"<!--.*?-->", "", out, flags=re.DOTALL)
        self.assertNotIn('src="commentable-html.js"', live)

    def test_a_document_without_the_assets_registry_still_migrates(self):
        # The registry is optional - the validator only WARNS when it is absent - so a document
        # that never had one (or already dropped it) must not be refused.
        html = _read(self.nonportable)
        html = re.sub(r'[ \t]*<script[^>]*src="[^"]*commentable-html\.assets\.js"[^>]*>\s*'
                      r'</script>[ \t]*\r?\n?', "", html, count=1)
        self.assertIsNone(re.search(r'<script[^>]*src="[^"]*commentable-html\.assets\.js"', html),
                          "fixture premise: the registry reference was removed")
        out, changed = to_portable.to_portable(html, self.layer, "no-registry.html")
        self.assertTrue(changed)
        self.assertFalse(to_portable.is_nonportable(out))


class BatchCliTests(_Case):
    """CMH-PORT-01: a mixed batch migrates what it can and still reports failure."""

    def _batch(self, extra_args=()):
        already = os.path.join(self.tmp, "already-portable.html")
        shutil.copyfile(os.path.join(_paths.DIST, "PORTABLE.html"), already)
        broken = os.path.join(self.tmp, "not-ours.html")
        _write(broken, "<html><body>not ours</body></html>\n")
        argv = ["to_portable.py"] + list(extra_args) + [self.nonportable, already, broken]
        return already, broken, to_portable.main(argv)

    def test_one_bad_file_does_not_stop_the_others_but_fails_the_run(self):
        before_broken = None
        already, broken, code = self._batch()
        before_broken = "<html><body>not ours</body></html>\n"
        self.assertEqual(code, 1, "a batch with an unusable file must report failure")
        self.assertFalse(to_portable.is_nonportable(_read(self.nonportable)),
                         "the legacy document must still have been migrated")
        self.assertEqual(_read(broken), before_broken, "a foreign file is never rewritten")

    def test_check_mode_writes_nothing(self):
        before = _read(self.nonportable)
        already, broken, code = self._batch(["--check"])
        self.assertEqual(code, 1, "the unusable file still fails the run")
        self.assertEqual(_read(self.nonportable), before, "--check must not write")


class PermanentCompatibilityTests(_Case):
    """CMH-PORT-02: a NonPortable document is still opened, validated, and finalized forever."""

    def test_a_nonportable_document_still_validates(self):
        errors, _warnings = validate.validate(self.nonportable)
        self.assertEqual(errors, [],
                         "NonPortable documents are supported permanently; only CREATING new "
                         "ones goes away")

    def test_the_nonportable_runtime_and_companions_are_still_shipped(self):
        # Existing documents reference these by bare name. Dropping them would break every
        # NonPortable document in the world on the next auto-update.
        for name in ("NONPORTABLE.html", "commentable-html.css", "commentable-html.js",
                     "commentable-html.assets.js"):
            self.assertTrue(os.path.exists(os.path.join(_paths.DIST, name)),
                            "%s must remain in dist/ for existing NonPortable documents" % name)

    def test_finalize_still_works_on_a_nonportable_document(self):
        import finalize
        result = finalize.finalize(self.nonportable)
        self.assertEqual(result["errors"], [])
        self.assertTrue(to_portable.is_nonportable(_read(self.nonportable)),
                        "finalize must not silently convert a NonPortable document")


if __name__ == "__main__":
    unittest.main()
