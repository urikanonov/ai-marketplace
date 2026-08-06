#!/usr/bin/env python3
"""CMH-BUILD-22: pin the three media load-attribute lists to each other.

WHICH `(tag, attribute)` pairs a browser FETCHES on open is a single contract implemented three
times, on three surfaces that never import one another:

- the strict layer gate's `_MEDIA_LOAD_ATTRS` (plus its core `img` / `script` / `iframe` / `link` /
  `base` groups, the type-gated `<input type=image>` and the universal `background` attribute), in
  `skill/tools/validate/checks/layer_parts/20-resources.py`,
- the deck gate's `_EGRESS_ATTRS` / `_EGRESS_ANY_ATTRS`, in `skill/tools/deck/deck_validate.py`,
- the offline exporter's per-selector strip passes, in `assets/js/68-export-offline.js`.

Every past widening of that contract (#992 `feImage`, #961 the CSS patterns, #1165 `<image src>`)
was found by a human or a review panel noticing a missing pair, one spelling at a time. This test
turns that into a mechanical check: it READS the three lists from their real sources and asserts the
stated relationship between them, so a widening that lands on one side only fails here instead of
being discovered by the next spelling.

The relationship, stated once (issue #1179):

1. EXPORTER >= LAYER. Every pair the layer gate reports has a strip that clears it, so the gate can
   never reject a file the offline export just produced. That is the CMH-OFFLINE-04 drift direction
   that actually costs a user something.
2. DECK == LAYER on the tags a deck may carry. A deck is validated by the deck gate and, outside
   descriptor mode `offline`, by nothing else, so a pair the layer knows about and the deck does not
   is a live egress hole (that is how `feImage` went missing from the deck for the whole life of
   #992), and a pair the DECK knows about and the layer does not is either a hole in the far larger
   shareable/offline surface or - the `lowsrc` case - a rule no engine has needed since before this
   project existed.

Every INTENTIONAL difference is named below as data with a reason, never silently excluded: a
difference that is not in one of these tables fails the test.

WHAT THIS TEST DOES NOT CLAIM, stated so nobody reads it as more than it is:

- It proves the three lists AGREE, not that they are COMPLETE against what a browser really
  fetches. A pair all three miss (the `<link rel=preload as=image imagesrcset>` residual
  CMH-VAL-08 records, closed on the offline-scoped reasoning of #999) passes here cleanly.
  Completeness is a question for the threat model and for measurement, not for a parity check.
- It compares the (tag, attribute) SETS, not the predicates each surface applies to a value. Where
  two surfaces ask a different question about the same pair, that is recorded in
  `SHAPE_DIFFERENCES` rather than reconciled.
- The two non-pair egress contracts - a `<meta http-equiv=refresh>` and the CSS `url()`/`@import`
  reads (#961) - are outside the comparison, because neither is keyed on a (tag, attribute) pair.
  They are pinned by their own tests, named in `EXPORT_EXTRA_STRIPS`. Note what the CSS reads
  do NOT cover: an SVG PRESENTATION ATTRIBUTE (`<rect mask="url(https://...)">`) is neither a
  (tag, attribute) pair in this contract nor part of a stylesheet the CSS reads inspect, and
  `clip-path` / `mask` really do fetch (measured in Chromium; `filter` does not) - tracked as
  issue #1186, and named here so nobody reads this comparison as covering it.
- The exporter side proves a pass EXISTS for a pair, not that the pass works. What each strip
  actually does to a document is pinned by the offline-export Playwright suite
  (`tests/49-offline-export.spec.js`, CMH-OFFLINE-04).

The two Python lists are read from the built STAGE (`dev/skill/...`) and the exporter from its
pre-build source (`dev/assets/js/...`) because that is where each one is EDITED; `build.py --check`
gates the stage against those sources, so the two trees cannot disagree.
"""
import bisect
import glob
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

sys.path.insert(0, os.path.join(_paths.TOOLS, "validate"))
sys.path.insert(0, _paths.DECK)
from checks import layer  # noqa: E402  the strict gate's own pair list, read not restated
from checks import resources  # noqa: E402  SCRIPT_LOAD_ATTRS
import deck_validate  # noqa: E402

EXPORT_OFFLINE = os.path.join(_paths.ASSETS, "js", "68-export-offline.js")
LAYER_PARTS = os.path.join(_paths.TOOLS, "validate", "checks", "layer_parts")

# The universal (tag-less) attribute question both gates ask: a pair keyed on the ATTRIBUTE alone,
# because the exporter's own selector is universal (`[background]`) and any tag list is narrower
# than it. Represented as the tag `*` so the three sets stay comparable.
ANY_TAG = "*"
# The attributes whose EXPORT strip is genuinely universal, so a `*` strip may satisfy a tag-keyed
# layer pair. Kept explicit rather than accepting any `*` strip (see `_export_has`).
UNIVERSAL_STRIP_ATTRS = frozenset({"background"})

# The layer gate's CORE groups, which live as literals in the check body rather than in a list this
# test can import. Frozen here (the `EXPECTED_REQUIRED_IDS` pattern) and cross-checked BEHAVIORALLY
# by `test_the_frozen_core_groups_are_really_enforced`, so this table cannot quietly drift away from
# what the gate does.
LAYER_CORE_PAIRS = frozenset(
    {("img", "src"), ("img", "srcset"), ("iframe", "src"), ("link", "href"), ("base", "href"),
     ("input", "src"), (ANY_TAG, "background")}
    | {("script", attr) for attr in resources.SCRIPT_LOAD_ATTRS})

