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
