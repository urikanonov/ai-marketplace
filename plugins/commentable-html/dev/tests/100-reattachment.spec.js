import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const assets = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../assets/js");
const read = name => fs.readFileSync(path.join(assets, name), "utf8");
const reattachment = fs.existsSync(path.join(assets, "16-reattachment.js"))
  ? read("16-reattachment.js") : "";
const restore = read("95-startup.js").split("function restoreHighlights()")[1].split("function setupChartContainment")[0];

async function harness(page, html) {
  await page.goto("about:blank");
  await page.route("**/*", route => route.abort());
  await page.setContent(`<main id="commentRoot">${html}</main>`);
  await page.addScriptTag({ content: `
    const root = document.getElementById("commentRoot");
    let comments = [];
    const CMH_MAX_OFFSET = 1000000000;
    const CMH_MAX_COMMENTS = 1000;
    function saveComments() { window.saved = JSON.parse(JSON.stringify(comments)); return true; }
    function _etIsAnchor(c) { return /^(table-column|table-cell)$/.test(c.anchorType); }
    ${read("10-offsets.js")}
    ${read("15-context.js")}
    ${reattachment}
    ${reattachment ? "" : "function cmhCaptureTextAnchor() {} function cmhReattachComments() {} function cmhIsDetached(c) { return !!c.detached; }"}
    function restoreHighlights()${restore}
    window.anchorTest = {
      set(html) { root.innerHTML = html; },
      text() { return getTextNodes().map(n => n.nodeValue).join(""); },
      add(quote, extra = {}, occurrence = 0) {
        const text = this.text(); let start = -1;
        for (let i = 0; i <= occurrence; i++) start = text.indexOf(quote, start + 1);
        const c = { id: "c" + comments.length, start, end: start + quote.length, quote,
          note: "Keep this question", createdAt: "2025-01-01", updatedAt: "2025-02-01", ...extra };
        Object.assign(c, captureContext(c.start, c.end, rangeFromOffsets(c.start, c.end)));
        comments.push(c); cmhCaptureTextAnchor(c); return c;
      },
      resolve() { cmhReattachComments(); return comments; },
      restore() { restoreHighlights(); return [...root.querySelectorAll("mark.cm-hl")].map(m => m.textContent).join(""); },
      comments() { return comments; },
      replace(arr) { comments = arr; },
      capture(c) { return cmhCaptureTextAnchor(c); },
      detached(c) { return cmhIsDetached(c); },
      index() { return cmhAnchorIndex(); },
      occurrences(quote) { return cmhAnchorOccurrences(cmhAnchorIndex(), quote, false, true); }
    };
  ` });
}

test("reattaches all locally retained roots after long insertion (CMH-REATTACH-01)", async ({ page }) => {
  await harness(page, "<p>First actionable phrase.</p><p>A late reviewer question remains.</p>");
  const result = await page.evaluate(() => {
    const a = anchorTest.add("actionable phrase", { unknown: { retained: true } });
    const b = anchorTest.add("reviewer question");
    const original = JSON.parse(JSON.stringify(a));
    delete a.cmAnchor;
    anchorTest.set("<p>" + "A lengthy new introduction. ".repeat(100) + "</p><p>First actionable phrase.</p><p>A late reviewer question remains.</p>");
    const comments = anchorTest.resolve();
    return { comments, original, highlighted: anchorTest.restore(), text: anchorTest.text(), b };
  });
  expect(result.comments[0].start).toBe(result.text.indexOf("actionable phrase"));
  expect(result.comments[1].start).toBe(result.text.indexOf("reviewer question"));
  expect(result.comments[0]).toMatchObject({ unknown: { retained: true }, updatedAt: result.original.updatedAt, quote: result.original.quote, before: result.original.before });
  expect(result.highlighted).toBe("actionable phrasereviewer question");
  expect(result.comments[0].cmAnchor.original.start).toBe(result.original.start);
  expect(result.comments[0].cmAnchor.original.end).toBe(result.original.end);
});

