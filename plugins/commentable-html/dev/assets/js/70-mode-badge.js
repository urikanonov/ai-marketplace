/* ---------- Mode badge + asset-version handshake ---------- */
function assetBannerDismissKey(pageVer, runtimeVer) {
  return "commentable-html::assetBannerDismissed::" + COMMENT_KEY + "::" + String(pageVer || "")
    + "::" + String(runtimeVer || "");
}
function assetBannerDismissed(key) {
  if (!key) return false;
  try { return localStorage.getItem(key) === "1"; } catch (e) { return false; }
}
function ensureAssetBannerChrome(b) {
  let msgEl = b.querySelector(".cmh-asset-message");
  let btn = b.querySelector(".cmh-asset-dismiss");
  if (!msgEl) {
    const current = b.innerHTML;
    b.innerHTML = '<span class="cmh-asset-message"></span>'
      + '<button type="button" class="cmh-asset-dismiss cm-skip" aria-label="Dismiss">X</button>';
    msgEl = b.querySelector(".cmh-asset-message");
    btn = b.querySelector(".cmh-asset-dismiss");
    if (msgEl) msgEl.innerHTML = current;
  }
  if (btn && !btn.dataset.cmhBound) {
    btn.dataset.cmhBound = "1";
    btn.addEventListener("click", function () {
      const key = b.dataset.cmhDismissKey || "";
      if (key) {
        try { localStorage.setItem(key, "1"); } catch (e) { /* ignore */ }
      }
      b.hidden = true;
    });
  }
  return msgEl;
}
function revealAssetBanner(msg, pageVer, runtimeVer) {
  const b = document.getElementById("cmhAssetBanner");
  if (!b) return;
  const key = (pageVer || runtimeVer) ? assetBannerDismissKey(pageVer, runtimeVer) : "";
  if (assetBannerDismissed(key)) {
    b.hidden = true;
    return;
  }
  const msgEl = ensureAssetBannerChrome(b);
  if (msg && msgEl) msgEl.innerHTML = msg;
  b.dataset.cmhDismissKey = key;
  b.hidden = false;
}
function versionBannerMessage(label, pageVer, runtimeVer) {
  const compat = runtimeCompatibleWith(pageVer, runtimeVer);
  const pageHtml = '<code>' + escapeHtml(pageVer) + '</code>';
  const runtimeHtml = '<code>' + escapeHtml(runtimeVer) + '</code>';
  if (compat && compat.kind === "compatible") return null;
  if (compat && compat.kind === "major") {
    return "Commentable-html version mismatch: " + label + " was generated for commentable-html "
      + '<code>' + compat.page.major + ".x</code> but the loaded runtime is " + runtimeHtml
      + "; they are not compatible. Regenerate the document or restore a matching runtime.";
  }
  if (compat && compat.kind === "runtime-older") {
    return "Commentable-html version notice: " + label + " expects a newer commentable-html "
      + pageHtml + " than the loaded runtime " + runtimeHtml
      + "; update the companion files or refresh with cache disabled.";
  }
  if (String(pageVer || "") !== String(runtimeVer || "")) {
    return "Commentable-html version mismatch: " + label + " expects assets "
      + pageHtml + " but the loaded runtime is " + runtimeHtml
      + ". Refresh with cache disabled, or update the companion files.";
  }
  return null;
}
function maybeRevealVersionBanner(label, pageVer, runtimeVer) {
  if (!pageVer || !runtimeVer) return false;
  const msg = versionBannerMessage(label, pageVer, runtimeVer);
  if (!msg) return false;
  revealAssetBanner(msg, pageVer, runtimeVer);
  return true;
}
let _embeddedSigCache = null;
// Map of embedded comment id -> a content signature (updatedAt, else createdAt) so the
// "Standalone with comments" state reflects the embedded CONTENT, not just id presence:
// editing a comment bumps its updatedAt, so a stale embedded copy no longer counts.
function _embeddedCommentSig() {
  if (!_embeddedSigCache) {
    _embeddedSigCache = new Map();
    getEmbeddedComments().forEach(function (c) {
      // Use the same id-universe as mergeCommentSets (which drops unsafe ids from the
      // live set), otherwise an unsafe embedded id looks like a "deleted in session"
      // comment and falsely flips the badge to Not portable.
      if (c && c.id && SAFE_ID_RE.test(c.id)) _embeddedSigCache.set(c.id, c.updatedAt || c.createdAt || "");
    });
  }
  return _embeddedSigCache;
}
// The document is either "Portable" (self-contained and safe to share: assets embedded
// and every current comment embedded, or none) or "Not portable" (it references external
// skill/companion resources, and/or has comments that are not embedded in the file). The
// bubble hover explains WHY a file is not portable.
function isOfflineDocument() {
  const script = document.getElementById("commentableHtmlLayer");
  if (script) {
    try {
      const data = JSON.parse((script.textContent || "").trim() || "{}");
      if (data && data.mode === "offline") return true;
    } catch (e) { /* malformed descriptors are handled by validate.py */ }
  }
  return !!document.querySelector("#commentRoot [data-cm-offline-chart]");
}
function currentDocState() {
  const reasons = [];
  if (NONPORTABLE_MODE) reasons.push("it references external skill / companion resources");
  if (typeof widgetStateChanges === "function" && widgetStateChanges().length > 0) {
    reasons.push("a widget's layout was changed in this session and is not saved into the file");
  }
  if (typeof checklistChanges === "function" && checklistChanges().length > 0) {
    reasons.push("a checklist's state was changed in this session and is not saved into the file");
  }
  if (typeof notesChanges === "function" && notesChanges().length > 0) {
    reasons.push("a notes field was edited in this session and is not saved into the file");
  }
  const emb = _embeddedCommentSig();
  if (comments.length > 0) {
    const hasUnembedded = !comments.every(function (c) {
      return emb.has(c.id) && emb.get(c.id) === (c.updatedAt || c.createdAt || "");
    });
    if (hasUnembedded) reasons.push("it has comments that are not embedded in the file");
  }
  // Embedded comments that are neither live nor marked handled still sit in the file even
  // though they were deleted in this session: sharing the file as-is would show them. The
  // file is stale (not portable) until re-exported.
  if (emb.size > 0) {
    const handled = getHandledIds();
    const liveIds = new Set(comments.map(function (c) { return c.id; }));
    let hasStale = false;
    emb.forEach(function (_sig, id) { if (!liveIds.has(id) && !handled.has(id)) hasStale = true; });
    if (hasStale) reasons.push("it still contains embedded comments that were removed in this session (re-export to drop them from the file)");
  }
  if (reasons.length === 0) {
    if (isOfflineDocument()) {
      return { type: "Offline", reason: "Offline: self-contained and works with no network - the review layer, styles, charts, and diagrams are all embedded in this one file." };
    }
    return { type: "Portable", reason: "Portable: self-contained and safe to share (assets embedded and every comment embedded)." };
  }
  return { type: "Not portable", reason: "Not portable because " + reasons.join(", and ") + ". Use Export as Portable to share it." };
}
function updateDocTypeUi() {
  const st = currentDocState();
  ["cmTypeBadge", "cmhModeBadge"].forEach(function (id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = st.type;
    el.setAttribute("data-doc-type", st.type);
    el.setAttribute("aria-label", st.reason);
    // If the tooltip layer already adopted this control (title moved to data-cmh-tip),
    // update the managed attributes in place so the new reason shows without a native-title
    // flash; otherwise set title and let the tooltip layer adopt it on first hover.
    if (el.hasAttribute("data-cmh-tip")) {
      el.setAttribute("data-cmh-tip", st.reason);
      el.removeAttribute("title");
    } else {
      el.title = st.reason;
    }
  });
}
function setupModeUi() {
  const ver = document.getElementById("cmVersion");
  if (ver) ver.textContent = "v" + CMH_VERSION;
  const meta = document.querySelector(".cm-sidebar .head-meta");
  if (meta && !meta.querySelector(".cm-brand-icon")) meta.insertAdjacentHTML("afterbegin", cmBrandLink(CMH_ICON_SVG));
  if (NONPORTABLE_MODE) {
    document.body.classList.add("cm-nonportable");
    // In nonportable (companion) mode the portability action embeds everything into one file.
    ["btnSaveHtml", "btnSaveHtmlTop"].forEach(function (id) {
      const b = document.getElementById(id);
      if (b) {
        // Preserve each button's icon + label span; the sidebar button uses the compact
        // "Portable" label, the overflow-menu item keeps the full "Export as Portable".
        const span = b.querySelector("span");
        const label = (id === "btnSaveHtmlTop") ? "Export as Portable" : "Portable";
        if (span) span.textContent = label; else b.textContent = label;
        b.title = "Download one self-contained, portable HTML with the commentable-html assets AND the current comments embedded, so it no longer depends on the skill folder or companion files.";
      }
    });
  }
  updateDocTypeUi();
  // Version handshake: the document declares the asset version it was generated
  // against. Same-major newer runtimes are compatible; older or breaking-major
  // runtimes warn rather than fail silently. Version strings are HTML-escaped since
  // they originate from an author-controlled <meta> / companion file.
  const declared = declaredAssetVersion();
  if (maybeRevealVersionBanner("this page", declared, CMH_VERSION)) {
    return;
  } else if (CMH_ASSETS && maybeRevealVersionBanner("the assets file", CMH_ASSETS.version, CMH_VERSION)) {
    return;
  } else {
    // No mismatch: make sure a banner the bootstrap watchdog may have raced to
    // show (slow-but-successful load) is hidden now that the runtime is up.
    const b = document.getElementById("cmhAssetBanner");
    if (b) b.hidden = true;
  }
}

