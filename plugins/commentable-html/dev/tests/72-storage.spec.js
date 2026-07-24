import { test, expect } from "@playwright/test";
import { fileUrl, ready, stageContent, stageInline, INLINE, addTextComment, storedComments, currentToast } from "./helpers.js";

// The storage manager and compression codec (CMH-STORE-*). Each test loads an isolated document
// (its own data-comment-key) so seeded "other document" data is unambiguous.

async function open(page, opts = {}) {
  const { html } = stageContent("<section><h2>Doc</h2><p>Some reviewable paragraph text here.</p></section>",
    { key: opts.key || "cmh-store-cur", source: opts.source || "current-doc.html" });
  await page.goto(fileUrl(html));
  await ready(page);
  return html;
}

async function openManager(page) {
  // The floating toolbar (and its overflow menu) is hidden while the sidebar is open, so reach the
  // manager via the sidebar export menu in that state and via the toolbar menu otherwise.
  const sidebarOpen = await page.evaluate(() => document.body.classList.contains("sidebar-open"));
  if (sidebarOpen) {
    if (await page.locator("#sidebarExportMenu").isHidden()) await page.click("#btnSidebarExportMenu");
    await page.click("#btnStorage");
  } else {
    if (await page.locator("#toolbarMenu").isHidden()) await page.click("#btnToolbarMenu");
    await page.click("#btnStorageTop");
  }
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
}

test("codec round-trips arbitrary Unicode and stores the smaller of plain/framed (CMH-STORE-01, CMH-STORE-03)", async ({ page }) => {
  await open(page);
  const res = await page.evaluate(() => {
    const C = window.__cmhStorageCodec;
    const samples = [
      "", "[]",
      "emoji \uD83D\uDE00 \uD83D\uDC69\u200D\uD83D\uDC67",
      "lone \uD83D surrogate \uDE00 mix",
      "sep \u2028 \u2029 ctrl \u0000 \u001f rtl \u05D0\u05D1 \u0627\u0644",
    ];
    const rt = samples.every((s) => {
      const dec = C.decode(C.encode(s));
      return dec.ok && dec.json === s;
    });
    // A big repetitive JSON string frames (marker \u0001) and is smaller; a tiny one stays plain.
    const big = JSON.stringify(Array.from({ length: 100 }, (_, i) => ({ id: "c" + i, note: "repeat ".repeat(20) })));
    const bigEnc = C.encode(big);
    const tiny = JSON.stringify([{ id: "c1", note: "x" }]);
    const tinyEnc = C.encode(tiny);
    return {
      rt,
      bigFramed: bigEnc.charCodeAt(0) === 1 && bigEnc.length < big.length,
      bigRoundTrips: C.decode(bigEnc).json === big,
      tinyNeverLarger: tinyEnc.length <= tiny.length && C.decode(tinyEnc).json === tiny,
      emptyPlain: C.encode("[]") === "[]",
    };
  });
  expect(res.rt).toBe(true);
  expect(res.bigFramed).toBe(true);
  expect(res.bigRoundTrips).toBe(true);
  expect(res.tinyNeverLarger).toBe(true);
  expect(res.emptyPlain).toBe(true);
});

test("large comment sets persist compressed in the ::z slot and reload intact (CMH-STORE-01, CMH-STORE-02)", async ({ page }) => {
  const key = "cmh-store-big";
  const big = Array.from({ length: 60 }, (_, i) => ({
    id: "c" + i.toString(36).padStart(6, "0"), note: "A fairly long repeated review note for compression.",
    createdAt: "2026-07-22T00:00:00Z", quote: "some quoted text", start: i, end: i + 5,
  }));
  const { html } = stageContent("<section><p>text</p></section>", { key, source: "big.html" });
  // Seed a legacy plain COMMENT_KEY value; the runtime migrates it to ::z on the startup save.
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [key, JSON.stringify(big)]);
  await page.goto(fileUrl(html));
  await ready(page);
  const state = await page.evaluate((k) => ({
    legacy: localStorage.getItem(k),
    z: localStorage.getItem(k + "::z"),
  }), key);
  expect(state.legacy).toBeNull();               // legacy slot reclaimed
  expect(state.z).not.toBeNull();
  expect(state.z.charCodeAt(0)).toBe(1);         // framed (compressed)
  expect((await storedComments(page)).length).toBe(60);
  await page.reload();
  await ready(page);
  expect((await storedComments(page)).length).toBe(60);
});

test("a legacy plain value still loads and migrates to the ::z slot (CMH-STORE-02)", async ({ page }) => {
  const key = "cmh-store-legacy";
  const arr = [{ id: "clegacy0001", note: "legacy note", quote: "q", start: 0, end: 1, createdAt: "2026-07-22T00:00:00Z" }];
  const { html } = stageContent("<section><p>text</p></section>", { key, source: "legacy.html" });
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [key, JSON.stringify(arr)]);
  await page.goto(fileUrl(html));
  await ready(page);
  expect((await storedComments(page)).length).toBe(1);
  const z = await page.evaluate((k) => localStorage.getItem(k + "::z"), key);
  expect(z).not.toBeNull();                        // migrated to the modern slot
});

test("the manager lists every document with size and count, current marked (CMH-STORE-04)", async ({ page }) => {
  await open(page, { key: "cmh-store-cur", source: "current-doc.html" });
  await addTextComment(page, "#commentRoot p", "a comment on the current doc");
  // Seed another document's stored data.
  await page.evaluate(() => {
    localStorage.setItem("commentable-html:/reports/other.html",
      JSON.stringify([{ id: "cother00001", note: "n", quote: "q", start: 0, end: 1 }]));
    localStorage.setItem("commentable-html:/reports/other.html::note", JSON.stringify({ n1: "x" }));
  });
  await openManager(page);
  await expect(page.locator(".cm-storage-row:not(.cm-storage-global)")).toHaveCount(2);
  await expect(page.locator(".cm-storage-current .cm-storage-badge")).toHaveText("This document");
  await expect(page.locator(".cm-storage-row", { hasText: "other.html" })).toBeVisible();
});

test("deleting another document's row frees its keys but never touches non-CMH data (CMH-STORE-05)", async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    localStorage.setItem("commentable-html:/reports/other.html",
      JSON.stringify([{ id: "cother00001", note: "n", quote: "q", start: 0, end: 1 }]));
    localStorage.setItem("commentable-html:/reports/other.html::note", JSON.stringify({ n1: "x" }));
    localStorage.setItem("some-other-app-key", "unrelated");   // must never be deleted
  });
  await openManager(page);
  const otherRow = page.locator(".cm-storage-row", { hasText: "other.html" });
  await otherRow.locator(".cm-storage-danger").click();
  await otherRow.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  const after = await page.evaluate(() => ({
    otherBase: localStorage.getItem("commentable-html:/reports/other.html"),
    otherNote: localStorage.getItem("commentable-html:/reports/other.html::note"),
    unrelated: localStorage.getItem("some-other-app-key"),
  }));
  expect(after.otherBase).toBeNull();
  expect(after.otherNote).toBeNull();
  expect(after.unrelated).toBe("unrelated");     // non-CMH key untouched
});