test("finds moved exact passages without ordinal or distance guesses (CMH-REATTACH-02)", async ({ page }) => {
  await harness(page, "<h2>Alpha</h2><p>A distinct selected passage stays intact.</p><h2>Beta</h2><p>Other material.</p>");
  const c = await page.evaluate(() => {
    anchorTest.add("distinct selected passage");
    anchorTest.set("<h2>Beta</h2><p>Other material.</p><h2>Alpha</h2><p>A distinct selected passage stays intact.</p>");
    return { c: anchorTest.resolve()[0], text: anchorTest.text() };
  });
  expect(c.c.start).toBe(c.text.indexOf("distinct selected passage"));
  expect(c.c.detached).not.toBe(true);
});

test("maps typography and prose whitespace to original offsets (CMH-REATTACH-03)", async ({ page }) => {
  await harness(page, "<p>A reviewer says \"hello world\" today.</p><pre>one  two\nthree</pre>");
  const result = await page.evaluate(() => {
    anchorTest.add('"hello world"');
    anchorTest.add("one  two\nthree");
    anchorTest.set('<p>New intro. A reviewer says \u201chello\u00a0 \nworld\u201d today.</p><pre>one two three</pre>');
    const arr = anchorTest.resolve();
    return { prose: anchorTest.text().slice(arr[0].start, arr[0].end), arr };
  });
  expect(result.prose).toBe("\u201chello\u00a0 \nworld\u201d");
  expect(result.arr[0].quote).toBe('"hello world"');
  expect(result.arr[1].detached).toBe(true);
});

test("recovers small block edits and changed selections with strong evidence (CMH-REATTACH-04)", async ({ page }) => {
  await harness(page, '<p id="stable">The introduction gives reliable context. The selected brown fox jumps over the lazy dog. The conclusion stays unchanged.</p>');
  const results = await page.evaluate(() => {
    const c = anchorTest.add("selected brown fox");
    anchorTest.set('<p id="stable">The revised introduction gives reliable context. The selected red fox jumps over the lazy dog. The conclusion stays unchanged.</p>');
    anchorTest.resolve();
    const first = anchorTest.text().slice(c.start, c.end);
    anchorTest.set('<p id="stable">The revised introduction gives reliable context. The selected red fox jumps over the very lazy dog. The conclusion stays unchanged.</p>');
    anchorTest.resolve();
    return { first, second: anchorTest.text().slice(c.start, c.end), c };
  });
  expect(results.first).toBe("selected red fox");
  expect(results.second).toBe("selected red fox");
  expect(results.c.quote).toBe("selected brown fox");
  await harness(page, "<p>A whole selected paragraph has reliable wording and unchanged concluding evidence.</p>");
  const whole = await page.evaluate(() => {
    anchorTest.add(anchorTest.text());
    anchorTest.set("<p>A whole selected paragraph has clearer reliable wording and unchanged concluding evidence.</p>");
    const c = anchorTest.resolve()[0]; return anchorTest.text().slice(c.start, c.end);
  });
  expect(whole).toBe("A whole selected paragraph has clearer reliable wording and unchanged concluding evidence.");
  await harness(page, "<p>Strong preceding words supply context. Selected brown fox. Strong following words preserve context.</p>");
  const legacy = await page.evaluate(() => {
    const c = anchorTest.add("Selected brown fox"); delete c.cmAnchor;
    anchorTest.set("<p>Strong preceding words supply context. Selected red fox. Strong following words preserve context.</p>");
    anchorTest.resolve(); return anchorTest.text().slice(c.start, c.end);
  });
  expect(legacy).toBe("Selected red fox");
  await harness(page, "<p>" + "Long stable introductory wording. ".repeat(100) + "The selected brown fox has a carefully preserved trailing explanation.</p>");
  const longBlock = await page.evaluate(() => {
    anchorTest.add("selected brown fox");
    anchorTest.set("<p>" + "Long stable introductory wording. ".repeat(100) + "The selected red fox has a carefully preserved trailing explanation.</p>");
    const c = anchorTest.resolve()[0]; return anchorTest.text().slice(c.start, c.end);
  });
  expect(longBlock).toBe("selected red fox");
  for (const quote of ["The selected brown fox", "selected brown fox."]) {
    const leading = quote.startsWith("The");
    const text = leading
      ? "The selected brown fox leads this paragraph. The unchanged conclusion supplies strong evidence."
      : "The unchanged introduction supplies strong evidence before the selected brown fox.";
    await harness(page, '<p id="edge">' + text + "</p>");
    const edge = await page.evaluate(({ text, quote }) => {
      const c = anchorTest.add(quote);
      anchorTest.set('<p id="edge">' + text.replace("brown", "red") + "</p>");
      anchorTest.resolve();
      return anchorTest.text().slice(c.start, c.end);
    }, { text, quote });
    expect(edge).toBe(quote.replace("brown", "red"));
  }
});

