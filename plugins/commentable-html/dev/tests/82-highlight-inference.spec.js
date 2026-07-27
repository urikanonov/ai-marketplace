import { test, expect } from "@playwright/test";
import { stageContent, fileUrl, ready } from "./helpers.js";

// CMH-HL-13: extension inference must be exercised for real, not just asserted in the source. A
// source-only check would still pass if `.html` mapped to `python`, and every existing parity spec
// supplies `data-diff-lang` EXPLICITLY, so nothing executed inferDiffLang() from a label. The first
// three blocks deliberately omit data-diff-lang so the label is the only signal. CMH-HL-14 and
// CMH-HL-15 are pinned on the same live path.

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function inferred(label, added) {
  return '<pre class="cmh-diff" data-diff-label="' + label + '">'
    + "@@ -1 +1 @@\n-removed\n+" + esc(added) + "</pre>";
}

function explicit(lang, label, added) {
  return '<pre class="cmh-diff" data-diff-lang="' + lang + '" data-diff-label="' + label + '">'
    + "@@ -1 +1 @@\n-removed\n+" + esc(added) + "</pre>";
}

const CONTENT = [
  inferred("config.xml", "<item>a</item> <ROOT>b</ROOT>"),
  inferred("page.html", "<div>a</div> <SPAN>b</SPAN>"),
  inferred("notes.zzz", "just some plain prose"),
  explicit("python", "a.py", "x = True and None and true"),
  explicit("objectivec", "a.m", "@interface Foo @property int n; @end"),
  explicit("sql", "a.sql", "SELECT \"col name\" FROM t WHERE a = 'x';"),
].join("\n");

async function tokens(view, cls) {
  return view.locator(".cmh-code-" + cls).allTextContents();
}

test.describe("runtime highlight parity on the live path", () => {
  test.beforeEach(async ({ page }) => {
    const staged = stageContent(CONTENT, { key: "cmh-highlight-inference" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
  });

  test("a diff labelled .xml infers its language and stays case-SENSITIVE (CMH-HL-13)", async ({ page }) => {
    // xml is NOT in the author-time CASE_INSENSITIVE_LANGUAGES, so a lowercase tag name is a
    // keyword and an uppercase one is not.
    const kw = await tokens(page.locator(".cmh-diff-view").nth(0), "kw");
    expect(kw).toContain("item");
    expect(kw).not.toContain("ROOT");
  });

  test("a diff labelled .html infers its language and IS case-insensitive (CMH-HL-13)", async ({ page }) => {
    const kw = await tokens(page.locator(".cmh-diff-view").nth(1), "kw");
    expect(kw).toContain("div");
    expect(kw).toContain("SPAN");
  });

  test("an unmapped extension renders plain rather than mis-inferring (CMH-HL-13)", async ({ page }) => {
    expect(await tokens(page.locator(".cmh-diff-view").nth(2), "kw")).toHaveLength(0);
  });

  test("python capitalized literals color and a lowercase true does not (CMH-HL-14)", async ({ page }) => {
    const kw = await tokens(page.locator(".cmh-diff-view").nth(3), "kw");
    expect(kw).toContain("True");
    expect(kw).toContain("None");
    expect(kw).not.toContain("true");
  });

  test("objective-c at-keywords color (CMH-HL-14)", async ({ page }) => {
    // The exact per-language set holds `@interface`, not a bare `interface`, so the runtime
    // identifier token must accept a leading `@` exactly as the author-time one does - otherwise
    // the split would color LESS than the old approximate bucket did.
    const kw = await tokens(page.locator(".cmh-diff-view").nth(4), "kw");
    expect(kw).toContain("@interface");
    expect(kw).toContain("@property");
    expect(kw).toContain("@end");
  });

  test("a double-quoted SQL identifier is a string (CMH-HL-15)", async ({ page }) => {
    const str = (await tokens(page.locator(".cmh-diff-view").nth(5), "str")).join("");
    expect(str).toContain("\"col name\"");
    expect(str).toContain("'x'");
  });
});