test("the dialog is near-full-screen, closes on backdrop and Escape, and restores focus (CMH-STORE-06)", async ({ page }) => {
  await open(page);
  await openManager(page);
  const size = await page.evaluate(() => {
    const b = document.querySelector(".cm-storage-manager");
    return { w: b.getBoundingClientRect().width / window.innerWidth, h: b.getBoundingClientRect().height / window.innerHeight };
  });
  expect(size.w).toBeGreaterThan(0.8);
  expect(size.h).toBeGreaterThan(0.8);
  // Escape closes and restores focus to the still-visible menu button.
  await page.keyboard.press("Escape");
  await expect(page.locator(".cm-storage-manager")).toHaveCount(0);
  expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe("btnToolbarMenu");
  // Backdrop click closes.
  await openManager(page);
  await page.locator(".cm-storage-overlay").click({ position: { x: 5, y: 5 } });
  await expect(page.locator(".cm-storage-manager")).toHaveCount(0);
});

test("the current-document row disables Delete and offers Clear all comments (CMH-STORE-08)", async ({ page }) => {
  await open(page);
  await addTextComment(page, "#commentRoot p", "note to clear");
  await openManager(page);
  const current = page.locator(".cm-storage-current");
  await expect(current.locator("button", { hasText: "Delete" })).toHaveCount(0);
  await expect(current.locator("button", { hasText: "Clear all comments" })).toBeVisible();
  await current.locator("button", { hasText: "Clear all comments" }).click();
  await current.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  expect((await storedComments(page)).length).toBe(0);
});

test("a quota failure on a comment save opens the manager and retrying after freeing space persists (CMH-STORE-07)", async ({ page }) => {
  const key = "cmh-store-quota";
  const { html } = stageContent("<section><p>reviewable paragraph text here for anchoring.</p></section>",
    { key, source: "quota-doc.html" });
  // Stateful quota: writing the current doc's ::z throws QuotaExceededError while the "bloat"
  // (another document's data) is still present; once that key is removed, the write succeeds.
  await page.addInitScript((k) => {
    const bloat = "commentable-html:/reports/bloat.html::z";
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::z" && localStorage.getItem(bloat) !== null) {
        throw new DOMException("quota", "QuotaExceededError");
      }
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  await page.evaluate(() => localStorage.setItem("commentable-html:/reports/bloat.html::z",
    "\u0001z" + "x".repeat(200)));
  await addTextComment(page, "#commentRoot p", "note that first fails to save");
  // The manager auto-opens (queued microtask).
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
  await expect(page.locator(".cm-storage-banner-warn")).toBeVisible();
  const bloatRow = page.locator(".cm-storage-row", { hasText: "bloat.html" });
  await bloatRow.locator(".cm-storage-danger").click();
  await bloatRow.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  // The pending comment write is retried and now succeeds.
  await expect.poll(async () => (await page.evaluate((k) => localStorage.getItem(k + "::z"), key)) !== null).toBe(true);
  await page.reload();
  await ready(page);
  expect((await storedComments(page)).length).toBe(1);
});

test("winner-first write order: a ::z quota failure leaves the legacy value recoverable (CMH-STORE-07)", async ({ page }) => {
  const key = "cmh-store-winner";
  const legacy = [{ id: "clegacywin1", note: "recoverable", quote: "q", start: 0, end: 1, createdAt: "2026-07-22T00:00:00Z" }];
  const { html } = stageContent("<section><p>text</p></section>", { key, source: "winner.html" });
  // Seed a legacy value and make EVERY ::z write throw quota, so the runtime can never migrate.
  await page.addInitScript(([k, v]) => {
    localStorage.setItem(k, v);
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::z") throw new DOMException("quota", "QuotaExceededError");
      return orig.call(this, key, value);
    };
  }, [key, JSON.stringify(legacy)]);
  await page.goto(fileUrl(html));
  await ready(page);
  // The startup migration save fails on ::z; the legacy value must NOT have been removed.
  const state = await page.evaluate((k) => ({ legacy: localStorage.getItem(k), z: localStorage.getItem(k + "::z") }), key);
  expect(state.legacy).not.toBeNull();
  expect(state.z).toBeNull();
  expect((await storedComments(page)).length).toBe(1);   // still loads the recoverable data
});

