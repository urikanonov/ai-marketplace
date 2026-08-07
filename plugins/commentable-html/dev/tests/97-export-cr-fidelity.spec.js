import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import os from "os";
import { INLINE, fileUrl, ready, readDownload, openInline, openToolbarMenu, stageContent } from "./helpers.js";

// CMH-EXP-24: an authored CR survives a runtime DOM export. Every export path re-serializes the
// document through cmhSerializeElement (getHTML()/outerHTML), and HTML's fragment serialization
// never escapes a CR - so a DOM node holding a real CR (which is exactly what an authored `&#13;`
// decodes to) came out as a LITERAL CR, and the next load's input-stream preprocessing folded it
// back to LF. The authored CR was lost, silently, on the round trip. The serializer now rewrites a
// CR back to `&#13;` wherever a browser decodes a character reference, and leaves comments and
// raw-text bodies alone (a `&#13;` is not a character reference there).

const ATTR_CONTENT =
  '<section><p id="p" data-cmh-cr="a&#13;b">An authored CR in an attribute value must survive an export.</p></section>';
const TEXT_CONTENT =
  '<section><p id="t">a&#13;b</p></section>';

const CR_TAIL = '\n<span id="tailhost"></span>CMHTAILa&#13;bCMHTAIL\n';
// A tail text node whose DATA looks like markup. Emitted raw it would become a live <script>, and
// the CR spelling would then land inside what the reload reads as a raw-text body - six literal
// characters instead of a CR. Serializing the text node properly is what keeps both correct.
const CR_TAIL_MARKUP = '\n<span id="tailhost2"></span>CMHMKa&lt;script&gt;b&#13;c&lt;/script&gt;dCMHMK\n';

function stageWithTail(tail, name) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_crtail_"));
  let html = fs.readFileSync(INLINE, "utf8");
  const marker = "<!-- END: commentable-html - JS -->";
  const idx = html.lastIndexOf(marker);
  if (idx < 0) throw new Error("no JS END marker in SHAREABLE.html");
  const after = idx + marker.length;
  html = html.slice(0, after) + tail + html.slice(after);
  const p = path.join(dir, name);
  fs.writeFileSync(p, html);
  return { dir, html: p };
}

async function exportShareableFromFile(page, htmlPath) {
  await page.goto(fileUrl(htmlPath));
  await ready(page);
  // Pin the assumption the round trip rests on. The export prefers the ON-DISK bytes when it can
  // fetch them, and the staged source already spells the CR as `&#13;`, so a fetched base would
  // make every byte assertion below a tautology. Only when the fetch fails does the export fall
  // back to _snapshotWithTail() - the re-serializing path this fix lives on. Assert the fetch
  // really is unavailable rather than trusting the environment to keep blocking it.
  const fetchBlocked = await page.evaluate(() =>
    fetch(location.href, { cache: "no-store" }).then(() => false, () => true));
  expect(fetchBlocked, "the export must fall back to the DOM snapshot for this test to mean anything")
    .toBe(true);
  await openToolbarMenu(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#btnSaveHtmlTop").click(),
  ]);
  return readDownload(download);
}

