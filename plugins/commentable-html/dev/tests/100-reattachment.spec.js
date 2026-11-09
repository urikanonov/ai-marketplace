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
      set(html) {
        root.innerHTML = html;
        if (typeof cmhAuthoredIds !== "undefined") {
          cmhAuthoredIds.clear();
          root.querySelectorAll("[id]").forEach(el => cmhAuthoredIds.add(el.id));
        }
      },
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

test("verified unchanged selectors avoid repeated evidence scans but detect layout changes (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, '<p id="stable">A sufficiently long selected passage.</p><p>Other prose.</p>');
  const result = await page.evaluate(() => {
    const c = anchorTest.add("selected passage");
    const occurrences = cmhAnchorOccurrences;
    let scans = 0;
    cmhAnchorOccurrences = (...args) => { scans++; return occurrences(...args); };
    try {
      anchorTest.resolve();
      const unchangedScans = scans;
      anchorTest.set('<p id="stable">A sufficiently long selected passage.</p><pre>Other prose.</pre>');
      anchorTest.resolve();
      return { unchangedScans, layoutScans: scans - unchangedScans, c };
    } finally { cmhAnchorOccurrences = occurrences; }
  });
  expect(result.unchangedScans).toBe(0);
  expect(result.layoutScans).toBeGreaterThan(0);
  expect(result.c).toMatchObject({ start: 20, detached: false });
});

test("legacy context backfill shares one immutable layout scan without replacing original fields (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<h2>Section</h2>" + "<p>Original context and selected review words.</p>".repeat(200));
  const result = await page.evaluate(() => {
    const text = anchorTest.text(), quote = "selected review";
    const c = [0, 1, 2, 3].map((i) => {
      const start = text.indexOf(quote, i * 43);
      return { id: "c" + i, quote, start, end: start + quote.length };
    });
    const expected = c.map(item => captureContext(item.start, item.end, rangeFromOffsets(item.start, item.end)));
    c[0].before = "Original historical context";
    anchorTest.replace(c);
    const style = window.getComputedStyle;
    let reads = 0;
    window.getComputedStyle = (...args) => { reads++; return style(...args); };
    try {
      backfillContext();
      return { reads, expected, actual: c };
    } finally { window.getComputedStyle = style; }
  });
  expect(result.reads).toBeLessThan(300);
  for (let i = 0; i < result.actual.length; i++) {
    expect(result.actual[i]).toMatchObject({ ...result.expected[i],
      ...(i === 0 ? { before: "Original historical context" } : {}) });
  }
});

test("highlight wrapping visits only the selected subtree while excluding skipped text (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<p>Other paragraph.</p>".repeat(200)
    + '<p>Target <span class="cm-skip">private</span>selected review words.</p>');
  const result = await page.evaluate(() => {
    const text = anchorTest.text(), start = text.indexOf("selected review");
    const range = rangeFromOffsets(start, start + "selected review".length);
    const scan = getTextNodes;
    let scans = 0;
    getTextNodes = () => { scans++; return scan(); };
    try {
      wrapRangeWithMark(range, "cbenchmark");
      return { scans, marks: [...root.querySelectorAll("mark.cm-hl")].map(el => el.textContent),
        skipped: root.querySelector(".cm-skip").innerHTML };
    } finally { getTextNodes = scan; }
  });
  expect(result.scans).toBe(0);
  expect(result.marks).toEqual(["selected review"]);
  expect(result.skipped).toBe("private");
});

test("highlight restoration updates split-node indexes without rescanning unrelated content (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<p>Other paragraph.</p>".repeat(200)
    + '<p>abcdefghi<span class="cm-skip">private</span></p><p>Tail <b>bold</b>end</p>');
  const result = await page.evaluate(() => {
    ["ab", "cd", "fg", "iTail "].forEach(quote => anchorTest.add(quote));
    const original = root.textContent, scan = getTextNodes;
    let scans = 0;
    getTextNodes = () => { scans++; return scan(); };
    try {
      anchorTest.restore();
      return { scans, unchanged: root.textContent === original,
        marks: [...root.querySelectorAll("mark.cm-hl")].map(el => [el.dataset.cid, el.textContent]),
        skipped: root.querySelector(".cm-skip").innerHTML,
        nested: root.querySelectorAll("mark.cm-hl mark.cm-hl").length };
    } finally { getTextNodes = scan; }
  });
  expect(result.scans).toBe(1);
  expect(result.unchanged).toBe(true);
  expect(result.marks).toEqual([["c0", "ab"], ["c1", "cd"], ["c2", "fg"], ["c3", "i"], ["c3", "Tail "]]);
  expect(result.skipped).toBe("private");
  expect(result.nested).toBe(0);
});

