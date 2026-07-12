// Export to Markdown: a deterministic content -> Markdown conversion, delivered as a
// .md download, reachable from the sidebar and the overflow menu.
import { test, expect } from "@playwright/test";
import {
  fileUrl, ready, installClipboardCapture, stageContent,
  openKitchenSink, openToolbarMenu, addTextComment,
  routeMermaidLocal, startStaticServer,
} from "./helpers.js";

async function openRich(page, content, key) {
  await installClipboardCapture(page);
  const { html } = stageContent(content, { key });
  await page.goto(fileUrl(html));
  await ready(page);
  return html;
}

test("kitchen-sink converts to structured Markdown", async ({ page }) => {
  await openKitchenSink(page);
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("# Kitchen-sink sample");
  expect(md).toContain("| Metric | Before | After |");
  expect(md).toContain("| --- | --- | --- |");
  expect(md).toContain("| p95 latency | 1.8s | 640ms |");
  expect(md).toContain("```python");
  expect(md).toContain("```mermaid");
  expect(md).toContain("flowchart LR");
  expect(md).toContain("[real link](https://example.com/spec#section-3)");
  expect(md).toContain("`inline-code`");
  expect(md).toMatch(/^- First bullet/m);
});

test("the Markdown export leaks no raw HTML block tags", async ({ page }) => {
  await openKitchenSink(page);
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).not.toMatch(/<\/?(div|section|table|thead|tbody|tr|td|th|figure|span|strong|em)\b/i);
});

test("the converter is deterministic (byte-identical across runs)", async ({ page }) => {
  await openKitchenSink(page);
  const [a, b] = await page.evaluate(() => [window.__cmhToMarkdown(), window.__cmhToMarkdown()]);
  expect(a).toBe(b);
  expect(a.endsWith("\n")).toBe(true);
  expect(a).not.toMatch(/\n{3,}/);
});

test("callouts, charts, and diffs map to their fixed Markdown forms", async ({ page }) => {
  const RICH = `
    <h1>Rich</h1>
    <div class="cmh-callout cmh-callout-warning"><strong>Careful.</strong> Watch out here.</div>
    <figure class="chart"><div class="chart-wrap cm-skip"><canvas id="c1" aria-label="Trend"></canvas></div><figcaption>My chart</figcaption></figure>
    <pre class="cmh-diff" data-diff-label="app.js">@@ -1,2 +1,2 @@
-old line
+new line
 context</pre>`;
  await openRich(page, RICH, "cmh-md-rich");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("> [!WARNING]");
  expect(md).toContain("Careful.");
  expect(md).toContain("_[Chart: My chart]_");
  expect(md).toContain("```diff");
  expect(md).toContain("+new line");
  expect(md).toContain("-old line");
});

test("a mermaid diagram exports its source, not the rendered SVG", async ({ page }) => {
  const M = `<h1>M</h1><pre class="mermaid cm-skip">\nflowchart LR\n  A --> B\n</pre>`;
  await openRich(page, M, "cmh-md-mermaid");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("```mermaid");
  expect(md).toContain("A --> B");
});

test("live comments are appended as a Review comments section", async ({ page }) => {
  await openKitchenSink(page);
  await addTextComment(page, "#dup-a", "please clarify");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("## Review comments (1)");
  expect(md).toContain("please clarify");
});

test("Export to Markdown downloads a .md file and does NOT write the clipboard", async ({ page }) => {
  await openKitchenSink(page);
  // Use the overflow-menu entry: the sidebar auto-closes with zero comments, so its
  // buttons sit off-screen; the floating toolbar menu is the reliable path here.
  await openToolbarMenu(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.click("#btnExportMdTop"),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.md$/);
  // The Markdown export is download-only: it must not push anything to the clipboard.
  const copied = await page.evaluate(() => (window.__copied || []).slice());
  expect(copied).toEqual([]);
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("# Kitchen-sink sample");
});

test("Export to Markdown is available in the sidebar and the overflow menu", async ({ page }) => {
  await openKitchenSink(page);
  await expect(page.locator("#btnExportMd")).toBeVisible();
  await openToolbarMenu(page);
  await expect(page.locator("#btnExportMdTop")).toBeVisible();
});

test("inline code containing backticks is fenced safely", async ({ page }) => {
  const C = '<h1>C</h1><p>Run <code>git commit -m "`x`"</code> now.</p>';
  await openRich(page, C, "cmh-md-backtick");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  // The inline code must use a backtick run longer than the run inside it (two here).
  expect(md).toContain('``git commit -m "`x`"``');
});

test("link and image labels/URLs are escaped", async ({ page }) => {
  const C = '<h1>L</h1>'
    + '<p><a href="https://e.com/a(b)?x=1 2">text [with] brackets</a></p>'
    + '<figure><img src="https://e.com/i(1).png" alt="alt [x]"><figcaption>cap</figcaption></figure>';
  await openRich(page, C, "cmh-md-links");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("[text \\[with\\] brackets](<https://e.com/a(b)?x=1 2>)");
  expect(md).toContain("![alt \\[x\\]](<https://e.com/i(1).png>)");
});

