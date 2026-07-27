// Freeze the volatile BUILD STAMPS in the review layer before a tutorial screenshot (dev-only).
//
// The runtime paints two values into its own UI that change on a release without any behavior
// change: the version badge (`v1.255.0`, in the sidebar head, the toolbar menu, the footer and the
// Help/About panel) and the "Generated on" date (from the document's build-stamped `data-generated`,
// or `document.lastModified` when the author set none - volatile per checkout). Left alone they
// force every stamped screenshot to be re-rendered on every version bump - or, worse, buy the drift
// gate a permanent pixel allowance big enough to hide a real regression (issue #710). Freezing them
// to fixed placeholders keeps the committed PNGs stable across releases, so the comparison can
// demand ZERO differing pixels. Both sides of every comparison capture through this same path, so
// the gate compares frozen against frozen.
//
// The freeze is deliberately NARROW: only the elements the runtime stamps those two values into, and
// only the value inside them. A blanket walk of the page would also rewrite rendered comment text
// and any other layer copy that happened to look like a stamp, masking exactly the regressions this
// gate exists to catch. Each label is kept, and a value that is not a real rendered date (`unknown`,
// a malformed stamp) is left alone so it still moves the shot. What IS deliberately un-gated by this
// is the date VALUE itself: a change in how the date is formatted will not fail a screenshot (it is
// covered by the sidebar's own tests instead).
export const STAMP_VERSION = "1.x";
export const STAMP_DATE = "Jan 1, 2026";

// Where the runtime stamps the version: the sidebar head badge (70-mode-badge.js), the toolbar menu
// badge (55-toolbar-menu.js), the footer (95-startup.js), and the Help heading + About paragraph
// (75-help.js), where it sits inside a longer sentence beside an inline SVG - hence a text-node
// substitution rather than a textContent assignment. (The version also appears in tooltip/aria
// attributes on the brand icon, which paint no pixels in a shot, so they are left alone.)
export const VERSION_SELECTOR = "#cmVersion, .cm-version, .cm-footer-ver, .cm-help-head h2, .cm-help-about p";
// Where it stamps the generated date: the sidebar info line (50-sidebar.js) and the footer.
export const DATE_SELECTOR = "#cmGenerated, .cm-footer-gen";

// Runs in the browser: no closure over module scope, so it survives being serialized to evaluate().
function freezeInPage({ version, stampVersion, stampDate, versionSelector, dateSelector }) {
  const content = document.getElementById("commentRoot");
  const textNodes = (el) => {
    const out = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) out.push(node);
    return out;
  };
  const authored = (el) => !!(content && content.contains(el));
  let frozen = 0;
  if (version) {
    for (const el of document.querySelectorAll(versionSelector)) {
      if (authored(el)) continue;
      for (const node of textNodes(el)) {
        if (node.nodeValue.indexOf(version) === -1) continue;
        node.nodeValue = node.nodeValue.split(version).join(stampVersion);
        frozen += 1;
      }
    }
  }
  for (const el of document.querySelectorAll(dateSelector)) {
    if (authored(el)) continue;
    for (const node of textNodes(el)) {
      // The two label forms the runtime renders, matched exactly so an ambiguous prefix cannot be
      // mis-split. The label is preserved and only the value replaced, so rewording the label stays
      // a visible change.
      const dated = node.nodeValue.match(/^(\s*)(Generated on:|Generated)\s+(\S.*?)\s*$/);
      if (!dated) continue;
      const value = dated[3];
      if (value === stampDate) continue;
      // Only a value the runtime itself could have RENDERED is replaced. Date.parse alone is far too
      // lenient (Chromium accepts "0" and silently rolls "Feb 31, 2026" over into March), so the
      // value is re-rendered with the same options formatTime uses for a date-only stamp and must
      // come back identical. An "unknown", a malformed or impossible date, or a stamp rendered in
      // some other shape is therefore left alone and still moves the shot.
      const parsed = Date.parse(value);
      if (!Number.isFinite(parsed)) continue;
      const rendered = new Date(parsed).toLocaleDateString(undefined,
        { year: "numeric", month: "short", day: "numeric" });
      if (rendered !== value) continue;
      node.nodeValue = `${dated[1]}${dated[2]} ${stampDate}`;
      frozen += 1;
    }
  }
  return frozen;
}

export async function freezeBuildStamps(page) {
  const version = await page.evaluate(() => window.__commentableHtmlVersion || "");
  return page.evaluate(freezeInPage, {
    version,
    stampVersion: STAMP_VERSION,
    stampDate: STAMP_DATE,
    versionSelector: VERSION_SELECTOR,
    dateSelector: DATE_SELECTOR,
  });
}
