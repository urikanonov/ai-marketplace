#!/usr/bin/env python3
"""Stop a finished document storing a checklist item's identity twice.

A survey of 15 generated documents (#1250) found their bodies compress 18.7x, because a tree of
about 1700 rows repeats the same handful of attribute values on every row. Two of those held the
BYTE-IDENTICAL string on all 1725 items of one document - `data-cmh-item="X"` and an authored
`data-<ns>-id="X"` - about 168 KB of provably duplicated data in a single file, and the same
duplication again between `data-cmh-parent` and `data-<ns>-parent`.

This drops the `data-cmh-*` copy and records WHERE to read it from on the container, as
`data-cmh-item-attr` / `data-cmh-parent-attr`. The runtime (`assets/js/36-checklist.js`), the
validator and `tools/checklist/checklist_apply.py` all DERIVE the id from the attribute the
container names, preferring the item's own `data-cmh-item` while it is still there. The authored
attribute is the one that survives, because a document's own CSS and tooling reference it.

TWO OTHER TRANSFORMS WERE IMPLEMENTED AND THEN REMOVED, and both are recorded here so they are
not re-attempted without new information. Each was measured at ZERO effect on every document this
repository ships, and each was found to change something a reader can observe:

1. Hoisting a class every child shares onto its container, extending each `.token` rule with
   `[data-cmh-cls~="token"] > *`. It could not be made sound by a static tool (a rule can live in
   a `<link>` stylesheet or behind an `@import` this never sees, a generic `[class]` selector
   stops matching either way, a CSS-escaped `.\\74 ok` evades a token scan, and a child-combinator
   selector matches children added later). Worse, it WEAKENED an enforcement layer: the WCAG
   contrast checker refuses any selector carrying a combinator, so the rewritten entry became
   invisible to it while the `.token` entry left behind matched nothing.
2. Dropping an `aria-label` equal to the element's own text. The accessible name falls back to an
   element's CONTENT only for the roles that support name-from-content, and that set cannot be
   approximated by refusing the obvious tags: measured through Chromium's own accessible-name
   computation, stripping the label emptied the name on `li`, `p`, `ul`, `dd`, `blockquote`,
   `label`, `tr`, `details`, `div` and `span`, on top of the landmark and heading cases found a
   round earlier. Doing it correctly needs an ALLOW-list of name-from-content roles, and on that
   list the transform fires nowhere in the surveyed corpus - so it buys nothing in exchange for a
   silent, user-observable accessibility regression whenever the list is wrong.

Everything here fails SAFE. The scan is one browser-accurate parser pass (quote-, comment- and
raw-text-aware, the reading `vendored_libs.py` uses for the same reason: a regex over markup
mis-reads quoted `>` and comment bodies), it is scoped to the `#commentRoot` CONTENT region, and
any anomaly abandons the transform and leaves the document byte-identical. Re-running is a no-op.

Usage (run from the skill root):
    python tools/authoring/dom_slim.py file.html
    python tools/authoring/dom_slim.py file.html --check
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import _atomic_io  # noqa: E402
import _browser_attrs  # noqa: E402

# The container attributes that NAME where an item's identity is read from, so the id is derived
# rather than stored on every row. The runtime (assets/js/36-checklist.js), the validator
# (tools/validate/checks/checklist.py) and tools/checklist/checklist_apply.py read the same two.
ITEM_ALIAS_ATTR = "data-cmh-item-attr"
PARENT_ALIAS_ATTR = "data-cmh-parent-attr"

_VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr"))

# Elements that open FOREIGN content. Inside them attribute names are case-sensitive
# (`viewBox`, `pathLength`), which the shared HTML tokenizer does not preserve, so no start tag
# in these subtrees is ever re-serialized.
_FOREIGN_ROOTS = frozenset(("svg", "math"))

# Tags a browser closes IMPLICITLY, on seeing a following tag rather than a closing one. This
# reader builds the tag tree the standard-library tokenizer reports, which is NOT the tree a
# browser repairs markup into, and the two disagree exactly around these: a
# `<p data-cmh-checklist="inner">` holding block children is already CLOSED by the time the
# browser reaches them, so the browser assigns those rows to the OUTER checklist while this
# reader assigns them to the `<p>`. Acting on that disagreement strips identity from rows the
# runtime then keys POSITIONALLY, orphaning saved state - so ownership that depends on one of
# these being still open is not provable here, and the dedupe refuses it.
_IMPLICITLY_CLOSED = frozenset((
    "p", "li", "dt", "dd", "td", "th", "tr", "thead", "tbody", "tfoot", "option", "optgroup",
    "rb", "rt", "rtc", "rp"))

# A script that can carry the runtime. An inert one (`type="text/plain"`, a JSON island) never
# executes, so a mention of the alias inside it proves nothing about what will read the document.
_JS_TYPES = frozenset((
    "", "text/javascript", "application/javascript", "module", "text/ecmascript",
    "application/ecmascript"))

_ALIAS_NAME_RE = re.compile(r"^data-[a-z0-9-]+$")
_TAG_NAME_RE = re.compile(r"<([a-zA-Z][^\t\n\r\f />]*)")


class _Node(object):
    __slots__ = ("tag", "attrs", "tag_start", "tag_end", "self_closing", "parent", "children",
                 "in_root", "foreign")

    def __init__(self, tag, attrs, tag_start, tag_end, self_closing, parent):
        self.tag = tag
        self.attrs = attrs
        self.tag_start = tag_start
        self.tag_end = tag_end
        self.self_closing = self_closing
        self.parent = parent
        self.children = []
        self.in_root = False
        self.foreign = False


class _SlimScan(_browser_attrs.BrowserTagNames):
    """One pass that answers every question the transform asks.

    It records the element tree with each start tag's exact span, and the raw text of every
    `<script>` that a browser would actually execute (the runtime-capability gate reads it).
    """

    def __init__(self, html):
        _browser_attrs.BrowserTagNames.__init__(self, convert_charrefs=False)
        self._html = html
        self._line_offsets = [0]
        for line in html.split("\n")[:-1]:
            self._line_offsets.append(self._line_offsets[-1] + len(line) + 1)
        self._stack = []
        self.nodes = []
        self.root = None          # the <main id="commentRoot"> node
        self.live_scripts = []    # (node, text) for every executable script
        self._raw_open = None     # the tag name while inside a raw-text element
        self._script_node = None

    def _offset(self):
        line, col = self.getpos()
        return self._line_offsets[line - 1] + col

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        raw = self.get_starttag_text() or ""
        start = self._offset()
        scanned = _browser_attrs.scan_start_tag(self._html, start)
        self_closing = bool(scanned[2]) if scanned else False
        node = _Node(tag, _browser_attrs.attrs_dict(self, tag, attrs), start, start + len(raw),
                     self_closing, self._stack[-1] if self._stack else None)
        if node.parent is not None:
            node.parent.children.append(node)
        self.nodes.append(node)
        if tag == "main" and node.attrs.get("id") == "commentRoot" and self.root is None:
            self.root = node
        # FOREIGN content keeps case-sensitive attribute names, which a re-serialization through
        # the HTML tokenizer would flatten (`viewBox` -> `viewbox`), breaking the rendering.
        node.foreign = (tag in _FOREIGN_ROOTS
                        or (node.parent is not None and node.parent.foreign))
        if tag in ("script", "style"):
            self._raw_open = tag
            self._script_node = node if tag == "script" else None
        if tag not in _VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        tag = self._browser_tag(tag)
        if self._raw_open == tag:
            self._raw_open = None
            self._script_node = None
        # A trailing `/>` only closes a VOID element or one in FOREIGN content. On an ordinary
        # HTML element a browser IGNORES it and the element stays open, so popping here would
        # hand the rows that follow to the wrong checklist - and this reader would then strip
        # them under the outer pointer while the runtime keys them under the inner one.
        if tag in _VOID or self._foreign_open():
            if self._stack and self._stack[-1].tag == tag:
                self._stack.pop()

    def _foreign_open(self):
        return bool(self._stack) and self._stack[-1].foreign

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        if self._raw_open == tag:
            self._raw_open = None
            self._script_node = None
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        if data and self._raw_open == "script" and self._script_node is not None:
            self.live_scripts.append((self._script_node, data))


def _scan(html):
    scan = _SlimScan(html)
    try:
        scan.feed(html)
        scan.close()
    except Exception:
        return None
    if scan.root is None:
        return None
    _mark_in_root(scan.root)
    return scan


def _mark_in_root(root):
    stack = [root]
    while stack:
        node = stack.pop()
        node.in_root = True
        stack.extend(node.children)


def _raw_attr_region(html, node):
    """The start tag's attribute text: everything between the tag name and the closing `>`."""
    raw = html[node.tag_start:node.tag_end]
    m = _TAG_NAME_RE.match(raw)
    if not m or not raw.endswith(">"):
        return None
    return raw[m.end():len(raw) - 1]


