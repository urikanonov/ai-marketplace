#!/usr/bin/env python3
"""Cross-implementation parity for the syntax highlighter (GH-REGRESS-HIGHLIGHT-PARITY).

The author-time Python tool (highlight_code.py) and the runtime JS diff highlighter
(cmhHighlightCode in assets/js/26-highlight.js) are parallel reimplementations of the same
tokenizer. They can drift silently - the PR #33 regression (single quotes swallowing Rust
lifetimes, YAML apostrophes, C++ digit separators as strings) had to be fixed in both. This test
pins the PYTHON side to the shared fixture tests/fixtures/highlight_parity.json; tests/57-highlight-parity.spec.js
pins the RUNTIME side to the SAME fixture, so a divergence fails one of the two suites.
"""
import html
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import highlight_code as H  # noqa: E402

PARITY_FIXTURE = os.path.join(HERE, "fixtures", "highlight_parity.json")
SPAN_RE = re.compile(r'<span class="cmh-code-([a-z]+)">(.*?)</span>', re.S)
HIGHLIGHT_JS = os.path.join(_paths.ASSETS, "js", "26-highlight.js")
# A key inside the _HL_FAMILY object literal: a bareword (javascript) or a quoted token ("c++")
# immediately before a colon. Values ("c", "hash") never precede a colon, so they are not captured.
_HL_FAMILY_KEY_RE = re.compile(r'("[^"]+"|[A-Za-z_$][A-Za-z0-9_$+.#-]*)\s*:')
# One `<family>: new Set(("a b " + "c d").split(" "))` entry of the _HL_FAM_KW map.
_FAM_KW_ENTRY_RE = re.compile(r'([A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*new Set\(\((.*?)\)\.split\(" "\)\)', re.S)
_JS_STRING_RE = re.compile(r'"([^"]*)"')
# The families _hlTokenRe() gives dedicated comment/string patterns to (`fam === "xxx"`).
_FAM_BRANCH_RE = re.compile(r'fam === "([a-z]+)"')
# Families that are deliberately keyword-shared: `hash` and `c` are multi-language buckets (python,
# ruby, shell, yaml ... / every C-family language), so no single author-time keyword list describes
# them and they keep the broad shared set. `markdown` carries no keywords at all.
SHARED_KEYWORD_FAMILIES = {"hash", "c", "markdown"}
# Each dedicated family and the author-time language(s) whose keywords it must mirror.
FAMILY_LANGUAGES = {
    "sql": ("sql",),
    "css": ("css",),
    "lua": ("lua",),
    "haskell": ("haskell",),
    "powershell": ("powershell",),
    "batch": ("batch",),
    "json": ("json",),
    "markup": ("html", "xml"),
}


def _highlight_js():
    with open(HIGHLIGHT_JS, "r", encoding="utf-8") as fh:
        return fh.read()


def runtime_family_keywords():
    """{family: set(keywords)} parsed from the _HL_FAM_KW map in assets/js/26-highlight.js."""
    src = _highlight_js()
    m = re.search(r"const _HL_FAM_KW\s*=\s*\{(.*?)\n\};", src, re.S)
    assert m, "could not locate the _HL_FAM_KW object literal in 26-highlight.js"
    out = {}
    for fam, body in _FAM_KW_ENTRY_RE.findall(m.group(1)):
        words = "".join(_JS_STRING_RE.findall(body)).split()
        out[fam] = set(words)
    return out


def runtime_shared_keywords():
    """The broad, multi-language _HL_KW_SET the shared families fall back to."""
    src = _highlight_js()
    m = re.search(r"const _HL_KW_SET\s*=\s*new Set\(\((.*?)\)\.split\(\" \"\)\);", src, re.S)
    assert m, "could not locate the _HL_KW_SET literal in 26-highlight.js"
    return set("".join(_JS_STRING_RE.findall(m.group(1))).split())


def runtime_dedicated_families():
    """Families _hlTokenRe() gives their own comment/string patterns to."""
    return set(_FAM_BRANCH_RE.findall(_highlight_js())) - SHARED_KEYWORD_FAMILIES


