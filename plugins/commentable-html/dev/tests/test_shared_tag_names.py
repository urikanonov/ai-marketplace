"""CMH-VAL-21 clause 7: the scanners OUTSIDE the validator's `checks` package fold TAG names the
way a browser folds them - ASCII-only.

U+212A KELVIN SIGN is the only character outside ASCII whose `str.lower()` is an ASCII letter
("k"), so a scanner that folds a name with Python's Unicode `str.lower()` reads `<lin\u212a>` as a
`<link>`, `</mar\u212a>` as a `<mark>` closer and `data-cmh-chec\u212alist` as
`data-cmh-checklist` - elements and attributes a browser keeps distinct. `checks/parsing` closed
that for the checks package; these tests pin the same rule for every scanner beside it, and the
structural gate at the bottom keeps a NEW scanner from reintroducing the host fold.
"""
import ast
import os
import sys
import unittest
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants + tools bootstrap

sys.path.insert(0, _paths.TOOLS)

import _browser_attrs  # noqa: E402
import _favicon  # noqa: E402
import checklist_apply  # noqa: E402
import deck_fix_fonts  # noqa: E402
import deck_validate  # noqa: E402
import new_document  # noqa: E402
import notes_apply  # noqa: E402
import to_shareable  # noqa: E402
import wrap_sections  # noqa: E402
from cmhval import contrast  # noqa: E402

K = "\u212a"  # KELVIN SIGN


class SharedTagNameShimTests(unittest.TestCase):
    """The shim hands the tools the SHIPPED rule, and its degraded path still names a tag."""

    def test_the_shim_resolves_the_shipped_fold_and_base(self):
        self.assertIsNotNone(_browser_attrs._shared_ascii_lower)
        self.assertIsNotNone(_browser_attrs._shared_tag_names)
        self.assertIs(_browser_attrs.BrowserTagNames, _browser_attrs._shared_tag_names)
        self.assertTrue(issubclass(_browser_attrs.BrowserTagNames, HTMLParser))

    def test_the_fold_is_ascii_only(self):
        self.assertEqual(_browser_attrs.ascii_lower("LIN" + K), "lin" + K)
        self.assertEqual(_browser_attrs.ascii_lower("LINK"), "link")
        self.assertEqual(_browser_attrs.ascii_lower("\u017fCRIPT"), "\u017fcript")

    def test_the_degraded_base_still_names_a_tag(self):
        # Only a broken/partial install gets here; a degraded fold beats a scanner that cannot run.
        degraded = _browser_attrs._FallbackTagNames()
        self.assertEqual(degraded._browser_tag("DIV"), "div")

    def test_the_start_tag_parser_names_a_tag_the_browsers_way(self):
        # The contrast scanner derives from `StartTagParser` (it also needs the vendored tag
        # extent and the bounded numeric decode), so that base must carry the same fold - and its
        # degraded fallback must still answer `_browser_tag()` rather than raise.
        self.assertTrue(hasattr(_browser_attrs.StartTagParser, "_browser_tag"))
        self.assertTrue(issubclass(_browser_attrs._start_tag_parser(None),
                                   _browser_attrs._FallbackTagNames))


class ContrastScannerTagNameTests(unittest.TestCase):
    """The contrast scanner's inline-style and element views (CMH-VAL-21 clause 7)."""

    def test_an_inline_style_carries_the_browsers_element_name(self):
        scanner = contrast._StyleScanner()
        scanner.feed('<mar%s style="color:#111">x</mar%s>' % (K, K))
        scanner.close()
        self.assertEqual([tag for tag, _attrs, _value in scanner.inline_styles], ["mar" + K])

    def test_a_document_node_carries_the_browsers_element_name(self):
        # A `mark { ... }` rule must not reach this element: to a browser it is an unknown
        # element named `mar<KELVIN>`, not a `<mark>`.
        scanner = contrast._DocumentScanner()
        scanner.feed("<mar%s>x</mar%s>" % (K, K))
        scanner.close()
        self.assertEqual([node.tag for node in scanner.root.children], ["mar" + K])


