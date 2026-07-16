import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { fileUrl, ready, stageDeck, addTextComment, installClipboardCapture, startStaticServer, readDownload, PYTHON, SKILL } from "./helpers.js";

// Three slides with distinct, stable ids and commentable text (CMH-DECK-05).
const SLIDES =
  '<section class="slide active" data-slide-id="slide-00000001"><h2>One</h2><p>Alpha slide one content</p></section>' +
  '<section class="slide" data-slide-id="slide-00000002"><h2>Two</h2><p>Beta slide two content</p></section>' +
  '<section class="slide" data-slide-id="slide-00000003"><h2>Three</h2><p>Gamma slide three content here</p></section>';

async function openDeck(page, hash = "") {
  await installClipboardCapture(page);
  const { html } = stageDeck(SLIDES);
  await page.goto(fileUrl(html) + hash);
  await ready(page);
}

const activeId = (page) => page.evaluate(() => window.__cmhDeck.activeSlideId());

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
    // ArrowRight / Space / PageDown advance; ArrowLeft / PageUp go back; Home / End jump to ends.
    await page.keyboard.press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000002");
    await expect(page.locator(".cmh-deck-count")).toHaveText("2 / 3");
    await page.keyboard.press(" ");
    expect(await activeId(page)).toBe("slide-00000003");
    await page.keyboard.press("PageUp");
    expect(await activeId(page)).toBe("slide-00000002");
    await page.keyboard.press("PageDown");
    expect(await activeId(page)).toBe("slide-00000003");
    await page.keyboard.press("Home");
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

  test("CMH-DECK-06: overview grid opens, lists every slide, titles slides, and click-jumps", async ({ page }) => {
    await openDeck(page);
    const overviewButton = page.locator(".cmh-deck-nav").getByRole("button", { name: "Slide overview", exact: true });
    await expect(overviewButton).toHaveAttribute("aria-expanded", "false");

    await overviewButton.click();
    const overview = page.locator(".cmh-deck-overview");
    await expect(overview).toBeVisible();
    await expect(overviewButton).toHaveAttribute("aria-expanded", "true");

    const slides = overview.locator(".cmh-deck-overview-card");
    await expect(slides).toHaveCount(3);
    await expect(slides.nth(1)).toHaveAttribute("title", "Two");
    await slides.nth(1).hover();
    await expect(page.locator(".cm-tooltip")).toHaveText("Two");

    await slides.nth(2).click();
    await expect(overview).toBeHidden();
    expect(await activeId(page)).toBe("slide-00000003");
    await expect(page.locator(".cmh-deck-count")).toHaveText("3 / 3");
    await expect(overviewButton).toHaveAttribute("aria-expanded", "false");
  });

  test("CMH-DECK-06: overview keyboard shortcut opens, closes, and selects in present and comment modes", async ({ page }) => {
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
    await page.keyboard.press(" ");
    await expect(overview).toBeHidden();
    expect(await activeId(page)).toBe("slide-00000003");
    expect(await page.evaluate(() => window.__overviewEvts.length)).toBe(1);

    await page.keyboard.press("o");
    await expect(overview).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(overview).toBeHidden();

    await page.locator(".cmh-deck-mode-toggle").click();
    await expect(page.locator(".cmh-deck-mode-toggle")).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("o");
    await expect(overview).toBeVisible();
    await page.keyboard.press("End");
    await page.keyboard.press(" ");
    await expect(overview).toBeHidden();
    expect(await activeId(page)).toBe("slide-00000003");
  });

  test("CMH-DECK-06: overview clones stay out of tab order", async ({ page }) => {
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
    await expect(overview.locator(".cmh-deck-overview-scale strong")).toHaveText("Nested highlight");
    expect(await page.locator(".cmh-deck-overview-scale a[href]").count()).toBe(0);

    const focused = [];
    for (let i = 0; i < 4; i++) {
      focused.push(await page.evaluate(() => {
        const el = document.activeElement;
        return {
          inClone: !!(el && el.closest && el.closest(".cmh-deck-overview-scale")),
          label: el && (el.getAttribute("aria-label") || el.textContent || "").trim(),
        };
      }));
      await page.keyboard.press("Tab");
    }
    expect(focused.some((entry) => entry.inClone)).toBe(false);
    expect(focused.map((entry) => entry.label)).toEqual([
      "Slide 1: Links",
      "Slide 2: Next",
      "Slide 1: Links",
      "Slide 2: Next",
    ]);
  });

  test("CMH-DECK-05: the stage refits on viewport resize and comment mode narrows it", async ({ page }) => {
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
    // comment mode narrows the viewport (400px sidebar inset at >=900px), and the stage refits smaller
    await page.setViewportSize({ width: 1400, height: 900 });
    await expect.poll(fits).toBe(true);
    const wideW = (await vp()).w;
    await page.locator(".cmh-deck-mode-toggle").click();
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
    await expect(page.locator(".cmh-deck-mode-toggle")).toBeVisible();
    // comment mode opens the near-full-width sidebar overlay; the controls hide so they don't cover it
    await page.locator(".cmh-deck-mode-toggle").click();
    await expect(page.locator("#sidebar")).toBeVisible();
    await expect(page.locator(".cmh-deck-mode-toggle")).toBeHidden();
    await expect(page.locator(".cmh-deck-nav")).toBeHidden();
    // hiding the sidebar brings the controls back, so returning to present mode stays reachable
    await page.locator("#btnCloseSidebar").click();
    await expect(page.locator(".cmh-deck-mode-toggle")).toBeVisible();
  });

  test("CMH-DECK-05a: present mode suppresses the doc-comment menu and keeps the native menu; comment mode restores it", async ({ page }) => {
    await openDeck(page);
    // present mode (default): a right-click does not preventDefault (native menu kept) and no menu opens
    const preventedInPresent = await page.evaluate(() => {
      const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 });
      document.querySelector(".slide.active").dispatchEvent(ev);
      return ev.defaultPrevented;
    });
    expect(preventedInPresent).toBe(false);
    await expect(page.locator("#contextMenu")).toBeHidden();
    // comment mode: a right-click on empty slide area opens the document-comment menu
    await page.locator(".cmh-deck-mode-toggle").click();
    const preventedInComment = await page.evaluate(() => {
      const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 60, clientY: 60 });
      document.querySelector(".slide.active").dispatchEvent(ev);
      return ev.defaultPrevented;
    });
    expect(preventedInComment).toBe(true);
    await expect(page.locator("#contextMenu")).toBeVisible();
    await expect(page.locator("#menuDocComment")).toBeVisible();
  });

  test("CMH-DECK-11: comment-mode toggle uses the brand icon label and still toggles", async ({ page }) => {
    await openDeck(page);
    const toggle = page.getByRole("button", { name: "Comment Mode" });
    await expect(toggle).toHaveAttribute("title", "Comment Mode");
    await expect(toggle).toHaveAttribute("aria-label", "Comment Mode");
    await expect(toggle.locator("svg.cm-brand-icon")).toHaveCount(1);
    await expect(toggle.locator("svg.cm-brand-icon")).toHaveAttribute("aria-hidden", "true");
    await expect(toggle.locator("svg.cm-brand-icon")).not.toHaveAttribute("data-cmh-tip");
    await expect(toggle).not.toHaveText(/Comment mode/i);
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await toggle.hover();
    await expect(page.locator(".cm-tooltip")).toHaveText("Comment Mode");

    // Once comment mode opens the panel, the toggle is display:none (out of the a11y tree), so the
    // role locator can no longer resolve it; drive the state checks through the CSS locator, which
    // still matches a hidden element.
    const toggleEl = page.locator(".cmh-deck-mode-toggle");
    await toggleEl.click();
    await expect(toggleEl).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#sidebar")).toBeVisible();
    await expect(toggleEl).toBeHidden();                  // the toggle hides while the panel is open

    await page.locator("#btnCloseSidebar").click();       // hide the panel to bring the toggle back
    await expect(toggleEl).toBeVisible();
    await toggleEl.click();                               // click it to leave comment mode
    await expect(toggleEl).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator("#sidebar")).toBeHidden();
  });

  test("CMH-DECK-05c: a comment on a hidden slide restores after reload", async ({ page }) => {
    await openDeck(page);
    await page.locator(".cmh-deck-mode-toggle").click();
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-00000003"));
    await addTextComment(page, ".slide.active p", "persist me");
    expect(await page.locator("mark.cm-hl").count()).toBe(1);
    await page.evaluate(() => history.replaceState(null, "", location.href.replace(/#.*/, "")));
    // Reload without a slide deep link: the deck re-activates in present mode on slide 1; the
    // comment must restore in the now-hidden slide 3.
    await page.reload();
    await ready(page);
    expect(await activeId(page)).toBe("slide-00000001");
    await expect.poll(() => page.locator("mark.cm-hl").count()).toBe(1);
    expect(await page.evaluate(() => {
      const m = document.querySelector("mark.cm-hl");
      return !!(m && m.closest('[data-slide-id="slide-00000003"]'));
    })).toBe(true);
    await page.locator(".cmh-deck-mode-toggle").click();
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

  test("CMH-DECK-05a: present mode hides the comment UI; comment mode reveals it and gates keys", async ({ page }) => {
    await openDeck(page);
    const toggle = page.locator(".cmh-deck-mode-toggle");
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    // present mode by default: the comment sidebar/toolbar are hidden so the slide is full-screen
    await expect(page.locator("#sidebar")).toBeHidden();
    await expect(page.locator(".cm-toolbar")).toBeHidden();
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(await page.evaluate(
      () => document.getElementById("commentRoot").classList.contains("cmh-deck-comment-mode"))).toBe(true);
    // comment mode reveals the sidebar for reviewing
    await expect(page.locator("#sidebar")).toBeVisible();
    // navigation keys do nothing while in comment mode
    await page.keyboard.press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000001");
    // the toggle hides while the panel is open; hide the panel to reveal it, then leave comment mode
    await expect(toggle).toBeHidden();
    await page.locator("#btnCloseSidebar").click();
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator("#sidebar")).toBeHidden();
    await page.keyboard.press("ArrowRight");
    expect(await activeId(page)).toBe("slide-00000002");
  });

  test("CMH-DECK-05a: comment mode force-reveals staged slide content", async ({ page }) => {
    await openDeck(page);
    await page.evaluate(() => {
      const s = document.querySelector(".slide.active");
      const r = document.createElement("div");
      r.className = "reveal";
      r.setAttribute("style", "opacity:0;visibility:hidden");
      r.textContent = "staged";
      s.appendChild(r);
    });
    // comment mode: the force-reveal !important rule overrides the inline hidden state
    await page.locator(".cmh-deck-mode-toggle").click();
    const cs = await page.evaluate(() => {
      const c = getComputedStyle(document.querySelector(".slide.active .reveal"));
      return { opacity: c.opacity, visibility: c.visibility };
    });
    expect(cs.opacity).toBe("1");
    expect(cs.visibility).toBe("visible");
  });

  test("CMH-DECK-05c/05d: a comment restores on a hidden slide and its card jumps to that slide", async ({ page }) => {
    await openDeck(page);
    // enter comment mode (the sidebar is where comments live and are reviewed)
    await page.locator(".cmh-deck-mode-toggle").click();
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
      // enter comment mode (to reach the toolbar) and add a comment on the third slide
      await page.locator(".cmh-deck-mode-toggle").click();
      await page.evaluate(() => window.__cmhDeck.showSlideById("slide-00000003"));
      await addTextComment(page, ".slide.active p", "offline deck note");
      await page.getByRole("button", { name: "Slide overview", exact: true }).click();
      await expect(page.locator(".cmh-deck-overview")).toBeVisible();
      // the sidebar Export Offline button is reachable in comment mode (the sidebar is revealed)
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnExportOffline").click(),
      ]);
      expect(download.suggestedFilename()).toMatch(/-offline\.html$/);
      const exportedHtml = await readDownload(download);
      // deck mode survives the export; the transient present-mode body class is NOT baked in
      expect(exportedHtml).toContain('data-cmh-mode="deck"');
      expect(/<body[^>]*class="[^"]*cmh-deck-present/.test(exportedHtml)).toBe(false);
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
      // the deck runtime re-activates, starting in present mode on slide 1
      expect(await page2.evaluate(() => typeof window.__cmhDeck)).toBe("object");
      expect(await page2.evaluate(() => window.__cmhDeck.activeSlideId())).toBe("slide-00000001");
      // the comment restored on the (hidden) third slide; its card jumps there
      await expect.poll(() => page2.locator("mark.cm-hl").count()).toBe(1);
      await page2.locator(".cmh-deck-mode-toggle").click();
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

  test("CMH-DECK-15: the comment-mode toggle hides while the side panel is open (all widths)", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 800 });
    await openDeck(page);
    const toggle = page.locator(".cmh-deck-mode-toggle");
    await expect(toggle).toBeVisible();
    await toggle.click();                                 // enter comment mode -> the panel opens
    await expect(page.locator("#sidebar")).toBeVisible();
    await expect(toggle).toBeHidden();                    // hidden while the panel is open, even wide
    await page.locator("#btnCloseSidebar").click();       // hide the panel
    await expect(toggle).toBeVisible();                   // reappears so present mode stays reachable
  });

  test("CMH-DECK-15: the comments action toolbar never appears in a deck", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 800 });
    await openDeck(page);
    const toolbar = page.locator(".cm-toolbar");
    await expect(toolbar).toBeHidden();                   // present mode
    await page.locator(".cmh-deck-mode-toggle").click();  // comment mode, panel open
    await expect(page.locator("#sidebar")).toBeVisible();
    await expect(toolbar).toBeHidden();
    await page.locator("#btnCloseSidebar").click();       // comment mode, panel hidden
    await expect(toolbar).toBeHidden();                   // still hidden - only the corner icon shows
  });

  test("CMH-DECK-15: the slide stage spans the full width when the panel is hidden in comment mode", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 800 });
    await openDeck(page);
    const innerW = await page.evaluate(() => window.innerWidth);
    const viewportRight = () => page.evaluate(() =>
      Math.round(document.querySelector(".deck-viewport").getBoundingClientRect().right));
    await page.locator(".cmh-deck-mode-toggle").click();  // comment mode, panel open -> stage inset
    await expect(page.locator("#sidebar")).toBeVisible();
    expect(await viewportRight()).toBeLessThanOrEqual(innerW - 300);   // room reserved for the panel
    await page.locator("#btnCloseSidebar").click();       // hide the panel
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

  test("CMH-DECK-16: overview thumbnails force-reveal animated slide content", async ({ page }) => {
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
    const cloneOpacity = await page.locator(".cmh-deck-overview-scale [data-reveal-probe]").first()
      .evaluate((el) => getComputedStyle(el).opacity);
    expect(cloneOpacity).toBe("1");
  });
});
