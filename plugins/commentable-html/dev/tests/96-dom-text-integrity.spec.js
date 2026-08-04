import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import path from "path";
import { fileUrl, ready, stageContent, stageDeck, addTextComment, routeMermaidLocal, EXAMPLES, PYTHON, SKILL } from "./helpers.js";

// CMH-CONTENT-21: every runtime DOM mutation inside #commentRoot is TEXT-NEUTRAL on an unedited
// document. The sort bug (#952, CMH-CONTENT-20) appended rows instead of permuting them through
// their slots, stranding the whitespace text nodes an author left between them and silently
// drifting the document/section content hashes. This spec is the audit that closed #977: it pins
// every other runtime path that moves or injects nodes in the content root against the SAME
// document hash the validated stamp is bound to.

// The Python-side hasher (tools/authoring/section_hash.py document_content_hash) reads the SOURCE
// FILE, so comparing it to the live runtime hash catches any LOAD-TIME transform that changed the
// hashed text - the "before" the page itself cannot show, since the transforms run before any
// script can read a hash.
const HASH_SRC = [
  "import sys",
  "sys.path.insert(0, 'tools')",
  "from authoring.section_hash import document_content_hash",
  "print(document_content_hash(open(sys.argv[1], encoding='utf-8').read()) or '')",
].join("\n");

function sourceHash(htmlPath) {
  return execFileSync(PYTHON, ["-c", HASH_SRC, path.resolve(htmlPath)], { cwd: SKILL, encoding: "utf8" }).trim();
}

const docHash = (page) => page.evaluate(() => window.__cmhReview.docHash());

async function openStaged(page, content, key) {
  const staged = stageContent(content, { key });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}

