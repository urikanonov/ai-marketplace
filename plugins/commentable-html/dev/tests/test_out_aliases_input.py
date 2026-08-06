#!/usr/bin/env python3
"""CMH-TOOL-23: a tool never lands its output on a file it READ as a different artifact.

Several tools read one file and write something else entirely: `content_extract` reads a
document and writes its CONTENT fragment, `pptx_to_fragment` reads extracted slides and writes
a deck fragment, `checklist_scaffold` reads an outline and writes markup, and
`deck_scaffold --force` / `new_document --force` read a content fragment (plus a template and a
brand profile) and write a whole document over an existing `--out`. Nothing compared the two
paths, so `--out <the input>` replaced the user's file with the derived artifact and exited 0.
The shared crash-safe writer (CMH-TOOL-22) makes that replacement clean and complete, which is
exactly what makes it unrecoverable.

The hazard is per INPUT, not per tool: a tool that legitimately rewrites its document IN PLACE
can still read a SECOND file its destination must not land on - `upgrade --template`,
`retrofit --brand`, `deck_theme --theme`, `content_replace --content`. And a destination is not
always spelled `--out`: `content_replace` rewrites a positional document, and
`new_document --copy-assets` writes companions on fixed names beside the output.

The comparison must be CANONICAL, not textual: a destination pointing at a symlink to the input
is the worst case, because `atomic_write` follows the link to its target and lands on the real
document, and an alternate spelling of the same path (`sub/../doc.html`, a different case on a
case-insensitive filesystem) hides the aliasing just as well.

Three layers:

- A behavioral case per (tool, input), run through every spelling of the input path, asserting
  the run FAILS with the REFUSAL (not merely with some other error), names both paths, and
  leaves the input byte for byte.
- No-false-positive cases: a distinct destination is never refused, an in-place transform may
  still write its `--out` over its own input, and `new_document` without `--force` still
  redirects to a suffixed sibling instead of refusing.
- A static guard, so a NEW tool with an `--out` cannot quietly skip the check, plus a test of
  the guard's own detection surface (what it must catch AND what it must not).
"""
import ast
import io
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: E402  shared pkg/dev split path constants

sys.path.insert(0, _paths.TOOLS)
import _atomic_io  # noqa: E402
import _deck_theme  # noqa: E402
import checklist_scaffold  # noqa: E402
import content_extract  # noqa: E402
import content_replace  # noqa: E402
import deck_scaffold  # noqa: E402
import deck_theme  # noqa: E402
import new_document  # noqa: E402
import normalize_typography  # noqa: E402
import pptx_to_fragment  # noqa: E402
import retrofit  # noqa: E402
import upgrade  # noqa: E402

EM_DASH = "\u2014"

# The one phrase every refusal carries. Asserting it is what stops a case passing vacuously on
# some unrelated non-zero exit that happens to mention the same path.
REFUSAL = "refusing to write over the tool's own input"

NONSHAREABLE_TEMPLATE = os.path.join(_paths.DIST, "NONSHAREABLE.html")

# A document from an OLDER release, so an `upgrade` run over it reaches its write instead of
# short-circuiting on "already up to date".
STALE_DOC = os.path.join(_paths.DEV, "upgrade-corpus", "v1.117.0.html")

CONTENT_DOC = (
    "<!doctype html>\n<html><head></head><body>\n"
    '<main id="commentRoot" data-comment-key="k" data-cmh-content-root>\n'
    "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->\n"
    "<p>the content region</p>\n"
    "<!-- END: commentable-html - CONTENT -->\n"
    "</main>\n</body></html>\n")

BRAND = ('{"tokens": {"--cp-bg": "#101820", "--cp-text": "#f7f7f7", '
         '"--cp-accent": "rgb(20, 120, 220)"}}\n')
# A real preset, so a run with the refusal removed genuinely gets as far as the write and
# destroys the profile - the fixture must not fail for its own reasons instead.
THEME_PRESET = os.path.join(_paths.DECK, "themes", "editorial.theme.json")


def _write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _scaffold_deck(directory, key):
    """A real scaffolded deck at <directory>/deck.html, for a fixture that must be re-themable."""
    deck = os.path.join(directory, "deck.html")
    code = deck_scaffold.main(["--slides", "1", "--out", deck, "--force",
                               "--label", "Deck", "--key", key])
    if code != 0:
        raise RuntimeError("deck_scaffold setup failed with exit %r" % code)
    return deck


