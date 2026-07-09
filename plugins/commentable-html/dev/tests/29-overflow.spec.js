import { test, expect } from "@playwright/test";
import { fileUrl, ready, KITCHEN_SINK } from "./helpers.js";

// The layer must never let author text run out of its box: long badges, long table
// cells, and long KQL cluster titles have to wrap within their container instead of
// overflowing (or being clipped by an ancestor's overflow:hidden). We inject the
// content inside a deliberately narrow, cm-skip host so the layer CSS is the only
// thing under test and comment offsets are untouched.
const LONG = "Draft-rev-17-whole-plan-duck-5-rounds-supercalifragilisticexpialidocious-cluster";

async function measure(page, buildInner) {
  return page.evaluate((inner) => {
    const root = document.getElementById("commentRoot");
    const host = document.createElement("div");
    host.className = "cm-skip cmh-overflow-probe";
    host.style.cssText = "width:180px;padding:0;margin:1rem 0;";
    host.innerHTML = inner;
    root.appendChild(host);
    // force layout
    void host.offsetHeight;
    const hostR = host.getBoundingClientRect();
    const targets = [...host.querySelectorAll("[data-probe]")].map((el) => {
      const r = el.getBoundingClientRect();
      return {
        tag: el.getAttribute("data-probe"),
        overflowsRight: r.right > hostR.right + 1,
        selfScrollOverflow: el.scrollWidth > el.clientWidth + 1,
        height: r.height,
      };
    });
    // a single-line reference height for the same badge styling with short text
    const ref = document.createElement("span");
    ref.className = "badge"; ref.textContent = "x";
    host.appendChild(ref);
    const refH = ref.getBoundingClientRect().height;
    host.remove();
    return { targets, refH };
  }, buildInner);
}

test.describe("boxed author content never overflows its container", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(fileUrl(KITCHEN_SINK));
    await ready(page);
  });

  test("a long .badge wraps inside its box instead of overflowing", async ({ page }) => {
    const { targets, refH } = await measure(page,
      `<span class="badge" data-probe="badge">${LONG}</span>`);
    const badge = targets.find((t) => t.tag === "badge");
    expect(badge.overflowsRight, "badge stays within its narrow container").toBe(false);
    expect(badge.selfScrollOverflow, "badge has no clipped horizontal content").toBe(false);
    expect(badge.height, "badge wrapped to more than one line").toBeGreaterThan(refH + 2);
  });

  test("a long unbroken token in a table cell wraps and the table fits its box", async ({ page }) => {
    const { targets } = await measure(page,
      `<table><tbody><tr><td data-probe="cell">${LONG}${LONG}</td></tr></tbody></table>`);
    const cell = targets.find((t) => t.tag === "cell");
    expect(cell.overflowsRight, "table cell stays within its container").toBe(false);
    expect(cell.selfScrollOverflow, "table cell has no clipped horizontal content").toBe(false);
  });

  test("a long KQL cluster title wraps and the figure is not clipped", async ({ page }) => {
    const { targets } = await measure(page,
      `<figure class="cmh-kql"><figcaption class="cmh-kql-cap">` +
      `<button type="button" class="cmh-kql-title" data-probe="title">${LONG}.kusto.windows.net</button>` +
      `<a class="cmh-kql-run" href="#">Run</a></figcaption>` +
      `<pre>Table | take 1</pre></figure>`);
    const title = targets.find((t) => t.tag === "title");
    expect(title.overflowsRight, "KQL title stays within the figure box").toBe(false);
  });
});
