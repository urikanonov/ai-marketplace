import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  DEV,
  INLINE,
  addTextComment,
  fileUrl,
  installClipboardCapture,
  openComposerFor,
  ready,
} from "./helpers.js";

const REPO_ROOT = path.resolve(DEV, "..", "..", "..");

function makeTmpDir(prefix) {
  const root = path.join(REPO_ROOT, "tmp");
  fs.mkdirSync(root, { recursive: true });
  return fs.mkdtempSync(path.join(root, prefix));
}

function stagePrintContent(contentHtml, { key, source = "print.html" }) {
  const dir = makeTmpDir("cmh_print_");
  let html = fs.readFileSync(INLINE, "utf8");
  const contentRe = /(<!-- BEGIN: commentable-html - CONTENT[^>]*-->)[\s\S]*?(<!-- END: commentable-html - CONTENT -->)/;
  html = html.replace(contentRe, (_m, a, b) => a + "\n" + contentHtml + "\n" + b);
  html = html.replace('data-comment-key="commentable-html-demo"', 'data-comment-key="' + key + '"');
  html = html.replace('data-doc-source="PORTABLE.html"', 'data-doc-source="' + source + '"');
  const file = path.join(dir, source);
  fs.writeFileSync(file, html);
  return { dir, html: file };
}

function stagePrintDeck(slidesHtml, { key, source = "deck-print.html" }) {
  const style =
    "<style>.deck-viewport{position:fixed;inset:0;overflow:hidden;}"
    + ".deck-stage{position:absolute;left:0;top:0;width:1920px;height:1080px;transform-origin:0 0;overflow:hidden;}"
    + ".slide{position:absolute;inset:0;width:1920px;height:1080px;overflow:hidden;visibility:hidden;opacity:0;pointer-events:none;}"
    + ".slide.active,.slide.visible{visibility:visible;opacity:1;pointer-events:auto;}</style>";
  const staged = stagePrintContent(style + '<div class="deck-viewport"><div class="deck-stage">' + slidesHtml + "</div></div>", {
    key,
    source,
  });
  fs.writeFileSync(staged.html, fs.readFileSync(staged.html, "utf8")
    .replace('data-comment-key="' + key + '"', 'data-comment-key="' + key + '" data-cmh-mode="deck"'));
  return staged;
}

test("CMH-PRINT-01: flat print hides runtime chrome, expands content, and materializes comments", async ({ page }) => {
  const content = `
    <header class="cmh-lede"><h1>Print contract</h1><p>Flat documents should print as content.</p></header>
    <section id="fold">
      <h2>Collapsed section</h2>
      <p id="target">Printable target text for the review comment appendix.</p>
      <pre><code>long code line that should wrap instead of clipping in print output</code></pre>
      <button type="button" class="cm-code-copy cm-skip">Copy</button>
    </section>`;
  const staged = stagePrintContent(content, { key: "cmh-print-flat", source: "print-flat.html" });
  expect(fs.readFileSync(staged.html, "utf8")).toContain("cmh-print-noscript");

  await installClipboardCapture(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await addTextComment(page, "#target", "This note belongs in the printed appendix.");
  const composer = await openComposerFor(page, "#target");
  await expect(composer).toBeVisible();
  await page.locator("#btnCloseSidebar").click();
  await expect(page.locator(".cm-toolbar")).toBeVisible();
  await page.locator("#fold .cmh-sec-caret").evaluate((button) => button.click());
  await expect(page.locator("#target")).toBeHidden();

  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));

  await expect(page.locator(".cm-toolbar")).toBeHidden();
  await expect(page.locator("#sidebar")).toBeHidden();
  await expect(page.locator(".cm-composer")).toBeHidden();
  await expect(page.locator("#hlBubble")).toBeHidden();
  expect(await page.locator(".cm-code-copy").evaluateAll((buttons) =>
    buttons.every((button) => getComputedStyle(button).display === "none"))).toBe(true);
  await expect(page.locator("#fold .cmh-sec-caret")).toBeHidden();
  await expect(page.locator("#target")).toBeVisible();

  const appendix = page.locator("#cmhPrintComments");
  await expect(appendix).toBeVisible();
  await expect(appendix).toContainText("Review comments");
  await expect(appendix).toContainText("target text for the review comment appendix");
  await expect(appendix).toContainText("This note belongs in the printed appendix.");
  expect(await appendix.evaluate((el) => ({
    insideRoot: el.parentElement && el.parentElement.id,
    skip: el.classList.contains("cm-skip"),
  }))).toEqual({ insideRoot: "commentRoot", skip: false });

  const printStyle = await page.locator("#fold").evaluate((section) => {
    const style = getComputedStyle(section);
    return { overflow: style.overflow, boxShadow: style.boxShadow };
  });
  expect(printStyle.overflow).toBe("visible");
  expect(printStyle.boxShadow).toBe("none");
});

test("CMH-PRINT-01: deck print keeps one slide per page", async ({ page }) => {
  const slides =
    '<section class="slide active" data-slide-id="slide-print-1"><h2>One</h2><p>First slide.</p></section>'
    + '<section class="slide" data-slide-id="slide-print-2"><h2>Two</h2><p>Second slide.</p></section>'
    + '<section class="slide" data-slide-id="slide-print-3"><h2>Three</h2><p>Third slide.</p></section>';
  const staged = stagePrintDeck(slides, { key: "cmh-print-deck" });

  await installClipboardCapture(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await page.emulateMedia({ media: "print" });

  await expect(page.locator(".cmh-deck-nav")).toBeHidden();
  await expect(page.locator(".cmh-deck-mode-ctl")).toBeHidden();

  const slidesInfo = await page.locator(".slide").evaluateAll((els) => els.map((slide) => {
    const style = getComputedStyle(slide);
    return {
      visibility: style.visibility,
      opacity: style.opacity,
      overflow: style.overflow,
      breakAfter: style.breakAfter,
      pageBreakAfter: style.pageBreakAfter,
      position: style.position,
    };
  }));
  expect(slidesInfo).toHaveLength(3);
  for (const info of slidesInfo) {
    expect(info.visibility).toBe("visible");
    expect(info.opacity).toBe("1");
    expect(info.overflow).toBe("visible");
    expect(info.position).not.toBe("fixed");
  }
  for (const info of slidesInfo.slice(0, -1)) {
    expect(info.breakAfter === "page" || info.pageBreakAfter === "always").toBe(true);
  }
});
