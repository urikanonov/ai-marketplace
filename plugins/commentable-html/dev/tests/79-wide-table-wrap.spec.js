import { test, expect } from "@playwright/test";
import { ready, stageContent, stageDeck, fileUrl } from "./helpers.js";

// CMH-RESP-10: a wide table must not break words mid-token.
//
// `overflow-wrap: anywhere` and `overflow-wrap: break-word` break identically once a line is
// being laid out, but they differ in INTRINSIC SIZING, and that is exactly what table layout
// depends on. `anywhere` participates in min-content sizing, so every cell reports a
// min-content width of roughly ONE CHARACTER; the table layout algorithm then happily
// collapses a column to that width and shreds its text, even while other columns still have
// spare room. `break-word` is ignored for min-content, so a cell keeps its longest-word
// min-content width and the column is only broken when there is genuinely nowhere left to go.
//
// Reported against a 14-column table where the cause column rendered `NAMESPACE MOVE` as
// `NAMES` / `PACE` / `MOVE` and `computeservice-as-tvm-paros` as `computeservic` /
// `e-as-tvm-paros`.
const WIDE_TABLE = `
<h1>Wide table</h1>
<table>
<thead><tr>
<th>id</th><th>cause</th><th>service</th><th>a</th><th>b</th><th>c</th><th>d</th>
<th>e</th><th>f</th><th>g</th><th>h</th><th>i</th><th>j</th><th>k</th>
</tr></thead>
<tbody>
<tr>
<td>1</td><td>NAMESPACE MOVE</td><td>computeservice-as-tvm-paros</td>
<td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>6</td><td>7</td><td>8</td>
<td>9</td><td>10</td><td>11</td>
</tr>
<tr>
<td>2</td><td>NAMESPACE MOVE</td><td>computeservice-as-tvm-paros</td>
<td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>6</td><td>7</td><td>8</td>
<td>9</td><td>10</td><td>11</td>
</tr>
</tbody>
</table>`;

/** Width of the widest unbroken word the browser reports for a cell's min-content size. */
async function minContentWidth(page, selector) {
  return page.evaluate((sel) => {
    const cell = document.querySelector(sel);
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;";
    probe.textContent = cell.textContent.split(/\s+/).sort((a, b) => b.length - a.length)[0];
    getComputedStyle(cell);
    cell.appendChild(probe);
    const w = probe.getBoundingClientRect().width;
    probe.remove();
    return w;
  }, selector);
}

// CMH-RESP-11: `break-word` alone is not a complete fix. It is IGNORED for min-content, so a
// table whose columns cannot fit reports a min-content width larger than its container and the
// table escapes its box - pushing the WHOLE DOCUMENT sideways, which is worse than the shredding
// it cures. Every table therefore renders inside a `.cmh-table-scroll` wrapper that scrolls
// horizontally, the same containment mobile already had, now at every width and without the
// `display:block` trick (which collapses a narrow table's columns to their content width).
const UNBREAKABLE = "Z".repeat(200);
const TOKEN_TABLE = `
<h1>Unbreakable token</h1>
<table><tbody><tr><td id="tok">${UNBREAKABLE}</td></tr></tbody></table>`;
const NARROW_TABLE = `
<h1>Narrow table</h1>
<table><tbody><tr><td>alpha</td><td>beta</td></tr></tbody></table>`;

async function gotoContent(page, content, key, width) {
  const staged = stageContent(content, { key, source: key + ".html" });
  await page.setViewportSize({ width, height: 800 });
  await page.goto(fileUrl(staged.html));
  await ready(page);
}

test("a table too wide for its column scrolls in its own box, not the page (CMH-RESP-11)", async ({ page }) => {
  await gotoContent(page, TOKEN_TABLE, "cmh-token-table", 900);

  const m = await page.evaluate(() => {
    const table = document.querySelector("#commentRoot table");
    const wrap = table.parentElement;
    const doc = document.documentElement;
    return {
      wrapped: wrap.classList.contains("cmh-table-scroll"),
      wrapScrolls: wrap.scrollWidth > wrap.clientWidth + 1,
      wrapWithinRoot: wrap.getBoundingClientRect().right <=
        document.getElementById("commentRoot").getBoundingClientRect().right + 1,
      docScrollsSideways: doc.scrollWidth > doc.clientWidth + 1,
    };
  });

  expect(m.wrapped, "the table is wrapped in a horizontal scroll container").toBe(true);
  expect(m.wrapScrolls, "the over-wide table scrolls inside its wrapper").toBe(true);
  expect(m.wrapWithinRoot, "the wrapper itself stays inside the content column").toBe(true);
  expect(m.docScrollsSideways, "an over-wide table must never push the document sideways").toBe(false);
});