test("disambiguates short repeats but detaches indistinguishable revised copies (CMH-REATTACH-05)", async ({ page }) => {
  await harness(page, "<h2>East</h2><p>The East status is OK with measured evidence.</p><h2>West</h2><p>The West status is OK with different evidence.</p>");
  const result = await page.evaluate(() => {
    anchorTest.add("OK", {}, 1);
    anchorTest.set("<p>Inserted preface.</p><h2>West</h2><p>The West status is OK with different evidence.</p><h2>East</h2><p>The East status is OK with measured evidence.</p>");
    const c = anchorTest.resolve()[0];
    return { c, text: anchorTest.text() };
  });
  expect(result.c.start).toBe(result.text.indexOf("OK"));
  await harness(page, "<p>Repeated selected passage.</p><p>Repeated selected passage.</p>");
  const ambiguous = await page.evaluate(() => {
    anchorTest.add("selected passage");
    anchorTest.set("<p>Repeated selected passage.</p><p>Repeated selected passage.</p><p>Revised ending.</p>");
    return anchorTest.resolve()[0];
  });
  expect(ambiguous).toMatchObject({ detached: true, start: 1000000000, end: 1000000000 });
});

test("deleting one historically identical paragraph cannot bind its comment to the surviving copy (CMH-REATTACH-05)", async ({ page }) => {
  for (const identity of ["own", "none", "ancestor"]) {
    const ids = identity === "own", ancestor = identity === "ancestor";
    const paragraph = "A repeated identical review phrase.";
    const content = `<p${ids ? ' id="original"' : ""}>${paragraph}</p><p${ids ? ' id="copy"' : ""}>${paragraph}</p>`;
    await harness(page, ancestor ? `<section id="shared">${content}</section>` : content);
    const c = await page.evaluate(({ paragraph, ids, ancestor }) => {
      anchorTest.add(paragraph);
      const content = `<p${ids ? ' id="copy"' : ""}>${paragraph}</p>`;
      anchorTest.set(ancestor ? `<section id="shared">${content}</section>` : content);
      return anchorTest.resolve()[0];
    }, { paragraph, ids, ancestor });
    expect(c.detached).toBe(true);
    expect(c.note).toBe("Keep this question");
    expect(c.cmAnchor.original.start).toBe(0);
  }
});

test("a huge rewrite cannot overflow small-block edit alignment into a false attachment (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, '<p id="stable">abc</p>');
  const c = await page.evaluate(() => {
    anchorTest.add("abc");
    anchorTest.set('<p id="stable">' + "x".repeat(65536) + "abc</p>");
    return anchorTest.resolve()[0];
  });
  expect(c.detached).toBe(true);
  expect(c.cmAnchor.original.quote).toBe("abc");
});

test("large-block evidence work is bounded before normalization and alignment slicing (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, '<p id="large">Selected passage</p>');
  const result = await page.evaluate(() => {
    const c = anchorTest.add("Selected passage");
    anchorTest.set('<p id="large">' + c.quote.repeat(128) + "x".repeat(600000) + "</p>");
    const index = anchorTest.index();
    const hits = cmhAnchorOccurrences(index, c.quote, false, false);
    let examined = 0, longestSlice = 0;
    const normalize = cmhAnchorNormalize, slice = String.prototype.slice;
    cmhAnchorNormalize = (text, ...args) => { examined += text.length; return normalize(text, ...args); };
    String.prototype.slice = function (start, end) {
      if (this.length === index.text.length) longestSlice = Math.max(longestSlice, (end ?? this.length) - start);
      return slice.call(this, start, end);
    };
    try {
      const before = index.budget;
      cmhAnchorChoose(index, hits, c.cmAnchor, c, c.quote);
      const charged = before - index.budget;
      cmhAnchorFuzzy(index, { code: false, block: { id: "large", tag: "p", from: 0, text: "abc", start: 0, end: 3 } });
      return { examined, charged, longestSlice };
    } finally {
      cmhAnchorNormalize = normalize;
      String.prototype.slice = slice;
    }
  });
  expect(result.examined).toBeLessThanOrEqual(result.charged);
  expect(result.longestSlice).toBeLessThanOrEqual(4096);
});