test("a secondary writer (note) surfaces a Manage storage action and freeing space retries + persists it (CMH-STORE-07)", async ({ page }) => {
  const key = "cmh-store-note";
  const { html } = stageContent(
    '<section><p>x</p><div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Risk">baseline</div></section>',
    { key, source: "note-doc.html" });
  // Stateful quota: the note write throws only while the bloat document's data is present.
  await page.addInitScript((k) => {
    const bloat = "commentable-html:/reports/notebloat.html::z";
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::note" && localStorage.getItem(bloat) !== null) {
        throw new DOMException("quota", "QuotaExceededError");
      }
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  await page.evaluate(() => localStorage.setItem("commentable-html:/reports/notebloat.html::z",
    "\u0001z" + "x".repeat(200)));
  const input = page.locator('[data-cmh-note="risk"] .cmh-note-input');
  await expect(input).toBeVisible();
  await input.fill("edited note text");
  await input.blur();
  await expect(page.locator("#toast .cm-toast-action")).toBeVisible();
  await expect(page.locator("#toast")).toContainText("Manage storage");
  await page.locator("#toast .cm-toast-action").click();
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
  const bloatRow = page.locator(".cm-storage-row", { hasText: "notebloat.html" });
  await bloatRow.locator(".cm-storage-danger").click();
  await bloatRow.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  // Freeing space retries the exact pending note write.
  await expect.poll(async () => await page.evaluate((k) => localStorage.getItem(k + "::note"), key)).not.toBeNull();
  await page.reload();
  await ready(page);
  await expect(page.locator('[data-cmh-note="risk"] .cmh-note-input')).toHaveValue("edited note text");
});

test("closing the manager while a secondary write (note) is still pending re-offers recovery (no silent loss) (CMH-STORE-07)", async ({ page }) => {
  const key = "cmh-store-note-close";
  const { html } = stageContent(
    '<section><p>x</p><div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Risk">baseline</div></section>',
    { key, source: "note-close-doc.html" });
  // The note write throws while the bloat document's data is present (space is never freed here).
  await page.addInitScript((k) => {
    const bloat = "commentable-html:/reports/noteclose.html::z";
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::note" && localStorage.getItem(bloat) !== null) {
        throw new DOMException("quota", "QuotaExceededError");
      }
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  await page.evaluate(() => localStorage.setItem("commentable-html:/reports/noteclose.html::z",
    "\u0001z" + "x".repeat(200)));
  const input = page.locator('[data-cmh-note="risk"] .cmh-note-input');
  await expect(input).toBeVisible();
  await input.fill("edited note text");
  await input.blur();
  // The note quota toast offers a Manage storage action; open the manager through it.
  await expect(page.locator("#toast .cm-toast-action")).toBeVisible();
  await page.locator("#toast .cm-toast-action").click();
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
  // Close WITHOUT freeing space: the still-pending secondary write must be re-offered, not lost.
  await page.keyboard.press("Escape");
  await expect(page.locator(".cm-storage-manager")).toHaveCount(0);
  await expect(page.locator("#toast")).toContainText("still not saved");
  await expect(page.locator("#toast .cm-toast-action")).toBeVisible();
});

test("foreign same-origin keys (bare arrays, non-CMH, lookalike prefix) are never listed or deletable (CMH-STORE-10)", async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    localStorage.setItem("some-app-prefs", JSON.stringify(["dark-mode", "compact"]));
    localStorage.setItem("config", "[]");
    localStorage.setItem("commentable-html-not-ours", JSON.stringify(["x"]));  // lookalike prefix (hyphen, not ":")
  });
  await openManager(page);
  await expect(page.locator(".cm-storage-row", { hasText: "some-app-prefs" })).toHaveCount(0);
  await expect(page.locator(".cm-storage-row", { hasText: "config" })).toHaveCount(0);
  await expect(page.locator(".cm-storage-row", { hasText: "not-ours" })).toHaveCount(0);
  // Delete the "Other / shared data" bucket if present; the foreign keys must still survive.
  const globalDel = page.locator(".cm-storage-global .cm-storage-btn").first();
  if (await globalDel.count()) {
    await globalDel.click();
    await page.locator(".cm-storage-global .cm-storage-danger", { hasText: "Confirm" }).click();
  }
  const survived = await page.evaluate(() => ({
    a: localStorage.getItem("some-app-prefs"), b: localStorage.getItem("config"),
    c: localStorage.getItem("commentable-html-not-ours"),
  }));
  expect(survived.a).not.toBeNull();
  expect(survived.b).not.toBeNull();
  expect(survived.c).not.toBeNull();
});

test("a custom-key document with only non-comment data is listed and reclaimable via the registry (CMH-STORE-10)", async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    const idx = JSON.parse(localStorage.getItem("commentable-html::index") || "{}");
    idx["myproj"] = { label: "My Project", source: "reports/myproj.html", t: Date.now() };
    localStorage.setItem("commentable-html::index", JSON.stringify(idx));
    localStorage.setItem("myproj::z", "[]");                                  // comments cleared
    localStorage.setItem("myproj::cl", JSON.stringify({ list: { a: "v" } })); // but a checklist remains
  });
  await openManager(page);
  const row = page.locator(".cm-storage-row", { hasText: "myproj.html" });
  await expect(row).toBeVisible();
  await row.locator(".cm-storage-danger").click();
  await row.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  const after = await page.evaluate(() => ({ z: localStorage.getItem("myproj::z"), cl: localStorage.getItem("myproj::cl") }));
  expect(after.z).toBeNull();
  expect(after.cl).toBeNull();
});

test("the quota auto-open re-arms after a successful save (repeated episodes) (CMH-STORE-11)", async ({ page }) => {
  const key = "cmh-store-reopen";
  const { html } = stageContent(
    "<section><p>Para one has some text.</p><p>Para two has some text.</p><p>Para three has some text.</p></section>",
    { key, source: "reopen.html" });
  await page.addInitScript((k) => {
    window.__cmhBlockZ = false;
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::z" && window.__cmhBlockZ) throw new DOMException("quota", "QuotaExceededError");
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  // Episode 1: blocked -> the manager auto-opens.
  await page.evaluate(() => { window.__cmhBlockZ = true; });
  await addTextComment(page, "#commentRoot p", "first", 0);
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".cm-storage-manager")).toHaveCount(0);
  // Space freed externally: a successful save re-arms the auto-open.
  await page.evaluate(() => { window.__cmhBlockZ = false; });
  await addTextComment(page, "#commentRoot p", "second", 1);
  // Episode 2: blocked again -> the manager re-opens (it would stay closed if the episode flag were
  // never reset).
  await page.evaluate(() => { window.__cmhBlockZ = true; });
  await addTextComment(page, "#commentRoot p", "third", 2);
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
});

test("an unreadable (corrupt/newer-format) stored value is left untouched and surfaces a notice (CMH-STORE-03)", async ({ page }) => {
  const key = "cmh-store-corrupt";
  const { html } = stageContent("<section><p>text</p></section>", { key, source: "corrupt.html" });
  await page.goto(fileUrl(html));
  await ready(page);
  // A framed value whose decompressed content is NOT valid JSON (simulates a newer/foreign format).
  const framed = await page.evaluate(() => window.__cmhStorageCodec.encode("x".repeat(500)));
  expect(framed.charCodeAt(0)).toBe(1);
  await page.evaluate((v) => {
    const k = document.getElementById("commentRoot").dataset.commentKey;
    localStorage.setItem(k + "::z", v);
  }, framed);
  await page.reload();
  await ready(page);
  await expect(page.locator("#toast")).toContainText("could not be read");
  const still = await page.evaluate(() => {
    const k = document.getElementById("commentRoot").dataset.commentKey;
    return localStorage.getItem(k + "::z");
  });
  expect(still).toBe(framed); // left untouched (not overwritten by the startup prune)
});

test("a startup context backfill does not overwrite an unreadable store (CMH-STORE-03)", async ({ page }) => {
  // An embedded comment lacking context fields makes backfillContext() call saveComments() at
  // startup; that automatic save must NOT clobber a present-but-unreadable ::z store.
  const embRe = /(<script[^>]*id="embeddedComments"[^>]*>)([\s\S]*?)(<\/script>)/;
  const { html } = stageInline({
    source: INLINE,
    mutate: (h) => h.replace(embRe, (_m, a, _b, c) =>
      a + JSON.stringify([{ id: "cembctx0001", note: "n", quote: "sample", start: 5, end: 15 }]) + c),
  });
  await page.goto(fileUrl(html));
  await ready(page);
  const framed = await page.evaluate(() => window.__cmhStorageCodec.encode("y".repeat(500)));
  await page.evaluate((v) => {
    const k = document.getElementById("commentRoot").dataset.commentKey;
    localStorage.setItem(k + "::z", v);
  }, framed);
  await page.reload();
  await ready(page);
  const still = await page.evaluate(() => {
    const k = document.getElementById("commentRoot").dataset.commentKey;
    return localStorage.getItem(k + "::z");
  });
  expect(still).toBe(framed); // backfillContext did not overwrite the unreadable store
});