def _can_rewrite(html, node):
    """Whether this node's start tag can be re-serialized at all.

    Checked on EVERY row and on the container before anything is mutated, because the container
    attribute carries what the rows stop carrying: committing the pointer while a row keeps its
    own id - or worse, stripping rows while the container rewrite fails - is how identity gets
    lost outright.
    """
    if node.foreign:
        return False
    region = _raw_attr_region(html, node)
    if region is None or "\r" in region:
        return False
    return _browser_attrs.raw_attrs_pairs_consumed(region)[1]


def _rewrite_start_tag(html, node, drop, add):
    """The node's start tag re-serialized without `drop` and with `add`, or None to leave it.

    Fails closed four ways: anything inside FOREIGN content is refused outright (the tokenizer
    folds attribute names to lower case, so `viewBox` would come back as `viewbox`), a start tag
    the shared tokenizer does not fully consume is not rewritten (re-serializing a partial read
    would DROP the attributes it could not see), a tag carrying a CR is left alone (the tokenizer
    folds it to LF the way a browser does, so writing the pairs back would change the document's
    line endings), and an `add` whose name is already on the element is refused rather than
    duplicated.
    """
    if node.foreign:
        return None
    region = _raw_attr_region(html, node)
    if region is None or "\r" in region:
        return None
    pairs, consumed = _browser_attrs.raw_attrs_pairs_consumed(region)
    if not consumed:
        return None
    kept = [(n, v) for n, v in pairs if n not in drop]
    if len(kept) == len(pairs) and not add:
        return None
    have = set(n for n, _v in kept)
    for name in sorted(add):
        if name in have:
            return None
        kept.append((name, add[name]))
    return _browser_attrs.serialize_start_tag(node.tag, kept, node.self_closing)


