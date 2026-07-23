import { test, expect } from "@playwright/test";
import { fileUrl, ready, stageContent } from "./helpers.js";

// CMH-CODE-08 (issue #619): the code line-number gutter created one <span> per line unbounded, and
// the runtime highlighter tokenized a known-language block into many spans regardless of size. A
// pathologically large authored code block could therefore allocate hundreds of thousands of DOM
// nodes on open and freeze the tab. Mirroring the diff renderer's CMH_DIFF_MAX_LINES cap, a block
// over CMH_CODE_MAX_LINES lines skips the per-line gutter, and a block over CMH_CODE_MAX_CHARS
// characters is left un-tokenized (plain, still readable and commentable), so the cost stays bounded.
test.describe("code block resource caps (CMH-CODE-08)", () => {
  async function open(page, content, key) {
    const { html } = stageContent(content, { key });
    await page.goto(fileUrl(html));
    await ready(page);
    return html;
  }

  test("a huge code block does not allocate one gutter span per line", async ({ page }) => {
    const lines = [];
    for (let i = 0; i < 20000; i++) lines.push("line " + i);
    await open(page,
      "<h1>Big</h1><pre><code>" + lines.join("\n") + "</code></pre>",
      "cmh-code-cap-gutter");
    // Over CMH_CODE_MAX_LINES the gutter is skipped entirely (old code created exactly one span per
    // authored line), so no per-line gutter spans exist at all.
    const gutterLines = await page.locator("#commentRoot pre code span.cmh-code-line").count();
    expect(gutterLines).toBe(0);
  });

  test("a block over the char cap but under the line cap skips the gutter (guard runs before the split)", async ({ page }) => {
    // Only ~100 lines (well under CMH_CODE_MAX_LINES) but each is huge, so the block is over
    // CMH_CODE_MAX_CHARS. The char guard must fire BEFORE the split allocation, so the gutter is
    // skipped even though the line count alone would allow it (old code made one span per line here).
    const wide = "x".repeat(3000);
    const lines = [];
    for (let i = 0; i < 100; i++) lines.push(wide);
    await open(page,
      "<h1>Wide</h1><pre><code>" + lines.join("\n") + "</code></pre>",
      "cmh-code-cap-gutter-wide");
    const gutterLines = await page.locator("#commentRoot pre code span.cmh-code-line").count();
    expect(gutterLines).toBe(0);
  });

  test("a normal code block still gets a per-line gutter", async ({ page }) => {
    const lines = [];
    for (let i = 0; i < 12; i++) lines.push("row " + i);
    await open(page,
      "<h1>Small</h1><pre><code>" + lines.join("\n") + "</code></pre>",
      "cmh-code-cap-gutter-ok");
    const gutterLines = await page.locator("#commentRoot pre code span.cmh-code-line").count();
    expect(gutterLines).toBe(12);
  });

  test("an enormous language-labelled block is left un-tokenized", async ({ page }) => {
    // Repeat a small JS snippet until it comfortably exceeds the char cap.
    const unit = "const x = 1; function f() { return x; }\n";
    let big = "";
    while (big.length < 250000) big += unit;
    await open(page,
      "<h1>Huge</h1>"
      + '<pre><code class="language-js">' + big + "</code></pre>",
      "cmh-code-cap-tokens");
    // Over the char cap the highlighter bails out, so no keyword token spans are created.
    const kw = await page.locator("#commentRoot pre code.language-js span.cmh-code-kw").count();
    expect(kw).toBe(0);
  });

  test("a modest language-labelled block is still tokenized", async ({ page }) => {
    await open(page,
      "<h1>Modest</h1>"
      + '<pre><code class="language-js">const x = 1; function f() { return x; }</code></pre>',
      "cmh-code-cap-tokens-ok");
    const kw = await page.locator("#commentRoot pre code.language-js span.cmh-code-kw").count();
    expect(kw).toBeGreaterThan(0);
  });
});