test("detaches deletion and recovers when original evidence returns (CMH-REATTACH-06)", async ({ page }) => {
  await harness(page, '<p id="original">Before this unique passage. Selected target phrase. After this unique passage.</p>');
  const result = await page.evaluate(() => {
    const c = anchorTest.add("Selected target phrase");
    const initial = JSON.parse(JSON.stringify(c));
    anchorTest.set('<p id="original">Completely unrelated replacement text.</p><p>Selected target phrase belongs to a different discussion.</p>');
    anchorTest.resolve();
    const detached = JSON.parse(JSON.stringify(c));
    anchorTest.set('<p>New introduction.</p><p id="original">Before this unique passage. Selected target phrase. After this unique passage.</p>');
    anchorTest.resolve();
    return { initial, detached, recovered: c, text: anchorTest.text() };
  });
  expect(result.detached).toMatchObject({ detached: true, start: 1000000000 });
  expect(result.recovered.start).toBe(result.text.indexOf("Selected target phrase"));
  expect(result.recovered.detached).not.toBe(true);
  expect(result.recovered.updatedAt).toBe(result.initial.updatedAt);
  const manuallyCaptured = await page.evaluate(() => {
    const c = anchorTest.comments()[0];
    c.quote = "New introduction"; c.start = 0; c.end = c.quote.length;
    c.detached = false; c.before = ""; c.after = "New manual context";
    anchorTest.capture(c);
    return c.cmAnchor.original;
  });
  expect(manuallyCaptured).toMatchObject({ start: result.initial.start, end: result.initial.end,
    quote: result.initial.quote, before: result.initial.before, after: result.initial.after });
});

test("preserves legacy and future metadata and skips structural roots and replies (CMH-REATTACH-07)", async ({ page }) => {
  await harness(page, "<p>Legacy text with usable offsets.</p>");
  const result = await page.evaluate(() => {
    const arr = [
      { id: "legacy", start: 0, end: 6, note: "no quote", custom: 42 },
      { id: "future", start: 0, end: 6, quote: "Legacy", cmAnchor: { v: 99, opaque: true } },
      { id: "broken", start: 0, end: 6, quote: "Legacy", cmAnchor: { v: 1, block: { text: "x".repeat(100000) } } },
      { id: "structural", anchorType: "image", quote: "Legacy" },
      { id: "reply", parentId: "future", note: "A reply" },
      { id: "offsetless", quote: "usable offsets" },
      { id: "discontiguous", quote: "missing ... fragments" },
      { id: "short", start: 0, end: 6, quote: "Legacy", note: "Short old selection" }
    ];
    anchorTest.replace(arr); anchorTest.resolve();
    return { arr, replyDetached: anchorTest.detached(arr[4]) };
  });
  expect(result.arr[0]).toMatchObject({ start: 0, end: 6, custom: 42 });
  expect(result.arr[1]).toMatchObject({ detached: true, cmAnchor: { v: 99, opaque: true } });
  expect(result.replyDetached).toBe(true);
  expect(result.arr[2]).toMatchObject({ start: 0, end: 6, detached: false });
  expect(result.arr[3]).toEqual({ id: "structural", anchorType: "image", quote: "Legacy" });
  expect(result.arr[5]).toMatchObject({ start: 17, end: 31, detached: false });
  expect(result.arr[6]).toEqual({ id: "discontiguous", quote: "missing ... fragments" });
  expect(result.arr[7]).toMatchObject({ start: 0, end: 6, detached: false });
});