def _checklist_container(node):
    """The checklist a node belongs to: its nearest `[data-cmh-checklist]` ANCESTOR-OR-SELF.

    Presence, not truthiness, and self-inclusive, because that is what the runtime's
    `el.closest("[data-cmh-checklist]") === container` filter means. Reading an empty
    `data-cmh-checklist=""` as "not a checklist" made a nested container invisible as a BOUNDARY,
    so its rows were treated as the outer checklist's and stripped while only the outer container
    got the pointer. Self-inclusive keeps a nested container out of its parent's item list.
    """
    p = node
    while p is not None:
        if "data-cmh-checklist" in p.attrs:
            return p
        p = p.parent
    return None


def _ownership_is_provable(container, items):
    """Whether this reader's tree can be trusted to agree with the browser's for this checklist.

    The standard-library tokenizer nests by tag, while a browser REPAIRS markup, and the two
    disagree around the tags a browser closes IMPLICITLY. The demonstrated hazard is a container
    that is one of them - a `<p data-cmh-checklist="inner">` holding block children is already
    closed when the browser reaches them, so the browser gives those rows to the OUTER checklist
    and keys them differently. Stripping identity on the strength of a tree the runtime does not
    share is how saved state gets orphaned.

    The path between an item and its container is checked for `<p>` ONLY. Ordinary structural
    nesting a browser preserves exactly - a `tbody` and `tr` under a `table`, a `ul` and `li`
    under a `div` - is how every real checklist is built, so refusing those would refuse the
    feature; `<p>` is the one that cannot legally hold block content and so gets closed early.
    """
    if container.tag in _IMPLICITLY_CLOSED:
        return False
    for item in items:
        p = item.parent
        while p is not None and p is not container:
            if p.tag == "p":
                return False
            p = p.parent
        if p is None:
            return False
    return True


