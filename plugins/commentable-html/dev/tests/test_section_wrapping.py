"""CMH-VAL-14: warn when top-level #commentRoot content is not wrapped in <section>.

A report/plan/generic document renders each top-level <section> as a boxed card
(#commentRoot > section). Content authored as bare top-level <h2> headings passes
validation but renders flat and off-brand, so the validator emits a non-fatal warning.
A properly sectioned document has its <h2>s INSIDE <section> wrappers (so they are not
direct children of #commentRoot); slides and boards do not use section cards and are exempt.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_validate import (  # noqa: E402
    CONTENT_BEGIN,
    CONTENT_END,
    EMBEDDED_REGION,
    HANDLED_REGION,
    JS_REGION,
    _validate_text,
    build,
    comment_ui,
)

_NEEDLE = "boxed card"


def _main(inner):
    return (
        '<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
        'data-doc-label="l" data-doc-source="s">\n'
        + CONTENT_BEGIN + "\n" + inner + "\n" + CONTENT_END + "\n</main>"
    )


def _doc(inner, kind="generic"):
    return build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), _main(inner), JS_REGION], kind=kind)


FLAT = "<h1>T</h1>\n<h2>One</h2>\n<p>a</p>\n<h2>Two</h2>\n<p>b</p>\n<h2>Three</h2>\n<p>c</p>"
SECTIONED = (
    '<h1>T</h1>\n'
    '<section aria-labelledby="one"><h2 id="one">One</h2><p>a</p></section>\n'
    '<section aria-labelledby="two"><h2 id="two">Two</h2><p>b</p></section>'
)


class SectionWrappingTests(unittest.TestCase):
    def test_flat_top_level_h2_warns(self):
        errors, warnings = _validate_text(_doc(FLAT))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any(_NEEDLE in w for w in warnings),
                        "expected a boxed-card section warning, got: %r" % warnings)

    def test_sectioned_content_is_clean(self):
        errors, warnings = _validate_text(_doc(SECTIONED))
        self.assertEqual(errors, [], errors)
        self.assertFalse(any(_NEEDLE in w for w in warnings),
                         "sectioned content must not warn, got: %r" % warnings)

    def test_slides_kind_is_exempt(self):
        _, warnings = _validate_text(_doc(FLAT, kind="slides"))
        self.assertFalse(any(_NEEDLE in w for w in warnings),
                         "slides must be exempt, got: %r" % warnings)

    def test_single_top_level_h2_is_clean(self):
        _, warnings = _validate_text(_doc("<h1>T</h1>\n<h2>Only</h2>\n<p>a</p>"))
        self.assertFalse(any(_NEEDLE in w for w in warnings),
                         "a single top-level h2 must not warn, got: %r" % warnings)


if __name__ == "__main__":
    unittest.main()
