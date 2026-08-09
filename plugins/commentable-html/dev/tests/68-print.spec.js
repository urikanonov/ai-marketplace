import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  DEV,
  INLINE,
  addTextComment,
  denyExternalNetwork,
  fileUrl,
  installClipboardCapture,
  openComposerFor,
  openSidebarExportMenu,
  openToolbarMenu,
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
  html = html.replace('data-doc-source="SHAREABLE.html"', 'data-doc-source="' + source + '"');
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
      <table id="sortme"><thead><tr><th>Name</th><th>Count</th></tr></thead>
        <tbody><tr><td>Alpha</td><td>2</td></tr><tr><td>Beta</td><td>1</td></tr></tbody></table>
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
  // Runtime chrome injected INSIDE #commentRoot (a table's sort-arrow controls, a section-review
  // badge) is cm-skip UI, not content, so it must not print into the PDF. The sort control renders
  // opacity:1 on screen, so without an explicit print rule it would appear in the printed output.
  await expect(page.locator("#sortme .cmh-sort-ctrl").first()).toBeAttached();
  expect(await page.locator("#commentRoot .cmh-sort-ctrl").evaluateAll((els) =>
    els.length > 0 && els.every((el) => getComputedStyle(el).display === "none"))).toBe(true);
  expect(await page.locator("#commentRoot .cmh-review-badge").evaluateAll((els) =>
    els.every((el) => getComputedStyle(el).display === "none"))).toBe(true);
  // A draggable widget's "Reset layout" control (.cm-widget-reset) is also cm-skip chrome injected
  // inside #commentRoot (only after a drag), so inject one and confirm the print rule hides it too.
  const resetHidden = await page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    const btn = document.createElement("button");
    btn.className = "cm-skip cm-widget-reset";
    btn.textContent = "Reset layout";
    root.appendChild(btn);
    return getComputedStyle(btn).display;
  });
  expect(resetHidden, "the widget Reset-layout control is hidden in print").toBe("none");
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

test("CMH-PRINT-01: the print appendix shows the comment author pill and ordered reply refinements", async ({ page }) => {
  const content = `<section><h2>Doc</h2><p id="pt">Printable body text.</p></section>`;
  const staged = stagePrintContent(content, { key: "cmh-print-threads", source: "print-threads.html" });
  await installClipboardCapture(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await page.evaluate(() => {
    const t = Date.now();
    window.__cmhStorageCodec.write([
      { id: "cprintroot1", anchorType: "document", note: "print root note", author: "Alice", createdAt: new Date(t).toISOString() },
      { id: "cprintrep01", parentId: "cprintroot1", note: "print reply one", author: "Bob", createdAt: new Date(t + 1000).toISOString() },
      { id: "cprintrep02", parentId: "cprintroot1", note: "print reply two", author: "Bob", createdAt: new Date(t + 2000).toISOString() },
    ]);
  });
  await page.reload();
  await ready(page);
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));

  const appendix = page.locator("#cmhPrintComments");
  await expect(appendix).toBeVisible();
  // One thread article (the count is per-thread), the root author pill, and both replies in order.
  await expect(appendix.locator(".cmh-print-comment")).toHaveCount(1);
  await expect(appendix.locator(".cmh-print-comment .cm-author-pill").first()).toHaveText("Alice");
  const replies = appendix.locator(".cmh-print-reply");
  await expect(replies).toHaveCount(2);
  await expect(replies.nth(0)).toContainText("print reply one");
  await expect(replies.nth(1)).toContainText("print reply two");
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
      breakBefore: style.breakBefore,
      pageBreakBefore: style.pageBreakBefore,
      position: style.position,
      width: style.width,
      page: style.page,
    };
  }));
  expect(slidesInfo).toHaveLength(3);
  for (const info of slidesInfo) {
    expect(info.visibility).toBe("visible");
    expect(info.opacity).toBe("1");
    // Slides clip to their fixed 1920x1080 box (a named landscape page) so nothing spills past the
    // page; the box is the native slide width, not a portrait-page-width reflow.
    expect(info.overflow).toBe("hidden");
    expect(info.position).not.toBe("fixed");
    expect(info.width).toBe("1920px");
    expect(info.page).toBe("cmh-deck-slide");
  }
  // Every slide after the first starts a new page (break-before), which is one page per slide with
  // no trailing blank page; the first slide does not force a break before it (no leading blank).
  for (const info of slidesInfo.slice(1)) {
    expect(info.breakBefore === "page" || info.pageBreakBefore === "always").toBe(true);
  }
  expect(slidesInfo[0].breakBefore === "page" || slidesInfo[0].pageBreakBefore === "always").toBe(false);
});

