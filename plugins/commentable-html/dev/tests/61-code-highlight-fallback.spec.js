import { test, expect } from "@playwright/test";
import { fileUrl, ready, stageContent, installClipboardCapture, addTextComment } from "./helpers.js";

// Runtime fallback: a <pre><code class="language-XXX"> block authored without highlight spans is
// tokenized on load, so a document that was never run through highlight_code.py still renders
// highlighted instead of monochrome. Unknown/non-tokenizable labels are left plain, and commenting
// on a now-highlighted block still round-trips through reload.
test.describe("runtime code-highlight fallback (CMH-HL-01)", () => {
  async function open(page, content, key) {
    const { html } = stageContent(content, { key });
    await installClipboardCapture(page);
    await page.goto(fileUrl(html));
    await ready(page);
    return html;
  }

  test("a language-labelled block with no spans is highlighted on load; unknown labels stay plain", async ({ page }) => {
    await open(page,
      "<h1>Code</h1>"
      + '<pre><code class="language-csharp">public sealed class X { int Y { get; } }</code></pre>'
      + '<pre><code class="language-text">just plain text no tokens</code></pre>',
      "cmh-hl-fallback-1");

    // The C# block gets runtime keyword highlight spans (public/sealed/class/get).
    const cs = page.locator("#commentRoot pre code.language-csharp");
    await expect(cs.locator("span.cmh-code-kw").first()).toBeVisible();
    expect(await cs.locator("span.cmh-code-kw").count()).toBeGreaterThan(0);
    // Text content is unchanged by highlighting.
    expect((await cs.textContent()).trim()).toBe("public sealed class X { int Y { get; } }");

    // A non-tokenizable label is left plain (no token spans; the line-number gutter is not a token).
    const txt = page.locator("#commentRoot pre code.language-text");
    await expect(txt.locator("span.cmh-code-kw")).toHaveCount(0);
    await expect(txt.locator("span.cmh-code-str, span.cmh-code-num, span.cmh-code-op, span.cmh-code-com")).toHaveCount(0);
  });

  test("an unbaked language-html and language-xml block is highlighted on load (markup family) (CMH-HL-01)", async ({ page }) => {
    await open(page,
      "<h1>Markup</h1>"
      + '<pre><code class="language-html">&lt;div class="cmh-note" id="x"&gt;&lt;!-- c --&gt;hi&lt;/div&gt;</code></pre>'
      + '<pre><code class="language-xml">&lt;item name="a"&gt;&lt;!-- x --&gt;&lt;/item&gt;</code></pre>',
      "cmh-hl-fallback-markup");

    // HTML: tag name -> keyword, attribute value -> string, <!-- --> -> comment.
    const htmlCode = page.locator("#commentRoot pre code.language-html");
    await expect(htmlCode.locator('span.cmh-code-kw', { hasText: "div" }).first()).toBeVisible();
    await expect(htmlCode.locator("span.cmh-code-str").first()).toBeVisible();
    await expect(htmlCode.locator("span.cmh-code-com").first()).toBeVisible();
    // Highlighting must not change the block's text.
    expect((await htmlCode.textContent())).toContain('<div class="cmh-note" id="x">');

    // XML gets the same markup treatment.
    const xmlCode = page.locator("#commentRoot pre code.language-xml");
    await expect(xmlCode.locator('span.cmh-code-kw', { hasText: "item" }).first()).toBeVisible();
    await expect(xmlCode.locator("span.cmh-code-str").first()).toBeVisible();
    await expect(xmlCode.locator("span.cmh-code-com").first()).toBeVisible();
  });

  test("an already-highlighted (baked) block is not re-highlighted", async ({ page }) => {
    await open(page,
      "<h1>Baked</h1>"
      + '<pre><code class="language-python"><span class="cmh-code-kw">def</span> f(): <span class="cmh-code-kw">return</span> 1</code></pre>',
      "cmh-hl-fallback-2");
    const kw = page.locator("#commentRoot pre code.language-python span.cmh-code-kw");
    // Exactly the two authored keyword spans - the fallback did not wrap the block again.
    await expect(kw).toHaveCount(2);
  });

  test("a comment on a runtime-highlighted code block survives reload", async ({ page }) => {
    await open(page,
      "<h1>Anchor</h1>"
      + '<pre><code class="language-csharp">public sealed class Widget { }</code></pre>',
      "cmh-hl-fallback-3");
    await expect(page.locator("#commentRoot pre code.language-csharp span.cmh-code-kw").first()).toBeVisible();
    await addTextComment(page, "#commentRoot pre code.language-csharp", "review this class");
    await expect(page.locator("#commentRoot pre mark.cm-hl")).not.toHaveCount(0);

    await page.reload();
    await ready(page);
    // The comment re-anchors on the (again highlighted) block.
    await expect(page.locator("#commentRoot pre code.language-csharp span.cmh-code-kw").first()).toBeVisible();
    await expect(page.locator("#commentRoot pre mark.cm-hl")).not.toHaveCount(0);
  });
});