def _content_extract_case(directory):
    src = os.path.join(directory, "source.html")
    _write(src, CONTENT_DOC)
    return src, lambda out: [src, "--out", out]


def _checklist_scaffold_case(directory):
    outline = os.path.join(directory, "outline.txt")
    _write(outline, "Backend\n\tMigrations\nDocs\n")
    return outline, lambda out: ["checklist_scaffold.py", "--in", outline,
                                 "--id", "release", "--out", out]


def _pptx_to_fragment_case(directory):
    slides = os.path.join(directory, "slides.json")
    _write(slides, '[{"title": "One", "bullets": ["a", "b"]}]\n')
    return slides, lambda out: ["--input", slides, "--out", out]


def _pptx_to_fragment_pptx_case(directory):
    # The --pptx branch shells out to the vendored extractor, but the alias check runs first, so
    # this pins that the second input of the mutually-exclusive pair is guarded too.
    pptx = os.path.join(directory, "deck.pptx")
    _write(pptx, "not a real pptx, but a real file the run names as its input\n")
    return pptx, lambda out: ["--pptx", pptx, "--out", out]


def _deck_scaffold_content_case(directory):
    content = os.path.join(directory, "slides.html")
    _write(content, '<section class="slide"><h2>One</h2><p>Body text.</p></section>\n')
    return content, lambda out: ["--content", content, "--out", out, "--force",
                                 "--label", "Deck", "--key", "alias-deck"]


def _deck_scaffold_brand_case(directory):
    brand = os.path.join(directory, "brand.json")
    _write(brand, BRAND)
    return brand, lambda out: ["--slides", "1", "--brand", brand, "--out", out, "--force",
                               "--label", "Deck", "--key", "alias-deck"]


def _deck_scaffold_theme_case(directory):
    theme = os.path.join(directory, "midnight.theme.json")
    shutil.copyfile(THEME_PRESET, theme)
    return theme, lambda out: ["--slides", "1", "--theme", theme, "--out", out, "--force",
                               "--label", "Deck", "--key", "alias-deck"]


def _new_document_argv(content, out, extra=()):
    return (["new_document.py", "--content", content, "--out", out, "--force",
             "--key", "alias-doc", "--label", "Doc", "--kind", "report",
             "--allow-unvalidated-output"] + list(extra))


def _new_document_content_case(directory):
    content = os.path.join(directory, "content.html")
    _write(content, "<h1>Title</h1>\n<p>Body text.</p>\n")
    return content, lambda out: _new_document_argv(content, out)


def _new_document_template_case(directory):
    # A copy of the real template, because the point is that the skill's own
    # dist/SHAREABLE.html must not be replaceable by a document built FROM it.
    template = os.path.join(directory, "TEMPLATE.html")
    shutil.copyfile(_paths.TEMPLATE, template)
    content = os.path.join(directory, "content.html")
    _write(content, "<h1>Title</h1>\n<p>Body text.</p>\n")
    return template, lambda out: _new_document_argv(content, out, ["--template", template])


def _new_document_brand_case(directory):
    brand = os.path.join(directory, "brand.json")
    _write(brand, BRAND)
    content = os.path.join(directory, "content.html")
    _write(content, "<h1>Title</h1>\n<p>Body text.</p>\n")
    return brand, lambda out: _new_document_argv(content, out, ["--brand", brand])


def _upgrade_template_case(directory):
    # upgrade rewrites the document in place (the SAME artifact), but its --template is a
    # different one: a destination resolving to it would replace the skill's template. The
    # document is a STALE corpus snapshot, so the run genuinely reaches its write rather than
    # short-circuiting on "already up to date".
    template = os.path.join(directory, "TEMPLATE.html")
    shutil.copyfile(_paths.TEMPLATE, template)
    doc = os.path.join(directory, "doc.html")
    shutil.copyfile(STALE_DOC, doc)
    return template, lambda out: ["upgrade.py", doc, "--template", template, "--out", out]


def _retrofit_brand_case(directory):
    brand = os.path.join(directory, "brand.json")
    _write(brand, BRAND)
    page = os.path.join(directory, "page.html")
    _write(page, "<!doctype html>\n<html><head></head><body><h1>Hi</h1></body></html>\n")
    return brand, lambda out: ["retrofit.py", page, "--label", "Page", "--kind", "report",
                               "--key", "alias-retrofit", "--brand", brand, "--out", out]