test("CMH-PRINT-02: the Save as PDF action fires native window.print() from both menus without intercepting Ctrl/Cmd+P", async ({ page }) => {
  // Stub window.print so the action is deterministic and never opens a real print dialog.
  await page.addInitScript(() => {
    window.__printCalls = 0;
    window.print = () => { window.__printCalls += 1; };
  });
  await page.goto(fileUrl(INLINE));
  await ready(page);

  // Toolbar overflow ("More actions") menu carries a discoverable "Save as PDF" item.
  await openToolbarMenu(page);
  const topBtn = page.locator("#btnPrintTop");
  await expect(topBtn).toBeVisible();
  await expect(topBtn).toContainText("Save as PDF");
  await topBtn.click();
  expect(await page.evaluate(() => window.__printCalls)).toBe(1);

  // The sidebar Export menu carries the same action (compact "PDF" label). A comment is added first
  // so the populated sidebar lays its header (and the Export disclosure) out on-screen, matching the
  // established sidebar-export tests.
  await addTextComment(page, "#commentRoot section p", "print action note");
  await openSidebarExportMenu(page);
  const sideBtn = page.locator("#btnPrint");
  await expect(sideBtn).toBeVisible();
  await sideBtn.click();
  expect(await page.evaluate(() => window.__printCalls)).toBe(2);

  // The native Ctrl/Cmd+P shortcut is not intercepted: a ctrl+p and a meta+p keydown are not
  // preventDefault-ed, so the browser's own print/PDF still fires unmodified on both platforms.
  const prevented = await page.evaluate(() => {
    return ["ctrlKey", "metaKey"].map((modifier) => {
      const event = new KeyboardEvent("keydown", { key: "p", [modifier]: true, cancelable: true, bubbles: true });
      document.dispatchEvent(event);
      return event.defaultPrevented;
    });
  });
  expect(prevented).toEqual([false, false]);
});


test("CMH-PRINT-07: print caps a div.mermaid diagram exactly like a pre.mermaid one", async ({ page }) => {
  // The runtime treats BOTH pre.mermaid and div.mermaid as diagram hosts (the mermaid layer scans
  // "pre.mermaid, div.mermaid"), so a document that authors its diagrams as div.mermaid must get the
  // same printable-height cap. Capping only pre.mermaid leaves the div.mermaid SVG unconstrained, so
  // a tall diagram overflows the printed page or splits across a break.
  //
  // The fixture is tall but NOT tall-narrow (aspect w/h 0.525, just above the 0.5 threshold): a
  // tall-NARROW diagram deliberately leaves the height cap for a width-bound print (CMH-PRINT-09),
  // so it would not exercise the cap this test is about. Sitting just ABOVE the threshold also pins
  // that side of the boundary - a marker that fired one step too eagerly would take this fixture
  // onto the width path and fail here.
  const svg = '<svg viewBox="0 0 2100 4000" width="2100" height="4000" role="img" aria-label="tall diagram">'
    + '<rect width="2100" height="4000" fill="#cccccc"></rect></svg>';
  const content = `
    <section>
      <h2>Diagrams</h2>
      <pre class="mermaid" id="preHost" data-processed="true">${svg}</pre>
      <div class="mermaid" id="divHost" data-processed="true">${svg}</div>
    </section>`;
  const staged = stagePrintContent(content, { key: "cmh-print-mermaid", source: "print-mermaid.html" });

  await denyExternalNetwork(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));

  const caps = await page.evaluate(() => {
    const read = (sel) => {
      const el = document.querySelector(sel + " svg");
      if (!el) return null;
      const cs = getComputedStyle(el);
      return { maxHeight: cs.maxHeight, maxWidth: cs.maxWidth };
    };
    return { pre: read("#preHost"), div: read("#divHost") };
  });
  // Guard the fixture itself: both hosts must have been found, or the comparison below is vacuous.
  expect(caps.pre).not.toBeNull();
  expect(caps.div).not.toBeNull();
  // The pre.mermaid cap is the established behavior; it must be a real cap, not "none".
  expect(caps.pre.maxHeight).not.toBe("none");
  expect(caps.div, "a div.mermaid diagram is constrained in print exactly like a pre.mermaid one")
    .toEqual(caps.pre);
});


