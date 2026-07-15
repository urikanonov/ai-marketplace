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
function setupValidationBanner() {
  const created = _cmhMetaContent("commentable-html-created");
  if (!created) return; // only a tooling-produced document is expected to carry a validation stamp
  const validated = _cmhMetaContent("commentable-html-validated");
  if (validated && !_cmhValidationStale(validated, created)) return; // strict-validated: show nothing
  const banner = document.createElement("div");
  banner.className = "cm-skip cmh-unvalidated-banner";
  banner.setAttribute("role", "status");
  const msg = document.createElement("span");
  msg.className = "cmh-unvalidated-msg";
  msg.textContent = "This document was not validated and may be incomplete. Run "
    + "tools/authoring/finalize.py <file> --strict, then tools/validate/validate.py --strict <file>.";
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
