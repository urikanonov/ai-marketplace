import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  openInline, addTextComment, storedComments, readDownload,
  stageInline, startStaticServer, ready, openToolbarMenu,
} from "./helpers.js";

// GH-REGRESS-EXPORT-HOTSPOT: the export path serializes user-authored comment text into the
// output HTML string and is a proven bug attractor (F2 $-replacement corruption, forged markers,
// escaping). This is a property/fuzz guard: a batch of adversarial notes ($-patterns, escaped <,
// HTML comments, closing-script tags, unicode, backticks, and literal region-marker phrases) must
// each round-trip byte-exact through Export as Portable and JSON.parse, and none may break the
// embedded-comments JSON, forge a region boundary, or corrupt the file.

const ADVERSARIAL = [
  "dollar-amp $& here",
  "dollar-group $1 and $2 and $99",
  "dollar-backtick $` end",
  "dollar-quote $' end",
  "double-dollar $$ literal",
  "combo $& $1 $` $' $$ all together",
  "escaped lt \u003c and amp & and gt >",
  "html comment open <!-- and close -->",
  "closing script tag </script> mid-note",
  "unicode emoji and accents cafe resume",
  "backticks `code` and dollar-brace ${notATemplate}",
  "forged END: commentable-html - EMBEDDED COMMENTS -->",
  "forged BEGIN: commentable-html - JS marker text",
  "kitchen sink <!-- $& </script> `x` END: commentable-html - HANDLED IDS -->",
];

function embeddedJson(html) {
  const m = html.match(/id="embeddedComments">([\s\S]*?)<\/script>/);
  expect(m, "embeddedComments block present in the export").toBeTruthy();
  return JSON.parse(m[1].trim() || "[]");
}

test("Export as Portable round-trips a batch of adversarial comment notes byte-exact (GH-REGRESS-EXPORT-HOTSPOT)", async ({ page }) => {
  await openInline(page);
  // Seed one real comment to obtain a valid comment-object template, then clone it once per
  // adversarial note with a fresh SAFE_ID_RE-compatible id, and persist the batch to localStorage.
  await addTextComment(page, "#commentRoot section p", "template note");
  const template = (await storedComments(page))[0];
  expect(template).toBeTruthy();

  const seeded = await page.evaluate(({ tmpl, notes }) => {
    const key = (document.getElementById("commentRoot") || document.body).dataset.commentKey
      || ("commentable-html:" + location.pathname);
    const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
    const mkId = (n) => {
      let s = "c";
      for (let i = 0; i < 10; i++) s += alphabet[(n * 7 + i * 13 + 5) % alphabet.length];
      return s;
    };
    const arr = notes.map((note, i) => {
      const c = JSON.parse(JSON.stringify(tmpl));
      c.id = mkId(i + 1);
      c.note = note;
      return c;
    });
    localStorage.setItem(key, JSON.stringify(arr));
    return arr.map((c) => ({ id: c.id, note: c.note }));
  }, { tmpl: template, notes: ADVERSARIAL });
  expect(seeded.length).toBe(ADVERSARIAL.length);

  await page.reload();
  await ready(page);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#btnSaveHtml").click(),
  ]);
  const html = await readDownload(download);

  // Every seeded note round-trips EXACTLY (no $-expansion, no escaping loss, no truncation).
  const items = embeddedJson(html);
  // No forged marker phrase truncated the embedded JSON: the block parses as one coherent array
  // with exactly the seeded count (a split would drop entries or fail JSON.parse above).
  expect(items.length).toBe(ADVERSARIAL.length);
  const byId = new Map(items.map((c) => [c.id, c.note]));
  for (const { id, note } of seeded) {
    expect(byId.get(id), "note for " + id + " round-trips exactly").toBe(note);
  }
});

// GH-REGRESS-EXPORT-HOTSPOT (grammar cross-test): the validator accepts region markers with any
// `=` fill count (=* grammar), including the compact single-line form. The runtime strip must
// accept the same across EVERY comment-data region, not just EMBEDDED COMMENTS, so a compact
// document exports to Plain cleanly with no comment-data leak.
function compactMarkers(html) {
  let t = html;
  for (const name of ["HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI"]) {
    t = t.replace(
      new RegExp("<!--\\s*=+\\s*BEGIN: commentable-html - " + name + "[\\s\\S]*?-->"),
      "<!-- BEGIN: commentable-html - " + name + " -->",
    );
  }
  return t;
}

test("Export as Plain strips compact-markered comment-data regions across all of them (GH-REGRESS-EXPORT-HOTSPOT)", async ({ page }) => {
  const staged = stageInline({ mutate: compactMarkers });
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/doc.html");
    await ready(page);
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSavePlainTop"),
    ]);
    const html = await readDownload(download);
    expect(html).not.toContain('id="embeddedComments"');
    expect(html).not.toContain('id="handledCommentIds"');
    expect(html).not.toContain("__commentableHtmlReady");
    expect(html).toMatch(/#commentRoot\s+table\s*\{/);
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
