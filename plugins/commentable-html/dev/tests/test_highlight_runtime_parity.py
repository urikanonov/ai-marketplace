#!/usr/bin/env python3
"""Runtime/author-time parity for extension inference, keyword sets, and string styles.

Covers CMH-HL-13 (`_EXT_LANG` maps every supported language's obvious extensions),
CMH-HL-14 (the runtime keyword lookup is per LANGUAGE, exactly mirroring the author-time
config, instead of one approximate bucket shared by 23 languages) and CMH-HL-15 (the
runtime `sql` family accepts the same string styles as its author-time config).

These are all the same defect class: a runtime family whose patterns do not mirror the
author-time config it claims parity with. The tests read the RUNTIME source and compare
it to the author-time tables, so a future divergence fails here rather than shipping as
a block that renders one way baked and another way live.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
sys.path.insert(0, _paths.TOOLS)
import highlight_code as H  # noqa: E402

RUNTIME_JS = os.path.join(_paths.ASSETS, "js", "26-highlight.js")


def _read_runtime():
    with open(RUNTIME_JS, "r", encoding="utf-8") as fh:
        return fh.read()


def _js_object(src, name):
    """Return the `{...}` body text of a top-level `const <name> = {...};`."""
    m = re.search(r"const\s+" + re.escape(name) + r"\s*=\s*\{", src)
    if not m:
        raise AssertionError("runtime is missing const %s" % name)
    i, depth = m.end() - 1, 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError("unbalanced braces in %s" % name)


def _mapping_keys(body):
    """Return the bare/quoted keys of a flat JS object literal."""
    return {a or b for a, b in
            re.findall(r'(?m)(?:^|[,{])\s*(?:"([^"]+)"|([A-Za-z_$][\w$]*))\s*:', body)}


def _ext_lang_map():
    body = _js_object(_read_runtime(), "_EXT_LANG")
    out = {}
    for m in re.finditer(r'(?:"([^"]+)"|([A-Za-z_$][\w$]*))\s*:\s*"([^"]+)"', body):
        out[m.group(1) or m.group(2)] = m.group(3)
    return out


def _family_branch(src, fam):
    """Return the body of `else if (fam === "<fam>") { ... }`, brace-aware.

    A naive `[^}]*` stops at the first `}` inside a regex literal (haskell's `(?:-\\}|$)`),
    which would make this guard report a false divergence.
    """
    m = re.search(r'\(fam === "%s"\)\s*\{' % re.escape(fam), src)
    if not m:
        return None
    i, depth = m.end() - 1, 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i + 1:j]
    return None


def _lang_kw_sets():
    """Return {language: set(keywords)} declared by the runtime's per-language map."""
    body = _js_object(_read_runtime(), "_HL_LANG_KW")
    out = {}
    for m in re.finditer(
            r'(?:"([^"]+)"|([A-Za-z_$][\w$]*))\s*:\s*new Set\(\(([^)]*)\)\.split\(" "\)\)', body):
        lang = m.group(1) or m.group(2)
        words = re.findall(r'"([^"]*)"', m.group(3))
        out[lang] = set(" ".join(words).split())
    return out


# The obvious primary extension(s) of every author-time language, used as the guard for
# CMH-HL-13. A language whose files really have no conventional extension is listed with
# an empty tuple and an explicit reason.
EXPECTED_EXTENSIONS = {
    "python": ("py",), "javascript": ("js",), "typescript": ("ts",), "java": ("java",),
    "c": ("c",), "cpp": ("cpp",), "csharp": ("cs",), "go": ("go",), "rust": ("rs",),
    "ruby": ("rb",), "php": ("php",), "swift": ("swift",), "kotlin": ("kt",),
    "scala": ("scala",), "sql": ("sql",), "shell": ("sh",), "yaml": ("yml", "yaml"),
    "toml": ("toml",), "json": ("json",), "css": ("css",), "lua": ("lua",),
    "haskell": ("hs",), "elixir": ("ex",), "powershell": ("ps1",), "batch": ("bat",),
    "groovy": ("groovy",), "perl": ("pl",), "r": ("r",), "objectivec": ("m",),
    "markdown": ("md",), "html": ("html", "htm"), "xml": ("xml",), "dart": ("dart",),
}


class ExtensionInferenceTests(unittest.TestCase):
    """CMH-HL-13."""

    def test_every_supported_language_has_its_extensions_mapped(self):
        ext = _ext_lang_map()
        missing = []
        for lang, exts in sorted(EXPECTED_EXTENSIONS.items()):
            for e in exts:
                if e not in ext:
                    missing.append("%s (.%s)" % (lang, e))
        self.assertEqual(missing, [], "_EXT_LANG has no entry for: " + ", ".join(missing))

    def test_markup_and_xml_extensions_resolve_to_a_highlightable_family(self):
        ext = _ext_lang_map()
        fam = _mapping_keys(_js_object(_read_runtime(), "_HL_FAMILY"))
        for e in ("html", "htm", "xml"):
            self.assertIn(e, ext, ".%s must infer a language" % e)
            self.assertIn(ext[e], fam, ".%s infers %r, which has no family" % (e, ext[e]))

    def test_the_guard_table_itself_covers_every_author_time_language(self):
        # Otherwise a new language could ship with the same hole this test exists to catch.
        known = set(H.LANGUAGE_CONFIGS)
        listed = {H._normalize_language(k) for k in EXPECTED_EXTENSIONS}
        self.assertEqual(known - listed, set(),
                         "EXPECTED_EXTENSIONS is missing author-time language(s)")


class PerLanguageKeywordTests(unittest.TestCase):
    """CMH-HL-14."""

    def test_every_shared_bucket_language_has_an_exact_runtime_keyword_set(self):
        # The hash/c buckets used one broad set for 23 languages, which both over-colored
        # (a lowercase `true` in Python) and under-colored (Python's `True`/`False`/`None`
        # never matched the case-sensitive lookup).
        runtime = _lang_kw_sets()
        mismatched = []
        for lang, words in sorted(runtime.items()):
            cfg = H.LANGUAGE_CONFIGS.get(H._normalize_language(lang))
            if cfg is None:
                mismatched.append("%s: not an author-time language" % lang)
                continue
            expected = set(cfg.get("keywords", frozenset()))
            if words != expected:
                mismatched.append("%s: +%s -%s" % (
                    lang, sorted(words - expected)[:6], sorted(expected - words)[:6]))
        self.assertEqual(mismatched, [], "runtime keyword sets diverge: " + "; ".join(mismatched))

    def test_python_capitalized_literals_are_keywords(self):
        runtime = _lang_kw_sets()
        self.assertIn("python", runtime, "python needs its own runtime keyword set")
        for word in ("True", "False", "None"):
            self.assertIn(word, runtime["python"])

    def test_a_lowercase_true_is_not_a_python_keyword(self):
        self.assertNotIn("true", _lang_kw_sets()["python"])

    def test_the_runtime_covers_every_shared_bucket_language(self):
        src = _read_runtime()
        fam_body = _js_object(src, "_HL_FAMILY")
        shared = set()
        for m in re.finditer(r'(?:"([^"]+)"|([A-Za-z_$][\w$]*))\s*:\s*"(hash|c)"', fam_body):
            name = m.group(1) or m.group(2)
            if H._normalize_language(name) in H.LANGUAGE_CONFIGS:
                shared.add(H._normalize_language(name))
        runtime = {H._normalize_language(k) for k in _lang_kw_sets()}
        self.assertEqual(shared - runtime, set(),
                         "these hash/c languages still fall back to the approximate bucket")


class SqlStringStyleTests(unittest.TestCase):
    """CMH-HL-15."""

    def test_the_runtime_sql_family_accepts_double_quoted_strings(self):
        branch = _family_branch(_read_runtime(), "sql")
        self.assertIsNotNone(branch, "runtime has no sql family branch")
        self.assertIn("dq", branch,
                      "the author-time sql config has string_styles sql_single + double, so the "
                      "runtime must accept a double-quoted identifier too")

    def test_the_author_time_sql_config_still_declares_both_styles(self):
        styles = set(H.LANGUAGE_CONFIGS["sql"].get("string_styles", ()))
        self.assertIn("double", styles)
        self.assertTrue({"sql_single", "single"} & styles)

    def test_dedicated_families_string_styles_are_spot_checked(self):
        # Any dedicated family whose author-time config declares a double-quoted style
        # must accept one at runtime; a divergence here is the CMH-HL-15 class.
        src = _read_runtime()
        for fam, lang in (("sql", "sql"), ("css", "css"), ("lua", "lua"),
                          ("powershell", "powershell"), ("haskell", "haskell")):
            cfg = H.LANGUAGE_CONFIGS.get(lang)
            if cfg is None or "double" not in set(cfg.get("string_styles", ())):
                continue
            m = _family_branch(src, fam)
            self.assertIsNotNone(m, "no runtime branch for %s" % fam)
            self.assertIn("dq", m,
                          "%s declares a double-quoted style at author time" % lang)


if __name__ == "__main__":
    unittest.main()