# Pairs the LAYER gate enforces that the DECK gate deliberately does not carry in its egress index.
# Each names the deck rule that covers the same ground, so "the deck has no rule for this" can never
# be mistaken for "the deck lets this through".
DECK_COVERED_ELSEWHERE = {
    ("script", "src"): "the deck rejects any external <script src/href/xlink:href> outright",
    ("script", "href"): "the deck rejects any external <script src/href/xlink:href> outright",
    ("script", "xlink:href"): "the deck rejects any external <script src/href/xlink:href> outright",
}

# Tags the DECK bans as ELEMENTS (`_ACTIVE_TAGS`), so its egress rule for them is belt-and-braces
# rather than the thing that catches them. Named because the deck's index carries them anyway and a
# reader should not have to re-derive why.
DECK_BANNED_TAGS = {
    "iframe": "an <iframe> is rejected as an element, whatever it points at",
    "object": "an <object> is rejected as an element, whatever it points at",
    "embed": "an <embed> is rejected as an element, whatever it points at",
}

# Differences in the SHAPE of a shared pair (both sides carry it; they ask a different question).
# Recorded rather than reconciled, with the reason each side is right where it stands. This is the
# declared LIMIT of the pair-set comparison: the three surfaces agree on WHICH pairs load, and each
# is free to answer "is this value remote" its own way.
SHAPE_DIFFERENCES = {
    ("input", "src"): (
        "the layer gate reads an <input src> only when `type=image` (the only type that fetches), "
        "while the deck gate reads every <input src>: the deck is a generated artifact with no "
        "legitimate <input> at all, so over-detection there costs an author nothing"),
    ("link", "href"): (
        "the layer gate reads a <link href> only when its REL fetches (`_link_loads`) and reports "
        "it as a WARNING in shareable mode, while the deck gate reads every <link href> as an "
        "error; the deck's own contract allows a local <link> only, so the rel question never "
        "arises there"),
    ("base", "href"): (
        "the layer gate holds a <base href> to the stricter `offline_is_non_local_ref` (ANY scheme "
        "or a two-slash authority) because a base REBASES every relative reference in the "
        "document, while the deck gate asks its ordinary remote-URL question"),
    (ANY_TAG, ANY_TAG): (
        "GLOBAL, not per pair: the deck gate scans every AUTHORED attribute (a duplicate included, "
        "since a duplicate is still something an author must clean up), while the layer gate and "
        "the DOM the exporter walks resolve duplicates the way a browser does, first wins"),
}

# Tags the layer gate's own source reads that are NOT automatic-subresource loads, so they are
# deliberately outside the pair set. Named here because `test_the_layer_gates_source_names_no_"
# "unclassified_rule` reads those literals out of the check body and refuses an unclassified one.
LAYER_TAGS_NOT_SUBRESOURCE = {
    "meta": "a <meta http-equiv=refresh> is a redirect rule decided by its CONTENT, not a "
            "(tag, attribute) subresource load",
    "form": "a form target is USER-INITIATED egress (it needs a submit), deliberately out of the "
            "self-contained scope and offline-only for export-strip parity",
}
LAYER_PAIRS_NOT_SUBRESOURCE = {
    ("form", "action"): "user-initiated egress: a form POST needs a submit",
}
# Attributes the layer gate checks through the universal `_find_attr_egress` question or through a
# DYNAMIC-tag `_check_network_attr` call, which are therefore classified by attribute rather than
# by pair. Same rule as the two tables above: a new one has to be classified here or be a real pair.
LAYER_ATTRS_NOT_SUBRESOURCE = {
    "formaction": "user-initiated egress: a form POST needs a submit (checked on a dynamic tag, "
                  "so it is classified by attribute rather than by pair)",
}

# The exporter reaches some pairs through a DIFFERENT selector than the tag name, because the DOM it
# walks is not the token stream the gates read. Each entry maps a layer pair to the strip that
# really clears it.
EXPORT_SELECTOR_ALIASES = {
    # `HTMLParser` lowercases a tag name, so the gates key on `feimage` while the exporter's CSS
    # selector must spell it `feImage` to match in both namespaces (#992).
    ("feimage", "href"): ("feImage", "href"),
    ("feimage", "xlink:href"): ("feImage", "xlink:href"),
}
# `<image>` needs no alias, and that is worth stating rather than leaving as an absence: HTML tree
# construction renames an `<image>` start tag to `img`, so the HTML spelling is cleared by the
# exporter's `all("img")` pass, and `all("image")` - which reaches only the SVG-namespaced element -
# clears the same four attributes anyway, so neither side can reject what the other leaves (#1165).

# Strips the exporter runs that no gate pair maps onto. Every one is a rule of its own, named here
# so this test's exporter reading can be exhaustive without pretending these are media loads.
EXPORT_EXTRA_STRIPS = {
    ("a", "ping"): "hyperlink auditing - a click POSTs, so it is not a load on open",
    ("area", "ping"): "hyperlink auditing - a click POSTs, so it is not a load on open",
    ("form", "action"): "user-initiated egress: a form POST needs a submit",
    ("button", "formaction"): "user-initiated egress: a form POST needs a submit",
    ("input", "formaction"): "user-initiated egress: a form POST needs a submit",
    ("meta", "http-equiv"): "a meta refresh navigates; it is a redirect rule, not a subresource",
    ("iframe", "srcdoc"): "a nested DOCUMENT, removed unconditionally (#996), not a URL attribute",
    ("link", "rel"): "the speculative-connection hint rels, dropped on the REL alone (#1076)",
    (ANY_TAG, "referrerpolicy"): "a per-element referrer override, not itself a fetch",
    (ANY_TAG, "style"): "CSS egress, read through the shared url()/@import patterns",
}


