#!/usr/bin/env python3
"""Author-time syntax highlighter for static commentable-html reports."""
import argparse
import html as _html
import os
import re
import sys


def _words(text):
    return frozenset(text.split())


LANGUAGE_CONFIGS = {
    "python": {
        "keywords": _words("""
False None True and as assert async await break class continue def del elif else
except finally for from global if import in is lambda nonlocal not or pass raise
return try while with yield
"""),
        "line_comments": ("#",),
        "block_comments": (),
        "string_styles": ("triple_double", "triple_single", "single", "double"),
    },
    "javascript": {
        "keywords": _words("""
async await break case catch class const continue debugger default delete do else
export extends false finally for from function get if import in instanceof let new
null of return set static super switch this throw true try typeof undefined var
void while with yield
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double", "backtick"),
    },
    "typescript": {
        "keywords": _words("""
abstract any as asserts async await bigint boolean break case catch class const
continue debugger declare default delete do else enum export extends false finally
for from function get if implements import in infer instanceof interface is keyof
let module namespace never new null number object of private protected public
readonly require return set static string super switch symbol this throw true try
type typeof undefined unique unknown var void while with yield
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double", "backtick"),
    },
    "json": {
        "keywords": _words("false null true"),
        "line_comments": ("//",),
        "block_comments": (),
        "string_styles": ("double",),
    },
    "bash": {
        "keywords": _words("""
case coproc do done elif else esac fi for function if in select then time until
while
"""),
        "line_comments": ("#",),
        "block_comments": (),
        "string_styles": ("single", "double", "backtick"),
    },
    "sql": {
        "keywords": _words("""
all alter and as asc between by case cast create cross delete desc distinct drop
else end exists false from full group having in inner insert into is join left
like limit not null on or order outer right select set table then true union
update values when where with
"""),
        "line_comments": ("--",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("sql_single", "double"),
    },
    "csharp": {
        "keywords": _words("""
abstract as base bool break byte case catch char checked class const continue
decimal default delegate do double else enum event explicit extern false finally
fixed float for foreach goto if implicit in int interface internal is lock long
namespace new null object operator out override params private protected public
readonly ref return sbyte sealed short sizeof stackalloc static string struct
switch this throw true try typeof uint ulong unchecked unsafe ushort using var
virtual void volatile while
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("csharp_verbatim", "single", "double"),
    },
    "java": {
        "keywords": _words("""
abstract assert boolean break byte case catch char class const continue default
do double else enum extends false final finally float for goto if implements
import instanceof int interface long native new null package private protected
public return short static strictfp super switch synchronized this throw throws
transient true try void volatile while
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double"),
    },
    "go": {
        "keywords": _words("""
break case chan const continue default defer else fallthrough false for func go
goto if import interface iota map nil package range return select struct switch
true type var
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double", "backtick"),
    },
    "yaml": {
        "keywords": _words("false False FALSE null Null NULL true True TRUE yes no on off"),
        "line_comments": ("#",),
        "block_comments": (),
        "string_styles": ("single", "double"),
    },
    "c": {
        "keywords": _words("""
auto break case char const continue default do double else enum extern float for
goto if inline int long register restrict return short signed sizeof static
struct switch typedef union unsigned void volatile while
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double"),
    },
    "cpp": {
        "keywords": _words("""
alignas alignof and asm auto bool break case catch char class const constexpr
continue decltype default delete do double else enum explicit export extern false
float for friend goto if inline int long mutable namespace new noexcept not null
nullptr operator or private protected public register reinterpret_cast requires
return short signed sizeof static static_cast struct switch template this throw
true try typedef typename union unsigned using virtual void volatile while
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double"),
    },
    "xml": {
        "keywords": _words("xml version encoding root item node element"),
        "line_comments": (),
        "block_comments": (("<!--", "-->"),),
        "string_styles": ("single", "double"),
    },
    "html": {
        "keywords": _words("""
a article body button code div footer h1 h2 h3 head header html img input label
li link main meta nav ol option p pre script section select span style table tbody
td template textarea th thead title tr ul
"""),
        "line_comments": (),
        "block_comments": (("<!--", "-->"),),
        "string_styles": ("single", "double"),
    },
}

ALIASES = {
    "sh": "bash",
    "shell": "bash",
    "cs": "csharp",
    "golang": "go",
    "yml": "yaml",
    "c++": "cpp",
}

_IDENTIFIER_RE = r"@?[A-Za-z_$][A-Za-z0-9_$]*"
_NUMBER_RE = r"\b(?:0[xX][0-9A-Fa-f_]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[A-Za-z0-9_]*)\b"
_OP_RE = r"[=!<>+\-*/%&|^~?:;.,()\[\]{}#]+"
_TOKEN_RE_CACHE = {}

_STRING_PATTERNS = {
    "triple_double": r'"""[\s\S]*?"""',
    "triple_single": r"'''[\s\S]*?'''",
    "csharp_verbatim": r'@"(?:[^"]|"")*"',
    "sql_single": r"'(?:[^']|'')*'",
    "single": r"'(?:[^'\\\n]|\\.)*'",
    "double": r'"(?:[^"\\\n]|\\.)*"',
    "backtick": r"`(?:[^`\\]|\\.)*`",
}


def _normalize_code(code):
    return code.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_language(language):
    lang = (language or "").strip().lower()
    return ALIASES.get(lang, lang)


def _class_language(language):
    lang = _normalize_language(language) or "text"
    return re.sub(r"[^A-Za-z0-9_+.-]+", "-", lang)


def _esc(text):
    return _html.escape(text, quote=False)


def _span(kind, text):
    return '<span class="cmh-code-%s">%s</span>' % (kind, _esc(text))


def _comment_pattern(config):
    parts = []
    for start, end in config["block_comments"]:
        parts.append(re.escape(start) + r"[\s\S]*?" + re.escape(end))
    if config["line_comments"]:
        prefixes = sorted((re.escape(p) for p in config["line_comments"]), key=len, reverse=True)
        parts.append(r"(?:%s)[^\n]*" % "|".join(prefixes))
    return "|".join(parts)


def _string_pattern(config):
    return "|".join(_STRING_PATTERNS[name] for name in config["string_styles"])


def _keyword_pattern(config):
    keywords = sorted((re.escape(k) for k in config["keywords"]), key=len, reverse=True)
    if not keywords:
        return ""
    return r"(?<![A-Za-z0-9_$])(?:%s)(?![A-Za-z0-9_$])" % "|".join(keywords)


def _token_re(language):
    if language in _TOKEN_RE_CACHE:
        return _TOKEN_RE_CACHE[language]
    config = LANGUAGE_CONFIGS[language]
    parts = []
    comments = _comment_pattern(config)
    strings = _string_pattern(config)
    keywords = _keyword_pattern(config)
    if comments:
        parts.append("(?P<com>%s)" % comments)
    if strings:
        parts.append("(?P<str>%s)" % strings)
    parts.append("(?P<num>%s)" % _NUMBER_RE)
    if keywords:
        parts.append("(?P<kw>%s)" % keywords)
    parts.extend((
        "(?P<fn>%s(?=\\())" % _IDENTIFIER_RE,
        "(?P<ident>%s)" % _IDENTIFIER_RE,
        "(?P<op>%s)" % _OP_RE,
        r"(?P<ws>\s+)",
        r"(?P<other>.)",
    ))
    token_re = re.compile("|".join(parts), re.IGNORECASE)
    _TOKEN_RE_CACHE[language] = token_re
    return token_re


def highlight_code(language, code):
    """Return escaped code with token spans and no wrapper."""
    src = _normalize_code(code)
    lang = _normalize_language(language)
    if lang not in LANGUAGE_CONFIGS:
        return _esc(src)
    out = []
    for match in _token_re(lang).finditer(src):
        kind = match.lastgroup
        text = match.group()
        if kind in {"kw", "fn", "str", "num", "op"}:
            out.append(_span(kind, text))
        elif kind == "com":
            out.append(_span("com", text))
        else:
            out.append(_esc(text))
    return "".join(out)


def highlight_block(language, code):
    """Return a highlighted pre/code block."""
    lang = _html.escape(_class_language(language), quote=True)
    return '<pre><code class="language-%s">%s</code></pre>' % (lang, highlight_code(language, code))


def supported_languages():
    return sorted(set(LANGUAGE_CONFIGS) | set(ALIASES))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Highlight code for commentable-html reports.")
    parser.add_argument("--list", action="store_true", help="print supported languages")
    parser.add_argument("language", nargs="?")
    parser.add_argument("code", nargs="?")
    args = parser.parse_args(argv)
    if args.list:
        sys.stdout.write(os.linesep.join(supported_languages()) + os.linesep)
        return 0
    if not args.language:
        parser.error("language is required unless --list is used")
    code = args.code
    if code is None:
        code = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    sys.stdout.write(highlight_block(args.language, code))
    return 0


if __name__ == "__main__":
    sys.exit(main())
