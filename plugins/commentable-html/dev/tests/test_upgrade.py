#!/usr/bin/env python3
"""Regression tests for tools/upgrade.py (the layer-region upgrade tool).

Standard library only. The real dist/PORTABLE.html is used as both the template and the
basis for a "deployed" file whose regions are then mutated, so the tests exercise the
actual region model rather than a synthetic fixture.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import upgrade  # noqa: E402

TEMPLATE = os.path.join(ROOT, "dist", "PORTABLE.html")


def _tpl():
    with open(TEMPLATE, "r", encoding="utf-8") as fh:
        return fh.read()


def _mutate_region_inner(text, name, injector):
    """Return text with `injector` inserted at the start of a region's inner content."""
    b, e = upgrade._region_inner(text, name, "<test>")
    return text[:b] + injector + text[b:e] + text[e:]


class UpgradeUnitTests(unittest.TestCase):
    def test_up_to_date_is_a_noop(self):
        tpl = _tpl()
        out, changed = upgrade.upgrade(tpl, tpl)
        self.assertEqual(changed, [])
        self.assertEqual(out, tpl)

    def test_missing_kind_meta_is_added_on_upgrade(self):
        # A pre-kind document (predates the mandatory document-kind meta) is migrated:
        # upgrade adds a default generic kind so it declares one and passes validation.
        tpl = _tpl()
        marker = '<meta name="commentable-html-kind" content="generic" />'
        self.assertIn(marker, tpl)
        legacy = tpl.replace(marker, "", 1)
        self.assertNotIn("commentable-html-kind", legacy)
        out, changed = upgrade.upgrade(legacy, tpl)
        self.assertIn("kind meta", changed)
        self.assertIn(marker, out)

    def test_reordered_kind_meta_is_not_duplicated_on_upgrade(self):
        # #81 hardening: an existing kind meta whose attributes are in a non-canonical order
        # (content before name) must still be detected, so upgrade does NOT append a second
        # (generic) kind meta. Two kind metas would leave the document with the wrong
        # effective kind (the inserted generic one wins as it lands higher in <head>).
        tpl = _tpl()
        canonical = '<meta name="commentable-html-kind" content="generic" />'
        self.assertIn(canonical, tpl)
        reordered = '<meta content="report" name="commentable-html-kind" />'
        legacy = tpl.replace(canonical, reordered, 1)
        out, changed = upgrade.upgrade(legacy, tpl)
        self.assertNotIn("kind meta", changed)
        self.assertEqual(out.count("commentable-html-kind"), 1,
                         "upgrade duplicated the kind meta: %d present" % out.count("commentable-html-kind"))
        self.assertIn(reordered, out)
        self.assertNotIn(canonical, out)

    def test_stale_css_region_is_restored_only(self):
        tpl = _tpl()
        target = _mutate_region_inner(tpl, "CSS", "\n/* STALE-SENTINEL */\n")
        out, changed = upgrade.upgrade(target, tpl)
        self.assertEqual(changed, ["CSS"])
        self.assertNotIn("STALE-SENTINEL", out)  # stale CSS replaced
        # the CSS region inner now equals the template's
        tb, te = upgrade._region_inner(tpl, "CSS", "t")
        ob, oe = upgrade._region_inner(out, "CSS", "o")
        self.assertEqual(out[ob:oe], tpl[tb:te])

    def test_state_regions_are_preserved(self):
        tpl = _tpl()
        # put document-owned state into HANDLED IDS and EMBEDDED COMMENTS, and make the
        # JS region stale so an upgrade actually runs.
        target = _mutate_region_inner(tpl, "HANDLED IDS", "\nKEEP-HANDLED-SENTINEL\n")
        target = _mutate_region_inner(target, "EMBEDDED COMMENTS", "\nKEEP-EMBEDDED-SENTINEL\n")
        target = _mutate_region_inner(target, "JS", "\n/* STALE-JS */\n")
        out, changed = upgrade.upgrade(target, tpl)
        self.assertEqual(changed, ["JS"])
        self.assertIn("KEEP-HANDLED-SENTINEL", out)   # state untouched
        self.assertIn("KEEP-EMBEDDED-SENTINEL", out)
        self.assertNotIn("STALE-JS", out)             # JS region refreshed

    def test_js_region_end_ignores_inline_marker_mentions(self):
        text = ("<!--\n"
                "     BEGIN: commentable-html - JS\n"
                "-->\n"
                "   var note = 'see END: commentable-html - JS in a string';\n"
                "   out += \"<!-- END: commentable-html - JS -->\\n\";\n"
                "<!-- END: commentable-html - JS -->\n"
                "trailing\n")
        b, e = upgrade._region_inner(text, "JS", "<t>")
        inner = text[b:e]
        # the inline mentions live inside the region (not treated as boundaries)
        self.assertIn("see END: commentable-html - JS in a string", inner)
        self.assertIn("out +=", inner)
        # the region ends at the real trailing marker line, not an inline mention
        self.assertEqual(e, text.rindex("<!-- END: commentable-html - JS -->") + len("<!-- "))
        self.assertNotIn("trailing", inner)

    def test_region_marker_must_be_comment_delimited(self):
        text = ("prefix x BEGIN: commentable-html - JS not-a-marker\n"
                "<pre>\nBEGIN: commentable-html - JS\n</pre>\n"
                "<!--\n"
                "     BEGIN: commentable-html - JS\n"
                "-->\n"
                "body\n"
                "<!-- END: commentable-html - JS -->\n")
        b, e = upgrade._region_inner(text, "JS", "<t>")
        inner = text[b:e]
        self.assertIn("body", inner)
        self.assertNotIn("not-a-marker", inner)
        self.assertNotIn("<pre>", inner)

    def test_region_marker_rejects_trailing_authored_text(self):
        text = ("     BEGIN: commentable-html - JS as discussed in this authored note\n"
                "poison-before\n"
                "<!--\n"
                "     BEGIN: commentable-html - JS\n"
                "-->\n"
                "body\n"
                "<!-- END: commentable-html - JS -->\n")
        b, e = upgrade._region_inner(text, "JS", "<t>")
        inner = text[b:e]
        self.assertIn("body", inner)
        self.assertNotIn("poison-before", inner)
        self.assertNotIn("authored note", inner)

    def test_nonportable_document_is_refused(self):
        tpl = _tpl()
        econ = tpl.replace("<head>",
                           "<head>\n<!-- BEGIN: commentable-html - NONPORTABLE BOOTSTRAP -->", 1)
        with self.assertRaises(ValueError) as cm:
            upgrade.upgrade(econ, tpl)
        self.assertIn("nonportable", str(cm.exception).lower())

    def test_non_commentable_file_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            upgrade.upgrade("<html><body>just a page</body></html>", _tpl())
        self.assertIn("not a commentable-html document", str(cm.exception))

    def test_missing_begin_marker_raises(self):
        with self.assertRaises(ValueError):
            upgrade._region_inner("no markers here", "CSS", "<t>")

    def test_duplicate_begin_marker_raises(self):
        text = ("<!-- BEGIN: commentable-html - CSS -->\n"
                "body\n"
                "<!-- BEGIN: commentable-html - CSS -->\n"
                "more\n"
                "<!-- END: commentable-html - CSS -->\n")
        with self.assertRaisesRegex(ValueError, "duplicate region"):
            upgrade._region_inner(text, "CSS", "<t>")

    def test_duplicate_end_marker_raises(self):
        text = ("<!-- BEGIN: commentable-html - JS -->\n"
                "body\n"
                "<!-- END: commentable-html - JS -->\n"
                "<!-- END: commentable-html - JS -->\n")
        with self.assertRaisesRegex(ValueError, "duplicate region"):
            upgrade._region_inner(text, "JS", "<t>")

    def test_upgrade_rejects_duplicate_state_region_end(self):
        tpl = _tpl()
        target = tpl.replace(
            "<!-- END: commentable-html - HANDLED IDS -->",
            "<!-- END: commentable-html - HANDLED IDS -->\n<!-- END: commentable-html - HANDLED IDS -->",
            1)
        with self.assertRaisesRegex(ValueError, "duplicate region: HANDLED IDS"):
            upgrade.upgrade(target, tpl)


