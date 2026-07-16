/* ---------- Callout accessibility affordance (CMH-CALLOUT-03) ---------- */
// A cmh-callout differs from its neighbors only by color, which fails color-blind readers,
// grayscale printouts, and screen readers. The CSS adds a per-variant ::before glyph (the
// non-color signal); this pass adds role="note" plus a variant aria-label so assistive tech
// announces the kind. When the author already opened the callout with a <strong> label
// (e.g. "Bottom line."), the aria-label is suppressed so the variant is not announced twice.
(function () {
  const root = document.getElementById("commentRoot") || document.body;
  if (!root) return;
  const LABELS = { info: "Note", success: "Success", warning: "Warning", danger: "Danger" };
  // The first meaningful child node of a container (skips whitespace text AND empty wrapper
  // elements like a stray leading <p></p>), or null.
  function firstMeaningfulChild(container) {
    for (let n = container.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3) { if ((n.textContent || "").trim() === "") continue; return n; }
      if (n.nodeType === 1) { if ((n.textContent || "").trim() === "") continue; return n; }
    }
    return null;
  }
  // True only when the callout OPENS with a <strong> label (directly, or as the first thing in its
  // first paragraph). Mid-sentence bold ("Watch out, <strong>Warning:</strong>") must NOT count,
  // so we check the FIRST meaningful node, not merely the first <strong> element.
  function startsWithStrongLabel(el) {
    let node = firstMeaningfulChild(el);
    if (node && node.nodeType === 1 && node.tagName === "P") node = firstMeaningfulChild(node);
    return !!(node && node.nodeType === 1 && node.tagName === "STRONG" && (node.textContent || "").trim());
  }
  root.querySelectorAll(".cmh-callout").forEach(function (el) {
    if (el.closest(".cm-skip")) return;
    if (!el.hasAttribute("role")) el.setAttribute("role", "note");
    if (el.hasAttribute("aria-label")) return; // respect an explicit author label
    let variant = null;
    for (const v in LABELS) { if (el.classList.contains("cmh-callout-" + v)) { variant = v; break; } }
    if (!variant) return;
    if (startsWithStrongLabel(el)) return; // authored visible label is the sole announcement
    el.setAttribute("aria-label", LABELS[variant]);
  });
})();