def runtime_known_languages():
    """The set of language labels the runtime tokenizer knows (keys of _HL_FAMILY in
    assets/js/26-highlight.js). diffLangKnown() gates both the diff highlighter and the
    runtime fallback on membership in this set."""
    with open(HIGHLIGHT_JS, "r", encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"const _HL_FAMILY\s*=\s*\{(.*?)\};", src, re.S)
    assert m, "could not locate the _HL_FAMILY object literal in 26-highlight.js"
    keys = set()
    for km in _HL_FAMILY_KEY_RE.finditer(m.group(1)):
        key = km.group(1)
        if key.startswith('"'):
            key = key[1:-1]
        keys.add(key.lower())
    return keys


def classes_to_text(inner_html):
    """Return {class: concatenated unescaped text} for every cmh-code-* span in the output."""
    out = {}
    for cls, body in SPAN_RE.findall(inner_html):
        out.setdefault(cls, "")
        out[cls] += html.unescape(body)
    return out


def load_cases():
    with open(PARITY_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)["cases"]


class HighlightParityPythonTests(unittest.TestCase):
    def test_python_tool_matches_the_shared_parity_fixture(self):
        for case in load_cases():
            lang, code = case["lang"], case["code"]
            spans = classes_to_text(H.highlight_code(lang, code))
            with self.subTest(lang=lang, code=code):
                for tok in case.get("str", []):
                    self.assertIn(tok, spans.get("str", ""),
                                  "%s: %r should be a string token" % (lang, tok))
                for tok in case.get("com", []):
                    self.assertIn(tok, spans.get("com", ""),
                                  "%s: %r should be a comment token" % (lang, tok))
                for tok in case.get("kw", []):
                    self.assertIn(tok, spans.get("kw", ""),
                                  "%s: %r should be a keyword token" % (lang, tok))
                for tok in case.get("key", []):
                    self.assertIn(tok, spans.get("key", ""),
                                  "%s: %r should be a property-key token" % (lang, tok))
                for tok in case.get("notStr", []):
                    self.assertNotIn(tok, spans.get("str", ""),
                                     "%s: %r must NOT be swallowed as a string" % (lang, tok))
                for tok in case.get("notKw", []):
                    self.assertNotIn(tok, spans.get("kw", ""),
                                     "%s: %r must NOT be a keyword token" % (lang, tok))
                for tok in case.get("notKey", []):
                    self.assertNotIn(tok, spans.get("key", ""),
                                     "%s: %r must NOT be a property-key token" % (lang, tok))


