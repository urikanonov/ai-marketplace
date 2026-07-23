import { test, expect } from "@playwright/test";
import { openInline, ready, fileUrl, INLINE, addTextComment, selectText, stageContent } from "./helpers.js";

// Accessibility + honesty of runtime feedback: toasts are announced to screen readers,
// and Copy all never claims success when it actually fell back to a manual prompt.

test("toasts carry a live-region role so screen readers announce them", async ({ page }) => {
  await openInline(page);
  await addTextComment(page, "#commentRoot p", "announce me");
  await page.click("#btnCopyAll").catch(() => {});
  const toast = page.locator("#toast");
  await expect(toast).toHaveAttribute("role", /status|alert/);
  await expect(toast).toHaveAttribute("aria-live", /polite|assertive/);
});

test("the toast is a live region before the first toast so the first one is announced (CMH-A11Y-03)", async ({ page }) => {
  await openInline(page);
  // A live region must carry aria-live BEFORE its content changes, or the FIRST toast of the
  // session is not announced. Assert the region is live at load, before any toast has fired.
  const toast = page.locator("#toast");
  await expect(toast).toHaveText("");
  await expect(toast).toHaveAttribute("aria-live", /polite|assertive/);
  await expect(toast).toHaveAttribute("role", /status|alert/);
});

test("showToast sets the live-region role/politeness before mutating the text (CMH-A11Y-03)", async ({ page }) => {
  await openInline(page);
  await addTextComment(page, "#commentRoot p", "order me");
  // Record the order of mutations on #toast: a live-region announcement fires only if the
  // role/aria-live are in place BEFORE the text changes, so pin the ordering (not just the final
  // attribute values, which a text-first regression would still satisfy).
  await page.evaluate(() => {
    window.__toastMut = [];
    const t = document.getElementById("toast");
    new MutationObserver((records) => {
      for (const r of records) {
        window.__toastMut.push(r.type === "attributes" ? "attr:" + r.attributeName : "text");
      }
    }).observe(t, { attributes: true, childList: true, characterData: true, subtree: true });
  });
  await page.click("#btnCopyAll").catch(() => {});
  await expect(page.locator("#toast")).not.toHaveText("");
  const mut = await page.evaluate(() => window.__toastMut);
  const firstText = mut.indexOf("text");
  const firstRole = mut.indexOf("attr:role");
  const firstLive = mut.indexOf("attr:aria-live");
  expect(firstText, JSON.stringify(mut)).toBeGreaterThan(-1);
  expect(firstRole, JSON.stringify(mut)).toBeGreaterThanOrEqual(0);
  expect(firstLive, JSON.stringify(mut)).toBeGreaterThanOrEqual(0);
  expect(firstRole, "role must be set before text").toBeLessThan(firstText);
  expect(firstLive, "aria-live must be set before text").toBeLessThan(firstText);
});

test("Copy all does NOT claim success when it falls back to a manual prompt", async ({ page }) => {
  await page.addInitScript(() => {
    try {
      Object.defineProperty(navigator, "clipboard", {
        value: { writeText: () => Promise.reject(new Error("blocked")) }, configurable: true,
      });
    } catch (e) {}
    document.execCommand = () => false;   // execCommand copy fails too
    window.prompt = () => null;           // the reviewer cancels the manual prompt
  });
  await page.goto(fileUrl(INLINE));
  await ready(page);
  await addTextComment(page, "#commentRoot p", "no false success");
  await page.click("#btnCopyAll");
  const txt = (await page.locator("#toast").textContent()) || "";
  expect(txt).not.toMatch(/Copied \d+ comment/); // must not lie about success
  expect(txt).toMatch(/blocked|manual/i);        // tells the reviewer what actually happened
  await expect(page.locator("#toast")).toHaveAttribute("role", "alert");
});