// Reopen the exported bytes and ask the DOM what it actually read back, which is the half of the
// round trip the exported spelling exists to protect.
async function reopen(browser, html, read) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_cr_out_"));
  const p = path.join(dir, "reopened.html");
  fs.writeFileSync(p, html, "utf8");
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  try {
    await page.goto(fileUrl(p));
    await ready(page);
    return await page.evaluate(read);
  } finally {
    await ctx.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test.describe("An authored CR survives a runtime DOM export (CMH-EXP-24)", () => {
  // file:// blocks the fetch of the page URL, so the export base is the DOM snapshot - the path
  // that actually re-serializes, and the one that used to downgrade the CR.
  test("an attribute value keeps its CR through Export as Shareable (CMH-EXP-24)", async ({ page, browser }) => {
    const staged = stageContent(ATTR_CONTENT, { key: "cmh-cr-attr", source: "cr-attr.html" });
    try {
      const html = await exportShareableFromFile(page, staged.html);
      expect(html, "the exported bytes must spell the CR as a character reference")
        .toContain('data-cmh-cr="a&#13;b"');
      expect(/data-cmh-cr="a\rb"/.test(html), "a literal CR in the exported attribute value is folded to LF on load")
        .toBe(false);
      const value = await reopen(browser, html, () =>
        document.getElementById("p").getAttribute("data-cmh-cr"));
      expect(value).toBe("a\rb");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a text node keeps its CR through Export as Shareable (CMH-EXP-24)", async ({ page, browser }) => {
    const staged = stageContent(TEXT_CONTENT, { key: "cmh-cr-text", source: "cr-text.html" });
    try {
      const html = await exportShareableFromFile(page, staged.html);
      expect(html, "the exported bytes must spell the CR as a character reference")
        .toContain(">a&#13;b<");
      expect(html.includes(">a\rb<"), "a literal CR in the exported text is folded to LF on load").toBe(false);
      const text = await reopen(browser, html, () => document.getElementById("t").textContent);
      expect(text).toBe("a\rb");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  // The snapshot base splices host content that follows the layer <script> back in node by node.
  // An ELEMENT there goes through cmhSerializeElement, but a direct TEXT sibling is spliced as its
  // own data, so it needs the same spelling applied explicitly or it bypasses the rule entirely.
  test("a text node after the layer script keeps its CR (CMH-EXP-24)", async ({ page, browser }) => {
    const staged = stageWithTail(CR_TAIL, "cr-tail.html");
    try {
      const html = await exportShareableFromFile(page, staged.html);
      expect(html, "tail text must spell its CR as a character reference")
        .toContain("CMHTAILa&#13;bCMHTAIL");
      expect(html.includes("CMHTAILa\rbCMHTAIL"), "a literal CR in the tail is folded to LF on load")
        .toBe(false);
      const text = await reopen(browser, html, () => document.body.textContent);
      expect(text).toContain("CMHTAILa\rbCMHTAIL");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  // Tail text whose DATA looks like markup: it must leave ESCAPED, so the CR beside it is spelled
  // into the data state (where a reload decodes it) rather than into a live raw-text body (where
  // `&#13;` is six literal characters), and so the authored text stays text instead of becoming a
  // real <script> element.
  test("markup-shaped tail text stays text, so its CR still round-trips (CMH-EXP-24)", async ({ page, browser }) => {
    const staged = stageWithTail(CR_TAIL_MARKUP, "cr-tail-markup.html");
    try {
      const html = await exportShareableFromFile(page, staged.html);
      expect(html, "the tail's markup characters must be escaped, not emitted raw")
        .toContain("CMHMKa&lt;script&gt;b&#13;c&lt;/script&gt;dCMHMK");
      const read = await reopen(browser, html, () => ({
        text: document.body.textContent,
        scripts: Array.from(document.querySelectorAll("script")).filter(
          (s) => (s.textContent || "").indexOf("CMHMK") >= 0).length,
      }));
      expect(read.text).toContain("CMHMKa<script>b\rc</script>dCMHMK");
      expect(read.scripts, "the authored text must not have become a live script").toBe(0);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  // A second, independent caller of the shared serializer. The "one rule, no path can drift" claim
  // is structural (every caller goes through cmhSerializeElement); this pins at least one more of
  // them so a future path that re-serializes on its own is caught rather than assumed away.
  test("Export Offline keeps an attribute value's CR (CMH-EXP-24)", async ({ page, browser }) => {
    const staged = stageContent(ATTR_CONTENT, { key: "cmh-cr-offline", source: "cr-offline.html" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      // Offline builds its base the same way, so pin the same assumption: without the snapshot
      // fallback the assertion below would be satisfied by the on-disk bytes instead of the pass.
      const fetchBlocked = await page.evaluate(() =>
        fetch(location.href, { cache: "no-store" }).then(() => false, () => true));
      expect(fetchBlocked).toBe(true);
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnExportOfflineTop").click(),
      ]);
      const html = await readDownload(download);
      expect(html).toContain('data-cmh-cr="a&#13;b"');
      const value = await reopen(browser, html, () =>
        document.getElementById("p").getAttribute("data-cmh-cr"));
      expect(value).toBe("a\rb");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  // The document-source normalizer runs DOWNSTREAM of the serializer: it re-encodes the
  // data-doc-source attribute after the CR pass has already run over the assembled string, so its
  // own encoder has to spell a CR the same way or it re-introduces the literal one.
  test("the document-source rewrite keeps a CR in the value it re-encodes (CMH-EXP-24)", async ({ page, browser }) => {
    const staged = stageContent(ATTR_CONTENT, {
      key: "cmh-cr-source",
      source: "reports/na&#13;me.html",
    });
    try {
      const html = await exportShareableFromFile(page, staged.html);
      // The normalizer reduces the value to its basename, and that basename keeps the CR spelled
      // as a character reference rather than as the literal CR a reload would fold to LF.
      expect(html).toContain('data-doc-source="na&#13;me.html"');
      const value = await reopen(browser, html, () =>
        document.getElementById("commentRoot").getAttribute("data-doc-source"));
      expect(value).toBe("na\rme.html");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });
});

// Unit tests for the pure pass (window.__cmhEscapeSerializedCRs). These pin the carve-outs a
// round-trip test cannot reach cheaply: a `&#13;` is NOT a character reference inside a comment or
// a raw-text body, so rewriting into one would show those six characters instead of the CR.
test.describe("Serialized-CR pass unit (CMH-EXP-24)", () => {
  async function esc(page, html) {
    return page.evaluate((h) => window.__cmhEscapeSerializedCRs(h), html);
  }

  test("text and attribute values are rewritten (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await esc(page, "<p>a\rb</p>")).toBe("<p>a&#13;b</p>");
    expect(await esc(page, '<p title="a\rb">x</p>')).toBe('<p title="a&#13;b">x</p>');
  });

  test("a string with no CR is returned unchanged (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    const input = '<div class="x"><!-- c --><script>var s = "a";</script>plain</div>';
    expect(await esc(page, input)).toBe(input);
  });

  test("a script or style body is left verbatim while its start tag is rewritten (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await esc(page, '<script data-x="a\rb">var s = "p\rq";</script>'))
      .toBe('<script data-x="a&#13;b">var s = "p\rq";</script>');
    expect(await esc(page, "<style>.a{content:'p\rq'}</style>")).toBe("<style>.a{content:'p\rq'}</style>");
  });

  test("a comment body is left verbatim (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await esc(page, "<!-- a\rb -->c\rd")).toBe("<!-- a\rb -->c&#13;d");
  });

  test("RCDATA text is rewritten, because a browser decodes a reference there (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await esc(page, "<title>a\rb</title>")).toBe("<title>a&#13;b</title>");
    expect(await esc(page, "<textarea>a\rb</textarea>")).toBe("<textarea>a&#13;b</textarea>");
  });

  test("a less-than sign inside an attribute value does not open a raw-text region (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    // The serializer escapes `&`, U+00A0 and `"` in an attribute value but NOT `<`, so this is a
    // shape a real export can produce; reading it as a <script> would silence the rewrite after it.
    expect(await esc(page, '<p title="<script>">a\rb</p>')).toBe('<p title="<script>">a&#13;b</p>');
  });

  test("a plaintext element makes the rest of the document verbatim (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await esc(page, "<p>a\rb</p><plaintext>c\rd")).toBe("<p>a&#13;b</p><plaintext>c\rd");
  });

  test("a script end tag that only prefixes the name does not end the body (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await esc(page, "<script>a\rb</scriptfoo>c\rd</script>e\rf"))
      .toBe("<script>a\rb</scriptfoo>c\rd</script>e&#13;f");
  });

  // The tokenizer's script-data DOUBLE-escaped run: inside a <script> body a `<!--` opens an
  // escaped run and a nested `<script` doubles it, so the next `</script>` only leaves that run.
  // `-->` returns to the plain script-data state (HTML5's script-data-double-escaped-dash-dash
  // state switches to the script data state on `>`), so the FOLLOWING `</script>` really is the
  // element close - and the text after it really is text. Getting this boundary wrong would either
  // corrupt a script body or silently stop rewriting.
  test("the double-escaped script-data idiom resolves the element close (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await esc(page, "<script><!--<script>a\rb</script>c\rd--></script>e\rf"))
      .toBe("<script><!--<script>a\rb</script>c\rd--></script>e&#13;f");
  });

  test("an unterminated tag or raw-text body leaves the remainder intact (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    // A tag a browser never finishes is discarded along with everything after it, so the only
    // requirement here is that nothing is lost or duplicated.
    expect(await esc(page, '<p>a\rb</p><div title="c\rd')).toBe('<p>a&#13;b</p><div title="c&#13;d');
    expect(await esc(page, "<p>a\rb</p><style>c\rd")).toBe("<p>a&#13;b</p><style>c\rd");
  });

  // The property the whole pass rests on: its output is an exact, ordered partition of its input
  // whose ONLY edit is CR -> `&#13;`. Nothing is lost, duplicated or reordered on any branch.
  test("the pass only ever substitutes, never loses or reorders content (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    const corpus = [
      "",
      "a\rb",
      "<div",
      "<style>a\rb",
      "<!--a\rb",
      "<!-->a\rb",
      "<!--->a\rb",
      "<p>a\rb</p><!--c\rd--!><script>e\rf</script>g\rh",
      '<p title="<script>x\ry">a\rb</p>',
      "<svg><plaintext>a\rb</plaintext></svg><p>c\rd</p>",
      "<textarea>a\rb</textarea><title>c\rd</title>",
      "<SCRIPT>a\rb</SCRIPT>c\rd",
    ];
    for (const input of corpus) {
      const out = await esc(page, input);
      expect(out.split("&#13;").join("\r"), `partition broken for ${JSON.stringify(input)}`).toBe(input);
    }
  });

  // A foreign <plaintext> is an ordinary SVG element to a browser and does NOT swallow the rest of
  // the document, but the walk keeps no namespace stack. Pinned as the DECLARED behavior: the pass
  // declines to rewrite after it (fidelity is not improved) rather than risking a real raw-text
  // body, and this test is what makes that a decision rather than an accident.
  test("a foreign plaintext declines the rewrite rather than risking a raw-text body (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await esc(page, "<p>a\rb</p><svg><plaintext></plaintext></svg><p>c\rd</p>"))
      .toBe("<p>a&#13;b</p><svg><plaintext></plaintext></svg><p>c\rd</p>");
  });

  // The other half of the same declared limit: a foreign <style> body IS escaped by the serializer
  // and IS decoded by the parser, but the walk has no namespace stack and leaves it verbatim.
  // Ordinary text AFTER it is still rewritten, so the decline is scoped to that body.
  test("a foreign style body is left verbatim while later text is still rewritten (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await esc(page, "<svg><style>a\rb</style></svg><p>c\rd</p>"))
      .toBe("<svg><style>a\rb</style></svg><p>c&#13;d</p>");
  });
});

// The attribute decode is the half of the round trip that reads a value back OUT of the serialized
// string. It is a separate rule from the walk, and the newline behavior is exactly what a refactor
// back to a <textarea> would silently undo, so it is pinned directly rather than only through the
// data-doc-source round trip.
test.describe("Attribute decode keeps a CR (CMH-EXP-24)", () => {
  async function dec(page, value) {
    return page.evaluate((v) => window.__cmhDecodeAttribute(v), value);
  }

  test("a character-reference CR decodes to a CR, not an LF (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await dec(page, "a&#13;b")).toBe("a\rb");
    expect(await dec(page, "a&#13;&#10;b")).toBe("a\r\nb");
  });

  test("a literal newline and a leading newline are preserved (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await dec(page, "\nab")).toBe("\nab");
    expect(await dec(page, "a\nb")).toBe("a\nb");
  });

  test("ordinary references and markup characters decode unchanged (CMH-EXP-24)", async ({ page }) => {
    await openInline(page);
    expect(await dec(page, "a&amp;b")).toBe("a&b");
    expect(await dec(page, "a&lt;b&gt;c")).toBe("a<b>c");
    // `<` is escaped before the parse, so a value that looks like markup stays text and cannot
    // build an element in the holder.
    expect(await dec(page, "a<script>b</script>c")).toBe("a<script>b</script>c");
    expect(await dec(page, "")).toBe("");
  });
});