def _layer_pairs():
    """Every `(tag, attr)` the strict layer gate reports as an automatic subresource load."""
    pairs = {(tag, attr) for tag, attr, _is_srcset in layer._MEDIA_LOAD_ATTRS}
    pairs |= LAYER_CORE_PAIRS
    return frozenset(pairs)


def _deck_pairs():
    """Every `(tag, attr)` the deck gate REACHES as egress, universal attributes under `*`.

    Reachability, not declaration: `_ActiveContentScanner._scan` filters on `_URL_ATTRS` BEFORE it
    consults `_EGRESS_ATTRS`, so an entry in the egress index whose attribute is not also a URL
    attribute is DEAD - the scan skips it. Counting a declared-but-dead entry as covered would let
    a widening that landed in only one of the deck's two lists read as done, which is the same
    one-sided landing this whole test exists to catch (`test_the_decks_own_two_lists_agree` fails
    loudly on it rather than leaving it to show up as a confusing absence here).
    """
    declared = {(tag, attr) for tag, attrs in deck_validate._EGRESS_ATTRS.items() for attr in attrs}
    declared |= {(ANY_TAG, attr) for attr in deck_validate._EGRESS_ANY_ATTRS}
    return frozenset(pair for pair in declared if _deck_reaches(pair[1]))


def _deck_reaches(attr):
    return attr == "srcset" or attr in deck_validate._URL_ATTRS


def _layer_source_rules():
    """The tag, attribute and `(tag, attr)` literals the layer gate's own source names.

    `_layer_pairs()` is built from an importable list plus a FROZEN table, so on its own it can only
    prove the pairs it already knows about. This reads the check bodies instead, so a NEW inline
    rule (which is where every past widening landed - `<input type=image>`, the universal
    `background`, `base`) has to be classified before the parity assertions can pass, rather than
    being invisible to all three of them.

    Every `layer_parts/*.py` is read, not just the one that carries the rules today, and all three
    idioms the gate uses are recognized: the TAG question (`_find_tag_attrs_egress`), the universal
    ATTRIBUTE question (`_find_attr_egress`, whose argument is a module constant that is resolved
    through the imported module), and the per-attribute check itself (`_check_network_attr`, whose
    tag is often a loop VARIABLE - those contribute the attribute alone rather than a pair, which
    is what stops a dynamic-tag rule from being invisible).
    """
    tags, attrs, pairs = set(), set(), set()
    for path in sorted(glob.glob(os.path.join(LAYER_PARTS, "*.py"))):
        with open(path, encoding="utf-8") as handle:
            src = handle.read()
        tags |= set(re.findall(r'_find_tag_attrs_egress\(\s*\w+\s*,\s*["\']([^"\']+)["\']', src))
        for arg in re.findall(r"_find_attr_egress\(\s*\w+\s*,\s*([^)\s]+)\s*\)", src):
            value = arg.strip("\"'") if arg[:1] in "\"'" else getattr(layer, arg, None)
            attrs.add(value if isinstance(value, str) else arg)
        pairs |= set(re.findall(
            r'_check_network_attr\(\s*["\']([^"\']+)["\']\s*,\s*[^,]+,\s*["\']([^"\']+)["\']', src))
        attrs |= set(re.findall(
            r'_check_network_attr\(\s*(?!["\'])[^,]+,\s*[^,]+,\s*["\']([^"\']+)["\']', src))
    return frozenset(tags), frozenset(attrs), frozenset(pairs)


_ALL_CALL_RE = re.compile(r'all\((["\'])(.+?)\1\)')
_CLEAR_RE = re.compile(r'(?:clearAttr\(\w+,\s*|removeAttribute\()(["\'])([^"\']+)\1')
# An element REMOVAL neutralizes every attribute the selector filtered on, so a block that removes
# the element counts as stripping its selector's presence predicates (`link[href]` and
# `meta[http-equiv]` are cleared exactly that way - the block never touches the attribute). It must
# be the WALKED element's own removal: any `.remove()` would let an unrelated call (a `Set` delete,
# a class-list removal) fabricate coverage for a pass that clears nothing.
_FOREACH_PARAM_RE = re.compile(r"forEach\(\s*(?:function\s*\(\s*(\w+)|\(?\s*(\w+)\s*\)?\s*=>)")
# The one strip pass that does not clear its attributes inline: a `<script>` load is judged by
# TYPE and namespace, so the walk hands each element to a helper. Its body is read as part of the
# block, which keeps this reading derived from the real code rather than from a claim about it.
_EXPORT_DELEGATES = ("_offlineStripScriptLoad",)
# A bracketed run with no nested bracket, and the quoted items inside it. Deliberately two simple
# patterns rather than one with a nested quantifier: the nested form is exponential on a crafted
# input, and this walks a whole source file.
_JS_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")
_JS_STRING_ITEM_RE = re.compile(r'["\']([^"\']+)["\']')
# A removal whose argument is an IDENTIFIER rather than a literal: `s.removeAttribute(attr)` inside
# a loop over a list. That call is what makes the list a strip; the list on its own is data.
_REMOVE_VAR_RE = re.compile(r"removeAttribute\(\s*(\w+)\s*\)")


