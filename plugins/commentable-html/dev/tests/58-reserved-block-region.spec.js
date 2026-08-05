// CMH-EXP-17 / CMH-EXP-18 / CMH-EXP-19: the layer's own data blocks are INFRASTRUCTURE, resolved
// against the content-root boundary rather than by document position. A same-id decoy inside
// `#commentRoot` is authored content: it can never be mistaken for one of the layer's blocks, on
// the read side or the write side, and its bytes are left alone (Shareable deliberately does not
// neutralize it the way Offline does - CMH-EXP-19). A CONTESTED boundary (more than one element
// carrying the content-root id) resolves nothing at all rather than falling back to position.
import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  addTextComment, clickSidebarExport, currentToast, fileUrl, openInline, readDownload, ready,
  stageInline, stageNonShareable,
} from "./helpers.js";

const EMBEDDED_REGION_RE =
  /[ \t]*<!--\s*=*\s*BEGIN: commentable-html - EMBEDDED COMMENTS[\s\S]*?<!--\s*=*\s*END: commentable-html - EMBEDDED COMMENTS\s*=*\s*-->\n?/;
const CONTENT_BEGIN = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->";
const OPEN = "<scr" + "ipt";
const CLOSE = "</scr" + "ipt>";

// Put `markup` inside the content root, right after the CONTENT begin marker.
function inContent(html, markup) {
  if (html.indexOf(CONTENT_BEGIN) < 0) throw new Error("fixture: no CONTENT region to plant into");
  return html.replace(CONTENT_BEGIN, CONTENT_BEGIN + "\n" + markup);
}

// Cut a block out by index (not a regex replace): the first `<script ... id="<id>">` and its
// closing tag. The throw makes a fixture that silently stopped matching fail loudly.
function removeBlock(html, id) {
  const open = html.indexOf('id="' + id + '"');
  if (open < 0) throw new Error("fixture: no " + id + " block to remove");
  const start = html.lastIndexOf("<", open);
  const close = html.indexOf(CLOSE, open);
  if (start < 0 || close < 0) throw new Error("fixture: malformed " + id + " block");
  return html.slice(0, start) + html.slice(close + CLOSE.length);
}

// Move the whole EMBEDDED COMMENTS region to just before the JS region, i.e. AFTER the content
// root, so a decoy planted in the content PRECEDES the real block in document order. That is the
// arrangement that tells a position-based lookup apart from a boundary-based one.
function moveEmbeddedRegionAfterContent(html) {
  const region = html.match(EMBEDDED_REGION_RE);
  if (!region) throw new Error("fixture: no EMBEDDED COMMENTS region to move");
  const rest = html.replace(EMBEDDED_REGION_RE, "");
  const jsBegin = /[ \t]*<!--\s*=*\s*\n?\s*BEGIN: commentable-html - JS/;
  if (!jsBegin.test(rest)) throw new Error("fixture: no JS region to move the block above");
  return rest.replace(jsBegin, (m) => "\n" + region[0] + m);
}

function embeddedRegionOf(html) {
  const region = html.match(EMBEDDED_REGION_RE);
  return region ? region[0] : "";
}

// Insert before the LAST </body>: the inlined runtime's own source mentions that tag, so a plain
// first-match replace would splice markup into the middle of the layer's JS.
function beforeLastBody(html, markup) {
  const at = html.toLowerCase().lastIndexOf("</body>");
  if (at < 0) throw new Error("fixture: no </body> to insert before");
  return html.slice(0, at) + markup + "\n" + html.slice(at);
}

// Write an exported copy beside the fixture and open it.
async function reopen(page, dir, html, name) {
  const out = path.join(dir, name);
  fs.writeFileSync(out, html);
  await page.goto(fileUrl(out));
  await ready(page);
}