def _deck_theme_case(directory):
    theme = os.path.join(directory, "midnight.theme.json")
    shutil.copyfile(THEME_PRESET, theme)
    # A REAL scaffolded deck, so a run with the refusal removed re-themes it successfully and
    # lands the deck on the theme profile: the fixture proves the loss, not a setup error.
    deck = _scaffold_deck(directory, "alias-deck-theme")
    return theme, lambda out: ["apply", deck, "--theme", theme, "--out", out]


def _deck_theme_preset_case(directory):
    # A bare preset NAME resolves into the shipped themes/ directory, so the file the run reads
    # is not the string the caller typed. Kept OUT of CASES because its input lives in the
    # install rather than the temp dir; `_installed_input_cases` drives it instead.
    deck = _scaffold_deck(directory, "alias-deck-preset")
    preset = os.path.join(_paths.DECK, "themes", "editorial.theme.json")
    return preset, lambda out: ["apply", deck, "--theme", "editorial", "--out", out]


def _content_replace_bundle_case(directory):
    # The other input of the positional-destination tool: a Copy-all bundle is not a document.
    doc = os.path.join(directory, "doc.html")
    _write(doc, CONTENT_DOC)
    fragment = os.path.join(directory, "fragment.html")
    _write(fragment, "<p>a replacement fragment</p>\n")
    return doc, lambda out: [out, "--content", fragment, "--handled-from-bundle", doc]


def _content_replace_case(directory):
    # The destination is the POSITIONAL document, so the aliasing input is --content.
    doc = os.path.join(directory, "doc.html")
    _write(doc, CONTENT_DOC)
    return doc, lambda out: [out, "--content", doc]


# (case name, setup(directory) -> (aliased input path, argv-for-a-destination), run(argv))
CASES = (
    ("content_extract/file", _content_extract_case, content_extract.main),
    ("checklist_scaffold/--in", _checklist_scaffold_case, checklist_scaffold.main),
    ("pptx_to_fragment/--input", _pptx_to_fragment_case, pptx_to_fragment.main),
    ("pptx_to_fragment/--pptx", _pptx_to_fragment_pptx_case, pptx_to_fragment.main),
    ("deck_scaffold/--content", _deck_scaffold_content_case, deck_scaffold.main),
    ("deck_scaffold/--brand", _deck_scaffold_brand_case, deck_scaffold.main),
    ("deck_scaffold/--theme", _deck_scaffold_theme_case, deck_scaffold.main),
    ("new_document/--content", _new_document_content_case, new_document.main),
    ("new_document/--template", _new_document_template_case, new_document.main),
    ("new_document/--brand", _new_document_brand_case, new_document.main),
    ("upgrade/--template", _upgrade_template_case, upgrade.main),
    ("retrofit/--brand", _retrofit_brand_case, retrofit.main),
    ("deck_theme/--theme", _deck_theme_case, deck_theme.main),
    ("content_replace/--content", _content_replace_case, content_replace.main),
    ("content_replace/--handled-from-bundle", _content_replace_bundle_case,
     content_replace.main),
)

# Every shipped tool that takes an `--out` and needs no refusal call, keyed by its path under
# tools/ (never by basename - two buckets can hold the same filename) with the reason.
OUT_WITHOUT_ALIAS_RISK = {
    "authoring/fix_skip.py": "in place: the document it rewrites is its only file input",
    "authoring/normalize_typography.py": "in place: the document is its only file input",
    "authoring/wrap_sections.py": "in place: the fragment it rewrites is its only file input",
    "deck/deck_fix_fonts.py": "in place: the deck it rewrites is its only file input",
    "notes/notes_scaffold.py": "no file input: the seed text comes from --text or stdin",
    "authoring/inline_images.py": (
        "the images it reads are discovered from the document, not named on the command line, "
        "and their bytes survive base64-encoded inside the document it writes"),
}


def _capture_stderr(run, argv):
    """Run a tool's `main`, returning (exit code, stderr).

    A tool that fails for its OWN reasons may `raise SystemExit` rather than return, so that is
    turned back into a code: these cases care about whether the REFUSAL fired, not about how a
    minimal fixture happens to fail afterwards."""
    err = io.StringIO()
    stderr, sys.stderr = sys.stderr, err
    try:
        code = run(argv)
    except SystemExit as exc:
        code = exc.code if exc.code is not None else 0
    finally:
        sys.stderr = stderr
    return code, err.getvalue()