test("CMH-PRINT-07: the measure CSS caps both mermaid hosts, so the measured page matches the print", async ({ page }) => {
  // The tall-media cap exists TWICE - in 92-print.css (@media print, what is printed) and in the
  // measureCss() string 83-print.js applies under SCREEN media to measure single-page height. They
  // must agree on what a diagram host is: capping a host in one but not the other either prints an
  // oversized diagram or measures a height the print never produces. That divergence is what let
  // div.mermaid fall out of the print cap while pre.mermaid kept it.
  //
  // Exercise measureCss() for real rather than reading the source for selector text: a substring
  // check would pass on a selector sitting in a comment or a dead rule. Measure the SAME tall
  // diagram authored both ways and require the injected @page to come out the same height. The
  // fixture is tall but NOT tall-narrow (aspect w/h 0.525), because a tall-narrow diagram is
  // measured on the width-bound path instead (CMH-PRINT-09) and so would not exercise this cap.
  // 0.525 sits just above the 0.5 threshold deliberately: the closer to it, the taller the UNCAPPED
  // diagram measures, and so the wider the margin the absolute bound below has to work with.
  const svg = '<svg viewBox="0 0 2100 4000" width="2100" height="4000" role="img" aria-label="tall diagram">'
    + '<rect width="2100" height="4000" fill="#cccccc"></rect></svg>';
  const pageHeightFor = async (hostHtml, key) => {
    const staged = stagePrintContent(`<section><h2>Diagram</h2>${hostHtml}</section>`, {
      key,
      source: key + ".html",
    });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
    return page.evaluate(() => {
      const el = document.getElementById("cmhPrintSinglePage");
      const m = el && /@page\{size:([\d.]+)px ([\d.]+)px/.exec(el.textContent || "");
      return m ? Math.round(parseFloat(m[2])) : null;
    });
  };

  // Installed once for the page, not per navigation: registering the same route twice would stack
  // duplicate handlers for no benefit.
  await denyExternalNetwork(page);

  const preHeight = await pageHeightFor(`<pre class="mermaid" data-processed="true">${svg}</pre>`, "cmh-measure-pre");
  const divHeight = await pageHeightFor(`<div class="mermaid" data-processed="true">${svg}</div>`, "cmh-measure-div");
  // Both documents must actually be on the single-page path, or the comparison is vacuous.
  expect(preHeight, "the pre.mermaid document measured a single page").not.toBeNull();
  expect(divHeight, "the div.mermaid document measured a single page").not.toBeNull();
  // The cap must actually be APPLIED, not merely applied equally: if measureCss stopped capping
  // BOTH hosts the two heights would still match, so bound each one absolutely. The 4000-unit-tall
  // SVG is capped to 8.4in (806px), so a capped page measures 1226px (pre) / 1211px (div); the same
  // SVG UNCAPPED fills the measurement column and measures 2658px. The bound sits between those two
  // measured values with a wide margin on each side, so a silently removed cap fails here.
  expect(preHeight, "the pre.mermaid diagram is capped during measurement").toBeLessThan(1500);
  expect(divHeight, "the div.mermaid diagram is capped during measurement").toBeLessThan(1500);
  // A `pre` carries a default 1em block margin that a `div` does not, so the two documents differ
  // by a small constant (~16px) even when both diagrams are capped identically. What matters is
  // that the difference is nowhere near the ~1430px an UNCAPPED SVG adds - which is exactly what an
  // uncapped div.mermaid measured before this fix.
  expect(Math.abs(divHeight - preHeight),
    "a div.mermaid document measures essentially the same page height as the identical pre.mermaid one")
    .toBeLessThan(200);
});


test("CMH-PRINT-08: print drops the diagram scroll-fade mask on both mermaid hosts", async ({ page }) => {
  // The scroll-fade mask is an ON-SCREEN cue that a wide diagram scrolls horizontally inside its own
  // box: it fades the host's left and right 18px. Paper does not scroll, so on paper the cue is
  // meaningless and only washes out the printed diagram's edges. Both host shapes carry the class
  // (CMH_MERMAID_SEL), so both must come out unmasked in print.
  //
  // The class is applied by the runtime only when a diagram genuinely overflows, which depends on
  // measured widths; the case is STAGED here (class pre-applied in the markup and re-asserted below)
  // so the test pins the print behavior rather than the overflow heuristics.
  const svg = '<svg viewBox="0 0 2400 300" width="2400" height="300" role="img" aria-label="wide diagram">'
    + '<rect width="2400" height="300" fill="#cccccc"></rect></svg>';
  const content = `
    <section>
      <h2>Diagrams</h2>
      <pre class="mermaid cmh-diagram-wide cmh-diagram-scroll-fade" id="preHost" data-processed="true">${svg}</pre>
      <div class="mermaid cmh-diagram-wide cmh-diagram-scroll-fade" id="divHost" data-processed="true">${svg}</div>
    </section>`;
  const staged = stagePrintContent(content, { key: "cmh-print-fade", source: "print-fade.html" });

  await denyExternalNetwork(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);

  // Re-apply the class before each read: the mermaid layer re-syncs it from live measurements, and a
  // host it decided does not overflow would leave nothing to assert about (a vacuous green).
  const readMasks = () => page.evaluate(() => {
    const out = {};
    ["preHost", "divHost"].forEach((id) => {
      const el = document.getElementById(id);
      el.classList.add("cmh-diagram-scroll-fade");
      const cs = getComputedStyle(el);
      out[id] = { mask: cs.maskImage, webkitMask: cs.webkitMaskImage };
    });
    return out;
  });

  // On screen the cue must still be there - this fix must not silently delete the affordance. The
  // SHAPE is asserted, not just "a gradient": a gradient with opaque edge stops is no fade at all,
  // and a plain `toContain("linear-gradient")` would accept it.
  const onScreen = await readMasks();
  const transparentStops = (value) => (String(value).match(/rgba\(0,\s*0,\s*0,\s*0\)/g) || []).length;
  expect(onScreen.preHost.webkitMask, "the on-screen scroll-fade cue survives on pre.mermaid").toContain("linear-gradient");
  expect(onScreen.divHost.webkitMask, "the on-screen scroll-fade cue survives on div.mermaid").toContain("linear-gradient");
  expect(onScreen.preHost.mask, "the unprefixed on-screen cue survives on pre.mermaid").toContain("linear-gradient");
  expect(onScreen.divHost.mask, "the unprefixed on-screen cue survives on div.mermaid").toContain("linear-gradient");
  expect(transparentStops(onScreen.preHost.mask), "pre.mermaid fades out at BOTH edges").toBeGreaterThanOrEqual(2);
  expect(transparentStops(onScreen.divHost.mask), "div.mermaid fades out at BOTH edges").toBeGreaterThanOrEqual(2);

  await page.emulateMedia({ media: "print" });

  const inPrint = await readMasks();
  // Both properties are read, but they are ONE signal here: Chromium aliases -webkit-mask-image and
  // mask-image into a single computed value, so no Chromium assertion can tell them apart. That the
  // stylesheet still declares BOTH (which matters for a report opened in another browser) is pinned
  // textually in tests/test_vendored_libs.py instead.
  expect(inPrint.preHost.webkitMask, "a pre.mermaid host prints with no edge mask").toBe("none");
  expect(inPrint.divHost.webkitMask, "a div.mermaid host prints with no edge mask").toBe("none");
  expect(inPrint.preHost.mask, "a pre.mermaid host prints with no unprefixed edge mask").toBe("none");
  expect(inPrint.divHost.mask, "a div.mermaid host prints with no unprefixed edge mask").toBe("none");
});

test("CMH-TOC-09: an active section filter never truncates the printed document", async ({ page }) => {
  // A reader's transient Filter sections... query hides non-matching sections on screen with
  // display:none. Print must ignore that runtime state exactly as it ignores a collapsed section,
  // or a Save as PDF silently drops authored content the reader never chose to remove.
  const content = `
    <section id="keep"><h2 id="k">Kept alpha</h2><p>Alpha body text.</p></section>
    <section id="drop"><h2 id="d">Dropped beta</h2><p id="dropbody">Beta body text.</p></section>`;
  const staged = stagePrintContent(content, { key: "cmh-print-toc-filter", source: "print-toc-filter.html" });
  await page.setViewportSize({ width: 1600, height: 800 });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await page.locator("#cmSideToc .cm-side-toc-search").fill("Alpha");
  await expect(page.locator("#drop")).toBeHidden();

  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  await expect(page.locator("#drop")).toBeVisible();
  await expect(page.locator("#dropbody")).toBeVisible();
  // The single-page MEASUREMENT css mirrors the print rules; if it missed this one the @page would
  // be locked to a document shorter than the one that actually prints.
  expect(fs.readFileSync(path.join(DEV, "assets", "css", "92-print.css"), "utf8")).toContain("section.cm-toc-filtered");
  expect(fs.readFileSync(path.join(DEV, "assets", "js", "83-print.js"), "utf8"))
    .toContain("#commentRoot section.cm-toc-filtered{display:revert !important}");
});