class DeckValidatorTagNameTests(unittest.TestCase):
    """The deck validator's active-content / egress scan."""

    def test_an_unknown_element_is_not_read_as_a_link(self):
        # A browser fetches nothing for `<lin<KELVIN> href=...>`: it is an unknown element, not a
        # stylesheet link, so the egress finding it used to raise was one no browser can produce.
        errors = deck_validate._active_content_errors(
            '<lin%s href="https://evil.example/a.css">' % K)
        self.assertFalse(any("remote media/resource" in e for e in errors), errors)
        real = deck_validate._active_content_errors('<link href="https://evil.example/a.css">')
        self.assertTrue(any("remote media/resource" in e for e in real), real)

    def test_the_authored_content_count_skips_an_unknown_element(self):
        # `<bloc<KELVIN>quote>` is not a `<blockquote>`, so it is not one of the authored
        # elements the overload advisory budgets.
        def counted(markup):
            scanner = deck_validate._AuthoredContentScanner(80)
            scanner.feed('<section class="slide" data-slide-id="s">%s</section>' % markup)
            scanner.close()
            return [r.elements for r in scanner.regions if r.kind == "slide"]

        self.assertEqual(counted("<bloc%squote>x</bloc%squote>" % (K, K)), [0])
        self.assertEqual(counted("<blockquote>x</blockquote>"), [1])


class ChecklistApplyTagNameTests(unittest.TestCase):
    """The checklist applier's container/item scan, which keys on both a tag and a `data-cmh-*`
    attribute name."""

    def test_a_kelvin_container_attribute_is_not_a_checklist(self):
        items = checklist_apply._scan_items(
            '<div data-cmh-chec%slist="c"><p data-cmh-item="i1" data-cmh-state="blank">x</p></div>'
            % K)
        self.assertEqual(items, [])
        real = checklist_apply._scan_items(
            '<div data-cmh-checklist="c"><p data-cmh-item="i1" data-cmh-state="blank">x</p></div>')
        self.assertEqual([i["key"] for i in real], ["i1"])

    def test_an_unknown_element_is_not_treated_as_void(self):
        # `<lin<KELVIN>>` is not a `<link>`, so it opens - and its end tag closes - a nesting
        # level a browser opens too. Read as void, its `</lin<KELVIN>>` matched nothing and the
        # nested container it opened stayed innermost for the rest of the document, so the item
        # after it was filed under the wrong checklist.
        items = checklist_apply._scan_items(
            '<div data-cmh-checklist="outer">'
            '<lin%s data-cmh-checklist="inner"></lin%s>'
            '<p data-cmh-item="i1" data-cmh-state="blank">x</p></div>' % (K, K))
        self.assertEqual([i["container_id"] for i in items], ["outer"])


class NotesApplyTagNameTests(unittest.TestCase):
    """The note applier's span scan."""

    def test_an_unknown_element_is_not_treated_as_void(self):
        # Read as a `<link>`, the element looked void and its note span was never recorded.
        notes = notes_apply._scan_notes('<lin%s data-cmh-note="n1">x</lin%s>' % (K, K))
        self.assertEqual([n["id"] for n in notes], ["n1"])
        self.assertIsNotNone(notes[0]["end"])


class FaviconTagNameTests(unittest.TestCase):
    """The shared favicon detection the retrofit/upgrade tools inject from."""

    def test_an_unknown_element_is_not_a_favicon_link(self):
        self.assertFalse(_favicon.head_has_favicon(
            '<head><lin%s rel="icon" href="f.png"></head>' % K))
        self.assertTrue(_favicon.head_has_favicon(
            '<head><link rel="icon" href="f.png"></head>'))


class WrapSectionsTagNameTests(unittest.TestCase):
    """The section wrapper's top-level scan."""

    def test_an_unknown_element_is_not_treated_as_void(self):
        # Read as a `<link>`, `<lin<KELVIN>>` opened nothing, so the heading inside it looked
        # like a direct child of the fragment and got wrapped in a section it does not head.
        nested = "<lin%s><h2 id=\"a\">H</h2></lin%s>\n<p>x</p>" % (K, K)
        wrapped, count = wrap_sections.wrap_fragment(nested)
        self.assertEqual(count, 0)
        self.assertEqual(wrapped, nested)
        _top, top_count = wrap_sections.wrap_fragment('<h2 id="a">H</h2>\n<p>x</p>')
        self.assertEqual(top_count, 1)


class DeckFontStripTagNameTests(unittest.TestCase):
    """The deck font fixer REMOVES the element it matches, so over-matching is data loss."""

    def test_an_unknown_element_is_not_stripped_as_a_remote_font_link(self):
        html = ('<lin%s rel="stylesheet" href="https://fonts.googleapis.com/css?family=X">\n'
                '<p>keep</p>\n' % K)
        out, removed = deck_fix_fonts._strip_remote_links(html)
        self.assertEqual(removed, 0)
        self.assertEqual(out, html)
        real, real_removed = deck_fix_fonts._strip_remote_links(
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=X">\n'
            '<p>keep</p>\n')
        self.assertEqual(real_removed, 1)
        self.assertNotIn("fonts.googleapis.com", real)

    def test_a_longer_element_name_is_not_stripped_as_a_link(self):
        # The mirror of the same mistake: a tag NAME ends at HTML whitespace, `/` or `>`, so
        # `<link\u212a>` and `<linkish>` are their own elements. A `\b` under `re.ASCII` calls
        # any non-ASCII letter a boundary and would delete the first of them.
        for name in ("link" + K, "linkish"):
            html = '<%s href="https://fonts.gstatic.com/x.woff2">\n<p>keep</p>\n' % name
            out, removed = deck_fix_fonts._strip_remote_links(html)
            with self.subTest(tag=name.encode("unicode_escape")):
                self.assertEqual(removed, 0)
                self.assertEqual(out, html)


