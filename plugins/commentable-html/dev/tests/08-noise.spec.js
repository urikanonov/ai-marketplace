import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import { PYTHON } from "./helpers.js";
import fs from "fs";
import {
  fileUrl, ready, distinctCids, markTextForCid, storedComments,
  stageInline, KITCHEN_SINK, SKILL,
} from "./helpers.js";

// Seeded PRNG so a failing position is reproducible. A matrix of seeds turns the
// single-path replay into real exploration while staying deterministic.
const prngInit = (seed) => `
  let s = ${seed} >>> 0;
  window.__rng = () => {
    s |= 0; s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };`;

function watchWarnings(page) {
  const warnings = [];
  page.on("console", (m) => { if (/Lost anchor|Could not restore|Could not anchor/i.test(m.text())) warnings.push(m.text()); });
  page.on("pageerror", (e) => warnings.push("pageerror: " + e));
  return warnings;
}

// Add a comment at a random not-yet-highlighted position. `mode`: "single" (inside
// one text node), "spanning" (crosses inline boundaries), "boundary" (range set on
// element edges, exercising the normalizeBoundary path the helper usually avoids).
// Returns true if a comment was created, false if no usable target remains. A
// selection that pops the menu MUST resolve to a saved comment (no silent skip).
async function addRandomComment(page, note, mode = "single") {
  const res = await page.evaluate(({ m }) => {
    const root = document.getElementById("commentRoot");
    const usable = (n) => {
      const p = n.parentElement;
      if (!p || p.closest(".cm-skip") || p.closest("mark.cm-hl")) return false;
      return n.data.trim().length >= 3;
    };
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT,
      { acceptNode: (n) => (usable(n) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT) });
    const nodes = []; let n; while ((n = walker.nextNode())) nodes.push(n);
    if (!nodes.length) return { popped: false };
    const r = document.createRange();
    const pick = () => nodes[Math.floor(window.__rng() * nodes.length)];
    if (m === "boundary") {
      const tn = pick(); const el = tn.parentElement;
      r.setStart(el, 0); r.setEnd(el, el.childNodes.length);
    } else if (m === "spanning" && nodes.length >= 2) {
      const i = Math.floor(window.__rng() * (nodes.length - 1));
      const j = i + 1 + Math.floor(window.__rng() * Math.min(3, nodes.length - i - 1));
      r.setStart(nodes[i], Math.min(1, nodes[i].data.length));
      r.setEnd(nodes[j], Math.max(1, Math.floor(window.__rng() * nodes[j].data.length)));
    } else {
      const tn = pick(); const len = tn.data.length;
      const a = Math.floor(window.__rng() * Math.max(1, len - 2));
      const b = Math.min(len, a + 2 + Math.floor(window.__rng() * Math.max(1, len - a - 2)));
      r.setStart(tn, a); r.setEnd(tn, b);
    }
    if (r.collapsed) return { popped: false };
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    // The runtime anchors on sel.getRangeAt(0) (possibly grapheme-snapped by the
    // browser), so derive the EXPECTED covered text from that same live range, not
    // from selection.toString() (which inserts block separators / snaps astral).
    const live = sel.rangeCount ? sel.getRangeAt(0) : r;
    // The runtime never wraps cm-skip content (e.g. a code block's top-right Copy button) in a
    // highlight, so strip any cm-skip element the live range snapped across before deriving the
    // expected covered text - otherwise a selection that ends next to the Copy button reports it.
    const frag = live.cloneContents();
    frag.querySelectorAll(".cm-skip").forEach((n) => n.remove());
    const expected = frag.textContent;
    const anchor = (r.startContainer.nodeType === 1 ? r.startContainer : r.startContainer.parentElement) || root;
    anchor.scrollIntoView({ block: "center" });
    anchor.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    return { popped: true, expected };
  }, { m: mode });
  if (!res.popped) return false;
  await page.evaluate(() => new Promise((r) => setTimeout(r, 0))); // drain the mouseup setTimeout(0)
  const menu = page.locator("#menuComment");
  if (!(await menu.isVisible().catch(() => false))) {
    // The menu did not appear (e.g. the layer rejected a boundary/empty selection).
    // That is a valid outcome for boundary fuzz; treat it as "no comment made".
    return false;
  }
  const cidsBefore = await page.$$eval("mark.cm-hl", (els) => [...new Set(els.map((e) => e.dataset.cid))]);
  await menu.click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  // The save may not create a comment: a spanning/boundary range crossing an existing highlight
  // is rejected with the not-saved toast (CMH-CORE-11), and a re-anchor failure would also leave
  // the composer open - both are valid non-creation outcomes for the fuzzer. Whatever the reason,
  // NO new highlight must have been wrapped; cancel and report "no comment made".
  if (await composer.count()) {
    const cidsNow = await page.$$eval("mark.cm-hl", (els) => [...new Set(els.map((e) => e.dataset.cid))]);
    expect(cidsNow.length, "a rejected save creates no new highlight").toBe(cidsBefore.length);
    await composer.locator('[data-act="cancel"]').click();
    await expect(composer).toHaveCount(0);
    return false;
  }
  // Creation correctness: saving must create exactly ONE new highlight, and it must
  // cover EXACTLY the DOM text that was selected (byte-for-byte, incl. astral
  // clusters and cross-block runs). A save that produced no distinct new cid would
  // otherwise silently pass, so require the new cid.
  const cidsAfter = await page.$$eval("mark.cm-hl", (els) => [...new Set(els.map((e) => e.dataset.cid))]);
  expect(cidsAfter.length, "exactly one new highlight cid").toBe(cidsBefore.length + 1);
  const newCid = cidsAfter.find((c) => !cidsBefore.includes(c));
  expect(newCid, "saving creates a distinct new highlight cid").toBeTruthy();
  expect(await markTextForCid(page, newCid), "new highlight covers its selected DOM text").toBe(res.expected);
  return true;
}

