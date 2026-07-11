// UI polish: the overflow-menu portability badge matches the sidebar badge's semantics
// (data-doc-type, color, tooltip), and prose paragraphs get a readable measure cap.
import { test, expect } from "@playwright/test";
import { openInline, openKitchenSink, openToolbarMenu, stageContent, fileUrl, ready, installClipboardCapture } from "./helpers.js";

test("overflow-menu portability badge mirrors the sidebar badge", async ({ page }) => {
  await openInline(page);
  await openToolbarMenu(page);
  const sidebar = await page.evaluate(() => {
    const el = document.getElementById("cmTypeBadge");
    const cs = getComputedStyle(el);
    return { type: el.getAttribute("data-doc-type"), title: el.getAttribute("title") || el.getAttribute("data-cmh-tip"), border: cs.borderColor, text: el.textContent };
  });
  const overflow = await page.evaluate(() => {
    const el = document.getElementById("cmhModeBadge");
    const cs = getComputedStyle(el);
    return { type: el.getAttribute("data-doc-type"), title: el.getAttribute("title") || el.getAttribute("data-cmh-tip"), border: cs.borderColor, text: el.textContent };
  });
  expect(overflow.type).toBeTruthy();
  expect(overflow.type).toBe(sidebar.type);
  expect(overflow.text).toBe(sidebar.text);
  expect(overflow.title).toBe(sidebar.title);
  // Same data-doc-type drives the same themed color on both badges.
  expect(overflow.border).toBe(sidebar.border);
});

test("top-level prose paragraphs get a readable measure cap", async ({ page }) => {
  await openKitchenSink(page);
  const rootP = await page.evaluate(() => {
    const p = document.querySelector("#commentRoot > p");
    return p ? getComputedStyle(p).maxWidth : null;
  });
  expect(rootP).toBeTruthy();
  expect(rootP).not.toBe("none");
  expect(rootP).toMatch(/px$/);
  // Tables keep full width (no cap).
  const tableMax = await page.evaluate(() => {
    const t = document.querySelector("#commentRoot table");
    return t ? getComputedStyle(t).maxWidth : "none";
  });
  expect(tableMax).toBe("none");
});

test("both portability badges flip together (color, background, border) on a layout change", async ({ page }) => {
  await installClipboardCapture(page);
  const content = '<h1>B</h1><div class="cm-skip" data-cm-widget="t">'
    + '<div data-cm-slot="Now" id="n"><div data-cm-part="a" data-cm-part-label="A">A</div></div>'
    + '<div data-cm-slot="L" id="l"></div></div>';
  const { html } = stageContent(content, { key: "cmh-parity-flip" });
  await page.goto(fileUrl(html));
  await ready(page);
  const read = () => page.evaluate(() => {
    const a = document.getElementById("cmTypeBadge"), b = document.getElementById("cmhModeBadge");
    const csa = getComputedStyle(a), csb = getComputedStyle(b);
    return {
      sType: a.getAttribute("data-doc-type"), oType: b.getAttribute("data-doc-type"),
      sBorder: csa.borderColor, oBorder: csb.borderColor,
      sColor: csa.color, oColor: csb.color,
      sBg: csa.backgroundColor, oBg: csb.backgroundColor,
    };
  });
  let s = await read();
  expect(s.sType).toBe("Portable");
  expect(s.oType).toBe("Portable");
  expect(s.oBorder).toBe(s.sBorder);
  expect(s.oColor).toBe(s.sColor);
  expect(s.oBg).toBe(s.sBg);
  // Trigger a layout change so both flip to Not portable.
  await page.evaluate(() => document.getElementById("l").appendChild(document.querySelector('[data-cm-part="a"]')));
  await page.waitForTimeout(80);
  s = await read();
  expect(s.sType).toBe("Not portable");
  expect(s.oType).toBe("Not portable");
  expect(s.oBorder).toBe(s.sBorder);
  expect(s.oColor).toBe(s.sColor);
  expect(s.oBg).toBe(s.sBg);
});
