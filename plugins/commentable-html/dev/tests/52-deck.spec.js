import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import {
  fileUrl,
  ready,
  stageDeck,
  stageContent,
  addTextComment,
  openComposerFor,
  installClipboardCapture,
  copiedBundle,
  startStaticServer,
  readDownload,
  routeMermaidLocal,
  openDeckModeMenu,
  enterCommentMode,
  leaveCommentMode,
  selectText,
  storedComments,
  PYTHON,
  SKILL,
  clickSidebarExport,
} from "./helpers.js";

// Three slides with distinct, stable ids and commentable text (CMH-DECK-05).
const SLIDES =
  '<section class="slide active" data-slide-id="slide-00000001"><h2>One</h2><p>Alpha slide one content</p></section>' +
  '<section class="slide" data-slide-id="slide-00000002"><h2>Two</h2><p>Beta slide two content</p></section>' +
  '<section class="slide" data-slide-id="slide-00000003"><h2>Three</h2><p>Gamma slide three content here</p></section>';

async function openDeck(page, hash = "", key = "cmh-deck-test") {
  await installClipboardCapture(page);
  const { html } = stageDeck(SLIDES, { key });
  await page.goto(fileUrl(html) + hash);
  await ready(page);
}

const activeId = (page) => page.evaluate(() => window.__cmhDeck.activeSlideId());

// Click squarely ON an element's rendered text glyphs (not the element-box center, which for a
// short left-aligned line is empty space to the right of the text - which now correctly advances).
async function clickOnText(page, selector) {
  const pt = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
      acceptNode(n) { return (n.nodeValue && n.nodeValue.trim()) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT; }
    });
    const tn = walker.nextNode();
    const range = document.createRange();
    range.selectNodeContents(tn);
    const r = range.getClientRects()[0];
    return { x: r.left + Math.min(10, r.width / 2), y: r.top + r.height / 2 };
  }, selector);
  await page.mouse.click(pt.x, pt.y);
}

function parseRgb(value) {
  const match = String(value || "").match(/rgba?\(([^)]+)\)/);
  if (!match) throw new Error("unsupported color: " + value);
  const parts = match[1].split(",").map((part) => Number(part.trim()));
  return { r: parts[0], g: parts[1], b: parts[2] };
}