def _strip_js_comments(text, string_spans=None):
    """The source with `//` and `/* */` comments blanked, quotes and template literals respected.

    Not cosmetic - it closes a FALSE PASS. This file's house style quotes calls and selectors
    inside its comments (the `all("image")` block's comment names the `all("img")` pass above it),
    so a reading that does not strip comments treats prose as code: it already saw one phantom
    selector block, and a strip deleted from the code but left quoted in a comment beside it would
    still be "found" and the parity assertions would stay green over a live egress hole.

    A `'` or `"` string ENDS AT A NEWLINE, as JS itself requires. Without that rule the scanner
    desynchronizes on this very file: a regex literal far above the scanned region carries a quote
    inside a character class (`_OFFLINE_NAV_OPEN_TAIL_RE`), which opens a string state that runs
    for hundreds of lines and copies every comment in between out verbatim. That is not a
    hypothetical - it left 65 comment lines and 5 block comments standing, and the state is carried
    into the scanned region from anywhere above it.
    `test_the_comment_stripper_leaves_no_comment_in_the_real_file` is the tripwire, and it checks
    the whole file rather than the region, because the scanner is stateful and an upstream desync
    is what reaches the region.

    `string_spans`, when given a list, collects the (start, end) ranges of the string literals in
    the OUTPUT, so that tripwire can tell a `/*` that is part of a regex-source STRING (this file
    has five) from one the scan failed to remove.
    """
    out = []
    i, n, quote, opened = 0, len(text), None, 0
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(text[i + 1])
                i += 2
                continue
            if (ch == "\n" and quote != "`") or ch == quote:
                quote = None
                out.append(ch)
                if string_spans is not None:
                    string_spans.append((opened, len(out)))
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            opened = len(out)
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            out.append(" ")
            i = n if end < 0 else end + 2
            continue
        out.append(ch)
        i += 1
    if quote is not None and string_spans is not None:
        string_spans.append((opened, len(out)))
    return "".join(out)


def _function_span(text, name):
    """The (start, end) of one top-level function, bounded by its own MATCHING closing brace.

    Bounding on the next `function ` keyword instead would absorb whatever follows when the next
    declaration is a `const`/arrow/class, and everything it carried would then land in the last
    block of the reading below. The brace count SKIPS string and template literals, so a `"}"` in a
    value cannot truncate the body (which would make a real strip after it invisible).
    """
    start = text.find("function %s(" % name)
    if start < 0:
        return (-1, -1)
    open_brace = text.find("{", start)
    if open_brace < 0:
        return (-1, -1)
    depth, quote, i = 0, None, open_brace
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
        i += 1
    return (-1, -1)


def _function_source(text, name):
    start, end = _function_span(text, name)
    return "" if start < 0 else text[start:end]


def _code_test(spans):
    """A predicate: is this absolute index OUTSIDE every string literal?

    Blanking comments is not enough on its own. A call QUOTED IN A STRING is still text a scan
    would read as code - `const note = 'clearAttr(el, "poster")';` inside an `audio` block would
    otherwise report a strip that does not exist. The literal ARGUMENTS of a real call are inside a
    string too, of course, which is why the test is applied to where the CALL NAME sits, never to
    its argument.
    """
    starts = [start for start, _end in spans]

    def is_code(index):
        pos = bisect.bisect_right(starts, index) - 1
        return not (pos >= 0 and spans[pos][0] <= index < spans[pos][1])
    return is_code


def _delegate_attrs(text, name, is_code):
    """The attributes a delegated strip helper removes, read from the helper itself."""
    start, end = _function_span(text, name)
    if start < 0:
        return frozenset()
    src = text[start:end]
    attrs = {m.group(2).lower() for m in _CLEAR_RE.finditer(src) if is_code(start + m.start())}
    # A LIST of attribute names is data, not a strip. It counts only when the helper really removes
    # through it - a loop variable handed to `removeAttribute` - so deleting that one statement
    # takes the list's attributes with it instead of leaving the guard green over a dead list.
    loop_vars = {m.group(1) for m in _REMOVE_VAR_RE.finditer(src) if is_code(start + m.start())}
    params = {g for m in _FOREACH_PARAM_RE.finditer(src) for g in m.groups() if g}
    if loop_vars & params:
        for bracket in _JS_BRACKET_RE.finditer(src):
            if not is_code(start + bracket.start()):
                continue
            attrs |= {item.lower() for item in _JS_STRING_ITEM_RE.findall(bracket.group(1))}
    return frozenset(attrs)



