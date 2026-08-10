import { test, expect } from "@playwright/test";
import fs from "fs";
import zlib from "node:zlib";
import {
  stageContent, fileUrl, ready, readDownload, openToolbarMenu, addTextComment, denyExternalNetwork,
} from "./helpers.js";

// CMH-COLD: the cold tier stores a large table's row TAIL compressed and the runtime restores it
// synchronously, before anything else in the layer touches the DOM.
//
// The point of these tests is not "does it decompress" - the Python suite pins the codec against
// zlib. It is that the reader cannot tell. So the load-bearing assertion is a DOM SNAPSHOT DIFF
// against the same document with no cold tier at all: if the hydrated tree differs by so much as a
// whitespace text node, anchors, section content hashes and every export drift with it.
//
// The marker vocabulary here is pinned to `tools/authoring/cold_tier.py` by
// `tests/test_cold_tier.py` (`SpecFixtureTests`), so this fixture cannot drift from the real tool.
const BLOB_ID = "cmhColdTier";
const SLOT_CLASS = "cmh-cold-slot";
const PART_ATTR = "data-cmh-cold-part";
const FENCE_OPEN = "<!-- BEGIN: commentable-html - COLD TIER (generated machinery; safe to skip) -->";
const FENCE_CLOSE = "<!-- END: commentable-html - COLD TIER -->";
const KEEP = 20;
const TOTAL = 60;

function rows(from, to) {
  const out = [];
  for (let i = from; i < to; i += 1) {
    out.push(`    <tr><td>r${i}</td><td>value ${i}</td><td>note ${i}</td></tr>`);
  }
  return out.join("\n");
}

// The fully-plain document: what the tier must be indistinguishable from.
const PLAIN_CONTENT = `<h1>Cold tier</h1>
<p>Prose stays plain.</p>
<table>
  <caption>Rows</caption>
  <thead><tr><th>a</th><th>b</th><th>c</th></tr></thead>
  <tbody>
${rows(0, TOTAL)}
  </tbody>
</table>`;

function placeholder(partId, cols, count) {
  const unit = count === 1 ? "table row" : "table rows";
  const verb = count === 1 ? "is" : "are";
  const explain = `${count} ${unit} here ${verb} stored compressed further down in this same file `
    + `(see the COLD TIER block) and ${verb} restored automatically when scripting is enabled. `
    + "No network access is needed either way.";
  const note = `${count} ${unit} here ${verb} stored compressed further down in this same file `
    + `(see the COLD TIER block) and ${count === 1 ? "was" : "were"} not expanded. Open this file `
    + "in a browser with scripting enabled, or run the skill's cold_tier.py --expand on it, to "
    + "read them.";
  return `<tr class="${SLOT_CLASS} cm-skip" ${PART_ATTR}="${partId}"><td colspan="${cols}">`
    + `<noscript>${explain}</noscript>`
    + `<span class="cmh-cold-note">${note}</span>`
    + "</td></tr>";
}

// The compressed document, built exactly the way `cold_tier.py` builds it. The cut BOUNDARY
// matters: the real compressor cuts from the `<` of the first cold `<tr>` to the last `</tr>`, so
// the leading indentation stays in the skeleton and the placeholder sits where that `<tr>` was.
// Cutting the indentation too would round-trip to the same text but put the inter-row whitespace
// on the other side of the boundary, which is exactly what the "identical DOM" test exists to
// catch. `SpecFixtureTests` in test_cold_tier.py pins this construction against the real emitter.
const TAIL_CUT = rows(KEEP, TOTAL).replace(/^ +/, "");
const COLD_CONTENT = PLAIN_CONTENT.replace(TAIL_CUT, placeholder("cmh-cold-1", 3, TOTAL - KEEP));

function payloadBlock({ corrupt = false } = {}) {
  let data = zlib.gzipSync(Buffer.from(TAIL_CUT, "utf8"), { level: 9 }).toString("base64");
  if (corrupt) data = data.slice(0, 24) + "AAAAAAAAAAAA" + data.slice(36);
  const json = JSON.stringify({
    v: 1,
    parts: [{ data, enc: "gzip+base64", id: "cmh-cold-1", rows: TOTAL - KEEP }],
  });
  return `\n${FENCE_OPEN}\n<script type="application/json" id="${BLOB_ID}">${json}</script>\n${FENCE_CLOSE}`;
}