test("deleting a document reclaims its dismissed-banner keys (CMH-STORE-12)", async ({ page }) => {
  await open(page);
  const bannerKey = "commentable-html::assetBannerDismissed::commentable-html:/reports/banner-doc.html::1.0.0::1.0.0";
  await page.evaluate((bk) => {
    localStorage.setItem("commentable-html:/reports/banner-doc.html",
      JSON.stringify([{ id: "cbanner0001", note: "n", quote: "q", start: 0, end: 1 }]));
    localStorage.setItem(bk, "1"); // a dismissed asset-version banner for that document
  }, bannerKey);
  await openManager(page);
  const row = page.locator(".cm-storage-row", { hasText: "banner-doc.html" });
  await expect(row).toBeVisible();
  await row.locator(".cm-storage-danger").click();
  await row.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  const after = await page.evaluate((bk) => ({
    base: localStorage.getItem("commentable-html:/reports/banner-doc.html"),
    banner: localStorage.getItem(bk),
  }), bannerKey);
  expect(after.base).toBeNull();
  expect(after.banner).toBeNull(); // the banner key was reclaimed with its document
});

test("a registered document whose custom key ends in a reserved suffix groups and deletes whole (CMH-STORE-05)", async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    const idx = JSON.parse(localStorage.getItem("commentable-html::index") || "{}");
    idx["proj::note"] = { label: "Proj", source: "reports/proj.html", t: Date.now() };
    localStorage.setItem("commentable-html::index", JSON.stringify(idx));
    // A legacy comment array stored directly at a custom key that itself ends in a reserved suffix,
    // plus a real sidecar. Both must group under "proj::note", not a phantom "proj" base.
    localStorage.setItem("proj::note", JSON.stringify([{ id: "cproj00001", note: "n" }]));
    localStorage.setItem("proj::note::cl", JSON.stringify({ l: { a: "v" } }));
    localStorage.setItem("proj::note::FOREIGN-APP", "keepme"); // a foreign key sharing the prefix
  });
  await openManager(page);
  const row = page.locator(".cm-storage-row", { hasText: "proj.html" });
  await expect(row).toBeVisible();
  await row.locator(".cm-storage-danger").click();
  await row.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  const after = await page.evaluate(() => ({
    base: localStorage.getItem("proj::note"),
    cl: localStorage.getItem("proj::note::cl"),
    foreign: localStorage.getItem("proj::note::FOREIGN-APP"),
  }));
  expect(after.base).toBeNull(); // the legacy base value was grouped correctly and reclaimed
  expect(after.cl).toBeNull();
  expect(after.foreign).toBe("keepme"); // a foreign sibling (unknown suffix) is never swept in
});

test("closing the manager with a comment still unsaved warns (no silent loss) (CMH-STORE-07)", async ({ page }) => {
  const key = "cmh-store-closewarn";
  const { html } = stageContent(
    "<section><p>reviewable paragraph text here for anchoring.</p></section>",
    { key, source: "closewarn.html" });
  await page.addInitScript((k) => {
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::z") throw new DOMException("quota", "QuotaExceededError");
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  await addTextComment(page, "#commentRoot p", "unsaved note");
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".cm-storage-manager")).toHaveCount(0);
  await expect(page.locator("#toast")).toContainText("still not saved");
  await expect(page.locator("#toast .cm-toast-action")).toBeVisible();
});

test("a corrupt PLAIN-JSON value in the modern slot is protected, not overwritten (CMH-STORE-03)", async ({ page }) => {
  // The ::z slot stores plain JSON when that is smaller, so a corrupt/truncated PLAIN (unframed)
  // value must be treated as unreadable too - not only a framed one. An embedded comment forces a
  // startup merge that would otherwise call saveComments() and clobber the recoverable bytes.
  const embRe = /(<script[^>]*id="embeddedComments"[^>]*>)([\s\S]*?)(<\/script>)/;
  const { html } = stageInline({
    source: INLINE,
    mutate: (h) => h.replace(embRe, (_m, a, _b, c) =>
      a + JSON.stringify([{ id: "cembplain01", note: "n", quote: "sample", start: 5, end: 15 }]) + c),
  });
  await page.goto(fileUrl(html));
  await ready(page);
  const corrupt = '[{"id":"cwhoops01","note":"tru';  // truncated plain JSON, UNFRAMED (charCode 91, not 1)
  await page.evaluate((v) => {
    const k = document.getElementById("commentRoot").dataset.commentKey;
    localStorage.setItem(k + "::z", v);
  }, corrupt);
  await page.reload();
  await ready(page);
  await expect(page.locator("#toast")).toContainText("could not be read");
  const still = await page.evaluate(() => {
    const k = document.getElementById("commentRoot").dataset.commentKey;
    return localStorage.getItem(k + "::z");
  });
  expect(still).toBe(corrupt); // the plain corrupt modern-slot value was left untouched
});

test("foreign keys named like Object.prototype members are never listed or deleted (CMH-STORE-05)", async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    localStorage.setItem("constructor", "1");
    localStorage.setItem("toString", "2");
    localStorage.setItem("__proto__", "3");
    localStorage.setItem("hasOwnProperty", "4");
  });
  await openManager(page);
  // A prototype-free membership test means these foreign keys never enter any listed bucket.
  for (const name of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
    await expect(page.locator(".cm-storage-row", { hasText: name })).toHaveCount(0);
  }
  // Deleting the shared-data bucket (if any) must not remove them.
  const globalDel = page.locator(".cm-storage-global .cm-storage-btn").first();
  if (await globalDel.count()) {
    await globalDel.click();
    await page.locator(".cm-storage-global .cm-storage-danger", { hasText: "Confirm" }).click();
  }
  const survived = await page.evaluate(() => ["constructor", "toString", "__proto__", "hasOwnProperty"]
    .map((k) => localStorage.getItem(k)));
  expect(survived).toEqual(["1", "2", "3", "4"]);
});

