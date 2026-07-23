/* ---------- Text-offset helpers ---------- */
function getTextNodes() {
  if (typeof window !== "undefined" && window.__cmhPerf) window.__cmhPerf.textScans = (window.__cmhPerf.textScans || 0) + 1;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
      if (n.parentElement && n.parentElement.closest(".cm-skip"))
        return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const arr = [];
  let n;
  while ((n = walker.nextNode())) arr.push(n);
  return arr;
}
function firstTextNodeIn(el) {
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
      if (n.parentElement && n.parentElement.closest(".cm-skip")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  return w.nextNode();
}
function lastTextNodeIn(el) {
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
      if (n.parentElement && n.parentElement.closest(".cm-skip")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let last = null, n;
  while ((n = w.nextNode())) last = n;
  return last;
}
// A selection boundary can land on an ELEMENT node (element, childIndex) instead of a
// text node - browsers do this when a selection starts or ends at the very edge of a
// block, e.g. selecting a heading from its start yields (h3, 0). offsetWithin only
// matches text nodes, so an element boundary returned -1 and aborted anchoring
// ("Could not anchor that selection"). Resolve such a boundary to the equivalent
// (textNode, offset) using the same cm-skip filter as getTextNodes.
function acceptableTextNode(n) {
  return !!(n && n.nodeType === 3 && n.nodeValue &&
    !(n.parentElement && n.parentElement.closest(".cm-skip")));
}
function normalizeBoundary(node, off) {
  if (!node || node.nodeType === 3) return [node, off];
  if (node.nodeType !== 1) return [node, off];
  const kids = node.childNodes;
  for (let i = off; i < kids.length; i++) {
    const k = kids[i];
    const t = acceptableTextNode(k) ? k : (k.nodeType === 1 ? firstTextNodeIn(k) : null);
    if (t) return [t, 0];
  }
  for (let i = Math.min(off, kids.length) - 1; i >= 0; i--) {
    const k = kids[i];
    const t = acceptableTextNode(k) ? k : (k.nodeType === 1 ? lastTextNodeIn(k) : null);
    if (t) return [t, t.nodeValue.length];
  }
  return [node, off];
}
function offsetWithin(node, off) {
  [node, off] = normalizeBoundary(node, off);
  const nodes = getTextNodes();
  let total = 0;
  for (const tn of nodes) {
    if (tn === node) return total + off;
    total += tn.nodeValue.length;
  }
  // The boundary normalized to a node that is not one of the counted text nodes -
  // typically a cm-skip element (e.g. an injected section caret) that a triple-click
  // or other block selection swept in just past the real text. If that node is still
  // inside the comment root, resolve the boundary by DOCUMENT POSITION: the summed
  // length of every counted text node lying at or before the boundary point. A
  // boundary outside the root stays rejected so cross-region selections still fail.
  if (!node || !root.contains(node)) return -1;
  total = 0;
  for (const tn of nodes) {
    if (_comparePointAt(tn, tn.nodeValue.length, node, off) <= 0) { total += tn.nodeValue.length; continue; }
    if (_comparePointAt(tn, 0, node, off) < 0) {
      const sub = document.createRange();
      sub.setStart(tn, 0); sub.setEnd(node, off);
      total += sub.toString().length;
    }
    break;
  }
  return total;
}
// Document-order comparison of two boundary points: -1 if (a,ao) precedes (b,bo),
// 0 if equal, 1 if it follows. Used to place a boundary that landed on a cm-skip node.
function _comparePointAt(a, ao, b, bo) {
  const r = document.createRange();
  r.setStart(b, bo); r.setEnd(b, bo);
  try { return r.comparePoint(a, ao); } catch (e) { return 1; }
}
function rangeFromOffsets(start, end, nodes) {
  // An optional precomputed text-node list lets a caller restoring/backfilling MANY comments reuse
  // one getTextNodes() walk across lookups instead of re-walking the whole document per comment
  // (O(count x doc) -> O(count + doc)). It is only safe to reuse while the DOM is unchanged, so a
  // caller must rebuild the list after any mutation (e.g. a successful wrapRangeWithMark).
  nodes = nodes || getTextNodes();
  let total = 0;
  const range = document.createRange();
  let sSet = false, eSet = false;
  for (const tn of nodes) {
    const next = total + tn.nodeValue.length;
    if (!sSet && start >= total && start <= next) { range.setStart(tn, start - total); sSet = true; }
    if (!eSet && end   >= total && end   <= next) { range.setEnd(tn,   end   - total); eSet = true; }
    if (sSet && eSet) return range;
    total = next;
  }
  return null;
}

