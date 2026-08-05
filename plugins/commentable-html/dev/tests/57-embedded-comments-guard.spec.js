// CMH-EXP-16: the embedded-comments block (and the layer descriptor beside it) must be resolved
// STRUCTURALLY - a parsed script element the BROWSER also sees, outside any raw-text body - never
// by scanning the document text. The layer's own source is part of every document and necessarily
// spells that markup, so a text scan was answered by the runtime itself: the "region is missing"
// guard could never fire, and a document that had genuinely lost the block exported a copy whose
// runtime source had been overwritten mid-function with the comments JSON.
import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  addTextComment, clickSidebarExport, currentToast, fileUrl, openInline, openToolbarMenu, readDownload,
  ready, stageContent, stageInline, stageNonShareable, startStaticServer,
} from "./helpers.js";

// Cut a block out by index (not a regex replace): the first `<script ... id="<id>">` and its
// closing tag. The throw makes a fixture that silently stopped matching fail loudly.
function removeBlock(html, id) {
  const open = html.indexOf('id="' + id + '"');
  if (open < 0) throw new Error("fixture: no " + id + " block to remove");
  const start = html.lastIndexOf("<", open);
  const close = html.indexOf("</scr" + "ipt>", open);
  if (start < 0 || close < 0) throw new Error("fixture: malformed " + id + " block");
  return html.slice(0, start) + html.slice(close + 9);
}

function removeEmbeddedBlock(html) {
  return removeBlock(html, "embeddedComments");
}

