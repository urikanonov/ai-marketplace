/* ---------- Link comment layer ----------
   Two runtime behaviours for author-facing <a href> links inside #commentRoot:
   1. At render time, every external reference is stamped target="_blank" +
      rel="noopener noreferrer" so opening a reference keeps the reader's place
      (authors do not hand-stamp each link).
   2. Each link is made commentable, mirroring the image/mermaid layers: hovering
      or keyboard-focusing a link reveals a floating #linkAddBtn that anchors a
      comment to that link by (linkIndex) + href/text fallback. The affordance is a
      separate floating button, so activating it does not navigate and a normal
      click still follows the link. Same-page "#" fragments (e.g. the TOC), UI
      chrome (.cm-skip), and javascript: links are excluded. */
const linkAddBtn = document.getElementById("linkAddBtn");
const linkEls = [];
let pendingLink = null;
let linkAddHideTimer = null;
let linkActiveEl = null;

// What the WHATWG URL parser removes from the ENDS of a URL before it parses it: every C0 control
// plus space (U+0000-U+0020) and NOTHING else. The JS twin of the validator's `url_ends_trim`
// (tools/validate/checks/parsing.py), written as an explicit range for the same reason
// `_OFFLINE_REL_WS_RE` is a literal class: neither engine's own trim is this set, and the two
// disagree in BOTH directions. JS `.trim()` reaches past ASCII and takes NBSP, U+2028, U+2029,
// every Zs and U+FEFF, which the parser KEEPS - so `href="&#xa0;#frag"` read as a same-page
// fragment although a browser resolves it to a DIFFERENT document (`%C2%A0#frag`), and the
// author's `target="_self"` stood and navigated the reviewer's tab away from the report and their
// comments (#1170). In the other direction JS `.trim()` KEEPS a non-whitespace C0 control the
// parser removes, so `href="&#x1;#frag"` was read as a document reference and stamped, although a
// browser navigates it within this document. (U+0085 is kept by BOTH, so it needs no correction.)
const _CMH_URL_ENDS_TRIM_RE = /^[\u0000-\u0020]+|[\u0000-\u0020]+$/g;
function _cmhUrlEndsTrim(value) {
  return String(value == null ? "" : value).replace(_CMH_URL_ENDS_TRIM_RE, "");
}
// Whether a click on `a` STAYS in this document, asked of the URL a browser RESOLVES rather than of
// the raw href. An empty or `#fragment` href is only same-page when it resolves against the
// document's OWN URL: a `<base href>` re-points both at a DIFFERENT document, which a click then
// navigates the current tab to - the exact harm the stamp exists to prevent - so the string shape
// alone cannot decide the exemption. The end trim above is still load-bearing beside this: it is
// what stops a padded `#frag` (which a browser resolves elsewhere) from reaching this test at all,
// and what lets a C0-padded one reach it.
function _cmhSamePageHref(a) {
  const bare = (u) => { const i = u.indexOf("#"); return i === -1 ? u : u.slice(0, i); };
  return bare(String(a.href || "")) === bare(location.href);
}
// The reading of an `<a href>` used as a comment's ANCHOR KEY: the classifier's own end trim, after
// ASCII tab/CR/LF are collapsed to a space so a stored href can never break the one-line Copy-all
// and sidebar renderings. It must be the classifier's trim: a link the classifier admits because
// the parser keeps its padding (`href="&#xa0;#frag"`) would otherwise store a JS-trimmed key that
// can never equal its own attribute, silently disabling href healing for exactly the links this
// reading newly admits, and storing an EMPTY key for `href="&#xa0;"`.
function _cmhLinkHrefKey(value) {
  return _cmhUrlEndsTrim(String(value == null ? "" : value).replace(/[\r\n\t]+/g, " "));
}
// The reading a runtime BEFORE 1.790.0 wrote, kept solely so a comment stored by one still resolves.
function _cmhLegacyLinkHrefKey(value) {
  return String(value == null ? "" : value).replace(/[\r\n\t]+/g, " ").trim();
}
// The validator's own reading of an `<a href>` (`tools/validate/checks/links.py` - `_browser_href`,
// `_href_scheme`, `_is_document_reference`), mirrored here for the case the browser cannot answer:
// an href `new URL()` refuses to resolve against this document. Each class is written out as an
// explicit range for the same reason `_CMH_URL_ENDS_TRIM_RE` above is - neither engine's own trim or
// `\s` is the parser's set - and each is pinned to the validator's as TEXT, and the pair over a
// corpus, by `tests/test_vendored_libs.py`.
//
// Two cleanups, both the URL parser's own input handling: ASCII tab/LF/CR removed from ANYWHERE
// (so `ja<TAB>vascript://[` is the non-document scheme it really is), then the ENDS trimmed through
// the shared `_cmhUrlEndsTrim` above, so a padded `<SP>foo://[` is not misread as the scheme-less
// relative reference it is not. This is deliberately NOT `_offlineNormalizeUrlValue`
// (68-export-offline), which also maps backslash onto slash: that mapping is right for an ORIGIN
// decision and wrong for a mirror of `_browser_href`, which omits it on purpose. Keep this reading
// pinned to the validator's, not to the exporter's.
const _CMH_URL_INNER_STRIP_RE = /[\t\n\r]/g;
// Anchored, and its class excludes `/`, `?` and `#`, so a ":" belonging to a path or query
// ("path/to:x") never reads as a scheme. The document schemes are the ones the stamp is for.
const _CMH_HREF_SCHEME_RE = /^[A-Za-z][A-Za-z0-9+.\-]*:/;
const _CMH_DOC_SCHEMES = ["http", "https", "file"];
function _cmhBrowserHref(href) {
  return _cmhUrlEndsTrim(String(href == null ? "" : href).replace(_CMH_URL_INNER_STRIP_RE, ""));
}
// Whether `href` names a DOCUMENT a click would navigate to, decided on the STRING - the reading the
// authoring gate (CMH-LINK-05) uses, and the only one available once `new URL()` has thrown. A
// scheme-less reference inherits the document's protocol, so it counts.
function _cmhHrefIsDocumentReference(href) {
  const raw = _cmhBrowserHref(href);
  if (!raw || raw.charAt(0) === "#") return false;
  const m = _CMH_HREF_SCHEME_RE.exec(raw);
  if (!m) return true;
  return _CMH_DOC_SCHEMES.indexOf(m[0].slice(0, -1).toLowerCase()) !== -1;
}