def _runtime_reads_the_alias(scan):
    """Whether the document's OWN embedded runtime knows how to derive an aliased identity.

    The dedupe moves an item's id onto a pointer, so it is only safe when the runtime that will
    read the document understands the pointer. A Shareable document embeds its runtime, so this
    is checkable directly. Two documents legitimately fail and must be left alone: a NONSHAREABLE
    one, whose runtime is a sibling `commentable-html.js` this tool can neither see nor version
    (a stale companion would read the trimmed rows as unidentified and fall back to POSITIONAL
    keys, silently orphaning stored checklist state), and one carrying an OLDER embedded runtime
    that predates the pointer.

    The evidence has to come from a script a browser would really RUN, and from OUTSIDE the
    content root - the rule CMH-SIZE-01 adopted for the same reason. An authored example inside
    the content root (a document DOCUMENTING this very feature) or an inert `text/plain` island
    mentioning the attribute is content, not a runtime, and treating it as proof would trim
    exactly the NonShareable document this gate exists to protect.
    """
    for node, text in scan.live_scripts:
        if node.in_root:
            continue
        stype = (node.attrs.get("type") or "").strip().lower().split(";")[0]
        if stype in _JS_TYPES and ITEM_ALIAS_ATTR in text:
            return True
    return False


def _alias_candidates(items, own_attr):
    """The `data-*` attributes that hold each item's `own_attr` value, byte for byte, on EVERY
    item - and that are ABSENT from every item `own_attr` is absent from.

    Both halves matter. Equal-where-present alone would let an alias carry an id on a row that
    authored none, so the derived reading would gain an item (or a parent link) the authored
    document never had.
    """
    names = set()
    for item in items:
        names |= set(n for n in item.attrs
                     if _ALIAS_NAME_RE.match(n) and not n.startswith("data-cmh-"))
    names = set(n for n in names
                if all(item.attrs.get(n) == item.attrs.get(own_attr) for item in items))
    if not any(item.attrs.get(own_attr) for item in items):
        return set()
    return names


