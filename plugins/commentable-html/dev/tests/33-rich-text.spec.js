// Rich-text comment notes (CMH-RICH): markdown-ish formatting rendered safely in the sidebar card,
// the inline popover, and the print appendix, plus the composer formatting toolbar and shortcuts.
import { test, expect } from "@playwright/test";
import {
  openInline, addTextComment, storedComments, distinctCids,
  installClipboardCapture, lastCopied, openSidebarExportMenu, openToolbarMenu, readDownload, openSearch,
} from "./helpers.js";

const SEL = "#commentRoot section p";

async function openComposer(page, selector, index = 0) {
  await page.evaluate(({ sel, i }) => {
    const el = document.querySelectorAll(sel)[i];
    const range = document.createRange();
    range.selectNodeContents(el);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(range);
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  }, { sel: selector, i: index });
  await page.locator("#menuComment").click();
  return page.locator(".cm-composer").last();
}

// Seed the comments array directly in localStorage and reload, so a test can render a note with an
// exact raw source (control chars, null) that a textarea would otherwise normalize away.
async function seedComments(page, comments) {
  await page.evaluate((cs) => {
    // Write the modern store the runtime reads (COMMENT_KEY + "::z", framed-or-plain) and clear the
    // legacy key, so the seed is not shadowed by an empty ::z written at startup.
    window.__cmhStorageCodec.write(cs);
  }, comments);
  await page.reload();
  await page.waitForFunction(() => window.__commentableHtmlReady === true);
}

