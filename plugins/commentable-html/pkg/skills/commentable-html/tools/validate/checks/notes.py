"""Editable notes-field authoring checks (`data-cmh-note` elements)."""

from html.parser import HTMLParser

_NOTE_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split())

# Layer substrates a note must not be nested inside (its text is cm-skip and would collide
# with these commentable mechanisms).
_LAYER_ATTRS = ("data-cmh-checklist", "data-cm-widget")
_LAYER_CLASSES = ("cmh-diff", "deck-stage", "slide")


class _NotesParser(HTMLParser):
    """Collect each data-cmh-note element instance: its id, whether it has element children,
    whether it is void, whether it nests inside another note, and whether it sits inside a
    checklist / diff / widget / deck substrate."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._stack = []      # (tag, note_dict_or_None)
        self._open_notes = 0
        self._layer_depth = 0
        self.notes = []       # {id, void, nested, in_layer, has_child}

    def _attrs(self, attrs):
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d

    def _is_layer(self, d):
        if any(a in d for a in _LAYER_ATTRS):
            return True
        cls = (d.get("class") or "").split()
        return any(c in cls for c in _LAYER_CLASSES)

    def handle_starttag(self, tag, attrs):
        d = self._attrs(attrs)
        is_note = "data-cmh-note" in d
        if not is_note and self._open_notes > 0:
            # An element child inside every currently-open note.
            for frame in self._stack:
                if frame[1] is not None:
                    frame[1]["has_child"] = True
        note = None
        if is_note:
            note = {
                "id": d.get("data-cmh-note") or "",
                "void": tag.lower() in _NOTE_VOID,
                "nested": self._open_notes > 0,
                "in_layer": self._layer_depth > 0,
                "has_child": False,
            }
            self.notes.append(note)
        is_layer = self._is_layer(d)
        if tag.lower() not in _NOTE_VOID:
            self._stack.append((tag.lower(), note, is_layer))
            if note is not None:
                self._open_notes += 1
            if is_layer:
                self._layer_depth += 1

    def handle_startendtag(self, tag, attrs):
        d = self._attrs(attrs)
        if "data-cmh-note" in d:
            self.notes.append({
                "id": d.get("data-cmh-note") or "",
                "void": True, "nested": self._open_notes > 0,
                "in_layer": self._layer_depth > 0, "has_child": False,
            })

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                popped = self._stack[i:]
                del self._stack[i:]
                for frame in reversed(popped):
                    if frame[1] is not None:
                        self._open_notes -= 1
                    if frame[2]:
                        self._layer_depth -= 1
                return


def check_notes(html):
    """Return (errors, warnings) for editable notes-field markup. No-op when the document has
    no data-cmh-note element. All findings are warnings so --strict escalates them while a
    normal run of a notes-free document is unaffected."""
    errors, warnings = [], []
    p = _NotesParser()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return errors, warnings
    ids = [n["id"] for n in p.notes]
    for d in sorted(set(x for x in ids if x and ids.count(x) > 1)):
        warnings.append('data-cmh-note id "%s" appears on %d elements (ids must be unique per document)'
                        % (d, ids.count(d)))
    for n in p.notes:
        nid = n["id"]
        if not nid:
            warnings.append("a data-cmh-note element has an empty id (each note needs a unique id)")
        if n["void"]:
            warnings.append('note "%s" is on a void element; a note must be a container with text content' % nid)
        if n["nested"]:
            warnings.append('note "%s" is nested inside another data-cmh-note (notes must not nest)' % nid)
        if n["has_child"]:
            warnings.append('note "%s" contains child elements; a note must hold plain text only' % nid)
        if n["in_layer"]:
            warnings.append('note "%s" is nested inside a checklist/diff/widget/deck substrate; keep notes standalone' % nid)
    return errors, warnings