test("broad highlights update many split nodes with linear index work (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<p>Unselected introduction.</p>" + Array.from({ length: 1000 }, (_, i) =>
    `<p>Prefix selected ${i}<span class="cm-skip">private</span> suffix.</p>`).join("")
    + "<p>Unselected ending.</p>");
  const result = await page.evaluate(() => {
    const text = anchorTest.text(), start = text.indexOf("selected 0"), end = text.lastIndexOf(" suffix.") + 4;
    const range = rangeFromOffsets(start, end), nodes = getTextNodes();
    let reads = 0, writes = 0;
    const index = new Proxy(nodes, {
      get(target, key) { if (/^\d+$/.test(String(key))) reads++; return Reflect.get(target, key); },
      set(target, key, value) { if (/^\d+$/.test(String(key))) writes++; return Reflect.set(target, key, value); },
    });
    const count = nodes.length;
    wrapRangeWithMark(range, "cbroad", index);
    const actual = getTextNodes();
    return { reads, writes, count,
      sameNodes: nodes.length === actual.length && nodes.every((node, i) => node === actual[i]),
      selected: [...root.querySelectorAll("mark.cm-hl")].map(el => el.textContent).join(""),
      expected: text.slice(start, end), unchanged: anchorTest.text() === text,
      skipped: [...root.querySelectorAll(".cm-skip")].every(el => el.innerHTML === "private") };
  });
  expect(result.reads + result.writes).toBeLessThan(result.count * 20);
  expect(result.sameNodes).toBe(true);
  expect(result.selected).toBe(result.expected);
  expect(result.unchanged).toBe(true);
  expect(result.skipped).toBe(true);
});

test("nested block lookup preserves smallest containment without scanning all blocks (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<section>Before <p>Inside <b>inline</b> text.</p> After</section>" + "<p>Tail.</p>".repeat(3000));
  const result = await page.evaluate(() => {
    const index = anchorTest.index(), blocks = index.blocks;
    let reads = 0, correct = true;
    index.blocks = new Proxy(blocks, { get(target, key) {
      if (/^\d+$/.test(String(key))) reads++;
      return Reflect.get(target, key);
    } });
    const pairs = [[0, 30], [9, 14], [22, 30], [0, index.text.length], [-1, 2]];
    for (let i = 0; i < 100; i++) pairs.push([30 + i * 5, 35 + i * 5]);
    for (const [start, end] of pairs) {
      let expected = null;
      for (const block of blocks) if (block.start <= start && end <= block.end
        && (!expected || block.end - block.start < expected.end - expected.start)) expected = block;
      if (cmhAnchorBlock(index, start, end) !== expected) correct = false;
    }
    return { reads, correct, queries: pairs.length };
  });
  expect(result.correct).toBe(true);
  expect(result.reads).toBeLessThan(result.queries * 30);
});