test.describe("rich-text comment notes (CMH-RICH)", () => {
  test("renders bold, italic, underline, strikethrough, and inline code from markers in the sidebar card (CMH-RICH-01)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "a **bold** b *ital* c __und__ d ~~strk~~ e `mono`");
    const note = page.locator(".cm-card .note.cmh-rich").first();
    await expect(note.locator("strong")).toHaveText("bold");
    await expect(note.locator("em")).toHaveText("ital");
    await expect(note.locator("u")).toHaveText("und");
    await expect(note.locator("s")).toHaveText("strk");
    await expect(note.locator("code")).toHaveText("mono");
    // Bold nested inside italic closes on the final lone "*", not on the inner bold marker.
    await addTextComment(page, SEL, "*outer **inner** outer*", 1);
    const nested = page.locator(".cm-card .note.cmh-rich").nth(1);
    await expect(nested.locator("em > strong")).toHaveText("inner");
    await expect(nested.locator("em")).toHaveText("outer inner outer");
  });

  test("renders '- ' lines as a bullet list and stores the note as raw source (CMH-RICH-02)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "todo:\n- one\n- two");
    const note = page.locator(".cm-card .note.cmh-rich").first();
    await expect(note.locator("ul.cmh-rich-list li")).toHaveCount(2);
    await expect(note.locator("ul.cmh-rich-list li").nth(0)).toHaveText("one");
    await expect(note.locator("ul.cmh-rich-list li").nth(1)).toHaveText("two");
    // The stored note keeps the raw source (presentation-only rendering).
    expect((await storedComments(page))[0].note).toBe("todo:\n- one\n- two");
    // A plain multi-line note keeps a single break per newline (no <br> doubling under pre-wrap).
    await addTextComment(page, SEL, "line one\nline two", 1);
    const plain = page.locator(".cm-card .note.cmh-rich").nth(1);
    await expect(plain.locator("br")).toHaveCount(0);
    expect(await plain.evaluate((el) => el.innerHTML)).toBe("line one\nline two");
  });

  test("renders markdown links and bare-URL auto-links as safe new-tab anchors; a note link does not trigger the card jump (CMH-RICH-03)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "see [docs](https://example.com/a_(b)) and https://plain.test/x.");
    const note = page.locator(".cm-card .note.cmh-rich").first();
    const md = note.locator('a[href="https://example.com/a_(b)"]');
    await expect(md).toHaveText("docs");
    await expect(md).toHaveAttribute("target", "_blank");
    await expect(md).toHaveAttribute("rel", /noopener/);
    // The balanced paren is kept in the URL; the trailing sentence period is stripped from the bare link.
    await expect(note.locator('a[href="https://plain.test/x"]')).toHaveCount(1);
    // Clicking a rendered note link must not fire the card's jump/flash handler (prevent the real
    // navigation so the click stays on the page and only the guard is under test).
    const link = note.locator("a").first();
    await link.evaluate((a) => a.addEventListener("click", (e) => e.preventDefault()));
    await link.click();
    await expect(page.locator(".cm-card.active")).toHaveCount(0);
    expect(await distinctCids(page)).toBe(1);
    // A balanced paren in a BARE auto-linked URL is also preserved (ended by the trailing space).
    await addTextComment(page, SEL, "ref https://en.wikipedia.org/wiki/A_(disambiguation) end", 1);
    await expect(page.locator(".cm-card .note.cmh-rich").nth(1)
      .locator('a[href="https://en.wikipedia.org/wiki/A_(disambiguation)"]')).toHaveCount(1);
    // A bare URL wrapped in brackets does not swallow the trailing bracket into the href.
    await addTextComment(page, SEL, "wrap [https://plain.test/y] here", 2);
    await expect(page.locator('.cm-card .note.cmh-rich a[href="https://plain.test/y"]')).toHaveCount(1);
    // A minimal one-character host still links (a bare scheme with no host does not).
    await addTextComment(page, SEL, "min http://a end", 3);
    await expect(page.locator('.cm-card .note.cmh-rich a[href="http://a"]')).toHaveCount(1);
  });

  test("escapes HTML and rejects javascript/data link schemes; malformed markers stay literal (CMH-RICH-04)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "<script>window.__pwned=1</script> [a](javascript:alert(1)) [b](data:text/html,x) unclosed **bold");
    const note = page.locator(".cm-card .note.cmh-rich").first();
    await expect(note.locator("script")).toHaveCount(0);
    await expect(note.locator("a")).toHaveCount(0);
    await expect(note).toContainText("<script>");
    await expect(note).toContainText("**bold");
    expect(await page.evaluate(() => window.__pwned)).toBeUndefined();
    // An ALLOWED-scheme link whose URL contains a double quote escapes it in the href (no attribute
    // breakout / no injected event handler).
    await addTextComment(page, SEL, '[click](https://safe.test/x"onmouseover=alert(1))', 2);
    const inja = page.locator('.cm-card .note.cmh-rich a[href*="safe.test"]');
    await expect(inja).toHaveCount(1);
    expect(await inja.getAttribute("onmouseover")).toBeNull();
    expect(await inja.getAttribute("href")).toBe('https://safe.test/x"onmouseover=alert(1)');
    // Whitespace-flanked "*" is not italic (so `3 * 4 * 5` stays literal).
    await addTextComment(page, SEL, "3 * 4 * 5", 1);
    const mathNote = page.locator(".cm-card .note.cmh-rich").nth(1);
    await expect(mathNote.locator("em")).toHaveCount(0);
    // Whitespace-flanked double markers stay literal too (`** x**`, `__ y__`, `~~ z~~`).
    await addTextComment(page, SEL, "** x** __ y__ ~~ z~~", 3);
    const flanked = page.locator(".cm-card .note.cmh-rich").nth(3);
    await expect(flanked.locator("strong, u, s")).toHaveCount(0);
  });

  test("strips control chars so a link URL cannot be CR-obfuscated, and a null note renders empty (CMH-RICH-04-ctl)", async ({ page }) => {
    await openInline(page);
    // A carriage return inside a link URL is stripped, so the href carries no raw CR (browsers would
    // otherwise drop the CR and navigate to a different host than the source implies).
    await seedComments(page, [
      { id: "cseedcr01", anchorType: "document", quote: "(document-wide)", note: "[safe](https://a.com\rmalware.com)", createdAt: new Date().toISOString(), section: null, headingPath: [] },
      { id: "cseednull1", anchorType: "document", quote: "(document-wide)", note: null, createdAt: new Date().toISOString(), section: null, headingPath: [] },
    ]);
    const href = await page.locator('.cm-card[data-cid="cseedcr01"] .note.cmh-rich a').getAttribute("href");
    expect(href).not.toContain("\r");
    expect(href).toBe("https://a.commalware.com");
    // A null note renders an empty card without error.
    await expect(page.locator('.cm-card[data-cid="cseednull1"] .note.cmh-rich')).toHaveText("");
    // The null note's hidden raw source is empty (not the literal string "null"), so it is not searchable as "null".
    await openSearch(page);
    await page.locator("#cmSearchInput").fill("null");
    await expect(page.locator('#commentList .cm-card[data-cid="cseednull1"]')).toBeHidden();
  });

  test("renders hostile long input fast without hanging (CMH-RICH-04-dos)", async ({ page }) => {
    // A non-linear parser would blow past the Playwright test timeout on these inputs; the timeout
    // (not a wall-clock comparison) is the deterministic hang guard.
    test.setTimeout(20000);
    await openInline(page);
    await addTextComment(page, SEL, "[".repeat(30000) + " " + "*".repeat(30000));
    await expect(page.locator(".cm-card .note.cmh-rich").first()).toBeVisible();
    // Trailing unmatched parens after a bare URL must not go quadratic.
    await addTextComment(page, SEL, "https://a.test/" + ")".repeat(60000), 1);
    await expect(page.locator(".cm-card .note.cmh-rich").nth(1)).toBeVisible();
  });

  test("composer toolbar buttons wrap the textarea selection for each format (CMH-RICH-05)", async ({ page }) => {
    await openInline(page);
    const composer = await openComposer(page, SEL);
    const ta = composer.locator("textarea");
    // The toolbar is a labelled group, and every button carries type="button" and an accessible name.
    await expect(composer.locator('.cm-format-bar[role="group"]')).toHaveAttribute("aria-label", /formatting/i);
    for (const fmt of ["bold", "italic", "underline", "strike", "code", "link", "list"]) {
      const btn = composer.locator(`.cm-format-bar button[data-fmt="${fmt}"]`);
      await expect(btn).toHaveAttribute("type", "button");
      expect((await btn.getAttribute("aria-label"))?.trim()).toBeTruthy();
    }

    const wraps = { bold: "**hello** world", italic: "*hello* world", underline: "__hello__ world", strike: "~~hello~~ world", code: "`hello` world" };
    for (const [fmt, expected] of Object.entries(wraps)) {
      await ta.fill("hello world");
      await ta.evaluate((el) => el.setSelectionRange(0, 5));
      await composer.locator(`[data-fmt="${fmt}"]`).click();
      await expect(ta).toHaveValue(expected);
    }

    await ta.fill("hello world");
    await ta.evaluate((el) => el.setSelectionRange(0, 5));
    await composer.locator('[data-fmt="link"]').click();
    await expect(ta).toHaveValue("[hello](url) world");
    // The inserted "url" placeholder is selected so the reviewer can type the address immediately.
    expect(await ta.evaluate((el) => el.value.substring(el.selectionStart, el.selectionEnd))).toBe("url");

    await ta.fill("a\nb");
    await ta.evaluate((el) => el.setSelectionRange(0, 3));
    await composer.locator('[data-fmt="list"]').click();
    await expect(ta).toHaveValue("- a\n- b");

    // With a bare caret the list button leaves a caret past "- " so typing does not overwrite the line.
    await ta.fill("");
    await ta.evaluate((el) => el.setSelectionRange(0, 0));
    await composer.locator('[data-fmt="list"]').click();
    await ta.pressSequentially("item");
    await expect(ta).toHaveValue("- item");

    // A click during an IME pre-edit is ignored on this surface too (the toolbar wiring is shared
    // with the side pane, so both call sites get the guard).
    await ta.fill("hello world");
    await ta.evaluate((el) => { el.setSelectionRange(0, 5); el.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true })); });
    await composer.locator('[data-fmt="bold"]').click();
    await expect(ta).toHaveValue("hello world");
    await ta.evaluate((el) => { el.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true })); el.setSelectionRange(0, 5); });
    await composer.locator('[data-fmt="bold"]').click();
    await expect(ta).toHaveValue("**hello** world");
  });

  test("Ctrl/Cmd+B/I/U/K shortcuts wrap the selection and Ctrl+Enter still saves (CMH-RICH-06)", async ({ page }) => {
    await openInline(page);
    const composer = await openComposer(page, SEL);
    const ta = composer.locator("textarea");
    const shortcuts = { b: "**pick** me", i: "*pick* me", u: "__pick__ me" };
    for (const [key, expected] of Object.entries(shortcuts)) {
      await ta.fill("pick me");
      await ta.evaluate((el) => el.setSelectionRange(0, 4));
      await ta.press(`Control+${key}`);
      await expect(ta).toHaveValue(expected);
    }
    // Ctrl+K wraps the selection as a link.
    await ta.fill("pick me");
    await ta.evaluate((el) => el.setSelectionRange(0, 4));
    await ta.press("Control+k");
    await expect(ta).toHaveValue("[pick](url) me");
    // Esc cancels the composer without persisting the draft.
    await ta.fill("discard me");
    await ta.press("Escape");
    await expect(composer).toHaveCount(0);
    expect(await storedComments(page)).toEqual([]);
    // Reopen a composer; Ctrl+Enter still saves.
    const composer2 = await openComposer(page, SEL);
    await composer2.locator("textarea").fill("save me");
    await composer2.locator("textarea").press("Control+Enter");
    await expect(composer2).toHaveCount(0);
    expect((await storedComments(page))[0].note).toBe("save me");
  });

  test("the inline comment popover renders the note rich (CMH-RICH-07)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "popover **strong** note");
    const cid = (await storedComments(page))[0].id;
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();
    await expect(pop.locator(".cm-comment-popover-note.cmh-rich strong")).toHaveText("strong");
  });

  test("Copy all keeps the raw note source; Markdown export fences it as literal data (CMH-RICH-08)", async ({ page }) => {
    await openInline(page);
    await installClipboardCapture(page);
    await addTextComment(page, SEL, "**bold** note");
    await page.click("#btnCopyAll");
    const bundle = await lastCopied(page);
    expect(bundle).toContain("**bold** note");

    await openSidebarExportMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnExportMd"),
    ]);
    const md = await readDownload(download);
    const fenced = "\n~~~\n**bold** note\n~~~\n";
    expect(md).toContain(fenced);
    expect(md.replace(fenced, "")).not.toContain("**bold** note");
    expect(md).not.toContain("<strong>");
  });

  test("comment search matches note markers and link URLs via the hidden raw source (CMH-RICH-09)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "review **urgent** [portal](https://intra.test/dashboard)");
    const note = page.locator(".cm-card .note.cmh-rich").first();
    // The URL and the raw markers are not in the visible note text (rich rendered).
    await expect(note).not.toContainText("dashboard");
    await expect(note).not.toContainText("**");
    const input = page.locator("#cmSearchInput");
    const visible = page.locator("#commentList .cm-card[data-cid]:visible");
    await openSearch(page);
    await input.fill("dashboard"); // only present in the URL
    await expect(visible).toHaveCount(1);
    await input.fill("**urgent**"); // a raw-only marker substring
    await expect(visible).toHaveCount(1);
    await input.fill("portal"); // the visible label
    await expect(visible).toHaveCount(1);
    await input.fill("zzz-no-match");
    await expect(visible).toHaveCount(0);
  });

  test("Help documents the formatting markers and shortcuts (CMH-RICH-10)", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    const help = page.locator(".cm-help");
    await expect(help).toBeVisible();
    await help.locator(".cm-help-search-input").fill("format");
    await expect(help).toContainText("Formatting");
    await expect(help).toContainText("**bold**");
    await expect(help).toContainText("Ctrl");
  });

  test("the add-comment selection menu renders above an open composer (CMH-RICH-11)", async ({ page }) => {
    await openInline(page);
    // Open a composer and leave it open, then make a fresh selection elsewhere to raise the menu.
    const composer = await openComposer(page, SEL, 0);
    await expect(composer).toBeVisible();
    await page.evaluate(() => {
      const el = document.querySelectorAll("#commentRoot section p")[1];
      const r = document.createRange();
      r.selectNodeContents(el);
      const s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
      el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    });
    const menu = page.locator("#contextMenu");
    await expect(menu).toBeVisible();
    const [menuZ, composerZ] = await page.evaluate(() => [
      parseInt(getComputedStyle(document.getElementById("contextMenu")).zIndex, 10),
      parseInt(getComputedStyle(document.querySelector(".cm-composer")).zIndex, 10),
    ]);
    expect(menuZ).toBeGreaterThan(composerZ);
  });

  test("the print appendix renders the note rich (CMH-RICH-12)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "print **bold**\n- one\n- two");
    await page.emulateMedia({ media: "print" });
    await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
    const note = page.locator("#cmhPrintComments .cmh-print-note.cmh-rich").first();
    await expect(note.locator("strong")).toHaveText("bold");
    await expect(note.locator("ul.cmh-rich-list li")).toHaveCount(2);
  });

  test("a threaded reply also renders its note rich and stays searchable (CMH-RICH-13)", async ({ page }) => {
    await openInline(page);
    await seedComments(page, [
      { id: "crootrich1", anchorType: "document", quote: "(document-wide)", note: "root note", createdAt: new Date().toISOString(), section: null, headingPath: [] },
      { id: "creplyrich1", parentId: "crootrich1", note: "reply **bolded** [ref](https://intra.test/ticket)", createdAt: new Date(Date.now() + 1000).toISOString() },
    ]);
    const reply = page.locator('.cm-reply[data-reply-cid="creplyrich1"] .note.cmh-rich');
    await expect(reply.locator("strong")).toHaveText("bolded");
    await expect(reply.locator('a[href="https://intra.test/ticket"]')).toHaveCount(1);
    // The reply's raw markers/URL stay searchable via its hidden raw-source element.
    await openSearch(page);
    await page.locator("#cmSearchInput").fill("ticket");
    await expect(page.locator('#commentList .cm-card[data-cid="crootrich1"]')).toBeVisible();
  });

  test("the side-pane reply and edit editors offer the same formatting toolbar (CMH-RICH-15)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "root note");

    await page.locator(".cm-card .cm-reply-btn").first().click();
    const reply = page.locator(".cm-card .cm-reply-compose").last();
    const bar = reply.locator('.cm-format-bar[role="group"]');
    await expect(bar).toHaveAttribute("aria-label", /formatting/i);
    for (const fmt of ["bold", "italic", "underline", "strike", "code", "link", "list"]) {
      const btn = bar.locator(`button[data-fmt="${fmt}"]`);
      await expect(btn).toHaveAttribute("type", "button");
      expect((await btn.getAttribute("aria-label"))?.trim()).toBeTruthy();
    }
    const ta = reply.locator("textarea");
    // The toolbar fits the narrow side pane on ONE row (every button shares the same top edge).
    const tops = await bar.locator("button[data-fmt]").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBe(1);
    const wraps = { bold: "**hello** world", italic: "*hello* world", underline: "__hello__ world", strike: "~~hello~~ world", code: "`hello` world" };
    for (const [fmt, expected] of Object.entries(wraps)) {
      await ta.fill("hello world");
      await ta.evaluate((el) => el.setSelectionRange(0, 5));
      await bar.locator(`[data-fmt="${fmt}"]`).click();
      await expect(ta).toHaveValue(expected);
    }
    await ta.fill("hello world");
    await ta.evaluate((el) => el.setSelectionRange(0, 5));
    await bar.locator('[data-fmt="link"]').click();
    await expect(ta).toHaveValue("[hello](url) world");
    await ta.fill("a\nb");
    await ta.evaluate((el) => el.setSelectionRange(0, 3));
    await bar.locator('[data-fmt="list"]').click();
    await expect(ta).toHaveValue("- a\n- b");

    // A toolbar click during an IME pre-edit is ignored, so markers are never spliced into
    // provisional composition text; once the composition commits the button works again.
    await ta.fill("hello world");
    await ta.evaluate((el) => { el.setSelectionRange(0, 5); el.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true })); });
    await bar.locator('[data-fmt="bold"]').click();
    await expect(ta).toHaveValue("hello world");
    await ta.evaluate((el) => { el.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true })); el.setSelectionRange(0, 5); });
    await bar.locator('[data-fmt="bold"]').click();
    await expect(ta).toHaveValue("**hello** world");

    await ta.fill("reply note");
    await reply.locator(".cm-reply-save").click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);

    // Editing the thread ROOT note in the side pane offers the same toolbar.
    await page.locator('.cm-card .cm-entry-root [data-act="edit"]').first().click();
    const rootEdit = page.locator(".cm-card .cm-entry-root .cm-reply-compose");
    const rootTa = rootEdit.locator("textarea");
    await expect(rootTa).toHaveValue("root note");
    await rootTa.evaluate((el) => el.setSelectionRange(0, 4));
    await rootEdit.locator('.cm-format-bar [data-fmt="bold"]').click();
    await expect(rootTa).toHaveValue("**root** note");

    // ... and so does editing a REPLY.
    await page.locator('[data-reply-cid] [data-act="reply-edit"]').first().click();
    const replyEdit = page.locator("[data-reply-cid] .cm-reply-compose");
    const replyTa = replyEdit.locator("textarea");
    await expect(replyTa).toHaveValue("reply note");
    await replyTa.evaluate((el) => el.setSelectionRange(0, 5));
    await replyEdit.locator('.cm-format-bar [data-fmt="code"]').click();
    await expect(replyTa).toHaveValue("`reply` note");

    // Anti-drift: the side pane and the floating composer render the SAME button set, in the same
    // order, because both build it from one shared source.
    const paneFmts = await replyEdit.locator(".cm-format-bar button[data-fmt]").evaluateAll((els) => els.map((e) => e.getAttribute("data-fmt")));
    const composer = await openComposer(page, SEL, 1);
    const composerFmts = await composer.locator(".cm-format-bar button[data-fmt]").evaluateAll((els) => els.map((e) => e.getAttribute("data-fmt")));
    expect(paneFmts).toEqual(["bold", "italic", "underline", "strike", "code", "link", "list"]);
    expect(composerFmts).toEqual(paneFmts);
  });

  test("the side-pane toolbar keeps >=44px touch targets on a phone (CMH-RICH-17)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "root note");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator(".cm-card .cm-reply-btn").first().click();
    const buttons = page.locator(".cm-reply-compose .cm-format-bar button[data-fmt]");
    await expect(buttons).toHaveCount(7);
    const boxes = await buttons.evaluateAll((els) => els.map((e) => {
      const r = e.getBoundingClientRect();
      return { w: r.width, h: r.height, left: r.left, right: r.right };
    }));
    const paneBox = await page.locator("#sidebar").evaluate((e) => {
      const r = e.getBoundingClientRect();
      return { left: r.left, right: r.right };
    });
    for (const b of boxes) {
      expect(b.h).toBeGreaterThanOrEqual(44);
      expect(b.w).toBeGreaterThanOrEqual(44);
      // The bar wraps rather than spilling out of the pane, so no button is clipped off-screen.
      expect(b.left).toBeGreaterThanOrEqual(paneBox.left - 0.5);
      expect(b.right).toBeLessThanOrEqual(paneBox.right + 0.5);
    }
  });

  test("Ctrl/Cmd+B/I/U/K work in the side-pane reply editor and Ctrl+Enter still saves (CMH-RICH-16)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, SEL, "root note");
    await page.locator(".cm-card .cm-reply-btn").first().click();
    const editor = page.locator(".cm-card .cm-reply-compose").last();
    const ta = editor.locator("textarea");
    const shortcuts = { b: "**pick** me", i: "*pick* me", u: "__pick__ me" };
    for (const [key, expected] of Object.entries(shortcuts)) {
      await ta.fill("pick me");
      await ta.evaluate((el) => el.setSelectionRange(0, 4));
      await ta.press(`Control+${key}`);
      await expect(ta).toHaveValue(expected);
    }
    await ta.fill("pick me");
    await ta.evaluate((el) => el.setSelectionRange(0, 4));
    await ta.press("Control+k");
    await expect(ta).toHaveValue("[pick](url) me");
    // Cmd (Meta) works too, so the macOS shortcut the Help panel advertises is real.
    await ta.fill("pick me");
    await ta.evaluate((el) => el.setSelectionRange(0, 4));
    await ta.press("Meta+b");
    await expect(ta).toHaveValue("**pick** me");
    // The shortcuts and Escape also work while focus is on a toolbar button, so the seven new
    // focusable controls never leak Escape to the document handler behind the editor.
    await ta.fill("pick me");
    await ta.evaluate((el) => el.setSelectionRange(0, 4));
    await editor.locator('[data-fmt="bold"]').focus();
    await editor.locator('[data-fmt="bold"]').press("Control+i");
    await expect(ta).toHaveValue("*pick* me");
    // A blank save marks the field invalid, and formatting (not just typing) clears that state.
    await ta.fill("   ");
    await editor.locator(".cm-reply-save").click();
    await expect(ta).toHaveAttribute("aria-invalid", "true");
    await expect(ta).toHaveClass(/cm-invalid/);
    await editor.locator('[data-fmt="bold"]').click();
    await expect(ta).not.toHaveAttribute("aria-invalid", "true");
    await expect(ta).not.toHaveClass(/cm-invalid/);
    await ta.fill("   ");
    await editor.locator(".cm-reply-save").click();
    await expect(ta).toHaveAttribute("aria-invalid", "true");
    await ta.fill("real text");
    await expect(ta).not.toHaveAttribute("aria-invalid", "true");
    // Escape pressed on a toolbar button closes THIS editor only: an unrelated floating composer
    // keeps its draft, because the editor's key handling never reaches the document handler.
    const other = await openComposer(page, SEL, 1);
    await other.locator("textarea").fill("unrelated draft");
    await editor.locator('[data-fmt="bold"]').focus();
    await editor.locator('[data-fmt="bold"]').press("Escape");
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);
    await expect(other).toHaveCount(1);
    await expect(other.locator("textarea")).toHaveValue("unrelated draft");
    await other.locator("textarea").press("Escape");
    expect((await storedComments(page)).length).toBe(1);

    // Mid-composition the editor swallows save and cancel too, even when the engine reports the
    // keydown with `isComposing` already false: the tracked composition state still guards them.
    await page.locator(".cm-card .cm-reply-btn").first().click();
    const editor3 = page.locator(".cm-card .cm-reply-compose").last();
    const ta3 = editor3.locator("textarea");
    await ta3.fill("mid composition");
    await ta3.evaluate((el) => el.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true })));
    await ta3.press("Control+Enter");
    await expect(editor3).toHaveCount(1);
    expect((await storedComments(page)).length).toBe(1);
    await ta3.press("Escape");
    await expect(editor3).toHaveCount(1);
    await expect(ta3).toHaveValue("mid composition");
    // Once the composition commits, both work again.
    await ta3.evaluate((el) => el.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true })));
    await ta3.press("Control+Enter");
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);
    expect((await storedComments(page)).length).toBe(2);
    // Ctrl+Enter still saves the reply, markers and all.
    await page.locator(".cm-card .cm-reply-btn").first().click();
    const editor2 = page.locator(".cm-card .cm-reply-compose").last();
    await editor2.locator("textarea").fill("**saved** reply");
    await editor2.locator("textarea").press("Control+Enter");
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);
    const stored = await storedComments(page);
    expect(stored.length).toBe(3);
    expect(stored.some((c) => c.note === "**saved** reply")).toBe(true);
  });
});
