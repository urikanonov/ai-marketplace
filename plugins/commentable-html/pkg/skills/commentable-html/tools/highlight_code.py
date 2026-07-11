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
        "keywords": _words("false False FALSE null Null NULL true True TRUE yes Yes YES no No NO on On ON off Off OFF"),
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
    "rust": {
        "keywords": _words("""
as async await break const continue crate dyn else enum extern false fn for if
impl in let loop match mod move mut pub ref return self Self static struct super
trait true type union unsafe use where while
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double"),
    },
    "ruby": {
        "keywords": _words("""
BEGIN END alias and begin break case class def defined do else elsif end ensure
false for if in module next nil not or redo rescue retry return self super then
true undef unless until when while yield
"""),
        "line_comments": ("#",),
        "block_comments": (),
        "string_styles": ("single", "double", "backtick"),
    },
    "php": {
        "keywords": _words("""
abstract and array as break callable case catch class clone const continue declare
default do echo else elseif empty enddeclare endfor endforeach endif endswitch
endwhile enum extends false final finally fn for foreach function global goto if
implements include include_once instanceof insteadof interface isset list match
namespace new null or print private protected public readonly require require_once
return static switch throw trait true try unset use var while xor yield
"""),
        "line_comments": ("//", "#"),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double"),
    },
    "swift": {
        "keywords": _words("""
as associatedtype break case catch class continue default defer deinit do else
enum extension fallthrough false fileprivate for func guard if import in init inout
internal is let nil open operator private protocol public repeat rethrows return
self Self static struct subscript super switch throw throws true try typealias var
where while
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("triple_double", "double"),
    },
    "kotlin": {
        "keywords": _words("""
abstract actual annotation as break by catch class companion const constructor
continue crossinline data delegate do dynamic else enum external false final finally
for fun get if import in infix init inline inner interface internal is lateinit lazy
noinline null object open operator out override package private protected public
reified return sealed super suspend this throw true try typealias typeof val var
vararg when where while
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("triple_double", "double"),
    },
    "scala": {
        "keywords": _words("""
abstract case catch class def do else extends false final finally for forSome if
implicit import lazy match new null object override package private protected return
sealed super this throw trait true try type val var while with yield
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("triple_double", "double"),
    },
    "dart": {
        "keywords": _words("""
abstract as assert async await break case catch class const continue covariant
default deferred do dynamic else enum export extends extension external factory
false final finally for get hide if implements import in interface is late library
mixin new null on operator part required rethrow return set show static super switch
sync this throw true try typedef var void while with yield
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("triple_double", "triple_single", "single", "double"),
    },
    "r": {
        "keywords": _words("""
break else for function if in next repeat while TRUE FALSE NULL Inf NaN NA
NA_integer_ NA_real_ NA_character_ NA_complex_
"""),
        "line_comments": ("#",),
        "block_comments": (),
        "string_styles": ("single", "double"),
    },
    "perl": {
        "keywords": _words("""
and cmp do else elsif eq for foreach ge gt if last le local lt my ne next no not
or our package redo require return sub unless until use while x
"""),
        "line_comments": ("#",),
        "block_comments": (),
        "string_styles": ("single", "double", "backtick"),
    },
    "powershell": {
        "keywords": _words("""
begin break catch class continue data default do dynamicparam else elseif end enum
exit filter finally for foreach from function hidden if in param process return
static switch throw trap try until using while
"""),
        "line_comments": ("#",),
        "block_comments": (("<#", "#>"),),
        "string_styles": ("single", "double"),
    },
    "lua": {
        "keywords": _words("""
and break do else elseif end false for function goto if in local nil not or repeat
return then true until while
"""),
        "line_comments": ("--",),
        "block_comments": (("--[[", "]]"),),
        "string_styles": ("single", "double"),
    },
    "toml": {
        "keywords": _words("true false"),
        "line_comments": ("#",),
        "block_comments": (),
        "string_styles": ("triple_double", "triple_single", "toml_single_literal", "double"),
    },
    "css": {
        "keywords": _words("auto important inherit initial none unset revert"),
        "line_comments": (),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double"),
    },
    "groovy": {
        "keywords": _words("""
abstract as assert boolean break byte case catch char class const continue def
default do double else enum extends false final finally float for goto if implements
import in instanceof int interface long native new null package private protected
public return short static strictfp super switch synchronized this throw throws
trait transient true try void volatile while
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("triple_double", "triple_single", "single", "double"),
    },
    "elixir": {
        "keywords": _words("""
after and case catch cond def defmacro defmodule defp defstruct do else end false
fn for if import in nil not or quote raise receive require rescue true try unless
unquote use when with
"""),
        "line_comments": ("#",),
        "block_comments": (),
        "string_styles": ("triple_double", "double"),
    },
    "haskell": {
        "keywords": _words("""
as case class data default deriving do else foreign hiding if import in infix infixl
infixr instance let module newtype of qualified then type where
"""),
        "line_comments": ("--",),
        "block_comments": (("{-", "-}"),),
        "string_styles": ("double",),
    },
    "objectivec": {
        "keywords": _words("""
auto break case char const continue default do double else enum extern float for
goto if inline int long register return short signed sizeof static struct switch
typedef union unsigned void volatile while id nil BOOL YES NO self super @interface
@implementation @end @property @synthesize @protocol @class @selector @encode
@synchronized @autoreleasepool @try @catch @finally @throw
"""),
        "line_comments": ("//",),
        "block_comments": (("/*", "*/"),),
        "string_styles": ("single", "double"),
    },
    "batch": {
        "keywords": _words("""
call cd cls copy defined del do echo else endlocal errorlevel exist exit for goto
if in md move not pause popd pushd rd ren set setlocal shift start title type
"""),
        "line_comments": ("rem", "::"),
        "block_comments": (),
        "string_styles": ("double",),
    },
}

# Languages whose keywords are genuinely case-insensitive. Only these compile their
# tokenizer with re.IGNORECASE; every other language matches keywords case-sensitively
# so an identifier like C# `String`, Python `true`, or Rust `Fn` is not mis-colored as a
# keyword. (Numbers/strings/identifiers use case-explicit patterns, so they are unaffected.)
CASE_INSENSITIVE_LANGUAGES = frozenset({"sql", "batch", "powershell", "html", "css"})

# Languages where a single quote delimits a CHAR / rune literal (one character), not a multi-character
# string. They use the "char" string style so a Rust lifetime (<'a>), a digit separator (1'000), or any
# other lone ' is never mis-highlighted as a string. The swap is applied here in one place.
CHAR_LITERAL_LANGUAGES = ("c", "cpp", "csharp", "java", "go", "rust", "objectivec")
for _lang in CHAR_LITERAL_LANGUAGES:
    LANGUAGE_CONFIGS[_lang]["string_styles"] = tuple(
        "char" if _style == "single" else _style
        for _style in LANGUAGE_CONFIGS[_lang]["string_styles"])

ALIASES = {
    "sh": "bash",
    "shell": "bash",
    "cs": "csharp",
    "golang": "go",
    "yml": "yaml",
    "c++": "cpp",
    "rs": "rust",
    "rb": "ruby",
    "kt": "kotlin",
    "pl": "perl",
    "ps1": "powershell",
    "ps": "powershell",
    "objc": "objectivec",
    "hs": "haskell",
    "ex": "elixir",
    "exs": "elixir",
    "bat": "batch",
    "cmd": "batch",
}

_IDENTIFIER_RE = r"@?[A-Za-z_$][A-Za-z0-9_$]*"
_NUMBER_RE = r"\b(?:0[xX][0-9A-Fa-f_]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[A-Za-z0-9_]*)\b"
_OP_RE = r"[=!<>+\-*/%&|^~?:;.,()\[\]{}#]+"
_TOKEN_RE_CACHE = {}

_STRING_PATTERNS = {
    # A closing delimiter is OPTIONAL for styles whose delimiter is (almost) never used as a non-string
    # sigil - double quote, backtick, both triple-quote forms, and @"..." verbatim - so an unterminated
    # one highlights to end of line / input without eating valid code. SINGLE-quote string styles REQUIRE
    # their closer, because a lone ' is common in real code (YAML apostrophes like don't, single-quoted
    # scalars) and an optional closer there would swallow the rest of the line as a string.
    "triple_double": r'"""[\s\S]*?(?:"""|\Z)',
    "triple_single": r"'''[\s\S]*?(?:'''|\Z)",
    "csharp_verbatim": r'@"[^"]*(?:""[^"]*)*"?',
    "sql_single": r"'[^']*(?:''[^']*)*'",
    "toml_single_literal": r"'[^'\n]*'",
    # A single character or escape between single quotes - a C/C++/C#/Java/Go/Rust char or rune literal.
    # It cannot match a Rust lifetime (<'a>) or a digit separator (1'000) because those are not `'x'`.
    "char": r"'(?:\\[\s\S]|[^'\\\n])'",
    # Unrolled (linear-time) loop so pathological escaped-quote input cannot backtrack; \\[\s\S]
    # keeps a backslash-newline line continuation inside the string.
    "single": r"'[^'\\\n]*(?:\\[\s\S][^'\\\n]*)*'",
    "double": r'"[^"\\\n]*(?:\\[\s\S][^"\\\n]*)*"?',
    "backtick": r"`[^`\\]*(?:\\[\s\S][^`\\]*)*`?",
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
        # An unterminated block comment (a partial snippet) still highlights to end of input
        # via the |\Z fallback. Nested block comments (e.g. Haskell {- {- -} -}) are NOT
        # supported: stdlib re has no recursion, so the first close ends the comment.
        parts.append(re.escape(start) + r"[\s\S]*?(?:" + re.escape(end) + r"|\Z)")
    if config["line_comments"]:
        prefixes = []
        for prefix in sorted(config["line_comments"], key=len, reverse=True):
            escaped = re.escape(prefix)
            # A word-like prefix (e.g. batch `rem`) needs a trailing boundary so it matches
            # `rem `, `rem<TAB>`, or a bare `rem` at end-of-line, but never `remark`.
            if prefix[-1:].isalnum():
                escaped += r"\b"
            prefixes.append(escaped)
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
    flags = re.IGNORECASE if language in CASE_INSENSITIVE_LANGUAGES else 0
    token_re = re.compile("|".join(parts), flags)
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