test("normalized offsets avoid identity maps and redundant per-character arrays (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<p>Text</p>");
  const result = await page.evaluate(() => {
    const bytes = map => (map.starts?.byteLength || 0) + (map.ends?.byteLength || 0)
      + (map.positions?.byteLength || 0) + (map.omitted?.byteLength || 0);
    const plain = cmhAnchorNormalize("Plain prose \u201cquote\u201d and \u2014 dash.".repeat(1000), false, true);
    const text = "A  \tB\u00a0 \nC".repeat(1000);
    const collapsed = cmhAnchorNormalize(text, false, true);
    const big = cmhAnchorNormalize(text.repeat(20), false, true);
    const sparse = cmhAnchorNormalize(("x".repeat(9998) + "  ").repeat(100), false, true);
    const boundaries = [text, text.repeat(20)].every(source => {
      const map = cmhAnchorNormalize(source, false, true);
      const points = [0, 1, 2, 3, map.text.length - 1, Math.floor(map.text.length / 2)];
      return points.every(pos => cmhAnchorNormalize(source.slice(cmhAnchorOffset(map, pos),
        cmhAnchorOffset(map, pos + 1)), false, false).text === map.text[pos]);
    });
    anchorTest.set("<p>A  \tB\u00a0 \nC \u201chello\u201d.</p>");
    const hits = anchorTest.occurrences('B C "hello"');
    return { plainBytes: bytes(plain), collapsedBytes: bytes(collapsed), bigBytes: bytes(big),
      sparseBytes: bytes(sparse),
      boundaries,
      length: text.length, matches: hits.map(hit => anchorTest.text().slice(hit.start, hit.end)) };
  });
  expect(result.plainBytes).toBe(0);
  expect(result.collapsedBytes).toBeLessThanOrEqual(result.length * 2);
  expect(result.bigBytes).toBeLessThanOrEqual(result.length * 20 * 4);
  expect(result.sparseBytes).toBeLessThanOrEqual(800);
  expect(result.boundaries).toBe(true);
  expect(result.matches).toEqual(["B\u00a0 \nC \u201chello\u201d"]);
  const unicode = await page.evaluate(() => {
    const spaces = [9, 10, 11, 12, 13, 32, 160, 5760, 8192, 8193, 8194, 8195, 8196,
      8197, 8198, 8199, 8200, 8201, 8202, 8232, 8233, 8239, 8287, 12288, 65279];
    return spaces.every(value => {
      const sep = String.fromCharCode(value).repeat(3);
      const original = "\u4e2d\ud83d\ude00A" + sep + "B\u201cC\u201d" + sep;
      anchorTest.set("<p></p>");
      root.querySelector("p").textContent = original;
      const matches = anchorTest.occurrences('A B"C"');
      return matches.length === 1 && anchorTest.text().slice(matches[0].start, matches[0].end)
        === "A" + sep + "B\u201cC\u201d"
        && cmhAnchorNormalize(original, true, true).text === original;
    });
  });
  expect(unicode).toBe(true);
});

test("already normalized prose avoids replacement passes while preserving whitespace and typography folding (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<p>Text</p>");
  const result = await page.evaluate(() => {
    const source = "Plain prose with single spaces and an emoji \ud83d\ude00.".repeat(1000);
    const replace = String.prototype.replace;
    let calls = 0, plain;
    String.prototype.replace = function (...args) { calls++; return replace.apply(this, args); };
    try { plain = cmhAnchorNormalize(source, false, true); }
    finally { String.prototype.replace = replace; }
    const spaces = [9, 10, 11, 12, 13, 160, 5760, 8192, 8193, 8194, 8195, 8196,
      8197, 8198, 8199, 8200, 8201, 8202, 8232, 8233, 8239, 8287, 12288, 65279];
    return { calls, plain: plain.text === source && plain.ends === null,
      whitespace: spaces.every(ch => cmhAnchorNormalize("A" + String.fromCharCode(ch) + "B", false, true).text === "A B"),
      doubled: cmhAnchorNormalize("A  B", false, true).text,
      typography: cmhAnchorNormalize("\u2018A\u2019 \u201cB\u201d \u2013 \u2014", false, true).text };
  });
  expect(result.calls).toBe(0);
  expect(result.plain).toBe(true);
  expect(result.whitespace).toBe(true);
  expect(result.doubled).toBe("A B");
  expect(result.typography).toBe("'A' \"B\" - -");
});

