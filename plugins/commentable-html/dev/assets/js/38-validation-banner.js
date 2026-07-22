/* ---------- Unvalidated-document fallback banner (CMH-STAMP-03, default ON) ----------
   A last-resort visible signal. If a document carries a `commentable-html-created` stamp (it was
   produced by the tooling) but no current `commentable-html-validated` stamp (validate.py writes
   that only on a strict-clean pass), show a small dismissible amber banner. The skill MUST always
   finalize and strict-validate before handoff, so this should NEVER appear; when it does, the
   document was shipped without validation and may be incomplete. The banner is `cm-skip` chrome and
   is added to CMH_INJECTED_CHROME so it never bakes into a Save/Export snapshot - it is re-derived
   on load, so an exported-but-unvalidated document still shows it. */
function _cmhMetaContent(name) {
  const m = document.querySelector('meta[name="' + name + '"]');
  return m ? (m.getAttribute("content") || "") : "";
}
function _cmhValidationStale(validated, created) {
  const v = Date.parse(validated), c = Date.parse(created);
  if (isNaN(v) || isNaN(c)) return false; // an unparseable stamp is not treated as stale (no nag)
  return v < c;
}
// True when the document carries a content-bound validated stamp (commentable-html-validated-hash)
// whose hash no longer matches the live content - i.e. the document was strict-validated and THEN
// manually edited. Fails SAFE: with no stamped hash (an older document, or one with no content
// root) or when the runtime hasher is unavailable, it returns false so the banner falls back to the
// timestamp signal and never false-positives on a genuinely validated document.
function _cmhValidationContentChanged() {
  const stampedHash = _cmhMetaContent("commentable-html-validated-hash");
  if (!stampedHash) return false;
  if (typeof cmhDocContentHash !== "function") return false;
  try {
    return cmhDocContentHash() !== stampedHash;
  } catch (e) {
    return false;
  }
}
function setupValidationBanner() {
  const created = _cmhMetaContent("commentable-html-created");
  if (!created) return; // only a tooling-produced document is expected to carry a validation stamp
  const validated = _cmhMetaContent("commentable-html-validated");
  // Show nothing only for a strict-validated document whose stamped content still matches: the
  // stamp must be present, not older than creation, and (when content-bound) still hash-current.
  if (validated && !_cmhValidationStale(validated, created) && !_cmhValidationContentChanged()) return;
  const banner = document.createElement("div");
  banner.className = "cm-skip cmh-unvalidated-banner";
  banner.setAttribute("role", "status");
  const msg = document.createElement("span");
  msg.className = "cmh-unvalidated-msg";
  msg.textContent = "This document was not validated in its current form and may be incomplete. Run "
    + "tools/validate/validate.py --strict <file> (or tools/authoring/finalize.py <file> --strict) to re-validate.";
  const dismiss = document.createElement("button");
  dismiss.type = "button";
  dismiss.className = "cmh-unvalidated-dismiss";
  dismiss.setAttribute("aria-label", "Dismiss the not-validated notice");
  dismiss.textContent = "\u00d7";
  dismiss.addEventListener("click", () => { banner.remove(); });
  banner.appendChild(msg);
  banner.appendChild(dismiss);
  document.body.appendChild(banner);
  CMH_INJECTED_CHROME.add(banner);
}
