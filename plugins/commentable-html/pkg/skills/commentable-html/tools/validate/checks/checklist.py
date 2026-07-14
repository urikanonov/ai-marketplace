"""Layered-checklist authoring checks (`data-cmh-checklist` containers)."""

from html.parser import HTMLParser

_CHECK_STATES = ("blank", "check", "cross", "question")

_CL_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split())


class _ChecklistParser(HTMLParser):
    """Collect each data-cmh-checklist container INSTANCE and the items inside it (an item is
    an element carrying data-cmh-state or data-cmh-item). Scoped to the innermost open
    container, mirroring the runtime's ownership rule."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._stack = []            # (tag, opened_instance_or_None)
        self._containers = []       # stack of open instance dicts
        self.instances = []         # ordered {id, items: [{state, item_id, parent}]}

    def _attrs(self, attrs):
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d

    def _record_item(self, d):
        if self._containers and ("data-cmh-state" in d or "data-cmh-item" in d):
            self._containers[-1]["items"].append({
                "state": d.get("data-cmh-state"),
                "item_id": d.get("data-cmh-item"),
                "parent": d.get("data-cmh-parent"),
            })

    def handle_starttag(self, tag, attrs):
        d = self._attrs(attrs)
        self._record_item(d)
        opened = None
        if "data-cmh-checklist" in d:
            opened = {"id": d.get("data-cmh-checklist") or "", "items": []}
            self.instances.append(opened)
            self._containers.append(opened)
        if tag.lower() not in _CL_VOID:
            self._stack.append((tag.lower(), opened))

    def handle_startendtag(self, tag, attrs):
        self._record_item(self._attrs(attrs))

    def handle_endtag(self, tag):
        tag = tag.lower()
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
            warnings.append('checklist "%s" has no items (elements with data-cmh-state or data-cmh-item)' % cid)
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