test("small-edit alignment bounds arithmetic to the admissible edit band (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<p>Text</p>");
  const result = await page.evaluate(() => {
    const old = "Context ".repeat(100), revised = old.slice(0, 400) + "z" + old.slice(401);
    const index = anchorTest.index(), min = Math.min;
    let cells = 0;
    Math.min = (...args) => { cells++; return min(...args); };
    try {
      const map = cmhAnchorEditMap(old, revised, index);
      return { cells, middle: map[400], first: map[0], last: map[799] };
    } finally { Math.min = min; }
  });
  expect(result).toMatchObject({ middle: -1, first: 0, last: 799 });
  expect(result.cells).toBeLessThan(300000);
  const differential = await page.evaluate(() => {
    function reference(a, b) {
      const width = b.length + 1, dp = new Uint32Array((a.length + 1) * width);
      for (let i = 0; i <= a.length; i++) dp[i * width] = i;
      for (let j = 0; j <= b.length; j++) dp[j] = j;
      for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
        dp[i * width + j] = Math.min(dp[(i - 1) * width + j] + 1, dp[i * width + j - 1] + 1,
          dp[(i - 1) * width + j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (dp[dp.length - 1] > Math.max(3, Math.floor(Math.max(a.length, b.length) * 0.2))) return null;
      const map = new Int32Array(a.length).fill(-1);
      let i = a.length, j = b.length;
      while (i || j) {
        if (i && j && dp[i * width + j] === dp[(i - 1) * width + j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)) {
          if (a[i - 1] === b[j - 1]) map[i - 1] = j - 1;
          i--; j--;
        } else if (i && dp[i * width + j] === dp[(i - 1) * width + j] + 1) i--;
        else j--;
      }
      return [...map];
    }
    const words = ["", "a", "ababa", "abc".repeat(40)];
    const mutations = text => [text, "x" + text, text + "x", text.slice(1),
      text.slice(0, -1), text.slice(0, 10) + "zy" + text.slice(12), "z".repeat(text.length)];
    return words.every(old => mutations(old).every(revised => {
      const actual = cmhAnchorEditMap(old, revised, anchorTest.index());
      return JSON.stringify(actual && [...actual]) === JSON.stringify(reference(old, revised));
    }));
  });
  expect(differential).toBe(true);
});

test("resolving mixed identity and quote-only roots precedes bounded evidence recapture (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<p>Setup</p>");
  const result = await page.evaluate(() => {
    const paragraphs = Array.from({ length: 3000 }, (_, i) =>
      `<p${i < 1000 && i % 100 === 0 ? ' id="stable' + i + '"' : ""}>Introduction ${i}. A selected review passage number ${i}. `
        + "Context for careful review. ".repeat(10) + ` Conclusion ${i}.</p>`);
    const html = paragraphs.join("");
    anchorTest.set(html);
    const index = anchorTest.index();
    const roots = Array.from({ length: 30 }, (_, i) => {
      const quote = `A selected review passage number ${i * 100}.`;
      const start = index.text.indexOf(quote), c = { id: "c" + i, quote, start, end: start + quote.length };
      index.budget = CMH_ANCHOR_SCAN_BUDGET;
      cmhCaptureTextAnchor(c, index);
      return c;
    });
    anchorTest.replace(roots);
    anchorTest.set("<p>New introduction.</p>" + html);
    anchorTest.resolve();
    const first = roots.filter(c => !c.detached).length;
    anchorTest.set("<p>Second introduction.</p>" + html);
    anchorTest.resolve();
    const text = anchorTest.text();
    return { chars: text.length, first, attached: roots.filter(c => !c.detached).length,
      correct: roots.every(c => text.slice(c.start, c.end) === c.quote) };
  });
  expect(result.chars).toBeGreaterThan(1000000);
  expect(result.first).toBe(30);
  expect(result.attached).toBe(30);
  expect(result.correct).toBe(true);
});

test("unverified changed-revision uniqueness cannot authorize a later surviving duplicate (CMH-REATTACH-05)", async ({ page }) => {
  const content = "Prefix with substantial context before chosen review phrase. Suffix with substantial context after.";
  await harness(page, `<p id="original">${content}</p>`);
  const result = await page.evaluate(content => {
    const c = anchorTest.add("chosen review phrase");
    const original = structuredClone(c.cmAnchor.original);
    anchorTest.set(`<p id="original">${content}</p><p id="copy">${content}</p>`);
    const index = anchorTest.index();
    index.budget = 0;
    cmhCaptureTextAnchor(c, index);
    const captured = structuredClone(c.cmAnchor);
    anchorTest.set(`<p id="copy">${content}</p>`);
    anchorTest.resolve();
    return { captured, original, c };
  }, content);
  expect(result.captured.unique).toBe(false);
  expect(result.captured.original).toEqual(result.original);
  expect(result.c.detached).toBe(true);
});

test("shared-budget refusals are distinguished from unresolved evidence (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<p>A uniquely selected review passage with enough context.</p>");
  const result = await page.evaluate(() => {
    const c = anchorTest.add("selected review passage");
    anchorTest.set("<p>Introduction.</p><p>A uniquely selected review passage with enough context.</p>");
    const original = cmhAnchorIndex;
    cmhAnchorIndex = () => { const index = original(); index.budget = 0; return index; };
    try { anchorTest.resolve(); return c; }
    finally { cmhAnchorIndex = original; }
  });
  expect(result.detached).toBe(true);
  expect(result.cmAnchor.reason).toBe("budget");
});

