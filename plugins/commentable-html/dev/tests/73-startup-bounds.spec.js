// Startup-DoS hardening: an untrusted embeddedComments array (or a poisoned localStorage
// array under a matching data-comment-key) must not make startup do unbounded work.
// mergeCommentSets() caps the merged comment count and drops comments whose start/end
// offsets are not sane, so backfillContext()/restoreHighlights() can never be driven into
// O(comment_count x document_size) work by attacker-controlled input. Maps to CMH-PERSIST-04.
import fs from "fs";
import { test, expect } from "@playwright/test";
import { fileUrl, ready, installClipboardCapture, stageContent, storedComments, distinctCids } from "./helpers.js";

// Same hard-failure watcher as tests/30-monkey.spec.js: any uncaught exception or genuine
// console error is a failure. Network/asset noise over file:// is filtered out.
function watchErrors(page) {
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + (e && e.stack ? e.stack : e)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (/favicon|Failed to load resource|net::ERR|ERR_/i.test(t)) return;
    errors.push("console.error: " + t);
  });
  return errors;
}

// Stage a small, realistic document (not the full demo page, so the test isolates the
// comment-count/offset bound from unrelated document size) and bake `arr` into its
// embeddedComments block, as an attacker-controlled file or a poisoned cross-document
// localStorage array under the same data-comment-key would.
function stageWithEmbeddedComments(contentHtml, arr, key) {
  const { html } = stageContent(contentHtml, { key });
  let text = fs.readFileSync(html, "utf8");
  const re = /(<script type="application\/json" id="embeddedComments">\n)\[\]\n(<\/script>)/;
  if (!re.test(text)) throw new Error("no embeddedComments block found in staged document");
  text = text.replace(re, (_m, open, close) => open + JSON.stringify(arr) + "\n" + close);
  fs.writeFileSync(html, text);
  return html;
}

// Valid-looking ids (matching SAFE_ID_RE): "c" + 10 lowercase base36 chars.
function idFor(i) {
  return "c" + i.toString(36).padStart(10, "0");
}

const CONTENT = "<h1>Doc</h1><p>Some target text here for offset testing purposes.</p>";
// A single long paragraph with plenty of distinct single-character offsets, so the flood
// below can give each comment its own small, non-overlapping range instead of piling every
// highlight onto the same few characters (which would be an unrealistic, extra-pathological
// DOM-fragmentation case beyond what F5 describes).
const LONG_CONTENT = "<h1>Doc</h1><p>" + "Lorem ipsum dolor sit amet consectetur. ".repeat(700) + "</p>";

test("an oversized embeddedComments array is capped at merge time and startup stays fast (CMH-PERSIST-04)", async ({ page }) => {
  test.setTimeout(30000);
  const OVER_CAP = 8000; // comfortably above the CMH_MAX_COMMENTS bound
  const arr = [];
  for (let i = 0; i < OVER_CAP; i++) {
    // Plain text comments (no anchorType) with small, valid, non-overlapping offsets:
    // this is the shape that drives backfillContext()'s captureContext() walk and
    // restoreHighlights()'s wrapRangeWithMark(), i.e. the exact O(count x doc size)
    // surface F5 describes.
    arr.push({
      id: idFor(i),
      start: i,
      end: i + 1,
      quote: "x",
      note: "flood-" + i,
      createdAt: "2024-01-01T00:00:00Z",
    });
  }
  const html = stageWithEmbeddedComments(LONG_CONTENT, arr, "cmh-flood-cap");
  const errors = watchErrors(page);
  await installClipboardCapture(page);
  const t0 = Date.now();
  await page.goto(fileUrl(html));
  await ready(page);
  const elapsedMs = Date.now() - t0;
  const stored = await storedComments(page);
  // Bounded: the merge never keeps more than the generous cap, no matter how large the
  // untrusted array was.
  expect(stored.length).toBeLessThan(OVER_CAP);
  expect(stored.length).toBeLessThanOrEqual(1000);
  // Fast: capping at merge time keeps startup well under a "hung browser" timescale even
  // though the untrusted array was far larger than any real document's comment count.
  expect(elapsedMs).toBeLessThan(10000);
  expect(errors).toEqual([]);
});

test("comments with non-finite or absurd start/end offsets are dropped without breaking other comments (CMH-PERSIST-04)", async ({ page }) => {
  const goodId = idFor(999999);
  const arr = [
    { id: goodId, start: 0, end: 4, quote: "Some", note: "GOOD-COMMENT", createdAt: "2024-01-01T00:00:00Z" },
    // Not a finite number (string offset from a hand-crafted / poisoned JSON array).
    { id: idFor(1), start: "not-a-number", end: 10, quote: "x", note: "bad-string-start", createdAt: "2024-01-01T00:00:00Z" },
    // Negative offsets.
    { id: idFor(2), start: -100, end: -1, quote: "x", note: "bad-negative", createdAt: "2024-01-01T00:00:00Z" },
    // Absurdly large offsets, far beyond any real document's length.
    { id: idFor(3), start: 1e15, end: 1e15 + 5, quote: "x", note: "bad-huge", createdAt: "2024-01-01T00:00:00Z" },
    // end before start.
    { id: idFor(4), start: 50, end: 10, quote: "x", note: "bad-inverted", createdAt: "2024-01-01T00:00:00Z" },
  ];
  const html = stageWithEmbeddedComments(CONTENT, arr, "cmh-flood-offsets");
  const errors = watchErrors(page);
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
  const stored = await storedComments(page);
  const ids = stored.map((c) => c.id);
  expect(ids).toContain(goodId);
  expect(ids).not.toContain(idFor(1));
  expect(ids).not.toContain(idFor(2));
  expect(ids).not.toContain(idFor(3));
  expect(ids).not.toContain(idFor(4));
  expect(await distinctCids(page)).toBe(1);
  await expect(page.locator(".cm-card")).toHaveCount(1);
  expect(errors).toEqual([]);
});