// CMH-A11Y-09: the text-selection context menu is a keyboard-operable ARIA menu.
test("the selection context menu exposes menu/menuitem roles and focuses its first item on open (CMH-A11Y-09)", async ({ page }) => {
  await openInline(page);
  const menu = page.locator("#contextMenu");
  // Roles are baked into the template so assistive tech announces a menu of actions.
  await expect(menu).toHaveAttribute("role", "menu");
  await expect(page.locator("#menuComment")).toHaveAttribute("role", "menuitem");
  await expect(page.locator("#menuDocComment")).toHaveAttribute("role", "menuitem");
  await expect(page.locator("#menuSlideComment")).toHaveAttribute("role", "menuitem");
  // Selecting text raises the menu; opening it moves focus to the first visible item so a
  // keyboard-only reviewer lands on the primary inline-comment action.
  await selectText(page, "#commentRoot p");
  await expect(menu).toBeVisible();
  await expect(page.locator("#menuComment")).toBeFocused();
  // Enter on the focused item opens the composer (the menu is operable without a mouse).
  await page.keyboard.press("Enter");
  await expect(page.locator(".cm-composer")).toHaveCount(1);
});

test("Escape closes the selection context menu and restores focus to the opener (CMH-A11Y-09)", async ({ page }) => {
  await openInline(page);
  // Give a real element focus, then open the doc-comment menu from an empty right-click; the
  // menu takes focus, and Escape must return focus to where it was.
  await page.locator("#btnToggleSidebar").focus();
  await page.evaluate(() => {
    document.getElementById("commentRoot").dispatchEvent(
      new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 30, clientY: 120 }));
  });
  const menu = page.locator("#contextMenu");
  await expect(menu).toBeVisible();
  await expect(page.locator("#menuDocComment")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(page.locator("#btnToggleSidebar")).toBeFocused();
});

// CMH-A11Y-10: the floating per-link add-comment affordance carries the shared focus ring.
test("the link add-comment affordance shows the shared focus-visible ring (CMH-A11Y-10)", async ({ page }) => {
  const staged = stageContent(
    '<h2 id="lead">Docs</h2><p>See the <a id="ext" href="https://example.com/docs">reference</a> for details.</p>',
    { key: "cmh-a11y10-doc" });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  // Keyboard-focusing a commentable link reveals the floating #linkAddBtn (keyboard parity).
  await page.locator("#ext").focus();
  const btn = page.locator("#linkAddBtn");
  await expect(btn).toBeVisible();
  // Establish keyboard modality so the browser applies :focus-visible on focus.
  await page.keyboard.press("Tab");
  const seen = await btn.evaluate((el) => {
    el.focus();
    return {
      matchesFocusVisible: el.matches(":focus-visible"),
      outlineStyle: getComputedStyle(el).outlineStyle,
      outlineWidth: getComputedStyle(el).outlineWidth,
    };
  });
  expect(seen.matchesFocusVisible).toBe(true);
  expect(seen.outlineStyle).toBe("solid");
  expect(parseFloat(seen.outlineWidth)).toBeGreaterThanOrEqual(2);
});

// CMH-A11Y-11: the collapsible-section caret carries a visible focus ring.
test("the section-collapse caret shows a focus-visible ring (CMH-A11Y-11)", async ({ page }) => {
  await openInline(page);
  const caret = page.locator("#commentRoot section .cmh-sec-caret").first();
  await expect(caret).toHaveCount(1);
  // Establish keyboard modality so :focus-visible applies.
  await page.keyboard.press("Tab");
  const seen = await caret.evaluate((el) => {
    el.focus();
    return {
      matchesFocusVisible: el.matches(":focus-visible"),
      outlineStyle: getComputedStyle(el).outlineStyle,
      outlineWidth: getComputedStyle(el).outlineWidth,
    };
  });
  expect(seen.matchesFocusVisible).toBe(true);
  expect(seen.outlineStyle).toBe("solid");
  expect(parseFloat(seen.outlineWidth)).toBeGreaterThanOrEqual(2);
});
