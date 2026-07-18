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
// Many small paragraphs (a "wide" document: lots of DOM/text nodes), unlike LONG_CONTENT's
// single long text node. getTextNodes()'s TreeWalker cost tracks DOM node count, not raw
// character count, so this shape is what actually makes a doomed rangeFromOffsets() call
// (one that never finds a match) expensive per call - the shape a large real report or a
// long thread of many short comments/sections would have.
const MANY_NODES_CONTENT = "<h1>Doc</h1>" + "<p>word</p>".repeat(20000);

test("an oversized embeddedComments array is capped at merge time and startup stays fast (CMH-PERSIST-04)", async ({ page }) => {
  // Tighter than the project default: pins "startup stays fast" via the test's own timeout
  // (deterministic - see below) rather than a wall-clock assertion. Pre-fix, this test's
  // page.goto() never resolved at all (a genuine hang), so any regression of the cap fails
  // the same way, without depending on runner speed for a numeric threshold.
  test.setTimeout(15000);
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
  await page.goto(fileUrl(html));
  await ready(page);
  const stored = await storedComments(page);
  // Bounded: every generated entry is a distinct, otherwise-valid id, so the merge keeps
  // exactly the cap - not fewer (which would mean valid comments were wrongly dropped) and
  // not more (which would mean the cap was not enforced).
  expect(stored.length).toBe(1000);
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

test("a flood of offsetless, non-anchor-typed comments does not drive per-comment full-document work (CMH-PERSIST-04)", async ({ page }) => {
  // Regression for a gap the merge-time cap alone does not close: an entry with neither a
  // recognized anchorType (document/image/widget/mermaid/diff) nor start/end passes
  // mergeCommentSets()'s offset-sanity check trivially (no offsets to validate), but
  // restoreHighlights() used to treat anything without one of those anchorTypes as a text
  // comment and call rangeFromOffsets(undefined, undefined) anyway - which still walks
  // every text node. A capped flood of such malformed entries would reproduce the same
  // O(count x doc size) hang the count cap is meant to prevent. restoreHighlights() must
  // skip these instead (kept as stored comments/cards, just never attempted as a highlight).
  test.setTimeout(15000);
  const FLOOD = 1000; // at the CMH_MAX_COMMENTS cap: the worst case that survives merging
  const goodId = idFor(999999);
  const arr = [{ id: goodId, start: 3, end: 7, quote: "word", note: "GOOD-COMMENT", createdAt: "2024-01-01T00:00:00Z" }];
  for (let i = 0; i < FLOOD - 1; i++) {
    arr.push({ id: idFor(i), note: "offsetless-" + i, createdAt: "2024-01-01T00:00:00Z" });
  }
  const html = stageWithEmbeddedComments(MANY_NODES_CONTENT, arr, "cmh-flood-offsetless");
  const errors = watchErrors(page);
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
  const stored = await storedComments(page);
  expect(stored.length).toBe(FLOOD);
  // The one real text comment still anchors and highlights; the offsetless flood does not
  // (no anchor to restore), and none of it crashes startup.
  expect(await distinctCids(page)).toBe(1);
  await expect(page.locator(".cm-card")).toHaveCount(FLOOD);
  expect(errors).toEqual([]);
});