class FamilyKeywordParityTests(unittest.TestCase):
    """CMH-HL-03: a family with its own patterns must also have its own keyword set.

    The runtime keeps ONE broad keyword set for the multi-language `hash`/`c` buckets. A family that
    gets dedicated comment/string patterns is 1:1 with an author-time language, so sharing that
    broad set both UNDER-colors (no `select`/`insert`/`join` for sql, no `auto`/`inherit` for css)
    and OVER-colors (`class` in lua, `def` in haskell - words the author-time tool never treats as
    keywords there). Pin each dedicated family to the author-time list instead.
    """

    def test_every_dedicated_family_has_its_own_keyword_set(self):
        # A future family with its own comment/string patterns must not silently inherit the broad
        # set - that is exactly how `sql` shipped without SELECT.
        missing = sorted(runtime_dedicated_families() - set(runtime_family_keywords()))
        self.assertEqual(missing, [],
                         "every family with dedicated patterns needs a _HL_FAM_KW entry; missing: %r"
                         % missing)
        unexpected = sorted(set(runtime_family_keywords()) - set(FAMILY_LANGUAGES))
        self.assertEqual(unexpected, [],
                         "a new _HL_FAM_KW family must also be mapped in FAMILY_LANGUAGES so this "
                         "test knows which author-time language it mirrors; unmapped: %r" % unexpected)

    def test_each_family_keyword_set_matches_the_author_time_config(self):
        runtime = runtime_family_keywords()
        for fam, langs in sorted(FAMILY_LANGUAGES.items()):
            expected = set()
            for lang in langs:
                expected |= set(H.LANGUAGE_CONFIGS[lang]["keywords"])
            with self.subTest(family=fam):
                self.assertIn(fam, runtime)
                self.assertEqual(runtime[fam], expected,
                                 "runtime _HL_FAM_KW[%r] must mirror %s keywords exactly (only in "
                                 "runtime: %r; only author-time: %r)"
                                 % (fam, "+".join(langs),
                                    sorted(runtime.get(fam, set()) - expected),
                                    sorted(expected - runtime.get(fam, set()))))

    def test_the_shared_keyword_set_is_not_widened(self):
        # The fix must ADD per-family sets, never broaden the shared one: a SQL-only word like
        # `select` would then tint a plain identifier in C, Python, Go and everything else.
        shared = runtime_shared_keywords()
        sql_only = set(H.LANGUAGE_CONFIGS["sql"]["keywords"]) - set(H.LANGUAGE_CONFIGS["python"]["keywords"])
        for word in ("select", "insert", "join", "group", "order", "update", "table", "values"):
            self.assertIn(word, sql_only)
            self.assertNotIn(word, shared,
                             "%r is SQL-specific and must not enter the shared keyword set" % word)
        # Same for the other dedicated families' distinctive words.
        for word in ("endlocal", "setlocal", "dynamicparam", "qualified", "infixl", "inherit"):
            self.assertNotIn(word, shared,
                             "%r belongs to one family's set, not the shared one" % word)



class RuntimeLanguageCoverageTests(unittest.TestCase):
    def test_runtime_knows_every_author_time_language(self):
        # CMH-HL-03: the runtime tokenizer (diffLangKnown / _HL_FAMILY) must know every language the
        # author-time highlighter supports (highlight_code.LANGUAGE_CONFIGS). Otherwise a supported
        # language that was authored raw renders monochrome at runtime, because the runtime fallback
        # (highlightCodeBlocks, CMH-HL-01) and the diff highlighter only fire for a known language.
        # This guard fails the moment an author-time language is added without runtime coverage.
        known = runtime_known_languages()
        missing = sorted(set(H.LANGUAGE_CONFIGS) - known)
        self.assertEqual(missing, [],
                         "runtime _HL_FAMILY must cover every author-time language; missing: %r "
                         "(add them to _HL_FAMILY in assets/js/26-highlight.js)" % missing)

    def test_runtime_knows_every_author_time_alias(self):
        # CMH-HL-03: the guard above covers LANGUAGE_CONFIGS, but an ALIAS is just as reachable from a
        # `language-XXX` label, and the runtime resolves nothing - diffLangKnown() looks the RAW label
        # up in _HL_FAMILY. So an alias the runtime does not know renders monochrome even though the
        # author-time tool highlights it. That is exactly how `language-jsonc` shipped as plain text.
        known = runtime_known_languages()
        missing = sorted(set(H.ALIASES) - known)
        self.assertEqual(missing, [],
                         "runtime _HL_FAMILY must cover every author-time alias; missing: %r "
                         "(add them to _HL_FAMILY in assets/js/26-highlight.js)" % missing)

    def test_author_time_knows_every_runtime_label(self):
        # CMH-HL-03, the REVERSE direction. A label the runtime knows but the author-time tool does
        # not is highlighted at runtime and baked as plain text - and, since a markdown fence picks
        # its nested language from this same table (CMH-HL-07/08), it would also nest on one path
        # and stay opaque on the other. Keeping the two tables identical is what makes the nested
        # fence language a shared decision rather than a per-implementation guess.
        author = set(H.LANGUAGE_CONFIGS) | set(H.ALIASES)
        missing = sorted(runtime_known_languages() - author)
        self.assertEqual(missing, [],
                         "highlight_code must know every runtime _HL_FAMILY label; missing: %r "
                         "(add them to LANGUAGE_CONFIGS or ALIASES in tools/blocks/highlight_code.py)"
                         % missing)


if __name__ == "__main__":
    unittest.main()
