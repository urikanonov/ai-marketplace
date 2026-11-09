/* ---------- Storage-constrained read-only mode ---------- */
const CMH_READ_ONLY_MESSAGE = "This document is read-only because browser storage was unavailable. "
  + "Review changes and file exports are disabled. Download the original HTML using your viewer's Download button "
  + "and open it locally in your browser to review.";
const CMH_READ_ONLY_SELECTOR = [
  "#contextMenu button", "#btnClearAll", "#btnClearAllTop", "#btnClearSelected",
  ".cm-storage-manager .cm-storage-danger",
  "#btnSaveHtml", "#btnSaveHtmlTop", "#btnSavePlain", "#btnSavePlainTop",
  "#btnExportOffline", "#btnExportOfflineTop", "#btnExportMd", "#btnExportMdTop",
  ".cmh-note-input", ".cmh-check", ".cmh-review-badge", ".cm-widget-reset",
  ".cmh-editable-table :is(button:not(.cmh-table-copy-draft),input,textarea,select,summary,.cmh-table-resize)",
  ".cmh-table-recovery button:not(.cmh-table-copy-draft)",
  ".cmh-table-dialog :is(input,select,button[type=submit])",
  ".cm-composer :is(input,textarea,select,button:not([data-act=cancel]))",
  ".cm-reply-input", ".cm-reply-compose button:not(.cm-reply-cancel)", ".cm-comment-popover-input",
  ".cm-comment-popover-edit button:not([data-act=edit-cancel])",
  ":is(#commentList,.cm-comment-popover) :is([data-act=reply],[data-act=reply-edit],[data-act=reply-del],"
    + "[data-act=edit],[data-act=del],[data-act=popover-del],[data-act=edit-save],[data-act=reattach],"
    + "[data-act=state-reset],[data-act=cl-reset],[data-act=note-reset],[data-act=table-reset])",
].join(",");
const _cmhReadOnlyControls = new Map();
function cmhShowReadOnlyNotice() {
  showToast(CMH_READ_ONLY_MESSAGE, { alert: true, duration: 8000 });
}
function cmhRestrictReviewControls(node) {
  if (!node.querySelectorAll) return;
  const controls = [...node.querySelectorAll(CMH_READ_ONLY_SELECTOR)];
  if (node.matches && node.matches(CMH_READ_ONLY_SELECTOR)) controls.push(node);
  controls.forEach(function (el) {
    if (!_cmhReadOnlyControls.has(el)) {
      const saved = {};
      ["disabled", "readonly", "tabindex", "aria-disabled", "title"].forEach(function (name) {
        saved[name] = el.getAttribute(name);
      });
      _cmhReadOnlyControls.set(el, saved);
    }
    if (el.matches("textarea,input:not([type=checkbox]):not([type=radio]):not([type=button])")) {
      if (!el.readOnly) el.readOnly = true;
    } else if ("disabled" in el) {
      if (!el.disabled) el.disabled = true;
    } else if (el.tabIndex !== -1) el.tabIndex = -1;
    if (el.getAttribute("aria-disabled") !== "true") el.setAttribute("aria-disabled", "true");
    if (el.title !== CMH_READ_ONLY_MESSAGE) el.title = CMH_READ_ONLY_MESSAGE;
  });
}
function cmhUpdateReadOnlyMode() {
  const readonly = cmhReviewReadOnly();
  document.body.classList.toggle("cm-review-read-only", readonly);
  if (readonly) {
    hideMenu();
    cmhRestrictReviewControls(document);
  } else {
    const restoring = _cmhReadOnlyControls.size > 0;
    _cmhReadOnlyControls.forEach(function (attrs, el) {
      Object.keys(attrs).forEach(function (name) {
        if (attrs[name] === null) el.removeAttribute(name);
        else el.setAttribute(name, attrs[name]);
      });
    });
    _cmhReadOnlyControls.clear();
    if (restoring) editableTables.forEach(function (t) {
      if (!t.stale && _etUnreadable === null) _etHistoryButtons(t);
    });
  }
}
function setupReadOnlyMode() {
  _cmhReadOnlyReady = true;
  cmhUpdateReadOnlyMode();
  new MutationObserver(function (records) {
    if (!cmhReviewReadOnly()) return;
    records.forEach(function (record) {
      if (record.type === "attributes") cmhRestrictReviewControls(record.target);
      else record.addedNodes.forEach(cmhRestrictReviewControls);
    });
  }).observe(document.body, {
    subtree: true, childList: true, attributes: true,
    attributeFilter: ["disabled", "readonly", "tabindex", "aria-disabled"],
  });
  function block(e) {
    if (!cmhReviewReadOnly()) return;
    const control = e.target.closest && e.target.closest(CMH_READ_ONLY_SELECTOR);
    if (!control) return;
    const text = control.matches("textarea,input:not([type=checkbox]):not([type=radio]):not([type=button])");
    if (text) {
      if (e.type === "keydown") {
        if (["Tab", "Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"].includes(e.key)
            || ((e.ctrlKey || e.metaKey) && ["a", "c"].includes(e.key.toLowerCase()))) return;
      } else if (!["beforeinput", "input", "change"].includes(e.type)) return;
    }
    e.preventDefault();
    e.stopImmediatePropagation();
    if (e.type === "click" || e.type === "keydown") cmhShowReadOnlyNotice();
  }
  ["pointerdown", "click", "keydown", "beforeinput", "input", "change"].forEach(function (type) {
    window.addEventListener(type, block, true);
  });
  window.addEventListener("focus", function () {
    if (!cmhReviewReadOnly() || _cmhInitialStorageReadFailed) return;
    if (_cmhPendingWrites.size) {
      cmhRetryPendingWrites();
      if (_cmhStorageIssue === "quota") cmhStorageFullToast(_cmhPendingWrites.keys().next().value, "Changes");
    }
    if (!_cmhPendingWrites.size) setupStorageNotice();
  });
}
function cmhAssertDownloadAllowed() {
  if (cmhReviewReadOnly()) throw new Error(CMH_READ_ONLY_MESSAGE);
}
