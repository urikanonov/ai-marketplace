import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import { EXAMPLES, INLINE, fileUrl, ready, stageContent, stageDeck, addTextComment, openComposerFor } from "./helpers.js";

// Follow-up polish (issue #360). Mobile viewport unless noted.
const MOBILE = { width: 390, height: 844 };

// The pane slides in over 0.22s (`assets/css/00-base.css`), so anything that opens it - saving a
// first comment, above all - leaves every box inside it moving for a few frames. Measuring then
// reads a rect that is still offset to the right, which is a flake, not a layout defect. Wait for
// the transform to settle before measuring geometry inside the pane.
const paneSettled = async (page) => {
  await expect.poll(() => page.evaluate(() => {
    const t = getComputedStyle(document.querySelector(".cm-sidebar")).transform;
    return t === "none" || t === "matrix(1, 0, 0, 1, 0, 0)";
  }), { message: "the side pane finished sliding in" }).toBe(true);
};

test.describe("visual-audit follow-ups", () => {
  test.use({ viewport: MOBILE });

  test("a leading lede/card also clears the fixed toolbar on mobile (CMH-RESP-03)", async ({ page }) => {
    const staged = stageContent(`<header class="cmh-lede"><h1>Carded title</h1></header><section><h2>Body</h2><p>Text.</p></section>`,
      { key: "cmh-lede-clear", source: "lede-clear.html" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const r = await page.evaluate(() => {
        const first = document.querySelector("#commentRoot > *");
        const tb = document.querySelector(".cm-toolbar");
        return {
          tag: first ? first.tagName.toLowerCase() : null,
          marginTop: first ? parseFloat(getComputedStyle(first).marginTop) : 0,
          firstTop: first ? first.getBoundingClientRect().top : 0,
          toolbarBottom: tb ? tb.getBoundingClientRect().bottom : 0,
        };
      });
      expect(r.tag, "the leading element is the lede header").toBe("header");
      expect(r.marginTop, "the leading card reserves space under the toolbar").toBeGreaterThanOrEqual(40);
      expect(r.firstTop, "the leading card starts below the toolbar pill").toBeGreaterThanOrEqual(r.toolbarBottom - 1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("the notes fold control has a >=44px touch target on mobile (CMH-RESP-07)", async ({ page }) => {
    const staged = stageContent(`<h1>Notes touch</h1><div class="cmh-note"><button type="button" class="cmh-note-fold" id="fold"></button></div>`,
      { key: "cmh-note-touch", source: "note-touch.html" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const size = await page.evaluate(() => {
        const a = getComputedStyle(document.getElementById("fold"), "::after");
        return { w: parseFloat(a.width), h: parseFloat(a.height) };
      });
      expect(size.w, "fold tap target width >=44px").toBeGreaterThanOrEqual(44);
      expect(size.h, "fold tap target height >=44px").toBeGreaterThanOrEqual(44);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("sidebar comment-card action buttons are >=44px tall on mobile (CMH-RESP-07)", async ({ page }) => {
    await page.goto(fileUrl(INLINE));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "touch target check");
    await paneSettled(page);
    const minH = await page.evaluate(() => {
      const btns = [...document.querySelectorAll(".cm-card .meta .acts button")];
      if (!btns.length) return 0;
      return Math.min(...btns.map((b) => b.getBoundingClientRect().height));
    });
    expect(minH, "jump/edit/delete are comfortable touch targets").toBeGreaterThanOrEqual(44);
  });

  // Measures an action row's buttons against the CONTENT box of the surface that owns it (inside
  // that surface's padding and border), so a button merely painted over the surface's edge still
  // counts as clipped. The surface is derived FROM the row rather than queried independently, so a
  // document holding several cards can never measure a button against a box that does not own it.
  // Floating surfaces are re-clamped from a ResizeObserver, so settle two frames first.
  async function measureActionRow(page, rowSel, surfaceSel) {
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
    return page.evaluate(({ q, s }) => {
      const row = document.querySelector(q);
      if (!row) throw new Error("missing row " + q);
      const surface = row.closest(s);
      if (!surface) throw new Error("row " + q + " has no " + s + " ancestor");
      const cs = getComputedStyle(surface);
      const rs = getComputedStyle(row);
      const box = surface.getBoundingClientRect();
      return {
        left: box.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth),
        right: box.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth),
        top: box.top + parseFloat(cs.paddingTop) + parseFloat(cs.borderTopWidth),
        bottom: box.bottom - parseFloat(cs.paddingBottom) - parseFloat(cs.borderBottomWidth),
        vw: window.innerWidth,
        vh: window.innerHeight,
        rowGap: parseFloat(rs.rowGap),
        columnGap: parseFloat(rs.columnGap),
        boxes: Array.from(row.querySelectorAll("button")).map((b) => {
          const r = b.getBoundingClientRect();
          // A button narrower than its label either truncates an unbreakable token (which
          // `scrollWidth` sees) or WRAPS the label onto extra lines (which it does not - these
          // buttons do not carry `white-space: nowrap`). Count the label's line boxes so the
          // squeeze is caught either way.
          const range = document.createRange();
          range.selectNodeContents(b);
          return {
            act: b.getAttribute("data-act") || b.classList[0] || (b.textContent || "").trim(),
            label: (b.textContent || "").trim(),
            w: r.width, h: r.height, top: r.top, bottom: r.bottom, left: r.left, right: r.right,
            // Rounded separately: the line grouping needs a stable key, but a rounded coordinate
            // would eat the sub-pixel tolerance the containment checks rely on.
            line: Math.round(r.top),
            overflowX: b.scrollWidth - b.clientWidth,
            labelLines: range.getClientRects().length,
          };
        }),
      };
    }, { q: rowSel, s: surfaceSel });
  }

  // Every button in the row is a >=44px target that stays inside its surface, on screen, with its
  // label on one line. The rows are right-aligned, so an overflowing line spills past the START
  // edge - the containment checks, not a scrollWidth probe on the surface, are what catch that.
  // `onScreenY` is only asserted for a FIXED floating surface: the side pane's cards live in a
  // scrolling list (`.cm-sidebar .list`), where a row below the fold is reached by scrolling and is
  // not a defect - there, containment within the composer is the meaningful bound.
  // `gaps` is opted out of for a row that is not a flex container at all (the side pane's
  // single-button reply row), where a computed `row-gap` of `normal` carries no separation promise.
  function expectRowFits(info, label, count, { onScreenY = false, gaps = true } = {}) {
    expect(info.boxes.length, `${label}: the row holds all of its actions`).toBe(count);
    for (const b of info.boxes) {
      expect(b.h, `${label}: '${b.label}' height`).toBeGreaterThanOrEqual(44);
      expect(b.w, `${label}: '${b.label}' width`).toBeGreaterThanOrEqual(44);
      expect(b.left, `${label}: '${b.label}' clipped at the start edge`).toBeGreaterThanOrEqual(info.left - 0.5);
      expect(b.right, `${label}: '${b.label}' clipped at the end edge`).toBeLessThanOrEqual(info.right + 0.5);
      expect(b.top, `${label}: '${b.label}' above its surface`).toBeGreaterThanOrEqual(info.top - 0.5);
      expect(b.bottom, `${label}: '${b.label}' below its surface`).toBeLessThanOrEqual(info.bottom + 0.5);
      expect(b.left, `${label}: '${b.label}' off the left of the screen`).toBeGreaterThanOrEqual(-0.5);
      expect(b.right, `${label}: '${b.label}' off the right of the screen`).toBeLessThanOrEqual(info.vw + 0.5);
      if (onScreenY) {
        expect(b.top, `${label}: '${b.label}' off the top of the screen`).toBeGreaterThanOrEqual(-0.5);
        expect(b.bottom, `${label}: '${b.label}' off the bottom of the screen`).toBeLessThanOrEqual(info.vh + 0.5);
      }
      expect(b.overflowX, `${label}: '${b.label}' truncates its own label`).toBeLessThanOrEqual(1);
      // Exactly one line box: zero would mean an empty label (which every size check would pass
      // vacuously), more than one means the button was squeezed until its label wrapped.
      expect(b.labelLines, `${label}: '${b.label}' does not render on exactly one line`).toBe(1);
    }
    // Neither axis may close up between an enlarged Save and the Cancel beside it, which discards
    // the draft with no confirmation.
    if (gaps) {
      expect(info.rowGap, `${label}: wrapped lines keep a deliberate gap`).toBeGreaterThanOrEqual(12);
      expect(info.columnGap, `${label}: neighbours on one line keep a deliberate gap`).toBeGreaterThanOrEqual(12);
    }
  }

  // Pins WHICH buttons a row holds, by selector rather than by a class string, so an added modifier
  // class or a reordering cannot break it while a dropped or relocated button still fails.
  async function expectRowHolds(page, rowSel, acts) {
    await expect(page.locator(`${rowSel} button`)).toHaveCount(acts.length);
    for (const sel of acts) await expect(page.locator(`${rowSel} button${sel}`)).toHaveCount(1);
  }

  const rowLines = (info) => new Set(info.boxes.map((b) => b.line)).size;

  // The shipped density presets each redefine the control padding, font size and gap
  // (`assets/css/00-base.css`), so each row is measured under all three, not just the default.
  const DENSITIES = ["", "compact", "comfortable"];
  const setDensity = (page, d) => page.evaluate((v) => {
    if (v) document.body.setAttribute("data-cm-density", v);
    else document.body.removeAttribute("data-cm-density");
  }, d);

  // Measure one action row under every density preset, asserting it fits and stays on one line.
  async function expectRowFitsEveryDensity(page, rowSel, surfaceSel, label, acts, opts) {
    await expectRowHolds(page, rowSel, acts);
    for (const density of DENSITIES) {
      await setDensity(page, density);
      const info = await measureActionRow(page, rowSel, surfaceSel);
      expectRowFits(info, `${label} [density=${density || "default"}]`, acts.length, opts);
      // With the shipped labels the enlarged row still fits ONE line at 320px in every preset, so
      // the wrap below is a fallback rather than the everyday layout.
      expect(rowLines(info), `${label} [density=${density || "default"}] fits one line at 320px`).toBe(1);
    }
    await setDensity(page, "");
  }

  test("the composer action rows are >=44px touch targets on mobile (CMH-RESP-13)", async ({ page }) => {
    // 320px is the narrowest phone the repo targets, so measure the tightest case, not just 390px.
    await page.setViewportSize({ width: 320, height: 720 });
    await page.goto(fileUrl(INLINE));
    await ready(page);

    // The FLOATING composer is the surface a reviewer touches first.
    await openComposerFor(page, "#commentRoot p");
    await expect(page.locator(".cm-composer")).toHaveCount(1);
    await expectRowFitsEveryDensity(page, ".cm-composer .row", ".cm-composer", "floating composer",
      ['[data-act="cancel"]', '[data-act="save"]'], { onScreenY: true });
    // The enlarged buttons still do their job at that size.
    await page.locator(".cm-composer textarea").fill("phone touch targets");
    await page.locator('.cm-composer .row [data-act="save"]').click();
    await expect(page.locator(".cm-composer")).toHaveCount(0);

    // The side pane's REPLY composer, on the same surface a reviewer answers a thread from. The
    // surface measured against is `.cm-reply-compose`, the row's own flex-column parent, whose
    // content box is exactly the width available to the row - strictly tighter than the card, and
    // the only box that reflects the extra inset a reply's editor sits behind.
    const REPLY_ACTS = [".cm-reply-cancel", ".cm-reply-save"];
    await page.locator(".cm-card .cm-reply-btn").first().click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(1);
    await expectRowFitsEveryDensity(page, ".cm-reply-compose-actions", ".cm-reply-compose",
      "side pane reply composer", REPLY_ACTS);
    await page.locator(".cm-reply-compose textarea").fill("a reply from a phone");
    await page.locator(".cm-reply-compose .cm-reply-save").click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);
    await expect(page.locator(".cm-card .cm-reply")).toContainText("a reply from a phone");

    // The ROOT entry's EDIT composer, which reuses the same actions row.
    await page.locator('.cm-card .cm-entry-root [data-act="edit"]').first().click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(1);
    await expectRowFitsEveryDensity(page, ".cm-reply-compose-actions", ".cm-reply-compose",
      "side pane root edit composer", REPLY_ACTS);
    await page.locator(".cm-reply-compose .cm-reply-cancel").click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);

    // A REPLY's edit composer is the narrowest instance of the row: `.cm-replies` insets it by its
    // own padding and border, so it is measured too rather than left to the wrap fallback.
    await page.locator('.cm-card .cm-reply [data-act="reply-edit"]').first().click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(1);
    await expectRowFitsEveryDensity(page, ".cm-reply-compose-actions", ".cm-reply-compose",
      "side pane reply edit composer", REPLY_ACTS);
    await page.locator(".cm-reply-compose .cm-reply-save").click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);
  });

  test("an over-wide composer action row wraps instead of clipping (CMH-RESP-13)", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 720 });
    await page.goto(fileUrl(INLINE));
    await ready(page);
    // Stand in for the thing that would actually overflow these rows - a localized label set, or a
    // host document with a larger root font - by widening the buttons themselves, so the wrap
    // fallback is exercised rather than merely declared.
    await page.addStyleTag({
      content: ".cm-composer .row button, .cm-reply-compose-actions button"
        + " { padding-left: 60px !important; padding-right: 60px !important; }",
    });

    await openComposerFor(page, "#commentRoot p");
    await expect(page.locator(".cm-composer")).toHaveCount(1);
    const composer = await measureActionRow(page, ".cm-composer .row", ".cm-composer");
    expectRowFits(composer, "wrapped floating composer", 2, { onScreenY: true });
    expect(rowLines(composer), "the floating composer row wraps rather than clipping").toBeGreaterThan(1);

    // The gaps are a FLOOR in an absolute unit, so no host document's root font-size can close the
    // lines (or the neighbours) up. Pin that at BOTH ends rather than only reading the computed px
    // once at the default root: a `rem` gap passes a single default-root reading, and a plain
    // absolute value would lose the roomier density-scaled gap a large-root host already had.
    try {
      for (const rootFont of ["8px", "32px"]) {
        await page.evaluate((v) => { document.documentElement.style.fontSize = v; }, rootFont);
        const scaled = await measureActionRow(page, ".cm-composer .row", ".cm-composer");
        expect(scaled.rowGap, `row gap floor at a ${rootFont} root`).toBeGreaterThanOrEqual(12);
        expect(scaled.columnGap, `column gap floor at a ${rootFont} root`).toBeGreaterThanOrEqual(12);
        // ...and at a large root the density-scaled gap is kept rather than capped back to 12px.
        if (rootFont === "32px") {
          expect(scaled.rowGap, "a large root keeps its roomier density gap").toBeGreaterThan(composer.rowGap);
        }
      }
    } finally {
      await page.evaluate(() => { document.documentElement.style.fontSize = ""; });
    }

    await page.locator(".cm-composer textarea").fill("wrapped actions row");
    await page.locator('.cm-composer .row [data-act="save"]').click();
    await expect(page.locator(".cm-composer")).toHaveCount(0);

    await page.locator(".cm-card .cm-reply-btn").first().click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(1);
    const reply = await measureActionRow(page, ".cm-reply-compose-actions", ".cm-reply-compose");
    expectRowFits(reply, "wrapped side pane reply composer", 2);
    expect(rowLines(reply), "the reply row wraps rather than clipping").toBeGreaterThan(1);
  });

  // The side pane's remaining compact controls (issue #1146): the Reply button that OPENS the
  // now-thumb-sized reply composer, and the identity row - the `set name` link that opens the
  // editor plus the editor's own input, Save and Cancel.
  test("the side pane Reply button and identity Save/Cancel are >=44px touch targets on mobile (CMH-RESP-14)", async ({ page }) => {
    // 320px is the narrowest phone the repo targets, so measure the tightest case.
    await page.setViewportSize({ width: 320, height: 720 });
    await page.goto(fileUrl(INLINE));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "side pane touch targets");
    await paneSettled(page);

    // The door to the reply composer, measured against the card that owns it. Its row is a plain
    // block, not a flex container, so there is no gap promise to assert.
    await expectRowFitsEveryDensity(page, ".cm-card .cm-reply-row", ".cm-card",
      "side pane reply button", [".cm-reply-btn"], { gaps: false });
    // Reply's nearest neighbour is the card's DESTRUCTIVE delete action. The two boxes are apart
    // on BOTH axes today (delete is right-aligned in `.meta`, Reply starts at the card's start
    // edge a row below), so pin the LARGER separation: two boxes are only a thumb-slip apart when
    // they are close on every axis, and this way neither a re-alignment nor a collapsed vertical
    // rhythm can bring them together while the other axis still holds them apart.
    await expect(page.locator(".cm-card .meta .acts button.del")).toHaveCount(1);
    const apart = await page.evaluate(() => {
      const card = document.querySelector(".cm-card");
      const delEl = card.querySelector(".meta .acts button.del");
      const replyEl = card.querySelector(".cm-reply-btn");
      if (!delEl || !replyEl) throw new Error("card is missing its delete or reply control");
      const del = delEl.getBoundingClientRect();
      const reply = replyEl.getBoundingClientRect();
      return Math.max(
        del.left - reply.right, reply.left - del.right,
        del.top - reply.bottom, reply.top - del.bottom);
    });
    expect(apart, "Reply is kept clear of the card's delete action").toBeGreaterThanOrEqual(12);
    // ...and the enlarged button still opens the composer at that size.
    await page.locator(".cm-card .cm-reply-btn").first().click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(1);
    await page.locator(".cm-reply-compose .cm-reply-cancel").click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);

    // The identity row's two states are disjoint: `43-identity.js` hides the `set name` link while
    // the editor is open, and hides the editor otherwise. Measure each in its own state, under
    // every density, so a preset-specific regression cannot slip through.
    const identity = () => page.evaluate(() => {
      const pane = document.querySelector(".cm-sidebar");
      const own = document.getElementById("cmIdentityEdit");
      const input = document.getElementById("cmIdentityInput");
      const save = document.getElementById("btnSaveIdentity");
      const cancel = document.getElementById("btnCancelIdentity");
      if (!pane || !own || !input || !save || !cancel) throw new Error("identity editor is not present");
      const box = (el) => { const r = el.getBoundingClientRect(); return { w: r.width, h: r.height, top: r.top, left: r.left, right: r.right }; };
      const owncs = getComputedStyle(own);
      const ownBox = own.getBoundingClientRect();
      return {
        input: box(input), save: box(save), cancel: box(cancel),
        editorLeft: ownBox.left + parseFloat(owncs.paddingLeft) + parseFloat(owncs.borderLeftWidth),
        editorRight: ownBox.right - parseFloat(owncs.paddingRight) - parseFloat(owncs.borderRightWidth),
        paneOverflow: pane.scrollWidth - pane.clientWidth,
        vw: window.innerWidth,
      };
    });
    for (const density of DENSITIES) {
      const at = `[density=${density || "default"}]`;
      await setDensity(page, density);
      // Closed: the `set name` / `change` link that OPENS the editor. Its 44px target is an
      // OVERLAID pseudo-element (as CMH-RESP-06 / CMH-RESP-07 do for the checklist control and the
      // notes fold), so the visible link is deliberately left small and `::after` is what is
      // measured - growing the link itself would add ~27px to the sidebar header on every phone.
      if (await page.locator("#cmIdentityEdit").isVisible()) await page.click("#btnCancelIdentity");
      await expect(page.locator("#btnEditIdentity")).toBeVisible();
      const opener = await page.evaluate(() => {
        const btn = document.getElementById("btnEditIdentity");
        if (!btn) throw new Error("the identity edit control is not present");
        const a = getComputedStyle(btn, "::after");
        // A missing overlay computes to `auto`, which parses to NaN; report it as 0 so the
        // failure reads as a missing target rather than an unreadable one.
        return { w: parseFloat(a.width) || 0, h: parseFloat(a.height) || 0, boxH: btn.getBoundingClientRect().height };
      });
      expect(opener.h, `${at}: the 'set name' tap target height`).toBeGreaterThanOrEqual(44);
      expect(opener.w, `${at}: the 'set name' tap target width`).toBeGreaterThanOrEqual(44);
      // The overlay must stay an overlay: if the link itself ever grew to 44px the header would
      // eat the comment list on a short phone, which is the whole reason for the pseudo-element.
      expect(opener.boxH, `${at}: the 'set name' link is not grown for real`).toBeLessThan(44);

      // Open: the editor's input, Save and Cancel, which DO grow for real.
      await page.click("#btnEditIdentity");
      await expect(page.locator("#cmIdentityEdit")).toBeVisible();
      await expectRowHolds(page, "#cmIdentityEdit", [".cm-identity-save", ".cm-identity-cancel"]);
      const info = await measureActionRow(page, "#cmIdentityEdit", ".cm-identity");
      expectRowFits(info, `identity editor ${at}`, 2);
      const id = await identity();
      // The input shares the row with the enlarged pair, so it must stay a usable, tappable
      // control rather than the one sliver left in a thumb-sized row.
      expect(id.input.h, `${at}: the name input is a touch target too`).toBeGreaterThanOrEqual(44);
      expect(id.input.w, `${at}: the name input keeps a usable width beside the pair`).toBeGreaterThanOrEqual(88);
      // The whole row stays inside the editor's content box and on screen, and nothing in it
      // pushes the pane sideways.
      for (const [name, b] of [["input", id.input], ["Save", id.save], ["Cancel", id.cancel]]) {
        expect(b.left, `${at}: '${name}' clipped at the start edge`).toBeGreaterThanOrEqual(id.editorLeft - 0.5);
        expect(b.right, `${at}: '${name}' clipped at the end edge`).toBeLessThanOrEqual(id.editorRight + 0.5);
        expect(b.left, `${at}: '${name}' off the left of the screen`).toBeGreaterThanOrEqual(-0.5);
        expect(b.right, `${at}: '${name}' off the right of the screen`).toBeLessThanOrEqual(id.vw + 0.5);
      }
      expect(id.paneOverflow, `${at}: the identity row does not scroll the side pane sideways`)
        .toBeLessThanOrEqual(1);
      // With the shipped labels the whole row - input included - still fits ONE line at 320px in
      // every preset. That is what bounds the sidebar header's growth: a forced line break costs
      // roughly another 56px of header, which a landscape phone pays out of the comment list.
      const lines = new Set([id.input, id.save, id.cancel].map((b) => Math.round(b.top))).size;
      expect(lines, `${at}: the identity row fits one line at 320px`).toBe(1);
      await page.click("#btnCancelIdentity");
      await expect(page.locator("#cmIdentityEdit")).toBeHidden();
    }
    await setDensity(page, "");

    // ...and both enlarged buttons still do their job at that size.
    await page.click("#btnEditIdentity");
    await page.fill("#cmIdentityInput", "Thumbs");
    await page.click("#btnSaveIdentity");
    await expect(page.locator("#cmIdentityEdit")).toBeHidden();
    await expect(page.locator("#cmIdentityName")).toContainText("Thumbs");
  });


  // The pane slides in over 0.22s (`assets/css/00-base.css`), so anything that opens it - saving a
  // first comment, above all - leaves every box inside it moving for a few frames. Measuring then
  // reads a rect that is still offset to the right, which is a flake, not a layout defect. Wait
  // for the transform to settle before measuring geometry inside the pane.

  // The states a landscape phone's sidebar header can be in: the two TRANSIENT rows (the
  // reader-toggled search field and the identity editor) open or closed, under every density.
  const setSearchRow = async (page, want) => {
    const open = await page.evaluate(() => !document.getElementById("cmSearchRow").hidden);
    if (open !== want) await page.click("#btnSearchToggle");
    await expect(page.locator("#cmSearchRow")).toBeVisible({ visible: want });
  };
  const setIdentityEditor = async (page, want) => {
    // The editor can already be open WITHOUT focus - the nudge after a first comment opens it that
    // way (`43-identity.js`) - so always drive it through the user's own open path rather than
    // accepting whatever state it is in, or the focus this helper promises never happens.
    if (await page.locator("#cmIdentityEdit").isVisible()) await page.click("#btnCancelIdentity");
    await expect(page.locator("#cmIdentityEdit")).toBeHidden();
    if (!want) return;
    await page.click("#btnEditIdentity");
    await expect(page.locator("#cmIdentityEdit")).toBeVisible();
    // Opening focuses the input from a `setTimeout(..., 0)` (`43-identity.js`), and it is that
    // focus that scrolls the editor into the bounded header region. Measuring before it lands
    // reads a pre-scroll geometry, so wait for the focus rather than racing it.
    await expect(page.locator("#cmIdentityInput")).toBeFocused();
  };
  // The list's LAYOUT height stops meaning anything once the header has pushed it past the pane's
  // bottom edge, so measure the part that is inside BOTH the pane and the viewport - what a
  // reviewer can actually see - alongside the pane's own vertical overflow, which is where any
  // further header growth is paid once the layout box has bottomed out.
  const measureList = (page) => page.evaluate(() => {
    const pane = document.querySelector(".cm-sidebar");
    const list = document.getElementById("commentList");
    if (!pane || !list) throw new Error("the side pane or its comment list is not present");
    const head = pane.querySelector("header");
    const primary = pane.querySelector(".head-primary");
    const pr = pane.getBoundingClientRect();
    const lr = list.getBoundingClientRect();
    const top = Math.max(lr.top, pr.top, 0);
    const bottom = Math.min(lr.bottom, pr.bottom, window.innerHeight);
    return {
      layout: lr.height,
      visible: Math.max(0, bottom - top),
      paneOverflowY: pane.scrollHeight - pane.clientHeight,
      // The header can now SHRINK, so a deficit no longer shows up as pane overflow - it moves
      // INSIDE the header, where the pinned chrome would paint over (and hit-test above) the
      // cards. That is the failure `paneOverflowY` alone can no longer see.
      headOverflowY: head.scrollHeight - head.clientHeight,
      chromeOverlap: primary.getBoundingClientRect().bottom - lr.top,
    };
  });
  test("enlarging the side pane's controls does not starve the comment list on a landscape phone (CMH-RESP-14)", async ({ page }) => {
    // The worst case for the sidebar header's vertical budget: the shortest phone the repo
    // targets, in every density preset. The header is mostly pre-existing chrome, so these are
    // FLOORS on what is left for the cards rather than a promise of roominess - they are what
    // stops a later touch-target bump from taking the last of it.
    //
    // The two states get different floors on purpose. CLOSED is the state a reviewer READS in, and
    // it must not regress: the `set name` link's 44px target is an overlaid pseudo-element
    // precisely so this state costs nothing, so each density keeps the budget it had before the
    // enlargement. The floors below are the measured pre-change heights less a 10px tolerance -
    // wide enough for cross-platform font metrics, far tighter than the ~28px a real (non-overlaid)
    // 44px link would cost, which is the regression they exist to catch. The causal half of that
    // guarantee is asserted separately, by the `set name` link's own box staying under 44px.
    // EDITING is transient and costs ~28px, because `Save` / `Cancel` / the input cannot be 44px
    // targets in a row that is not 44px tall; while a reviewer is typing a name they are not
    // reading cards, and the row collapses again the moment they save or cancel.
    //
    // SEARCH is the third dimension (issue #1167). The search field is the one control in the
    // pane whose 44px target CANNOT be an overlay - it is a replaced element, which renders no
    // `::after` - so enlarging it costs real header height, which this viewport cannot afford.
    // The budget is measured three ways, because the obvious one was misleading: the comment
    // list's LAYOUT height stops shrinking once the header has pushed it past the pane's bottom
    // edge, at which point further header growth is paid in list the reviewer cannot SEE. So each
    // state pins the layout height, the VISIBLE height (the part inside both the pane and the
    // viewport), and a CEILING on the pane's own vertical overflow.
    //
    // Those ceilings used to be BOUNDED RESIDUALS: three cells started with 0-7px visible and
    // 16-47px of pane overflow, a pre-existing defect of this viewport that they RECORDED rather
    // than blessed. CMH-RESP-16 (issue #1180) fixed it by bounding the header, so they are
    // TIGHTENED here to the new guarantee rather than left as a second, weaker copy of it: every
    // cell now keeps the whole list on screen (layout == visible, at the structural
    // `min(96px, 30vh)` floor - 96px here) with zero pane overflow, in every density preset and
    // every combination of the two transient rows. The per-cell table is gone with the residual
    // it described; what is left is one number that holds everywhere.
    //
    // The `field < 44` assertion below is unchanged and remains the exact, binary guard against
    // CMH-RESP-15's gate being DELETED (as opposed to moved); the THRESHOLD itself is pinned by
    // the 359/360 boundary pass in the CMH-RESP-15 test.
    const BUDGET = { layout: 95, visible: 95, overflow: 1 };
    // One 44px control plus its overlaid tap target: below this the identity editor cannot be
    // shown, which is the same starvation one step downstream of the cards, and it is where a
    // later control bump is paid now that the list has a structural floor.
    const AUX_FLOOR = 48;
    await page.setViewportSize({ width: 640, height: 320 });
    await page.goto(fileUrl(INLINE));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "landscape budget");
    await paneSettled(page);
    // `visible` intersects the vertical axis only, so pin once that the pane is on screen
    // horizontally - otherwise a pane translated off the side would still measure fully visible.
    const onScreen = await page.evaluate(() => {
      const r = document.querySelector(".cm-sidebar").getBoundingClientRect();
      return r.right > 0 && r.left < window.innerWidth;
    });
    expect(onScreen, "the side pane is on screen before the budget is measured").toBe(true);
    for (const density of DENSITIES) {
      await setDensity(page, density);
      for (const editing of [false, true]) {
        for (const search of [false, true]) {
          await setIdentityEditor(page, editing);
          await setSearchRow(page, search);
          const budget = await measureList(page);
          const at = `[density=${density || "default"}, editing=${editing}, search=${search}]`;
          const want = BUDGET;
          expect(budget.layout, `${at}: the comment list keeps its layout height`)
            .toBeGreaterThanOrEqual(want.layout);
          expect(budget.visible, `${at}: the comment list keeps the VISIBLE height this viewport already had`)
            .toBeGreaterThanOrEqual(want.visible);
          expect(budget.paneOverflowY, `${at}: the header does not push more of the list off the pane's bottom`)
            .toBeLessThanOrEqual(want.overflow);
          // A shrinkable header can no longer report a deficit as PANE overflow - it moves inside
          // the header, where the pinned chrome would paint over the cards - so measure that too,
          // and the scroll window the transient rows are left with.
          expect(budget.headOverflowY, `${at}: the header's pinned chrome fits the header box`)
            .toBeLessThanOrEqual(1);
          expect(budget.chromeOverlap, `${at}: the pinned chrome does not paint over the comment list`)
            .toBeLessThanOrEqual(1);
          const auxH = await page.evaluate(() => document.querySelector(".cm-sidebar .head-aux").getBoundingClientRect().height);
          expect(auxH, `${at}: the header's transient rows keep a usable scroll window`)
            .toBeGreaterThanOrEqual(AUX_FLOOR);
          // The gate must stay a gate: a search field grown for real on THIS viewport is exactly
          // what would take the last of the list above. The clear button still keeps the WCAG
          // 2.5.8 AA 24x24 floor here, which costs the header nothing.
          if (search) {
            const row = await page.evaluate(() => {
              const i = document.getElementById("cmSearchInput");
              const f = i.getBoundingClientRect();
              i.value = "x";
              i.dispatchEvent(new Event("input", { bubbles: true }));
              const c = document.getElementById("cmSearchClear").getBoundingClientRect();
              i.value = "";
              i.dispatchEvent(new Event("input", { bubbles: true }));
              return { field: f.height, clearW: c.width, clearH: c.height };
            });
            expect(row.field, `${at}: the search field is not grown on a short viewport`).toBeLessThan(44);
            expect(row.clearW, `${at}: the clear button keeps the AA 24px floor`).toBeGreaterThanOrEqual(24);
            expect(row.clearH, `${at}: the clear button keeps the AA 24px floor`).toBeGreaterThanOrEqual(24);
          }
        }
      }
      // The menus are overlays, so their 44px items cost this viewport no header height - but the
      // `max-height: min(60vh, 22rem, calc(100vh - 12rem))` cap is only ~128px here, so they were
      // ALREADY scrollers before the enlargement. What has to hold is that every item stays
      // reachable by scrolling and the menu stays on screen, not that it never scrolls.
      for (const [toggle, menu, count] of [
        ["#btnSidebarExportMenu", "#sidebarExportMenu", 5],
        ["#btnMoreMenu", "#sidebarMoreMenu", 5],
      ]) {
        await page.evaluate((t) => {
          const b = document.querySelector(t);
          if (b.getAttribute("aria-expanded") !== "true") b.click();
        }, toggle);
        await expect(page.locator(menu)).toBeVisible();
        const reach = await page.evaluate((m) => {
          const el = document.querySelector(m);
          const items = [...el.querySelectorAll("button")];
          let worst = Infinity;
          for (const b of items) {
            b.scrollIntoView({ block: "nearest" });
            const box = el.getBoundingClientRect();
            const r = b.getBoundingClientRect();
            // The whole item must be inside the menu box, not just 44px of it - a taller item
            // could otherwise stay clipped and still pass.
            worst = Math.min(worst, Math.min(r.bottom, box.bottom) - Math.max(r.top, box.top) - r.height);
          }
          const box = el.getBoundingClientRect();
          return { items: items.length, worst, top: box.top, bottom: box.bottom, vh: window.innerHeight };
        }, menu);
        const at = `[density=${density || "default"}] ${menu}`;
        expect(reach.items, `${at}: holds all of its items`).toBe(count);
        expect(reach.worst, `${at}: every item can be scrolled FULLY into the menu`).toBeGreaterThanOrEqual(-0.5);
        expect(reach.top, `${at}: stays on screen at the top`).toBeGreaterThanOrEqual(-0.5);
        expect(reach.bottom, `${at}: stays on screen at the bottom`).toBeLessThanOrEqual(reach.vh + 0.5);
        await page.evaluate((t) => {
          const b = document.querySelector(t);
          if (b.getAttribute("aria-expanded") === "true") b.click();
        }, toggle);
      }
    }
    await setDensity(page, "");

    // The gate's THRESHOLD is only defensible if the viewport at it can afford the grown row. That
    // is the measurement the threshold was chosen from, so pin it here rather than cite it: same
    // state machine, one viewport taller than the gate, with the search row open. This used to
    // carry a per-density residual table too - five of six cells held the whole list and the sixth
    // (`comfortable`, both transient rows open) still overflowed by 14px - and CMH-RESP-16
    // tightens it the same way: with the header bounded, ALL six cells hold the whole list with no
    // pane overflow at 640x360 as well, so the residual and the table describing it are gone.
    const THRESHOLD = { visible: 95, overflow: 1 };
    await page.setViewportSize({ width: 640, height: 360 });
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
    for (const density of DENSITIES) {
      await setDensity(page, density);
      for (const editing of [false, true]) {
        await setIdentityEditor(page, editing);
        await setSearchRow(page, true);
        const at = `[640x360, density=${density || "default"}, editing=${editing}]`;
        const want = THRESHOLD;
        const budget = await measureList(page);
        const field = await page.evaluate(() => document.getElementById("cmSearchInput").getBoundingClientRect().height);
        expect(field, `${at}: the field is grown at the gate's own threshold`).toBeGreaterThanOrEqual(44);
        expect(budget.visible, `${at}: the comment list is affordable at the threshold`).toBeGreaterThanOrEqual(want.visible);
        expect(budget.paneOverflowY, `${at}: the header does not push the list off the pane's bottom`).toBeLessThanOrEqual(want.overflow);
        expect(budget.headOverflowY, `${at}: the header's pinned chrome fits the header box`).toBeLessThanOrEqual(1);
      }
    }
    await setSearchRow(page, false);
    await setIdentityEditor(page, false);
    await setDensity(page, "");
  });

  // The side pane's LAST compact controls (issue #1167): the search row, the two dropdown menus'
  // items, and the card `edit` action's WIDTH. CMH-RESP-14 deliberately did not claim the pane was
  // finished; this is the rest of it.
  test("the side pane search row, dropdown menu items and card edit action are >=44px touch targets on mobile (CMH-RESP-15)", async ({ page }) => {
    // 320x720 is the narrowest phone the repo targets, and it is tall enough to afford the search
    // row's real growth (see the landscape guard below for the short-viewport bound).
    await page.setViewportSize({ width: 320, height: 720 });
    await page.goto(fileUrl(INLINE));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "side pane touch targets 1167");
    await paneSettled(page);
    // A reply gives the card its second actions row, so `reply-edit` / `reply-del` are measured
    // beside the root card's jump / edit / delete rather than assumed to match them.
    await page.locator(".cm-card .cm-reply-btn").first().click();
    await page.locator(".cm-reply-compose textarea").fill("a reply");
    await page.locator(".cm-reply-compose .cm-reply-save").click();
    await expect(page.locator('.cm-card [data-act="reply-edit"]')).toHaveCount(1);

    const measure = (sel) => page.evaluate((q) => {
      const els = [...document.querySelectorAll(q)];
      return els.map((el) => {
        const r = el.getBoundingClientRect();
        return { l: (el.getAttribute("data-act") || el.textContent || el.id || "").trim(), w: r.width, h: r.height };
      });
    }, sel);

    for (const density of DENSITIES) {
      const at = `[density=${density || "default"}]`;
      await setDensity(page, density);

      // --- the search row -------------------------------------------------------------------
      // The row is reader-toggled (51-comment-search.js), and the clear (X) button only appears
      // once there is a query, so drive both into view rather than measuring a hidden box.
      await page.evaluate(() => {
        const row = document.querySelector(".head-search");
        if (row && row.hidden) document.getElementById("btnSearchToggle").click();
      });
      await expect(page.locator("#cmSearchRow")).toBeVisible();
      await page.fill("#cmSearchInput", "side");
      await expect(page.locator("#cmSearchClear")).toBeVisible();
      const search = await page.evaluate(() => {
        const row = document.querySelector(".head-search");
        const pane = document.querySelector(".cm-sidebar");
        const input = document.getElementById("cmSearchInput");
        const clear = document.getElementById("cmSearchClear");
        const cs = getComputedStyle(row);
        const rb = row.getBoundingClientRect();
        const box = (el) => { const r = el.getBoundingClientRect(); return { w: r.width, h: r.height, left: r.left, right: r.right }; };
        return {
          input: box(input), clear: box(clear),
          rowLeft: rb.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth),
          rowRight: rb.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth),
          paneOverflow: pane.scrollWidth - pane.clientWidth,
          vw: window.innerWidth,
        };
      });
      expect(search.input.h, `${at}: the search field height`).toBeGreaterThanOrEqual(44);
      expect(search.clear.h, `${at}: the search clear height`).toBeGreaterThanOrEqual(44);
      expect(search.clear.w, `${at}: the search clear width`).toBeGreaterThanOrEqual(44);
      // The clear button takes its width out of the field, which shares the row with it, so the
      // field must stay a usable place to type rather than the one sliver left in the row.
      expect(search.input.w, `${at}: the search field keeps a usable width`).toBeGreaterThanOrEqual(88);
      for (const [name, b] of [["field", search.input], ["clear", search.clear]]) {
        expect(b.left, `${at}: the search ${name} is clipped at the start edge`).toBeGreaterThanOrEqual(search.rowLeft - 0.5);
        expect(b.right, `${at}: the search ${name} is clipped at the end edge`).toBeLessThanOrEqual(search.rowRight + 0.5);
        expect(b.right, `${at}: the search ${name} is off the right of the screen`).toBeLessThanOrEqual(search.vw + 0.5);
      }
      expect(search.paneOverflow, `${at}: the search row does not scroll the side pane sideways`).toBeLessThanOrEqual(1);

      // --- the two dropdown menus ------------------------------------------------------------
      // Both TOGGLES are already 44px (CMH-SIDE-12); these are the items behind them, one of
      // which is `Clear all comments`. The menus are absolutely-positioned overlays, so this
      // costs the header nothing - the bound that matters is that a portrait phone does not turn
      // them into scrollers.
      for (const [toggle, menu, count] of [
        ["#btnSidebarExportMenu", "#sidebarExportMenu", 5],
        ["#btnMoreMenu", "#sidebarMoreMenu", 5],
      ]) {
        await page.evaluate((t) => {
          const b = document.querySelector(t);
          if (b.getAttribute("aria-expanded") !== "true") b.click();
        }, toggle);
        await expect(page.locator(menu)).toBeVisible();
        const items = await measure(`${menu} button`);
        expect(items.length, `${at}: ${menu} holds all of its items`).toBe(count);
        for (const b of items) {
          expect(b.h, `${at}: ${menu} item '${b.l}' height`).toBeGreaterThanOrEqual(44);
        }
        const scroll = await page.evaluate((m) => {
          const el = document.querySelector(m);
          return { overflow: el.scrollHeight - el.clientHeight, clientH: el.clientHeight, bottom: el.getBoundingClientRect().bottom, vh: window.innerHeight };
        }, menu);
        // A `display: none` menu measures 0 everywhere, which would make the two bounds below pass
        // vacuously; pin that it is actually laid out.
        expect(scroll.clientH, `${at}: ${menu} is actually laid out`).toBeGreaterThan(44);
        expect(scroll.overflow, `${at}: ${menu} is not a scroller on a portrait phone`).toBeLessThanOrEqual(1);
        expect(scroll.bottom, `${at}: ${menu} stays on screen`).toBeLessThanOrEqual(scroll.vh + 0.5);
        await page.evaluate((t) => {
          const b = document.querySelector(t);
          if (b.getAttribute("aria-expanded") === "true") b.click();
        }, toggle);
      }

      // --- the card action rows ---------------------------------------------------------------
      // Height was already 44px (CMH-RESP-07); the WIDTH was 40-43px, so the pane shipped two
      // different definitions of the same target. Both axes now, on the root card and the reply.
      // The query is cleared FIRST: a filtered-out card is `display: none !important`, so measuring
      // under a live filter would read 0x0 boxes and fail as a phantom layout bug.
      await page.locator("#cmSearchClear").click();
      await expect(page.locator("#cmSearchInput")).toHaveValue("");
      await expect(page.locator(".cm-card.cm-hidden")).toHaveCount(0);
      const acts = await measure(".cm-card:not(.cm-hidden) .meta .acts button");
      expect(acts.length, `${at}: the card rows hold exactly their actions`).toBe(5);
      for (const b of acts) {
        expect(b.h, `${at}: card action '${b.l}' height`).toBeGreaterThanOrEqual(44);
        expect(b.w, `${at}: card action '${b.l}' width`).toBeGreaterThanOrEqual(44);
      }
      // ...and the row still fits its card when the OTHER half of `.meta` is long. The stamp is
      // replaced by an UNBREAKABLE token grown until it no longer fits beside the actions, because
      // a breakable localized string just wraps inside its own flex item and would never exercise
      // the rule this covers. What is asserted is the wrap itself (the actions move to a line of
      // their own), that they stay END-aligned there rather than jumping to the start edge, and
      // that nothing overflows.
      const wrapped = await page.evaluate(() => {
        const card = document.querySelector(".cm-card:not(.cm-hidden)");
        const metas = [...card.querySelectorAll(".meta")];
        const stamps = metas.map((m) => m.querySelector(":scope > *:not(.acts)"));
        if (stamps.some((s) => !s)) throw new Error("a .meta row has no timestamp element");
        const before = stamps.map((s) => s.innerHTML);
        try {
          return metas.map((m, i) => {
            const s = stamps[i];
            const acts = m.querySelector(".acts");
            s.style.whiteSpace = "nowrap";
            // Grow the token until the actions actually MOVE to a line of their own, rather than
            // until some computed width threshold is crossed - the threshold depends on font
            // metrics and on how much room the row had, and on a narrow reply row it can be
            // satisfied while both halves still share one line. Stop growing once the stamp fills
            // the row's content box, since past that even a wrapped line would overflow.
            let dropped = false;
            for (let n = 8; n < 400; n += 4) {
              s.textContent = "0".repeat(n);
              const st = s.getBoundingClientRect();
              if (acts.getBoundingClientRect().top >= st.bottom - 0.5) { dropped = true; break; }
              if (st.width >= m.clientWidth) break;
            }
            const mb = m.getBoundingClientRect();
            const ab = acts.getBoundingClientRect();
            return {
              dropped,
              endGap: mb.right - ab.right,
              metaOverflow: m.scrollWidth - m.clientWidth,
              cardOverflow: card.scrollWidth - card.clientWidth,
              pastRight: Math.max(0, ...[...acts.querySelectorAll("button")].map((b) => b.getBoundingClientRect().right - mb.right)),
            };
          });
        } finally {
          stamps.forEach((s, i) => { s.style.whiteSpace = ""; s.innerHTML = before[i]; });
        }
      });
      for (const [i, w] of wrapped.entries()) {
        expect(w.dropped, `${at}: meta row ${i} drops its actions onto their own line`).toBe(true);
        expect(w.endGap, `${at}: meta row ${i} keeps its wrapped actions end-aligned`).toBeLessThanOrEqual(1);
        expect(w.metaOverflow, `${at}: meta row ${i} does not overflow`).toBeLessThanOrEqual(1);
        expect(w.cardOverflow, `${at}: the card does not overflow`).toBeLessThanOrEqual(1);
        expect(w.pastRight, `${at}: no action is pushed past the meta row's end edge`).toBeLessThanOrEqual(1);
      }
    }
    await setDensity(page, "");

    // The search row's target is gated on viewport HEIGHT, and a media query reads the LAYOUT
    // viewport - which this layer's own doctrine (assets/js/04-viewport.js) says is not what the
    // reader sees. A soft keyboard does not move it under the default `interactive-widget`
    // behaviour, but split-screen, a rotation, heavy browser zoom, or a host document that opts
    // into `interactive-widget=resizes-content` can cross the threshold live. Pin the THRESHOLD
    // itself, not just the gate's existence: 359 and 360 straddle it, so moving it anywhere else
    // fails here. Below it both controls keep the WCAG 2.5.8 AA 24px floor.
    for (const [h, want] of [[720, 44], [360, 44], [359, 24], [340, 24]]) {
      await page.setViewportSize({ width: 320, height: h });
      await expect(page.locator("#cmSearchRow")).toBeVisible();
      await page.fill("#cmSearchInput", "side");
      await expect(page.locator("#cmSearchClear")).toBeVisible();
      const row = await page.evaluate(() => {
        const pane = document.querySelector(".cm-sidebar");
        const c = document.getElementById("cmSearchClear").getBoundingClientRect();
        return {
          field: document.getElementById("cmSearchInput").getBoundingClientRect().height,
          clearW: c.width, clearH: c.height,
          paneOverflow: pane.scrollWidth - pane.clientWidth,
        };
      });
      const at = `[320x${h}]`;
      expect(row.field, `${at}: search field height`).toBeGreaterThanOrEqual(want);
      expect(row.clearW, `${at}: clear button width`).toBeGreaterThanOrEqual(want);
      expect(row.clearH, `${at}: clear button height`).toBeGreaterThanOrEqual(want);
      if (want === 24) {
        // Below the gate the AA floor is all that is promised - pin that the FULL target is
        // genuinely off, so a threshold moved above 360 cannot pass here.
        expect(row.field, `${at}: the full target is off below the gate`).toBeLessThan(44);
      }
      expect(row.paneOverflow, `${at}: the row does not scroll the pane sideways`).toBeLessThanOrEqual(1);
    }

    // A host document with a large root font scales the density variables but not an absolute
    // floor, so the floors are `min-*`: the control must keep the LARGER of the two, never be
    // shrunk to 44px at the very breakpoint meant to enlarge it.
    await page.setViewportSize({ width: 320, height: 720 });
    const bigRoot = await page.evaluate(() => {
      const root = document.documentElement;
      const had = root.style.fontSize;
      root.style.fontSize = "32px";
      const c = document.getElementById("cmSearchClear").getBoundingClientRect();
      const out = { w: c.width, h: c.height };
      root.style.fontSize = had;
      return out;
    });
    expect(bigRoot.w, "a large-root host keeps a clear button wider than the floor").toBeGreaterThan(44);
    expect(bigRoot.h, "a large-root host keeps a clear button taller than the floor").toBeGreaterThan(44);

    // The enlarged targets must stay INSIDE the phone breakpoint: on a desktop viewport the same
    // controls keep their compact size, so a rule that escaped its media query fails here. The
    // query is cleared first, since a filtered-out card measures 0 and would pass `< 44` vacuously.
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.locator("#cmSearchClear").click();
    await expect(page.locator(".cm-card.cm-hidden")).toHaveCount(0);
    const desktop = await page.evaluate(() => {
      const editEl = document.querySelector('.cm-card:not(.cm-hidden) .meta .acts [data-act="edit"]');
      if (!editEl) throw new Error("the card edit action is not present");
      return {
        field: document.getElementById("cmSearchInput").getBoundingClientRect().height,
        edit: editEl.getBoundingClientRect().width,
      };
    });
    expect(desktop.field, "the desktop search field is measured, not hidden").toBeGreaterThan(0);
    expect(desktop.edit, "the desktop card edit action is measured, not hidden").toBeGreaterThan(0);
    expect(desktop.field, "the desktop search field keeps its compact height").toBeLessThan(44);
    expect(desktop.edit, "the desktop card edit action keeps its compact width").toBeLessThan(44);
  });

  // Issue #1180: the header's own rows - not any one control - were what pushed the list off the
  // bottom, so this guard walks the whole state space rather than the one state CMH-RESP-14 reads.
  test("the side pane header never pushes the comment list off the bottom on a landscape phone (CMH-RESP-16)", async ({ page }) => {
    // A rendered card measures ~250px at this viewport, taller than the whole 320px pane, so no
    // header can promise "a whole card" (the issue's wording); what IS promised is a list that
    // stays a usable scroll window - a card's meta line plus the start of its body. The CSS floor
    // is `min(96px, 30vh)`, exactly 96px here, and the assertion sits just under it so genuine
    // cross-platform font metrics cannot flake it while a real regression still fails.
    const VISIBLE_FLOOR = 95;
    await page.setViewportSize({ width: 640, height: 320 });
    await page.goto(fileUrl(INLINE));
    await ready(page);
    // The EMPTY list is the first-time reviewer's state and the one with the least reason to be
    // squeezed, so measure it before there is a card to measure. Nothing has opened the pane yet,
    // so open it explicitly - it is translated off-screen until then.
    if (!(await page.evaluate(() => document.body.classList.contains("sidebar-open")))) {
      await page.click("#btnToggleSidebar");
    }
    await expect(page.locator("body")).toHaveClass(/sidebar-open/);
    await expect(page.locator("#commentList .cm-empty")).toBeVisible();
    for (const density of DENSITIES) {
      await setDensity(page, density);
      for (const search of [false, true]) {
        await setSearchRow(page, search);
        for (const editing of [false, true]) {
          await setIdentityEditor(page, editing);
          const m = await measureList(page);
          const at = `[empty, density=${density || "default"}, search=${search}, editing=${editing}]`;
          expect(m.visible, `${at}: the empty comment list keeps a visible window`).toBeGreaterThanOrEqual(VISIBLE_FLOOR);
          expect(m.paneOverflowY, `${at}: the side pane does not overflow vertically`).toBeLessThanOrEqual(1);
          expect(m.headOverflowY, `${at}: the header's pinned chrome fits the header box`).toBeLessThanOrEqual(1);
          expect(m.chromeOverlap, `${at}: the pinned chrome does not paint over the comment list`).toBeLessThanOrEqual(1);
        }
      }
    }
    await setSearchRow(page, false);
    await setIdentityEditor(page, false);
    await setDensity(page, "");

    await addTextComment(page, "#commentRoot p", "landscape header budget");
    await paneSettled(page);
    for (const density of DENSITIES) {
      await setDensity(page, density);
      for (const search of [false, true]) {
        await setSearchRow(page, search);
        for (const editing of [false, true]) {
          await setIdentityEditor(page, editing);
          const at = `[density=${density || "default"}, search=${search}, editing=${editing}]`;
          const m = await measureList(page);
          expect(m.visible, `${at}: the comment list keeps a visible scroll window`)
            .toBeGreaterThanOrEqual(VISIBLE_FLOOR);
          // The visible part is the WHOLE list box: nothing of it is below the fold, which is the
          // failure mode - a non-zero layout height that a reviewer cannot see any of.
          expect(m.layout - m.visible, `${at}: no part of the comment list is below the fold`)
            .toBeLessThanOrEqual(1);
          expect(m.paneOverflowY, `${at}: the side pane does not overflow vertically`)
            .toBeLessThanOrEqual(1);
          // A shrinkable header moves the OLD failure somewhere the pane's own overflow can no
          // longer see it: the pinned chrome would spill out of the header box and paint over -
          // and hit-test above - the cards, with `paneOverflowY` still reading 0.
          expect(m.headOverflowY, `${at}: the header's pinned chrome fits the header box`)
            .toBeLessThanOrEqual(1);
          expect(m.chromeOverlap, `${at}: the pinned chrome does not paint over the comment list`)
            .toBeLessThanOrEqual(1);
        }
      }
    }
    await setSearchRow(page, false);
    await setIdentityEditor(page, false);
    await setDensity(page, "");

    // Shorter than the viewport this targets, the floors must YIELD rather than let the pinned
    // chrome overrun the list: the list's `min(96px, 30vh)` cap, and the region carrying no floor
    // of its own, are what make that graceful. Measured, the full containment guarantee holds all
    // the way down to 640x240 - well under any device, and less than the pinned chrome plus one
    // control - so it is asserted rather than merely bounded. What is NOT promised below 320px is
    // the 96px window itself; it scales with the viewport instead, which is what the `30vh` cap is.
    for (const height of [280, 240]) {
      await page.setViewportSize({ width: 640, height });
      const short = await measureList(page);
      const at = `[640x${height}]`;
      expect(short.visible, `${at}: the window scales with the viewport instead of vanishing`)
        .toBeGreaterThanOrEqual(height * 0.3 - 1);
      expect(short.chromeOverlap, `${at}: the pinned chrome does not paint over the comment list`).toBeLessThanOrEqual(1);
      expect(short.headOverflowY, `${at}: the header still fits its box`).toBeLessThanOrEqual(1);
      expect(short.paneOverflowY, `${at}: the side pane does not overflow vertically`).toBeLessThanOrEqual(1);
    }
    await page.setViewportSize({ width: 640, height: 320 });
  });

  // The second half of the CMH-RESP-16 guarantee: a bounded region is only worth anything if what
  // you open in it is reachable. Split from the state sweep above because the two together run
  // past the per-test budget, and the repo splits a slow test rather than widening the timeout.
  test("the side pane header's bounded region stays reachable on a landscape phone (CMH-RESP-16)", async ({ page }) => {
    await page.setViewportSize({ width: 640, height: 320 });
    await page.goto(fileUrl(INLINE));
    await ready(page);

    const revealed = (page, sel) => page.evaluate((s) => {
      const aux = document.querySelector(".head-aux");
      const el = document.querySelector(s);
      const ar = aux.getBoundingClientRect();
      const er = el.getBoundingClientRect();
      return {
        h: er.height,
        insideTop: er.top - ar.top,
        insideBottom: ar.bottom - er.bottom,
        onScreenTop: er.top,
        onScreenBottom: window.innerHeight - er.bottom,
      };
    }, sel);

    // The identity NUDGE is the FIRST way a reviewer meets the editor: saving a first comment opens
    // it for them, and deliberately does NOT focus it (`43-identity.js`). Focus is what would
    // otherwise scroll it into the bounded region, so this is the one path that has to scroll
    // itself - and it is the path a reviewer actually walks. It runs FIRST here because the nudge
    // fires only once. Saving the comment is also what OPENS the pane, so the nudge fires while the
    // pane is still translated off screen - the closed-pane path.
    expect(await page.evaluate(() => document.body.classList.contains("sidebar-open")),
      "the pane is closed when the nudge fires").toBe(false);
    await addTextComment(page, "#commentRoot p", "landscape header reach");
    await expect(page.locator("#cmIdentityEdit")).toBeVisible();
    await paneSettled(page);
    let nudged = await revealed(page, "#cmIdentityInput");
    expect(nudged.h, "the nudged identity editor is rendered").toBeGreaterThan(0);
    expect(nudged.insideTop, "an unfocused (nudged) identity editor is scrolled into view").toBeGreaterThanOrEqual(-0.5);
    expect(nudged.insideBottom, "an unfocused (nudged) identity editor is scrolled into view").toBeGreaterThanOrEqual(-0.5);
    expect(nudged.onScreenTop, "an unfocused (nudged) identity editor is on screen").toBeGreaterThanOrEqual(-0.5);
    expect(nudged.onScreenBottom, "an unfocused (nudged) identity editor is on screen").toBeGreaterThanOrEqual(-0.5);

    // That reveal is CLAMPED to the region's own scrollTop rather than delegated to
    // `scrollIntoView`, which walks every scrollable ancestor - the pane is `position: fixed` and
    // can be translated fully off screen when the nudge fires, and a reveal that moved the DOCUMENT
    // to chase it would be a bigger side effect than the one it fixes. Put the region back to the
    // top with the document genuinely scrolled, re-open the editor, and pin that ONLY the region
    // moved.
    await setSearchRow(page, true);
    await setIdentityEditor(page, false);
    const clamped = await page.evaluate(async () => {
      const aux = document.querySelector(".cm-sidebar .head-aux");
      document.body.style.minHeight = "4000px";
      document.body.style.minWidth = "4000px";
      window.scrollTo(300, 400);
      aux.scrollTop = 0;
      const before = { x: window.scrollX, y: window.scrollY, aux: aux.scrollTop };
      document.getElementById("btnEditIdentity").click();
      await new Promise((r) => requestAnimationFrame(r));
      const after = { x: window.scrollX, y: window.scrollY, aux: aux.scrollTop };
      document.body.style.minHeight = "";
      document.body.style.minWidth = "";
      window.scrollTo(0, 0);
      return { before, after };
    });
    expect(clamped.before.y, "the document is genuinely scrolled before the reveal").toBeGreaterThan(0);
    expect(clamped.after.y, "revealing the editor does not scroll the document vertically").toBe(clamped.before.y);
    expect(clamped.after.x, "revealing the editor does not scroll the document horizontally").toBe(clamped.before.x);
    expect(clamped.after.aux, "the reveal scrolls the bounded region itself").toBeGreaterThan(clamped.before.aux);
    nudged = await revealed(page, "#cmIdentityInput");
    expect(nudged.insideBottom, "the editor stays inside the region with the search row open").toBeGreaterThanOrEqual(-0.5);
    await setIdentityEditor(page, false);
    await setSearchRow(page, false);

    // A bounded region is only usable if what you OPEN in it comes into view. Both transient rows
    // focus their own field on open, so the browser scrolls `.head-aux` to it; pin that the field
    // lands fully inside both the scroll window and the viewport, in every preset.
    for (const density of DENSITIES) {
      await setDensity(page, density);
      const at = `[density=${density || "default"}]`;
      for (const [open, field, close] of [
        [() => setSearchRow(page, true), "#cmSearchInput", () => setSearchRow(page, false)],
        [() => setIdentityEditor(page, true), "#cmIdentityInput", () => setIdentityEditor(page, false)],
      ]) {
        await open();
        const r = await revealed(page, field);
        expect(r.h, `${at}: ${field} is rendered`).toBeGreaterThan(0);
        expect(r.insideTop, `${at}: ${field} is scrolled into the header's scroll window`).toBeGreaterThanOrEqual(-0.5);
        expect(r.insideBottom, `${at}: ${field} is scrolled into the header's scroll window`).toBeGreaterThanOrEqual(-0.5);
        expect(r.onScreenTop, `${at}: ${field} is on screen`).toBeGreaterThanOrEqual(-0.5);
        expect(r.onScreenBottom, `${at}: ${field} is on screen`).toBeGreaterThanOrEqual(-0.5);
        await close();
      }
    }
    await setDensity(page, "");

    // The region takes a keyboard tab stop and a name only WHILE it actually scrolls, so a sighted
    // keyboard-only reviewer can reach the non-focusable `Generated on` / `Last comment` lines
    // without a dead tab stop appearing on a viewport where nothing scrolls. The stamping is
    // observer-driven, so assert it with the auto-retrying locator matchers rather than a single
    // synchronous read that can land before the observer has run.
    const aux = page.locator(".cm-sidebar .head-aux");
    await setSearchRow(page, true);
    expect(await page.evaluate(() => {
      const el = document.querySelector(".cm-sidebar .head-aux");
      return el.scrollHeight > el.clientHeight + 1;
    }), "the bounded region scrolls on a landscape phone").toBe(true);
    await expect(aux, "a scrolling region is keyboard reachable").toHaveAttribute("tabindex", "0");
    await expect(aux, "a scrolling region is a named group").toHaveAttribute("role", "group");
    await expect(aux, "a scrolling region carries an accessible name").toHaveAttribute("aria-label", /\S/);
    // A tab stop the layer adds must land visibly: the UA ring is what `assets/css/80-focus.css`
    // exists to replace, and an OUTSET ring on this box is clipped by the pane edge, so it takes
    // the same inset accent ring the comment list does. The ring is `:focus-visible`, which a
    // PROGRAMMATIC focus does not match on a non-input, so walk into it with the keyboard.
    await page.locator("#cmSearchInput").focus();
    await page.keyboard.press("Shift+Tab");
    const ring = await page.evaluate(() => {
      const el = document.querySelector(".cm-sidebar .head-aux");
      const cs = getComputedStyle(el);
      return {
        focused: document.activeElement === el,
        matches: el.matches(":focus-visible"),
        style: cs.outlineStyle, width: cs.outlineWidth, offset: cs.outlineOffset,
      };
    });
    expect(ring.focused, "Shift+Tab from the search field reaches the scrolling region").toBe(true);
    expect(ring.matches, "the region's focus is a visible one").toBe(true);
    expect(ring.style, "the region's focus ring is themed, not the UA default").toBe("solid");
    expect(parseFloat(ring.width), "the region's focus ring is visible").toBeGreaterThanOrEqual(2);
    expect(parseFloat(ring.offset), "the region's focus ring is inset so the pane edge cannot clip it")
      .toBeLessThanOrEqual(0);
    await setSearchRow(page, false);

    // A long localized metadata line must WRAP rather than turn the header into a horizontal
    // scroller: `overflow-y: auto` computes the inline axis to `auto` on its own, and a scrollbar
    // there would eat the vertical budget this region exists to protect. Two things carry that -
    // the wrap, which stops the overflow existing, and the pinned `hidden`, which is what a browser
    // falls back to safely - so pin both.
    const wide = await page.evaluate(() => {
      const el = document.getElementById("cmGenerated");
      const before = el.textContent;
      el.textContent = "Erstellt am Donnerstag, 6. August 2026 um 14:32:07 Mitteleuropaeische Sommerzeit "
        + "(automatisch erzeugt durch den Pruefbericht-Generator, Revision 2026-08-06T14:32:07Z)";
      const aux2 = document.querySelector(".cm-sidebar .head-aux");
      const pane = document.querySelector(".cm-sidebar");
      const out = {
        auxX: aux2.scrollWidth - aux2.clientWidth,
        paneX: pane.scrollWidth - pane.clientWidth,
        overflowX: getComputedStyle(aux2).overflowX,
      };
      el.textContent = before;
      return out;
    });
    expect(wide.overflowX, "the region pins its inline axis rather than inheriting a scroller").toBe("hidden");
    expect(wide.auxX, "a long metadata line wraps instead of scrolling the header sideways").toBeLessThanOrEqual(1);
    expect(wide.paneX, "a long metadata line does not scroll the pane sideways either").toBeLessThanOrEqual(1);

    // On a tall viewport it must NOT scroll at all - neither a leftover tab stop nor the 44px
    // identity tap target's overhang may turn the header into a scroller with nothing to scroll.
    await page.setViewportSize({ width: 400, height: 900 });
    await expect(aux, "no dead tab stop where nothing scrolls").not.toHaveAttribute("tabindex", /.*/);
    await expect(aux, "no leftover accessible name where nothing scrolls").not.toHaveAttribute("aria-label", /.*/);
    expect(await page.evaluate(() => {
      const el = document.querySelector(".cm-sidebar .head-aux");
      return el.scrollHeight - el.clientHeight;
    }), "the region does not scroll where the header has room").toBeLessThanOrEqual(1);
    await page.setViewportSize({ width: 640, height: 320 });

    // The obvious way to bound a header - scrolling the header itself - would CLIP the Export and
    // More menus, which are absolutely positioned inside it. Pin that they are not: each opens
    // fully on screen, anchored to its own toggle, with every item reachable.
    for (const [toggle, menu, item] of [
      ["#btnSidebarExportMenu", "#sidebarExportMenu", "#btnPrint"],
      ["#btnMoreMenu", "#sidebarMoreMenu", "#btnClearAll"],
    ]) {
      await page.click(toggle);
      await expect(page.locator(menu)).toBeVisible();
      const geo = await page.evaluate(([t, m]) => {
        const tog = document.querySelector(t);
        const el = document.querySelector(m);
        const tr = tog.getBoundingClientRect();
        const mr = el.getBoundingClientRect();
        return {
          top: mr.top, bottom: mr.bottom, left: mr.left, right: mr.right,
          w: mr.width, h: mr.height,
          vw: window.innerWidth, vh: window.innerHeight,
          // Anchored to its toggle: the menu opens directly under it and shares an edge with it.
          below: mr.top - tr.bottom,
          overlapsX: Math.min(mr.right, tr.right) - Math.max(mr.left, tr.left),
          clipped: (() => {
            for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
              const cs = getComputedStyle(a);
              if (cs.overflowY !== "visible" || cs.overflowX !== "visible") return a.className || a.tagName;
            }
            return "";
          })(),
        };
      }, [toggle, menu]);
      expect(geo.clipped, `${menu} has no clipping ancestor inside the pane`).toBe("");
      expect(geo.w, `${menu} is rendered`).toBeGreaterThan(0);
      expect(geo.h, `${menu} is rendered`).toBeGreaterThan(0);
      expect(geo.top, `${menu} starts on screen`).toBeGreaterThanOrEqual(-0.5);
      expect(geo.bottom, `${menu} ends on screen`).toBeLessThanOrEqual(geo.vh + 0.5);
      expect(geo.left, `${menu} starts inside the viewport`).toBeGreaterThanOrEqual(-0.5);
      expect(geo.right, `${menu} ends inside the viewport`).toBeLessThanOrEqual(geo.vw + 0.5);
      expect(geo.below, `${menu} opens just under its toggle`).toBeGreaterThanOrEqual(-0.5);
      expect(geo.below, `${menu} stays anchored to its toggle`).toBeLessThanOrEqual(12);
      expect(geo.overlapsX, `${menu} is aligned with its toggle`).toBeGreaterThan(0);
      // Every item is reachable. The menu's own `max-height` cap (`assets/css/20-chrome.css`,
      // `.cm-sidebar-export-menu`) makes it a scroller on a 320px-tall viewport, so assert it IS
      // one before scrolling the LAST item into it - otherwise "the item is inside the menu" would
      // pass simply because the menu was never bounded.
      const scroller = await page.evaluate((m) => {
        const el = document.querySelector(m);
        return el.scrollHeight > el.clientHeight + 1;
      }, menu);
      expect(scroller, `${menu} is bounded and scrolls on a landscape phone`).toBe(true);
      await page.locator(item).scrollIntoViewIfNeeded();
      const reach = await page.evaluate(([m, i]) => {
        const el = document.querySelector(m);
        const last = document.querySelector(i);
        const mr = el.getBoundingClientRect();
        const ir = last.getBoundingClientRect();
        return { insideTop: ir.top - mr.top, insideBottom: mr.bottom - ir.bottom, h: ir.height };
      }, [menu, item]);
      expect(reach.h, `${item} is rendered`).toBeGreaterThan(0);
      expect(reach.insideTop, `${item} can be scrolled into ${menu}`).toBeGreaterThanOrEqual(-0.5);
      expect(reach.insideBottom, `${item} can be scrolled into ${menu}`).toBeGreaterThanOrEqual(-0.5);
      await page.keyboard.press("Escape");
      await expect(page.locator(menu)).toBeHidden();
    }
  });

  test("table-mode checklist rows keep their 44px tap targets from overlapping (CMH-RESP-06)", async ({ page }) => {
    const table =
      '<h1>Audit</h1>' +
      '<table class="cmh-checklist" data-cmh-checklist="audit" data-cmh-checklist-label="Audit">' +
      '<thead><tr><th></th><th>Control</th></tr></thead><tbody>' +
      '<tr data-cmh-item="a" data-cmh-state="blank"><td class="st"></td><td>Alpha</td></tr>' +
      '<tr data-cmh-item="b" data-cmh-state="blank"><td></td><td>Bravo</td></tr>' +
      '<tr data-cmh-item="c" data-cmh-state="blank"><td></td><td>Charlie</td></tr>' +
      '</tbody></table>';
    const staged = stageContent(table, { key: "cmh-resp06-table", source: "resp06-table.html" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("table.cmh-checklist.cmh-checklist-ready")).toHaveCount(1);
      const gap = await page.evaluate(() => {
        const checks = [...document.querySelectorAll("table.cmh-checklist .cmh-check")];
        const centers = checks.map((c) => { const r = c.getBoundingClientRect(); return r.top + r.height / 2; });
        let minGap = Infinity;
        for (let i = 1; i < centers.length; i++) minGap = Math.min(minGap, centers[i] - centers[i - 1]);
        return { count: checks.length, minGap };
      });
      expect(gap.count, "every authored row has a state control").toBeGreaterThanOrEqual(3);
      // The 44px tap overlays are centred on these controls; a center-to-center gap of
      // >=44px keeps a row's overlay out of its neighbour's hit area.
      expect(gap.minGap, "adjacent row tap targets do not overlap").toBeGreaterThanOrEqual(44);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });
});

