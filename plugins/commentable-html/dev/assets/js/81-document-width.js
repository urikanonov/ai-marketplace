/* ---------- Per-document reading width (flow documents only) ---------- */
function setupDocumentWidth() {
  if (IS_DECK) return;
  const shell = root.closest(".app") || root;
  shell.classList.add("cm-document-width-shell");
  function authoredWidth() {
    // Measure authored layout without the reader preference or desktop sidebar gutter override.
    const sidebarOpen = document.body.classList.contains("sidebar-open");
    const sheet = style.sheet;
    sheet.disabled = true;
    if (sidebarOpen) document.body.classList.remove("sidebar-open");
    try {
      const raw = getComputedStyle(shell).maxWidth;
      return /^\d+(?:\.\d+)?px$/.test(raw) ? parseFloat(raw) : (shell.getBoundingClientRect().width || 1800);
    } finally {
      if (sidebarOpen) document.body.classList.add("sidebar-open");
      sheet.disabled = false;
    }
  }
  const minimum = 800, maximum = 3000, step = 100;
  const style = document.createElement("style");
  style.className = "cm-document-width-style";
  document.body.appendChild(style);
  const groups = [];
  let width = authoredWidth();
  let pinned = false;
  let toolbarHeight = 0;

  function savedWidth() {
    const raw = cmhReadPref(DOCUMENT_WIDTH_KEY);
    if (!raw || !/^\d+$/.test(raw)) return null;
    const value = Number(raw);
    return value >= minimum && value <= maximum && value % step === 0 ? value : null;
  }
  function apply(value) {
    pinned = value !== null;
    if (pinned) width = value;
    else width = authoredWidth();
    // Keep this screen-only and runtime-injected: print and the authored export snapshot
    // must not inherit a browser-local reading preference.
    const selector = ".cm-document-width-shell";
    const override = value === null ? "" : selector + " { max-width: " + width + "px !important; }"
      + (shell === root ? "" : "@media (min-width: 1100px) { body.sidebar-open " + selector + " { max-width: none !important; } }");
    style.textContent = "@media screen { :root { --cm-doc-max-width: " + width + "px; --cm-toolbar-height: " + toolbarHeight + "px; } "
      + override + " }";
    groups.forEach(function (group) {
      group.output.textContent = Math.round(width) + "px";
      group.minus.disabled = width <= minimum;
      group.plus.disabled = width >= maximum;
    });
    hideChartTooltip();
    root.querySelectorAll(CMH_CHART_DATA_SEL).forEach(function (canvas) {
      if (canvas._cmhChart) renderInteractiveChart(canvas, -1);
    });
  }
  function change(direction) {
    const snapped = direction > 0 ? Math.floor(width / step) + 1 : Math.ceil(width / step) - 1;
    const next = Math.max(minimum, Math.min(maximum, snapped * step));
    apply(next);
    if (!cmhWritePref(DOCUMENT_WIDTH_KEY, String(next))) {
      showToast("Could not save document width - this browser's storage is full or blocked.", { alert: true });
    }
  }
  function addControls(host) {
    if (!host) return;
    const group = document.createElement("div");
    group.className = "cm-document-width cm-skip";
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", "Document maximum width");
    const label = document.createElement("span");
    label.textContent = "Width";
    function button(text, name, direction) {
      const el = document.createElement("button");
      el.type = "button";
      el.textContent = text;
      el.setAttribute("aria-label", name);
      el.title = name + " by 100px (800-3000px)";
      el.addEventListener("click", function () { change(direction); });
      cmhMarkLayerChrome(el);
      return el;
    }
    const minus = button("-", "Decrease document width", -1);
    const output = document.createElement("output");
    output.setAttribute("role", "status");
    output.setAttribute("aria-label", "Document maximum width");
    const plus = button("+", "Increase document width", 1);
    group.append(label, minus, output, plus);
    host.appendChild(group);
    groups.push({ output, minus, plus });
  }
  const toolbarToggle = cmhEl("btnToggleSidebar");
  const toolbar = toolbarToggle && toolbarToggle.closest(".cm-toolbar");
  addControls(toolbar);
  if (toolbar) toolbarHeight = toolbar.getBoundingClientRect().height;
  const sidebar = cmhLayerBlock(document, "sidebar");
  const header = sidebar && sidebar.querySelector("header");
  addControls(header && header.querySelector(".head-aux"));
  apply(savedWidth());
  function refreshLayout() {
    const height = toolbar && toolbar.getBoundingClientRect().height;
    const toolbarChanged = height > 0 && height !== toolbarHeight;
    if (toolbarChanged) toolbarHeight = height;
    if (toolbarChanged || (!pinned && authoredWidth() !== width)) apply(pinned ? width : null);
  }
  window.addEventListener("resize", refreshLayout);
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(refreshLayout);
    observer.observe(shell);
    if (toolbar) observer.observe(toolbar);
  }
  window.addEventListener("storage", function (event) {
    if (event.key === null || event.key === DOCUMENT_WIDTH_KEY) apply(savedWidth());
  });
}