/** A staged document whose table tail lives in the compressed payload.
 *
 * The block goes immediately after the content root's `</main>`, exactly where `cold_tier.py`
 * puts it - and NOT before `</body>`. The layer is an inline classic script the browser runs
 * during parse, so a payload after it does not exist yet when the loader looks for it; a
 * `</body>`-anchored fixture would silently test a document whose rows never come back.
 */
function stageCold({ corrupt = false } = {}) {
  const staged = stageContent(COLD_CONTENT, { key: "cmh-cold-tier" });
  const html = fs.readFileSync(staged.html, "utf8");
  const at = html.indexOf("</main>");
  expect(at).toBeGreaterThan(0);
  const cut = at + "</main>".length;
  fs.writeFileSync(staged.html, html.slice(0, cut) + payloadBlock({ corrupt }) + html.slice(cut));
  return staged;
}

async function bodyRowIds(page) {
  return page.$$eval("#commentRoot tbody tr td:first-child", (cells) => cells.map((c) => c.textContent));
}

test.describe("Cold tier (CMH-COLD)", () => {
  test("the raw file keeps the skeleton literal and the cold rows out of it (CMH-COLD-01)", async () => {
    const staged = stageCold();
    const raw = fs.readFileSync(staged.html, "utf8");
    // Always plain: a reader, a search indexer or an AI tool sees these without running anything.
    expect(raw).toContain("<h1>Cold tier</h1>");
    expect(raw).toContain("<p>Prose stays plain.</p>");
    expect(raw).toContain("<caption>Rows</caption>");
    expect(raw).toContain("<th>a</th>");
    expect(raw).toContain("<td>r0</td>");
    expect(raw).toContain(`<td>r${KEEP - 1}</td>`);
    // Cold: only in the payload.
    expect(raw).not.toContain(`<td>r${KEEP}</td>`);
    expect(raw).not.toContain(`<td>r${TOTAL - 1}</td>`);
    // Machinery-last and fenced.
    expect(raw.indexOf(BLOB_ID)).toBeGreaterThan(raw.indexOf("</main>"));
    expect(raw).toContain(FENCE_OPEN);
    expect(raw).toContain(FENCE_CLOSE);
  });

  test("expands the cold tier before the comment layer initializes (CMH-COLD-04)", async ({ page }) => {
    await denyExternalNetwork(page);
    const staged = stageCold();
    await page.goto(fileUrl(staged.html));
    await ready(page);
    expect(await bodyRowIds(page)).toEqual(
      Array.from({ length: TOTAL }, (_, i) => `r${i}`));
    // Hydration is done and cleaned up: no placeholder, no payload, no fence left behind. The
    // fence check counts COMMENT NODES - the layer's own script carries the fence text as a regex
    // literal, so a substring test on the serialized body can never pass.
    await expect(page.locator(`.${SLOT_CLASS}`)).toHaveCount(0);
    await expect(page.locator(`#${BLOB_ID}`)).toHaveCount(0);
    expect(await page.evaluate(() => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_COMMENT);
      let node;
      let seen = 0;
      while ((node = walker.nextNode())) if (/COLD TIER/.test(node.nodeValue)) seen += 1;
      return seen;
    })).toBe(0);
    // Text in the cold tier is findable now that it is materialized.
    expect(await page.evaluate(() => document.body.innerText)).toContain(`note ${TOTAL - 1}`);
    // No failure toast. The startup diagnostic flushes one turn after DOMContentLoaded, so wait
    // for that turn before asserting - and assert on CONTENT, since `#toast` is only faded out
    // with `opacity`, which Playwright counts as visible.
    await page.waitForFunction(() => document.readyState === "complete");
    await page.waitForTimeout(50);
    await expect(page.locator("#toast")).toHaveText("");
  });

  test("the hydrated DOM is identical to the uncompressed document (CMH-COLD-04)", async ({ page }) => {
    const read = async (staged) => {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      // The layer injects its own chrome into the root; compare the TABLE, which is the part the
      // tier touches, node for node including the whitespace between rows.
      return page.evaluate(() => document.querySelector("#commentRoot table").outerHTML);
    };
    const plainHtml = await read(stageContent(PLAIN_CONTENT, { key: "cmh-cold-plain" }));
    const coldHtml = await read(stageCold());
    expect(coldHtml).toBe(plainHtml);
  });

  test("expands with DecompressionStream deleted (CMH-COLD-05)", async ({ page }) => {
    // The loader never calls it, so this is the strongest form of the backwards-compatibility
    // promise: the pure-JS inflate is what every browser runs.
    await page.addInitScript(() => {
      delete window.DecompressionStream;
      delete window.CompressionStream;
    });
    const staged = stageCold();
    await page.goto(fileUrl(staged.html));
    await ready(page);
    expect(await page.evaluate(() => typeof window.DecompressionStream)).toBe("undefined");
    expect(await bodyRowIds(page)).toHaveLength(TOTAL);
    expect(await page.evaluate(() => document.body.innerText)).toContain(`note ${TOTAL - 1}`);
  });

  test("a comment anchored in the cold tier survives a reload (CMH-COLD-04)", async ({ page }) => {
    const staged = stageCold();
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot tbody tr:nth-child(55) td:nth-child(3)",
      "a note on a restored row");
    await expect(page.locator("mark.cm-hl")).toHaveCount(1);
    const anchored = await page.locator("mark.cm-hl").first().textContent();
    await page.reload();
    await ready(page);
    await expect(page.locator("mark.cm-hl")).toHaveCount(1);
    expect(await page.locator("mark.cm-hl").first().textContent()).toBe(anchored);
    await expect(page.locator(".cm-card")).toContainText("a note on a restored row");
  });

  test("an export carries the expanded rows and no payload (CMH-COLD-04)", async ({ page }) => {
    const staged = stageCold();
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSavePlainTop"),
    ]);
    const html = await readDownload(download);
    expect(html).toContain(`<td>r${TOTAL - 1}</td>`);
    expect(html).not.toContain(BLOB_ID);
    // The CSS region survives a plain export by design, and it names the placeholder class - so
    // assert the MARKUP spelling, not the bare class name.
    expect(html).not.toContain(`class="${SLOT_CLASS}`);
    expect(html).not.toContain(`${PART_ATTR}=`);
  });

  test("print sees the complete table (CMH-COLD-04)", async ({ page }) => {
    const staged = stageCold();
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await page.emulateMedia({ media: "print" });
    await expect(page.locator(`#commentRoot tbody tr:has-text("note ${TOTAL - 1}")`)).toBeVisible();
    expect(await bodyRowIds(page)).toHaveLength(TOTAL);
  });

  test("a corrupt payload leaves the plain tier and explains itself (CMH-COLD-06)", async ({ page }) => {
    const staged = stageCold({ corrupt: true });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // The plain tier is intact and the document is fully usable - never a blank page. The
    // placeholder row stays (it is what carries the explanation), so it counts as a row too.
    const ids = await bodyRowIds(page);
    expect(ids).toHaveLength(KEEP + 1);
    expect(ids.slice(0, KEEP)).toEqual(Array.from({ length: KEEP }, (_, i) => `r${i}`));
    await expect(page.locator("h1")).toHaveText("Cold tier");
    // The placeholder now explains itself, and the layer says so once, without blocking.
    await expect(page.locator(`.${SLOT_CLASS} .cmh-cold-note`)).toBeVisible();
    await expect(page.locator("#toast")).toContainText("could not be expanded");
    expect(errors).toEqual([]);
    // A failed expansion is never half applied.
    expect(ids).not.toContain(`r${TOTAL - 1}`);
  });

  test("explains itself with JavaScript disabled (CMH-COLD-07)", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    const staged = stageCold();
    await page.goto(fileUrl(staged.html));
    // The uncompressed tier renders, and the placeholder row says where the rest is.
    await expect(page.locator("h1")).toHaveText("Cold tier");
    expect(await bodyRowIds(page)).toHaveLength(KEEP + 1);
    expect((await bodyRowIds(page)).slice(0, KEEP)).toEqual(
      Array.from({ length: KEEP }, (_, i) => `r${i}`));
    // Read the <noscript> content DIRECTLY: Playwright's text matchers skip it, so asserting on
    // the row's text would silently match the sibling note span instead (both say "stored
    // compressed") and prove nothing about the no-JS path.
    const noscript = await page.evaluate(
      () => document.querySelector("tr.cmh-cold-slot noscript").textContent);
    expect(noscript).toContain("stored compressed further down in this same file");
    expect(noscript).toContain("restored automatically when scripting is enabled");
    expect(noscript).toContain("No network access is needed");
    // The note meant for a runtime that has no loader stays hidden here: with scripting off the
    // stylesheet still applies, so the reader sees the <noscript> line and only that one.
    await expect(page.locator(`.${SLOT_CLASS} .cmh-cold-note`)).toBeHidden();
    await context.close();
  });
});