class UpgradeCliTests(unittest.TestCase):
    def _write(self, text):
        fd, p = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        self.addCleanup(lambda: os.path.exists(p) and os.remove(p))
        return p

    def test_cli_check_reports_stale_and_exits_1(self):
        target = _mutate_region_inner(_tpl(), "CSS", "\n/* STALE */\n")
        p = self._write(target)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = upgrade.main(["upgrade.py", p, "--check"])
        self.assertEqual(rc, 1)
        self.assertIn("STALE", out.getvalue())

    def test_cli_check_reports_up_to_date_and_exits_0(self):
        p = self._write(_tpl())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = upgrade.main(["upgrade.py", p, "--check"])
        self.assertEqual(rc, 0)
        self.assertIn("up to date", out.getvalue())

    def test_cli_upgrades_in_place_and_validates(self):
        target = _mutate_region_inner(_tpl(), "CSS", "\n/* STALE */\n")
        p = self._write(target)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = upgrade.main(["upgrade.py", p])
        self.assertEqual(rc, 0)
        with open(p, encoding="utf-8") as fh:
            result = fh.read()
        self.assertNotIn("STALE", result)  # region refreshed and file re-validated clean

    def test_cli_missing_file_returns_2(self):
        rc = upgrade.main(["upgrade.py", os.path.join(tempfile.gettempdir(), "cmh-no-such-file.html")])
        self.assertEqual(rc, 2)

    def test_cli_noop_when_already_up_to_date(self):
        p = self._write(_tpl())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = upgrade.main(["upgrade.py", p])
        self.assertEqual(rc, 0)
        self.assertIn("already up to date", out.getvalue())

    def test_validation_failure_leaves_target_unchanged(self):
        target = _mutate_region_inner(_tpl(), "CSS", "\n/* STALE */\n")
        p = self._write(target)
        with open(p, "rb") as fh:
            original_bytes = fh.read()

        mock_validate = mock.MagicMock()
        mock_validate.validate.return_value = (["some error"], [])

        err = io.StringIO()
        with mock.patch.dict(sys.modules, {"validate": mock_validate}), \
             contextlib.redirect_stderr(err):
            rc = upgrade.main(["upgrade.py", p])

        self.assertEqual(rc, 1)
        self.assertIn("validation", err.getvalue().lower())
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), original_bytes)
        parent = os.path.dirname(os.path.abspath(p))
        leftovers = sorted(f for f in os.listdir(parent) if f.startswith(".cmh-upgrade-"))
        self.assertEqual(leftovers, [])

    def test_validator_crash_is_surfaced_not_swallowed(self):
        target = _mutate_region_inner(_tpl(), "CSS", "\n/* STALE */\n")
        p = self._write(target)
        with open(p, "rb") as fh:
            original_bytes = fh.read()

        mock_validate = mock.MagicMock()
        mock_validate.validate.side_effect = RuntimeError("boom")

        err = io.StringIO()
        with mock.patch.dict(sys.modules, {"validate": mock_validate}), \
             contextlib.redirect_stderr(err):
            rc = upgrade.main(["upgrade.py", p])

        self.assertEqual(rc, 1)
        err_text = err.getvalue().lower()
        self.assertTrue(
            "aborted" in err_text or "crashed" in err_text or "boom" in err_text,
            "Expected crash indication in stderr, got: %r" % err_text,
        )
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), original_bytes)
        parent = os.path.dirname(os.path.abspath(p))
        leftovers = sorted(f for f in os.listdir(parent) if f.startswith(".cmh-upgrade-"))
        self.assertEqual(leftovers, [])

    def test_out_flag_does_not_clobber_source_on_validation_fail(self):
        target = _mutate_region_inner(_tpl(), "CSS", "\n/* STALE */\n")
        src = self._write(target)
        fd, dst = tempfile.mkstemp(suffix=".out.html")
        os.close(fd)
        os.remove(dst)  # start absent; must remain absent on failure
        self.addCleanup(lambda p=dst: os.path.exists(p) and os.remove(p))
        with open(src, "rb") as fh:
            src_original = fh.read()

        mock_validate = mock.MagicMock()
        mock_validate.validate.return_value = (["some error"], [])

        with mock.patch.dict(sys.modules, {"validate": mock_validate}):
            rc = upgrade.main(["upgrade.py", src, "--out", dst])

        self.assertEqual(rc, 1)
        with open(src, "rb") as fh:
            self.assertEqual(fh.read(), src_original)
        self.assertFalse(os.path.exists(dst))

    def test_cli_out_writes_elsewhere_and_leaves_input(self):
        target = _mutate_region_inner(_tpl(), "CSS", "\n/* STALE */\n")
        src = self._write(target)
        dst = self._write("placeholder")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = upgrade.main(["upgrade.py", src, "--out", dst])
        self.assertEqual(rc, 0)
        with open(src, encoding="utf-8") as fh:
            self.assertIn("STALE", fh.read())  # input untouched
        with open(dst, encoding="utf-8") as fh:
            self.assertNotIn("STALE", fh.read())  # fresh copy written to --out


if __name__ == "__main__":
    unittest.main(verbosity=2)