test("small charts fit the mobile viewport instead of being force-widened (CMH-RESP-08)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const staged = stageContent(
    `<h1>Chart fit</h1><figure class="chart" id="c"><div class="chart-wrap"><canvas width="280" height="180" role="img" aria-label="small chart"></canvas></div><figcaption>small</figcaption></figure>`,
    { key: "cmh-chart-fit", source: "chart-fit.html" });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const m = await page.evaluate(() => {
      const fig = document.getElementById("c");
      const wrap = fig.querySelector(".chart-wrap");
      return {
        vw: document.documentElement.clientWidth,
        wrapW: wrap.getBoundingClientRect().width,
        figScroll: fig.scrollWidth - fig.clientWidth,
      };
    });
    expect(m.wrapW, "the chart wrap is not force-widened past the viewport").toBeLessThanOrEqual(m.vw + 1);
    expect(m.figScroll, "a small chart does not need horizontal scrolling").toBeLessThanOrEqual(1);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("sidebar context preview inserts separators at block boundaries (CMH-CTX-01)", async ({ page }) => {
  const staged = stageContent(
    `<h1>Ctx doc</h1><div class="cmh-callout"><div>18</div><div>open incidents</div></div>` +
    `<p id="t">Target sentence to anchor the comment for the context separator test.</p>`,
    { key: "cmh-ctx-sep", source: "ctx-sep.html" });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#t", "context separator check");
    await paneSettled(page);
    const before = await page.evaluate(() => {
      const arr = window.__cmhStorageCodec.read();
      return (arr[0] && arr[0].before) || "";
    });
    expect(before, "adjacent block texts are not glued into a run-on").not.toContain("18open");
    expect(before, "the numbers and label read as separate words").toContain("18 open incidents");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("deck mode does not inherit the report title toolbar-clearance margin on mobile (CMH-RESP-03)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { dir, html } = stageDeck('<section class="slide active" data-slide-id="s1"><h2>One</h2><p>content</p></section>', { key: "cmh-deck-margin" });
  try {
    await page.goto(fileUrl(html));
    await ready(page);
    const mt = await page.evaluate(() => {
      const fc = document.querySelector("#commentRoot > :first-child");
      return fc ? parseFloat(getComputedStyle(fc).marginTop) : -1;
    });
    expect(mt, "the deck viewport is not pushed down by the report toolbar-clearance margin (the deck toolbar is hidden)").toBeLessThanOrEqual(1);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