test("the shared registry index is never listed or deletable, so custom-key docs stay reclaimable (CMH-STORE-10)", async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    localStorage.setItem("commentable-html::index",
      JSON.stringify({ myproj: { label: "My Project", source: "reports/myproj.html", t: Date.now() } }));
    localStorage.setItem("myproj::z", "[]");                          // comments cleared
    localStorage.setItem("myproj::note", JSON.stringify({ n: "x" })); // a note sidecar remains
    localStorage.setItem("commentable-html::sidebarWidth", "320");    // a real shared preference
  });
  await openManager(page);
  // The index is never surfaced as a row.
  await expect(page.locator(".cm-storage-row", { hasText: "::index" })).toHaveCount(0);
  // Delete the shared-preferences bucket; the index must survive (only the width pref is removed).
  const globalRow = page.locator(".cm-storage-global");
  await globalRow.locator(".cm-storage-btn", { hasText: "Delete" }).click();
  await globalRow.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  const state = await page.evaluate(() => ({
    index: localStorage.getItem("commentable-html::index"),
    width: localStorage.getItem("commentable-html::sidebarWidth"),
  }));
  expect(state.index).not.toBeNull(); // ownership metadata was NOT deletable
  expect(state.width).toBeNull();
  // The custom-key document (comments empty, only a sidecar) is still listed and reclaimable.
  await expect(page.locator(".cm-storage-row", { hasText: "myproj.html" })).toBeVisible();
});

test("the storage toast action is removed once dismissed so it cannot linger clickable or focusable (CMH-STORE-07)", async ({ page }) => {
  const key = "cmh-store-toasta11y";
  const { html } = stageContent(
    '<section><p>x</p><div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Risk">baseline</div></section>',
    { key, source: "toast-a11y.html" });
  await page.addInitScript((k) => {
    const bloat = "commentable-html:/reports/toastbloat.html::z";
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::note" && localStorage.getItem(bloat) !== null) {
        throw new DOMException("quota", "QuotaExceededError");
      }
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  await page.evaluate(() => localStorage.setItem("commentable-html:/reports/toastbloat.html::z",
    "\u0001z" + "x".repeat(200)));
  const input = page.locator('[data-cmh-note="risk"] .cmh-note-input');
  await input.fill("edited note text");
  await input.blur();
  const action = page.locator("#toast .cm-toast-action");
  await expect(action).toBeVisible();
  // While the toast is shown the action is interactive.
  expect(await action.evaluate((el) => getComputedStyle(el).pointerEvents)).toBe("auto");
  // Dismissing it (via its own click) removes the button from the DOM, so a faded toast never leaves
  // an invisible control that can intercept clicks or receive Tab focus.
  await action.click();
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
  await expect(page.locator("#toast .cm-toast-action")).toHaveCount(0);
});

test("Tab stays within the dialog and deleting a row keeps focus inside it (CMH-STORE-06)", async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    localStorage.setItem("commentable-html:/reports/o1.html",
      JSON.stringify([{ id: "co100001", note: "n", quote: "q", start: 0, end: 1 }]));
    localStorage.setItem("commentable-html:/reports/o2.html",
      JSON.stringify([{ id: "co200001", note: "n", quote: "q", start: 0, end: 1 }]));
  });
  await openManager(page);
  const inside = () => page.evaluate(() => {
    const dlg = document.querySelector(".cm-storage-manager");
    return !!(dlg && dlg.contains(document.activeElement));
  });
  for (let i = 0; i < 10; i++) { await page.keyboard.press("Tab"); expect(await inside()).toBe(true); }
  for (let i = 0; i < 3; i++) { await page.keyboard.press("Shift+Tab"); expect(await inside()).toBe(true); }
  // Deleting a row re-renders and keeps focus inside the dialog (not lost to the body).
  const row = page.locator(".cm-storage-row", { hasText: "o1.html" });
  await row.locator(".cm-storage-danger").click();
  await row.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  await expect(page.locator(".cm-storage-row", { hasText: "o1.html" })).toHaveCount(0);
  expect(await inside()).toBe(true);
});