test("a content-region decoy that precedes the real block never receives the comments (CMH-EXP-17)", async ({ page }) => {
  const DECOY = OPEN + ' type="application/json" id="embeddedComments">"DECOY_SENTINEL_MUST_SURVIVE"' + CLOSE;
  const staged = stageInline({
    mutate: (h) => inContent(moveEmbeddedRegionAfterContent(h), DECOY),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "region-scoped note");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const out = await readDownload(download);
    // The layer's own block - the one inside the EMBEDDED COMMENTS region - carries the comment,
    // and the author's decoy is returned byte-intact.
    expect(embeddedRegionOf(out)).toContain("region-scoped note");
    expect(out).toContain("DECOY_SENTINEL_MUST_SURVIVE");
    // And the exported copy reads its comment back from that block on reload.
    await reopen(page, staged.dir, out, "reopened.html");
    await expect(page.locator("#sidebar")).toContainText("region-scoped note");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a content-region decoy is not a substitute for a missing block (CMH-EXP-17)", async ({ page }) => {
  // With the real block gone, the decoy is the only element owning the id. Position would hand the
  // export straight to it; the boundary makes the document what it is - one that lost its region -
  // so the export fails loudly instead of writing review state into authored content.
  const DECOY = OPEN + ' type="application/json" id="embeddedComments">"DECOY_SENTINEL_MUST_SURVIVE"' + CLOSE;
  const staged = stageInline({
    mutate: (h) => inContent(h.replace(EMBEDDED_REGION_RE, ""), DECOY),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "note that must not be exported");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnSaveHtml");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("inside the content root");
    expect(gotDownload).toBe(false);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a contested content root resolves nothing rather than falling back to position (CMH-EXP-17)", async ({ page }) => {
  // A duplicate content-root id is how a planted wrapper would re-point the boundary, so there is
  // no answer to give: the export refuses instead of falling back to the position rule the
  // boundary exists to replace.
  const staged = stageInline({
    mutate: (h) => inContent(h, '<div id="commentRoot" hidden></div>'),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "contested note");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnSaveHtml");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("more than one element carrying the commentable-html content-root id");
    expect(gotDownload).toBe(false);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("no surviving descriptor copy disagrees with the exported mode, and author scripts are left alone (CMH-EXP-18)", async ({ page }) => {
  // Two inert decoys borrow the descriptor id outside the content root, one before the real block
  // and one after it. Rewriting only the first left the other stale, so the document shipped two
  // reserved descriptors that disagreed about what it IS - and which one a reader believed came
  // down to document order. A RUNNABLE script that borrows the id is a different matter:
  // clobbering an author's code is the mutation CMH-EXP-19 refuses to make, so it is left alone.
  const REAL = OPEN + ' type="application/json" id="commentableHtmlLayer">';
  const decoy = (tag) => OPEN + ' type="application/json" id="commentableHtmlLayer">'
    + '{"version":"0.0.0","mode":"' + tag + '","regions":[]}' + CLOSE + "\n";
  const RUNNABLE_DECOY = OPEN + ' id="commentableHtmlLayer">window.__cmhAuthorScript = "AUTHOR_CODE_MUST_SURVIVE";' + CLOSE + "\n";
  const CONTENT_DECOY = OPEN + ' type="application/json" id="commentableHtmlLayer">'
    + '{"note":"DECOY_CONTENT_SENTINEL"}' + CLOSE;
  const staged = stageNonShareable({
    mutate: (h) => inContent(
      h.replace(REAL, decoy("before") + REAL).replace("</head>", decoy("after") + RUNNABLE_DECOY + "</head>"),
      CONTENT_DECOY),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "descriptor mode note");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const out = await readDownload(download);
    expect(out).toContain("descriptor mode note");
    expect(out).not.toContain('"mode":"before"');
    expect(out).not.toContain('"mode":"after"');
    expect(out).not.toContain('"mode":"nonshareable"');
    // The author's runnable script and the content-region decoy are both authored content: the
    // export returns them exactly as it found them.
    expect(out).toContain("AUTHOR_CODE_MUST_SURVIVE");
    expect(out).toContain("DECOY_CONTENT_SENTINEL");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a document whose only descriptor id sits in content is refused, not given a second one (CMH-EXP-18)", async ({ page }) => {
  // Minting a fresh descriptor beside the decoy would emit a document with two elements owning an
  // id the strict validator requires to be unique, so the export fails loudly instead.
  const CONTENT_DECOY = OPEN + ' type="application/json" id="commentableHtmlLayer">{"mode":"decoy"}' + CLOSE;
  const staged = stageNonShareable({
    mutate: (h) => inContent(removeBlock(h, "commentableHtmlLayer"), CONTENT_DECOY),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "no-descriptor note");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnSaveHtml");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("sits inside the content root");
    expect(gotDownload).toBe(false);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a content-region descriptor decoy cannot declare the document offline (CMH-EXP-17)", async ({ page }) => {
  // The read side runs through the same boundary as the write side. With the real descriptor gone,
  // a decoy inside the content root is the only element owning the id - and position would let it
  // declare this document Offline in the badge a reviewer trusts.
  const CONTENT_DECOY = OPEN + ' type="application/json" id="commentableHtmlLayer">'
    + '{"version":"0.0.0","mode":"offline","regions":[]}' + CLOSE;
  const staged = stageInline({
    mutate: (h) => inContent(removeBlock(h, "commentableHtmlLayer"), CONTENT_DECOY),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(page.locator("#cmTypeBadge")).not.toHaveText("Offline");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a descriptor decoy that PRECEDES the real block loses on both sides (CMH-EXP-17)", async ({ page }) => {
  // The sharpest arrangement for the descriptor: the real block moved BELOW the content root, and
  // an `offline` decoy planted inside the content above it. Position hands both the badge and the
  // export to the decoy; the boundary hands both to the real block and leaves the decoy's bytes
  // alone.
  const REAL = OPEN + ' type="application/json" id="commentableHtmlLayer">'
    + '{"version":"0.0.0","mode":"shareable","regions":[]}' + CLOSE;
  const CONTENT_DECOY = OPEN + ' type="application/json" id="commentableHtmlLayer">'
    + '{"version":"0.0.0","mode":"offline","regions":[],"note":"PRECEDING_DECOY_SENTINEL"}' + CLOSE;
  const staged = stageInline({
    mutate: (h) => beforeLastBody(inContent(removeBlock(h, "commentableHtmlLayer"), CONTENT_DECOY), REAL),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // The badge follows the real block below the content, not the decoy above it.
    await expect(page.locator("#cmTypeBadge")).not.toHaveText("Offline");
    await addTextComment(page, "#commentRoot p", "preceding descriptor decoy note");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const out = await readDownload(download);
    // The decoy travels byte-intact, still declaring its own mode; the real block was restamped.
    expect(out).toContain("PRECEDING_DECOY_SENTINEL");
    expect(out).toContain('"mode":"shareable"');
    expect(out).toContain("preceding descriptor decoy note");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a plain Save leaves no stale descriptor copy behind either (CMH-EXP-18)", async ({ page }) => {
  // Save is not a mode CHANGE, but it is still an export: the same "no surviving copy disagrees"
  // rule has to hold, or an inline document keeps shipping a second descriptor nobody rewrote.
  const REAL = OPEN + ' type="application/json" id="commentableHtmlLayer">';
  const STALE = OPEN + ' type="application/json" id="commentableHtmlLayer">'
    + '{"version":"0.0.0","mode":"STALE_MODE","regions":[]}' + CLOSE + "\n";
  const staged = stageInline({ mutate: (h) => h.replace(REAL, STALE + REAL) });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "stale copy note");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const out = await readDownload(download);
    expect(out).not.toContain("STALE_MODE");
    expect(out).toContain("stale copy note");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a content-region handled-ids decoy cannot delete a reviewer's comment (CMH-EXP-17)", async ({ page }) => {
  // getHandledIds() feeds pruneHandled(), which DELETES matching comments from the live store and
  // persists that, so a decoy the boundary did not exclude could quietly erase review state on
  // load. The comment is baked by a real export first, so the id is a real one.
  const staged = stageInline();
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "HANDLED_DECOY_NOTE_MUST_SURVIVE");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const exported = await readDownload(download);
    const id = (embeddedRegionOf(exported).match(/"id":\s*"([^"]+)"/) || [])[1];
    expect(id, "the export baked a comment id").toBeTruthy();
    const DECOY = OPEN + ' type="application/json" id="handledCommentIds">["' + id + '"]' + CLOSE;
    await reopen(page, staged.dir, inContent(exported, DECOY), "with-handled-decoy.html");
    await expect(page.locator("#sidebar")).toContainText("HANDLED_DECOY_NOTE_MUST_SURVIVE");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("Shareable keeps a reserved-id decoy runnable rather than neutralizing it (CMH-EXP-19)", async ({ page }) => {
  // Offline retypes a runnable reserved-id script to inert JSON (CMH-OFFLINE-04) because its
  // zero-network promise needs the egress strips' reserved-id exemption to be earned. Shareable
  // makes no such promise and preserves author scripts by design, so the decoy travels untouched;
  // what protects the export is the boundary, not a rewrite of the author's script. The decoy is
  // planted BEFORE the real block so position and boundary genuinely disagree.
  const DECOY = OPEN + ' id="embeddedComments">window.__cmhDecoyRan = "DECOY_RAN";' + CLOSE;
  const staged = stageInline({
    mutate: (h) => inContent(moveEmbeddedRegionAfterContent(h), DECOY),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "shareable decoy note");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const out = await readDownload(download);
    expect(out).toContain(DECOY);
    expect(embeddedRegionOf(out)).toContain("shareable decoy note");
    // Untouched means still RUNNABLE: the exported copy executes the author's script on reopen.
    await reopen(page, staged.dir, out, "reopened-decoy.html");
    expect(await page.evaluate(() => window.__cmhDecoyRan)).toBe("DECOY_RAN");
    // ...and Plain export of that same document still succeeds: the leak guard judges the layer's
    // own blocks by the boundary, so authored content carrying a reserved id cannot abort it.
    const [plain] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSavePlain"),
    ]);
    const plainOut = await readDownload(plain);
    expect(plainOut).toContain("DECOY_RAN");
    expect(plainOut).not.toContain("shareable decoy note");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("two blocks with identical bodies are told apart by identity, not position (CMH-EXP-17)", async ({ page }) => {
  // The walk reports SOURCE order and a parsed document reports TREE order. Equal counts do not
  // prove the two lists describe the same elements, and equal bodies cannot tell a match from a
  // swap, so the mapping is established by identity - checked here on the one shape where a
  // position-based mapping would look fine: two blocks whose bodies are byte-identical. The second
  // case is the mirror rule: a decoy the walk and the parse see DIFFERENTLY is only a reason to
  // refuse when it is one of the layer's own candidates, so authored content cannot veto an
  // export by parking a same-id script somewhere only one of the two models sees it.
  await openInline(page);
  const out = await page.evaluate(() => {
    const O = "<scr" + "ipt";
    const C = "</scr" + "ipt>";
    const BLOCK = O + ' type="application/json" id="embeddedComments">[]' + C;
    const doc = '<html><body><main id="commentRoot">' + BLOCK + "</main>" + BLOCK + "</body></html>";
    // A self-closed foreign-content script and a <noscript>-parked one: the parse builds elements
    // the tokenizer walk (and the live, scripting-enabled runtime) never sees as elements.
    const vetoContent = "<svg>" + O + ' id="embeddedComments" />' + "</svg>"
      + "<noscript>" + O + ' id="embeddedComments">DECOY' + C + "</noscript>";
    const vetoDoc = '<html><body><main id="commentRoot">' + vetoContent + "</main>" + BLOCK + "</body></html>";
    return {
      r: window.__cmhFindEmbeddedComments(doc),
      rootEnd: doc.indexOf("</main>"),
      veto: window.__cmhFindEmbeddedComments(vetoDoc),
      vetoRootEnd: vetoDoc.indexOf("</main>"),
    };
  });
  expect(out.r).not.toBe(null);
  // The resolved range is the block OUTSIDE the content root, even though both bodies are "[]".
  expect(out.r.start).toBeGreaterThan(out.rootEnd);
  // Content-region shapes the two models disagree about do not block the resolution.
  expect(out.veto).not.toBe(null);
  expect(out.veto.start).toBeGreaterThan(out.vetoRootEnd);
});

test("a contested content root refuses the descriptor restamp too (CMH-EXP-18)", async ({ page }) => {
  // The Standalone path (which a nonshareable document's Save takes) restamps the descriptor, so
  // the contested-boundary refusal has to hold in the descriptor resolver as well as in the
  // comments one - a document the layer cannot read its own blocks out of must not be restamped.
  const staged = stageNonShareable({
    mutate: (h) => inContent(h, '<div id="commentRoot" hidden></div>'),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "contested standalone note");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnSaveHtml");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("more than one element carrying the commentable-html content-root id");
    expect(gotDownload).toBe(false);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a runnable author script is never overwritten with descriptor JSON (CMH-EXP-18)", async ({ page }) => {
  // The block a reader resolves is normally the layer's inert descriptor. When it is instead an
  // author's runnable script that borrowed the id (planted BEFORE the real descriptor, so it is
  // what a reader resolves), the export refuses rather than replacing the author's code with JSON.
  const REAL = OPEN + ' type="application/json" id="commentableHtmlLayer">';
  const RUNNABLE = OPEN + ' id="commentableHtmlLayer">window.__cmhAuthorFirst = "AUTHOR_CODE";' + CLOSE + "\n";
  const staged = stageNonShareable({ mutate: (h) => h.replace(REAL, RUNNABLE + REAL) });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "runnable descriptor note");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnSaveHtml");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("is a runnable script");
    expect(gotDownload).toBe(false);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("Plain export removes every descriptor copy the layer owns (CMH-EXP-19)", async ({ page }) => {
  // An export that declares a mode maintains ADDITIONAL descriptor copies, so a first-match strip
  // would leave a "plain" copy still declaring itself a commentable-html document with a mode.
  const REAL = OPEN + ' type="application/json" id="commentableHtmlLayer">';
  const EXTRA = OPEN + ' type="application/json" id="commentableHtmlLayer">'
    + '{"version":"0.0.0","mode":"shareable","regions":[]}' + CLOSE + "\n";
  const staged = stageInline({ mutate: (h) => h.replace(REAL, EXTRA + REAL) });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "plain descriptor note");
    const [plain] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSavePlain"),
    ]);
    const out = await readDownload(plain);
    expect(out).not.toContain('id="commentableHtmlLayer"');
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// ---- CMH-EXP-21: the Plain-export safety net names the block and where it survived ----

// Plant a stray reserved block just above the JS region: outside the content root (so the boundary
// counts it as the layer's) and outside every region (so no region strip can reach it). It must
// come BEFORE the layer's own script, or the runtime would not have parsed it yet when it reads.
function strayEmbeddedBlock(html, payload) {
  const jsBegin = /[ \t]*<!--\s*=*\s*\n?\s*BEGIN: commentable-html - JS/;
  if (!jsBegin.test(html)) throw new Error("fixture: no JS region to plant above");
  const stray = OPEN + ' type="application/json" id="embeddedComments">'
    + JSON.stringify(payload || []) + CLOSE + "\n";
  return html.replace(jsBegin, (m) => stray + m);
}

// Put `arr` in the block the EMBEDDED COMMENTS region owns (the one the runtime reads and every
// export rewrites).
function regionEmbeddedPayload(html, arr) {
  const re = /(<script type="application\/json" id="embeddedComments">\n)\[\]\n(<\/script>)/;
  if (!re.test(html)) throw new Error("fixture: no embeddedComments block to seed");
  return html.replace(re, (_m, a, b) => a + JSON.stringify(arr) + "\n" + b);
}

// The bodies of every embeddedComments DATA block in the html, in document order. Bodies that are
// not JSON are skipped: the inlined runtime's own source spells `id="embeddedComments">` in a string
// literal, and that text is not one of the document's blocks.
function embeddedBlockBodies(html) {
  const out = [];
  const re = /id="embeddedComments">([\s\S]*?)<\/script>/g;
  let m;
  while ((m = re.exec(html))) {
    try { JSON.parse(m[1].trim() || "[]"); } catch (e) { continue; }
    out.push(m[1]);
  }
  return out;
}

// Give the EMBEDDED COMMENTS banner comment some prose BEFORE its BEGIN marker. Every marker
// COUNT view still resolves the region (the marker is a line of its own inside a comment), but the
// region STRIP anchors on "<!--" + whitespace + "BEGIN:", so the region text no longer matches and
// the whole region survives - with the markers intact.
function proseBeforeBeginMarkerOf(html, region) {
  const marker = "BEGIN: commentable-html - " + region;
  const at = html.indexOf(marker);
  if (at < 0) throw new Error("fixture: no " + region + " begin marker");
  const open = html.lastIndexOf("<!--", at);
  if (open < 0) throw new Error("fixture: begin marker is not inside a comment");
  return html.slice(0, open + 4) + " author note about this region\n" + html.slice(open + 4);
}

function proseBeforeBeginMarker(html) {
  return proseBeforeBeginMarkerOf(html, "EMBEDDED COMMENTS");
}

// The same class of damage on the OTHER anchor: prose before the END marker, inside its comment.
// The count views still resolve the region (the marker is a line of its own inside a comment), but
// the strip anchors on "<!--" + whitespace + "END:", so this too leaves the region in place with its
// markers resolving - which is why the diagnosis must not name one marker as the culprit.
function proseBeforeEndMarker(html) {
  const end = "<!-- END: commentable-html - EMBEDDED COMMENTS -->";
  if (html.indexOf(end) < 0) throw new Error("fixture: no EMBEDDED COMMENTS end comment");
  return html.replace(end, "<!-- author note about this region\n     END: commentable-html - EMBEDDED COMMENTS\n-->");
}

// Rewrite the region's END marker as a CSS comment. The count views accept that shape, so the
// document still has exactly one ordered pair as far as they are concerned, but no HTML comment
// carries the END marker any more - so the region cannot be attributed at all.
function endMarkerAsCssComment(html) {
  const end = "<!-- END: commentable-html - EMBEDDED COMMENTS -->";
  if (html.indexOf(end) < 0) throw new Error("fixture: no EMBEDDED COMMENTS end comment");
  return html.replace(end, "/* END: commentable-html - EMBEDDED COMMENTS */");
}

async function plainExportToast(page, staged) {
  await page.goto(fileUrl(staged.html));
  await ready(page);
  // A comment of its own, so the export is the ordinary "save a plain copy of a reviewed file"
  // flow (and so the sidebar the export menu lives in is open).
  await addTextComment(page, "#commentRoot p", "plain leak note");
  let gotDownload = false;
  page.once("download", () => { gotDownload = true; });
  await clickSidebarExport(page, "#btnSavePlain");
  await expect.poll(() => currentToast(page), { timeout: 15000 }).toContain("Plain export aborted");
  expect(gotDownload).toBe(false);
  return currentToast(page);
}

// ---- CMH-EXP-20: a duplicate block the layer owns is reported, never silently ignored ----

test("a damaged region declines the review state but never the comments themselves (CMH-EXP-17)", async ({ page }) => {
  // The recorded, deliberate divergence: the CONTENT-ROOT BOUNDARY is the ONE ownership rule for
  // every reserved data block, and the review-state block asks for region ownership ON TOP of it.
  // The failure costs are not symmetric - declining the review state only omits an accessory from
  // this copy, while declining the comments payload would strand the reader's comments AND block
  // the very export that would save them - so this same document must answer both ways at once.
  const staged = stageInline({ mutate: endMarkerAsCssComment });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "payload survives a damaged region");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const out = await readDownload(download);
    expect(out).toContain("payload survives a damaged region");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("Section-review state was left out");
    // And the exported copy reads that comment back.
    await reopen(page, staged.dir, out, "reopened-damaged-region.html");
    await expect(page.locator("#sidebar")).toContainText("payload survives a damaged region");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a second block the layer owns for a data id is reported (CMH-EXP-20)", async ({ page }) => {
  // The reader reads the FIRST block the boundary accepts and every export rewrites that same one,
  // so a second one is stale on load and never updated on save - a document whose comment data is
  // half ignored, silently, forever. Say so once, on the console and to the reader, and pin that
  // the FIRST block really is the one both sides use.
  const now = new Date().toISOString();
  const staged = stageInline({
    mutate: (h) => strayEmbeddedBlock(
      regionEmbeddedPayload(h, [
        { id: "cregion001", anchorType: "document", note: "region block note", author: "Region", createdAt: now },
      ]),
      [{ id: "cstray0001", anchorType: "document", note: "stray block note", author: "Stray", createdAt: now }],
    ),
  });
  try {
    const warnings = [];
    page.on("console", (m) => { if (m.type() === "warning") warnings.push(m.text()); });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect.poll(() => currentToast(page), { timeout: 15000 }).toContain("embeddedComments");
    const toast = await currentToast(page);
    expect(toast).toContain("2");
    expect(warnings.join("\n")).toContain("embeddedComments");
    // The first block is the one that is READ: its comment is loaded, the stray's is not.
    await expect(page.locator("#sidebar")).toContainText("region block note");
    await expect(page.locator("#sidebar")).not.toContainText("stray block note");
    // ...and the one that is WRITTEN: a new comment lands in the first block while the stray's
    // bytes travel untouched, so a reload of the copy reads back what this session saw.
    await addTextComment(page, "#commentRoot p", "duplicate-block note");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const out = await readDownload(download);
    const bodies = embeddedBlockBodies(out);
    expect(bodies.length).toBe(2);
    expect(bodies[0]).toContain("duplicate-block note");
    expect(bodies[0]).toContain("region block note");
    expect(bodies[1]).toContain("stray block note");
    expect(bodies[1]).not.toContain("duplicate-block note");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("competing startup diagnostics are aggregated so both remain visible (CMH-A11Y-03)", async ({ page }) => {
  const blockerUrl = "http://127.0.0.1:31827/cmh-startup-blocker.js";
  await page.addInitScript(() => {
    Storage.prototype.setItem = function () {
      throw new DOMException("storage blocked for startup diagnostic test", "SecurityError");
    };
  });
  let requestSeenResolve;
  let releaseRequest;
  const requestSeen = new Promise((resolve) => { requestSeenResolve = resolve; });
  const requestGate = new Promise((resolve) => { releaseRequest = resolve; });
  await page.route(blockerUrl, async (route) => {
    requestSeenResolve();
    await requestGate;
    await route.fulfill({ status: 200, contentType: "application/javascript", body: "" });
  });
  const staged = stageInline({
    mutate: (h) => beforeLastBody(
      regionEmbeddedPayload(endMarkerAsCssComment(h), [{
        id: "cstartup001",
        anchorType: "document",
        note: "startup storage write",
        createdAt: "2026-08-04T00:00:00.000Z",
      }]),
      '<script src="' + blockerUrl + '"></script>\n'
        + OPEN + ' type="application/json" id="embeddedComments">[]' + CLOSE,
    ),
  });
  try {
    const navigation = page.goto(fileUrl(staged.html));
    await requestSeen;
    // Let the old two-timer heuristic expire while parsing is still blocked. A correct aggregation
    // waits for parsing itself, not an assumed number of event-loop turns.
    await page.evaluate(() => new Promise((resolve) => {
      setTimeout(() => setTimeout(resolve, 0), 0);
    }));
    releaseRequest();
    await navigation;
    await ready(page);
    await expect.poll(() => currentToast(page), { timeout: 15000 }).toContain("embeddedComments");
    const toast = await currentToast(page);
    expect(toast).toContain("Comment NOT saved");
    expect(toast).toContain("reviewedSections");
    expect(toast).toContain("embeddedComments");
  } finally {
    releaseRequest();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a missing toast surface cannot make a deferred duplicate-block warning throw (CMH-EXP-20)", async ({ page }) => {
  const toastMarkup = '<div class="cm-toast cm-skip" id="toast" role="status" aria-live="polite"></div>';
  const staged = stageInline({
    mutate: (h) => {
      if (h.indexOf(toastMarkup) < 0) throw new Error("fixture: no toast surface to remove");
      return strayEmbeddedBlock(h.replace(toastMarkup, ""), []);
    },
  });
  try {
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(errors).toEqual([]);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("the Plain safety net names a block that was never in the region (CMH-EXP-21)", async ({ page }) => {
  // The commonest real cause, and the one "malformed markers?" always misnamed: the markers are
  // fine, the region was stripped, and the block that survived was never inside it.
  const staged = stageInline({ mutate: strayEmbeddedBlock });
  try {
    const toast = await plainExportToast(page, staged);
    expect(toast).toContain('"embeddedComments"');
    expect(toast).toContain("OUTSIDE the EMBEDDED COMMENTS region");
    expect(toast).not.toContain("malformed markers?");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("the Plain safety net says when the surviving block is INSIDE its region (CMH-EXP-21)", async ({ page }) => {
  const staged = stageInline({ mutate: proseBeforeBeginMarker });
  try {
    const toast = await plainExportToast(page, staged);
    expect(toast).toContain('"embeddedComments"');
    expect(toast).toContain("INSIDE the EMBEDDED COMMENTS region");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("the INSIDE diagnosis does not blame one marker for the other's shape (CMH-EXP-21)", async ({ page }) => {
  // Prose before the END marker breaks the strip exactly as prose before the BEGIN marker does, so
  // the message must describe the requirement both anchors share rather than naming BEGIN.
  const staged = stageInline({ mutate: proseBeforeEndMarker });
  try {
    const toast = await plainExportToast(page, staged);
    expect(toast).toContain('"embeddedComments"');
    expect(toast).toContain("INSIDE the EMBEDDED COMMENTS region");
    expect(toast).not.toContain("BEGIN marker must be");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a duplicate in the document TAIL is reported once the parser is done (CMH-EXP-20)", async ({ page }) => {
  // A block after the layer's own script did not exist yet when the read happened, so the read-time
  // count cannot see it. The audit runs again when the document is fully parsed.
  const staged = stageInline({
    mutate: (h) => beforeLastBody(h, OPEN + ' type="application/json" id="embeddedComments">[]' + CLOSE),
  });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect.poll(() => currentToast(page), { timeout: 15000 }).toContain("embeddedComments");
    expect(await currentToast(page)).toContain("2");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("the OUTSIDE remedy never tells an author to move a duplicate ahead of the real block (CMH-EXP-21)", async ({ page }) => {
  // Moving a second block into the region could put it BEFORE the real one, which would hand the
  // reader and the next export the stale copy - the swap the whole rule exists to stop.
  const staged = stageInline({ mutate: (h) => strayEmbeddedBlock(h, []) });
  try {
    const toast = await plainExportToast(page, staged);
    expect(toast).toContain("OUTSIDE the EMBEDDED COMMENTS region");
    expect(toast).toContain("already has another embeddedComments block");
    expect(toast).not.toContain("Move it into the");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("the Plain safety net places a surviving descriptor copy in its region (CMH-EXP-21)", async ({ page }) => {
  // A NON-script element carrying the descriptor id is not something the descriptor strip can
  // remove (it resolves scripts only), and with the COMMENT UI region's strip broken the region it
  // sits in survives too - so the message must place it rather than claim the descriptor sits
  // outside every region.
  const staged = stageInline({
    mutate: (h) => {
      const marker = "<!-- END: commentable-html - COMMENT UI -->";
      if (h.indexOf(marker) < 0) throw new Error("fixture: no COMMENT UI end comment");
      return proseBeforeBeginMarkerOf(
        h.replace(marker, '<div id="commentableHtmlLayer" hidden></div>\n' + marker), "COMMENT UI");
    },
  });
  try {
    const toast = await plainExportToast(page, staged);
    expect(toast).toContain('"commentableHtmlLayer"');
    expect(toast).toContain("inside its COMMENT UI region");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("the Plain safety net says when the region cannot be attributed at all (CMH-EXP-21)", async ({ page }) => {
  const staged = stageInline({ mutate: endMarkerAsCssComment });
  try {
    const toast = await plainExportToast(page, staged);
    expect(toast).toContain('"embeddedComments"');
    expect(toast).toContain("exactly one ordered pair of EMBEDDED COMMENTS region markers");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