class ShareableCompanionTagNameTests(unittest.TestCase):
    """The Shareable conversion REWRITES the companion element it matches."""

    def test_only_a_real_companion_element_is_matched(self):
        style = to_shareable._COMPANION_ELEMENT_RE["style"]
        script = to_shareable._COMPANION_ELEMENT_RE["script"]
        self.assertTrue(style.match('<link href="commentable-html.css">'))
        self.assertTrue(style.match("<LINK/>"))
        self.assertTrue(script.match('<script src="a.js"></script >'))
        for markup in ('<lin%s href="commentable-html.css">' % K,
                       '<link%s href="commentable-html.css">' % K,
                       '<linkish href="commentable-html.css">'):
            with self.subTest(markup=markup.encode("unicode_escape")):
                self.assertIsNone(style.match(markup))
        for markup in ('<scrip%s src="a.js"></scrip%s>' % (K, K),
                       '<script%s src="a.js"></script%s>' % (K, K)):
            with self.subTest(markup=markup.encode("unicode_escape")):
                self.assertIsNone(script.match(markup))

    def test_only_a_real_companion_attribute_is_matched(self):
        # U+017F LONG S lowercases to "s", so a Unicode fold read `\u017frc=` as `src=` and this
        # pass would have rewritten the URL of an attribute a browser never fetches.
        href = to_shareable._URL_ATTR_RE["style"]
        src = to_shareable._URL_ATTR_RE["script"]
        self.assertTrue(href.search('<link HREF="a.css">'))
        self.assertTrue(src.search('<script SRC="a.js">'))
        self.assertIsNone(href.search('<link h\u017fef="a.css">'))
        self.assertIsNone(src.search('<script \u017frc="a.js">'))
        self.assertIsNone(href.search('<link data-href="a.css">'))

    def test_a_raw_text_body_is_bounded_by_a_real_element_name(self):
        body = to_shareable._RAW_TEXT_BODY_RE
        self.assertTrue(body.search("<script>x</script >"))
        self.assertTrue(body.search("<SCRIPT id=a>x</SCRIPT>"))
        self.assertIsNone(body.search("<\u017fcript>x</\u017fcript>"))
        self.assertIsNone(body.search("<script%s>x</script%s>" % (K, K)))

class AuthoringAttributeNameTests(unittest.TestCase):
    """The attribute maps the authoring tools still build themselves."""

    def test_a_kelvin_lookalike_is_not_the_attribute_being_set(self):
        # `_set_attr` REWRITES the matching attribute, so a lookalike must not absorb the write
        # and leave the document without the real one.
        attrs = [("data-comment-%sey" % K, "decoy")]
        new_document._set_attr(attrs, "data-comment-key", "real")
        self.assertEqual(attrs, [("data-comment-%sey" % K, "decoy"),
                                 ("data-comment-key", "real")])

    def test_a_kelvin_lookalike_is_not_the_attribute_being_dropped(self):
        attrs = [("data-comment-%sey" % K, "decoy"), ("data-comment-key", "real")]
        new_document._drop_attr(attrs, "data-comment-key")
        self.assertEqual(attrs, [("data-comment-%sey" % K, "decoy")])


class ContrastSelectorTagNameTests(unittest.TestCase):
    """The contrast scanner's CSS selectors are matched against the SAME folded names."""

    def test_an_attribute_selector_folds_ascii_only(self):
        token = contrast._parse_selector_compound("[data-%sey]" % K)
        self.assertEqual(token["attrs"], [("data-%sey" % K, None)])
        self.assertEqual(contrast._parse_selector_compound("[DATA-KEY]")["attrs"],
                         [("data-key", None)])