// Author-facing reference links only: real href, not UI chrome, not an in-page
// fragment (those navigate within the document, so a new tab would be wrong and
// commenting on a TOC entry is not the intent). Classification is by the browser-
// NORMALIZED protocol (a.protocol), not a string match on the raw href, so an
// obfuscated scheme (java\tscript:, embedded control chars) cannot slip past: only
// real document references are eligible - http/https, or a relative/root-relative
// URL that inherits the document's http(s)/file protocol. Everything else
// (javascript:, mailto:, tel:, data:, blob:, ...) is excluded, so a mailto/tel link
// is never stamped target=_blank (which would strand the reader on a dead tab).
//
// The EMPTINESS and leading-`#` tests read the href through `_cmhUrlEndsTrim`, the URL parser's
// own end trim, because both decide the EARLY RETURN - so an over-broad trim makes the stamp apply
// to FEWER links, the unsafe direction (contrast the `rel` stamp below, whose JS `.trim()` on the
// target only ever makes that stamp apply to MORE links and is deliberately left alone). The
// exemption they gate is then confirmed against the URL a browser RESOLVES (`_cmhSamePageHref`),
// so a `<base href>` that re-points an empty or `#fragment` href at another document cannot buy an
// exemption from a navigation that really does leave this page.
//
// When `new URL()` cannot RESOLVE the href against this document there is no normalized protocol to
// read. That is two populations, not one: an href the parser rejects outright (`http://[`,
// `http://%`, `file://[`, `https://?`), and ANY relative reference in a document whose base URL has
// an opaque path (`about:blank`, `blob:`, `data:`), which has no base to resolve against.
// `a.protocol` is not the answer for either: it is ":" for an anchor whose URL record is null (the
// HTML getter's defined value, not a Chromium quirk), which matches none of the three document
// schemes - so such a link was left unstamped and an author-set `target="_self"` on it stood, and
// the reviewer's own tab navigated away from the report and their comments. It also put the runtime
// and the CMH-LINK-05 gate, which classifies the same href on the string and calls it a document
// reference, on opposite sides of the same link. The fallback is therefore that same string
// reading (#1183), which is what the gate would say and can only ever ADD a stamp: the old branch
// answered false for every href that reached it.
function _cmhCommentableLink(a) {
  if (!a || a.tagName !== "A" || !a.hasAttribute("href")) return false;
  if (a.closest(".cm-skip")) return false;
  const raw = _cmhUrlEndsTrim(a.getAttribute("href"));
  if ((!raw || raw.charAt(0) === "#") && _cmhSamePageHref(a)) return false; // same-page fragment
  let proto = "";
  try { proto = new URL(a.href, document.baseURI).protocol.toLowerCase(); }
  catch (e) { return _cmhHrefIsDocumentReference(a.getAttribute("href")); }
  return proto === "http:" || proto === "https:" || proto === "file:";
}
// The EFFECTIVE target a browser resolves for a hyperlink (HTML's "get an element's target"), which
// is not the raw `target` attribute. `own` is the anchor's own attribute value or null; `base` is the
// value of the document's FIRST `<base target>` or null. Two rules the raw read does not model:
//   1. `<base target>` INHERITANCE - an anchor with no target of its own inherits it, so in a
//      `<base target="_blank">` document a link whose attribute is absent still opens an auxiliary
//      context with a live `window.opener`.
//   2. The `<`-COERCION - a name carrying BOTH an ASCII tab-or-newline and a U+003C is what a
//      dangling-markup injection produces, so HTML replaces it with `_blank`. It runs AFTER the base
//      lookup, so an inherited value is coerced too, and BOTH characters are required.
// This is the bundle's single copy of the validator's `effective_link_target`, pinned to it as TEXT
// and over a corpus by the parity test, so the render-time stamp and the `cmh-kql-run` gate cannot
// disagree about which links open a new tab. HTML's "ASCII tab or newline" (Infra) is exactly
// U+0009/U+000A/U+000D, written out as a literal class for the same reason `_OFFLINE_REL_WS_RE` is:
// neither engine's own `\s` is this set.
const _CMH_TARGET_COERCE_WS_RE = /[\t\n\r]/;
function _cmhEffectiveTarget(own, base) {
  // `== null` (not `===`) so an `undefined` from a caller that read a missing property behaves like
  // the absent value rather than reaching `.trim()` as `undefined` and throwing mid-render. Python
  // has only `None`, so the twin's `is not None` is the same test.
  const target = own != null ? own : base;
  if (target == null) return "";
  if (_CMH_TARGET_COERCE_WS_RE.test(target) && target.indexOf("<") !== -1) return "_blank";
  return target;
}
function _cmhBaseTarget(doc) {
  // The FIRST LIVE HTML `<base target>`. The namespace filter is the whole point: a bare CSS type
  // selector matches ANY namespace, so `document.querySelector("base[target]")` returns an
  // `<svg><base target="_self">` - which is a foreign element a browser never treats as a base
  // (`base` is not a foreign breakout tag, so it stays in the SVG namespace) - and an author who
  // wrote one before the real `<base target="_blank">` silently lost the stamp on every link that
  // inherits it, measured in Chromium (#1141). `<template>` and shadow content need no filter here:
  // template content is a separate document fragment and a shadow tree is not in the light DOM, so
  // neither is reachable from this query at all - which is exactly what a browser does too.
  const bases = (doc || document).querySelectorAll("base[target]");
  for (let i = 0; i < bases.length; i++) {
    if (bases[i].namespaceURI === _OFFLINE_HTML_NS) return bases[i].getAttribute("target");
  }
  return null;
}
// Render-time defaults. Two independent concerns:
// - NEW-TAB stamping: open author-facing document references (http/https/file only) in a new
//   tab, ALWAYS (never fragments, UI chrome, or non-document schemes like mailto:/tel:). An
//   author-set target on a document reference (target="_self"/"_top"/a named frame) is OVERRIDDEN
//   to _blank: navigating a document reference in the same tab would strand the reviewer away from
//   the report and their comments, so a new tab is enforced, not merely defaulted.
// - rel ENFORCEMENT (reverse-tabnabbing defense): whenever the EFFECTIVE target is _blank
//   (case-insensitively) on ANY author link - even a data:/blob: link an author pre-set - ensure
//   rel="noopener noreferrer" is present. Effective, not raw: the link may inherit the document's
//   `<base target>`, or carry a name HTML coerces to _blank (#1141), and a `#fragment`, a mailto:
//   or a tel: link is never given a target of its own by the branch above, so those two rules are
//   the only thing that makes them a new tab. This is decoupled from commentability on purpose so
//   a pre-targeted non-reference link is not left without the secure rel. It stays on the `_blank`
//   KEYWORD rather than the gate's broader "opens an auxiliary context": the gate only warns, but
//   this MUTATES the document, and adding `noopener` to a link the author targeted by NAME would
//   stop it reusing the context it named and open a new tab instead.
function stampLinkTargets() {
  const baseTarget = _cmhBaseTarget(document);
  root.querySelectorAll("a[href]").forEach((a) => {
    if (a.closest(".cm-skip")) return; // never touch runtime UI chrome
    if (_cmhCommentableLink(a)) a.setAttribute("target", "_blank");
    const effective = _cmhEffectiveTarget(
      a.hasAttribute("target") ? a.getAttribute("target") : null,
      // Only an HTML anchor INHERITS: HTML's "get an element's target" is defined for an HTML
      // `a`/`area`/`form`, so a foreign `<a>` (an SVG one, which mermaid emits for a clickable
      // node) inherits nothing and navigates the current context. Without this a
      // `<base target="_blank">` document would newly stamp every SVG anchor - and `noreferrer`
      // on a same-tab navigation is not a no-op, it suppresses the Referer. An own `target` on a
      // foreign anchor still reads as before, so no stamp that exists today is taken away.
      a.namespaceURI === _OFFLINE_HTML_NS ? baseTarget : null);
    if (effective.trim().toLowerCase() === "_blank") {
      // HTML tokenizes a `rel` list on ASCII whitespace ONLY, so read it through the bundle's one
      // reading (`_offlineLinkRelTokens`, pinned to the validator's `link_rel_tokens`) rather than
      // a JS `\s` split, which also takes the vertical tab, NBSP and U+FEFF: `rel="noopener<VT>x
      // noreferrer<VT>y"` looked like it already named both, so nothing was stamped and the browser
      // - which reads TWO opaque relations - honored neither and left `window.opener` exposed
      // (#1120). The RAW tokens are what is written back, so an author's casing and any relation
      // they authored survive. The `.trim()` applied to the effective target is deliberately left as
      // the JS one, which is BROADER than HTML whitespace: it only makes this stamp MORE links,
      // never fewer.
      const attr = a.getAttribute("rel");
      const raw = String(attr || "").split(_OFFLINE_REL_WS_RE).filter(Boolean);
      const have = _offlineLinkRelTokens(attr);
      let changed = false;
      ["noopener", "noreferrer"].forEach((t) => {
        if (have.indexOf(t) === -1) { raw.push(t); changed = true; }
      });
      if (changed || !a.hasAttribute("rel")) a.setAttribute("rel", raw.join(" "));
    }
  });
}
function indexLinks() {
  linkEls.length = 0;
  root.querySelectorAll("a[href]").forEach((a) => {
    if (!_cmhCommentableLink(a)) {
      // A document saved or exported by an older runtime carries the marks IT stamped, and this
      // classifier admits a different set. Clearing them is not cosmetic: `findLinkEl` falls back to
      // `[data-cm-link-index="N"]`, so a stale attribute left on a link this runtime does not index
      // would resolve a comment onto it.
      a.classList.remove("cm-link-commentable");
      a.removeAttribute("data-cm-link-index");
      return;
    }
    const i = linkEls.length;
    a.classList.add("cm-link-commentable");
    a.dataset.cmLinkIndex = String(i);
    linkEls.push(a);
  });
}
function findLinkEl(index) {
  if (!/^\d+$/.test(String(index))) return null;
  return linkEls[index] || root.querySelector(`[data-cm-link-index="${index}"]`) || null;
}
// Resolve a link comment to its current element: by index first, then heal by stored
// href if the index is stale (the document re-ordered). Used everywhere a link anchor
// is looked up (highlight, jump, edit, section review) so all consumers relocate the
// same way - not just the highlight restore. The stored key is compared AS WRITTEN against the live
// attribute, read the CURRENT way first and the pre-1.790.0 way only as a fallback, so a record
// either runtime wrote finds its own link and an exact match always wins a stale one. Normalizing
// the STORED side instead would conflate keys that were distinct when they were written: a
// pre-1.790.0 record for `href="&#x1;#frag"` would match a `href="&#x9;#frag"` link, because the
// parser trim empties both paddings, and the comment would silently relocate to a DIFFERENT link.
// The legacy reading has the mirror hazard (it empties the paddings the parser keeps), which is why
// it runs only after the current reading has found nothing.
function resolveLinkEl(comment) {
  if (!comment) return null;
  let a = findLinkEl(comment.linkIndex);
  const key = comment.linkHref;
  if (!key) return a || null;
  const exact = (l) => _cmhLinkHrefKey(l.getAttribute("href")) === key;
  const legacy = (l) => _cmhLegacyLinkHrefKey(l.getAttribute("href")) === key;
  if (!a || !exact(a)) {
    const byHref = linkEls.find(exact);
    if (byHref) a = byHref;
    else if (!a || !legacy(a)) {
      const byLegacy = linkEls.find(legacy);
      if (byLegacy) a = byLegacy;
    }
  }
  return a || null;
}
function linkInfo(a) {
  const i = parseInt(a.dataset.cmLinkIndex, 10) || 0;
  const href = _cmhLinkHrefKey(a.getAttribute("href"));
  const text = (a.textContent || "").replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim();
  const shortHref = href.length > 120 ? href.slice(0, 117) + "..." : href;
  const quote = text || ("link: " + (shortHref || "(no href)"));
  return { linkIndex: i, href, text, quote };
}
function applyLinkHighlight(comment) {
  const a = resolveLinkEl(comment);
  if (!a) return false;
  // A link can carry several comments; track them all in data-cids (first in
  // data-cid for legacy selectors), like the image and mermaid layers.
  a.classList.add("cm-link-hl");
  const cids = (a.getAttribute("data-cids") || "").split(/\s+/).filter(Boolean);
  if (!cids.includes(comment.id)) cids.push(comment.id);
  a.setAttribute("data-cids", cids.join(" "));
  a.setAttribute("data-cid", cids[0]);
  return true;
}
function _linkCids(a) {
  return (a.getAttribute("data-cids") || a.getAttribute("data-cid") || "").split(/\s+/).filter(Boolean);
}
function clearLinkHighlight(id) {
  root.querySelectorAll("a.cm-link-hl").forEach((a) => {
    const cids = _linkCids(a);
    const rest = cids.filter((c) => c !== id);
    if (rest.length === cids.length) return;
    if (rest.length) {
      a.setAttribute("data-cids", rest.join(" "));
      a.setAttribute("data-cid", rest[0]);
    } else {
      a.classList.remove("cm-link-hl", "cm-link-active");
      a.removeAttribute("data-cid");
      a.removeAttribute("data-cids");
    }
  });
}
function flashLink(id) {
  const a = [...root.querySelectorAll("a.cm-link-hl")].find((l) => _linkCids(l).includes(id));
  if (!a) return;
  a.classList.add("cm-link-active");
  setTimeout(() => a.classList.remove("cm-link-active"), 2200);
}
function positionLinkAdd(a) {
  // Anchor to the first line of the link (an inline link can wrap across lines, so
  // getBoundingClientRect would span both; use the first client rect).
  const rects = a.getClientRects();
  const rect = rects.length ? rects[0] : a.getBoundingClientRect();
  const visible = _clipAwareRect(a, rect);
  if (!visible) return false;
  const btnW = linkAddBtn.offsetWidth || 110;
  const btnH = linkAddBtn.offsetHeight || 26;
  const bounds = _floatingBounds(a);
  const left = visible.right - btnW;
  let top = visible.top - btnH - 4;
  if (top < bounds.top) top = visible.bottom + 4;
  linkAddBtn.style.left = _clamp(left, bounds.left, bounds.right - btnW) + "px";
  linkAddBtn.style.top = _clamp(top, bounds.top, bounds.bottom - btnH) + "px";
  return true;
}
function showLinkAddFor(a) {
  const rect = a.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  pendingLink = linkInfo(a);
  if (linkAddHideTimer) { clearTimeout(linkAddHideTimer); linkAddHideTimer = null; }
  linkAddBtn.hidden = false;
  if (!positionLinkAdd(a)) { linkAddBtn.hidden = true; linkActiveEl = null; pendingLink = null; return; }
  setActiveAdd({ el: a, btn: linkAddBtn, position: () => positionLinkAdd(a), clear: () => { pendingLink = null; } });
}
function scheduleHideLinkAdd() {
  if (linkAddHideTimer) clearTimeout(linkAddHideTimer);
  linkAddHideTimer = setTimeout(() => {
    // Keep it visible while the pointer is over the button OR the button itself holds
    // focus, so a keyboard user moving to the button does not have it hidden from under them.
    if (!linkAddBtn.matches(":hover") && document.activeElement !== linkAddBtn) {
      linkAddBtn.hidden = true; linkActiveEl = null; pendingLink = null; clearActiveAdd(linkAddBtn);
    }
  }, 220);
}
function openLinkComposer(info) {
  return createComposerElement({ mode: "new-link", link: info });
}
function setupLinkLayer() {
  if (!linkAddBtn) return;
  stampLinkTargets();
  indexLinks();
  linkEls.forEach((a) => {
    if (!a._cmLinkAttached) {
      a._cmLinkAttached = true;
      a.addEventListener("mouseenter", () => { linkActiveEl = a; showLinkAddFor(a); });
      a.addEventListener("mouseleave", scheduleHideLinkAdd);
      // Keyboard focus reveals the affordance too. Enter and Space keep their native
      // behavior (Enter follows the link, Space scrolls), so the only keyboard comment
      // entry point is the non-navigating Alt+Enter chord below - a normal activation
      // still navigates.
      a.addEventListener("focus", () => { linkActiveEl = a; showLinkAddFor(a); });
      a.addEventListener("blur", scheduleHideLinkAdd);
      a.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
          e.preventDefault();
          linkAddBtn.hidden = true;
          linkActiveEl = null;
          openLinkComposer(linkInfo(a));
        }
      });
    }
  });
  comments.forEach((c) => { if (c.anchorType === "link") applyLinkHighlight(c); });
}
if (linkAddBtn) {
  linkAddBtn.addEventListener("mouseenter", () => {
    if (linkAddHideTimer) { clearTimeout(linkAddHideTimer); linkAddHideTimer = null; }
  });
  linkAddBtn.addEventListener("focus", () => {
    if (linkAddHideTimer) { clearTimeout(linkAddHideTimer); linkAddHideTimer = null; }
  });
  linkAddBtn.addEventListener("mouseleave", scheduleHideLinkAdd);
  linkAddBtn.addEventListener("blur", scheduleHideLinkAdd);
  linkAddBtn.addEventListener("click", () => {
    if (!pendingLink) return;
    const info = pendingLink;
    pendingLink = null;
    linkAddBtn.hidden = true;
    linkActiveEl = null;
    openLinkComposer(info);
  });
}