test("intact uniquely identified blocks recover without whole-document quote scans (CMH-REATTACH-02)", async ({ page }) => {
  await harness(page, '<p id="stable">The complete block retains its selected review passage.</p><p>Other text.</p>');
  const result = await page.evaluate(() => {
    anchorTest.add("selected review passage");
    anchorTest.set('<p>Inserted introduction.</p><p id="stable">The complete block retains its selected review passage.</p><p>Other text.</p>');
    const occurrences = cmhAnchorOccurrences;
    let scans = 0;
    cmhAnchorOccurrences = (...args) => { scans++; return occurrences(...args); };
    try {
      anchorTest.resolve();
      return { scans, c: anchorTest.comments()[0], text: anchorTest.text() };
    } finally { cmhAnchorOccurrences = occurrences; }
  });
  expect(result.scans).toBeLessThanOrEqual(6);
  expect(result.c.start).toBe(result.text.indexOf("selected review passage"));
  expect(result.c.detached).toBe(false);
});

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

test("runtime-generated identities cannot detach unchanged duplicate text (CMH-REATTACH-02)", async ({ page }) => {
  await harness(page, "<nav>Repeated</nav><h2>Repeated</h2>");
  const result = await page.evaluate(() => {
    root.querySelector("nav").id = "cmhToc0";
    root.querySelector("h2").id = "generated-heading";
    const c = anchorTest.add("Repeated"), basis = c.cmAnchor.basis;
    anchorTest.set("<nav>Repeated</nav><h2>Repeated</h2>");
    const occurrences = cmhAnchorOccurrences;
    let scans = 0;
    cmhAnchorOccurrences = (...args) => { scans++; return occurrences(...args); };
    try { return { c: anchorTest.resolve()[0], scans, sameBasis: c.cmAnchor.basis === basis }; }
    finally { cmhAnchorOccurrences = occurrences; }
  });
  expect(result.c).toMatchObject({ start: 0, end: 8, detached: false });
  expect(result.scans).toBe(0);
  expect(result.sameBasis).toBe(true);
});

