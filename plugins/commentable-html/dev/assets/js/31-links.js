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

// Author-facing reference links only: real href, not UI chrome, not an in-page
// fragment (those navigate within the document, so a new tab would be wrong and
// commenting on a TOC entry is not the intent). Classification is by the browser-
// NORMALIZED protocol (a.protocol), not a string match on the raw href, so an
// obfuscated scheme (java\tscript:, embedded control chars) cannot slip past: only
// real document references are eligible - http/https, or a relative/root-relative
// URL that inherits the document's http(s)/file protocol. Everything else
// (javascript:, mailto:, tel:, data:, blob:, ...) is excluded, so a mailto/tel link
// is never stamped target=_blank (which would strand the reader on a dead tab).
function _cmhCommentableLink(a) {
  if (!a || a.tagName !== "A" || !a.hasAttribute("href")) return false;
  if (a.closest(".cm-skip")) return false;
  const raw = (a.getAttribute("href") || "").trim();
  if (!raw || raw.charAt(0) === "#") return false; // same-page fragment
  let proto = "";
  try { proto = new URL(a.href, document.baseURI).protocol.toLowerCase(); }
  catch (e) { proto = (a.protocol || "").toLowerCase(); }
  return proto === "http:" || proto === "https:" || proto === "file:";
}
// Render-time defaults. Two independent concerns:
// - NEW-TAB stamping: open author-facing document references (http/https/file only) in a new
//   tab by default (never fragments, UI chrome, or non-document schemes like mailto:/tel:).
// - rel ENFORCEMENT (reverse-tabnabbing defense): whenever the effective target is _blank
//   (case-insensitively) on ANY author link - even a data:/blob: link an author pre-set - ensure
//   rel="noopener noreferrer" is present. This is decoupled from commentability on purpose so a
//   pre-targeted non-reference link is not left without the secure rel.
function stampLinkTargets() {
  root.querySelectorAll("a[href]").forEach((a) => {
    if (a.closest(".cm-skip")) return; // never touch runtime UI chrome
    if (_cmhCommentableLink(a) && !a.getAttribute("target")) a.setAttribute("target", "_blank");
    if ((a.getAttribute("target") || "").trim().toLowerCase() === "_blank") {
      const rel = (a.getAttribute("rel") || "").split(/\s+/).filter(Boolean);
      let changed = false;
      ["noopener", "noreferrer"].forEach((t) => { if (rel.indexOf(t) === -1) { rel.push(t); changed = true; } });
      if (changed || !a.hasAttribute("rel")) a.setAttribute("rel", rel.join(" "));
    }
  });
}
function indexLinks() {
  linkEls.length = 0;
  root.querySelectorAll("a[href]").forEach((a) => {
    if (!_cmhCommentableLink(a)) return;
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
// same way - not just the highlight restore.
function resolveLinkEl(comment) {
  if (!comment) return null;
  let a = findLinkEl(comment.linkIndex);
  if ((!a || (comment.linkHref && a.getAttribute("href") !== comment.linkHref)) && comment.linkHref) {
    const byHref = linkEls.find((l) => l.getAttribute("href") === comment.linkHref);
    if (byHref) a = byHref;
  }
  return a || null;
}
function linkInfo(a) {
  const i = parseInt(a.dataset.cmLinkIndex, 10) || 0;
  const href = (a.getAttribute("href") || "").replace(/[\r\n\t]+/g, " ").trim();
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
  _activeAdd = { el: a, btn: linkAddBtn, position: () => positionLinkAdd(a), clear: () => { pendingLink = null; } };
}
function scheduleHideLinkAdd() {
  if (linkAddHideTimer) clearTimeout(linkAddHideTimer);
  linkAddHideTimer = setTimeout(() => {
    // Keep it visible while the pointer is over the button OR the button itself holds
    // focus, so a keyboard user moving to the button does not have it hidden from under them.
    if (!linkAddBtn.matches(":hover") && document.activeElement !== linkAddBtn) {
      linkAddBtn.hidden = true; linkActiveEl = null; pendingLink = null;
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
