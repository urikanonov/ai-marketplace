"""Layered-checklist authoring checks (`data-cmh-checklist` containers)."""

import re

from .parsing import _BrowserStartTag, _browser_attrs_dict

_CHECK_STATES = ("blank", "check", "cross", "question")

# A container may NAME where an item's identity lives rather than repeat it on every row (see
# tools/authoring/dom_slim.py); the reading here derives the same id the runtime does.
_ITEM_ALIAS_ATTR = "data-cmh-item-attr"
_PARENT_ALIAS_ATTR = "data-cmh-parent-attr"
_ALIAS_NAME_RE = re.compile(r"^data-[a-z0-9-]+$")

_CL_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split())


def _alias(d, which):
    raw = (d.get(which) or "").strip().lower()
    return raw if _ALIAS_NAME_RE.match(raw) else ""


class _ChecklistParser(_BrowserStartTag):
    """Collect each data-cmh-checklist container INSTANCE and the items inside it (an item is
    an element carrying data-cmh-state, data-cmh-item, or the container's named identity
    attribute). Scoped to the innermost open container, mirroring the runtime's ownership rule."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._stack = []            # (tag, opened_instance_or_None)
        self._containers = []       # stack of open instance dicts
        self.instances = []         # ordered {id, items: [{state, item_id, parent}]}

    def _attrs(self, tag, attrs):
        # Browser attribute-value decoding, shared with the document parser, so a
        # `data-cmh-item` id reads the same on every interpreter (CMH-VAL-21). Trusting the
        # host's values instead hid a real duplicate id on Python 3.12.
        return _browser_attrs_dict(self, tag, attrs)

    def _record_item(self, d):
        if not self._containers:
            return
        # A nested checklist CONTAINER is not an item of the checklist enclosing it - the runtime
        # scopes items with `closest("[data-cmh-checklist]") === container`, which is
        # ancestor-or-SELF. Recording it made it a ghost item of the outer list.
        if "data-cmh-checklist" in d:
            return
        ctx = self._containers[-1]
        alias, parent_alias = ctx["alias"], ctx["parent_alias"]
        if not ("data-cmh-state" in d or "data-cmh-item" in d or (alias and alias in d)):
            return
        ctx["items"].append({
            "state": d.get("data-cmh-state"),
            "item_id": d.get("data-cmh-item") or (d.get(alias) if alias else None),
            "parent": d.get("data-cmh-parent") or (d.get(parent_alias) if parent_alias else None),
        })

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        d = self._attrs(tag, attrs)
        self._record_item(d)
        opened = None
        if "data-cmh-checklist" in d:
            opened = {"id": d.get("data-cmh-checklist") or "", "items": [],
                      "alias": _alias(d, _ITEM_ALIAS_ATTR),
                      "parent_alias": _alias(d, _PARENT_ALIAS_ATTR)}
            self.instances.append(opened)
            self._containers.append(opened)
        if tag not in _CL_VOID:
            self._stack.append((tag, opened))

    def handle_startendtag(self, tag, attrs):
        self._record_item(self._attrs(self._browser_tag(tag), attrs))

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                popped = self._stack[i:]
                del self._stack[i:]
                for (_t, opened) in reversed(popped):
                    if opened is not None and self._containers and self._containers[-1] is opened:
                        self._containers.pop()
                return


def check_checklists(html):
    """Return (errors, warnings) for layered-checklist markup. No-op when the document has
    no data-cmh-checklist container. All findings are warnings so --strict escalates them
    while a normal run of a checklist-free document is unaffected."""
    errors, warnings = [], []
    p = _ChecklistParser()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return errors, warnings
    ids = [inst["id"] for inst in p.instances]
    for d in sorted(set(x for x in ids if ids.count(x) > 1)):
        warnings.append('data-cmh-checklist id "%s" appears on %d containers (ids must be unique per document)'
                        % (d, ids.count(d)))
    for inst in p.instances:
        cid = inst["id"]
        if not inst["items"]:
            warnings.append('checklist "%s" has no items (elements with data-cmh-state, data-cmh-item, or the container\'s named identity attribute)' % cid)
            continue
        item_ids = [it["item_id"] for it in inst["items"] if it["item_id"]]
        seen, dups = set(), set()
        for iid in item_ids:
            if iid in seen:
                dups.add(iid)
            seen.add(iid)
        for iid in sorted(dups):
            warnings.append('checklist "%s" has duplicate data-cmh-item id "%s"' % (cid, iid))
        for it in inst["items"]:
            st = it["state"]
            if st is not None and st.strip().lower() not in _CHECK_STATES:
                warnings.append('checklist "%s": invalid data-cmh-state "%s" (use blank, check, cross, or question)'
                                % (cid, st))
        valid = set(item_ids)
        for it in inst["items"]:
            if it["parent"] and it["parent"] not in valid:
                warnings.append('checklist "%s": data-cmh-parent "%s" does not resolve to an item in the same checklist'
                                % (cid, it["parent"]))
    return errors, warnings