class OutsideScannerBaseTests(unittest.TestCase):
    """Structural gate: no scanner outside `tools/validate/checks` may derive straight from
    `html.parser.HTMLParser` without supplying the fold itself, because the host hands every
    handler the UNICODE fold. They derive from a shared base instead - `BrowserTagNames`, or the
    `BrowserBoundaries` / `StartTagParser` that derive from it - so a NEW scanner cannot quietly
    reintroduce clause 7's differential."""

    # A class that DEFINES its own `_browser_tag()` is exempt: that is how each shim's degraded
    # fallback base keeps a broken install working, and it supplies the fold rather than dropping
    # it. Exempted by that PROPERTY, not by file, so nothing else gets a free pass.

    @staticmethod
    def _defines_browser_tag(node):
        return any(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and child.name == "_browser_tag" for child in node.body)

    @staticmethod
    def _dotted(node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

    @classmethod
    def _host_aliases(cls, tree):
        """Every local name that resolves to `html.parser.HTMLParser`, including an aliased or
        indirect import (`from html.parser import HTMLParser as Parser`, `import html.parser as
        hp`, `from html import parser`), so the gate cannot be sidestepped by renaming it."""
        names = {"HTMLParser"}
        modules = {"html.parser"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "html.parser":
                for alias in node.names:
                    if alias.name == "HTMLParser":
                        names.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "html":
                for alias in node.names:
                    if alias.name == "parser":
                        modules.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "html.parser":
                        # `import html.parser` binds `html`; `... as hp` binds `hp`.
                        modules.add(alias.asname or "html")
                    elif alias.name == "html":
                        modules.add(alias.asname or "html")
        return names, modules

    def _outside_tool_files(self):
        checks = os.path.join(_paths.TOOLS, "validate", "checks")
        for root, dirs, files in os.walk(_paths.TOOLS):
            dirs[:] = [d for d in dirs if not d.startswith((".", "__pycache__"))]
            if root == checks or root.startswith(checks + os.sep):
                continue
            for name in sorted(files):
                if name.endswith(".py"):
                    yield os.path.join(root, name)

    def test_no_outside_scanner_derives_from_the_host_parser(self):
        offenders = []
        for path in self._outside_tool_files():
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            names, modules = self._host_aliases(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if self._defines_browser_tag(node):
                    continue
                for base in node.bases:
                    dotted = self._dotted(base)
                    head, _dot, leaf = dotted.rpartition(".")
                    if dotted in names or (leaf == "HTMLParser" and (not head or head in modules)):
                        offenders.append("%s: %s" % (
                            os.path.relpath(path, _paths.TOOLS), node.name))
        self.assertEqual(offenders, [], "these scanners still fold tag names with the host's "
                                        "Unicode str.lower(); derive them from "
                                        "_browser_attrs.BrowserTagNames instead")

    def test_the_gate_sees_the_scanners_it_is_meant_to_cover(self):
        # Without this the gate above would pass vacuously if the walk ever stopped finding files.
        seen = {os.path.basename(p) for p in self._outside_tool_files()}
        for name in ("contrast.py", "deck_validate.py", "checklist_apply.py", "_favicon.py",
                     "notes_apply.py", "wrap_sections.py"):
            self.assertIn(name, seen)

    def test_the_gate_catches_an_aliased_host_base(self):
        # A renamed or indirect import is the obvious way to sidestep a name-matching gate, so
        # the alias resolution is pinned rather than assumed.
        names, _modules = self._host_aliases(
            ast.parse("from html.parser import HTMLParser as Parser\n"
                      "class Sneaky(Parser):\n    pass\n"))
        self.assertIn("Parser", names)
        for source, module in (("import html.parser as hp\n", "hp"),
                               ("import html.parser\n", "html"),
                               ("from html import parser\n", "parser"),
                               ("from html import parser as p\n", "p")):
            _names, modules = self._host_aliases(ast.parse(source))
            with self.subTest(source=source.strip()):
                self.assertIn(module, modules)

    def test_the_gate_flags_every_spelling_of_the_host_base(self):
        for source in ("from html.parser import HTMLParser as Parser\nclass S(Parser):\n    x=1\n",
                       "import html.parser\nclass S(html.parser.HTMLParser):\n    x=1\n",
                       "import html.parser as hp\nclass S(hp.HTMLParser):\n    x=1\n",
                       "from html import parser\nclass S(parser.HTMLParser):\n    x=1\n"):
            tree = ast.parse(source)
            names, modules = self._host_aliases(tree)
            flagged = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for base in node.bases:
                    dotted = self._dotted(base)
                    head, _dot, leaf = dotted.rpartition(".")
                    if dotted in names or (leaf == "HTMLParser"
                                           and (not head or head in modules)):
                        flagged.append(node.name)
            with self.subTest(source=source.splitlines()[0]):
                self.assertEqual(flagged, ["S"])


if __name__ == "__main__":
    unittest.main()