// Snapshot the RAW text each highlight covers (no whitespace normalization), keyed
// by cid, so reload-stability is a byte-for-byte offset round-trip check.
async function captureMarks(page) {
  const stored = await storedComments(page);
  const out = {};
  for (const c of stored) if (c.anchorType !== "mermaid") out[c.id] = await markTextForCid(page, c.id);
  return out;
}

// A restore-from-offsets must reproduce the byte-for-byte identical covered text
// (catches any wrong-offset restore, incl. cross-block selections and astral
// clusters, where a whitespace-normalized compare could mask a one-character drift).
async function assertMarksStable(page, before) {
  for (const [cid, text] of Object.entries(before)) {
    expect(await markTextForCid(page, cid), "cid " + cid + " restore-stable").toBe(text);
    expect(text.length, "cid " + cid + " non-empty").toBeGreaterThan(0);
  }
}

for (const seed of [0x9e3779b9, 0x1234567, 0xdeadbeef]) {
  test(`noise: random comments anchor to the right text, persist, and prune (seed ${seed})`, async ({ page }) => {
    const { html, dir } = stageInline({ source: KITCHEN_SINK });
    const warnings = watchWarnings(page);
    try {
      await page.addInitScript(prngInit(seed));
      await page.goto(fileUrl(html));
      await ready(page);

      let made = 0;
      for (let i = 0; i < 24; i++) if (await addRandomComment(page, "noise " + i)) made++;
      expect(made).toBeGreaterThanOrEqual(15);
      expect(await distinctCids(page)).toBe(made);
      // Creation correctness (each highlight covers exactly its selected DOM text)
      // is asserted per-comment inside addRandomComment; capture for the prune step.
      const stored = await storedComments(page);
      const before = await captureMarks(page);

      await page.reload();
      await ready(page);
      expect(warnings).toEqual([]);
      expect(await distinctCids(page)).toBe(made);
      await assertMarksStable(page, before); // restore-from-offsets is byte-for-byte lossless

      // Prune a subset and prove EXACTLY those disappear.
      const all = stored.map((c) => c.id);
      const handled = all.filter((_, idx) => idx % 2 === 0);
      const remaining = all.filter((id) => !handled.includes(id));
      execFileSync(PYTHON, ["tools/authoring/mark_handled.py", html, ...handled], { cwd: SKILL });
      await page.reload();
      await ready(page);
      expect(warnings).toEqual([]);
      const live = new Set((await storedComments(page)).map((c) => c.id));
      for (const id of handled) expect(live.has(id), "handled " + id + " should be gone").toBe(false);
      for (const id of remaining) expect(live.has(id), "unhandled " + id + " should remain").toBe(true);
      expect(await distinctCids(page)).toBe(remaining.length);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
}

test("noise: selections crossing inline elements, entities and emoji anchor exactly", async ({ page }) => {
  const warnings = watchWarnings(page);
  await page.addInitScript(prngInit(0x51ed));
  await page.goto(fileUrl(KITCHEN_SINK));
  await ready(page);
  let made = 0;
  for (let i = 0; i < 16; i++) if (await addRandomComment(page, "span " + i, "spanning")) made++;
  expect(made).toBeGreaterThanOrEqual(8);
  const before = await captureMarks(page);
  await page.reload();
  await ready(page);
  expect(warnings).toEqual([]);
  await assertMarksStable(page, before); // restore reproduces the exact covered text
});

test("noise: element-boundary selections either anchor exactly or are cleanly rejected", async ({ page }) => {
  const warnings = watchWarnings(page);
  await page.addInitScript(prngInit(0xb0117));
  await page.goto(fileUrl(KITCHEN_SINK));
  await ready(page);
  let made = 0;
  for (let i = 0; i < 14; i++) if (await addRandomComment(page, "edge " + i, "boundary")) made++;
  // At least some boundary selections must anchor (a total regression to "always
  // rejected" would otherwise pass); each that anchored covered exactly its selected
  // DOM text (asserted in the helper).
  expect(made, "at least one boundary selection anchored").toBeGreaterThanOrEqual(1);
  const before = await captureMarks(page);
  await page.reload();
  await ready(page);
  expect(warnings).toEqual([]);
  await assertMarksStable(page, before);
});

test("noise: a random sequence of add/edit/delete/clear keeps every invariant", async ({ page }) => {
  const { html, dir } = stageInline({ source: KITCHEN_SINK });
  const warnings = watchWarnings(page);
  try {
    await page.addInitScript(prngInit(0x5eed5));
    await page.goto(fileUrl(html));
    await ready(page);

    const invariants = async () => {
      const stored = await storedComments(page);
      const ids = stored.map((c) => c.id);
      expect(new Set(ids).size, "no duplicate ids").toBe(ids.length);
      const count = await page.locator("#toolbarCount").textContent();
      expect(Number(count), "toolbar count == stored").toBe(stored.length);
      expect(await page.locator(".cm-card").count(), "cards == stored").toBe(stored.length);
      // No orphan highlights: DOM mark cids exactly match the stored non-mermaid ids
      // (delete/clear must remove marks, not just cards + storage).
      const textIds = stored.filter((c) => c.anchorType !== "mermaid").map((c) => c.id).sort();
      const domIds = (await page.$$eval("mark.cm-hl", (els) => [...new Set(els.map((e) => e.dataset.cid))])).sort();
      expect(domIds, "DOM marks == stored non-mermaid comments").toEqual(textIds);
      return stored;
    };

    page.on("dialog", (d) => d.accept());
    for (let step = 0; step < 16; step++) {
      const stored = await storedComments(page);
      const roll = await page.evaluate(() => window.__rng());
      if (stored.length === 0 || roll < 0.55) {
        await addRandomComment(page, "op " + step);
      } else if (roll < 0.75) {
        // edit a random comment (scroll its highlight into view so the composer,
        // which anchors near the highlight, opens within the viewport)
        const idx = Math.floor((await page.evaluate(() => window.__rng())) * stored.length);
        const card = page.locator(".cm-card").nth(idx);
        const cid = await card.getAttribute("data-cid");
        await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().scrollIntoViewIfNeeded().catch(() => {});
        await card.locator('[data-act="edit"]').click();
        const composer = page.locator(".cm-composer").last();
        await composer.locator("textarea").fill("edited " + step);
        await composer.locator('[data-act="save"]').click();
        await expect(composer).toHaveCount(0);
      } else if (roll < 0.92) {
        const idx = Math.floor((await page.evaluate(() => window.__rng())) * stored.length);
        await page.locator(".cm-card").nth(idx).locator('[data-act="del"]').click();
        await expect(page.locator(".cm-card")).toHaveCount(stored.length - 1);
      } else {
        await page.locator("#btnClearAll").click();
        await page.locator(".cm-modal").getByRole("button", { name: "OK" }).click();
        await expect(page.locator(".cm-card")).toHaveCount(0);
      }
      await invariants();
    }
    // Creation correctness is asserted per-add in the helper; the deep end-state
    // check is byte-for-byte reload stability of every surviving highlight.
    const before = await captureMarks(page);
    await page.reload();
    await ready(page);
    expect(warnings).toEqual([]);
    await invariants();
    await assertMarksStable(page, before);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