test("a list item containing a block child keeps the block", async ({ page }) => {
  const C = '<h1>Nested</h1><ul><li>Item with code:<pre><code class="language-js">const x = 1;</code></pre></li><li>plain</li></ul>';
  await openRich(page, C, "cmh-md-listblock");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("- Item with code:");
  expect(md).toMatch(/- Item with code:\n\s+```js\n\s+const x = 1;/);
});

test("a blockquote and an image figure map to their forms", async ({ page }) => {
  const C = '<h1>B</h1><blockquote><p>quoted wisdom</p></blockquote>'
    + '<figure><img src="pic.png" alt="a picture"><figcaption>cap</figcaption></figure>';
  await openRich(page, C, "cmh-md-bq");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("> quoted wisdom");
  expect(md).toContain("![a picture](pic.png)");
});

test("a KQL figure exports a kusto fence and the run link", async ({ page }) => {
  const C = '<h1>K</h1><figure class="cmh-kql"><pre><code class="language-kusto">StormEvents | take 5</code></pre>'
    + '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x">Run</a><figcaption>q</figcaption></figure>';
  await openRich(page, C, "cmh-md-kql");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("```kusto");
  expect(md).toContain("StormEvents | take 5");
  expect(md).toContain("[Run in Azure Data Explorer](https://dataexplorer.azure.com/x)");
});

test("a comment note cannot forge headings/fences or inject HTML in the appendix", async ({ page }) => {
  await openKitchenSink(page);
  await addTextComment(page, "#dup-a", "line one\n## Injected heading\n```\nnot a real fence\n<img src=x onerror=alert(1)>");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  // Each note line is escaped like prose and emitted as a blockquote, so no bare heading,
  // fence, or raw HTML tag survives into the export.
  expect(md).toContain("> \\## Injected heading");
  expect(md).not.toMatch(/^## Injected heading/m);
  expect(md).toContain("> \\`\\`\\`");
  expect(md).toContain("> \\<img src=x onerror=alert(1)>");
  expect(md).not.toContain("> <img src=x onerror=alert(1)>");
  expect(md).toContain("## Review comments (1)");
});

test("export is deterministic and sort-independent with seeded comments", async ({ page }) => {
  await openKitchenSink(page);
  await addTextComment(page, "#dup-a", "note A");
  const before = await page.evaluate(() => [window.__cmhToMarkdown(), window.__cmhToMarkdown()]);
  expect(before[0]).toBe(before[1]);
  // Sorting a table must not change the exported Markdown (canonical row order).
  await page.evaluate(() => {
    const btn = document.querySelector("#commentRoot table .cmh-sort-ctrl");
    if (btn) btn.click();
  });
  const after = await page.evaluate(() => window.__cmhToMarkdown());
  expect(after).toBe(before[0]);
});

test("mermaid exports its SOURCE even after it renders over http", async ({ page }) => {
  const C = '<h1>M</h1><pre class="mermaid cm-skip">\nflowchart LR\n  A --> B\n</pre>';
  const { dir } = stageContent(C, { key: "cmh-md-mermaid-http" });
  const server = await startStaticServer(dir);
  try {
    await routeMermaidLocal(page);
    await installClipboardCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    // Wait for mermaid to actually render (host now contains an <svg>).
    await page.waitForFunction(() => !!document.querySelector("pre.mermaid svg"), null, { timeout: 8000 });
    const md = await page.evaluate(() => window.__cmhToMarkdown());
    expect(md).toContain("```mermaid");
    expect(md).toContain("A --> B");
    expect(md).not.toContain("<svg");
  } finally {
    await server.close();
  }
});

test("a backslash in link text cannot hijack the destination", async ({ page }) => {
  const C = '<h1>H</h1><p><a href="https://legit.example/">Click here\\</a>SECRET](https://evil.example/)</p>';
  await openRich(page, C, "cmh-md-hijack");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("[Click here\\\\](https://legit.example/)");
  expect(md).toContain("SECRET\\](https://evil.example/)");
});

test("plain prose cannot forge headings, blockquotes, lists, or rules", async ({ page }) => {
  const C = '<h1>H</h1><p># Not a heading</p><p>&gt; not a quote</p><p>1. not a list</p><p>- not a bullet</p><p>---</p>';
  await openRich(page, C, "cmh-md-leading");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("\\# Not a heading");
  expect(md).toContain("\\> not a quote");
  expect(md).toContain("1\\. not a list");
  expect(md).toContain("\\- not a bullet");
  expect(md).not.toMatch(/^# Not a heading/m);
});

test("a div.mermaid exports its source too", async ({ page }) => {
  const C = '<h1>H</h1><div class="mermaid cm-skip">\nflowchart TD\n  X --> Y\n</div>';
  await openRich(page, C, "cmh-md-divmermaid");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("```mermaid");
  expect(md).toContain("X --> Y");
});

test("ordered-list continuation indents to the marker width", async ({ page }) => {
  const C = '<h1>H</h1><ol><li>one<ul><li>sub</li></ul></li></ol>';
  await openRich(page, C, "cmh-md-ol");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("1. one");
  expect(md).toContain("\n   - sub");
});

test("attribute-derived labels (image alt) escape HTML and markup", async ({ page }) => {
  const C = '<h1>H</h1><figure><img src="x.png" alt="<img src=x onerror=alert(1)> *b* _c_"><figcaption>c</figcaption></figure>';
  await openRich(page, C, "cmh-md-altxss");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("![\\<img src=x onerror=alert(1)> \\*b\\* \\_c\\_](x.png)");
});

test("direct text inside a container cannot forge a heading", async ({ page }) => {
  const C = '<h1>H</h1><div># forged heading</div>';
  await openRich(page, C, "cmh-md-divtext");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("\\# forged heading");
  expect(md).not.toMatch(/^# forged heading/m);
});

test("list continuation text after a block child cannot forge a heading", async ({ page }) => {
  const C = '<h1>L</h1><ul><li><pre><code>code</code></pre># forged in continuation</li></ul>';
  await openRich(page, C, "cmh-md-listcont");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("\\# forged in continuation");
  expect(md).not.toMatch(/^\s*# forged in continuation/m);
});

test("an inline image inside prose exports as Markdown image syntax", async ({ page }) => {
  const C = '<h1>I</h1><p>Before <img src="in.png" alt="inline pic"> after.</p>';
  await openRich(page, C, "cmh-md-inlineimg");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("![inline pic](in.png)");
});

test("a code language class with a backtick cannot void the fence", async ({ page }) => {
  const C = '<h1>P</h1><pre><code class="language-a`b">payload</code></pre>';
  await openRich(page, C, "cmh-md-fencelang");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("```ab\npayload");
  expect(md).not.toContain("a`b");
});

test("a javascript: link URL is neutralized in the export", async ({ page }) => {
  const C = '<h1>J</h1><p><a href="javascript:alert(1)">click</a></p>';
  await openRich(page, C, "cmh-md-jsurl");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("[click](about:blank)");
  expect(md).not.toContain("javascript:alert(1)");
});

test("a comment note cannot forge a setext heading", async ({ page }) => {
  await openKitchenSink(page);
  await addTextComment(page, "#dup-a", "Setext H1\n===\nSetext H2\n-");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("> \\===");
  expect(md).toContain("> \\-");
  expect(md).not.toMatch(/^===$/m);
});

test("a comment note cannot forge a GFM table", async ({ page }) => {
  await openKitchenSink(page);
  await addTextComment(page, "#dup-a", "col1 | col2\n--- | ---\nv1 | v2");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("> col1 \\| col2");
  expect(md).toContain("> --- \\| ---");
});

test("a bang before a link is not turned into an image but stays a link", async ({ page }) => {
  const C = '<h1>H</h1><p>wow!<a href="https://x.com/p">link</a></p>';
  await openRich(page, C, "cmh-md-banglink");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  // The bang is escaped (so no image), and the link syntax is left intact (so the link works).
  expect(md).toContain("wow\\![link](https://x.com/p)");
  expect(md).not.toContain("wow![link]");
});

test("a captioned image with empty alt does not double-escape the caption fallback", async ({ page }) => {
  const C = '<h1>H</h1><figure><img src="x.png" alt=""><figcaption>a*b_c</figcaption></figure>';
  await openRich(page, C, "cmh-md-figalt");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("![a\\*b\\_c](x.png)");
  expect(md).not.toContain("a\\\\*b");
});

test("a link URL with a leading control char cannot smuggle an executable scheme", async ({ page }) => {
  await openRich(page, '<h1>H</h1><p>x</p>', "cmh-md-ctrlurl");
  const md = await page.evaluate(() => {
    const root = document.getElementById("commentRoot") || document.body;
    const p = document.createElement("p");
    const a = document.createElement("a");
    a.setAttribute("href", String.fromCharCode(1) + "javascript:alert(1)");
    a.textContent = "clk";
    p.appendChild(a);
    root.appendChild(p);
    return window.__cmhToMarkdown();
  });
  expect(md).toContain("[clk](about:blank)");
  expect(md).not.toContain("javascript:alert(1)");
});

test("pipes inside code spans in a table cell stay escaped, not column boundaries", async ({ page }) => {
  const C = '<h1>T</h1><table><thead><tr><th>cmd</th><th>note</th></tr></thead>'
    + '<tbody><tr><td><code>a|b</code></td><td>plain</td></tr>'
    + '<tr><td><code>x\\|y</code></td><td>ok</td></tr></tbody></table>';
  await openRich(page, C, "cmh-md-cellpipe");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  const rows = md.split("\n").filter((l) => l.startsWith("|"));
  expect(rows.length).toBe(4);
  // Every row of a 2-column table must expose exactly 3 structural (unescaped) pipes; the pipes
  // inside the code spans must remain escaped so they do not forge extra columns.
  for (const r of rows) {
    const structural = (r.match(/(?<!\\)\|/g) || []).length;
    expect(structural).toBe(3);
  }
  expect(md).toContain("`a\\|b`");
});
