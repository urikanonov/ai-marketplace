(() => {
// Pristine snapshot of the document, captured before any DOM mutation
// (mermaid render, restored highlights, dynamic composers, etc). Used as a
// fallback by "Export as Portable" when fetch() of the page URL is unavailable
// (e.g., file://, blocked fetch, or CSP). The snapshot is taken on the very first line
// of the IIFE so it predates every runtime change this script makes.
const SNAPSHOT_HTML = "<!DOCTYPE html>\n" + document.documentElement.outerHTML;
// The layer runs synchronously during parse, so SNAPSHOT_HTML stops at THIS <script>:
// host content placed after the layer (per charts.md, chart data + init scripts land
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

