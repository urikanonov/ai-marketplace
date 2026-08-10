(() => {
// Restore the compressed cold tier FIRST - before the snapshot below, and so before anything else
// in the layer touches the DOM. `cmhHydrateColdTier` is a hoisted declaration in `01-cold-tier.js`
// and is written to use only function-locals, so it is safe to call from here, above every
// module-level `const`. It never throws; `var` (not `const`) because this statement runs before
// this file's own `const`s are initialized. `95-startup.js` turns a failure into a toast.
var CMH_COLD_TIER = cmhHydrateColdTier();
// Pristine snapshot of the document, captured before any DOM mutation
// (mermaid render, restored highlights, dynamic composers, etc). Used as a
// fallback by "Export as Shareable" when fetch() of the page URL is unavailable
// (e.g., file://, blocked fetch, or CSP). The snapshot is taken on the very first line
// of the IIFE so it predates every runtime change this script makes - which is why it is the RAW
// assembly here and gets the CR pass a few lines below, once that pass's `const`s exist.
let SNAPSHOT_HTML = "<!DOCTYPE html>\n" + cmhSerializeElementRaw(document.documentElement);

// ---- Shared HTML-string boundary readings ----
// Pure, and declared as early as the snapshot allows. They moved here from
// `65-export-shareable.js`, which now reads them from this one copy so the string-scanning rule
// cannot drift between the export walk and the serializer's own CR post-pass.
//
// ASCII whitespace is the HTML spec's tag delimiter set. JS `\s` also matches NBSP and other
// Unicode spaces, which a browser does NOT treat as a delimiter, so `<script\u00a0id="...">`
// (one bogus unknown element to a browser) would otherwise look like a real script tag here.
const _CMH_SPACE_CH = /[\t\n\f\r ]/;
// One source of truth for "what ends a tag name" - a space belongs here, since an end tag may
// carry a space before its ">" and still close the element. Spelling the class twice let the space go missing from
// the close scanners, which made such a document impossible to export at all.
const _CMH_NAME_END_SRC = "\\t\\n\\f\\r />";
const _CMH_NAME_END_CH = new RegExp("[" + _CMH_NAME_END_SRC + "]");
// Elements whose CONTENT a browser parses as TEXT, never as markup (noscript counts because the
// layer only runs with scripting enabled). Nothing inside one of these is an element.
const _CMH_RAW_TEXT = /^(?:script|style|textarea|title|xmp|iframe|noembed|noframes|noscript)$/;
// A tag name only begins with an ASCII letter; anything else after `<` is text, a comment, a
// markup declaration or a bogus comment.
const _CMH_TAG_OPEN_CH = /[a-zA-Z]/;
function _cmhTagEnd(html, start) {
  let quote = "";
  let afterEquals = false;
  for (let i = start + 1; i < html.length; i += 1) {
    const ch = html[i];
    if (quote) {
      if (ch === quote) quote = "";
      continue;
    }
    // A quote only opens an attribute value directly after `=`; a stray apostrophe elsewhere in
    // the tag (`<div data-x=it's ok>`) does not, and treating it as one used to swallow the
    // rest of the document.
    if (ch === '"' || ch === "'") {
      if (afterEquals) quote = ch;
      afterEquals = false;
      continue;
    }
    if (ch === "=") {
      afterEquals = true;
      continue;
    }
    if (_CMH_SPACE_CH.test(ch)) continue;
    if (ch === ">") return i;
    afterEquals = false;
  }
  return -1;
}
function _cmhTagName(html, from) {
  let i = from;
  while (i < html.length && !_CMH_NAME_END_CH.test(html[i])) i += 1;
  return html.slice(from, i).toLowerCase();
}
function _cmhCommentEnd(html, start) {
  // `<!-->` and `<!--->` are complete (empty) comments, and `--!>` also terminates one. Missing
  // those made a legal comment swallow the rest of the document.
  let i = start + 4;
  if (html[i] === ">") return i + 1;
  if (html[i] === "-" && html[i + 1] === ">") return i + 2;
  const rx = /--!?>/g;
  rx.lastIndex = i;
  const m = rx.exec(html);
  return m ? m.index + m[0].length : html.length;
}
function _cmhScriptDataClose(html, from) {
  // The tokenizer's script-data escaped states: inside a <script> body a `<!--` starts an
  // escaped run, and a nested `<script` within it starts a DOUBLE-escaped run in which the next
  // closing script tag only ends that run instead of closing the element (the classic
  // `<!--<script>` idiom). Only `-->` leaves those runs (`--!>` does not, unlike in a comment).
  const rx = new RegExp("<!--|-->|</?script(?=[" + _CMH_NAME_END_SRC + "])", "gi");
  rx.lastIndex = from;
  let escaped = false;
  let doubled = false;
  let m;
  while ((m = rx.exec(html))) {
    const tok = m[0].toLowerCase();
    if (tok === "<!--") { escaped = true; continue; }
    if (tok.charAt(0) === "-") { escaped = false; doubled = false; continue; }
    if (tok === "<script") { if (escaped) doubled = true; continue; }
    if (doubled) { doubled = false; continue; }
    return m.index;
  }
  return -1;
}
function _cmhRawTextClose(html, name, from) {
  if (name === "script") return _cmhScriptDataClose(html, from);
  // An end tag only closes a raw-text element when the name is followed by whitespace, `/`, or
  // `>`; an end tag that merely PREFIXES the name (a "scriptfoo" close) is text. Matching a bare
  // prefix ended the element early and exposed its text to this walk as markup - the very
  // failure this resolver exists to prevent.
  const rx = new RegExp("</" + name + "(?=[" + _CMH_NAME_END_SRC + "])", "gi");
  rx.lastIndex = from;
  const m = rx.exec(html);
  return m ? m.index : -1;
}

// ---- Serialized-CR fidelity ----
// A DOM re-serialized through `getHTML()` / `outerHTML` spells a CR LITERALLY: HTML's fragment
// serialization escapes `&`, U+00A0, `<` and `>` in a text node (and `&`, U+00A0 and `"` in an
// attribute value) and NOTHING else. But HTML's INPUT-STREAM PREPROCESSING folds every CR and
// every CRLF to a single LF BEFORE the tokenizer runs, so the next load reads that literal CR
// back as an LF and the authored CR is gone - silently, on every export that re-serializes the
// DOM. `&#13;` is decoded AFTER preprocessing, so it is the only spelling that round-trips; the
// authoring tools already write a CR that way (#1196), and this is the runtime half of the same
// rule, applied in ONE place so the export paths that share this serializer cannot drift.
//
// The rewrite is only correct where a browser DECODES a character reference, so the scan walks
// the string the way the tokenizer does and leaves two kinds of region VERBATIM: a COMMENT, and
// the BODY of an element whose text a serializer appends literally and a parser never decodes
// (`script`, `style`, `xmp`, `iframe`, `noembed`, `noframes`, `noscript`, plus `plaintext`, which
// swallows the rest of the document). Writing `&#13;` into one of those would show those six
// characters instead of the CR. A raw-text element's own START TAG is still rewritten, because an
// attribute value is decoded whatever the element is. `textarea` and `title` are deliberately NOT
// verbatim - they are RCDATA, which the serializer escapes and the tokenizer decodes, so a CR
// there rewrites like any other text (which is why this set is narrower than `_CMH_RAW_TEXT`).
//
// The scan is quote-aware because attribute-value escaping does NOT escape `<`: a
// `title="<script>"` would otherwise look like a raw-text element opening here and silence the
// rewrite for everything after it.
//
// Declared limit: nothing is raw text inside FOREIGN content, so an `<svg><style>` body IS
// escaped by the serializer and IS decoded by the parser, and an `<svg><plaintext>` is an ordinary
// foreign element that does NOT swallow the rest of the document - but this walk keeps no
// namespace stack and treats both as it would in the HTML namespace. That direction merely
// DECLINES to rewrite (fidelity is not improved there, and after a foreign `<plaintext>` not
// improved for the rest of the document either); the other direction would corrupt a real script
// or style body into showing six literal characters, so the walk errs here on purpose. A
// half-correct namespace stack would have to model the HTML integration points
// (`<foreignObject>`, `<desc>`, SVG `<title>`, the MathML text points) and every breakout tag to
// stay on the safe side of that trade, which is why declining is preferred to guessing.
const _CMH_TEXT_VERBATIM = /^(?:script|style|xmp|iframe|noembed|noframes|noscript)$/;
const _CMH_CR_RE = /\r/g;
// The SPELLING half of the rule, in one place: a CR that must survive a re-parse is written as
// `&#13;`. The walk below decides WHERE that is legal; any other re-serializer that already knows
// it is writing into a reference-decoding region (an attribute-value encoder) spells it through
// this rather than keeping its own `\r` literal.
function cmhEscapeCr(text) {
  return String(text == null ? "" : text).replace(_CMH_CR_RE, "&#13;");
}
// A Text node's own data, serialized the way HTML's fragment serialization serializes one: through
// the browser's own escaper, so `&`, U+00A0, `<` and `>` come back as references, and then through
// the CR spelling, which that escaper does not apply. A caller that splices a Text node's data into
// a document directly - rather than letting an element serializer do it - must go through this. The
// raw data is not markup-safe (an authored `<script>` in a text node becomes a LIVE script), and
// that is not merely a separate bug: it makes the CR spelling WRONG too, because a `&#13;` written
// into what the reload then reads as a raw-text body is six literal characters, not a CR.
function cmhSerializeTextData(data) {
  const holder = document.createElement("div");
  holder.textContent = String(data == null ? "" : data);
  return cmhEscapeCr(holder.innerHTML);
}
function cmhEscapeSerializedCarriageReturns(html) {
  const s = String(html == null ? "" : html);
  // The overwhelmingly common case. Returning the input untouched also means no document that
  // carries no CR at all can be changed by this pass, however the walk below behaves.
  if (s.indexOf("\r") < 0) return s;
  const keep = function (a, b) { return s.slice(a, b); };
  const fix = function (a, b) { return cmhEscapeCr(s.slice(a, b)); };
  let out = "";
  let run = 0;
  let i = 0;
  while (i < s.length) {
    const lt = s.indexOf("<", i);
    if (lt < 0) break;
    if (s.slice(lt, lt + 4) === "<!--") {
      const end = _cmhCommentEnd(s, lt);
      out += fix(run, lt) + keep(lt, end);
      i = run = end;
      continue;
    }
    if (!_CMH_TAG_OPEN_CH.test(s.charAt(lt + 1) || "")) { i = lt + 1; continue; }
    const gt = _cmhTagEnd(s, lt);
    // A tag that never finishes is discarded by a browser along with everything after it, so
    // whatever this pass does with the remainder is unobservable; rewrite it like ordinary text.
    if (gt < 0) break;
    const name = _cmhTagName(s, lt + 1);
    if (name === "plaintext") return out + fix(run, gt + 1) + keep(gt + 1, s.length);
    if (!_CMH_TEXT_VERBATIM.test(name)) { i = gt + 1; continue; }
    const close = _cmhRawTextClose(s, name, gt + 1);
    const bodyEnd = close < 0 ? s.length : close;
    out += fix(run, gt + 1) + keep(gt + 1, bodyEnd);
    i = run = bodyEnd;
  }
  return out + fix(run, s.length);
}
// Exposed for deterministic tests (the pass is pure, and its carve-outs are worth unit-testing
// without having to round-trip a whole export).
window.__cmhEscapeSerializedCRs = function (h) { return cmhEscapeSerializedCarriageReturns(h); };

// The load-time snapshot is the ONE caller that cannot run the pass at capture time: it must be
// the first statement in the IIFE (nothing may mutate the DOM before it, and a build guard pins
// that), while the pass depends on `const`s that are not hoisted. The transform is PURE, so it is
// applied here instead - the same single rule, deferred by a few lines rather than duplicated.
SNAPSHOT_HTML = cmhEscapeSerializedCarriageReturns(SNAPSHOT_HTML);

// Pristine snapshot of the document, captured before any DOM mutation
// (mermaid render, restored highlights, dynamic composers, etc). Used as a
// fallback by "Export as Shareable" when fetch() of the page URL is unavailable
// (e.g., file://, blocked fetch, or CSP). The snapshot is taken on the very first line
// of the IIFE so it predates every runtime change this script makes.
function cmhSerializableOpenShadowRoots(rootEl) {
  const roots = [];
  const visit = function (scope) {
    scope.querySelectorAll("*").forEach(function (el) {
      if (!el.shadowRoot) return;
      roots.push(el.shadowRoot);
      visit(el.shadowRoot);
    });
  };
  if (rootEl.shadowRoot) {
    roots.push(rootEl.shadowRoot);
    visit(rootEl.shadowRoot);
  }
  visit(rootEl);
  return roots;
}
// The RAW assembly: the element's own serialization, with its serializable shadow roots spliced
// in, and no CR pass. Split out because the load-time snapshot must run before that pass's
// declarations exist; every other caller goes through `cmhSerializeElement`.
function cmhSerializeElementRaw(el) {
  if (!el || typeof el.getHTML !== "function") return el ? el.outerHTML : "";
  const inner = el.getHTML({
    serializableShadowRoots: true,
    shadowRoots: cmhSerializableOpenShadowRoots(el),
  });
  const shell = el.cloneNode(false).outerHTML;
  const close = "</" + el.tagName.toLowerCase() + ">";
  return shell.toLowerCase().endsWith(close)
    ? shell.slice(0, shell.length - close.length) + inner + close
    : shell;
}
function cmhSerializeElement(el) {
  // The CR pass runs on the ASSEMBLED string, once: it is the single point every export path
  // shares, so none of them can drift into writing an authored CR back as a literal one.
  return cmhEscapeSerializedCarriageReturns(cmhSerializeElementRaw(el));
}
// The layer runs synchronously during parse, so SNAPSHOT_HTML stops at THIS <script>:
// host content placed after the layer (per charts-embedding.md, chart data + init scripts land
// after the "END: commentable-html - JS" marker, before the final </body>) has not been
// parsed yet and is absent from the snapshot. Capture the script element now, while
// document.currentScript is still valid, so an export can recover that tail from the
// fully-parsed DOM (see _snapshotWithTail).
const CMH_LAYER_SCRIPT = document.currentScript;
// Layer chrome injected during init (footer, side-TOC, scroll progress) is captured in
// this set at the end of the IIFE - before the browser parses any host content that
// follows the layer <script> - so a file:// export tail can exclude it while keeping
// host content (which may itself be cm-skip, e.g. a chart <canvas>). See _snapshotWithTail.
const CMH_INJECTED_CHROME = new Set();

// Layer chrome that must not count as DOCUMENT TEXT. Deliberately SEPARATE from
// CMH_INJECTED_CHROME above: that set is populated partly by a heuristic sweep (every element
// sibling following the layer script, in 95-startup.js), which is fine for its job - trimming an
// export tail - because an over-capture there costs a stale tail. Membership HERE subtracts text
// from the document content hash, where an over-capture is silent and produces the exact false
// "not validated" banner the hash exists to prevent, so this set is populated only where the layer
// CREATES the node, by construction. Today that is the print appendix (83-print.js), the one pass
// that appends real prose into the content root; every other in-root control is cm-skip.
const CMH_HASH_EXCLUDED = new Set();

// The layer's OWN interactive chrome, held by IDENTITY. Some of it is injected INSIDE the content
// root (a sortable-table sort control, a widget "Reset moves", a checklist box), where containment
// cannot tell it from author content and a class match would let author content spoof its way past
// a guard. Registering each control where the layer CREATES it is the only test a document cannot
// fake. Register the interactive CONTROL itself, never a container that also holds inert or author
// content (a toolbar's label, the code wrap around an author `<pre>`, an author `[data-cmh-note]`
// container): membership below covers the whole subtree, so a container registration hands away the
// dismiss click on dead space for no functional gain. Consumed by the comment dialog's
// outside-click swallow (53-comment-popover.js).
const CMH_LAYER_CHROME = new WeakSet();
function cmhMarkLayerChrome(el) {
  if (!el || el.nodeType !== 1) return el;
  // Enforce the invariant rather than only documenting it: registering a node that IS or CONTAINS
  // the annotated document would exempt the whole document from the swallow, which is the one
  // mistake a future call site could make that silently disables the guard entirely.
  try {
    if (el === document.documentElement || el === document.body) return el;
    if (root && el.contains(root)) return el;
  } catch (e) { return el; }
  CMH_LAYER_CHROME.add(el);
  return el;
}
// Resolve the layer's OWN control inside `scope`, by IDENTITY rather than by class name. Every
// "does a control already exist here?" guard must go through this: an author element wearing a
// control's class would otherwise make the layer skip creating (or, worse, remove) the real
// control, silently denying the reviewer the affordance. The spoof gains nothing either way - it
// is never registered, so the dialog's outside-click swallow still treats it as document content.
function cmhOwnChrome(scope, selector) {
  if (!scope || typeof scope.querySelectorAll !== "function") return null;
  try {
    const list = scope.querySelectorAll(selector);
    for (let i = 0; i < list.length; i++) if (CMH_LAYER_CHROME.has(list[i])) return list[i];
  } catch (e) { return null; }
  return null;
}

// True when a click landed on, or inside, a registered chrome subtree. Prefers the EVENT's
// propagation path (fixed at dispatch) so a control another listener detaches mid-dispatch is still
// recognized, and falls back to the live ancestor chain where `composedPath` is unavailable.
function cmhClickHitsLayerChrome(target, path) {
  if (path) {
    for (let i = 0; i < path.length; i++) if (CMH_LAYER_CHROME.has(path[i])) return true;
    return false;
  }
  let el = target && target.nodeType === 1 ? target : (target && target.parentElement) || null;
  while (el) {
    if (CMH_LAYER_CHROME.has(el)) return true;
    el = el.parentElement;
  }
  return false;
}

// Scroll behavior that respects prefers-reduced-motion: JS scrollIntoView/scrollTo take a
// `behavior` option that OVERRIDES the CSS `scroll-behavior` reset, so every programmatic
// smooth scroll must consult this so motion-sensitive readers get an instant jump instead.
// Fails closed to "auto" (less motion) when the preference cannot be determined, since this is
// an accessibility affordance and an instant jump is never worse than an unwanted animation.
function cmScrollBehavior() {
  try {
    if (typeof window.matchMedia !== "function") return "auto";
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  } catch (e) { return "auto"; }
}

// ---- Authored-text preservation: permute children through the slots they ALREADY occupy ----
// Reordering elements by APPENDING them strands the whitespace text nodes an author leaves between
// them: the elements end up textually adjacent and the stranded whitespace piles up ahead of them.
// That is a text change no later "unsort" can undo (unsorting restores element ORDER, not the moved
// whitespace), so it silently drifted the document and section content hashes and made the same
// file show the "not validated" banner on one machine and not another (#952). Every reorder inside
// the content root goes through these helpers instead, so the class cannot reappear in a third copy
// of the slot math (#977): `ordered` is dropped into the slots its OWN members already occupy and
// every other child node stays exactly where the author put it.
//
// Both fail SAFE. Given anything that is not a permutation of nodes currently parented by `parent`
// (a foreign node, a duplicate) they decline, because an untouched DOM is always text-neutral while
// a partial rearrangement is not.
function _cmhSlotPlan(parent, ordered) {
  if (!parent || !ordered || ordered.length < 2) return null;
  const kids = Array.prototype.slice.call(parent.childNodes);
  const pos = new Map();
  for (let i = 0; i < kids.length; i++) pos.set(kids[i], i);
  const slots = [];
  for (let i = 0; i < ordered.length; i++) {
    if (!pos.has(ordered[i])) return null;
    slots.push(pos.get(ordered[i]));
  }
  if (new Set(slots).size !== slots.length) return null;
  slots.sort(function (a, b) { return a - b; });
  return { kids: kids, slots: slots };
}
// Pure READ: a copy of `parent`'s child nodes with `ordered` placed into its members' slots.
// Returns null when the input is not such a permutation, so a caller can fall back to the live
// order. Used by the canonical-hash scan, which must never touch the DOM.
function cmhPermutedChildNodes(parent, ordered) {
  const plan = _cmhSlotPlan(parent, ordered);
  if (!plan) return null;
  const out = plan.kids.slice();
  for (let i = 0; i < plan.slots.length; i++) out[plan.slots[i]] = ordered[i];
  return out;
}
// WRITE: apply that permutation to the DOM by swapping each member out for a placeholder comment
// and each placeholder back for the node that belongs in it. Returns true when the DOM changed;
// an identity reorder returns false without touching anything (the canonical-hash and export passes
// unsort EVERY sortable table, including ones the reader never sorted).
function cmhPermuteChildrenInSlots(parent, ordered) {
  const plan = _cmhSlotPlan(parent, ordered);
  if (!plan) return false;
  const members = plan.slots.map(function (s) { return plan.kids[s]; });
  let same = true;
  for (let i = 0; i < members.length; i++) if (members[i] !== ordered[i]) { same = false; break; }
  if (same) return false;
  const marks = members.map(function () { return document.createComment(""); });
  members.forEach(function (n, i) { parent.replaceChild(marks[i], n); });
  marks.forEach(function (m, i) { parent.replaceChild(ordered[i], m); });
  return true;
}