test("excludes skipped source text and bounds snapshots and matcher work (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, '<p id="large">' + "Long prose. ".repeat(1000) + 'Unique end phrase.</p><p>Excluded <span class="cm-skip">private target</span> text.</p>');
  const result = await page.evaluate(() => {
    const c = anchorTest.add("Unique end phrase");
    anchorTest.set('<p>Inserted <span class="cm-skip">Unique end phrase</span> preface.</p>' + document.getElementById("commentRoot").innerHTML);
    anchorTest.resolve();
    return { c, text: anchorTest.text(), size: JSON.stringify(c.cmAnchor).length };
  });
  expect(result.c.start).toBe(result.text.indexOf("Unique end phrase"));
  expect(result.size).toBeLessThan(10000);
  expect(result.text).not.toContain("private target");
  await harness(page, "<p>" + "x".repeat(4096) + "y" + "z".repeat(900) + "</p>");
  expect(await page.evaluate(() => anchorTest.occurrences("x".repeat(4096) + "y"))).toBeNull();
  const source = "<p>Alpha introductory words before a crossing selection.</p>"
    + "<p>The crossing selection ends here.</p><p>Repeated OK statement.</p><p>Repeated OK statement.</p>";
  await harness(page, source);
  const unchanged = await page.evaluate(html => {
    anchorTest.add("crossing selection.The crossing selection");
    anchorTest.restore();
    const c = anchorTest.add("OK", {}, 1);
    const before = { start: c.start, end: c.end, revision: c.cmAnchor.revision };
    anchorTest.set(html);
    anchorTest.resolve();
    return { before, c };
  }, source);
  expect(unchanged.c).toMatchObject({ start: unchanged.before.start, end: unchanged.before.end, detached: false });
  expect(unchanged.c.cmAnchor.revision).toBe(unchanged.before.revision);
  await harness(page, "<p>Repeated OK statement.</p><p>Repeated OK statement.</p>");
  const regrouped = await page.evaluate(() => {
    const c = anchorTest.add("OK");
    const before = { start: c.start, end: c.end, revision: c.cmAnchor.revision };
    anchorTest.set("<div><p>Repeated OK</p><p> statement.</p></div><p>Repeated OK statement.</p>");
    anchorTest.resolve();
    return { before, c };
  });
  expect(regrouped.c).toMatchObject({ start: regrouped.before.start, end: regrouped.before.end, detached: false });
  expect(regrouped.c.cmAnchor.revision).toBe(regrouped.before.revision);
});

test("large headings cannot multiply full-document hashing across every indexed block (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<h2>" + "H".repeat(600000) + "</h2>" + "<p>Tail paragraph.</p>".repeat(128));
  const result = await page.evaluate(() => {
    const hash = cmhAnchorHash;
    let examined = 0;
    cmhAnchorHash = text => { examined += text.length; return hash(text); };
    try {
      const index = anchorTest.index();
      return { examined, chars: index.text.length, blocks: index.blocks.length };
    } finally {
      cmhAnchorHash = hash;
    }
  });
  expect(result.examined).toBeLessThanOrEqual(result.chars * 2 + result.blocks * 4096);
});

test("marks overlaps and failed wraps Detached without changing comment data (CMH-REATTACH-09)", async ({ page }) => {
  await harness(page, "<p>Distinct selected phrase for review.</p>");
  const result = await page.evaluate(() => {
    const a = anchorTest.add("selected phrase");
    const b = anchorTest.add("selected");
    anchorTest.resolve(); anchorTest.restore();
    return { arr: anchorTest.comments(), marks: anchorTest.restore(), a, b };
  });
  expect(result.arr[1].detached).toBe(true);
  expect(result.arr[0].note).toBe("Keep this question");
  await harness(page, "<p>A selected phrase for review.</p>");
  const failure = await page.evaluate(() => {
    anchorTest.add("selected phrase"); anchorTest.resolve();
    wrapRangeWithMark = () => { throw new Error("simulated wrap failure"); };
    anchorTest.restore(); return anchorTest.comments()[0];
  });
  expect(failure.detached).toBe(true);
});