test.describe("runtime DOM mutations are text-neutral (CMH-CONTENT-21)", () => {
  test("the table-scroll wrapper does not move authored text", async ({ page }) => {
    const staged = await openStaged(page, [
      "<h1>Wide table</h1>",
      "<p>Intro prose.</p>",
      "<table>",
      "  <thead>",
      "    <tr><th>Name</th><th>Count</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr><td>Bravo</td><td>2</td></tr>",
      "    <tr><td>Alpha</td><td>1</td></tr>",
      "  </tbody>",
      "</table>",
      "<p>Trailing prose.</p>",
    ].join("\n"), "cmh-audit-tablescroll");
    // The wrapper really was injected (else this would pass on a no-op).
    await expect(page.locator(".cmh-table-scroll[data-cmh-wrap] > table")).toHaveCount(1);
    expect(await docHash(page)).toBe(sourceHash(staged.html));
  });

  test("checklist control injection does not move authored text", async ({ page }) => {
    const staged = await openStaged(page, [
      "<h1>Checklist</h1>",
      "<ul data-cmh-checklist=\"audit\" data-cmh-checklist-label=\"Audit\">",
      "  <li data-cmh-item=\"one\" data-cmh-state=\"blank\">First item</li>",
      "  <li data-cmh-item=\"two\" data-cmh-state=\"check\">Second item</li>",
      "</ul>",
      "<table data-cmh-checklist=\"rows\" data-cmh-checklist-label=\"Rows\">",
      "  <thead>",
      "    <tr><th>State</th><th>Task</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr data-cmh-item=\"r1\" data-cmh-state=\"blank\"><td data-cmh-state-cell></td><td>Row one</td></tr>",
      "    <tr data-cmh-item=\"r2\" data-cmh-state=\"cross\"><td data-cmh-state-cell>status:</td><td>Row two</td></tr>",
      "  </tbody>",
      "</table>",
    ].join("\n"), "cmh-audit-checklist");
    await expect(page.locator("button.cmh-check")).toHaveCount(4);
    // The second state cell carries AUTHORED text, so the button is prepended in front of real
    // hashed prose rather than into an empty cell - the case that would expose a reorder.
    await expect(page.locator("[data-cmh-item=\"r2\"] [data-cmh-state-cell]")).toContainText("status:");
    expect(await docHash(page)).toBe(sourceHash(staged.html));
    // Toggling a control is a state change, not a text change.
    const before = await docHash(page);
    await page.locator("button.cmh-check").first().click();
    expect(await docHash(page)).toBe(before);
  });

  test("editable notes do not move authored text", async ({ page }) => {
    const staged = await openStaged(page, [
      "<h1>Notes</h1>",
      "<p>Before the note.</p>",
      "<div data-cmh-note=\"n1\" data-cmh-note-label=\"Reviewer note\">Authored note text</div>",
      "<p>After the note.</p>",
    ].join("\n"), "cmh-audit-notes");
    await expect(page.locator("textarea.cmh-note-input")).toHaveCount(1);
    expect(await docHash(page)).toBe(sourceHash(staged.html));
    const before = await docHash(page);
    await page.locator("textarea.cmh-note-input").fill("edited by the reviewer");
    expect(await docHash(page)).toBe(before);
  });

  test("the code-line gutter and fallback highlighter do not move authored text", async ({ page }) => {
    const staged = await openStaged(page, [
      "<h1>Code</h1>",
      "<pre><code class=\"language-js\">const a = 1;",
      "const b = a + 2;",
      "",
      "function go() { return b; }",
      "</code></pre>",
    ].join("\n"), "cmh-audit-code");
    await expect(page.locator(".cmh-code-gutter")).toHaveCount(1);
    await expect(page.locator("pre code .cmh-code-kw").first()).toBeVisible();
    expect(await docHash(page)).toBe(sourceHash(staged.html));
  });

  test("a cm-skip draggable board is hash-invisible, and Reset moves restores a plain board", async ({ page }) => {
    const board = (extraClass) => [
      "<div class=\"" + extraClass + "\" data-cm-widget=\"board\" data-cm-draggable aria-label=\"Board\"",
      "     style=\"display:flex;gap:16px;align-items:flex-start;\">",
      "  <div data-cm-slot=\"Todo\" data-cm-part=\"col-todo\" data-cm-part-label=\"Todo column\"",
      "       style=\"width:220px;min-height:260px;border:1px solid #999;padding:8px;\">",
      "    <strong>Todo</strong>",
      "    <article data-cm-part=\"card-a\" data-cm-part-label=\"Card A\"",
      "             style=\"border:1px solid #bbb;padding:8px;margin:6px 0;\">Card A</article>",
      "    <article data-cm-part=\"card-b\" data-cm-part-label=\"Card B\"",
      "             style=\"border:1px solid #bbb;padding:8px;margin:6px 0;\">Card B</article>",
      "  </div>",
      "  <div data-cm-slot=\"Done\" data-cm-part=\"col-done\" data-cm-part-label=\"Done column\"",
      "       style=\"width:220px;min-height:260px;border:1px solid #999;padding:8px;\">",
      "    <strong>Done</strong>",
      "  </div>",
      "</div>",
    ].join("\n");

    const staged = await openStaged(page, "<h1>Board</h1>\n" + board("cm-skip"), "cmh-audit-widget-skip");
    expect(await docHash(page)).toBe(sourceHash(staged.html));
    const skipBefore = await docHash(page);
    await dragCard(page, "[data-cm-part=\"card-a\"]", "[data-cm-slot=\"Done\"]");
    await expect(page.locator("[data-cm-slot=\"Done\"] [data-cm-part=\"card-a\"]")).toHaveCount(1);
    // A cm-skip board is excluded from the hashed text entirely, so even a real move is invisible.
    expect(await docHash(page)).toBe(skipBefore);

    const plain = await openStaged(page, "<h1>Board</h1>\n" + board("audit-board"), "cmh-audit-widget-plain");
    expect(await docHash(page)).toBe(sourceHash(plain.html));
    const before = await docHash(page);
    await dragCard(page, "[data-cm-part=\"card-a\"]", "[data-cm-slot=\"Done\"]");
    await expect(page.locator("[data-cm-slot=\"Done\"] [data-cm-part=\"card-a\"]")).toHaveCount(1);
    // A move on a HASHED board is a real content change (the arrangement IS the content), so the
    // hash is expected to move - that is the documented, intentional exception.
    expect(await docHash(page)).not.toBe(before);
    // ...but it must be fully reversible: Reset moves puts every recorded child back in its load
    // order, including the whitespace between the cards, so the hash returns EXACTLY to the load
    // value. An append-style restore would leave the cards textually adjacent and never recover.
    await page.locator("button.cm-widget-reset").first().click();
    await expect(page.locator("[data-cm-slot=\"Todo\"] [data-cm-part=\"card-a\"]")).toHaveCount(1);
    expect(await docHash(page)).toBe(before);
  });

  test("deck navigation and the overview grid do not move authored text", async ({ page }) => {
    const staged = stageDeck([
      "<section class=\"slide active\" data-slide-id=\"s1\"><h2>First slide</h2><p>Alpha prose.</p></section>",
      "<section class=\"slide\" data-slide-id=\"s2\"><h2>Second slide</h2><p>Bravo prose.</p></section>",
      "<section class=\"slide\" data-slide-id=\"s3\"><h2>Third slide</h2><p>Charlie prose.</p></section>",
    ].join("\n"), { key: "cmh-audit-deck" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const before = await docHash(page);
    expect(before).toBe(sourceHash(staged.html));
    await page.evaluate(() => window.__cmhDeck.showSlideById("s3"));
    // Prove the navigation and the overview actually happened, so neither assertion can pass on a
    // no-op if the shortcut is ever remapped or the slide id lookup breaks.
    expect(await page.evaluate(() => window.__cmhDeck.activeSlideId())).toBe("s3");
    expect(await docHash(page)).toBe(before);
    await page.locator(".cmh-deck-nav").getByRole("button", { name: "Slide overview", exact: true }).click();
    const overview = page.locator(".cmh-deck-overview");
    await expect(overview).toBeVisible();
    await expect(overview.locator(".cmh-deck-overview-card")).toHaveCount(3);
    expect(await docHash(page)).toBe(before);
  });

  // The shared guard itself (00-preamble.js cmhPermuteChildrenInSlots / cmhPermutedChildNodes):
  // sorting must leave the authored whitespace text nodes at the SAME child positions, not just
  // hash the same. The structural assertion is what an append-style reorder breaks first.
  test("sorting permutes rows through their slots, leaving authored whitespace in place", async ({ page }) => {
    const staged = await openStaged(page, [
      "<h1>Sortable</h1>",
      "<table>",
      "  <thead>",
      "    <tr><th>Name</th><th>Count</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr><td>Bravo</td><td>2</td></tr>",
      "    <tr><td>Alpha</td><td>1</td></tr>",
      "    <tr><td>Charlie</td><td>3</td></tr>",
      "  </tbody>",
      "</table>",
    ].join("\n"), "cmh-audit-sortguard");
    const shape = () => page.evaluate(() => Array.prototype.map.call(
      document.querySelector("table.cmh-sortable tbody").childNodes,
      (n) => (n.nodeType === 3 ? "ws:" + JSON.stringify(n.nodeValue) : n.nodeName)).join("|"));
    const beforeShape = await shape();
    expect(beforeShape).toContain("ws:");
    const before = await docHash(page);
    await page.locator("table.cmh-sortable th .cmh-sort-ctrl").first().click();
    await expect(page.locator("table.cmh-sortable tbody tr td:first-child"))
      .toHaveText(["Alpha", "Bravo", "Charlie"]);
    expect(await shape()).toBe(beforeShape);
    expect(await docHash(page)).toBe(before);
    expect(await docHash(page)).toBe(sourceHash(staged.html));
  });

  // CMH-SEC-02 alignment: the persisted sort map is re-homed onto a null-prototype object like the
  // checklist and notes state maps, so a property READ can never fall through to Object.prototype.
  // The pollution is installed BEFORE the layer runs and under the exact key the runtime generates
  // (`<idx>::<header-sig>`), and non-enumerably, so `Object.keys` still sees an empty map and only a
  // direct read can reach it - which is precisely the fall-through this convention closes. On a
  // plain `{}` state the runtime would inherit that value and silently sort the table at load.
  test("a polluted Object.prototype cannot inject a persisted sort", async ({ page }) => {
    const content = [
      "<h1>Sortable</h1>",
      "<table>",
      "  <thead>",
      "    <tr><th>Name</th><th>Count</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr><td>Bravo</td><td>2</td></tr>",
      "    <tr><td>Alpha</td><td>1</td></tr>",
      "    <tr><td>Charlie</td><td>3</td></tr>",
      "  </tbody>",
      "</table>",
    ].join("\n");
    const staged = stageContent(content, { key: "cmh-audit-sortproto2" });
    await page.addInitScript(() => {
      Object.defineProperty(Object.prototype, "0::Name|Count", {
        value: { col: 0, dir: "desc" }, configurable: true,
      });
    });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // Untouched authored order - NOT the descending order the inherited value asks for.
    await expect(page.locator("table.cmh-sortable tbody tr td:first-child"))
      .toHaveText(["Bravo", "Alpha", "Charlie"]);
    expect(await docHash(page)).toBe(sourceHash(staged.html));
  });

  // The same convention against a crafted STORED payload. Not exploitable on its own (the runtime
  // only ever reads generated keys), so this is a regression guard for the convention rather than a
  // red-first fix - the test above is the one that observes the null prototype directly.
  test("a crafted ::tableSort payload cannot pollute Object.prototype", async ({ page }) => {
    const content = [
      "<h1>Sortable</h1>",
      "<table>",
      "  <thead>",
      "    <tr><th>Name</th><th>Count</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr><td>Bravo</td><td>2</td></tr>",
      "    <tr><td>Alpha</td><td>1</td></tr>",
      "  </tbody>",
      "</table>",
    ].join("\n");
    const staged = await openStaged(page, content, "cmh-audit-sortproto");
    // Written as RAW JSON, not an object literal: `{ __proto__: ... }` in JS SETS the prototype
    // instead of creating an own key, so JSON.stringify would drop it and the test would assert
    // nothing. JSON.parse, by contrast, produces a genuine own "__proto__" property.
    await page.evaluate(() => localStorage.setItem("cmh-audit-sortproto::tableSort",
      '{"__proto__":{"col":0,"dir":"asc","polluted":"yes"},'
      + '"constructor":{"col":1,"dir":"desc","polluted":"yes"}}'));
    await page.goto(fileUrl(staged.html));
    await ready(page);
    expect(await page.evaluate(() => [
      Object.prototype.polluted, Object.prototype.dir, ({}).polluted,
    ])).toEqual([undefined, undefined, undefined]);
    // The document still behaves: the crafted keys match no table, so nothing is pre-sorted, and a
    // real sort still works and stays text-neutral.
    await expect(page.locator("table.cmh-sortable tbody tr td:first-child")).toHaveText(["Bravo", "Alpha"]);
    const before = await docHash(page);
    await page.locator("table.cmh-sortable th .cmh-sort-ctrl").first().click();
    await expect(page.locator("table.cmh-sortable tbody tr td:first-child")).toHaveText(["Alpha", "Bravo"]);
    expect(await docHash(page)).toBe(before);
  });

  // The LOAD-TIME catch-all: every SHIPPED document is loaded and its live hash compared to the
  // Python hash of the file on disk. This covers the whole runtime at once - the six paths above
  // plus every other load-time transform (TOC, section-review badges, callouts, image and link
  // affordances, charts, diagrams, KQL) - so a NEW stranding mutation is caught even though nobody
  // thought to add a case for it. It cannot see an EVENT-driven pass, though: the print appendix
  // above only fires on `beforeprint`, which is why it needs its own explicit trigger test, and why
  // any future observer/event pass does too.
  // The print appendix (83-print.js) is the one runtime pass that appends REAL prose to the content
  // root: on beforeprint it materializes every open comment as an article at the end of #commentRoot.
  // It is layer chrome, so it must not count as document text - but it cannot wear cm-skip, because
  // the print stylesheet hides `body > .cm-skip` and a document with no #commentRoot roots the layer
  // at <body>, which would hide the appendix from the very print it exists for.
  test("materializing the print appendix does not move the document hash", async ({ page }) => {
    const staged = await openStaged(page, [
      "<h1>Printable</h1>",
      "<p>Some prose worth commenting on.</p>",
    ].join("\n"), "cmh-audit-print");
    expect(await docHash(page)).toBe(sourceHash(staged.html));
    await addTextComment(page, "#commentRoot p", "a note that must not enter the document text");
    const before = await docHash(page);
    await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
    await expect(page.locator("#commentRoot #cmhPrintComments")).toHaveCount(1);
    await expect(page.locator("#cmhPrintComments")).toContainText("must not enter the document text");
    expect(await docHash(page)).toBe(before);
    expect(await docHash(page)).toBe(sourceHash(staged.html));
    await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
    expect(await docHash(page)).toBe(before);
  });

  // Same class, one level up: the appendix must be resolved by IDENTITY, not by id. An author
  // element that happens to carry id="cmhPrintComments" was treated as the layer's own - its
  // content overwritten on beforeprint and the element DELETED on afterprint (or immediately, when
  // the document has no comments) - and, never having been registered as layer chrome, its authored
  // prose also moved the document hash.
  test("an authored element carrying the appendix id is neither clobbered nor hashed away", async ({ page }) => {
    const staged = await openStaged(page, [
      "<h1>Printable</h1>",
      "<p>Some prose worth commenting on.</p>",
      "<section id=\"cmhPrintComments\">Authored prose that must survive a print.</section>",
    ].join("\n"), "cmh-audit-print-spoof");
    const before = await docHash(page);
    expect(before).toBe(sourceHash(staged.html));
    await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
    await expect(page.locator("#commentRoot section#cmhPrintComments")).toContainText("must survive a print");
    expect(await docHash(page)).toBe(before);
    await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
    await expect(page.locator("#commentRoot section#cmhPrintComments")).toContainText("must survive a print");
    expect(await docHash(page)).toBe(before);
    // And with a comment present the layer still gets its OWN appendix, alongside the author's.
    await addTextComment(page, "#commentRoot p", "a note that must not enter the document text");
    const withComment = await docHash(page);
    await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
    await expect(page.locator("#commentRoot section#cmhPrintComments")).toContainText("must survive a print");
    // Ours is a SECOND element that yields the id rather than duplicating it, so the author's
    // element is still the only `#cmhPrintComments` in the document.
    await expect(page.locator("#commentRoot .cmh-print-comments")).toContainText("must not enter the document text");
    await expect(page.locator("#cmhPrintComments")).toHaveCount(1);
    expect(await docHash(page)).toBe(withComment);
    expect(await docHash(page)).toBe(before);
  });

  // A non-map payload used to be ACCEPTED (`typeof [] === "object"`), and an array silently ate the
  // reader's sort: string keys written onto it are dropped by JSON.stringify, so the sort never
  // survived a reload. Re-homing through _tsNullProto discards it instead.
  test("an array ::tableSort payload is discarded, so a sort still persists across a reload", async ({ page }) => {
    const staged = await openStaged(page, [
      "<h1>Sortable</h1>",
      "<table>",
      "  <thead>",
      "    <tr><th>Name</th><th>Count</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr><td>Bravo</td><td>2</td></tr>",
      "    <tr><td>Alpha</td><td>1</td></tr>",
      "  </tbody>",
      "</table>",
    ].join("\n"), "cmh-audit-sortarray");
    await page.evaluate(() => localStorage.setItem("cmh-audit-sortarray::tableSort", '["not","a","map"]'));
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await page.locator("table.cmh-sortable th .cmh-sort-ctrl").first().click();
    await expect(page.locator("table.cmh-sortable tbody tr td:first-child")).toHaveText(["Alpha", "Bravo"]);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(page.locator("table.cmh-sortable tbody tr td:first-child")).toHaveText(["Alpha", "Bravo"]);
    expect(await docHash(page)).toBe(sourceHash(staged.html));
  });

  test("the shipped report-triage.html hashes the same live as on disk", hashesOnDisk("report-triage.html"));
  test("the shipped report-checklist.html hashes the same live as on disk", hashesOnDisk("report-checklist.html"));
  test("the shipped report-notes.html hashes the same live as on disk", hashesOnDisk("report-notes.html"));
  test("the shipped report-metrics.html hashes the same live as on disk", hashesOnDisk("report-metrics.html"));
  test("the shipped report-community-garden.html hashes the same live as on disk", hashesOnDisk("report-community-garden.html"));
  test("the shipped report-taxi.html hashes the same live as on disk", hashesOnDisk("report-taxi.html"));
  test("the shipped deck-showcase.html hashes the same live as on disk", hashesOnDisk("deck-showcase.html"));
});

// Written as a factory so each test carries a LITERAL title the spec can name (a title built by
// concatenation inside a loop is invisible to scripts/check_spec_test_refs.py).
function hashesOnDisk(name) {
  return async ({ page }) => {
    const file = path.join(EXAMPLES, name);
    // The shipped examples import mermaid from jsDelivr; serve it from the vendored copy and deny
    // every other remote host, so this coverage is hermetic like the rest of the suite.
    await routeMermaidLocal(page);
    await page.goto(fileUrl(file));
    await ready(page);
    expect(await docHash(page)).toBe(sourceHash(file));
  };
}

async function dragCard(page, cardSelector, slotSelector) {
  const card = page.locator(cardSelector);
  await card.scrollIntoViewIfNeeded();
  const from = await card.boundingBox();
  const slot = page.locator(slotSelector);
  await slot.scrollIntoViewIfNeeded();
  const to = await slot.boundingBox();
  // Grab near the card's LEFT edge, not its centre: hovering a part pops the floating
  // "Comment on this element" button over the middle of it, and a pointerdown on that button is
  // (correctly) not a drag start.
  await page.mouse.move(from.x + 24, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + Math.min(to.height - 12, 80), { steps: 12 });
  await page.mouse.up();
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
}
