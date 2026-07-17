def _region_bounds(begin_idx, end_idx, name):
    """Byte range [lo, hi) of a region's content, or (None, None) when its
    markers are missing or out of order, so a state JSON block is read from inside
    its own region and a decoy <script> with the same id elsewhere is ignored."""
    if name in begin_idx and name in end_idx and begin_idx[name] < end_idx[name]:
        return begin_idx[name], end_idx[name]
    return None, None


def _check_state_json_blocks(html, parser, begin_idx, end_idx, nonportable):
    errors, warnings = [], []
    # 4) handledCommentIds is a JSON array of safe ids.
    hlo, hhi = _region_bounds(begin_idx, end_idx, "HANDLED IDS")
    handled_script = _parser_script(parser, "handledCommentIds", hlo, hhi)
    handled = handled_script["body"] if handled_script is not None else None
    if handled is None:
        errors.append('missing <script id="handledCommentIds"> block')
    else:
        if not _is_json_attrs(handled_script["attrs"]):
            errors.append('the <script id="handledCommentIds"> block must be type="application/json" '
                          "(without it the browser executes the JSON as JavaScript)")
        try:
            arr = json.loads(handled.strip() or "[]")
            if not isinstance(arr, list):
                errors.append("handledCommentIds is not a JSON array")
            else:
                bad = [x for x in arr if not (isinstance(x, str) and SAFE_ID_RE.match(x))]
                if bad:
                    errors.append(f"handledCommentIds has {len(bad)} id(s) not matching the safe pattern "
                                  f"{SAFE_ID_RE.pattern}: {bad[:3]} - mark_handled.py will refuse to edit "
                                  "this file until they are corrected")
        except json.JSONDecodeError as exc:
            errors.append(f"handledCommentIds is not valid JSON: {exc}")

    # 5) embeddedComments is a JSON array.
    elo, ehi = _region_bounds(begin_idx, end_idx, "EMBEDDED COMMENTS")
    embedded_script = _parser_script(parser, "embeddedComments", elo, ehi)
    embedded = embedded_script["body"] if embedded_script is not None else None
    if embedded is None:
        errors.append('missing <script id="embeddedComments"> block')
    else:
        if not _is_json_attrs(embedded_script["attrs"]):
            errors.append('the <script id="embeddedComments"> block must be type="application/json" '
                          "(without it the browser executes the JSON as JavaScript)")
        try:
            arr = json.loads(embedded.strip() or "[]")
            if not isinstance(arr, list):
                errors.append("embeddedComments is not a JSON array")
            else:
                # Each embedded comment must have a safe string id (the runtime keys
                # merge/dedupe on it and getElementById-style lookups assume it is safe);
                # a null/non-string/unsafe id silently drops or breaks the comment at load.
                bad = [i for i, item in enumerate(arr)
                       if not (isinstance(item, dict) and isinstance(item.get("id"), str)
                               and SAFE_ID_RE.match(item["id"]))]
                if bad:
                    errors.append("embeddedComments: %d item(s) have a missing or unsafe id "
                                  "(indices %s) - each item must be an object whose id matches %s"
                                  % (len(bad), bad[:5], SAFE_ID_RE.pattern))
        except json.JSONDecodeError as exc:
            errors.append(f"embeddedComments is not valid JSON: {exc}")

    # 6) The JS region must contain exactly one real </script>.
    if not nonportable and "JS" in begin_idx and "JS" in end_idx:
        lo, hi = sorted((begin_idx["JS"], end_idx["JS"]))
        js_slice = html[lo:hi]
        n_close = len(re.findall(r"</script\s*>", js_slice, re.IGNORECASE))
        if n_close == 0:
            errors.append("JS region has no closing </script> before its END marker (malformed)")
        elif n_close > 1:
            errors.append(f"JS region contains {n_close} </script> tags - a literal </script> in the script body must be escaped as <\\/script>")
    return errors, warnings


def _check_offset_within(html, begin_idx, end_idx):
    errors, warnings = [], []
    # 3c) Text-anchoring robustness. The layer's offsetWithin() must normalize a range
    #     boundary that lands on an element node (element, childIndex) to a text node,
    #     or a selection starting/ending at a block edge (e.g. a heading selected from
    #     its start yields a (h3, 0) boundary) returns -1 and the composer aborts with
    #     "Could not anchor that selection". Require a real normalizeBoundary() function
    #     AND a call to it from within offsetWithin()'s body (brace-matched on the
    #     string/comment-blanked source via _js_scan, so a normalizeBoundary token that
    #     lives only in a comment or a string literal cannot satisfy the check and a `}`
    #     inside a string cannot prematurely close the body). Gate on offsetWithin so the
    #     stub JS used by the test fixtures (which has neither symbol) stays exempt.
    _jlo, _jhi = _region_bounds(begin_idx, end_idx, "JS")
    if _jlo is not None:
        _scan = _js_scan(html[_jlo:_jhi])[1]  # init view: comments AND strings blanked
        _decl = re.search(r"function\s+offsetWithin\s*\([^)]*\)\s*\{", _scan)
        if _decl is not None:
            _has_decl = re.search(r"function\s+normalizeBoundary\s*\(", _scan) is not None
            _calls = False
            _m = _decl
            if _m:
                _depth, _body_start = 0, _m.end()
                for _j in range(_m.end() - 1, len(_scan)):
                    if _scan[_j] == "{":
                        _depth += 1
                    elif _scan[_j] == "}":
                        _depth -= 1
                        if _depth == 0:
                            _calls = re.search(r"\bnormalizeBoundary\s*\(", _scan[_body_start:_j]) is not None
                            break
            if not (_has_decl and _calls):
                errors.append(
                    "the JS region defines offsetWithin() but does not both declare a "
                    "normalizeBoundary() function and call it from within offsetWithin(); a "
                    'selection whose start or end lands on an element boundary will fail to '
                    'anchor ("Could not anchor that selection")')
    return errors, warnings