test("wrapping a table leaves a normal table full-width and never double-wraps (CMH-RESP-11)", async ({ page }) => {
  // The second table arrives ALREADY wrapped: author HTML is arbitrary, so the pass must adopt an
  // existing wrapper rather than nesting a second one around it.
  await gotoContent(page, NARROW_TABLE +
    `<div class="cmh-table-scroll"><table><tbody><tr><td>gamma</td><td>delta</td></tr></tbody></table></div>`,
    "cmh-narrow-table", 900);

  const m = await page.evaluate(() => {
    const tables = [...document.querySelectorAll("#commentRoot table")];
    const wraps = [...document.querySelectorAll("#commentRoot .cmh-table-scroll")];
    const first = tables[0];
    return {
      tableW: Math.round(first.getBoundingClientRect().width),
      wrapW: Math.round(first.parentElement.clientWidth),
      allWrapped: tables.every((t) => t.parentElement.classList.contains("cmh-table-scroll")),
      wrapCount: wraps.length,
      nested: wraps.some((w) => !!w.parentElement.closest(".cmh-table-scroll")),
    };
  });

  // `display:block` on the table would have collapsed these two columns to their content width.
  expect(m.tableW, "a table that fits still fills its container").toBe(m.wrapW);
  expect(m.allWrapped, "every table ends up in a scroll wrapper").toBe(true);
  expect(m.wrapCount, "exactly one wrapper per table - the pre-wrapped table is adopted").toBe(2);
  expect(m.nested, "wrappers are never nested").toBe(false);
});

test("a table wrapper takes keyboard focus only while it actually scrolls (CMH-RESP-11)", async ({ page }) => {
  // A scrollable region that cannot be reached by keyboard is unusable without a mouse, but a
  // focusable wrapper on a table that fits is a dead tab stop - so the state must track the
  // measurement, including across a resize.
  await gotoContent(page, WIDE_TABLE, "cmh-a11y-table", 1400);

  const wrap = page.locator("#commentRoot .cmh-table-scroll").first();
  const scrolls = () => wrap.evaluate((w) => w.scrollWidth > w.clientWidth + 1);

  expect(await scrolls(), "the 14-column table fits a 1400px viewport").toBe(false);
  expect(await wrap.getAttribute("tabindex"), "a table that fits adds no dead tab stop").toBe(null);
  expect(await wrap.getAttribute("data-cmh-scroll-a11y"), "nothing is marked while it fits").toBe(null);

  await page.setViewportSize({ width: 500, height: 800 });
  // The state is re-measured off a ResizeObserver, so these assertions poll rather than sampling
  // once - reading the attributes in the same tick as the resize is a race, not a failure.
  await expect(wrap, "once it scrolls it is reachable by keyboard").toHaveAttribute("tabindex", "0");
  await expect(wrap, "the layer marks the affordance it owns").toHaveAttribute("data-cmh-scroll-a11y", /tabindex/);
  await expect(wrap, "a focusable scroll region is named").toHaveAttribute("aria-label", /\S/);
  await expect(wrap, "and says that it scrolls").toHaveAttribute("aria-description", /scroll/i);
  expect(await scrolls(), "the table really is wider than its box at 500px").toBe(true);
});

test("a table in a FLEX parent keeps its width and is not collapsed (CMH-RESP-11)", async ({ page }) => {
  // A scroll container's automatic minimum size is 0, so a width-less wrapper in a flex parent (a
  // gallery card row, a deck slide) would shrink to min-content and collapse the table - the very
  // failure that ruled out putting `display: block` on the table itself. Measured at 900px wide:
  // 900px -> 252px before the wrapper was given an explicit width.
  await gotoContent(page,
    `<h1>Flex</h1><div style="display:flex;flex-wrap:wrap;">${NARROW_TABLE}</div>` + NARROW_TABLE,
    "cmh-flex-table", 1000);

  const m = await page.evaluate(() => {
    const tables = [...document.querySelectorAll("#commentRoot table")];
    return tables.map((t) => ({
      w: Math.round(t.getBoundingClientRect().width),
      wrapW: Math.round(t.parentElement.clientWidth),
    }));
  });

  expect(m.length, "both tables are present").toBe(2);
  expect(m[0].w, "a table in a flex parent still fills its scroll box").toBe(m[0].wrapW);
  expect(m[0].w, "and is not collapsed towards min-content").toBe(m[1].w);
});