def _statement_depths(strip):
    """The brace depth of every `all(...)` call in the strip function, body level being 1.

    The block split assumes the calls are SEQUENTIAL statements of the function body. One NESTED
    inside another's callback would silently take the outer block's clears, and asking only that
    the call follows a `;`/`{`/`}` does not catch that - a call opening an inner callback body ends
    in `{` too.
    """
    depths = {}
    depth, quote, i = 0, None, 0
    while i < len(strip):
        ch = strip[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif strip.startswith("all(", i) and (i == 0 or not (strip[i - 1].isalnum()
                                                             or strip[i - 1] in "._$")):
            depths[i] = depth
        i += 1
    return depths


def _export_pairs(source=None, strip_comments=True):
    """Every `(selector-tag, attr)` the offline exporter's strip passes clear.

    Read out of the real partial rather than restated. The reading is SCOPED to
    `_stripOfflineNetworkLoads`, the one pass that decides what an offline export may still fetch,
    so an unrelated `removeAttribute` elsewhere in the file (the mermaid re-render clones an
    element and drops its `id`, say) cannot masquerade as an egress strip. Two things that are TEXT
    rather than code are excluded before anything is read: comments are blanked, and a call whose
    NAME sits inside a string literal is skipped. `strip_comments=False` exists only so a test can
    show its own sample really would be mis-read without that treatment.

    Inside the function each `all("<selector>")` opens a block that runs until the next `all(`
    call. What the block CLEARS is read from its `clearAttr` / `removeAttribute` calls, from the
    body of any helper it delegates to, and - when the block REMOVES THE WALKED ELEMENT - from the
    presence predicates of its own selector (`link[href]`, `meta[http-equiv]`). A predicate
    carrying an operator (`input[type="image"]`) is deliberately NOT read as an attribute: it
    FILTERS the walk, it does not name something the pass clears, and reading it would invent a
    pair.
    """
    raw = source if source is not None else _read_export_source()
    spans = []
    text = _strip_js_comments(raw, string_spans=spans) if strip_comments else raw
    is_code = _code_test(spans if strip_comments else [])
    start, end = _function_span(text, "_stripOfflineNetworkLoads")
    if start < 0:
        return frozenset()
    strip = text[start:end]
    delegates = {name: _delegate_attrs(text, name, is_code) for name in _EXPORT_DELEGATES}
    calls = [m for m in _ALL_CALL_RE.finditer(strip) if is_code(start + m.start())]
    pairs = set()
    for i, call in enumerate(calls):
        block_at = call.end()
        block_end = calls[i + 1].start() if i + 1 < len(calls) else len(strip)
        body = strip[block_at:block_end]
        offset = start + block_at
        attrs = {m.group(2).lower() for m in _CLEAR_RE.finditer(body)
                 if is_code(offset + m.start())}
        for name, delegated in delegates.items():
            if any(is_code(offset + m.start())
                   for m in re.finditer(r"\b%s\(" % re.escape(name), body)):
                attrs |= delegated
        param = _FOREACH_PARAM_RE.search(body)
        walked = (param.group(1) or param.group(2)) if param else None
        removes_element = bool(walked and any(
            is_code(offset + m.start())
            for m in re.finditer(r"\b%s\.remove\(\s*\)" % re.escape(walked), body)))
        for selector in call.group(2).split(","):
            selector = selector.strip()
            if not selector:
                continue
            predicates = {p.strip().lower() for p in re.findall(r"\[([^\]]+)\]", selector)
                          if not re.search(r"[=~|^$*]", p)}
            tag = re.sub(r"\[.*", "", selector).strip() or ANY_TAG
            for attr in attrs | (predicates if removes_element else set()):
                pairs.add((tag, attr))
    return frozenset(pairs)


def _read_export_source():
    with open(EXPORT_OFFLINE, encoding="utf-8") as handle:
        return handle.read()


def _export_has(pair, export_pairs):
    tag, attr = EXPORT_SELECTOR_ALIASES.get(pair, pair)
    if (tag, attr) in export_pairs:
        return True
    # A UNIVERSAL strip satisfies a tag-keyed pair, but only for an attribute whose strip really is
    # universal. Left open, this fallback would let any `removeAttribute("src")` that landed in an
    # attribute-only block (the last one, `all("[style]")`, runs to the end of the function) bless
    # `src` on every tag at once.
    return attr in UNIVERSAL_STRIP_ATTRS and (ANY_TAG, attr) in export_pairs


class EgressListParityTests(unittest.TestCase):
    """CMH-BUILD-22 - the three media load-attribute lists move together or this fails."""

    def test_the_exporter_strips_every_pair_the_layer_gate_reports(self):
        # The CMH-OFFLINE-04 drift direction that costs a user something: a gate that rejects the
        # file the export just produced. Every pair the gate reports must have a strip.
        export_pairs = _export_pairs()
        missing = sorted(p for p in _layer_pairs() if not _export_has(p, export_pairs))
        self.assertEqual(missing, [], "the offline exporter has no strip for these layer-gate "
                                      "egress pairs: %s" % (missing,))

    def test_the_deck_gate_carries_every_pair_the_layer_gate_reports(self):
        # Outside descriptor mode `offline` the base validator's media rules never run over a deck,
        # so this gate is the only checker a deck's egress gets. A pair the layer knows about and
        # the deck does not is a live hole, not a stylistic difference.
        missing = sorted(p for p in _layer_pairs() - _deck_pairs()
                         if p not in DECK_COVERED_ELSEWHERE)
        self.assertEqual(missing, [], "the deck gate has no egress rule for these pairs the layer "
                                      "gate reports (and no named deck rule covers them): %s"
                                      % (missing,))

    def test_the_layer_gate_carries_every_pair_the_deck_gate_reports(self):
        # The other direction: a pair only the DECK carries is either a hole in the far larger
        # shareable/offline surface or a rule that has outlived the engines that needed it. Either
        # way it is a decision to make, not a difference to leave lying around (#1179).
        extra = sorted(_deck_pairs() - _layer_pairs())
        self.assertEqual(extra, [], "the deck gate treats these pairs as egress while the strict "
                                    "layer gate carries no rule for them at all: %s" % (extra,))

    def test_every_named_difference_is_still_real(self):
        # A named exception that no longer describes anything is how a list of "intentional
        # differences" turns into a list nobody reads. Each table entry must still be live.
        layer_pairs, deck_pairs = _layer_pairs(), _deck_pairs()
        for pair in DECK_COVERED_ELSEWHERE:
            self.assertIn(pair, layer_pairs, "%s is named as a layer pair the deck covers "
                                             "elsewhere, but the layer gate no longer carries it"
                                             % (pair,))
            self.assertNotIn(pair, deck_pairs, "%s is named as covered by another deck rule, but "
                                               "the deck's egress index now carries it - drop the "
                                               "exception" % (pair,))
        for tag in DECK_BANNED_TAGS:
            self.assertIn(tag, deck_validate._ACTIVE_TAGS,
                          "%s is named as a deck-banned element but is no longer banned" % tag)
        for pair in SHAPE_DIFFERENCES:
            if pair == (ANY_TAG, ANY_TAG):
                continue   # the global reading difference, not a pair either side carries
            self.assertIn(pair, layer_pairs, "%s is named as a shape difference but the layer gate "
                                             "no longer carries it" % (pair,))
            self.assertIn(pair, deck_pairs, "%s is named as a shape difference but the deck gate "
                                            "no longer carries it" % (pair,))
        export_pairs = _export_pairs()
        for pair, alias in EXPORT_SELECTOR_ALIASES.items():
            self.assertIn(pair, layer_pairs, "%s is named as an exporter alias but the layer gate "
                                             "no longer carries it" % (pair,))
            self.assertIn(alias, export_pairs, "%s is named as the exporter strip for %s but no "
                                               "such strip exists" % (alias, pair))
        for pair in EXPORT_EXTRA_STRIPS:
            self.assertIn(pair, export_pairs, "%s is named as a non-media exporter strip but the "
                                              "exporter no longer clears it - drop the exception"
                              % (pair,))
            # ... and it must not ALSO be a layer pair. Without this, the cheapest way to silence
            # `test_the_exporter_reading_names_every_strip_it_finds` over a genuinely new media
            # load would be to park it in this table, which is the one move that would let a pair
            # land on the exporter alone and stay green.
            self.assertNotIn(pair, layer_pairs, "%s is in EXPORT_EXTRA_STRIPS but the layer gate "
                                                "carries it too - it is a media load and belongs "
                                                "in the parity coverage, not the exception table"
                                 % (pair,))

    def test_the_exporter_reading_is_not_silently_empty(self):
        # A parse that finds nothing would make the superset assertions above vacuous in the one
        # direction that matters. Pin the reading against a hand-checked sample of the real file.
        export_pairs = _export_pairs()
        self.assertGreater(len(export_pairs), 20, sorted(export_pairs))
        for pair in (("img", "src"), ("img", "srcset"), ("video", "poster"), ("object", "data"),
                     ("feImage", "xlink:href"), ("input", "src"), (ANY_TAG, "background"),
                     ("link", "href"), ("script", "xlink:href")):
            self.assertIn(pair, export_pairs, sorted(export_pairs))
        # ... and that it reads BLOCKS rather than the whole file: an attribute cleared in one
        # block must not leak onto the selector of another.
        self.assertNotIn(("audio", "poster"), export_pairs, sorted(export_pairs))
        self.assertNotIn(("use", "src"), export_pairs, sorted(export_pairs))
        # A FILTER predicate is not a strip: `input[type="image"]` must never invent ("input",
        # "type"). (The real selector is `input[src]`; this is the guard, not a claim about it.)
        self.assertNotIn(("input", "type"), export_pairs, sorted(export_pairs))
        # Every delegate the reading follows must actually resolve. A renamed helper would
        # otherwise silently drop its strips and quietly narrow the exhaustiveness check below.
        text = _strip_js_comments(_read_export_source())
        for name in _EXPORT_DELEGATES:
            source = _function_source(text, name)
            self.assertTrue(source.endswith("}"), "delegate %s did not resolve to a function" % name)
        strip = _function_source(text, "_stripOfflineNetworkLoads")
        self.assertTrue(strip.endswith("}"), "the strip function did not resolve to a brace-bounded "
                                             "body - the reading may have absorbed its neighbours")
        # The block split assumes the `all(...)` calls are SEQUENTIAL statements of the function
        # BODY. One nested inside another's callback would silently steal the outer block's
        # clears, and asking only that a call follows a `;`/`{`/`}` does not catch that - a call
        # that opens an inner callback body ends in `{` too. Require body depth exactly.
        depths = _statement_depths(strip)
        self.assertTrue(depths, "no all() call was found in the strip function")
        nested = sorted(d for d in depths.values() if d != 1)
        self.assertEqual(nested, [], "an all() call is nested inside another block, so the split "
                                     "would misattribute its clears (depths seen: %s)" % (nested,))
        # Every `all(` the depth walk sees must also be one the block reader can PARSE. A call
        # wrapped across lines, or one given a variable selector, would otherwise vanish from the
        # reading with no signal - and its clears would be silently folded into the block before it.
        self.assertEqual(len(_ALL_CALL_RE.findall(strip)), len(depths),
                         "an all() call is written in a form the block reader cannot parse (a "
                         "line-wrapped or computed selector), so its strips would go unseen")

    def test_the_deck_reachability_filter_still_matches_the_deck_scanner(self):
        # `_deck_reaches` restates the scanner's own filter, which is the one place this file does
        # not read the source. If the scanner ever narrows that filter, the restatement would
        # over-report reachable pairs and could hide a real layer/deck gap. Pin the line.
        with open(os.path.join(_paths.DECK, "deck_validate.py"), encoding="utf-8") as handle:
            src = handle.read()
        self.assertIn('if name != "srcset" and name not in _URL_ATTRS:', src,
                      "the deck scanner's URL-attribute filter changed shape - `_deck_reaches` "
                      "restates it and must be re-derived from the new one")

    def test_the_comment_stripper_removes_prose_without_eating_code(self):
        # The false pass this closes, reproduced in miniature: a strip deleted from the code but
        # still QUOTED in a comment BETWEEN two real passes must not be read as present. The
        # placement matters - a comment before the FIRST `all(...)` call is in no block at all, so
        # a sample built that way would pass with the stripper deleted and prove nothing.
        sample = ('function _stripOfflineNetworkLoads(doc) {\n'
                  '  const all = function (s) { return q(doc, s); };\n'
                  '  all("use").forEach(function (el) { clearAttr(el, "href"); });\n'
                  '  // prose: the retired pass used to run clearAttr(el, "xlink:href") here,\n'
                  '  // and a quoted selector all("video") beside it\n'
                  '  /* a block comment quoting clearAttr(el, "poster") too */\n'
                  '  all("track").forEach(function (el) { clearAttr(el, "src"); });\n'
                  '}\n')
        pairs = _export_pairs(sample)
        self.assertEqual(sorted(pairs), [("track", "src"), ("use", "href")], sorted(pairs))
        # ... and the sample really is a MUTANT-KILLING one: without the stripper the quoted call
        # would land in the `use` block and invent a pair.
        unstripped = {(t, a) for t, a in _export_pairs(sample, strip_comments=False)}
        self.assertIn(("use", "xlink:href"), unstripped, sorted(unstripped))
        # A `//` inside a string is not a comment.
        self.assertIn("https://host", _strip_js_comments('const u = "https://host"; // gone'))
        self.assertNotIn("gone", _strip_js_comments('const u = "https://host"; // gone'))
        # A quote inside a regex character class must not open a string that swallows the rest of
        # the file - the desync that left 65 real comment lines standing.
        desync = ('const re = /\\(\\s*["`](?:x)/;\n'
                  'function _stripOfflineNetworkLoads(doc) {\n'
                  '  const all = function (s) { return q(doc, s); };\n'
                  '  all("use").forEach(function (el) { clearAttr(el, "href"); });\n'
                  '  // prose: clearAttr(el, "xlink:href")\n'
                  '  all("track").forEach(function (el) { clearAttr(el, "src"); });\n'
                  '}\n')
        self.assertEqual(sorted(_export_pairs(desync)),
                         [("track", "src"), ("use", "href")], sorted(_export_pairs(desync)))

    def test_the_comment_stripper_leaves_no_comment_in_the_real_file(self):
        # The tripwire for the desync class: the scanner is STATEFUL and runs over the whole file,
        # so a quote-bearing regex literal anywhere above the scanned region can carry a fake
        # string state into it. Checking the region alone would not see that, and the loss
        # direction is not the dangerous one - a desync ADDS phantom pairs from prose.
        stripped = _strip_js_comments(_read_export_source())
        leftover = [line for line in stripped.splitlines() if line.lstrip().startswith("//")]
        self.assertEqual(leftover[:5], [], "%d comment lines survived the strip - the scanner has "
                                           "desynchronized on a quote it read as a string opener"
                             % len(leftover))
        # A `/*` may legitimately remain INSIDE a string: this file builds several regexes from
        # source strings that contain one. Anything outside a string is a comment the scan missed.
        spans = []
        stripped = _strip_js_comments(_read_export_source(), string_spans=spans)
        for match in re.finditer(r"/\*", stripped):
            inside = any(start <= match.start() and match.end() <= end for start, end in spans)
            self.assertTrue(inside, "a block comment survived the strip at offset %d: ...%s..."
                            % (match.start(), stripped[match.start():match.start() + 60]))

    def test_a_quoted_call_inside_a_string_is_not_a_strip(self):
        # The sibling of the comment channel: a call whose NAME sits inside a STRING literal is
        # text, not code. Without the check, a `const note = 'clearAttr(el, "poster")';` parked in
        # a block would report a strip that does not exist - and the same shape could make the
        # parity assertions bless a pair the exporter never clears.
        sample = ('function _stripOfflineNetworkLoads(doc) {\n'
                  '  const all = function (s) { return q(doc, s); };\n'
                  '  all("audio").forEach(function (el) {\n'
                  '    const note = \'clearAttr(el, "poster")\';\n'
                  '    clearAttr(el, "src");\n'
                  '  });\n'
                  '}\n')
        pairs = _export_pairs(sample)
        self.assertEqual(sorted(pairs), [("audio", "src")], sorted(pairs))
        # ... and the sample really is mutant-killing: without the string exclusion the quoted call
        # would be read as a strip.
        self.assertIn(("audio", "poster"), _export_pairs(sample, strip_comments=False))

    def test_a_delegated_attribute_list_counts_only_with_a_real_removal(self):
        # An attribute LIST in a delegated helper is data. It becomes a strip only because the
        # helper loops over it and calls `removeAttribute`, so deleting that one statement must
        # take the list's attributes with it - otherwise the guard would stay green over a helper
        # that removes nothing.
        live = ('function _stripOfflineNetworkLoads(doc) {\n'
                '  const all = function (s) { return q(doc, s); };\n'
                '  all("script").forEach(function (s) { _offlineStripScriptLoad(s); });\n'
                '}\n'
                'function _offlineStripScriptLoad(s) {\n'
                '  const loading = ["href", "xlink:href"].filter(function (attr) { return f(attr); });\n'
                '  loading.forEach(function (attr) { s.removeAttribute(attr); });\n'
                '}\n')
        self.assertEqual(sorted(_export_pairs(live)),
                         [("script", "href"), ("script", "xlink:href")], sorted(_export_pairs(live)))
        dead = live.replace("  loading.forEach(function (attr) { s.removeAttribute(attr); });\n", "")
        self.assertEqual(sorted(_export_pairs(dead)), [], sorted(_export_pairs(dead)))

    def test_the_decks_own_two_lists_agree(self):
        # `_ActiveContentScanner._scan` filters on `_URL_ATTRS` BEFORE it consults `_EGRESS_ATTRS`,
        # so an egress entry whose attribute is missing from `_URL_ATTRS` is DEAD - the deck gate
        # declares a rule it never applies. That is a one-sided landing inside a single file, and
        # this PR had to edit both lists in tandem, so it is exactly the shape worth pinning.
        dead = sorted((tag, attr)
                      for tag, attrs in deck_validate._EGRESS_ATTRS.items() for attr in attrs
                      if not _deck_reaches(attr))
        dead += sorted((ANY_TAG, attr) for attr in deck_validate._EGRESS_ANY_ATTRS
                       if not _deck_reaches(attr))
        self.assertEqual(dead, [], "these deck egress rules are unreachable because the attribute "
                                   "is not in `_URL_ATTRS` (the scan filters on it first), so the "
                                   "rule is declared but never applied: %s" % (dead,))

    def test_the_layer_gates_source_names_no_unclassified_rule(self):
        # `_layer_pairs()` is an importable list plus a frozen table, so by itself it can only
        # prove what it already knows. Read the check bodies instead: every past widening landed as
        # a new inline rule there, and a new one that no list carries would otherwise be invisible
        # to every assertion above. All three idioms are read - the TAG question, the universal
        # ATTRIBUTE question, and the per-attribute check with a dynamic tag.
        tags, attrs, pairs = _layer_source_rules()
        known_tags = {tag for tag, _attr in _layer_pairs()}
        known_attrs = {attr for _tag, attr in _layer_pairs()}
        unclassified_tags = sorted(t for t in tags
                                   if t not in known_tags and t not in LAYER_TAGS_NOT_SUBRESOURCE)
        self.assertEqual(unclassified_tags, [], "the layer gate reads these tags and nothing "
                                                "classifies them - is each an automatic "
                                                "subresource the other two surfaces also need? %s"
                                                % (unclassified_tags,))
        unclassified_attrs = sorted(a for a in attrs
                                    if a not in known_attrs
                                    and a not in LAYER_ATTRS_NOT_SUBRESOURCE)
        self.assertEqual(unclassified_attrs, [], "the layer gate checks these attributes (through "
                                                 "the universal `_find_attr_egress` question or a "
                                                 "dynamic-tag check) and nothing classifies them: "
                                                 "%s" % (unclassified_attrs,))
        unclassified_pairs = sorted(p for p in pairs
                                    if p not in _layer_pairs()
                                    and p not in LAYER_PAIRS_NOT_SUBRESOURCE)
        self.assertEqual(unclassified_pairs, [], "the layer gate checks these (tag, attribute) "
                                                 "pairs and nothing classifies them: %s"
                                                 % (unclassified_pairs,))
        for tag in LAYER_TAGS_NOT_SUBRESOURCE:
            self.assertIn(tag, tags, "%s is named as a non-subresource layer rule but the gate no "
                                     "longer reads that tag - drop the exception" % tag)
        for attr in LAYER_ATTRS_NOT_SUBRESOURCE:
            self.assertIn(attr, attrs, "%s is named as a non-subresource layer attribute but the "
                                       "gate no longer checks it - drop the exception" % attr)
        for pair in LAYER_PAIRS_NOT_SUBRESOURCE:
            self.assertIn(pair, pairs, "%s is named as a non-subresource layer rule but the gate "
                                       "no longer checks it - drop the exception" % (pair,))
        # The universal-attribute idiom is the one a reader is most likely to copy (it is how
        # `background` was added), so pin that the reading really sees it: `background` must arrive
        # through `_find_attr_egress`, not only through the frozen table.
        self.assertIn("background", attrs, "the universal `_find_attr_egress` idiom is no longer "
                                           "seen by this reading - a universal widening would be "
                                           "invisible again")

    def test_the_exporter_reading_names_every_strip_it_finds(self):
        # The exporter runs strips that are rules of their own (a `ping`, a form target, a
        # `srcdoc`). They are enumerated in `EXPORT_EXTRA_STRIPS` so this reading stays exhaustive:
        # a NEW exporter strip has to be classified as a media load or named here, which is the
        # moment to ask whether the two gates need it too.
        layer_pairs = _layer_pairs()
        aliased = {EXPORT_SELECTOR_ALIASES.get(p, p) for p in layer_pairs}
        unclassified = sorted(p for p in _export_pairs()
                              if p not in aliased and p not in layer_pairs
                              and p not in EXPORT_EXTRA_STRIPS)
        self.assertEqual(unclassified, [], "the offline exporter clears these attributes and "
                                           "nothing classifies them - is each a media load the two "
                                           "gates also need? %s" % (unclassified,))

    def test_the_frozen_core_groups_are_really_enforced(self):
        # `LAYER_CORE_PAIRS` is a test-owned copy of literals the check body carries inline, so it
        # is worth exactly nothing unless the gate really reports them. Drive the real validator
        # once per pair.
        from _validate_helpers import build, comment_ui, _validate_text
        from _validate_helpers import HANDLED_REGION, EMBEDDED_REGION, JS_REGION, MAIN
        markup = {
            ("img", "src"): '<img src="https://evil.example/x.png" alt="x">',
            ("img", "srcset"): '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" '
                               'srcset="https://evil.example/x.png 1x" alt="x">',
            ("iframe", "src"): '<iframe src="https://evil.example/x.html"></iframe>',
            ("link", "href"): '<link rel="stylesheet" href="https://evil.example/x.css">',
            ("base", "href"): '<base href="https://evil.example/">',
            ("input", "src"): '<input type="image" src="https://evil.example/x.png">',
            (ANY_TAG, "background"): '<td background="https://evil.example/x.png"></td>',
            ("script", "src"): '<script src="https://evil.example/x.js"></script>',
            ("script", "href"): '<script href="https://evil.example/x.js"></script>',
            ("script", "xlink:href"): '<script xlink:href="https://evil.example/x.js"></script>',
        }
        self.assertEqual(sorted(markup), sorted(LAYER_CORE_PAIRS),
                         "every frozen core pair needs a fixture that exercises it")
        for pair, snippet in sorted(markup.items()):
            body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, snippet, JS_REGION]
            errors, warnings = _validate_text(build(body=body))
            # The finding must name the ATTRIBUTE under test, not merely mention the URL: another
            # rule reporting the same snippet would otherwise satisfy this while the rule this pair
            # stands for had quietly stopped firing.
            attr = pair[1]
            self.assertTrue(any("evil.example" in line and '%s="' % attr in line
                                for line in errors + warnings),
                            "the layer gate reports nothing for %s: %s" % (pair, errors + warnings))


if __name__ == "__main__":
    unittest.main()