test("a checklist quota failure surfaces a Manage storage action (CMH-STORE-07)", async ({ page }) => {
  const key = "cmh-store-checklist";
  const { html } = stageContent(
    '<section><div class="cmh-checklist" data-cmh-checklist="rel" data-cmh-checklist-label="Release">'
    + '<ul><li data-cmh-item="a" data-cmh-state="blank">Task A</li></ul></div></section>',
    { key, source: "checklist-doc.html" });
  await page.addInitScript((k) => {
    const bloat = "commentable-html:/reports/clbloat.html::z";
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::cl" && localStorage.getItem(bloat) !== null) {
        throw new DOMException("quota", "QuotaExceededError");
      }
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  await page.evaluate(() => localStorage.setItem("commentable-html:/reports/clbloat.html::z",
    "\u0001z" + "x".repeat(200)));
  await page.locator('[data-cmh-item="a"] .cmh-check').first().click();
  await expect(page.locator("#toast .cm-toast-action")).toBeVisible();
  await expect(page.locator("#toast")).toContainText("Manage storage");
});

test("a section-review quota failure surfaces a Manage storage action (CMH-STORE-07)", async ({ page }) => {
  const key = "cmh-store-review";
  const { html } = stageContent(
    '<section><h2 id="sec-a">Section A</h2><p>Body text for the section here.</p></section>',
    { key, source: "review-doc.html" });
  await page.addInitScript((k) => {
    const bloat = "commentable-html:/reports/revbloat.html::z";
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::reviews" && localStorage.getItem(bloat) !== null) {
        throw new DOMException("quota", "QuotaExceededError");
      }
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  await page.evaluate(() => localStorage.setItem("commentable-html:/reports/revbloat.html::z",
    "\u0001z" + "x".repeat(200)));
  await page.locator("#sec-a").hover();
  await page.locator("#sec-a .cmh-review-badge").click();
  await expect(page.locator("#toast .cm-toast-action")).toBeVisible();
  await expect(page.locator("#toast")).toContainText("Manage storage");
});

test("the empty/quota state offers Export and Clear shortcuts even when shared preferences remain (CMH-STORE-08)", async ({ page }) => {
  const key = "cmh-store-emptyquota";
  const { html } = stageContent("<section><p>reviewable paragraph text here for anchoring.</p></section>",
    { key, source: "emptyquota.html" });
  await page.addInitScript((k) => {
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::z") throw new DOMException("quota", "QuotaExceededError");
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  // A shared preference (a globals row) exists, but there is NO other document to delete.
  await page.evaluate(() => localStorage.setItem("commentable-html::sidebarWidth", "320"));
  await addTextComment(page, "#commentRoot p", "unsaved");
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
  // The empty/quota Export + Clear shortcuts must show despite the shared-preference globals row.
  const empty = page.locator(".cm-storage-empty");
  await expect(empty).toBeVisible();
  await expect(empty.locator("button", { hasText: "Export as Portable" })).toBeVisible();
  await expect(empty.locator("button", { hasText: "Clear all comments" })).toBeVisible();
});

test("when the manager cannot open, the comment save surfaces a recovery toast instead of failing silently (CMH-STORE-11)", async ({ page }) => {
  const key = "cmh-store-fallback";
  const { html } = stageContent(
    "<section><p>First paragraph for anchoring text here.</p><p>Second paragraph for anchoring text here.</p></section>",
    { key, source: "fallback.html" });
  await page.addInitScript((k) => {
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === k + "::z") throw new DOMException("quota", "QuotaExceededError");
      return orig.call(this, key, value);
    };
  }, key);
  await page.goto(fileUrl(html));
  await ready(page);
  // First failed save opens the manager (quota episode armed).
  await addTextComment(page, "#commentRoot p:nth-of-type(1)", "first unsaved");
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
  // Close without freeing: the comment slot stays pending, so the quota episode stays armed.
  await page.keyboard.press("Escape");
  await expect(page.locator(".cm-storage-manager")).toHaveCount(0);
  // A second failed save cannot re-open the manager (episode unresolved) -> it must fall back to a
  // recovery toast with the Manage storage action, not fail silently.
  await addTextComment(page, "#commentRoot p:nth-of-type(2)", "second unsaved");
  await expect(page.locator(".cm-storage-manager")).toHaveCount(0);
  await expect(page.locator("#toast")).toContainText("Comment not saved");
  await expect(page.locator("#toast .cm-toast-action")).toBeVisible();
});

test("dismissed-banner keys attribute to the longest owned base when two bases overlap (CMH-STORE-12)", async ({ page }) => {
  await open(page);
  const shortBanner = "commentable-html::assetBannerDismissed::proj::1.0.0::1.0.0";
  const longBanner = "commentable-html::assetBannerDismissed::proj::note::1.0.0::1.0.0";
  await page.evaluate(([sb, lb]) => {
    localStorage.setItem("commentable-html::index", JSON.stringify({
      proj: { label: "Proj", source: "reports/proj.html", t: Date.now() },
      "proj::note": { label: "Proj Note", source: "reports/projnote.html", t: Date.now() },
    }));
    localStorage.setItem("proj", JSON.stringify([{ id: "cproj00001", note: "n", quote: "q", start: 0, end: 1 }]));
    localStorage.setItem("proj::note", JSON.stringify([{ id: "cprojn0001", note: "n", quote: "q", start: 0, end: 1 }]));
    localStorage.setItem(sb, "1");
    localStorage.setItem(lb, "1");
  }, [shortBanner, longBanner]);
  await openManager(page);
  // Delete the shorter base "proj". Its own banner is reclaimed, but the longer overlapping base's
  // banner (proj::note) must NOT be swept in - longest owned base wins the attribution.
  const projRow = page.locator(".cm-storage-row", { hasText: "proj.html" });
  await projRow.locator(".cm-storage-danger").click();
  await projRow.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  const after = await page.evaluate(([sb, lb]) => ({
    projBase: localStorage.getItem("proj"),
    shortBanner: localStorage.getItem(sb),
    longBanner: localStorage.getItem(lb),
    noteBase: localStorage.getItem("proj::note"),
  }), [shortBanner, longBanner]);
  expect(after.projBase).toBeNull();
  expect(after.shortBanner).toBeNull();     // proj's own banner was reclaimed with it
  expect(after.longBanner).toBe("1");       // proj::note's banner was NOT stolen by "proj"
  expect(after.noteBase).not.toBeNull();    // the proj::note document is untouched
});

test("clearing the current document's comments keeps its index entry so residual keys stay reclaimable (CMH-STORE-10)", async ({ page }) => {
  const key = "cmh-store-clearkeep";
  const { html } = stageContent("<section><p>reviewable paragraph text here for anchoring.</p></section>",
    { key, source: "clearkeep.html" });
  await page.goto(fileUrl(html));
  await ready(page);
  // A dismissed-banner residual that outlives a comment clear and needs the index for ownership.
  await page.evaluate((k) => localStorage.setItem(
    "commentable-html::assetBannerDismissed::" + k + "::1.0.0::1.0.0", "1"), key);
  await addTextComment(page, "#commentRoot p", "note to clear");
  await openManager(page);
  const current = page.locator(".cm-storage-current");
  await current.locator("button", { hasText: "Clear all comments" }).click();
  await current.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  expect((await storedComments(page)).length).toBe(0);
  // The current document's index entry survives the clear, so it (and its residual banner) remains
  // owned and reclaimable from another document rather than being orphaned.
  const idxKept = await page.evaluate((k) => {
    const idx = JSON.parse(localStorage.getItem("commentable-html::index") || "{}");
    return Object.prototype.hasOwnProperty.call(idx, k);
  }, key);
  expect(idxKept).toBe(true);
});

test("the index LRU eviction preserves an entry whose key is __proto__ (CMH-STORE-10)", async ({ page }) => {
  const { html } = stageContent("<section><p>text here for anchoring purposes only.</p></section>",
    { key: "cmh-store-lru", source: "lru.html" });
  await page.addInitScript(() => {
    // Seed the index as a raw JSON string so it carries a literal "__proto__" KEY (object assignment
    // would mutate the prototype instead of creating the entry). 200 stale entries + a RECENT
    // __proto__ entry that must survive the >200 LRU eviction triggered when this doc registers.
    const parts = [];
    for (let i = 0; i < 200; i++) parts.push('"doc' + i + '":{"label":"D' + i + '","source":"d' + i + '.html","t":1}');
    parts.push('"__proto__":{"label":"Proto","source":"proto.html","t":9999999999999}');
    localStorage.setItem("commentable-html::index", "{" + parts.join(",") + "}");
  });
  await page.goto(fileUrl(html));
  await ready(page);
  // Registering the current document triggers the LRU cap; the recent __proto__ entry must survive
  // as an OWN property (a prototype-mutating copy in the eviction path would silently drop it).
  const survived = await page.evaluate(() => {
    const idx = JSON.parse(localStorage.getItem("commentable-html::index") || "{}");
    return Object.prototype.hasOwnProperty.call(idx, "__proto__");
  });
  expect(survived).toBe(true);
});

test("the storage breakdown is a four-slice pie with a bullet legend (CMH-STORE-13)", async ({ page }) => {
  await open(page, { key: "cmh-usage-cur", source: "usage-cur.html" });
  await addTextComment(page, "#commentRoot p", "a note on the current document");
  await page.evaluate(() => {
    // A large NON-commentable-html blob so the Other slice is clearly non-zero.
    localStorage.setItem("some-other-app-blob", "z".repeat(150000));
    // A second commentable-html document, so the Other commentable-html documents slice is non-zero.
    localStorage.setItem("commentable-html:/reports/other.html",
      JSON.stringify(Array.from({ length: 20 }, (_, i) => ({
        id: "cusage" + i.toString().padStart(4, "0"), note: "n".repeat(50), quote: "q", start: i, end: i + 1,
      }))));
  });
  await openManager(page);
  const usage = page.locator(".cm-storage-usage");
  await expect(usage).toBeVisible();
  // The old prose usage lines are gone; a pie chart replaces them.
  await expect(usage.locator(".cm-storage-usage-line")).toHaveCount(0);
  await expect(usage.locator("svg.cm-storage-pie")).toHaveCount(1);
  await expect(usage.locator("svg.cm-storage-pie")).toHaveAttribute("role", "img");

  // Exactly four legend bullets, in slice order, each labelled and sized.
  const items = usage.locator(".cm-storage-legend-item");
  await expect(items).toHaveCount(4);
  await expect(items.nth(0)).toHaveAttribute("data-slice", "this");
  await expect(items.nth(1)).toHaveAttribute("data-slice", "otherdocs");
  await expect(items.nth(2)).toHaveAttribute("data-slice", "other");
  await expect(items.nth(3)).toHaveAttribute("data-slice", "free");
  await expect(items.nth(0).locator(".cm-storage-legend-label")).toHaveText("This document");
  await expect(items.nth(3).locator(".cm-storage-legend-label")).toHaveText("Free");

  const bd = await page.evaluate(() => window.__cmhStorageCodec.breakdown());
  expect(bd.thisDoc).toBeGreaterThan(0);
  expect(bd.otherDocs).toBeGreaterThan(0);  // the second commentable-html document
  expect(bd.other).toBeGreaterThan(0);      // the non-CMH blob (plus shared metadata)
  expect(bd.free).toBeGreaterThan(0);       // headroom remains in the ~5 MB budget
  // The four slices sum to the whole disc.
  expect(bd.thisDoc + bd.otherDocs + bd.other + bd.free).toBe(bd.whole);

  // Every non-zero slice is drawn in the pie and tagged with its byte value.
  for (const key of ["this", "otherdocs", "other", "free"]) {
    const slice = usage.locator(`svg.cm-storage-pie .cm-pie-slice[data-slice="${key}"]`);
    await expect(slice).toHaveCount(1);
    // Each slice carries a <title> so a mouse user gets a non-color hover cue.
    await expect(slice.locator("title")).toHaveCount(1);
    const bytes = Number(await slice.getAttribute("data-bytes"));
    expect(bytes).toBeGreaterThan(0);
  }
  // The legend size for "This document" reports a human size and percentage.
  await expect(items.nth(0).locator(".cm-storage-legend-size")).toContainText("(");
});

test("the storage breakdown caps Free at 0 and fills the disc when usage exceeds the budget (CMH-STORE-13)", async ({ page }) => {
  await open(page, { key: "cmh-over", source: "over.html" });
  const seeded = await page.evaluate(() => {
    // A blob large enough that total origin usage exceeds the assumed ~5 MB budget (UTF-16 = 2 bytes/char).
    try { localStorage.setItem("big-non-cmh-blob", "z".repeat(3 * 1024 * 1024)); return true; }
    catch (e) { return false; }
  });
  expect(seeded, "seeded an over-budget blob").toBe(true);
  await openManager(page);
  const bd = await page.evaluate(() => window.__cmhStorageCodec.breakdown());
  expect(bd.used).toBeGreaterThan(bd.quota);   // over the assumed 5 MB budget
  expect(bd.free).toBe(0);                      // no headroom left
  // The disc equals the actual usage (not the budget), and the four slices still sum to it.
  expect(bd.thisDoc + bd.otherDocs + bd.other + bd.free).toBe(bd.whole);
  expect(bd.whole).toBe(bd.used);
  // The pie still renders a full disc from the non-zero slices; Free (0) is not drawn.
  const usage = page.locator(".cm-storage-usage");
  await expect(usage.locator("svg.cm-storage-pie .cm-pie-slice[data-slice='other']")).toHaveCount(1);
  await expect(usage.locator("svg.cm-storage-pie .cm-pie-slice[data-slice='free']")).toHaveCount(0);
  // The Free legend bullet reports 0.
  await expect(usage.locator(".cm-storage-legend-item[data-slice='free'] .cm-storage-legend-size")).toContainText("0 B");
});

test("the storage breakdown counts the shared registry index in the Other slice (CMH-STORE-13)", async ({ page }) => {
  await open(page, { key: "cmh-idx", source: "idx.html" });
  await page.evaluate(() => {
    const big = {};
    for (let i = 0; i < 50; i++) big["doc" + i] = { label: "D".repeat(200), source: "s" + i + ".html", t: 1 };
    localStorage.setItem("commentable-html::index", JSON.stringify(big));
  });
  await openManager(page);
  const u = await page.evaluate(() => {
    const raw = localStorage.getItem("commentable-html::index");
    const idxBytes = ("commentable-html::index".length + raw.length) * 2;
    const bd = window.__cmhStorageCodec.breakdown();
    return { idxBytes, other: bd.other, otherDocs: bd.otherDocs };
  });
  // The registry index belongs to no single document, so it lands in the catch-all "Other" slice -
  // NOT the "Other commentable-html documents" slice (which counts only real other documents, and is
  // 0 here because this is the only document).
  expect(u.other).toBeGreaterThanOrEqual(u.idxBytes);
  expect(u.otherDocs).toBe(0);
});

test("documents are shown in a table with a column-headed Share of commentable-html storage (CMH-STORE-14)", async ({ page }) => {
  await open(page, { key: "cmh-table-cur", source: "table-cur.html" });
  await addTextComment(page, "#commentRoot p", "small current-doc note");
  await page.evaluate(() => {
    // A much larger other document, so its share of commentable-html storage is clearly higher.
    localStorage.setItem("commentable-html:/reports/big.html",
      JSON.stringify(Array.from({ length: 80 }, (_, i) => ({
        id: "cbig" + i.toString().padStart(6, "0"), note: "long repeated review note ".repeat(8),
        quote: "q", start: i, end: i + 1, createdAt: "2026-07-22T00:00:00Z",
      }))));
  });
  await openManager(page);
  const table = page.locator(".cm-storage-table");
  await expect(table).toBeVisible();
  await expect(table.locator("thead")).toContainText("Comments");
  await expect(table.locator("thead")).toContainText("Size");
  await expect(table.locator("thead")).toContainText("Share");
  const bigShare = await page.locator(".cm-storage-row", { hasText: "big.html" }).locator(".cm-storage-share").innerText();
  const curShare = await page.locator(".cm-storage-current .cm-storage-share").innerText();
  expect(bigShare).toContain("%");
  expect(curShare).toContain("%");
  expect(parseInt(bigShare, 10)).toBeGreaterThan(parseInt(curShare, 10));
});

test("the current document's comments can be browsed lazily and deleted per comment (CMH-STORE-15)", async ({ page }) => {
  const key = "cmh-browse-cur";
  const { html } = stageContent(
    "<section><p>First paragraph to browse and comment on.</p><p>Second paragraph to browse and comment on.</p></section>",
    { key, source: "browse-cur.html" });
  await page.goto(fileUrl(html));
  await ready(page);
  await addTextComment(page, "#commentRoot p:nth-of-type(1)", "first note to browse");
  await addTextComment(page, "#commentRoot p:nth-of-type(2)", "second note to browse");
  await openManager(page);
  const current = page.locator(".cm-storage-current");
  // The per-comment list is lazy: it appears only after the toggle is clicked.
  await expect(page.locator(".cm-storage-comments-row")).toHaveCount(0);
  await current.locator("button", { hasText: "Show comments" }).click();
  const list = page.locator(".cm-storage-comments-row");
  await expect(list).toBeVisible();
  const items = page.locator(".cm-storage-comment");
  await expect(items).toHaveCount(2);
  await expect(list).toContainText("first note to browse");
  await expect(items.first().locator(".cm-storage-comment-size")).toContainText("B"); // approximate per-comment size
  // Delete the first comment through its own Delete + inline confirm.
  await items.first().locator(".cm-storage-danger").click();
  await items.first().locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  // The persisted store and the live in-manager list both drop to one comment.
  await expect.poll(async () => (await storedComments(page)).length).toBe(1);
  await expect(page.locator(".cm-storage-comment")).toHaveCount(1);
  await expect(page.locator(".cm-storage-current .cm-storage-count")).toHaveText("1");
  // Deleting the last comment collapses the now-empty list (the Show comments toggle is suppressed
  // at zero, so an empty list must not stay stuck open).
  await page.locator(".cm-storage-comment").first().locator(".cm-storage-danger").click();
  await page.locator(".cm-storage-comment").first().locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  await expect(page.locator(".cm-storage-comments-row")).toHaveCount(0);
  await expect(page.locator(".cm-storage-current .cm-storage-count")).toHaveText("0");
  await expect(page.locator(".cm-storage-current").locator("button", { hasText: "Show comments" })).toHaveCount(0);
});

test("another document's comments can be browsed and deleted per comment without touching others (CMH-STORE-15)", async ({ page }) => {
  await open(page, { key: "cmh-browse-other", source: "browse-other.html" });
  await page.evaluate(() => {
    localStorage.setItem("commentable-html:/reports/peer.html",
      JSON.stringify([
        { id: "cpeer00001", note: "peer note one", quote: "q1", start: 0, end: 1, createdAt: "2026-07-22T00:00:00Z" },
        { id: "cpeer00002", note: "peer note two", quote: "q2", start: 2, end: 3, createdAt: "2026-07-22T00:00:01Z" },
      ]));
  });
  await openManager(page);
  const row = page.locator(".cm-storage-row", { hasText: "peer.html" });
  await row.locator("button", { hasText: "Show comments" }).click();
  const items = page.locator(".cm-storage-comment");
  await expect(items).toHaveCount(2);
  await items.filter({ hasText: "peer note one" }).locator(".cm-storage-danger").click();
  await items.filter({ hasText: "peer note one" }).locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  const remaining = await page.evaluate(() => {
    const raw = localStorage.getItem("commentable-html:/reports/peer.html::z")
      || localStorage.getItem("commentable-html:/reports/peer.html");
    const dec = window.__cmhStorageCodec.decode(raw);
    return JSON.parse(dec.json);
  });
  expect(remaining.map((c) => c.id)).toEqual(["cpeer00002"]); // only the deleted comment was removed
  // The removed id is tombstoned in the peer document's ::deleted set, so an embedded copy of it in
  // that file does not resurrect when the peer document is next opened.
  const tomb = await page.evaluate(() => JSON.parse(
    localStorage.getItem("commentable-html:/reports/peer.html::deleted") || "[]"));
  expect(tomb).toContain("cpeer00001");
});

test("a long comment note is truncated to a snippet with the full text in its title (CMH-STORE-15)", async ({ page }) => {
  await open(page, { key: "cmh-trunc", source: "trunc.html" });
  const longNote = "L".repeat(400);
  await page.evaluate((n) => {
    localStorage.setItem("commentable-html:/reports/big-note.html",
      JSON.stringify([{ id: "ctrunc0001", note: n, quote: "q", start: 0, end: 1, createdAt: "2026-07-22T00:00:00Z" }]));
  }, longNote);
  await openManager(page);
  await page.locator(".cm-storage-row", { hasText: "big-note.html" }).locator("button", { hasText: "Show comments" }).click();
  const note = page.locator(".cm-storage-comment-note");
  await expect(note).toBeVisible();
  const text = await note.innerText();
  expect(text.length).toBeLessThan(160);            // rendered as a bounded snippet, not in full
  expect(text.endsWith("...")).toBe(true);
  expect(await note.getAttribute("title")).toBe(longNote); // the full text is preserved in the title
});

test("per-comment delete keeps focus within the same document's list (CMH-STORE-15)", async ({ page }) => {
  await open(page, { key: "cmh-focus", source: "focus.html" });
  await page.evaluate(() => {
    localStorage.setItem("commentable-html:/reports/da.html", JSON.stringify([
      { id: "cda000001", note: "a-one", quote: "q", start: 0, end: 1 },
      { id: "cda000002", note: "a-two", quote: "q", start: 2, end: 3 }]));
    localStorage.setItem("commentable-html:/reports/db.html", JSON.stringify([
      { id: "cdb000001", note: "b-one", quote: "q", start: 0, end: 1 },
      { id: "cdb000002", note: "b-two", quote: "q", start: 2, end: 3 }]));
  });
  await openManager(page);
  await page.locator(".cm-storage-row", { hasText: "da.html" }).locator("button", { hasText: "Show comments" }).click();
  await page.locator(".cm-storage-row", { hasText: "db.html" }).locator("button", { hasText: "Show comments" }).click();
  const dbItem = page.locator(".cm-storage-comment").filter({ hasText: "b-one" });
  await dbItem.locator(".cm-storage-danger").click();
  await dbItem.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  // Focus lands within the db document's comment list (scoped), not the first expanded document's.
  const focusedBase = await page.evaluate(() => {
    const row = document.activeElement && document.activeElement.closest(".cm-storage-comments-row");
    return row ? row.dataset.cmhBase : null;
  });
  expect(focusedBase).toBe("commentable-html:/reports/db.html");
});

test("the dialog has a footer Close button that closes it and restores focus (CMH-STORE-16)", async ({ page }) => {
  await open(page);
  await openManager(page);
  const foot = page.locator(".cm-storage-foot");
  await expect(foot).toBeVisible();
  await foot.locator("button", { hasText: "Close" }).click();
  await expect(page.locator(".cm-storage-manager")).toHaveCount(0);
  expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe("btnToolbarMenu");
});