def _plan_identity(scan, html, mutations):
    changed = 0
    if not _runtime_reads_the_alias(scan):
        return 0
    for container in scan.nodes:
        if not container.in_root or not container.attrs.get("data-cmh-checklist"):
            continue
        # PRESENCE, not truthiness. A container already carrying `data-cmh-item-attr=""` read as
        # "no alias" under a truthiness test, so the rows were stripped while the container
        # rewrite was refused (the name was already on it) - a document left with no identity at
        # all and nothing to derive it from.
        if ITEM_ALIAS_ATTR in container.attrs or PARENT_ALIAS_ATTR in container.attrs:
            continue
        items = [n for n in scan.nodes
                 if n is not container
                 and ("data-cmh-state" in n.attrs or "data-cmh-item" in n.attrs)
                 and _checklist_container(n) is container]
        if len(items) < 2 or not all(n.attrs.get("data-cmh-item") for n in items):
            continue
        if not _ownership_is_provable(container, items):
            continue
        # ALL-OR-NOTHING: every row's start tag and the container's are proved rewritable before
        # anything is mutated, so the pointer can never be committed against rows that keep
        # their own ids, nor rows stripped against a container that never gets the pointer.
        if not _can_rewrite(html, container) or not all(_can_rewrite(html, n) for n in items):
            continue
        item_alias = sorted(_alias_candidates(items, "data-cmh-item"))
        seen = set(id(n) for n in items)
        inside = [n for n in scan.nodes
                  if n is not container and id(n) not in seen
                  and _checklist_container(n) is container]
        # A non-item inside the container must not carry the alias, or DERIVING identity from it
        # would promote that element to an item the authored document never had. Tested by
        # PRESENCE: the runtime selects on `[alias]`, which an empty value satisfies.
        item_alias = [n for n in item_alias if not any(n in x.attrs for x in inside)]
        if not item_alias:
            continue
        name = item_alias[0]
        parent_alias = None
        if any(n.attrs.get("data-cmh-parent") for n in items):
            cands = _alias_candidates(items, "data-cmh-parent") - {name}
            cands = set(c for c in cands if not any(c in x.attrs for x in inside))
            if cands:
                parent_alias = sorted(cands)[0]
        add = {ITEM_ALIAS_ATTR: name}
        drop_item = set(["data-cmh-item"])
        if parent_alias:
            add[PARENT_ALIAS_ATTR] = parent_alias
            drop_item.add("data-cmh-parent")
        mutations.setdefault(id(container), (container, set(), {}))[2].update(add)
        for item in items:
            mutations.setdefault(id(item), (item, set(), {}))[1].update(
                drop_item if item.attrs.get("data-cmh-parent") else set(["data-cmh-item"]))
            changed += 1
    return changed


def slim(html):
    """Return `(html, changed, stats)` with the duplicated identity removed.

    Idempotent: a document already trimmed (or one this reader cannot follow) comes back
    byte-identical with `changed` False.
    """
    stats = {"identity": 0}
    scan = _scan(html)
    if scan is None:
        return html, False, stats
    mutations = {}
    stats["identity"] = _plan_identity(scan, html, mutations)
    edits = []
    for node, drop, add in mutations.values():
        new_tag = _rewrite_start_tag(html, node, drop, add)
        if new_tag is not None:
            edits.append((node.tag_start, node.tag_end, new_tag))
    if not edits:
        return html, False, stats
    edits.sort(key=lambda e: e[0], reverse=True)
    out = html
    last = None
    for start, end, text in edits:
        if last is not None and end > last:
            continue  # overlapping edit: never splice twice over the same bytes
        out = out[:start] + text + out[end:]
        last = start
    return out, out != html, stats


def slim_file(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        html = fh.read()
    out, changed, stats = slim(html)
    if changed:
        _atomic_io.atomic_write(path, out)
    return changed, stats


def main(argv):
    parser = argparse.ArgumentParser(
        prog="dom_slim.py",
        description="Stop a finished document storing a checklist item's identity twice: drop "
                    "the data-cmh-item / data-cmh-parent copy of an authored id and name its "
                    "source on the container instead. finalize.py runs this automatically; use "
                    "it directly on a single document.")
    parser.add_argument("file", help="HTML document to inspect or rewrite")
    parser.add_argument("--check", action="store_true",
                        help="report what would be trimmed and exit without writing")
    args = parser.parse_args(argv[1:])

    try:
        with open(args.file, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write("dom_slim: %s\n" % exc)
        return 1

    if args.check:
        _out, changed, stats = slim(html)
        print("dom_slim: identity=%d -> %s"
              % (stats["identity"], "would rewrite" if changed else "nothing to trim"))
        return 0
    try:
        changed, stats = slim_file(args.file)
    except OSError as exc:
        sys.stderr.write("dom_slim: %s\n" % exc)
        return 1
    print("dom_slim: identity=%d -> %s"
          % (stats["identity"], "rewritten" if changed else "unchanged"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