test("runtime-generated block ids preserve authored ancestor evidence across heading edits (CMH-REATTACH-02)", async ({ page }) => {
  const heading = "The introduction gives reliable context. The selected brown fox jumps over the lazy dog. The conclusion stays unchanged.";
  await harness(page, `<section id="authored"><h2>${heading}</h2></section>`);
  const result = await page.evaluate(heading => {
    root.querySelector("h2").id = "generated-heading";
    const c = anchorTest.add("selected brown fox");
    const capturedId = c.cmAnchor.block.id;
    anchorTest.set(`<p>New introduction.</p><section id="authored"><h2>${heading.replace("brown fox", "brown fast fox")}</h2></section>`);
    anchorTest.resolve();
    return { capturedId, c, selected: anchorTest.text().slice(c.start, c.end) };
  }, heading);
  expect(result.capturedId).toBe("authored");
  expect(result.c.detached).toBe(false);
  expect(result.selected).toBe("selected brown fast fox");
  expect(result.c.quote).toBe("selected brown fox");
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

test("normalized historical duplicates cannot become safe merely by deleting their original (CMH-REATTACH-05)", async ({ page }) => {
  for (const [original, copy, copyTag = "p"] of [
    ['A "repeated review" remains.', "A \u201crepeated review\u201d remains."],
    ["A repeated review remains.", "A  repeated review remains."],
    ["A repeated review remains.", "A repeated review remains.", "pre"],
  ]) {
    await harness(page, `<p>${original}</p><${copyTag}>${copy}</${copyTag}>`);
    const c = await page.evaluate(({ original, copy, copyTag }) => {
      anchorTest.add(original);
      anchorTest.set(`<${copyTag}>${copy}</${copyTag}>`);
      return anchorTest.resolve()[0];
    }, { original, copy, copyTag });
    expect(c.detached).toBe(true);
  }
});

test("a unique historical block cannot substitute for the original repeated occurrence (CMH-REATTACH-05)", async ({ page }) => {
  for (const [source, quote, revised] of [
    ['<p id="budget">Budget: thirty minutes. Revised budget: thirty minutes.</p>',
      "thirty minutes.", '<p id="budget">Revised budget: thirty minutes.</p>'],
    ["<p>Original reasoning. A repeated lengthy selected review passage. Original conclusion.</p>"
      + "<p>Other reasoning. A repeated lengthy selected review passage. Other conclusion.</p>",
      "A repeated lengthy selected review passage.",
      "<p>Other reasoning. A repeated lengthy selected review passage. Other conclusion.</p>"],
  ]) {
    await harness(page, source);
    const c = await page.evaluate(({ quote, revised }) => {
      anchorTest.add(quote);
      anchorTest.set(revised);
      return anchorTest.resolve()[0];
    }, { quote, revised });
    expect(c.detached).toBe(true);
  }
});

test("occurrence-specific preserved flanks can recover an edited repeated selection (CMH-REATTACH-04)", async ({ page }) => {
  const source = "<p>" + "Stable introduction. ".repeat(5)
    + "Original reliable preceding context. selected brown fox. Original reliable following context."
    + " Stable conclusion.".repeat(5) + "</p>"
    + "<p>Other preceding context. selected brown fox. Other following context.</p>";
  await harness(page, source);
  const recovered = await page.evaluate(html => {
    const c = anchorTest.add("selected brown fox");
    anchorTest.set(html.replace("Stable introduction.", "Revised introduction.").replace("selected brown fox", "selected red fox"));
    anchorTest.resolve();
    return { c, text: anchorTest.text().slice(c.start, c.end) };
  }, source);
  expect(recovered.c.detached).toBe(false);
  expect(recovered.text).toBe("selected red fox");
});

test("excluded code occurrences still bound normalized recovery work (CMH-REATTACH-08)", async ({ page }) => {
  await harness(page, "<pre>\u201crepeated recovery target\u201d</pre>".repeat(1000));
  const result = await page.evaluate(() => {
    const index = anchorTest.index(), original = cmhAnchorBlock;
    let lookups = 0;
    cmhAnchorBlock = (...args) => { lookups++; return original(...args); };
    try {
      return { hits: cmhAnchorOccurrences(index, '"repeated recovery target"', false, true),
        lookups };
    } finally { cmhAnchorBlock = original; }
  });
  expect(result.lookups).toBeLessThanOrEqual(128);
  expect(result.hits).toBeNull();
});

test("large quote-less legacy selections survive unchanged migrated reloads (CMH-REATTACH-07)", async ({ page }) => {
  await harness(page, "<p>" + "x".repeat(5000) + "</p>");
  const result = await page.evaluate(() => {
    anchorTest.replace([{ id: "long-legacy", start: 0, end: 5000, note: "Legacy note" }]);
    anchorTest.resolve();
    anchorTest.replace(JSON.parse(JSON.stringify(anchorTest.comments())));
    anchorTest.resolve();
    const unchanged = JSON.parse(JSON.stringify(anchorTest.comments()[0]));
    anchorTest.set("<p>New prefix." + "x".repeat(5000) + "</p>");
    anchorTest.resolve();
    const revised = JSON.parse(JSON.stringify(anchorTest.comments()[0]));
    anchorTest.set("<p>" + "x".repeat(5000) + "</p>");
    anchorTest.resolve();
    return { unchanged, revised, recovered: anchorTest.comments()[0] };
  });
  expect(result.unchanged).toMatchObject({ start: 0, end: 5000, detached: false });
  expect(result.revised.detached).toBe(true);
  expect(result.recovered).toMatchObject({ start: 0, end: 5000, detached: false });
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

test("discontiguous selectors require intact text rather than approximate interval recovery (CMH-REATTACH-07)", async ({ page }) => {
  const html = "<p>Stable surrounding words before alpha bravo and stable surrounding words after.</p>";
  await harness(page, html);
  const result = await page.evaluate(original => {
    const c = anchorTest.add("alpha bravo");
    c.cmAnchor.discontiguous = true;
    delete c.start; delete c.end;
    anchorTest.set(original.replace("alpha bravo", "alpha EXTRA bravo"));
    anchorTest.resolve();
    const detached = JSON.parse(JSON.stringify(c));
    anchorTest.set(original);
    anchorTest.resolve();
    return { detached, recovered: c };
  }, html);
  expect(result.detached.detached).toBe(true);
  expect(result.detached.start).toBeUndefined();
  expect(result.detached.end).toBeUndefined();
  expect(result.recovered).toMatchObject({ start: 32, end: 43, detached: false });
  expect(result.recovered.cmAnchor.discontiguous).toBeUndefined();
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