test("a table added after startup is contained too (CMH-RESP-11)", async ({ page }) => {
  // Author content scripts run AFTER the layer, so a document that builds a table at runtime must
  // not escape containment and push the page sideways again.
  await gotoContent(page, `<h1>Late</h1><p>before</p>`, "cmh-late-table", 900);

  await page.evaluate((token) => {
    const host = document.createElement("section");
    host.innerHTML = `<table><tbody><tr><td>${token}</td></tr></tbody></table>`;
    document.getElementById("commentRoot").appendChild(host);
  }, "Q".repeat(200));

  const wrap = page.locator("#commentRoot .cmh-table-scroll");
  await expect(wrap, "the late table is wrapped by the observer").toHaveCount(1);
  await expect(wrap, "and its scroll affordance is measured").toHaveAttribute("tabindex", "0");
  const docScrolls = await page.evaluate(() =>
    document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(docScrolls, "a late table must not push the document sideways either").toBe(false);
});

test("an author-labelled wrapper keeps its label AND still gets the tab stop (CMH-RESP-11)", async ({ page }) => {
  // Ownership is per-attribute: refusing to touch an element the author labelled would leave a
  // scrolling region no keyboard user can reach, which is the barrier this exists to remove.
  await gotoContent(page,
    `<h1>Authored</h1><div class="cmh-table-scroll" aria-label="Quarterly budget">` +
    `<table><tbody><tr><td>${"W".repeat(200)}</td></tr></tbody></table></div>`,
    "cmh-authored-wrap", 900);

  const wrap = page.locator("#commentRoot .cmh-table-scroll").first();
  await expect(wrap, "the author's own label is never clobbered").toHaveAttribute("aria-label", "Quarterly budget");
  await expect(wrap, "but the scrolling region is still keyboard reachable").toHaveAttribute("tabindex", "0");
  const owned = await wrap.getAttribute("data-cmh-scroll-a11y");
  expect(owned, "and only the attributes the layer added are marked as its own").not.toContain("aria-label");
  expect(owned, "tabindex among them").toContain("tabindex");
});

test("an author table inside a cm-skip host is contained too (CMH-RESP-11)", async ({ page }) => {
  // `.cm-skip` only means "not part of the comment text-offset coordinate system"; it is used by
  // AUTHOR content (widgets, embedded hosts) as well, and the layer itself never creates a table -
  // so skipping cm-skip would leave a real author table free to push the page sideways.
  await gotoContent(page,
    `<h1>Skip host</h1><div class="cm-skip"><table><tbody><tr>` +
    `<td>${"S".repeat(200)}</td></tr></tbody></table></div>`,
    "cmh-skip-table", 900);

  const m = await page.evaluate(() => {
    const t = document.querySelector("#commentRoot .cm-skip table");
    return {
      wrapped: !!t.closest(".cmh-table-scroll"),
      docScrolls: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    };
  });
  expect(m.wrapped, "a table in an author cm-skip host is wrapped").toBe(true);
  expect(m.docScrolls, "and does not push the document sideways").toBe(false);
});

test("a table's grid placement survives being wrapped (CMH-RESP-11)", async ({ page }) => {
  // The WRAPPER becomes the layout item, so placement the author put on the table would silently
  // stop applying unless it is carried across.
  await gotoContent(page,
    `<h1>Grid</h1><div style="display:grid;grid-template-columns:100px 100px 100px 100px;">` +
    `<div>a</div><table style="grid-column:2 / 4;"><tbody><tr><td>x</td></tr></tbody></table></div>`,
    "cmh-grid-table", 1000);

  const m = await page.evaluate(() => {
    const t = document.querySelector("#commentRoot table");
    const wrap = t.parentElement;
    return {
      wrapCol: getComputedStyle(wrap).gridColumnStart + " / " + getComputedStyle(wrap).gridColumnEnd,
      wrapW: Math.round(wrap.getBoundingClientRect().width),
    };
  });
  expect(m.wrapCol, "the wrapper takes over the table's grid placement").toBe("2 / 4");
  expect(m.wrapW, "so the table still spans two 100px columns").toBe(200);
});

test("arrow keys scroll a focused table box instead of changing deck slides (CMH-RESP-11)", async ({ page }) => {
  // Making the wrapper focusable is only useful if the arrow keys actually reach it: in a deck the
  // arrows change slides, so a focused scroll region has to own them or the clipped columns are
  // unreachable by keyboard (WCAG 2.1.1).
  const cells = [];
  for (let i = 0; i < 24; i++) cells.push("<td>columnvalue" + i + "0123456789</td>");
  const wide = "<table><tbody><tr>" + cells.join("") + "</tr></tbody></table>";
  const staged = stageDeck(
    '<section class="slide active"><h2>One</h2>' + wide + "</section>" +
    '<section class="slide"><h2>Two</h2></section>', { key: "cmh-deck-table" });
  await page.setViewportSize({ width: 900, height: 700 });
  await page.goto(fileUrl(staged.html));
  await ready(page);

  const wrap = page.locator("#commentRoot .cmh-table-scroll").first();
  await expect(wrap, "the deck table scrolls, so it takes a tab stop").toHaveAttribute("tabindex", "0");

  await wrap.focus();
  const before = await page.evaluate(() => ({
    left: document.querySelector("#commentRoot .cmh-table-scroll").scrollLeft,
    slide: [...document.querySelectorAll(".slide")].findIndex((s) => s.classList.contains("active")),
  }));
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(150);
  const after = await page.evaluate(() => ({
    left: document.querySelector("#commentRoot .cmh-table-scroll").scrollLeft,
    slide: [...document.querySelectorAll(".slide")].findIndex((s) => s.classList.contains("active")),
  }));

  expect(before.slide, "starts on the first slide").toBe(0);
  expect(after.slide, "the deck must NOT advance while a scroll region has focus").toBe(0);
  expect(after.left, "the arrow key scrolls the table instead").toBeGreaterThan(before.left);
});

test("removing a table cleans up its wrapper, but an author mount point survives (CMH-RESP-11)", async ({ page }) => {
  // Our own emptied wrapper is dead weight carrying margins (a blank gap); an author's empty
  // `.cmh-table-scroll` may be a mount point a later script fills, so it must be left alone.
  await gotoContent(page,
    '<h1>Cleanup</h1><table><tbody><tr><td>a</td></tr></tbody></table>' +
    '<div id="mount" class="cmh-table-scroll"></div>',
    "cmh-cleanup-table", 900);

  const before = await page.evaluate(() =>
    document.querySelectorAll("#commentRoot .cmh-table-scroll").length);
  expect(before, "the real table is wrapped; the author mount point is left as-is").toBe(2);

  await page.evaluate(() => { document.querySelector("#commentRoot table").remove(); });
  await expect.poll(async () => page.evaluate(() =>
    document.querySelectorAll("#commentRoot .cmh-table-scroll").length),
  { message: "the emptied layer wrapper is pruned" }).toBe(1);

  const mountAlive = await page.evaluate(() => !!document.getElementById("mount"));
  expect(mountAlive, "an author's empty mount point is never pruned").toBe(true);
});

test("a regenerated caption refreshes the wrapper's own label (CMH-RESP-11)", async ({ page }) => {
  // Ownership is by VALUE, not by mere presence: once we set `aria-label`, "is it set?" is true
  // forever, so a caption changed at runtime would otherwise leave AT reading the old one.
  await gotoContent(page,
    '<h1>Caption</h1><table><caption>First caption</caption><tbody><tr>' +
    '<td>' + "C".repeat(200) + '</td></tr></tbody></table>',
    "cmh-caption-table", 900);

  const wrap = page.locator("#commentRoot .cmh-table-scroll").first();
  await expect(wrap, "named from the caption").toHaveAttribute("aria-label", /First caption/);

  await page.evaluate(() => {
    document.querySelector("#commentRoot table caption").textContent = "Second caption";
  });
  // Re-measured on a real resize; the point under test is that the refresh REPLACES our own stale
  // value instead of treating its mere presence as an author-owned label.
  await page.setViewportSize({ width: 880, height: 800 });
  await expect(wrap, "the label follows the caption").toHaveAttribute("aria-label", /Second caption/);
});

test("a wide table does not break words mid-token (CMH-RESP-10)", async ({ page }) => {
  const staged = stageContent(WIDE_TABLE, { key: "cmh-wide-table", source: "wide-table.html" });
  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto(fileUrl(staged.html));
  await ready(page);

  const cause = "#commentRoot tbody tr:first-child td:nth-child(2)";
  const service = "#commentRoot tbody tr:first-child td:nth-child(3)";

  // The property itself: `anywhere` is what collapses the min-content width to one character.
  const wrap = await page.$eval(cause, (el) => getComputedStyle(el).overflowWrap);
  expect(wrap, "table cells must not use overflow-wrap:anywhere, which shreds intrinsic sizing")
    .not.toBe("anywhere");

  // And the observable consequence: each cell must be at least as wide as its longest word,
  // so the word is never split. This is what a reader actually sees.
  for (const [name, sel] of [["cause", cause], ["service", service]]) {
    const longest = await minContentWidth(page, sel);
    const box = await page.locator(sel).boundingBox();
    expect(box.width, `${name} column collapsed below its longest word and broke it mid-token`)
      .toBeGreaterThanOrEqual(longest - 1);
  }
});