function luminance(color) {
  const channel = (value) => {
    const s = value / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
}

test.describe("deck runtime profile (CMH-DECK-05)", () => {
  test("CMH-DECK-05: exposes the controller and starts on the first slide", async ({ page }) => {
    await openDeck(page);
    expect(await page.evaluate(() => typeof window.__cmhDeck)).toBe("object");
    expect(await page.evaluate(() => window.__cmhDeck.slideCount())).toBe(3);
    expect(await activeId(page)).toBe("slide-00000001");
    expect(await page.locator(".slide.active").count()).toBe(1);
    // the fixed stage is scaled to exactly min(vw/1920, vh/1080)
    const info = await page.evaluate(() => {
      const host = document.querySelector(".deck-viewport") || document.documentElement;
      return { t: document.querySelector(".deck-stage").style.transform, vw: host.clientWidth, vh: host.clientHeight };
    });
    const expected = Math.min(info.vw / 1920, info.vh / 1080);
    const got = parseFloat(info.t.match(/scale\(([-0-9.eE]+)\)/)[1]);
    expect(got).toBeCloseTo(expected, 5);
  });

  test("CMH-DECK-05d: keyboard, id, and prev/next navigation; doc-mode chrome suppressed", async ({ page }) => {
    await openDeck(page);
    await page.evaluate(() => {
      window.__evts = [];
      document.addEventListener("cmh:slidechange", (e) => window.__evts.push(e.detail));
    });
    // ArrowRight / Space / PageDown advance; ArrowLeft / PageUp / Backspace go back; Home / End jump to ends.
    await page.keyboard.press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000002");
    await expect(page.locator(".cmh-deck-count")).toHaveText("2 / 3");
    await page.keyboard.press(" ");
    expect(await activeId(page)).toBe("slide-00000003");
    await page.keyboard.press("PageUp");
    expect(await activeId(page)).toBe("slide-00000002");
    await page.keyboard.press("PageDown");
    expect(await activeId(page)).toBe("slide-00000003");
    await page.keyboard.press("Backspace");
    expect(await activeId(page)).toBe("slide-00000002");
    await page.keyboard.press("Home");
    expect(await activeId(page)).toBe("slide-00000001");
    // Backspace on the first slide is a no-op, but the deck still suppresses the browser's
    // legacy "history back" default so a viewer is never navigated away from the deck.
    const backspacePrevented = await page.evaluate(() => {
      const ev = new KeyboardEvent("keydown", { key: "Backspace", bubbles: true, cancelable: true });
      document.dispatchEvent(ev);
      return ev.defaultPrevented;
    });
    expect(backspacePrevented).toBe(true);
    expect(await activeId(page)).toBe("slide-00000001");
    await page.keyboard.press("End");
    expect(await activeId(page)).toBe("slide-00000003");
    await expect(page.locator(".cmh-deck-count")).toHaveText("3 / 3");
    // exactly one slide carries BOTH .active and .visible
    expect(await page.locator(".slide.active.visible").count()).toBe(1);
    // cmh:slidechange fired with { slideId, index }
    const evts = await page.evaluate(() => window.__evts);
    expect(evts.length).toBeGreaterThan(0);
    expect(evts[evts.length - 1]).toMatchObject({ slideId: "slide-00000003", index: 2 });

    // id + prev/next button navigation (aria-label contains the visible text: Prev/Next, WCAG 2.5.3)
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-00000001"));
    expect(await activeId(page)).toBe("slide-00000001");
    await page.locator(".cmh-deck-nav button[aria-label='Next slide']").click();
    expect(await activeId(page)).toBe("slide-00000002");
    await page.locator(".cmh-deck-nav button[aria-label='Prev slide']").click();
    expect(await activeId(page)).toBe("slide-00000001");
    // boundary: Prev disabled on the first slide, Next disabled on the last
    await expect(page.locator(".cmh-deck-nav button[aria-label='Prev slide']")).toBeDisabled();
    await page.evaluate(() => window.__cmhDeck.showSlide(2));
    await expect(page.locator(".cmh-deck-nav button[aria-label='Next slide']")).toBeDisabled();
    // out-of-range / wrong-type navigation is a no-op returning false, leaving the active slide put
    // and dispatching NO cmh:slidechange event.
    const evtsBeforeInvalid = await page.evaluate(() => window.__evts.length);
    expect(await page.evaluate(() => window.__cmhDeck.showSlide(99))).toBe(false);
    expect(await page.evaluate(() => window.__cmhDeck.showSlide(-1))).toBe(false);
    expect(await page.evaluate(() => window.__cmhDeck.showSlide("2"))).toBe(false);
    expect(await page.evaluate(() => window.__cmhDeck.showSlideById("nope"))).toBe(false);
    expect(await page.evaluate(() => window.__cmhDeck.showSlideById(""))).toBe(false);
    expect(await activeId(page)).toBe("slide-00000003");
    expect(await page.evaluate(() => window.__evts.length)).toBe(evtsBeforeInvalid);
    // heading anchors / collapsible carets / side TOC / footer / scroll progress are not installed
    expect(await page.locator("#cmFooter").count()).toBe(0);
    expect(await page.locator("#cmScrollProgress").count()).toBe(0);
    expect(await page.locator(".cm-toc-menu, #cmSideToc").count()).toBe(0);
  });

  test("CMH-DECK-17: deck URL hash restores and tracks slides without history spam", async ({ page }) => {
    await openDeck(page, "#slide-00000002");
    expect(await activeId(page)).toBe("slide-00000002");
    await expect(page.locator(".cmh-deck-count")).toHaveText("2 / 3");
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("#slide-00000002");

    const historyLength = await page.evaluate(() => history.length);
    await page.locator(".cmh-deck-nav button[aria-label='Next slide']").click();
    expect(await activeId(page)).toBe("slide-00000003");
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("#slide-00000003");
    expect(await page.evaluate(() => history.length)).toBe(historyLength);

    await page.evaluate(() => { location.hash = "#slide-00000001"; });
    await expect.poll(() => activeId(page)).toBe("slide-00000001");
    await expect(page.locator(".cmh-deck-count")).toHaveText("1 / 3");
  });

  test("CMH-DECK-20: edge hover arrows reveal, click-navigate, and Enter/Space advance only from the stage", async ({ page }) => {
    await openDeck(page);
    const viewport = page.locator(".deck-viewport");
    const prevEdge = page.locator(".cmh-deck-edge-nav-prev");
    const nextEdge = page.locator(".cmh-deck-edge-nav-next");

    await expect(prevEdge).toBeHidden();
    await expect(nextEdge).toBeHidden();

    const box = await viewport.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await expect(nextEdge).toBeHidden();

    await page.mouse.move(box.x + box.width - 8, box.y + box.height / 2);
    await expect(nextEdge).toBeVisible();
    await nextEdge.click();
    expect(await activeId(page)).toBe("slide-00000002");

    await page.mouse.move(box.x + 8, box.y + box.height / 2);
    await expect(prevEdge).toBeVisible();
    await prevEdge.click();
    expect(await activeId(page)).toBe("slide-00000001");

    await page.evaluate(() => {
      const probe = document.createElement("div");
      probe.id = "cmh-deck-enter-probe";
      probe.tabIndex = 0;
      document.body.appendChild(probe);
      probe.focus();
    });
    await page.keyboard.press("Enter");
    expect(await activeId(page)).toBe("slide-00000001");

    await viewport.focus();
    await page.keyboard.press("Enter");
    expect(await activeId(page)).toBe("slide-00000002");
    await viewport.focus();
    await page.keyboard.press("Space");
    expect(await activeId(page)).toBe("slide-00000003");

    const composer = await openComposerFor(page, ".slide.active p");
    await composer.locator("textarea").press("Enter");
    await expect(composer).toBeVisible();
    expect(await activeId(page)).toBe("slide-00000003");
  });

  test("CMH-DECK-33: empty right-click offers slide and deck comments; a slide comment ties to and jumps to its slide", async ({ page }) => {
    await openDeck(page);
    // An empty right-click on the active slide (closed mode) offers BOTH a slide-scoped comment
    // and a deck-wide comment; the deck relabels the document item to "Comment on deck".
    await page.evaluate(() => {
      const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 });
      document.querySelector(".slide.active").dispatchEvent(ev);
    });
    await expect(page.locator("#contextMenu")).toBeVisible();
    const slideItem = page.locator("#menuSlideComment");
    const deckItem = page.locator("#menuDocComment");
    await expect(slideItem).toBeVisible();
    await expect(slideItem).toHaveText("Comment on slide");
    await expect(deckItem).toBeVisible();
    await expect(deckItem).toHaveText("Comment on deck");

    // Creating the slide comment stores it against the active slide (id + title), no highlight.
    await slideItem.click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("note about slide one");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);

    const stored = await storedComments(page);
    expect(stored.length).toBe(1);
    expect(stored[0].anchorType).toBe("slide");
    expect(stored[0].slideId).toBe("slide-00000001");
    expect(stored[0].slideTitle).toBe("One");
    expect(await page.locator("mark.cm-hl").count()).toBe(0);

    // The sidebar card is a slide card, names the slide, and keeps a jump button that navigates.
    const card = page.locator(".cm-card[data-cid='" + stored[0].id + "']");
    await expect(card).toHaveClass(/cm-card-slide/);
    await expect(card).toContainText("One");
    const jump = card.locator('[data-act="jump"]');
    await expect(jump).toBeVisible();
    await page.evaluate(() => window.__cmhDeck.showSlide(2));
    expect(await activeId(page)).toBe("slide-00000003");
    await jump.click();
    expect(await activeId(page)).toBe("slide-00000001");

    // The deck-wide item still makes a document-scoped comment (relabelled, same behavior).
    await page.evaluate(() => {
      const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 });
      document.querySelector(".slide.active").dispatchEvent(ev);
    });
    await page.locator("#menuDocComment").click();
    const deckComposer = page.locator(".cm-composer").last();
    await deckComposer.locator("textarea").fill("note about the whole deck");
    await deckComposer.locator('[data-act="save"]').click();
    await expect(deckComposer).toHaveCount(0);
    const after = await storedComments(page);
    expect(after.some((c) => c.anchorType === "document")).toBe(true);
    const slideCid = stored[0].id;

    // The slide comment survives a reload (no offsets to re-anchor) and its card + jump restore.
    await page.reload();
    await ready(page);
    const reloaded = await storedComments(page);
    const rslide = reloaded.find((c) => c.id === slideCid);
    expect(rslide).toBeTruthy();
    expect(rslide.anchorType).toBe("slide");
    expect(rslide.slideId).toBe("slide-00000001");
    expect(rslide.slideIndex).toBe(0);
    await enterCommentMode(page);
    const rcard = page.locator(".cm-card[data-cid='" + slideCid + "']");
    await expect(rcard).toContainText("One");

    // Copy-all emits the slide comment as a "(slide)" bundle entry naming the slide.
    await page.locator("#btnCopyAll").click();
    const bundle = await copiedBundle(page);
    expect(bundle).toContain("(slide)");
    expect(bundle).toContain('Anchor: slide "One"');

    // Export Markdown names the slide comment in its review-comments appendix.
    const md = await page.evaluate(() => window.__cmhToMarkdown());
    expect(md).toContain('slide "One"');

    // Deleting the slide comment removes it cleanly.
    page.once("dialog", (d) => d.accept());
    await rcard.locator('[data-act="del"]').click();
    await expect(page.locator(".cm-card[data-cid='" + slideCid + "']")).toHaveCount(0);
    expect((await storedComments(page)).some((c) => c.id === slideCid)).toBe(false);

    // A FLAT (non-deck) document keeps the single "Comment on document" item, no slide item.
    const flat = stageContent('<h1>Flat</h1><p id="fp">Flat paragraph body</p>', { key: "cmh-flat-relabel" });
    await page.goto(fileUrl(flat.html));
    await ready(page);
    await page.evaluate(() => {
      const p = document.getElementById("fp");
      p.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 30, clientY: 30 }));
    });
    await expect(page.locator("#menuDocComment")).toBeVisible();
    await expect(page.locator("#menuDocComment")).toHaveText("Comment on document");
    await expect(page.locator("#menuSlideComment")).toBeHidden();
  });

  test("Arrow keys rove focus between the deck context-menu items (CMH-A11Y-09)", async ({ page }) => {
    await openDeck(page);
    // An empty right-click on the active slide shows two visible menuitems (slide + deck).
    await page.evaluate(() => {
      const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 });
      document.querySelector(".slide.active").dispatchEvent(ev);
    });
    await expect(page.locator("#contextMenu")).toBeVisible();
    // In a deck the empty right-click shows two items (deck + slide); menuComment is hidden, so the
    // first VISIBLE item takes focus on open.
    await expect(page.locator("#menuDocComment")).toBeFocused();
    // ArrowDown moves to the next visible item; a second wraps back to the first.
    await page.keyboard.press("ArrowDown");
    await expect(page.locator("#menuSlideComment")).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(page.locator("#menuDocComment")).toBeFocused();
    // ArrowUp roves backwards (wrapping to the last visible item).
    await page.keyboard.press("ArrowUp");
    await expect(page.locator("#menuSlideComment")).toBeFocused();
  });

  test("CMH-DECK-33: a slide comment caps a long title and falls back to the active slide without an id", async ({ page }) => {
    const longTitle = "T".repeat(200);
    const slides =
      '<section class="slide active"><h2>' + longTitle + '</h2><p>No id on this slide</p></section>'
      + '<section class="slide" data-slide-id="s2"><h2>Second</h2><p>Second body</p></section>';
    const { html } = stageDeck(slides, { key: "cmh-deck-slide-fallback" });
    await installClipboardCapture(page);
    await page.goto(fileUrl(html));
    await ready(page);

    await page.evaluate(() => {
      document.querySelector(".slide.active").dispatchEvent(
        new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 40, clientY: 40 }));
    });
    await page.locator("#menuSlideComment").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("comment on the id-less slide");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);

    const stored = await storedComments(page);
    const c = stored.find((x) => x.anchorType === "slide");
    expect(c).toBeTruthy();
    // Title capped to 120 chars; the id-less active slide is captured by index (0), not lost.
    expect(c.slideTitle.length).toBe(120);
    expect(c.slideId == null).toBe(true);
    expect(c.slideIndex).toBe(0);

    // The jump uses the slideIndex fallback (no id) to return to the owning slide.
    await page.evaluate(() => window.__cmhDeck.showSlideById("s2"));
    expect(await activeId(page)).toBe("s2");
    await page.locator(".cm-card[data-cid='" + c.id + "'] [data-act='jump']").click();
    expect(await page.evaluate(() => document.querySelector(".slide.active") === document.querySelectorAll(".slide")[0])).toBe(true);
  });

  test("CMH-DECK-31: a click on EMPTY slide space advances in both present and open modes; text and interactive targets never advance", async ({ page }) => {
    const slides =
      '<section class="slide active" data-slide-id="s1"><h2 id="cah">Title one</h2>'
      + '<p id="cap">Plain paragraph body text here</p>'
      + '<p id="cap2">More plain body to select</p>'
      + '<div id="cae" style="height:160px"></div>'
      + '<a id="cal" href="#nowhere">a real link</a>'
      + '<button id="cab" type="button">a button</button></section>'
      + '<section class="slide" data-slide-id="s2"><h2>Title two</h2><p id="cap3">Second body</p></section>'
      + '<section class="slide" data-slide-id="s3"><h2>Title three</h2><div id="cae3" style="height:160px"></div></section>';
    const { html } = stageDeck(slides, { key: "cmh-deck-click-advance" });
    await installClipboardCapture(page);
    await page.goto(fileUrl(html));
    await ready(page);

    // A click on EMPTY slide space (a spacer that holds no text) advances to the next slide - the
    // natural "click forward" a presenter expects.
    await page.locator("#cae").click();
    expect(await activeId(page)).toBe("s2");

    // A click whose POINT is over TEXT never advances (the reader may be selecting it to comment):
    // neither a paragraph nor a heading pages the deck.
    await page.evaluate(() => window.__cmhDeck.showSlide(0));
    await clickOnText(page, "#cap");
    expect(await activeId(page)).toBe("s1");
    await clickOnText(page, "#cah");
    expect(await activeId(page)).toBe("s1");

    // Interactive targets (link, button) do NOT advance.
    await page.locator("#cal").click();
    expect(await activeId(page)).toBe("s1");
    await page.locator("#cab").click();
    expect(await activeId(page)).toBe("s1");

    // A modified (Ctrl) click on empty space is never a "next slide" intent.
    await page.locator("#cae").click({ modifiers: ["Control"] });
    expect(await activeId(page)).toBe("s1");

    // A click that DISMISSES a standing text selection must not advance (the browser collapses the
    // selection on mousedown, so this guards the mousedown-snapshot path).
    await page.evaluate(() => {
      const r = document.createRange();
      r.selectNodeContents(document.getElementById("cap2"));
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    });
    await page.locator("#cae").click();
    expect(await activeId(page)).toBe("s1");

    // A click that DISMISSES the open comment context menu must not advance.
    await page.evaluate(() => {
      document.querySelector(".slide.active").dispatchEvent(
        new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 }));
    });
    await expect(page.locator("#contextMenu")).toBeVisible();
    await page.locator("#cae").click();
    expect(await activeId(page)).toBe("s1");

    // With the review panel OPEN, an empty-space click STILL advances (the reviewer can page
    // through by clicking empty space)...
    await page.evaluate(() => window.__cmhDeck.showSlide(0));
    await enterCommentMode(page);
    await page.locator("#cae").click();
    expect(await activeId(page)).toBe("s2");
    // ...but a click on text in open mode does not, so the text stays selectable to comment.
    await clickOnText(page, "#cap3");
    expect(await activeId(page)).toBe("s2");

    // The last slide is a no-op (no wrap-around) even for an empty-space click.
    await page.evaluate(() => window.__cmhDeck.showSlide(2));
    expect(await activeId(page)).toBe("s3");
    await page.locator("#cae3").click();
    expect(await activeId(page)).toBe("s3");
  });

  test("CMH-DECK-31: a slide or wrapper carrying loose text still advances on an empty-space click (point-based)", async ({ page }) => {
    const slides =
      '<section class="slide active" data-slide-id="s1">Loose kicker text on the slide'
      + '<div class="wrap">Wrapper loose text<div id="cae" style="height:200px"></div></div>'
      + '<p id="cap">A real paragraph of body text</p></section>'
      + '<section class="slide" data-slide-id="s2"><h2>Two</h2></section>';
    const { html } = stageDeck(slides, { key: "cmh-deck-loosetext" });
    await installClipboardCapture(page);
    await page.goto(fileUrl(html));
    await ready(page);
    // The slide AND a wrapper both carry loose direct text, but a click on the empty spacer (no text
    // under the point) still advances - the old element-ancestry heuristic wrongly suppressed this.
    await page.locator("#cae").click();
    expect(await activeId(page)).toBe("s2");
    // A click whose point IS over the paragraph text does not advance.
    await page.evaluate(() => window.__cmhDeck.showSlide(0));
    await clickOnText(page, "#cap");
    expect(await activeId(page)).toBe("s1");
  });

  test("CMH-DECK-31: a visible highlight hover bubble suppresses the empty-space advance", async ({ page }) => {
    const slides =
      '<section class="slide active" data-slide-id="s1"><p id="cap">Commentable paragraph text here to select</p>'
      + '<div id="cae" style="height:220px"></div></section>'
      + '<section class="slide" data-slide-id="s2"><h2>Two</h2></section>';
    const { html } = stageDeck(slides, { key: "cmh-deck-bubble" });
    await installClipboardCapture(page);
    await page.goto(fileUrl(html));
    await ready(page);
    // Leave a comment so the paragraph carries a saved highlight, then hover it to raise the bubble.
    await addTextComment(page, "#cap", "a note");
    expect(await activeId(page)).toBe("s1");
    await page.locator("mark.cm-hl").first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    // An empty-space click that dismisses the bubble must NOT also advance the deck.
    await page.locator("#cae").click();
    expect(await activeId(page)).toBe("s1");
  });

  test("CMH-DECK-34: the deck comment-scope menu stacks vertically with 'Comment on deck' above 'Comment on slide'", async ({ page }) => {
    await openDeck(page);
    // An empty right-click on the active slide offers both scope options.
    await page.evaluate(() => {
      document.querySelector(".slide.active").dispatchEvent(
        new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 }));
    });
    await expect(page.locator("#contextMenu")).toBeVisible();
    const deckItem = page.locator("#menuDocComment");
    const slideItem = page.locator("#menuSlideComment");
    await expect(deckItem).toBeVisible();
    await expect(slideItem).toBeVisible();
    await expect(deckItem).toHaveText("Comment on deck");
    await expect(slideItem).toHaveText("Comment on slide");
    // The menu lays its options out as a vertical column...
    await expect(page.locator("#contextMenu")).toHaveCSS("flex-direction", "column");
    // ...with the deck-wide option ABOVE the slide option (deck first), stacked not side by side.
    const dBox = await deckItem.boundingBox();
    const sBox = await slideItem.boundingBox();
    expect(dBox.y).toBeLessThan(sBox.y);
    expect(sBox.y).toBeGreaterThanOrEqual(dBox.y + dBox.height - 1);
  });

  test("CMH-DECK-32: edge arrows reveal across a wide hover band and are a comfortably large target", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await openDeck(page);
    const viewport = page.locator(".deck-viewport");
    const nextEdge = page.locator(".cmh-deck-edge-nav-next");
    const box = await viewport.boundingBox();

    // The center stays clear so the arrows never block slide content.
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await expect(nextEdge).toBeHidden();

    // The arrow reveals well before the very edge (a wide band, ~250px in from the right edge),
    // so it is easy to reach and click quickly.
    await page.mouse.move(box.x + box.width - 250, box.y + box.height / 2);
    await expect(nextEdge).toBeVisible();
    const edgeBox = await nextEdge.boundingBox();
    expect(edgeBox.width).toBeGreaterThanOrEqual(52);
    expect(edgeBox.height).toBeGreaterThanOrEqual(52);
    await nextEdge.click();
    expect(await activeId(page)).toBe("slide-00000002");
  });

  test("CMH-DECK-05d: typing in an editable field does not navigate; deck chrome is installed once", async ({ page }) => {
    await openDeck(page);
    // the isEditableTarget gate: a keypress inside a textarea must not move the deck
    await page.evaluate(() => {
      const ta = document.createElement("textarea");
      ta.id = "probe";
      document.body.appendChild(ta);
      ta.focus();
    });
    await page.locator("#probe").press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000001");
    // Backspace inside a text field deletes text (isEditableTarget gate) instead of navigating.
    await page.evaluate(() => { const ta = document.getElementById("probe"); ta.value = "ab"; ta.focus(); ta.setSelectionRange(2, 2); });
    await page.locator("#probe").press("Backspace");
    expect(await activeId(page)).toBe("slide-00000001");
    expect(await page.locator("#probe").inputValue()).toBe("a");
    // contenteditable is gated the same way
    await page.evaluate(() => {
      const ce = document.createElement("div");
      ce.id = "probe-ce"; ce.setAttribute("contenteditable", "true"); ce.textContent = "edit";
      document.body.appendChild(ce);
      ce.focus();
    });
    await page.locator("#probe-ce").press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000001");
    // the deck chrome exists exactly once (the setupDeck idempotency guard prevents duplicates)
    expect(await page.locator(".cmh-deck-mode-toggle").count()).toBe(1);
    expect(await page.locator(".cmh-deck-nav").count()).toBe(1);
  });

  test("CMH-DECK-06: overview title list opens, lists every slide, titles slides, and click-jumps", async ({ page }) => {
    await openDeck(page);
    const overviewButton = page.locator(".cmh-deck-nav").getByRole("button", { name: "Slide overview", exact: true });
    await expect(overviewButton).toHaveAttribute("aria-expanded", "false");

    await overviewButton.click();
    const overview = page.locator(".cmh-deck-overview");
    await expect(overview).toBeVisible();
    await expect(overviewButton).toHaveAttribute("aria-expanded", "true");

    const slides = overview.locator(".cmh-deck-overview-card");
    await expect(slides).toHaveCount(3);
    await expect(slides.nth(0).locator(".cmh-deck-overview-card-num")).toHaveText("1");
    await expect(slides.nth(0).locator(".cmh-deck-overview-card-label")).toHaveText("One");
    await expect(slides.nth(1).locator(".cmh-deck-overview-card-num")).toHaveText("2");
    await expect(slides.nth(1).locator(".cmh-deck-overview-card-label")).toHaveText("Two");
    await expect(slides.nth(1)).toHaveAttribute("title", "Two");
    await expect(overview.locator(".cmh-deck-overview-thumb, .cmh-deck-overview-scale")).toHaveCount(0);
    await slides.nth(1).hover();
    await expect(page.locator(".cm-tooltip")).toHaveText("Two");

    await slides.nth(2).click();
    await expect(overview).toBeHidden();
    expect(await activeId(page)).toBe("slide-00000003");
    await expect(page.locator(".cmh-deck-count")).toHaveText("3 / 3");
    await expect(overviewButton).toHaveAttribute("aria-expanded", "false");
  });

  test("CMH-DECK-06: overview keyboard shortcut opens, closes, and selects in closed and open modes", async ({ page }) => {
    await openDeck(page);
    const overview = page.locator(".cmh-deck-overview");
    await page.evaluate(() => {
      window.__overviewEvts = [];
      document.addEventListener("cmh:slidechange", (e) => window.__overviewEvts.push(e.detail));
    });

    await page.keyboard.press("o");
    await expect(overview).toBeVisible();
    expect(await page.evaluate(() => document.activeElement && document.activeElement.getAttribute("data-slide-id")))
      .toBe("slide-00000001");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect.poll(async () => page.evaluate(
      () => document.activeElement && document.activeElement.getAttribute("data-slide-id"),
    )).toBe("slide-00000003");
    await page.keyboard.press(" ");
    await expect(overview).toBeHidden({ timeout: 10000 });
    expect(await activeId(page)).toBe("slide-00000003");
    expect(await page.evaluate(() => window.__overviewEvts.length)).toBe(1);

    await page.keyboard.press("o");
    await expect(overview).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(overview).toBeHidden();

    await enterCommentMode(page);
    // Opening the panel moves focus into the cm-skip review panel, where deck shortcuts are
    // intentionally out of scope; move focus to the stage so the "o" shortcut applies.
    await page.evaluate(() => document.querySelector(".deck-viewport").focus());
    await page.keyboard.press("o");
    await expect(overview).toBeVisible();
    await page.keyboard.press("End");
    await expect.poll(async () => page.evaluate(
      () => document.activeElement && document.activeElement.getAttribute("data-slide-id"),
    )).toBe("slide-00000003");
    await page.keyboard.press(" ");
    await expect(overview).toBeHidden({ timeout: 10000 });
    expect(await activeId(page)).toBe("slide-00000003");
  });

  test("CMH-DECK-06: overview title list has no thumbnail clones or nested focusables", async ({ page }) => {
    const slides =
      '<section class="slide active" data-slide-id="slide-link-1"><h2>Links</h2>'
      + '<p><a href="#inside">Focusable link</a> in the source slide.</p>'
      + '<mark class="cm-hl" data-cid="cabc1234"><strong>Nested highlight</strong></mark></section>'
      + '<section class="slide" data-slide-id="slide-link-2"><h2>Next</h2><p>Second slide</p></section>';
    await installClipboardCapture(page);
    const { html } = stageDeck(slides, { key: "cmh-deck-tab-order" });
    await page.goto(fileUrl(html));
    await ready(page);

    await page.keyboard.press("o");
    const overview = page.locator(".cmh-deck-overview");
    await expect(overview).toBeVisible();
    await expect(overview.locator(".cmh-deck-overview-thumb, .cmh-deck-overview-scale")).toHaveCount(0);
    await expect(overview.locator(".cmh-deck-overview-card").first().locator(".cmh-deck-overview-card-label")).toHaveText("Links");
    await expect(overview.locator(".cmh-deck-overview-card a[href], .cmh-deck-overview-card button")).toHaveCount(0);

    const focused = [];
    for (let i = 0; i < 4; i++) {
      focused.push(await page.evaluate(() => {
        const el = document.activeElement;
        return {
          inCard: !!(el && el.closest && el.closest(".cmh-deck-overview-card")),
          label: el && (el.getAttribute("aria-label") || el.textContent || "").trim(),
        };
      }));
      await page.keyboard.press("Tab");
    }
    expect(focused.every((entry) => entry.inCard)).toBe(true);
    expect(focused.map((entry) => entry.label)).toEqual([
      "Slide 1: Links",
      "Slide 2: Next",
      "Slide 1: Links",
      "Slide 2: Next",
    ]);
  });

  test("CMH-DECK-30: the overview has a search filter that narrows the slide list by title", async ({ page }) => {
    await openDeck(page);
    const overview = page.locator(".cmh-deck-overview");
    const overviewButton = page.locator(".cmh-deck-nav").getByRole("button", { name: "Slide overview", exact: true });
    await overviewButton.click();
    await expect(overview).toBeVisible();

    const search = overview.locator(".cmh-deck-overview-search");
    await expect(search).toBeVisible();
    const visibleCards = overview.locator(".cmh-deck-overview-card:visible");
    await expect(visibleCards).toHaveCount(3);

    // Filtering by a title substring hides the non-matching slides.
    await search.fill("two");
    await expect(visibleCards).toHaveCount(1);
    await expect(visibleCards.locator(".cmh-deck-overview-card-label")).toHaveText("Two");
    await expect(overview.locator(".cmh-deck-overview-count")).toHaveText("1 of 3");

    // Clearing the filter restores every slide.
    await search.fill("");
    await expect(visibleCards).toHaveCount(3);

    // A filtered card still jumps to its slide and closes the overview.
    await search.fill("three");
    await expect(visibleCards).toHaveCount(1);
    await visibleCards.click();
    await expect(overview).toBeHidden();
    expect(await activeId(page)).toBe("slide-00000003");

    // Reopening resets the filter so every slide is listed again.
    await overviewButton.click();
    await expect(overview).toBeVisible();
    await expect(search).toHaveValue("");
    await expect(visibleCards).toHaveCount(3);
  });

  test("CMH-DECK-30: filter keyboard nav stays on visible cards; search stays reachable and does not eat the o shortcut", async ({ page }) => {
    await openDeck(page);
    const overview = page.locator(".cmh-deck-overview");
    const overviewButton = page.locator(".cmh-deck-nav").getByRole("button", { name: "Slide overview", exact: true });
    await overviewButton.click();
    await expect(overview).toBeVisible();
    const search = overview.locator(".cmh-deck-overview-search");
    const visibleCards = overview.locator(".cmh-deck-overview-card:visible");
    const activeSlideId = () => page.evaluate(() =>
      document.activeElement && document.activeElement.getAttribute("data-slide-id"));

    // A zero-match filter empties the grid and the count reads "0 of 3".
    await search.fill("zzz");
    await expect(visibleCards).toHaveCount(0);
    await expect(overview.locator(".cmh-deck-overview-count")).toHaveText("0 of 3");

    // Filter to the two slides containing "t" (Two, Three); arrow nav skips the hidden "One".
    await search.fill("t");
    await expect(visibleCards).toHaveCount(2);
    await search.press("ArrowDown");
    expect(await activeSlideId()).toBe("slide-00000002");
    await page.keyboard.press("ArrowDown");
    expect(await activeSlideId()).toBe("slide-00000003");
    await page.keyboard.press("Home");
    expect(await activeSlideId()).toBe("slide-00000002");

    // Shift+Tab off the top of the list returns focus to the filter box (keyboard reachable).
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() =>
      document.activeElement === document.querySelector(".cmh-deck-overview-search"))).toBe(true);

    // Typing "o" in the filter box narrows, it does NOT close the overview.
    await search.fill("");
    await search.press("o");
    await expect(overview).toBeVisible();
    await expect(search).toHaveValue("o");

    // But pressing "o" while a card has focus still closes the overview.
    await search.fill("");
    await search.press("ArrowDown");
    await page.keyboard.press("o");
    await expect(overview).toBeHidden();
  });

  test("CMH-CORE-16: the inline dialog opens and Escape-closes inside a deck", async ({ page }) => {
    await openDeck(page);
    // Add a comment on the active slide (auto-opens the panel), then return to closed mode.
    await addTextComment(page, ".slide.active p", "deck popover note");
    await leaveCommentMode(page);
    const cid = await page.locator("mark.cm-hl").first().getAttribute("data-cid");

    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();
    await expect(pop).toContainText("deck popover note");

    // The dialog is always dismissible in a deck (no stuck state): Escape closes it.
    await page.keyboard.press("Escape");
    await expect(pop).toBeHidden();
  });

  test("CMH-DECK-05: the stage refits on viewport resize and open mode narrows it", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openDeck(page);
    const scaleOf = () => page.evaluate(() => {
      const m = document.querySelector(".deck-stage").style.transform.match(/scale\(([-0-9.eE]+)\)/);
      return m ? parseFloat(m[1]) : null;
    });
    const vp = () => page.evaluate(() => {
      const h = document.querySelector(".deck-viewport") || document.documentElement;
      return { w: h.clientWidth, h: h.clientHeight };
    });
    const fits = async () => {
      const s = await scaleOf(); const { w, h } = await vp();
      return Math.abs(s - Math.min(w / 1920, h / 1080)) < 1e-3;
    };
    expect(await fits()).toBe(true);
    // a resize is picked up by the ResizeObserver and refits the stage
    await page.setViewportSize({ width: 1000, height: 700 });
    await expect.poll(fits).toBe(true);
    // open mode narrows the viewport (400px sidebar inset at >=900px), and the stage refits smaller
    await page.setViewportSize({ width: 1400, height: 900 });
    await expect.poll(fits).toBe(true);
    const wideW = (await vp()).w;
    await enterCommentMode(page);
    await expect.poll(async () => (await vp()).w < wideW).toBe(true);
    await expect.poll(fits).toBe(true);
  });

  test("CMH-DECK-05: slides fit the fixed 1080px stage and vertical overflow is detectable as clipping", async ({ page }) => {
    await openDeck(page);
    // a well-formed slide does not overflow the clipped 1080px stage vertically
    const allFit = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".slide")).every((s) => s.scrollHeight - s.clientHeight <= 4));
    expect(allFit).toBe(true);
    // content taller than the stage overflows a CLIPPED box - the audit's clip-y signal and a fit
    // gate both catch this (the dominant fixed-stage deck defect: silently cut-off content).
    const clip = await page.evaluate(() => {
      const s = document.querySelector(".slide.active");
      const filler = document.createElement("div");
      filler.style.height = "3000px";
      s.appendChild(filler);
      const cs = getComputedStyle(s);
      return { clipped: cs.overflowY === "hidden" || cs.overflowY === "clip", over: s.scrollHeight - s.clientHeight };
    });
    expect(clip.clipped).toBe(true);
    expect(clip.over).toBeGreaterThan(4);
  });

  test("CMH-DECK-05d: cmh:slidechange fires only for a changed active slide", async ({ page }) => {
    // register the listener BEFORE the deck initializes, so a setup-time dispatch would be caught
    await page.addInitScript(() => {
      window.__evtCount = 0;
      document.addEventListener("cmh:slidechange", () => { window.__evtCount++; });
    });
    await openDeck(page);
    expect(await page.evaluate(() => window.__evtCount)).toBe(0);            // no event at setup
    await page.evaluate(() => window.__cmhDeck.showSlide(0));                // already on slide 0
    await page.evaluate(() => window.__cmhDeck.showSlideById(window.__cmhDeck.activeSlideId()));
    expect(await page.evaluate(() => window.__evtCount)).toBe(0);            // no event on a no-op
    await page.evaluate(() => window.__cmhDeck.showSlide(1));                // a real move
    expect(await page.evaluate(() => window.__evtCount)).toBe(1);
  });

  test("CMH-DECK-05a: on a narrow screen the deck controls yield to the open sidebar", async ({ page }) => {
    await page.setViewportSize({ width: 480, height: 800 });
    await openDeck(page);
    await expect(page.locator(".cmh-deck-mode-ctl")).toBeVisible();
    // open mode opens the near-full-width sidebar overlay; the controls hide so they don't cover it
    await enterCommentMode(page);
    await expect(page.locator("#sidebar")).toBeVisible();
    await expect(page.locator(".cmh-deck-mode-ctl")).toBeHidden();
    await expect(page.locator(".cmh-deck-nav")).toBeHidden();
    // hiding the sidebar brings the controls back, so the menu stays reachable
    await leaveCommentMode(page);
    await expect(page.locator(".cmh-deck-mode-ctl")).toBeVisible();
  });

  test("CMH-DECK-05a: default closed mode allows the doc-comment menu; off mode suppresses it", async ({ page }) => {
    await openDeck(page);
    // default closed mode: comments are enabled even with the panel closed.
    const preventedInClosed = await page.evaluate(() => {
      const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 });
      document.querySelector(".slide.active").dispatchEvent(ev);
      return ev.defaultPrevented;
    });
    expect(preventedInClosed).toBe(true);
    await expect(page.locator("#contextMenu")).toBeVisible();
    await expect(page.locator("#menuDocComment")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator("#contextMenu")).toBeHidden();

    const menu = await openDeckModeMenu(page);
    await menu.locator(".cmh-deck-mode-off-item").click();
    expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("off");
    const preventedInOff = await page.evaluate(() => {
      const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 });
      document.querySelector(".slide.active").dispatchEvent(ev);
      return ev.defaultPrevented;
    });
    expect(preventedInOff).toBe(false);
    await expect(page.locator("#contextMenu")).toBeHidden();
    await expect(page.locator("#menuDocComment")).toBeHidden();
  });

  test("CMH-DECK-11: comment-options menu is a 3-state radio group controlling the review panel", async ({ page }) => {
    await openDeck(page);
    const toggle = page.getByRole("button", { name: "Comment options" });
    await expect(toggle).toHaveAttribute("title", "Comment options");
    await expect(toggle).toHaveAttribute("aria-haspopup", "menu");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle.locator("svg.cm-brand-icon")).toHaveCount(1);
    await expect(toggle.locator("svg.cm-brand-icon")).toHaveAttribute("aria-hidden", "true");
    await expect(toggle.locator(".cmh-deck-mode-caret")).toHaveCount(1);

    const menu = await openDeckModeMenu(page);
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    // Three mutually-exclusive radio options; exactly one is checked (the default "closed").
    const off = menu.locator('.cmh-deck-mode-radio[data-deck-mode="off"]');
    const closed = menu.locator('.cmh-deck-mode-radio[data-deck-mode="closed"]');
    const open = menu.locator('.cmh-deck-mode-radio[data-deck-mode="open"]');
    await expect(menu.locator(".cmh-deck-mode-radio")).toHaveCount(3);
    await expect(off).toHaveAttribute("role", "menuitemradio");
    await expect(closed).toHaveAttribute("role", "menuitemradio");
    await expect(open).toHaveAttribute("role", "menuitemradio");
    await expect(off).toHaveText("Comments off");
    await expect(closed).toHaveText("Comments on, panel closed");
    await expect(open).toHaveText("Comments on, panel open");
    await expect(closed).toHaveAttribute("aria-checked", "true");
    await expect(off).toHaveAttribute("aria-checked", "false");
    await expect(open).toHaveAttribute("aria-checked", "false");
    await expect(menu.locator(".cmh-deck-mode-site")).toHaveText("Commentable HTML site");

    // Selecting "panel open" opens the review panel and hides the corner control.
    await open.click();
    expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("open");
    await expect(page.locator("#sidebar")).toBeVisible();
    await expect(page.locator(".cmh-deck-mode-ctl")).toBeHidden();

    await leaveCommentMode(page);
    expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("closed");
    await expect(page.locator(".cmh-deck-mode-ctl")).toBeVisible();
    await expect(page.locator("#sidebar")).toBeHidden();

    // Reopen: "closed" is checked again, and selecting "off" disables commenting.
    const menu2 = await openDeckModeMenu(page);
    await expect(menu2.locator('.cmh-deck-mode-radio[data-deck-mode="closed"]')).toHaveAttribute("aria-checked", "true");
    await menu2.locator('.cmh-deck-mode-radio[data-deck-mode="off"]').click();
    expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("off");
    await expect(page.locator("body")).toHaveClass(/cmh-deck-comments-off/);
  });

  test("CMH-DECK-25: three-state comment model defaults, persists, and gates commenting", async ({ page }) => {
    await openDeck(page, "", "cmh-deck-22-authoring");
    const mode = () => page.evaluate(() => window.__cmhDeck.deckMode());
    const triggerBackground = () => page.locator(".cmh-deck-mode-toggle").evaluate((el) =>
      getComputedStyle(el).backgroundColor);

    expect(await mode()).toBe("closed");
    expect(await page.locator("body").evaluate((body) => body.classList.contains("cmh-deck-present"))).toBe(true);
    expect(await page.locator("body").evaluate((body) => body.classList.contains("cmh-deck-comments-off"))).toBe(false);
    expect(await page.locator("#commentRoot").evaluate((root) => root.classList.contains("cmh-deck-comment-mode"))).toBe(false);
    await expect(page.locator("#sidebar")).toBeHidden();

    const closedBg = await triggerBackground();
    expect(closedBg).not.toBe("rgba(0, 0, 0, 0)");
    expect(closedBg).not.toBe("transparent");

    await selectText(page, ".slide.active p");
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.evaluate(() => window.getSelection().removeAllRanges());
    const preventedInClosed = await page.evaluate(() => {
      const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 });
      document.querySelector(".slide.active").dispatchEvent(ev);
      return ev.defaultPrevented;
    });
    expect(preventedInClosed).toBe(true);
    await expect(page.locator("#menuDocComment")).toBeVisible();
    await page.keyboard.press("Escape");

    const gateMenu = await openDeckModeMenu(page);
    await page.keyboard.press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000001");
    await page.keyboard.press("Escape");
    await expect(gateMenu).toBeHidden();

    await addTextComment(page, ".slide.active p", "opens panel from closed mode");
    await expect(page.locator("#sidebar")).toBeVisible();
    expect(await mode()).toBe("open");
    await leaveCommentMode(page);
    const disabledMenu = await openDeckModeMenu(page);
    const offWithComment = disabledMenu.locator(".cmh-deck-mode-off-item");
    await expect(offWithComment).toBeDisabled();
    await expect(offWithComment).toHaveAttribute("aria-disabled", "true");

    await openDeck(page, "", "cmh-deck-22-open-persist");
    await enterCommentMode(page);
    expect(await mode()).toBe("open");
    await page.reload();
    await ready(page);
    expect(await mode()).toBe("open");
    await expect(page.locator("#sidebar")).toBeVisible();

    await openDeck(page, "", "cmh-deck-22-off-persist");
    const menu = await openDeckModeMenu(page);
    await menu.locator(".cmh-deck-mode-off-item").click();
    expect(await mode()).toBe("off");
    await expect(page.locator("body")).toHaveClass(/cmh-deck-comments-off/);
    expect(await triggerBackground()).toBe(closedBg);

    await selectText(page, ".slide.active p");
    await expect(page.locator("#menuComment")).toBeHidden();
    await page.evaluate(() => window.getSelection().removeAllRanges());
    const preventedInOff = await page.evaluate(() => {
      const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 });
      document.querySelector(".slide.active").dispatchEvent(ev);
      return ev.defaultPrevented;
    });
    expect(preventedInOff).toBe(false);
    await expect(page.locator("#menuDocComment")).toBeHidden();

    await page.reload();
    await ready(page);
    expect(await mode()).toBe("off");
    await expect(page.locator("body")).toHaveClass(/cmh-deck-comments-off/);
  });

  test("CMH-DECK-25: off gates every rich-content comment entry point, not just the selection popup", async ({ page }) => {
    // A deck slide with a real rich-content affordance (an image) that is commentable via the
    // keyboard (focus + Enter opens the image composer) - a path that bypasses the selection popup.
    const IMG = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
    const slides =
      '<section class="slide active" data-slide-id="slide-rich"><h2>Rich</h2>'
      + '<p>Alpha slide content</p><img src="' + IMG + '" alt="pic" width="80" height="60"></section>';
    await installClipboardCapture(page);
    const { html } = stageDeck(slides, { key: "cmh-deck-off-rich" });
    await page.goto(fileUrl(html));
    await ready(page);

    const addImageComment = () => page.evaluate(() => {
      const before = document.querySelectorAll(".cm-composer").length;
      const img = document.querySelector(".slide.active img");
      if (img) { img.focus(); img.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); }
      return document.querySelectorAll(".cm-composer").length - before;
    });

    // In an ON state (closed mode, comments enabled) the image affordance opens a composer,
    // proving the rich-content entry point is live before we disable commenting.
    expect(await addImageComment()).toBe(1);
    await page.locator(".cm-composer [data-act='cancel']").click();
    await expect(page.locator(".cm-composer")).toHaveCount(0);

    // Switch to off (present-only). It must gate EVERY entry point, not just the selection popup.
    const menu = await openDeckModeMenu(page);
    await menu.locator(".cmh-deck-mode-off-item").click();
    await expect(page.locator("body")).toHaveClass(/cmh-deck-comments-off/);

    // Every floating "Add Comment" affordance (mermaid / image / diff / widget / heading) stays
    // hidden even when its reveal path fires, so a present-only deck exposes no dead control.
    const revealed = await page.evaluate(() => {
      const ids = ["mermaidAddBtn", "imageAddBtn", "diffAddBtn", "widgetAddBtn", "headingAddBtn"];
      const out = {};
      for (const id of ids) {
        const b = document.getElementById(id);
        if (!b) { out[id] = "missing"; continue; }
        b.hidden = false; // simulate the hover/focus reveal path
        out[id] = getComputedStyle(b).display;
      }
      return out;
    });
    for (const [id, display] of Object.entries(revealed)) {
      expect(display, id + " must stay hidden while commenting is off").toBe("none");
    }

    // The central composer guard also refuses to open a new composer from the rich-content path.
    expect(await addImageComment(), "no composer opens from a rich-content entry point while off").toBe(0);
  });

  test("CMH-DECK-11: the comment-options menu supports full keyboard navigation", async ({ page }) => {
    await openDeck(page, "", "cmh-deck-menu-kbd");
    const menu = await openDeckModeMenu(page);
    const activeClass = () => page.evaluate(() => (document.activeElement && document.activeElement.className) || "");
    // Opening the menu focuses the current (checked) option - default "closed".
    await expect.poll(activeClass).toContain("cmh-deck-mode-closed-item");
    await page.keyboard.press("ArrowDown");
    await expect.poll(activeClass).toContain("cmh-deck-mode-open-item");
    await page.keyboard.press("ArrowDown");
    await expect.poll(activeClass).toContain("cmh-deck-mode-site");
    await page.keyboard.press("ArrowDown"); // wraps to the first item
    await expect.poll(activeClass).toContain("cmh-deck-mode-off-item");
    await page.keyboard.press("ArrowUp"); // wraps to the last item
    await expect.poll(activeClass).toContain("cmh-deck-mode-site");
    await page.keyboard.press("Home");
    await expect.poll(activeClass).toContain("cmh-deck-mode-off-item");
    await page.keyboard.press("End");
    await expect.poll(activeClass).toContain("cmh-deck-mode-site");
    // Tab moves focus out of the menu and closes it (no keyboard trap).
    await page.keyboard.press("Tab");
    await expect(menu).toBeHidden();
  });

  test("CMH-DECK-11: the open menu blocks slide navigation, dismisses on outside click, and manages focus", async ({ page }) => {
    await openDeck(page, "", "cmh-deck-menu-focus");
    const toggle = page.locator(".cmh-deck-mode-toggle");
    const menu = page.locator(".cmh-deck-mode-menu");

    // While the menu is open, deck slide-navigation keys do NOT move slides.
    await openDeckModeMenu(page);
    await page.keyboard.press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000001");
    await page.keyboard.press("PageDown");
    expect(await activeId(page)).toBe("slide-00000001");
    // Backspace is guarded the same way: it must not step back while blocking chrome is open.
    await page.evaluate(() => window.__cmhDeck.showSlide(1));
    expect(await activeId(page)).toBe("slide-00000002");
    await page.keyboard.press("Backspace");
    expect(await activeId(page)).toBe("slide-00000002");
    await page.evaluate(() => window.__cmhDeck.showSlide(0));
    // Escape closes the menu and returns focus to the trigger.
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    await expect(toggle).toBeFocused();

    // A click outside the menu dismisses it.
    await openDeckModeMenu(page);
    await page.mouse.click(5, 400);
    await expect(menu).toBeHidden();

    // Choosing "panel open" hides the trigger, so focus moves into the sidebar (not lost).
    const menu2 = await openDeckModeMenu(page);
    await menu2.locator('.cmh-deck-mode-radio[data-deck-mode="open"]').click();
    await expect(page.locator("#sidebar")).toBeVisible();
    await expect(page.locator("#btnCloseSidebar")).toBeFocused();
  });

  test("CMH-DECK-26: Mermaid diagrams on deck slides fill the slide width", async ({ page }) => {
    const slides =
      '<section class="slide active" data-slide-id="slide-mermaid"><h2>Mermaid</h2>'
      + '<pre class="mermaid cm-skip">flowchart LR\n A[Alpha]-->B[Beta]</pre></section>';
    const { dir } = stageDeck(slides, { key: "cmh-deck-mermaid-width" });
    const server = await startStaticServer(dir);
    try {
      await installClipboardCapture(page);
      await routeMermaidLocal(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      await expect.poll(() => page.locator(".slide.active .cm-mermaid-host > svg").count(), { timeout: 20000 }).toBe(1);
      const metrics = await page.evaluate(() => {
        const slide = document.querySelector(".slide.active");
        const host = slide.querySelector(".cm-mermaid-host");
        const svg = host.querySelector("svg");
        return {
          slideWidth: slide.getBoundingClientRect().width,
          hostWidth: host.getBoundingClientRect().width,
          svgWidth: svg.getBoundingClientRect().width,
        };
      });
      expect(metrics.svgWidth).toBeGreaterThanOrEqual(metrics.hostWidth * 0.8);
      expect(metrics.svgWidth).toBeGreaterThanOrEqual(metrics.slideWidth * 0.55);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  // Measure the active slide's diagram and its content zone in layout pixels: the stage transform
  // is neutralized so getBoundingClientRect reads 1:1 (the fit itself is transform-independent).
  const fitMetrics = (page) => page.evaluate(() => {
    const stage = document.querySelector(".deck-stage");
    const prev = stage.style.transform;
    stage.style.transform = "none";
    const slide = document.querySelector(".slide.active");
    const cs = getComputedStyle(slide);
    const contentH = slide.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    const contentW = slide.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const svg = slide.querySelector(".cm-mermaid-host > svg").getBoundingClientRect();
    stage.style.transform = prev;
    return { contentH, contentW, svgH: svg.height, svgW: svg.width };
  });

  test("CMH-DECK-35: a diagram-dominant deck slide fills the slide height as well as the width", async ({ page }) => {
    // A tall vertical chain: width-fill alone (CMH-DECK-26) would overflow the slide height and
    // clip; contain-to-fit must instead bound it to the slide height while still filling most of it.
    const slides =
      '<section class="slide active" data-slide-id="slide-tall"><h2>Flow</h2>'
      + '<pre class="mermaid cm-skip">flowchart TB\n'
      + ' A[Alpha]-->B[Beta]\n B-->C[Gamma]\n C-->D[Delta]\n D-->E[Epsilon]\n E-->F[Zeta]</pre></section>';
    const { dir } = stageDeck(slides, { key: "cmh-deck-mermaid-fit" });
    const server = await startStaticServer(dir);
    try {
      await installClipboardCapture(page);
      await routeMermaidLocal(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      await expect.poll(() => page.locator(".slide.active .cm-mermaid-host > svg").count(), { timeout: 20000 }).toBe(1);
      // A slide whose only non-text content is one diagram is auto-marked as a diagram slide.
      await expect(page.locator(".slide.active.cmh-deck-diagram-slide")).toHaveCount(1);
      // The diagram is contained within the slide content height (no overflow / clipping) ...
      await expect.poll(async () => {
        const m = await fitMetrics(page);
        return m.svgH <= m.contentH + 2;
      }, { timeout: 10000 }).toBe(true);
      const m = await fitMetrics(page);
      // ... and still fills a meaningful fraction of the available height (not the tiny intrinsic size).
      expect(m.svgH).toBeGreaterThanOrEqual(m.contentH * 0.8);
      // Height-bound: it never overflows the width either.
      expect(m.svgW).toBeLessThanOrEqual(m.contentW + 2);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-35: a lone diagram in a two-column slide is un-confined to the full slide width", async ({ page }) => {
    // Bullets left, diagram right in a two-column slide: without the fill treatment the diagram is
    // boxed into the half-width column. The .cmh-slide-diagram recipe un-confines it to full width.
    const slides =
      '<section class="slide active cmh-slide-diagram" data-slide-id="slide-cols"><h2>Cols</h2>'
      + '<div class="cmh-cols-2">'
      + '<div><ul><li>First point</li><li>Second point</li><li>Third point</li></ul></div>'
      + '<div><pre class="mermaid cm-skip">flowchart LR\n A[Alpha]-->B[Beta]\n B-->C[Gamma]\n C-->D[Delta]</pre></div>'
      + '</div></section>';
    const { dir } = stageDeck(slides, { key: "cmh-deck-mermaid-lone" });
    const server = await startStaticServer(dir);
    try {
      await installClipboardCapture(page);
      await routeMermaidLocal(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      await expect.poll(() => page.locator(".slide.active .cm-mermaid-host > svg").count(), { timeout: 20000 }).toBe(1);
      // The diagram uses the full slide width (well beyond a half column) without overflowing.
      await expect.poll(async () => {
        const m = await fitMetrics(page);
        return m.svgW / m.contentW;
      }, { timeout: 10000 }).toBeGreaterThanOrEqual(0.85);
      const m = await fitMetrics(page);
      expect(m.svgW).toBeLessThanOrEqual(m.contentW + 2);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-35: a diagram nested in wrappers is still bounded to the slide (no overflow)", async ({ page }) => {
    // The opt-in .cmh-slide-diagram allows arbitrary wrapping; a diagram nested below a direct child
    // must still contain-fit within the slide (its own height is content-driven, not space-driven,
    // so an unbounded fit would overflow/clip the fixed stage). A tall chain makes the regression loud.
    const slides =
      '<section class="slide active cmh-slide-diagram" data-slide-id="slide-nested"><h2>Nested</h2>'
      + '<div class="wrap-a"><div class="wrap-b">'
      + '<pre class="mermaid cm-skip">flowchart TB\n'
      + ' A[Alpha]-->B[Beta]\n B-->C[Gamma]\n C-->D[Delta]\n D-->E[Epsilon]\n E-->F[Zeta]</pre>'
      + '</div></div></section>';
    const { dir } = stageDeck(slides, { key: "cmh-deck-mermaid-nested" });
    const server = await startStaticServer(dir);
    try {
      await installClipboardCapture(page);
      await routeMermaidLocal(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      await expect.poll(() => page.locator(".slide.active .cm-mermaid-host > svg").count(), { timeout: 20000 }).toBe(1);
      // Bounded to the slide content box: no orders-of-magnitude overflow / clip.
      await expect.poll(async () => {
        const m = await fitMetrics(page);
        return m.svgH <= m.contentH + 2 && m.svgW <= m.contentW + 2;
      }, { timeout: 10000 }).toBe(true);
      const m = await fitMetrics(page);
      // Still meaningfully large, not collapsed to the intrinsic size.
      expect(m.svgH).toBeGreaterThanOrEqual(m.contentH * 0.6);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-35: a bullets+diagram two-column slide is NOT auto-flattened (opt-in only)", async ({ page }) => {
    // A slide the author deliberately laid out as two columns keeps that layout: the automatic rule
    // must not silently collapse a .cmh-cols-2. Only the explicit .cmh-slide-diagram opt-in un-confines.
    const slides =
      '<section class="slide active" data-slide-id="slide-keepcols"><h2>Keep</h2>'
      + '<div class="cmh-cols-2">'
      + '<div><ul><li>First point</li><li>Second point</li></ul></div>'
      + '<div><pre class="mermaid cm-skip">flowchart LR\n A[Alpha]-->B[Beta]\n B-->C[Gamma]</pre></div>'
      + '</div></section>';
    const { dir } = stageDeck(slides, { key: "cmh-deck-mermaid-keepcols" });
    const server = await startStaticServer(dir);
    try {
      await installClipboardCapture(page);
      await routeMermaidLocal(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      await expect.poll(() => page.locator(".slide.active .cm-mermaid-host > svg").count(), { timeout: 20000 }).toBe(1);
      // Not auto-classified: the two-column grid is preserved (still a grid, not display:contents).
      await expect(page.locator(".slide.active.cmh-deck-diagram-slide")).toHaveCount(0);
      const preserved = await page.evaluate(() => {
        const grid = document.querySelector(".slide.active .cmh-cols-2");
        return grid ? getComputedStyle(grid).display : null;
      });
      expect(preserved).toBe("grid");
      // The diagram stays boxed in its half-width column (well under the full slide width).
      const m = await fitMetrics(page);
      expect(m.svgW).toBeLessThan(m.contentW * 0.65);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-35: a nested diagram sits above a trailing reference row (no overlap)", async ({ page }) => {
    // A forced diagram slide with the diagram nested in wrappers AND a bottom-pinned .cmh-refs row:
    // the diagram must be bounded to the space ABOVE the refs, not painted over it.
    const slides =
      '<section class="slide active cmh-slide-diagram" data-slide-id="slide-nref"><h2>Nested + refs</h2>'
      + '<div class="wrap-a"><div class="wrap-b">'
      + '<pre class="mermaid cm-skip">flowchart TB\n A[Alpha]-->B[Beta]\n B-->C[Gamma]\n C-->D[Delta]</pre>'
      + '</div></div>'
      + '<p class="cmh-refs"><span class="cmh-refs-label">Ref</span> <a href="https://example.com/a.md">a.md</a></p>'
      + '</section>';
    const { dir } = stageDeck(slides, { key: "cmh-deck-mermaid-nref" });
    const server = await startStaticServer(dir);
    try {
      await installClipboardCapture(page);
      await routeMermaidLocal(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      await expect.poll(() => page.locator(".slide.active .cm-mermaid-host > svg").count(), { timeout: 20000 }).toBe(1);
      // The diagram's bottom stays at or above the refs row's top (no overlap), and it still fills.
      await expect.poll(async () => {
        return page.evaluate(() => {
          const stage = document.querySelector(".deck-stage");
          const prev = stage.style.transform;
          stage.style.transform = "none";
          const svg = document.querySelector(".slide.active .cm-mermaid-host > svg").getBoundingClientRect();
          const refs = document.querySelector(".slide.active .cmh-refs").getBoundingClientRect();
          stage.style.transform = prev;
          return { ok: svg.bottom <= refs.top + 2, svgH: svg.height };
        }).then((r) => r.ok);
      }, { timeout: 10000 }).toBe(true);
      const m = await fitMetrics(page);
      expect(m.svgH).toBeGreaterThanOrEqual(m.contentH * 0.4);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-35: two diagrams on a forced slide are each sized without stealing space", async ({ page }) => {
    // flex:1 1 0% shares the slide equally, so neither diagram collapses to zero when the runtime
    // momentarily zeroes one SVG to measure it.
    const slides =
      '<section class="slide active cmh-slide-diagram" data-slide-id="slide-two"><h2>Two</h2>'
      + '<pre class="mermaid cm-skip">flowchart LR\n A[Alpha]-->B[Beta]\n B-->C[Gamma]</pre>'
      + '<pre class="mermaid cm-skip">flowchart LR\n D[Delta]-->E[Epsilon]\n E-->F[Zeta]</pre>'
      + '</section>';
    const { dir } = stageDeck(slides, { key: "cmh-deck-mermaid-two" });
    const server = await startStaticServer(dir);
    try {
      await installClipboardCapture(page);
      await routeMermaidLocal(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      await expect.poll(() => page.locator(".slide.active .cm-mermaid-host > svg").count(), { timeout: 20000 }).toBe(2);
      // Both diagrams end up meaningfully sized (neither collapsed to ~0) and bounded to the slide.
      await expect.poll(async () => {
        return page.evaluate(() => {
          const stage = document.querySelector(".deck-stage");
          const prev = stage.style.transform;
          stage.style.transform = "none";
          const slide = document.querySelector(".slide.active");
          const cs = getComputedStyle(slide);
          const contentH = slide.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
          const svgs = Array.from(slide.querySelectorAll(".cm-mermaid-host > svg"));
          const heights = svgs.map((s) => s.getBoundingClientRect().height);
          stage.style.transform = prev;
          return heights.length === 2 && heights.every((h) => h > contentH * 0.15) &&
            heights.reduce((a, b) => a + b, 0) <= contentH + 4;
        });
      }, { timeout: 10000 }).toBe(true);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-35: navigating to a previously inactive diagram slide fits it (slidechange path)", async ({ page }) => {
    // The diagram lives on slide 2 (inactive at load). Navigating there fires cmh:slidechange; the
    // diagram must be contain-fit on the now-active slide. Also proves a re-fit recomputes: the SVG is
    // deliberately mis-sized first, and the slide change restores the correct fit.
    const slides =
      '<section class="slide active" data-slide-id="slide-a"><h2>Intro</h2><p>Opening slide.</p></section>'
      + '<section class="slide cmh-slide-diagram" data-slide-id="slide-b"><h2>Flow</h2>'
      + '<pre class="mermaid cm-skip">flowchart TB\n A[Alpha]-->B[Beta]\n B-->C[Gamma]\n C-->D[Delta]</pre></section>';
    const { dir } = stageDeck(slides, { key: "cmh-deck-mermaid-nav" });
    const server = await startStaticServer(dir);
    try {
      await installClipboardCapture(page);
      await routeMermaidLocal(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      await expect.poll(() => page.locator("[data-slide-id='slide-b'] .cm-mermaid-host > svg").count(), { timeout: 20000 }).toBe(1);
      // Mis-size the SVG and navigate: the cmh:slidechange handler must recompute the contain-fit.
      await page.evaluate(() => {
        const svg = document.querySelector("[data-slide-id='slide-b'] .cm-mermaid-host > svg");
        svg.style.width = "10px";
        svg.style.height = "10px";
        window.__cmhDeck.showSlideById("slide-b");
      });
      await expect(page.locator(".slide.active[data-slide-id='slide-b']")).toHaveCount(1);
      await expect.poll(async () => {
        const m = await fitMetrics(page);
        return m.svgH > m.contentH * 0.5 && m.svgH <= m.contentH + 2 && m.svgW <= m.contentW + 2;
      }, { timeout: 10000 }).toBe(true);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-35: a padded diagram host is fit to its content box, not clipped", async ({ page }) => {
    // client{Width,Height} include the host's padding; the fit must size the SVG to the host CONTENT
    // box so a padded host (the showcase gives pre.mermaid 26px) does not clip the diagram.
    const slides =
      '<section class="slide active cmh-slide-diagram" data-slide-id="slide-pad"><h2>Padded</h2>'
      + '<pre class="mermaid cm-skip" style="padding:26px">flowchart LR\n A[Alpha]-->B[Beta]\n B-->C[Gamma]\n C-->D[Delta]</pre>'
      + '</section>';
    const { dir } = stageDeck(slides, { key: "cmh-deck-mermaid-pad" });
    const server = await startStaticServer(dir);
    try {
      await installClipboardCapture(page);
      await routeMermaidLocal(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      await expect.poll(() => page.locator(".slide.active .cm-mermaid-host > svg").count(), { timeout: 20000 }).toBe(1);
      // The SVG stays within the host's padded content box (no clip) on both axes.
      await expect.poll(async () => {
        return page.evaluate(() => {
          const stage = document.querySelector(".deck-stage");
          const prev = stage.style.transform;
          stage.style.transform = "none";
          const host = document.querySelector(".slide.active .cm-mermaid-host");
          const hcs = getComputedStyle(host);
          const padX = parseFloat(hcs.paddingLeft) + parseFloat(hcs.paddingRight);
          const padY = parseFloat(hcs.paddingTop) + parseFloat(hcs.paddingBottom);
          const svg = host.querySelector("svg").getBoundingClientRect();
          const ok = svg.width <= host.clientWidth - padX + 2 && svg.height <= host.clientHeight - padY + 2;
          stage.style.transform = prev;
          return ok;
        });
      }, { timeout: 10000 }).toBe(true);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-27: sortable-table sort chevrons inherit the deck table header color", async ({ page }) => {
    const slides =
      '<section class="slide active" data-slide-id="slide-sort"><h2>Sortable</h2>'
      + '<table><thead><tr>'
      + '<th style="background:#174ea6">Bed</th>'
      + '<th style="background:#174ea6">Status</th>'
      + '</tr></thead><tbody>'
      + '<tr><td>2</td><td>Open</td></tr>'
      + '<tr><td>8</td><td>Closed</td></tr>'
      + '</tbody></table></section>';
    const { html, dir } = stageDeck(slides, { key: "cmh-deck-sort-chevrons" });
    try {
      await installClipboardCapture(page);
      await page.goto(fileUrl(html));
      await ready(page);
      await expect(page.locator(".slide.active th .cmh-sort-ctrl")).toHaveCount(2);
      const chevrons = await page.locator(".slide.active th").evaluateAll((ths) => ths.map((th) => {
        const headerColor = getComputedStyle(th).color;
        const up = th.querySelector(".cmh-sort-up");
        const dn = th.querySelector(".cmh-sort-dn");
        return {
          headerColor,
          controlColor: getComputedStyle(th.querySelector(".cmh-sort-ctrl")).color,
          upColor: getComputedStyle(up).color,
          dnColor: getComputedStyle(dn).color,
        };
      }));
      for (const item of chevrons) {
        expect(item.controlColor).toBe(item.headerColor);
        expect(item.upColor).toBe(item.headerColor);
        expect(item.dnColor).toBe(item.headerColor);
        expect(luminance(parseRgb(item.upColor))).toBeGreaterThan(0.8);
      }
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-05c: a comment on a hidden slide restores after reload", async ({ page }) => {
    await openDeck(page);
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-00000003"));
    await addTextComment(page, ".slide.active p", "persist me");
    expect(await page.locator("mark.cm-hl").count()).toBe(1);
    await page.evaluate(() => history.replaceState(null, "", location.href.replace(/#.*/, "")));
    // Reload without a slide deep link: the deck re-activates in closed mode on slide 1; the
    // comment must restore in the now-hidden slide 3.
    await page.reload();
    await ready(page);
    expect(await activeId(page)).toBe("slide-00000001");
    await expect.poll(() => page.locator("mark.cm-hl").count()).toBe(1);
    expect(await page.evaluate(() => {
      const m = document.querySelector("mark.cm-hl");
      return !!(m && m.closest('[data-slide-id="slide-00000003"]'));
    })).toBe(true);
    await enterCommentMode(page);
    await page.locator(".cm-card").first().click();
    await expect.poll(() => activeId(page)).toBe("slide-00000003");
  });

  test("CMH-DECK-05d: the deck-aware jump resolves a non-text ([data-cids~]) anchor's slide", async ({ page }) => {
    await openDeck(page);
    await page.evaluate(() => {
      const slide3 = document.querySelector('[data-slide-id="slide-00000003"]');
      const anchor = document.createElement("span");
      anchor.setAttribute("data-cids", "cid-XYZ");
      slide3.appendChild(anchor);
      const card = document.createElement("div");
      card.className = "cm-card";
      card.setAttribute("data-cid", "cid-XYZ");
      document.body.appendChild(card);
    });
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-00000001"));
    // fire a synthetic click (the deck-aware jump is a document-level capture listener; a real
    // pointer click would be intercepted by the full-screen slide stage)
    await page.evaluate(() => document.querySelector('.cm-card[data-cid="cid-XYZ"]').click());
    await expect.poll(() => activeId(page)).toBe("slide-00000003");
  });

  test("CMH-DECK-05a: default closed mode hides the panel; open mode reveals it and gates keys", async ({ page }) => {
    await openDeck(page);
    const control = page.locator(".cmh-deck-mode-ctl");
    expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("closed");
    // closed mode by default: the comment sidebar/toolbar are hidden so the slide is full-screen
    await expect(page.locator("#sidebar")).toBeHidden();
    await expect(page.locator(".cm-toolbar")).toBeHidden();
    await enterCommentMode(page);
    expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("open");
    expect(await page.evaluate(
      () => document.getElementById("commentRoot").classList.contains("cmh-deck-comment-mode"))).toBe(true);
    // open mode reveals the sidebar for reviewing
    await expect(page.locator("#sidebar")).toBeVisible();
    // navigation keys do nothing while open mode has the review panel up
    await page.keyboard.press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000001");
    // the control hides while the panel is open; hide the panel to return to closed mode
    await expect(control).toBeHidden();
    await leaveCommentMode(page);
    await expect(control).toBeVisible();
    expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("closed");
    await expect(page.locator("#sidebar")).toBeHidden();
    await page.keyboard.press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000002");
  });

  test("CMH-DECK-05a: open mode force-reveals staged slide content", async ({ page }) => {
    await openDeck(page);
    await page.evaluate(() => {
      const s = document.querySelector(".slide.active");
      const r = document.createElement("div");
      r.className = "reveal";
      r.setAttribute("style", "opacity:0;visibility:hidden");
      r.textContent = "staged";
      s.appendChild(r);
    });
    // open mode: the force-reveal !important rule overrides the inline hidden state
    await enterCommentMode(page);
    const cs = await page.evaluate(() => {
      const c = getComputedStyle(document.querySelector(".slide.active .reveal"));
      return { opacity: c.opacity, visibility: c.visibility };
    });
    expect(cs.opacity).toBe("1");
    expect(cs.visibility).toBe("visible");
  });

  test("CMH-DECK-05c/05d: a comment restores on a hidden slide and its card jumps to that slide", async ({ page }) => {
    await openDeck(page);
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-00000003"));
    await addTextComment(page, ".slide.active p", "note on slide three");
    expect(await page.locator("mark.cm-hl").count()).toBe(1);
    // navigate away; the highlight persists in the (now hidden) slide DOM
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-00000001"));
    expect(await activeId(page)).toBe("slide-00000001");
    // clicking the sidebar card activates the owning slide (deck-aware jump)
    await page.locator(".cm-card").first().click();
    await expect.poll(() => activeId(page)).toBe("slide-00000003");
  });

  test("CMH-DECK-05: a REAL scaffolded deck activates the runtime, not the flow-document chrome", async ({ page }) => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_scaffold_"));
    const frag = path.join(dir, "slides.html");
    fs.writeFileSync(frag,
      '<section class="slide"><h2>A</h2><p>first slide alpha</p></section>'
      + '<section class="slide"><h2>B</h2><p>second slide beta</p></section>');
    const out = path.join(dir, "deck.html");
    const r = spawnSync(PYTHON, [path.join(SKILL, "tools", "deck", "deck_scaffold.py"),
      "--content", frag, "--label", "Real Deck", "--source", out, "--out", out], { encoding: "utf8" });
    expect(r.status, r.stderr).toBe(0);
    await installClipboardCapture(page);
    await page.goto(fileUrl(out));
    await ready(page);
    // the deck runtime activated - the decoy-root bug would have left __cmhDeck undefined
    expect(await page.evaluate(() => typeof window.__cmhDeck)).toBe("object");
    expect(await page.evaluate(() => window.__cmhDeck.slideCount())).toBe(2);
    // the flow-document side TOC is NOT rendered on a deck
    expect(await page.locator("#cmSideToc").count()).toBe(0);
    // the fixed stage is scaled to the viewport (not left at full 1920px)
    const transform = await page.evaluate(() => document.querySelector(".deck-stage").style.transform);
    expect(transform).toContain("scale(");
    // slide counter shows position / total
    await expect(page.locator(".cmh-deck-count")).toHaveText("1 / 2");
  });

  test("CMH-DECK-05: Export Offline round-trips a deck (mode + comments + card jump) with zero network", async ({ page, browser }) => {
    test.setTimeout(60000);
    const { dir } = stageDeck(SLIDES, { key: "cmh-deck-offline" });
    const server = await startStaticServer(dir);
    let ctx2;
    try {
      await installClipboardCapture(page);
      await page.goto(server.url + "/deck.html");
      await ready(page);
      // Add a comment on the third slide; saving it auto-opens the review panel for export.
      await page.evaluate(() => window.__cmhDeck.showSlideById("slide-00000003"));
      await addTextComment(page, ".slide.active p", "offline deck note");
      await page.getByRole("button", { name: "Slide overview", exact: true }).click();
      await expect(page.locator(".cmh-deck-overview")).toBeVisible();
      // the sidebar Export Offline button is reachable once the panel is revealed
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        clickSidebarExport(page, "#btnExportOffline"),
      ]);
      expect(download.suggestedFilename()).toMatch(/-offline\.html$/);
      const exportedHtml = await readDownload(download);
      // deck mode survives the export; transient deck mode body classes are NOT baked in
      expect(exportedHtml).toContain('data-cmh-mode="deck"');
      expect(/<body[^>]*class="[^"]*cmh-deck-present/.test(exportedHtml)).toBe(false);
      expect(/<body[^>]*class="[^"]*cmh-deck-comments-off/.test(exportedHtml)).toBe(false);
      expect(exportedHtml).not.toMatch(/<section\b[^>]*\bcmh-deck-overview\b/);
      const slideIds = Array.from(exportedHtml.matchAll(/data-slide-id="([^"]+)"/g), (m) => m[1]);
      expect(new Set(slideIds).size).toBe(slideIds.length);

      const exportedPath = path.join(dir, "deck-offline.html");
      fs.writeFileSync(exportedPath, exportedHtml);
      ctx2 = await browser.newContext();
      const page2 = await ctx2.newPage();
      const external = [];
      await page2.route(/^https?:\/\//, async (route) => { external.push(route.request().url()); await route.abort(); });
      await page2.goto(fileUrl(exportedPath));
      await ready(page2);
      // the deck runtime re-activates, starting in closed mode on slide 1
      expect(await page2.evaluate(() => typeof window.__cmhDeck)).toBe("object");
      expect(await page2.evaluate(() => window.__cmhDeck.deckMode())).toBe("closed");
      expect(await page2.evaluate(() => window.__cmhDeck.activeSlideId())).toBe("slide-00000001");
      // the comment restored on the (hidden) third slide; its card jumps there
      await expect.poll(() => page2.locator("mark.cm-hl").count()).toBe(1);
      await enterCommentMode(page2);
      await expect(page2.locator("#commentList")).toContainText("offline deck note");
      await page2.locator(".cm-card").first().click();
      await expect.poll(() => page2.evaluate(() => window.__cmhDeck.activeSlideId())).toBe("slide-00000003");
      expect(external).toEqual([]);
    } finally {
      if (ctx2) await ctx2.close();
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-DECK-15: the comment-options control hides while the side panel is open (all widths)", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 800 });
    await openDeck(page);
    const control = page.locator(".cmh-deck-mode-ctl");
    await expect(control).toBeVisible();
    await enterCommentMode(page);
    await expect(page.locator("#sidebar")).toBeVisible();
    await expect(control).toBeHidden();                   // hidden while the panel is open, even wide
    await leaveCommentMode(page);
    await expect(control).toBeVisible();                  // reappears so the menu stays reachable
  });

  test("CMH-DECK-15: the comments action toolbar never appears in a deck", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 800 });
    await openDeck(page);
    const toolbar = page.locator(".cm-toolbar");
    await expect(toolbar).toBeHidden();                   // closed mode
    await enterCommentMode(page);
    await expect(page.locator("#sidebar")).toBeVisible();
    await expect(toolbar).toBeHidden();
    await leaveCommentMode(page);
    await expect(toolbar).toBeHidden();                   // still hidden - only the menu control shows
  });

  test("CMH-DECK-15: the slide stage spans the full width when the panel is hidden in closed mode", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 800 });
    await openDeck(page);
    const innerW = await page.evaluate(() => window.innerWidth);
    const viewportRight = () => page.evaluate(() =>
      Math.round(document.querySelector(".deck-viewport").getBoundingClientRect().right));
    await enterCommentMode(page);
    await expect(page.locator("#sidebar")).toBeVisible();
    expect(await viewportRight()).toBeLessThanOrEqual(innerW - 300);   // room reserved for the panel
    await leaveCommentMode(page);
    await expect.poll(viewportRight).toBeGreaterThanOrEqual(innerW - 2);  // full width, no black bar
  });

  test("CMH-DECK-16: the overview is accent-tinted with a red Close button and shows the slide count", async ({ page }) => {
    await openDeck(page);
    await page.locator(".cmh-deck-nav").getByRole("button", { name: "Slide overview", exact: true }).click();
    const overview = page.locator(".cmh-deck-overview");
    await expect(overview).toBeVisible();
    await expect(page.locator(".cmh-deck-overview-count")).toHaveText("3 slides");
    const panelReddish = await overview.evaluate((el) => {
      const [r, g, b] = getComputedStyle(el).backgroundColor.match(/[\d.]+/g).map(Number);
      return r > g && r > b;                              // red is the dominant channel (any scale)
    });
    expect(panelReddish).toBe(true);
    const closeRed = await page.locator(".cmh-deck-overview-close").evaluate((el) => {
      const [r, g, b] = getComputedStyle(el).backgroundColor.match(/[\d.]+/g).map(Number);
      return r > g + 40 && r > b + 40;                    // a saturated 0-255 red, not neutral gray
    });
    expect(closeRed).toBe(true);
  });

  test("CMH-DECK-16: clicking the main deck area closes the overview", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 800 });
    await openDeck(page);
    const overview = page.locator(".cmh-deck-overview");
    await page.locator(".cmh-deck-nav").getByRole("button", { name: "Slide overview", exact: true }).click();
    await expect(overview).toBeVisible();
    await page.mouse.click(1180, 400);                    // far-right deck area, outside the left panel
    await expect(overview).toBeHidden();
  });

  test("CMH-DECK-16: the overview grid scrolls when the slides overflow the viewport", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 480 });
    await installClipboardCapture(page);
    const many = Array.from({ length: 14 }, (_, i) =>
      '<section class="slide' + (i === 0 ? " active" : "") + '" data-slide-id="slide-scroll-' + i + '">'
      + "<h2>Slide " + (i + 1) + "</h2><p>Body " + (i + 1) + "</p></section>").join("");
    const { html } = stageDeck(many, { key: "cmh-deck-scroll" });
    await page.goto(fileUrl(html));
    await ready(page);
    await page.keyboard.press("o");
    const overview = page.locator(".cmh-deck-overview");
    await expect(overview).toBeVisible();
    const scrollable = await page.locator(".cmh-deck-overview-grid").evaluate((el) => el.scrollHeight - el.clientHeight > 4);
    expect(scrollable).toBe(true);
  });

  test("CMH-DECK-16: the overview title list omits slide thumbnail clones", async ({ page }) => {
    const revealSlides =
      '<section class="slide active" data-slide-id="slide-reveal-1"><h2>Reveal</h2>'
      + '<div class="reveal" style="opacity:0" data-reveal-probe>Hidden until revealed</div></section>'
      + '<section class="slide" data-slide-id="slide-reveal-2"><h2>Two</h2><p>Second</p></section>';
    await installClipboardCapture(page);
    const { html } = stageDeck(revealSlides, { key: "cmh-deck-reveal" });
    await page.goto(fileUrl(html));
    await ready(page);
    await page.keyboard.press("o");
    await expect(page.locator(".cmh-deck-overview")).toBeVisible();
    await expect(page.locator(".cmh-deck-overview-card")).toHaveCount(2);
    await expect(page.locator(".cmh-deck-overview-card").first().locator(".cmh-deck-overview-card-num")).toHaveText("1");
    await expect(page.locator(".cmh-deck-overview-card").first().locator(".cmh-deck-overview-card-label")).toHaveText("Reveal");
    await expect(page.locator(".cmh-deck-overview-thumb, .cmh-deck-overview-scale")).toHaveCount(0);
    await expect(page.locator(".cmh-deck-overview [data-reveal-probe]")).toHaveCount(0);
  });

  test("CMH-DECK-28: narrow portrait decks show a dismissible landscape hint only for decks", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const deck = stageDeck('<section class="slide active" data-slide-id="s1"><h2>Portrait</h2><p>Rotate for readability.</p></section>', {
      key: "cmh-deck-portrait-hint",
    });
    const doc = stageContent("<h1>Flat doc</h1><p>No deck hint here.</p>", {
      key: "cmh-flat-portrait-hint",
      source: "flat-portrait-hint.html",
    });
    try {
      await page.goto(fileUrl(deck.html));
      await ready(page);
      const hint = page.locator(".cmh-deck-landscape-hint");
      await expect(hint).toBeVisible();
      await expect(hint).toContainText("Best viewed in landscape");

      await page.emulateMedia({ media: "print" });
      await expect(hint).toBeHidden();
      await page.emulateMedia({ media: null });
      await expect(hint).toBeVisible();

      await page.evaluate(() => window.__cmhDeck.setDeckMode("open"));
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        clickSidebarExport(page, "#btnSaveHtml"),
      ]);
      const exported = await readDownload(download);
      expect(exported).not.toMatch(/<[^>]+class="[^"]*cmh-deck-landscape-hint/);
      expect(exported).not.toMatch(/<[^>]+class='[^']*cmh-deck-landscape-hint/);

      await page.setViewportSize({ width: 844, height: 390 });
      await expect(hint).toBeHidden();

      await page.setViewportSize({ width: 390, height: 844 });
      await expect(hint).toBeVisible();
      await hint.getByRole("button", { name: "Dismiss landscape hint" }).click();
      await expect(hint).toBeHidden();

      await page.goto(fileUrl(doc.html));
      await ready(page);
      await expect(page.locator(".cmh-deck-landscape-hint")).toHaveCount(0);
    } finally {
      fs.rmSync(deck.dir, { recursive: true, force: true });
      fs.rmSync(doc.dir, { recursive: true, force: true });
    }
  });
});