test("Export as Shareable fails loudly when the embedded-comments block is missing (CMH-EXP-16)", async ({ page }) => {
  const staged = stageInline({ mutate: removeEmbeddedBlock });
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/doc.html");
    await ready(page);
    await addTextComment(page, "#commentRoot p", "note that must not be exported");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnSaveHtml");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("EMBEDDED COMMENTS region is present");
    // Nothing was downloaded: no export ever rewrites the layer's own source in place of the
    // missing block.
    expect(gotDownload).toBe(false);
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("Export as Shareable from a nonshareable document fails loudly too (CMH-EXP-16)", async ({ page }) => {
  // The standalone path wraps the same builder (_buildStandaloneHtml -> _buildSavedHtml), so the
  // guard must hold there as well - and must fire BEFORE the companion assets are inlined.
  const staged = stageNonShareable({ mutate: removeEmbeddedBlock });
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/NONSHAREABLE.html");
    await ready(page);
    await addTextComment(page, "#commentRoot p", "standalone note that must not be exported");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnSaveHtml");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("EMBEDDED COMMENTS region is present");
    expect(gotDownload).toBe(false);
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("an ambiguous document is refused rather than spliced on a guess (CMH-EXP-16)", async ({ page }) => {
  // A non-script element shadows the id, so a reload would not read the block at all: the source
  // text and the document a browser builds from it disagree about what the block IS, and the
  // export must refuse instead of picking one.
  const shadow = (h) => h.replace('<script type="application/json" id="embeddedComments">',
    '<div id="embeddedComments" hidden></div>\n<script type="application/json" id="embeddedComments">');
  const staged = stageInline({ mutate: shadow });
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/doc.html");
    await ready(page);
    await addTextComment(page, "#commentRoot p", "ambiguous note");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnSaveHtml");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("could not locate it reliably");
    expect(gotDownload).toBe(false);
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("Export Offline fails loudly too when the embedded-comments block is missing (CMH-EXP-16)", async ({ page }) => {
  test.setTimeout(60000);
  const staged = stageInline({ mutate: removeEmbeddedBlock });
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/doc.html");
    await ready(page);
    await addTextComment(page, "#commentRoot p", "offline note that must not be exported");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnExportOffline");
    await expect.poll(() => currentToast(page), { timeout: 15000 })
      .toContain("EMBEDDED COMMENTS region is present");
    expect(gotDownload).toBe(false);
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// The resolver must agree with a real HTML parser on documents whose text merely LOOKS like the
// block. Each case names the same decoy shape twice: once with a real block after it (the real one
// must win) and once alone (nothing must resolve).
test("the embedded-comments block is resolved structurally, never from text a browser parses as content (CMH-EXP-16)", async ({ page }) => {
  await openInline(page);
  const out = await page.evaluate(() => {
    const OPEN = "<scr" + "ipt";
    const CLOSE = "</scr" + "ipt>";
    const MENTION = OPEN + ' id="embeddedComments">DECOY' + CLOSE;
    const REAL = OPEN + ' type="application/json" id="embeddedComments">REAL' + CLOSE;
    const decoys = {
      // the layer's own shape: the markup spelled inside a script body
      scriptBody: OPEN + ">\n// writes into " + MENTION + "\nvar x = 1;\n" + CLOSE,
      // an end tag that only PREFIXES the element name does not close it
      prefixCloseTag: OPEN + ">var s = '</scr" + "iptfoo'; " + MENTION + CLOSE,
      // the classic "<!--<script>" idiom puts the tokenizer in the double-escaped state, where
      // the first closing tag ends the escape instead of the element
      doubleEscaped: OPEN + "><!--" + OPEN + ">nested" + CLOSE + MENTION + CLOSE + CLOSE,
      // an iframe's content is text, not markup
      iframe: "<iframe>" + MENTION + "</iframe>",
      // a bogus declaration is consumed to the first ">" by a parser
      bogusDeclaration: "<![CDATA[ " + MENTION + " ]]>",
      // template content is an inert fragment, invisible to getElementById; nesting must not
      // end the skip early
      nestedTemplate: "<template><template></template>" + MENTION + "</template>",
      // Declarative shadow content renders, but remains outside the document tree:
      // document.getElementById cannot resolve an id owned by either an open or closed shadow root.
      declarativeShadowOpen: '<div><template shadowrootmode="open">' + MENTION + "</template></div>",
      declarativeShadowClosed: '<div><template shadowrootmode="closed">' + MENTION + "</template></div>",
      // <noscript> content is TEXT to a browser running the layer, so the layer ignores it on
      // BOTH sides (CMH-EXP-17 imposes that one scripting model): the real block still wins, and
      // the decoy alone resolves nothing. A parsed document does build those children (parsing
      // has scripting disabled), which is exactly why the two models are reconciled rather than
      // left to disagree - otherwise one inert <noscript> block could veto every export.
      noscript: "<noscript>" + MENTION + "</noscript>",
      // a decoy attribute is not an id
      decoyAttribute: OPEN + ' data-id="embeddedComments">DECOY' + CLOSE,
    };
    // Shapes where the walk and a parsed document CANNOT agree on what the block is, so the
    // resolver must refuse rather than guess (see the assertions below for why).
    const ambiguous = {
      // not a <script> element at all: the tag name runs to the first delimiter, so the id
      // belongs to an unknown element that shadows the real block for getElementById.
      notAScriptTag: "<scr" + "ipt.foo id=\"embeddedComments\">DECOY</scr" + "ipt.foo>",
    };
    const wrap = function (body) { return "<html><body>" + body + "</body></html>"; };
    const slice = function (html) {
      const r = window.__cmhFindEmbeddedComments(html);
      return r ? html.slice(r.start, r.end) : null;
    };
    const result = { decoys: {}, ambiguous: {} };
    Object.keys(decoys).forEach(function (key) {
      result.decoys[key] = {
        withReal: slice(wrap(decoys[key] + REAL)),
        alone: slice(wrap(decoys[key])),
      };
    });
    Object.keys(ambiguous).forEach(function (key) {
      result.ambiguous[key] = {
        withReal: slice(wrap(ambiguous[key] + REAL)),
        alone: slice(wrap(ambiguous[key])),
      };
    });
    // Shapes that are NOT decoys: a legal empty comment and an unquoted attribute value holding
    // an apostrophe both used to swallow the rest of the document, a legal end tag may carry a
    // space before its ">", and in <svg> a raw-text-named element really self-closes.
    result.emptyComment = slice(wrap("<!-->" + REAL));
    result.apostropheAttribute = slice(wrap("<div data-x=it's ok>host</div>" + REAL));
    result.spacedEndTag = slice(wrap("<textarea>x</textarea >" + REAL));
    result.foreignSelfClosed = slice(wrap("<svg><title/></svg>" + REAL));
    // A truncated block has no closing tag, so it cannot be spliced: resolve nothing.
    result.truncated = slice(wrap(OPEN + ' id="embeddedComments">REAL'));
    return result;
  });
  // Assert the whole matrix at once so a failure names every shape that regressed.
  const summary = {};
  const wanted = {};
  Object.keys(out.decoys).forEach((key) => {
    summary[key] = {
      aloneResolvesNothing: out.decoys[key].alone === null,
      realBlockWins: (out.decoys[key].withReal || "").indexOf(">REAL<") >= 0
        && (out.decoys[key].withReal || "").indexOf("DECOY") < 0,
    };
    wanted[key] = { aloneResolvesNothing: true, realBlockWins: true };
  });
  expect(summary).toEqual(wanted);
  // The ambiguous shapes resolve NOTHING either way: the export fails loudly instead of splicing
  // into a block the reloading browser would not read back.
  Object.keys(out.ambiguous).forEach((key) => {
    expect(out.ambiguous[key], key).toEqual({ withReal: null, alone: null });
  });
  expect(out.emptyComment).toContain(">REAL<");
  expect(out.apostropheAttribute).toContain(">REAL<");
  expect(out.spacedEndTag).toContain(">REAL<");
  expect(out.foreignSelfClosed).toContain(">REAL<");
  expect(out.truncated).toBe(null);
});

test("Save preserves a serializable closed declarative shadow root (CMH-VAL-23)", async ({ page }) => {
  const staged = stageContent(
    '<div id="shadowHost"><template shadowrootmode="closed" shadowrootserializable>'
    + "<h2>Durable shadow heading</h2><p>Durable shadow prose</p>"
    + "</template></div>",
    { key: "cmh-shadow-export" },
  );
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await openToolbarMenu(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#btnSaveHtmlTop").click(),
  ]);
  const saved = await readDownload(download);
  expect(saved).toContain('shadowrootmode="closed"');
  expect(saved).toContain("shadowrootserializable");
  expect(saved).toContain("<h2>Durable shadow heading</h2>");
  expect(saved).toContain("<p>Durable shadow prose</p>");
});

test("Save preserves an open shadow root on a post-layer tail element (CMH-VAL-23)", async ({ page }) => {
  const staged = stageInline({
    mutate: (html) => html.replace(
      "</body>",
      '<div id="tailShadowHost"><template shadowrootmode="open">'
      + "<p>Durable tail shadow prose</p></template></div></body>",
    ),
  });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await openToolbarMenu(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#btnSaveHtmlTop").click(),
  ]);
  const saved = await readDownload(download);
  expect(saved).toContain('id="tailShadowHost"');
  expect(saved).toContain('shadowrootmode="open"');
  expect(saved).toContain("<p>Durable tail shadow prose</p>");
});

test("a fetched copy is accepted only when it really carries the block (CMH-EXP-16)", async ({ page }) => {
  const staged = stageInline();
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/doc.html");
    await ready(page);
    await addTextComment(page, "#commentRoot p", "snapshot-note");
    const onDisk = fs.readFileSync(staged.html, "utf8");
    const sentinel = (html) => html.replace("</body>", "<!-- FETCHED_COPY_SENTINEL -->\n</body>");
    // 1) The copy the runtime re-fetches at export time has LOST its embedded-comments block; its
    // only remaining mention of one is inside the layer's own script body. That copy is unusable
    // as a base, so the export must fall back to the pre-mutation DOM snapshot instead.
    await page.route(server.url + "/doc.html", (route) => route.fulfill({
      status: 200, contentType: "text/html", body: sentinel(removeEmbeddedBlock(onDisk)),
    }));
    const [broken] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const fromSnapshot = await readDownload(broken);
    expect(fromSnapshot).not.toContain("FETCHED_COPY_SENTINEL");
    expect(fromSnapshot).toContain("snapshot-note");
    // 2) A well-formed fetched copy IS still preferred, so the guard did not simply disable the
    // fetch path.
    await page.unroute(server.url + "/doc.html");
    await page.route(server.url + "/doc.html", (route) => route.fulfill({
      status: 200, contentType: "text/html", body: sentinel(onDisk),
    }));
    const [good] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const fromFetch = await readDownload(good);
    expect(fromFetch).toContain("FETCHED_COPY_SENTINEL");
    expect(fromFetch).toContain("snapshot-note");
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a document that lost its layer descriptor never has its runtime overwritten (CMH-EXP-16)", async ({ page }) => {
  test.setTimeout(90000);
  // The descriptor block carried the identical defect: the runtime's own source spells
  // `<script type="application/json" id="commentableHtmlLayer">`, so the text scan matched inside
  // the inlined runtime and the replacement overwrote a quarter of a megabyte of runtime JS with
  // the descriptor JSON - silently, on every Offline export.
  const staged = stageInline({ mutate: (h) => removeBlock(h, "commentableHtmlLayer") });
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/doc.html");
    await ready(page);
    await addTextComment(page, "#commentRoot p", "descriptor note");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const html = await readDownload(download);
    // The runtime survived intact: the old text scan overwrote a quarter of a megabyte of it,
    // mid-function, taking the startup code with it.
    expect(html).toContain("__commentableHtmlReady");
    expect(html).toContain("descriptor note");
    // The strongest proof there is no corruption: the exported file still BOOTS, and still
    // carries its comment.
    const out = path.join(staged.dir, "offline.html");
    fs.writeFileSync(out, html);
    await page.goto(fileUrl(out));
    await ready(page);
    await expect(page.locator("#sidebar")).toContainText("descriptor note");
    // And the descriptor was really re-created for the new mode, not just left out.
    const descriptor = await page.evaluate(() => {
      const el = document.getElementById("commentableHtmlLayer");
      return el ? JSON.parse(el.textContent) : null;
    });
    expect(descriptor.mode).toBe("offline");
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
