/* ---------- Callout accessibility affordance (CMH-CALLOUT-03) ---------- */
// A cmh-callout differs from its neighbors only by color, which fails color-blind readers,
// grayscale printouts, and screen readers. The CSS adds a per-variant ::before glyph (the
// non-color signal); this pass adds role="note" plus a variant aria-label so assistive tech
// announces the kind. When the author already opened the callout with a <strong> label
// (e.g. "Bottom line."), the aria-label is suppressed so the variant is not announced twice.
(function () {
  const root = document.getElementById("commentRoot") || document.body;
  if (!root) return;
  const LABELS = { info: "Note", success: "Success", warning: "Warning", danger: "Important" };
  root.querySelectorAll(".cmh-callout").forEach(function (el) {
    if (el.closest(".cm-skip")) return;
    if (!el.hasAttribute("role")) el.setAttribute("role", "note");
    if (el.hasAttribute("aria-label")) return; // respect an explicit author label
    let variant = null;
    for (const v in LABELS) { if (el.classList.contains("cmh-callout-" + v)) { variant = v; break; } }
    if (!variant) return;
    // A leading <strong> is the authored visible label; keep it as the sole announcement.
    const first = el.querySelector(":scope > p:first-child > strong:first-child, :scope > strong:first-child");
    if (first && (first.textContent || "").trim()) return;
    el.setAttribute("aria-label", LABELS[variant]);
  });
})();