class OutAliasesInputTests(unittest.TestCase):
    """A destination that resolves to a file the tool READ is refused, not written."""

    def _tmpdir(self):
        directory = tempfile.mkdtemp(prefix="cmh-out-alias-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return directory

    def _spellings(self, directory, path):
        """Every way a caller could NAME `path`: itself, an alternate spelling of the same
        path, and a symlink to it (where the platform allows one)."""
        yield "exact", path
        sub = os.path.join(directory, "sub")
        if not os.path.isdir(sub):
            os.mkdir(sub)
        yield "alternate spelling", os.path.join(sub, os.pardir, os.path.basename(path))
        link = os.path.join(directory, "link-" + os.path.basename(path))
        try:
            os.symlink(path, link)
        except (OSError, NotImplementedError, AttributeError):
            return  # Windows without the developer-mode symlink privilege
        yield "symlink", link

    def test_a_destination_that_resolves_to_an_input_is_refused(self):
        for name, setup, run in CASES:
            directory = self._tmpdir()
            src, argv_for = setup(directory)
            original = _read(src)
            for spelling, out in self._spellings(directory, src):
                with self.subTest(case=name, spelling=spelling):
                    code, message = _capture_stderr(run, argv_for(out))
                    self.assertNotEqual(code, 0,
                                        "%s (%s) wrote its output over its own input"
                                        % (name, spelling))
                    # Not merely "it failed": it failed with THIS refusal. Without this the
                    # case would pass on any unrelated early error that names the path.
                    self.assertIn(REFUSAL, message,
                                  "%s (%s) failed for some other reason: %s"
                                  % (name, spelling, message))
                    self.assertEqual(_read(src), original,
                                     "%s (%s) replaced its input" % (name, spelling))
                    self.assertIn(out, message,
                                  "%s (%s) did not name the destination" % (name, spelling))
                    self.assertIn(src, message,
                                  "%s (%s) did not name the input path" % (name, spelling))

    def test_a_distinct_destination_is_never_refused(self):
        # The guard must not cost the ordinary run. A minimal fixture may still fail for its
        # own reasons, so this asserts the precise thing that must not happen: the REFUSAL.
        for name, setup, run in CASES:
            directory = self._tmpdir()
            _src, argv_for = setup(directory)
            out = os.path.join(directory, "distinct-output.html")
            with self.subTest(case=name):
                _code, message = _capture_stderr(run, argv_for(out))
                self.assertNotIn(REFUSAL, message,
                                 "%s refused a destination that is a different file" % name)

    def test_a_distinct_out_still_produces_the_artifact(self):
        directory = self._tmpdir()
        _src, argv_for = _content_extract_case(directory)
        out = os.path.join(directory, "fragment.html")
        self.assertEqual(content_extract.main(argv_for(out)), 0)
        self.assertIn("the content region", _read(out))

    def test_an_in_place_tool_may_still_write_its_out_over_its_own_input(self):
        # normalize_typography --out <input> writes the SAME artifact back, so it must be
        # untouched by the refusal: the guard is about a DIFFERENT artifact landing on an input.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        _write(path, "<html><body><p>alpha%sbeta</p></body></html>\n" % EM_DASH)
        code, message = _capture_stderr(
            normalize_typography.main, ["normalize_typography.py", path, "--out", path])
        self.assertEqual(code, 0, message)
        self.assertEqual(_read(path), "<html><body><p>alpha - beta</p></body></html>\n")

    def test_new_document_without_force_still_writes_a_suffixed_sibling(self):
        # Without --force the tool has ALREADY redirected an existing --out to a fresh sibling,
        # so nothing can be lost and refusing would be a false alarm. The check therefore runs
        # against the RESOLVED target, not the path the caller typed.
        directory = self._tmpdir()
        content = os.path.join(directory, "content.html")
        _write(content, "<h1>Title</h1>\n<p>Body text.</p>\n")
        original = _read(content)
        code, message = _capture_stderr(new_document.main, [
            "new_document.py", "--content", content, "--out", content,
            "--key", "alias-sibling", "--label", "Doc", "--kind", "report",
            "--allow-unvalidated-output"])
        self.assertEqual(code, 0, message)
        self.assertNotIn(REFUSAL, message)
        self.assertEqual(_read(content), original, "the content fragment was replaced")
        siblings = sorted(n for n in os.listdir(directory) if n != "content.html")
        self.assertTrue(siblings, "no sibling document was written")

    def _fake_install(self):
        """Copies of the resources the tools read off their own install, in a temp directory.

        The destinations below are the files under test, and a REGRESSION here is precisely a
        tool writing to one of them - so pointing the tools at copies keeps a broken guard from
        overwriting the checkout (and keeps the fixtures writable, per the testing guidelines).
        """
        directory = tempfile.mkdtemp(prefix="cmh-fake-install-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        themes = os.path.join(directory, "themes")
        os.mkdir(themes)
        install = {
            "template": os.path.join(directory, "SHAREABLE.html"),
            "nonshareable": os.path.join(directory, "NONSHAREABLE.html"),
            "viewport": os.path.join(directory, "viewport-base.css"),
            "preset": os.path.join(themes, "editorial.theme.json"),
            "themes": themes,
            "dir": directory,
        }
        shutil.copyfile(_paths.TEMPLATE, install["template"])
        shutil.copyfile(NONSHAREABLE_TEMPLATE, install["nonshareable"])
        shutil.copyfile(os.fspath(deck_scaffold.VIEWPORT_CSS), install["viewport"])
        shutil.copyfile(THEME_PRESET, install["preset"])
        for target, attr, value in (
                (deck_scaffold, "TEMPLATE", pathlib.Path(install["template"])),
                (deck_scaffold, "VIEWPORT_CSS", pathlib.Path(install["viewport"])),
                (_deck_theme, "THEMES_DIR", pathlib.Path(themes)),
                (upgrade, "DEFAULT_TEMPLATE", install["template"]),
                (new_document, "_default_template",
                 lambda nonshareable=False, _i=install: (
                     _i["nonshareable"] if nonshareable else _i["template"])),
        ):
            patch = mock.patch.object(target, attr, value)
            patch.start()
            self.addCleanup(patch.stop)
        return install

    def test_a_destination_that_aliases_a_file_read_off_the_install_is_refused(self):
        # Some inputs are not named on the command line at all: deck_scaffold always reads the
        # shipped SHAREABLE.html and viewport-base.css, a bare --theme preset name resolves into
        # the shipped themes/ directory, and upgrade's --template defaults to the same template.
        # The tools are pointed at COPIES of those (see _fake_install), so a regression cannot
        # damage the checkout; the exact installed path is used, never the temp-dir spelling
        # matrix, which would build a path that is not the installed file.
        install = self._fake_install()
        stale = self._tmpdir()
        stale_doc = os.path.join(stale, "doc.html")
        shutil.copyfile(STALE_DOC, stale_doc)
        deck_dir = self._tmpdir()
        deck = _scaffold_deck(deck_dir, "alias-install-deck")
        page_dir = self._tmpdir()
        page = os.path.join(page_dir, "page.html")
        _write(page, "<!doctype html>\n<html><head></head><body><h1>Hi</h1></body></html>\n")
        for label, run, argv_for, installed in (
                ("deck_scaffold/dist template", deck_scaffold.main, lambda out: [
                    "--slides", "1", "--out", out, "--force", "--label", "Deck",
                    "--key", "alias-install"], install["template"]),
                ("deck_scaffold/viewport css", deck_scaffold.main, lambda out: [
                    "--slides", "1", "--out", out, "--force", "--label", "Deck",
                    "--key", "alias-install"], install["viewport"]),
                ("deck_scaffold/preset name", deck_scaffold.main, lambda out: [
                    "--slides", "1", "--theme", "editorial", "--out", out, "--force",
                    "--label", "Deck", "--key", "alias-install"], install["preset"]),
                ("deck_theme/preset name", deck_theme.main, lambda out: [
                    "apply", deck, "--theme", "editorial", "--out", out], install["preset"]),
                ("upgrade/default template", upgrade.main, lambda out: [
                    "upgrade.py", stale_doc, "--out", out], install["template"]),
                ("retrofit/shareable template", retrofit.main, lambda out: [
                    "retrofit.py", page, "--label", "Page", "--kind", "report",
                    "--key", "alias-tpl", "--out", out], install["template"]),
                # Shareable mode reads the NonShareable template too, only for its theme
                # variables - the input a per-mode single-template list would miss.
                ("retrofit/nonshareable theme template", retrofit.main, lambda out: [
                    "retrofit.py", page, "--label", "Page", "--kind", "report",
                    "--key", "alias-tpl", "--out", out], install["nonshareable"]),
        ):
            with self.subTest(case=label):
                before = _read(installed)
                code, message = _capture_stderr(run, argv_for(installed))
                self.assertNotEqual(code, 0, "%s wrote over an installed input" % label)
                self.assertIn(REFUSAL, message, "%s: %s" % (label, message))
                self.assertIn(installed, message)
                self.assertEqual(_read(installed), before)

    def test_a_read_only_mode_is_never_refused(self):
        # --check writes nothing, so refusing it would be a false alarm about a write the run
        # does not make. upgrade's --template defaults to the skill's own template, so checking
        # that template against itself is exactly the run that must still work.
        code, message = _capture_stderr(
            upgrade.main, ["upgrade.py", os.fspath(deck_scaffold.TEMPLATE), "--check"])
        self.assertNotIn(REFUSAL, message)
        self.assertEqual(code, 0, message)

    def test_retrofit_copy_assets_companions_cannot_land_on_an_input(self):
        # retrofit delegates its companion copies to new_document._copy_companions, so it needs
        # the same per-companion check rather than inheriting one.
        directory = self._tmpdir()
        companion = os.path.join(directory, new_document.COMPANIONS[0])
        _write(companion, '{"tokens": {"--cp-bg": "#101820"}}\n')
        original = _read(companion)
        page = os.path.join(directory, "page.html")
        _write(page, "<!doctype html>\n<html><head></head><body><h1>Hi</h1></body></html>\n")
        code, message = _capture_stderr(retrofit.main, [
            "retrofit.py", page, "--label", "Page", "--kind", "report",
            "--key", "alias-retrofit-companion", "--brand", companion, "--copy-assets",
            "--out", os.path.join(directory, "out.html")])
        self.assertNotEqual(code, 0, "a companion replaced the brand profile")
        self.assertIn(REFUSAL, message)
        self.assertEqual(_read(companion), original)

    def test_copy_assets_companions_cannot_land_on_an_input(self):
        # The companions land on FIXED names beside the document, so a destination the caller
        # never spelled can still collide with an input the run read.
        directory = self._tmpdir()
        companion = os.path.join(directory, new_document.COMPANIONS[0])
        _write(companion, "<h1>Title</h1>\n<p>the content fragment, which must survive</p>\n")
        original = _read(companion)
        code, message = _capture_stderr(new_document.main, [
            "new_document.py", "--content", companion,
            "--out", os.path.join(directory, "doc.html"), "--force", "--copy-assets",
            "--template", NONSHAREABLE_TEMPLATE,
            "--key", "alias-companion", "--label", "Doc", "--kind", "report",
            "--allow-unvalidated-output"])
        self.assertNotEqual(code, 0, "a companion replaced the content fragment")
        self.assertIn(REFUSAL, message)
        self.assertEqual(_read(companion), original)


class SameFileTests(unittest.TestCase):
    """The shared canonical-path helper behind the refusal."""

    def _tmpdir(self):
        directory = tempfile.mkdtemp(prefix="cmh-same-file-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return directory

    def test_same_file_is_canonical_not_textual(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        _write(path, "x")
        os.mkdir(os.path.join(directory, "sub"))
        self.assertTrue(_atomic_io.same_file(path, path))
        self.assertTrue(_atomic_io.same_file(
            path, os.path.join(directory, "sub", os.pardir, "doc.html")))
        self.assertTrue(_atomic_io.same_file(path, os.path.join(directory, ".", "doc.html")))

    def test_same_file_follows_a_symlink_to_its_target(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        _write(path, "x")
        link = os.path.join(directory, "link.html")
        try:
            os.symlink(path, link)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("this platform does not allow creating a symlink here")
        self.assertTrue(_atomic_io.same_file(link, path))

    def test_same_file_folds_case_where_the_filesystem_does(self):
        # Only meaningful on a case-insensitive filesystem (Windows, the default macOS one);
        # elsewhere the two spellings really are different files and must NOT match.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        _write(path, "x")
        shouty = os.path.join(directory, "DOC.HTML")
        insensitive = os.path.exists(shouty)
        self.assertEqual(_atomic_io.same_file(path, shouty), insensitive)

    def test_two_different_files_are_not_the_same_file(self):
        directory = self._tmpdir()
        a = os.path.join(directory, "a.html")
        b = os.path.join(directory, "b.html")
        _write(a, "x")
        _write(b, "x")
        self.assertFalse(_atomic_io.same_file(a, b))
        self.assertFalse(_atomic_io.same_file(a, os.path.join(directory, "missing.html")))
        self.assertFalse(_atomic_io.same_file(a, None))
        self.assertFalse(_atomic_io.same_file(None, a))

    def test_a_path_the_platform_cannot_represent_answers_no_rather_than_raising(self):
        # A CLI boundary must not turn a safety check into a traceback: os.path.samefile
        # raises ValueError on an embedded NUL, not OSError.
        self.assertFalse(_atomic_io.same_file("doc\x00.html", "doc.html"))

    def test_an_input_that_is_not_a_file_is_never_an_alias(self):
        # `-` (stdin), an absent optional input, a directory, and a --theme naming a built-in
        # preset are all "not a file the tool read", so they need no per-caller special case.
        directory = self._tmpdir()
        out = os.path.join(directory, "out.html")
        _write(out, "x")
        err = io.StringIO()
        stderr, sys.stderr = sys.stderr, err
        try:
            refused = _atomic_io.refuse_aliased_output(
                "t", out, ["-", None, "", directory, os.path.join(directory, "gone.html")])
        finally:
            sys.stderr = stderr
        self.assertFalse(refused)
        self.assertEqual(err.getvalue(), "")

    def test_a_file_genuinely_named_dash_is_still_protected(self):
        directory = self._tmpdir()
        dash = os.path.join(directory, "-")
        _write(dash, "the user's file, literally named -\n")
        err = io.StringIO()
        stderr, sys.stderr = sys.stderr, err
        try:
            refused = _atomic_io.refuse_aliased_output("t", dash, [dash])
        finally:
            sys.stderr = stderr
        self.assertTrue(refused)
        self.assertIn(REFUSAL, err.getvalue())

    def test_the_message_names_both_paths_and_the_resolved_file(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        _write(path, "x")
        spelled = os.path.join(directory, ".", "doc.html")
        err = io.StringIO()
        stderr, sys.stderr = sys.stderr, err
        try:
            refused = _atomic_io.refuse_aliased_output("t", spelled, [path])
        finally:
            sys.stderr = stderr
        message = err.getvalue()
        self.assertTrue(refused)
        self.assertIn(spelled, message)
        self.assertIn(path, message)
        self.assertIn(os.path.realpath(path), message)


def _calls_refusal(node):
    """True when `node` is a call to the shared refusal, however it was imported."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (getattr(func, "attr", None) == "refuse_aliased_output"
            or getattr(func, "id", None) == "refuse_aliased_output")


def _takes_out_option(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "add_argument"
                and any(isinstance(a, ast.Constant) and a.value == "--out" for a in node.args)):
            return True
    return False


def _stops(stmt):
    """True when `stmt` leaves the CLI with a failure.

    A bare `SystemExit(1)` expression only CONSTRUCTS the exception, so it does not count; the
    `raise SystemExit(...)` spelling is caught by the `ast.Raise` branch above."""
    if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value not in (0, None, False)
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        return (getattr(stmt.value.func, "attr", None)
                or getattr(stmt.value.func, "id", None)) == "exit"
    return False


def _entrypoint(tree):
    """The tool's `main`, or the whole module when it has none - the only scope in which a
    refusal proves anything. A call sitting in an unrelated helper says nothing about whether
    the write path is guarded."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            return node
    return tree


def guards_out_aliasing(tree):
    """True when the tool's entrypoint refuses an aliasing destination AND ACTS on the answer.

    A bare call is not enough: `refuse_aliased_output` reports and returns a bool, so a tool
    that called it and ignored the result would be exactly as unprotected as one that never
    called it, while looking guarded to a checker that only matches the call. The test must be
    the call ITSELF, so an inverted (`if not ...`) or conditional (`if x and ...`) spelling -
    which lets an aliasing run fall through to the write - does not count either."""
    for node in ast.walk(_entrypoint(tree)):
        if not isinstance(node, ast.If) or not _calls_refusal(node.test):
            continue
        if any(_stops(stmt) for stmt in node.body):
            return True
    return False


class OutAliasGuardTests(unittest.TestCase):
    """A NEW tool cannot quietly skip the refusal."""

    def _tools(self):
        """Every shipped tool module, keyed by its path under tools/ (walked recursively, so a
        CLI added in a nested package is not invisible to this guard)."""
        for root, dirs, names in os.walk(_paths.TOOLS):
            dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
            for name in sorted(names):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                key = os.path.relpath(path, _paths.TOOLS).replace(os.sep, "/")
                if "/" in key:  # the tools/ root holds shared modules, not tools
                    yield key, path

    def _trees(self):
        for key, path in self._tools():
            yield key, ast.parse(_read(path), filename=path)

    def test_there_are_tools_with_an_out_option_to_check(self):
        # Guards the guard: a discovery walk that found nothing would pass every case below.
        self.assertGreaterEqual(
            len([key for key, tree in self._trees() if _takes_out_option(tree)]), 10)

    def test_every_tool_with_an_out_option_checks_it_or_is_listed_as_in_place(self):
        unguarded = sorted(
            key for key, tree in self._trees()
            if _takes_out_option(tree) and not guards_out_aliasing(tree)
            and key not in OUT_WITHOUT_ALIAS_RISK)
        self.assertEqual(
            unguarded, [],
            "tool(s) with an --out that neither refuse an aliasing destination nor are listed "
            "in OUT_WITHOUT_ALIAS_RISK with a reason: %s" % unguarded)

    def test_the_in_place_list_names_only_tools_that_exist_and_take_an_out(self):
        # A stale entry would exempt nothing, or worse, exempt a renamed or moved tool.
        with_out = {key for key, tree in self._trees() if _takes_out_option(tree)}
        self.assertEqual(sorted(set(OUT_WITHOUT_ALIAS_RISK) - with_out), [],
                         "OUT_WITHOUT_ALIAS_RISK names tool(s) that no longer take an --out")

    def test_the_guard_detects_every_spelling_it_claims_to(self):
        must_catch = (
            "def main(a):\n"
            "    if _atomic_io.refuse_aliased_output('t', o, [i]):\n        return 1\n",
            "def main(a):\n"
            "    if refuse_aliased_output('t', o, [i]):\n        return 1\n",
            "def main(a):\n"
            "    if _atomic_io.refuse_aliased_output('t', o, [i]):\n        raise SystemExit(1)\n",
            "def main(a):\n"
            "    if _atomic_io.refuse_aliased_output('t', o, [i]):\n        sys.exit(1)\n",
        )
        must_not_catch = (
            # Called but ignored: it reports on stderr and the tool writes anyway.
            "def main(a):\n    _atomic_io.refuse_aliased_output('t', o, [i])\n",
            # Guarded but continues: the write still happens.
            "def main(a):\n"
            "    if _atomic_io.refuse_aliased_output('t', o, [i]):\n        pass\n",
            "def main(a):\n"
            "    if _atomic_io.refuse_aliased_output('t', o, [i]):\n        return 0\n",
            # Constructs the exception without raising it, so the write still happens.
            "def main(a):\n"
            "    if _atomic_io.refuse_aliased_output('t', o, [i]):\n        SystemExit(1)\n",
            # Inverted: an ALIASING run is the one that falls through to the write.
            "def main(a):\n"
            "    if not _atomic_io.refuse_aliased_output('t', o, [i]):\n        return 1\n",
            # Conditional: the refusal only bites when some other flag happens to be set.
            "def main(a):\n"
            "    if x and _atomic_io.refuse_aliased_output('t', o, [i]):\n        return 1\n",
            "def main(a):\n"
            "    if x or _atomic_io.refuse_aliased_output('t', o, [i]):\n        return 1\n",
            # In an unrelated helper, while main's write path is unguarded.
            "def helper(a):\n"
            "    if _atomic_io.refuse_aliased_output('t', o, [i]):\n        return 1\n"
            "def main(a):\n    write(o)\n",
            # A different helper entirely.
            "def main(a):\n    if _atomic_io.same_file(o, i):\n        return 1\n",
        )
        for source in must_catch:
            with self.subTest(source=source):
                self.assertTrue(guards_out_aliasing(ast.parse(source)))
        for source in must_not_catch:
            with self.subTest(source=source):
                self.assertFalse(guards_out_aliasing(ast.parse(source)))


if __name__ == "__main__":
    unittest.main()
