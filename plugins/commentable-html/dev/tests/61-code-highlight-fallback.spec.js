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

  test("an unbaked language-html and language-xml block is highlighted on load (markup and xml families) (CMH-HL-01)", async ({ page }) => {
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

  test("an unbaked language-sql block colors its own keywords, not the shared set's (CMH-HL-03)", async ({ page }) => {
    // Regression (#706): the sql family had dedicated comment/string patterns but shared the broad
    // multi-language keyword set, which carries no SELECT/INSERT/JOIN/GROUP/ORDER - so an unbaked
    // block rendered with strings and comments colored and almost every keyword plain, while the
    // same block baked by highlight_code.py colored them.
    await open(page,
      "<h1>Query</h1>"
      + '<pre><code class="language-sql">SELECT id FROM orders'
      + " INNER JOIN customers ON customers.id = orders.cid"
      + " GROUP BY id ORDER BY id -- note</code></pre>",
      "cmh-hl-fallback-sql");

    const code = page.locator("#commentRoot pre code.language-sql");
    const kw = await code.locator("span.cmh-code-kw").allTextContents();
    for (const word of ["SELECT", "FROM", "INNER", "JOIN", "ON", "GROUP", "BY", "ORDER"]) {
      expect(kw, "SQL keyword " + word + " should be colored").toContain(word);
    }
    // Identifiers stay plain, and the comment still tokenizes.
    expect(kw).not.toContain("orders");
    expect(kw).not.toContain("customers");
    expect(await code.locator("span.cmh-code-com").allTextContents()).toEqual(["-- note"]);
  });

  test("an unbaked language-jsonc block is highlighted on load with keys, values and comments (CMH-HL-05)", async ({ page }) => {
    const src = '{ /* blk */\n  "name": "cmh", // note\n  "n": 3\n}';
    await open(page,
      "<h1>Config</h1>"
      + '<pre><code class="language-jsonc">' + src.replace(/</g, "&lt;") + "</code></pre>",
      "cmh-hl-fallback-jsonc");

    const code = page.locator("#commentRoot pre code.language-jsonc");
    // The property keys are their own token class, distinct from the string VALUE.
    const keys = code.locator("span.cmh-code-key");
    expect(await keys.allTextContents()).toEqual(['"name"', '"n"']);
    const strings = code.locator("span.cmh-code-str");
    expect(await strings.allTextContents()).toEqual(['"cmh"']);
    // Both JSONC comment forms are comments.
    expect(await code.locator("span.cmh-code-com").allTextContents()).toEqual(["/* blk */", "// note"]);
    // Highlighting never changes the block's text.
    expect(await code.textContent()).toBe(src);
  });

  test("a raw newline inside a JSON string produces no key span, matching the author-time tokenizer (CMH-HL-05)", async ({ page }) => {
    // A raw newline is illegal inside a JSON string. If the runtime scanned across it, it would claim
    // one multi-line key span where highlight_code.py emits two unterminated string tokens. The second
    // block pins the sibling shape: an UNTERMINATED string followed by a colon is a string, not a key,
    // because the author-time key pattern requires the closing quote.
    await open(page,
      "<h1>Broken</h1>"
      + '<pre><code class="language-json">{"a\nb": 1}</code></pre>'
      + '<pre><code class="language-jsonc">{"a\n: 1}</code></pre>'
      + '<pre><code class="language-json">{"a\\"\n: 1}</code></pre>',
      "cmh-hl-fallback-json-newline");

    const code = page.locator("#commentRoot pre code.language-json").first();
    await expect(code.locator("span.cmh-code-key")).toHaveCount(0);
    expect(await code.locator("span.cmh-code-str").allTextContents()).toEqual(['"a', '": 1}']);

    const truncated = page.locator("#commentRoot pre code.language-jsonc");
    await expect(truncated.locator("span.cmh-code-key")).toHaveCount(0);
    expect(await truncated.locator("span.cmh-code-str").allTextContents()).toEqual(['"a']);

    // The trailing quote of `"a\"` belongs to an escape, so the token is still unterminated and must
    // not become a key either.
    const escaped = page.locator("#commentRoot pre code.language-json").nth(1);
    await expect(escaped.locator("span.cmh-code-key")).toHaveCount(0);
  });

  test("the JSON key token is tinted apart from a string value in light, dark and print (CMH-HL-05)", async ({ page }) => {
    // CMH-HL-05 promises the key token is VISIBLY distinct, not just classified apart, in every mode
    // the layer CSS covers. Token classification alone would stay green while the CSS regressed.
    await open(page,
      "<h1>Config</h1>"
      + '<pre><code class="language-json">{"name": "cmh"}</code></pre>',
      "cmh-hl-key-color");

    const read = () => page.evaluate(() => ({
      key: getComputedStyle(document.querySelector("#commentRoot .cmh-code-key")).color,
      str: getComputedStyle(document.querySelector("#commentRoot .cmh-code-str")).color,
    }));

    const light = await read();
    expect(light.key, "the key token is tinted apart from a string value (light)").not.toBe(light.str);

    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
    const dark = await read();
    expect(dark.key, "the key token is tinted apart from a string value (dark)").not.toBe(dark.str);
    expect(dark.key, "the dark key color is a real dark-theme override").not.toBe(light.key);

    // A dark-theme reader keeps data-theme="dark" when printing, so the key must be re-lit for the
    // white paper background the way the other tinted tokens are.
    await page.emulateMedia({ media: "print" });
    const printed = await read();
    await page.emulateMedia({ media: null });
    expect(printed.key, "the key token is re-lit for print, not left as the dark pastel").toBe(light.key);
  });

  test("in a diff a key whose colon is on the next line stays a string (line-independent tokenizing) (CMH-HL-05)", async ({ page }) => {
    // The diff highlighter tokenizes each line on its own, so the "next non-whitespace character"
    // key rule cannot see a colon that sits on the following line. CMH-HL-05 narrows the contract to
    // this; the test pins the limitation so it cannot change silently.
    await open(page,
      "<h1>Diff</h1>"
      + '<pre class="cmh-diff" data-diff-lang="json" data-diff-label="a.json">'
      + '@@ -1 +1 @@\n-old\n+  "name"\n+  : "cmh"</pre>',
      "cmh-hl-key-diff");

    const view = page.locator(".cmh-diff-view");
    await expect(view.locator("span.cmh-code-key")).toHaveCount(0);
    expect((await view.locator("span.cmh-code-str").allTextContents())).toContain('"name"');
  });

  test("an unbaked language-markdown block is highlighted on load (CMH-HL-08)", async ({ page }) => {
    const source = [
      "## Findings",
      "",
      "A *soft* and **hard** point, see [the spec](https://x.dev/a).",
      "",
      "1. first `step`",
      "- [ ] some_long_name stays plain",
      "",
      "```js",
      "const a = 1;",
      "```",
    ].join("\n");
    await open(page, "<h1>Markdown</h1>" + '<pre><code class="language-markdown">' + source + "</code></pre>",
      "cmh-hl-fallback-markdown");

    const md = page.locator("#commentRoot pre code.language-markdown");
    const joined = async (cls) => (await md.locator("span.cmh-code-" + cls).allTextContents()).join("\u0000");
    // Headings and bold read as keywords; emphasis reads as a comment (the italic token class).
    expect(await joined("kw")).toContain("## Findings");
    expect(await joined("kw")).toContain("**hard**");
    expect(await joined("com")).toContain("*soft*");
    // Link text vs destination, the inline code span, the fenced body and its info string.
    expect(await joined("fn")).toContain("the spec");
    expect(await joined("str")).toContain("https://x.dev/a");
    expect(await joined("str")).toContain("`step`");
    expect(await joined("kw")).toContain("js");
    // The fenced body is tokenized in its own language (CMH-HL-08), so `const` reads as a keyword
    // rather than the whole line being one opaque string run.
    expect(await joined("kw")).toContain("const");
    expect(await joined("str")).not.toContain("const a = 1;");
    // An ordered-list marker colors its digits as a number.
    expect(await joined("num")).toContain("1");
    // An intraword underscore is not emphasis: the com class IS populated (asserted above), and no
    // comment token covers the underscored run.
    await expect(md.locator("span.cmh-code-com", { hasText: "_long_" })).toHaveCount(0);
    expect(await joined("com")).not.toContain("_long_");
    // Highlighting only adds structure: the block's text is untouched.
    expect(await md.textContent()).toBe(source);
  });

  test("a fenced block inside a markdown block is highlighted in its own language (CMH-HL-08)", async ({ page }) => {
    const source = [
      "Intro **bold** line.",
      "",
      "```python",
      'def area(r):  # note',
      '    return "hi"',
      "```",
      "",
      "```kusto",
      "StormEvents | take 5",
      "```",
    ].join("\n");
    await open(page, "<h1>Nested</h1>" + '<pre><code class="language-markdown">' + source + "</code></pre>",
      "cmh-hl-fallback-md-nested");

    const md = page.locator("#commentRoot pre code.language-markdown");
    const joined = async (cls) => (await md.locator("span.cmh-code-" + cls).allTextContents()).join("\u0000");
    // The python body is tokenized AS PYTHON, not as one opaque run.
    expect(await joined("kw")).toContain("def");
    expect(await joined("kw")).toContain("return");
    expect(await joined("com")).toContain("# note");
    expect(await joined("str")).toContain('"hi"');
    expect(await joined("str")).not.toContain('def area(r):  # note');
    // An info string the tokenizer does not know keeps the opaque body.
    expect(await joined("str")).toContain("StormEvents | take 5");
    // Surrounding markdown still reads as markdown, and the text is untouched.
    expect(await joined("kw")).toContain("**bold**");
    expect(await md.textContent()).toBe(source);
  });

  test("a nested fenced body is highlighted as a whole and markdown nesting is depth-bounded (CMH-HL-08)", async ({ page }) => {
    // Two runtime-only behaviors that a per-line tokenizer would get wrong: a construct spanning
    // body lines, and the recursion bound on markdown-inside-markdown.
    const deep = (levels) => {
      let code = "# deep heading";
      for (let i = 0; i < levels; i++) {
        const fence = "`".repeat(3 + i);
        code = fence + "markdown\n" + code + "\n" + fence;
      }
      return code;
    };
    const source = [
      "```js",
      "/* open",
      "still comment",
      "*/",
      "let a = 1;",
      "```",
      "",
      deep(3),   // at the cap: the innermost heading is still tokenized
      "",
      deep(4),   // past the cap: that body stays one opaque run
    ].join("\n");
    await open(page, "<h1>Deep</h1>" + '<pre><code class="language-markdown">' + source + "</code></pre>",
      "cmh-hl-fallback-md-deep");

    const md = page.locator("#commentRoot pre code.language-markdown");
    const texts = async (cls) => await md.locator("span.cmh-code-" + cls).allTextContents();
    // The block comment is ONE comment token spanning three lines, not three fragments.
    expect(await texts("com")).toContain("/* open\nstill comment\n*/");
    // The heading nested at the cap is tokenized; the one past the cap is inside an opaque run.
    const headings = (await texts("kw")).filter((t) => t === "# deep heading");
    expect(headings).toHaveLength(1);
    expect((await texts("str")).some((t) => t.includes("# deep heading"))).toBe(true);
    expect(await md.textContent()).toBe(source);
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
