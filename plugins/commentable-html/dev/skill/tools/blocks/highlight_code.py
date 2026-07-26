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
        "block_comments": (("/*", "*/"),),
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
    "markdown": {
        # Markdown is structural and line-oriented, not keyword-based, so it opts out of the shared
        # comment/string/keyword tokenizer and is highlighted by _highlight_markdown() below.
        "tokenizer": "markdown",
        "keywords": frozenset(),
        "line_comments": (),
        "block_comments": (),
        "string_styles": (),
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

# Languages whose object/mapping syntax makes a quoted string before a `:` a PROPERTY KEY rather than a
# value. They get an extra "key" token class so a JSON document reads the way every mainstream JSON
# highlighter renders it (key and value tinted differently) instead of as one wall of string tokens.
# Only JSON qualifies today: in JavaScript or Python a `"x":` can also be a slice/label/type context, so
# widening this set needs its own analysis rather than a blanket lookahead.
KEY_STRING_LANGUAGES = frozenset({"json"})

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
    "jsonc": "json",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "py": "python",
    "ts": "typescript",
    "tsx": "typescript",
    "md": "markdown",
    "mdown": "markdown",
    "mkd": "markdown",
}

_IDENTIFIER_RE = r"@?[A-Za-z_$][A-Za-z0-9_$]*"
_NUMBER_RE = r"\b(?:0[xX][0-9A-Fa-f_]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[A-Za-z0-9_]*)\b"
_OP_CHAR_RE = r"[=!<>+\-*/%&|^~?:;.,()\[\]{}#]"
_OP_RE = _OP_CHAR_RE + "+"
# A property KEY: the same unrolled double-quoted string as the "double" style, but with a REQUIRED
# closer and a following `:` (whitespace and newlines allowed between). The closer must be required
# here so an unterminated string cannot scan ahead and claim a later colon.
_KEY_STRING_RE = r'"[^"\\\n]*(?:\\[\s\S][^"\\\n]*)*"(?=\s*:)'
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
    # We allow multi-byte escapes (\u1234) but restrict unescaped content to exactly one char to avoid
    # swallowing Rust lifetimes (<'a>) or C++ digit separators (1'000'000).
    "char": r"'(?:\\[\s\S][^'\\\n]*|[^'\\\n])'",
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


def _op_pattern(config):
    """The operator run, guarded so it can never swallow this language's own comment opener.

    `_OP_RE` is greedy and several comment openers begin with an operator character (`/*`, `//`,
    `--`, `::`, `<#`, `{-`). Without the guard an operator that directly precedes a comment - with
    no whitespace between them - absorbs the opener, so the comment is never recognized at all:
    `{/* c */}` tokenized `{/*` as one operator and then highlighted the comment BODY as live code.
    The guard is built from the language's OWN comment prefixes, so a `//` that is not a comment
    (Python floor division) still tokenizes as an operator.
    """
    openers = [start for start, _end in config["block_comments"]]
    openers += [p for p in config["line_comments"] if p[:1] and not p[:1].isalnum()]
    if not openers:
        return _OP_RE
    guard = "(?!%s)" % "|".join(re.escape(p) for p in sorted(set(openers), key=len, reverse=True))
    return r"(?:%s%s)+" % (guard, _OP_CHAR_RE)


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
    if language in KEY_STRING_LANGUAGES:
        parts.append("(?P<key>%s)" % _KEY_STRING_RE)
    if strings:
        parts.append("(?P<str>%s)" % strings)
    parts.append("(?P<num>%s)" % _NUMBER_RE)
    if keywords:
        parts.append("(?P<kw>%s)" % keywords)
    parts.extend((
        "(?P<fn>%s(?=\\())" % _IDENTIFIER_RE,
        "(?P<ident>%s)" % _IDENTIFIER_RE,
        "(?P<op>%s)" % _op_pattern(config),
        r"(?P<ws>\s+)",
        r"(?P<other>.)",
    ))
    flags = re.IGNORECASE if language in CASE_INSENSITIVE_LANGUAGES else 0
    token_re = re.compile("|".join(parts), flags)
    _TOKEN_RE_CACHE[language] = token_re
    return token_re


# ---------------------------------------------------------------------------
# Markdown
#
# Markdown carries no keywords, so it gets its own line-oriented tokenizer. Block constructs are
# classified per line (with one carried-over state: an open fenced code block), then the remainder
# of a line runs through the inline scanner. The runtime mirror is cmhHighlightMarkdown() in
# assets/js/26-highlight.js; the two are pinned together by tests/fixtures/highlight_parity.json.
#
# Token mapping (reusing the six shipped classes): headings, setext underlines, bold and a fence
# info string -> kw; emphasis, strikethrough and HTML comments -> com; code spans, a fenced body
# whose info string names no known language, autolinks and link destinations -> str; link text,
# reference labels and footnote references -> fn; ordered-list numbers -> num; structural
# punctuation -> op. A fenced body WITH a known info-string language is BUFFERED and tokenized in
# that language as one unit when the fence closes (_md_fence_language, _md_fenced_body), so a
# construct spanning lines survives; markdown-in-markdown recurses through _MD_MAX_NESTING.
# ---------------------------------------------------------------------------

_MD_FENCE_RE = re.compile(r"([ \t]{0,3})(`{3,}|~{3,})([ \t]*)(.*)$")
_MD_HEADING_RE = re.compile(r"([ \t]{0,3})(#{1,6}(?:[ \t].*)?)$")
_MD_SETEXT_RE = re.compile(r"[ \t]{0,3}=+[ \t]*$")
# A dash run under a paragraph is a setext H2 underline, not a thematic break. A single `-` stays a
# list marker (an empty list item is far more common in a draft than a one-character underline).
_MD_SETEXT_DASH_RE = re.compile(r"[ \t]{0,3}-{2,}[ \t]*$")
_MD_BREAK_RE = re.compile(r"[ \t]{0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
# Each cell is `|`-terminated so no two whitespace runs are adjacent: an ambiguous
# `(?:\|[ \t]*:?-*:?[ \t]*)+` backtracks exponentially on a line of `|\t` repetitions (CodeQL
# "inefficient regular expression"), and this pattern runs on every line of every markdown block.
_MD_TABLE_RULE_RE = re.compile(r"[ \t]{0,3}\|?(?:[ \t]*:?-+:?[ \t]*\|)+(?:[ \t]*:?-+:?[ \t]*)?$")
_MD_LIST_RE = re.compile(r"([-*+]|\d{1,9}[.)])([ \t]+|$)")
_MD_TASK_RE = re.compile(r"\[[ xX]\](?=[ \t]|$)")
_MD_REFDEF_RE = re.compile(r"(\[)([^\]\n]+)(\]:)([ \t]*)([^ \t]+)(.*)$")
_MD_WORD_RE = re.compile(r"[A-Za-z0-9_]")
# How deep a ```markdown fence may nest inside a markdown block before its body is left opaque.
# Markdown is the only language whose tokenizer can re-enter itself, so this constant is what bounds
# the recursion an authored document can drive.
_MD_MAX_NESTING = 3
# Precedence matters: the first alternative that matches at the leftmost position wins, so a code
# span shields its contents from emphasis, and an autolink is tried before a generic inline tag.
# Every scan that could fail is LENGTH-CAPPED: an uncapped `[^\]\n]*` retried from each of 32k `[`
# characters is quadratic, and this tokenizer runs in the browser on authored content. A construct
# longer than its cap simply is not highlighted.
# Each emphasis form is spelled as a one-character and a two-or-more-character alternative so the
# character before the CLOSER can exclude a backslash: `**bold\**` has no valid closer (the first
# `*` is escaped) and must stay literal. Doing that with a lookbehind would be shorter but would
# throw at regex-construction time on Safari < 16.4 and take the whole layer down with it.
_MD_INLINE_RE = re.compile(
    r"(?P<esc>\\[\\`*_{}\[\]()#+.!|~>-])"
    r"|(?P<code>```[^\n]*?```|``[^\n]*?``|`[^`\n]+`)"
    r"|(?P<auto><[A-Za-z][A-Za-z0-9+.-]{0,30}:[^<>\s]{0,500}>|<[^<>\s@]{1,200}@[^<>\s]{1,200}>)"
    r"|(?P<htmlcom><!--[\s\S]*?(?:--!?>|$))"
    r"|(?P<tag></?[A-Za-z][^<>\n]{0,500}>)"
    r"|(?P<link>(?P<link_open>!?\[)(?P<link_text>[^\]\n]{0,200})(?P<link_mid>\]\()(?P<link_dest>[^)\n]{0,500})(?P<link_end>\)))"
    r"|(?P<ref>(?P<ref_open>!?\[)(?P<ref_text>[^\]\n]{0,200})(?P<ref_mid>\]\[)(?P<ref_label>[^\]\n]{0,200})(?P<ref_end>\]))"
    r"|(?P<note>\[\^[^\]\n]{1,200}\])"
    r"|(?P<strong>\*\*\*[^\s*\\]\*\*\*|\*\*\*[^\s*][^\n]{0,500}?[^\s*\\]\*\*\*"
    r"|___[^\s_\\]___|___[^\s_][^\n]{0,500}?[^\s_\\]___"
    r"|\*\*[^\s*\\]\*\*|\*\*[^\s*][^\n]{0,500}?[^\s*\\]\*\*"
    r"|__[^\s_\\]__|__[^\s_][^\n]{0,500}?[^\s_\\]__)"
    r"|(?P<strike>~~[^\s~\\]~~|~~[^\s~][^\n]{0,500}?[^\s~\\]~~)"
    r"|(?P<em>\*[^\s*\\]\*|\*[^\s*][^*\n]{0,500}?[^\s*\\]\*"
    r"|_[^\s_\\]_|_[^\s_][^_\n]{0,500}?[^\s_\\]_)"
    r"|(?P<pipe>\|)")
# HTML tolerates `--!>` as a comment terminator as well as `-->`.
_MD_COMMENT_ENDS = ("-->", "--!>")


def _md_comment_end(line):
    """(index, length) of the earliest HTML comment terminator in `line`, or (-1, 0)."""
    best, size = -1, 0
    for token in _MD_COMMENT_ENDS:
        at = line.find(token)
        if at >= 0 and (best < 0 or at < best):
            best, size = at, len(token)
    return best, size


def _md_word_at(text, index):
    return 0 <= index < len(text) and bool(_MD_WORD_RE.match(text[index]))


def _md_intraword(text, match):
    """True when an underscore-delimited emphasis run sits inside a word (some_long_name), where
    Markdown does not start emphasis."""
    if not match.group().startswith("_"):
        return False
    return _md_word_at(text, match.start() - 1) or _md_word_at(text, match.end())


def _md_inline_token(match, text, pipes):
    """The HTML for one inline match, or None to reject it and rescan from the next character."""
    if match.group("esc") is not None:
        return _esc(match.group())
    if match.group("code") is not None or match.group("auto") is not None:
        return _span("str", match.group())
    if match.group("htmlcom") is not None:
        return _span("com", match.group())
    if match.group("tag") is not None:
        return _span("op", match.group())
    if match.group("link") is not None:
        text_part, dest = match.group("link_text"), match.group("link_dest")
        return (_span("op", match.group("link_open"))
                + (_span("fn", text_part) if text_part else "")
                + _span("op", match.group("link_mid"))
                + (_span("str", dest) if dest else "")
                + _span("op", match.group("link_end")))
    if match.group("ref") is not None:
        text_part, label = match.group("ref_text"), match.group("ref_label")
        return (_span("op", match.group("ref_open"))
                + (_span("fn", text_part) if text_part else "")
                + _span("op", match.group("ref_mid"))
                + (_span("fn", label) if label else "")
                + _span("op", match.group("ref_end")))
    if match.group("note") is not None:
        return _span("fn", match.group())
    if match.group("strong") is not None:
        return None if _md_intraword(text, match) else _span("kw", match.group())
    if match.group("strike") is not None:
        return _span("com", match.group())
    if match.group("em") is not None:
        return None if _md_intraword(text, match) else _span("com", match.group())
    return _span("op", "|") if pipes else None


def _md_inline(text, pipes=False):
    """(html, open_comment) - open_comment is True when the line ends inside an unclosed HTML
    comment, so the caller can carry the comment across lines the way it carries a fence."""
    out = []
    pos = 0
    open_comment = False
    while pos < len(text):
        match = _MD_INLINE_RE.search(text, pos)
        if match is None:
            break
        if match.start() > pos:
            out.append(_esc(text[pos:match.start()]))
        rendered = _md_inline_token(match, text, pipes)
        if rendered is None:
            out.append(_esc(text[match.start()]))
            pos = match.start() + 1
            continue
        if match.group("htmlcom") is not None and not match.group().endswith(_MD_COMMENT_ENDS):
            open_comment = True
        out.append(rendered)
        pos = match.end()
    if pos < len(text):
        out.append(_esc(text[pos:]))
    return "".join(out), open_comment


def _md_closes_fence(line, char, length):
    body = line.lstrip(" \t")
    if len(line) - len(body) > 3:
        return False
    body = body.rstrip(" \t")
    return len(body) >= length and set(body) == {char}


def _md_prefixed(line):
    """(html, open_comment) - blockquote markers, a list marker and an optional task checkbox,
    then inline content."""
    out = []
    index, size = 0, len(line)
    while index < size and line[index] in " \t":
        index += 1
    out.append(_esc(line[:index]))
    while index < size and line[index] == ">":
        out.append(_span("op", ">"))
        index += 1
        start = index
        while index < size and line[index] in " \t":
            index += 1
        out.append(_esc(line[start:index]))
    match = _MD_LIST_RE.match(line, index)
    if match:
        marker = match.group(1)
        if marker[0].isdigit():
            out.append(_span("num", marker[:-1]))
            out.append(_span("op", marker[-1]))
        else:
            out.append(_span("op", marker))
        out.append(_esc(match.group(2)))
        index = match.end()
        task = _MD_TASK_RE.match(line, index)
        if task:
            out.append(_span("op", task.group()))
            index = task.end()
    rest = line[index:]
    refdef = _MD_REFDEF_RE.match(rest)
    if refdef and not refdef.group(2).startswith("^"):
        tail, open_comment = _md_inline(refdef.group(6))
        out.append(_span("op", refdef.group(1)))
        out.append(_span("fn", refdef.group(2)))
        out.append(_span("op", refdef.group(3)))
        out.append(_esc(refdef.group(4)))
        out.append(_span("str", refdef.group(5)))
        out.append(tail)
        return "".join(out), open_comment
    tail, open_comment = _md_inline(rest, rest.count("|") >= 2)
    out.append(tail)
    return "".join(out), open_comment


def _md_fence_language(info):
    """The language a fenced block's info string selects, or None when the label is unknown. Only
    the first word counts, so `python title="x.py"` still selects Python. The runtime mirror reads
    the SAME table (a drift guard keeps the two label sets identical), so both paths nest a fenced
    body for exactly the same set of info strings."""
    label = (info or "").strip(" \t").split(" ")[0].split("\t")[0]
    lang = _normalize_language(label)
    return lang if lang in LANGUAGE_CONFIGS else None


def _md_fenced_body(lang, lines, depth):
    """The html for a fenced block's buffered body lines. A body with a known language is tokenized
    as ONE unit so a multi-line construct (a C-style block comment, a Python triple-quoted string)
    reads exactly as it would in a standalone block of that language. Markdown is the one language
    that can nest into itself, so it recurses through a DEPTH BOUND: past it the body stays opaque,
    which keeps a hostile document (thousands of ```markdown openers) from exhausting the stack."""
    text = "\n".join(lines)
    if not text:
        return ""
    if LANGUAGE_CONFIGS[lang].get("tokenizer") == "markdown":
        if depth >= _MD_MAX_NESTING:
            return _span("str", text)
        return _highlight_markdown(text, depth + 1)
    return highlight_code(lang, text)


def _md_line(line, in_comment, prev_para):
    """(html, fence, in_comment, paragraph) for one line OUTSIDE a fenced block - the caller owns an
    open fence, because a fenced body is buffered and highlighted as a unit. `fence` is the
    (char, length, language) block this line OPENS, or None; `in_comment` is True while an HTML
    comment opened on an earlier line is still open; `prev_para` says whether the PREVIOUS line was
    plain paragraph text, which is what turns a dash run into a setext underline rather than a
    thematic break."""
    if in_comment:
        end, size = _md_comment_end(line)
        if end < 0:
            return (_span("com", line) if line else ""), None, True, False
        rest = line[end + size:]
        tail, still_open = _md_inline(rest, rest.count("|") >= 2)
        return _span("com", line[:end + size]) + tail, None, still_open, False
    match = _MD_FENCE_RE.match(line)
    if match and not (match.group(2)[0] == "`" and "`" in match.group(4)):
        info = match.group(4)
        html = (_esc(match.group(1)) + _span("op", match.group(2)) + _esc(match.group(3))
                + (_span("kw", info) if info else ""))
        opened = (match.group(2)[0], len(match.group(2)), _md_fence_language(info))
        return html, opened, False, False
    match = _MD_HEADING_RE.match(line)
    if match:
        return _esc(match.group(1)) + _span("kw", match.group(2)), None, False, False
    if prev_para and _MD_SETEXT_DASH_RE.match(line):
        return _span("kw", line), None, False, False
    if _MD_BREAK_RE.match(line):
        return _span("op", line), None, False, False
    if _MD_SETEXT_RE.match(line):
        return _span("kw", line), None, False, False
    if _MD_TABLE_RULE_RE.match(line):
        return _span("op", line), None, False, False
    indent = len(line) - len(line.lstrip(" \t"))
    paragraph = bool(line.strip()) and line[indent:indent + 1] != ">" and not _MD_LIST_RE.match(line, indent)
    html, open_comment = _md_prefixed(line)
    return html, None, open_comment, paragraph


def _highlight_markdown(src, depth=0):
    parts, fence, in_comment, para, body = [], None, False, False, []
    for line in src.split("\n"):
        if fence is not None:
            if _md_closes_fence(line, fence[0], fence[1]):
                if body:
                    parts.append(_md_fenced_body(fence[2], body, depth))
                    body = []
                parts.append(_span("op", line))
                fence = None
            elif fence[2]:
                # Buffered: the whole body is tokenized at once when the fence closes, so a nested
                # language's multi-line constructs survive.
                body.append(line)
            else:
                parts.append(_span("str", line) if line else "")
            para = False
            continue
        html, fence, in_comment, para = _md_line(line, in_comment, para)
        parts.append(html)
    if body:  # an unterminated fence still renders its body
        parts.append(_md_fenced_body(fence[2], body, depth))
    return "\n".join(parts)


def highlight_code(language, code):
    """Return escaped code with token spans and no wrapper."""
    src = _normalize_code(code)
    lang = _normalize_language(language)
    if lang not in LANGUAGE_CONFIGS:
        return _esc(src)
    if LANGUAGE_CONFIGS[lang].get("tokenizer") == "markdown":
        return _highlight_markdown(src)
    out = []
    for match in _token_re(lang).finditer(src):
        kind = match.lastgroup
        text = match.group()
        if kind in {"kw", "fn", "str", "num", "op", "key"}:
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
