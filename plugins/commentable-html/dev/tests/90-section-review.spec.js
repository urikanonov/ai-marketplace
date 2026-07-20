// Section review tracking (CMH-REVIEW-01..08). Hermetic: file:// documents, external network
// denied, built dist consumed via stageContent. See docs/testing-guidelines.md.
import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { spawnSync } from "child_process";
import { fileURLToPath } from "url";
import {
  stageContent, fileUrl, ready, denyExternalNetwork, installClipboardCapture,
  addTextComment, openToolbarMenu, readDownload, DEV, SKILL, PYTHON,
} from "./helpers.js";

const CONTENT = `
<section><h1 id="rv-title">Review Demo</h1><p>Intro paragraph for the review demo.</p></section>
<section><h2 id="rv-alpha">Alpha</h2><p id="rv-alpha-body">Alpha section body text that is long enough to select.</p></section>
<section><h2 id="rv-beta">Beta</h2><p id="rv-beta-body">Beta section body text goes here.</p></section>
<section><h2 id="rv-gamma">Gamma</h2><p id="rv-gamma-body">Gamma section body text goes here.</p></section>
`;

async function openReviewDoc(page) {
  await installClipboardCapture(page);
  await denyExternalNetwork(page);
  page.on("dialog", (d) => d.accept()); // single-comment delete uses confirm()
  await page.setViewportSize({ width: 1400, height: 900 }); // wide: the side-TOC renders
  const { html } = stageContent(CONTENT, { key: "cmh-review-e2e", source: "review-e2e.html" });
  await page.goto(fileUrl(html));
  await ready(page);
  return html;
}

const stateOf = (page, id) => page.evaluate((i) => window.__cmhReview.stateOf(i), id);
const refresh = (page) => page.evaluate(() => window.__cmhReview.refresh());

test.describe("section review tracking", () => {
  test("marking a heading reviewed shows the badge and toggling clears it (CMH-REVIEW-01)", async ({ page }) => {
    await openReviewDoc(page);
    const badge = page.locator("#rv-alpha .cmh-review-badge");
    await expect(badge).toHaveClass(/cmh-review-unreviewed/);
    await page.locator("#rv-alpha").hover();
    await badge.click();
    await expect(badge).toHaveClass(/cmh-review-reviewed/);
    await expect(badge).toHaveAttribute("data-cmh-label", "Reviewed");
    // The badge label is a CSS pseudo-element, so it must NOT pollute the heading's textContent
    // (the TOC, deep-link ids, and other readers depend on clean heading text).
    expect(await page.evaluate(() => document.getElementById("rv-alpha").textContent.trim())).toBe("Alpha");
    expect(await stateOf(page, "rv-alpha")).toBe("reviewed");
    // h5/h6 are covered too, but a plain doc has none; the badge attaches to every h1-h6 - assert
    // the h1 title also got a badge.
    await expect(page.locator("#rv-title .cmh-review-badge")).toHaveCount(1);
    await badge.click(); // toggle off
    await expect(badge).toHaveClass(/cmh-review-unreviewed/);
    expect(await stateOf(page, "rv-alpha")).toBe("unreviewed");
  });

  test("a review marker survives reload and the chrome is absent from Plain export (CMH-REVIEW-02)", async ({ page }) => {
    await openReviewDoc(page);
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click();
    await page.reload();
    await ready(page);
    expect(await stateOf(page, "rv-alpha")).toBe("reviewed");
    const marker = await page.evaluate(() => {
      const key = document.getElementById("commentRoot").dataset.commentKey + "::reviews";
      return JSON.parse(localStorage.getItem(key) || "{}")["rv-alpha"];
    });
    expect(marker).toBeTruthy();
    expect(marker.hash).toMatch(/^[0-9a-z]{1,16}$/);
    // Plain export strips the runtime chrome DOM and the reviewedSections data block (the CSS
    // rules stay, inert - "plain" removes the commenting ability, not the styling).
    await openToolbarMenu(page);
    const [download] = await Promise.all([page.waitForEvent("download"), page.click("#btnSavePlainTop")]);
    const html = await readDownload(download);
    expect(html).not.toContain('class="cmh-review-badge'); // the badge element is gone
    expect(html).not.toContain('id="reviewedSections"');   // the baked marker block is gone
    expect(html).not.toContain("__commentableHtmlReady");  // the runtime JS is gone
  });

  test("editing a reviewed section flips it to Changed while an unchanged one stays Reviewed (CMH-REVIEW-03)", async ({ page }) => {
    await openReviewDoc(page);
    for (const id of ["rv-alpha", "rv-beta"]) {
      await page.locator("#" + id).hover();
      await page.locator("#" + id + " .cmh-review-badge").click();
    }
    expect(await stateOf(page, "rv-alpha")).toBe("reviewed");
    // Change alpha's content only.
    await page.evaluate(() => { document.getElementById("rv-alpha-body").textContent = "totally different content now"; });
    await refresh(page);
    expect(await stateOf(page, "rv-alpha")).toBe("changed");
    await expect(page.locator("#rv-alpha .cmh-review-badge")).toHaveClass(/cmh-review-changed/);
    expect(await stateOf(page, "rv-beta")).toBe("reviewed"); // unchanged section unaffected
  });

  test("an open comment marks the section Commented and one-click re-review re-stamps it (CMH-REVIEW-04)", async ({ page }) => {
    await openReviewDoc(page);
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click();
    expect(await stateOf(page, "rv-alpha")).toBe("reviewed");
    // An open comment inside the section -> Commented (precedence over reviewed).
    await addTextComment(page, "#rv-alpha-body", "please revisit this");
    expect(await stateOf(page, "rv-alpha")).toBe("commented");
    await expect(page.locator("#rv-alpha .cmh-review-badge")).toHaveClass(/cmh-review-commented/);
    // Deleting the comment reverts to the underlying reviewed state.
    const cid = await page.evaluate(() => document.querySelector("#rv-alpha-body mark.cm-hl").dataset.cid);
    await page.locator(`.cm-card[data-cid="${cid}"] [data-act="del"]`).click();
    await expect(page.locator(`.cm-card[data-cid="${cid}"]`)).toHaveCount(0);
    expect(await stateOf(page, "rv-alpha")).toBe("reviewed");
    // One-click re-review on a Changed badge re-stamps the hash back to Reviewed.
    await page.evaluate(() => { document.getElementById("rv-alpha-body").textContent = "edited again"; });
    await refresh(page);
    expect(await stateOf(page, "rv-alpha")).toBe("changed");
    await page.locator("#rv-alpha .cmh-review-badge").click();
    expect(await stateOf(page, "rv-alpha")).toBe("reviewed");
  });

  test("a handled comment does not keep a section Commented, and re-review on Commented re-stamps (CMH-REVIEW-04)", async ({ page }) => {
    const html = await openReviewDoc(page);
    await page.locator("#rv-alpha .cmh-review-badge").click({ force: true }); // reviewed (hash H0)
    await addTextComment(page, "#rv-alpha-body", "please revisit");
    expect(await stateOf(page, "rv-alpha")).toBe("commented");
    // Change the section text WITHOUT destroying the comment's highlight mark (append, not replace),
    // then one-click re-review from the Commented badge: it must re-stamp the CURRENT hash. Prove the
    // re-stamp by deleting the comment in-session -> Reviewed (it would be Changed if not re-stamped).
    await page.evaluate(() => document.getElementById("rv-alpha-body").insertAdjacentText("beforeend", " appended text"));
    await refresh(page);
    expect(await stateOf(page, "rv-alpha")).toBe("commented"); // comment precedence over changed
    await page.locator("#rv-alpha .cmh-review-badge").click({ force: true }); // re-stamp to the new hash
    const cid = await page.evaluate(() => document.querySelector("#rv-alpha-body mark.cm-hl").dataset.cid);
    await page.locator(`.cm-card[data-cid="${cid}"] [data-act="del"]`).click();
    await expect(page.locator(`.cm-card[data-cid="${cid}"]`)).toHaveCount(0);
    expect(await stateOf(page, "rv-alpha")).toBe("reviewed");
    // A HANDLED comment (pruned at load) never yields Commented: beta has an open comment now, but
    // after it is marked handled in the file and reloaded it is gone, so beta is not Commented.
    await addTextComment(page, "#rv-beta-body", "beta note");
    expect(await stateOf(page, "rv-beta")).toBe("commented");
    const bcid = await page.evaluate(() => document.querySelector("#rv-beta-body mark.cm-hl").dataset.cid);
    const markHandled = path.join(SKILL, "tools", "authoring", "mark_handled.py");
    expect(spawnSync(PYTHON, [markHandled, html, bcid], { encoding: "utf8" }).status).toBe(0);
    await page.reload();
    await ready(page);
    expect(await stateOf(page, "rv-beta")).toBe("unreviewed");
  });

  test("the TOC review filter collapses non-matching sections and All re-expands them (CMH-REVIEW-05)", async ({ page }) => {
    await openReviewDoc(page);
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click(); // alpha reviewed; beta/gamma unreviewed
    await expect(page.locator("nav.cm-side-toc")).toBeVisible();
    // Per-entry status mark reflects the reviewed state.
    await expect(page.locator("nav.cm-side-toc .cmh-toc-mark-reviewed")).toHaveCount(1);
    // Filter to Reviewed: alpha stays expanded, beta collapses.
    await page.locator(".cm-side-toc-review-btn.cmh-review-filter-reviewed").click();
    await expect(page.locator("section:has(> #rv-alpha)")).not.toHaveClass(/cmh-section-collapsed/);
    await expect(page.locator("section:has(> #rv-beta)")).toHaveClass(/cmh-section-collapsed/);
    // Filter to Unreviewed: beta expands, alpha collapses.
    await page.locator(".cm-side-toc-review-btn.cmh-review-filter-unreviewed").click();
    await expect(page.locator("section:has(> #rv-beta)")).not.toHaveClass(/cmh-section-collapsed/);
    await expect(page.locator("section:has(> #rv-alpha)")).toHaveClass(/cmh-section-collapsed/);
    // All re-expands everything.
    await page.locator(".cm-side-toc-review-btn.cmh-review-filter-all").click();
    await expect(page.locator("section:has(> #rv-alpha)")).not.toHaveClass(/cmh-section-collapsed/);
    await expect(page.locator("section:has(> #rv-beta)")).not.toHaveClass(/cmh-section-collapsed/);
  });

  test("a manual section caret toggle resets the review filter (CMH-REVIEW-05)", async ({ page }) => {
    await openReviewDoc(page);
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click(); // alpha reviewed
    await page.locator(".cm-side-toc-review-btn.cmh-review-filter-reviewed").click();
    await expect(page.locator("section:has(> #rv-beta)")).toHaveClass(/cmh-section-collapsed/);
    // Manually expand beta via its caret: the filter must reset to All so a later refresh does not
    // re-collapse it.
    await page.locator("section:has(> #rv-beta) .cmh-sec-caret").click();
    await expect(page.locator(".cm-side-toc-review-btn.cmh-review-filter-all")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".cm-side-toc-review-btn.cmh-review-filter-reviewed")).toHaveAttribute("aria-pressed", "false");
    await page.evaluate(() => window.__cmhReview.refresh());
    await expect(page.locator("section:has(> #rv-beta)")).not.toHaveClass(/cmh-section-collapsed/);
  });

  test("the review filter covers Commented and Changed and composes with the text filter (CMH-REVIEW-05)", async ({ page }) => {
    await openReviewDoc(page);
    await page.locator("#rv-gamma .cmh-review-badge").click({ force: true }); // gamma reviewed...
    await page.evaluate(() => document.getElementById("rv-gamma-body").insertAdjacentText("beforeend", " changed gamma"));
    await addTextComment(page, "#rv-beta-body", "a note on beta"); // beta -> commented
    await refresh(page);                                            // gamma -> changed
    expect(await stateOf(page, "rv-beta")).toBe("commented");
    expect(await stateOf(page, "rv-gamma")).toBe("changed");
    // Commented filter isolates beta.
    await page.locator(".cm-side-toc-review-btn.cmh-review-filter-commented").click();
    await expect(page.locator("section:has(> #rv-beta)")).not.toHaveClass(/cmh-section-collapsed/);
    await expect(page.locator("section:has(> #rv-gamma)")).toHaveClass(/cmh-section-collapsed/);
    // Changed filter isolates gamma.
    await page.locator(".cm-side-toc-review-btn.cmh-review-filter-changed").click();
    await expect(page.locator("section:has(> #rv-gamma)")).not.toHaveClass(/cmh-section-collapsed/);
    await expect(page.locator("section:has(> #rv-beta)")).toHaveClass(/cmh-section-collapsed/);
    // The existing text-search filter still composes (hides non-matching TOC entries) while a review
    // filter is active.
    await page.locator(".cm-side-toc-search").fill("Gamma");
    await expect(page.locator("nav.cm-side-toc li.cm-toc-li-hidden").first()).toBeAttached();
  });

  test("each review-filter button shows a live per-state count that stays on one line (CMH-REVIEW-14)", async ({ page }) => {
    await openReviewDoc(page);
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click(); // alpha reviewed -> review UI active (auto-refresh)
    const count = (k) => page.locator(`.cm-side-toc-review-btn.cmh-review-filter-${k} .cm-side-toc-review-btn-count`);
    // 4 headings: rv-title, rv-alpha (reviewed), rv-beta, rv-gamma. The four states partition All.
    await expect(count("all")).toHaveText("(4)");
    await expect(count("reviewed")).toHaveText("(1)");
    await expect(count("unreviewed")).toHaveText("(3)");
    await expect(count("commented")).toHaveText("(0)");
    await expect(count("changed")).toHaveText("(0)");
    // The count is decorative (aria-hidden); the number is folded into the button's accessible name
    // (singular for 1, plural otherwise).
    await expect(count("reviewed")).toHaveAttribute("aria-hidden", "true");
    await expect(page.locator(".cm-side-toc-review-btn.cmh-review-filter-reviewed"))
      .toHaveAttribute("aria-label", "Reviewed, 1 section");
    await expect(page.locator(".cm-side-toc-review-btn.cmh-review-filter-unreviewed"))
      .toHaveAttribute("aria-label", "Unreviewed, 3 sections");
    // Geometry, not just the CSS declaration: the label and its count render on ONE line (their
    // boxes share a row) and the whole filter group never overflows the sidebar horizontally.
    const oneLine = (k) => page.evaluate((key) => {
      const btn = document.querySelector(".cm-side-toc-review-btn.cmh-review-filter-" + key);
      const lab = btn.querySelector(".cm-side-toc-review-btn-label").getBoundingClientRect();
      const cnt = btn.querySelector(".cm-side-toc-review-btn-count").getBoundingClientRect();
      return cnt.left >= lab.right - 1 && cnt.top < lab.bottom && lab.top < cnt.bottom;
    }, k);
    const noOverflow = () => page.evaluate(() => {
      const g = document.querySelector(".cm-side-toc-review");
      return g.scrollWidth <= g.clientWidth + 1;
    });
    const rowCount = () => page.evaluate(() => new Set(Array.from(
      document.querySelectorAll(".cm-side-toc-review-btn")).map((b) => Math.round(b.getBoundingClientRect().top))).size);
    expect(await oneLine("unreviewed")).toBe(true);
    expect(await noOverflow()).toBe(true);
    // Force the promised worst case - every count two digits - and confirm the group still fits and
    // each button keeps label+count on one line. tabular-nums makes this the widest the row can get.
    await page.evaluate(() => document.querySelectorAll(".cm-side-toc-review-btn-count")
      .forEach((c) => { c.textContent = "(88)"; }));
    expect(await noOverflow()).toBe(true);
    expect(await oneLine("unreviewed")).toBe(true);
    // Squeeze the sidebar: the buttons must actually wrap into more than one row (not a vacuous
    // pass) and still not overflow horizontally, even with the two-digit counts injected above.
    await page.evaluate(() => document.documentElement.style.setProperty("--cm-side-toc-w", "11rem"));
    expect(await rowCount()).toBeGreaterThan(1);
    expect(await noOverflow()).toBe(true);
    expect(await oneLine("unreviewed")).toBe(true);
    await page.evaluate(() => document.documentElement.style.removeProperty("--cm-side-toc-w"));
    // Live update via the REAL path (no manual refresh): an open comment on beta moves beta
    // commented; the h1 title's section span covers the whole doc, so it also flips commented (the
    // documented ancestor overlay the filter shows). The four states still partition All:
    // reviewed 1 + unreviewed 1 + commented 2 + changed 0 == 4.
    await addTextComment(page, "#rv-beta-body", "a note on beta");
    await expect(count("commented")).toHaveText("(2)");
    await expect(count("unreviewed")).toHaveText("(1)");
    await expect(count("reviewed")).toHaveText("(1)");
    await expect(count("all")).toHaveText("(4)");
    // Deleting the comment reverts the counts (the ancestor overlay clears with the last comment).
    const bcid = await page.evaluate(() => document.querySelector("#rv-beta-body mark.cm-hl").dataset.cid);
    await page.locator(`.cm-card[data-cid="${bcid}"] [data-act="del"]`).click();
    await expect(count("commented")).toHaveText("(0)");
    await expect(count("unreviewed")).toHaveText("(3)");
    // Changed transition: editing alpha's reviewed content flips it to Changed, and the Changed
    // count follows (guards against the tally omitting the changed state).
    await page.evaluate(() => document.getElementById("rv-alpha-body").insertAdjacentText("beforeend", " edited"));
    await refresh(page);
    expect(await stateOf(page, "rv-alpha")).toBe("changed");
    await expect(count("changed")).toHaveText("(1)");
    await expect(count("reviewed")).toHaveText("(0)");
    await expect(count("all")).toHaveText("(4)");
  });

  test("Export as Portable bakes reviewedSections and Plain strips it (CMH-REVIEW-06)", async ({ page }) => {
    await openReviewDoc(page);
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click();
    await openToolbarMenu(page);
    const [download] = await Promise.all([page.waitForEvent("download"), page.click("#btnSaveHtmlTop")]);
    const html = await readDownload(download);
    const m = html.match(/<script[^>]*id="reviewedSections"[^>]*>([\s\S]*?)<\/script>/);
    expect(m).toBeTruthy();
    const markers = JSON.parse(m[1].trim());
    expect(markers["rv-alpha"]).toBeTruthy();
    expect(markers["rv-alpha"].hash).toMatch(/^[0-9a-z]{1,16}$/);
    // The baked headingText is the clean heading text, not polluted by the injected badge label.
    expect(markers["rv-alpha"].headingText).toBe("Alpha");
  });

  test("Export Offline also bakes the review markers (CMH-REVIEW-06)", async ({ page }) => {
    await openReviewDoc(page);
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click();
    await openToolbarMenu(page);
    const [download] = await Promise.all([page.waitForEvent("download"), page.click("#btnExportOfflineTop")]);
    const html = await readDownload(download);
    const m = html.match(/<script[^>]*id="reviewedSections"[^>]*>([\s\S]*?)<\/script>/);
    expect(m).toBeTruthy();
    expect(JSON.parse(m[1].trim())["rv-alpha"]).toBeTruthy();
  });

  test("export prunes orphan markers whose heading no longer exists (CMH-REVIEW-13)", async ({ page }) => {
    await openReviewDoc(page);
    // Mark two sections reviewed, then delete one heading so its marker is orphaned. The orphan must
    // not be baked into the export - it would leak stale headingText/reviewedAt for a section that no
    // longer exists in the shared copy.
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click();
    await page.locator("#rv-gamma").hover();
    await page.locator("#rv-gamma .cmh-review-badge").click();
    await page.evaluate(() => document.getElementById("rv-gamma").remove());
    await openToolbarMenu(page);
    const [download] = await Promise.all([page.waitForEvent("download"), page.click("#btnSaveHtmlTop")]);
    const html = await readDownload(download);
    const m = html.match(/<script[^>]*id="reviewedSections"[^>]*>([\s\S]*?)<\/script>/);
    expect(m).toBeTruthy();
    const markers = JSON.parse(m[1].trim());
    expect(markers["rv-alpha"]).toBeTruthy();     // the live heading is kept
    expect(markers["rv-gamma"]).toBeFalsy();      // the orphan is pruned
  });

  test("the runtime and Python extractors agree on a doc with script/style/void and transformed blocks (CMH-REVIEW-08)", async ({ page }) => {
    await installClipboardCapture(page);
    await denyExternalNetwork(page);
    const content = `
      <section><h1 id="rv-title">T</h1><p>intro</p></section>
      <section><h2 id="rv-rich">Rich</h2><p>Body text before.</p><style>.z{color:red}</style>
        <script>var q=1;</script><img class="cm-skip" src="x">
        <pre class="cmh-diff" data-diff-label="a.txt">@@ -1 +1 @@\n-old line\n+new line</pre>
        <div data-cmh-note>a note</div><p>More body after inert and transformed nodes.</p></section>
      <section><h2 id="rv-tail">Tail</h2><p>tail body</p></section>`;
    const { html } = stageContent(content, { key: "cmh-review-parity", source: "parity.html" });
    await page.goto(fileUrl(html));
    await ready(page);
    const jsHash = await page.evaluate(() => window.__cmhReview.sectionHashOf("rv-rich"));
    const authoring = path.join(SKILL, "tools", "authoring");
    const code = "import sys;sys.path.insert(0,r'" + authoring + "');import section_hash;"
      + "h=open(r'" + html + "',encoding='utf-8').read();"
      + "print({s['id']:s['hash'] for s in section_hash.extract_sections(h)}['rv-rich'])";
    const py = spawnSync(PYTHON, ["-c", code], { encoding: "utf8" });
    expect(py.status, py.stderr).toBe(0);
    expect(jsHash).toBe(py.stdout.trim());
  });

  test("a marker baked by mark_reviewed.py loads Reviewed, and clearing it persists (CMH-REVIEW-07)", async ({ page }) => {
    await installClipboardCapture(page);
    await denyExternalNetwork(page);
    page.on("dialog", (d) => d.accept());
    await page.setViewportSize({ width: 1400, height: 900 });
    const { html } = stageContent(CONTENT, { key: "cmh-review-baked", source: "baked.html" });
    // Bake a reviewed marker for rv-alpha with the CLI tool, then open: the runtime must read it as
    // reviewed (proves JS/Python extractor parity end-to-end for a prose section).
    const tool = path.join(SKILL, "tools", "authoring", "mark_reviewed.py");
    const r = spawnSync(PYTHON, [tool, html, "rv-alpha"], { encoding: "utf8" });
    expect(r.status, r.stderr).toBe(0);
    await page.goto(fileUrl(html));
    await ready(page);
    expect(await stateOf(page, "rv-alpha")).toBe("reviewed");
    // Clearing a BAKED marker must survive reload (tombstone), not resurrect from the block.
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click();
    expect(await stateOf(page, "rv-alpha")).toBe("unreviewed");
    await page.reload();
    await ready(page);
    expect(await stateOf(page, "rv-alpha")).toBe("unreviewed");
  });

  test("the runtime section hash matches the JS/Python golden (CMH-REVIEW-08)", async ({ page }) => {
    await openReviewDoc(page);
    const goldenPath = path.join(DEV, "tests", "fixtures", "section_hash", "golden.json");
    const golden = JSON.parse(fs.readFileSync(goldenPath, "utf8"));
    for (const entry of golden) {
      const got = await page.evaluate((t) => window.__cmhReview.hash(t), entry.text);
      expect(got, JSON.stringify(entry.text)).toBe(entry.hash);
    }
  });

  test("the review filter and TOC status marks stay dormant until the first review or comment (CMH-REVIEW-10)", async ({ page }) => {
    await openReviewDoc(page);
    // Dormant on first open: the segmented filter is hidden, no TOC status marks exist, and no
    // heading shows a persistent (non-hover) badge.
    await expect(page.locator(".cm-side-toc-review")).toBeHidden();
    // No status marker of either the old (dot) or new (mark) shape is painted while dormant - this is
    // genuinely red against the pre-change runtime, which always painted a per-entry dot.
    await expect(page.locator("nav.cm-side-toc .cmh-toc-mark, nav.cm-side-toc .cmh-toc-dot")).toHaveCount(0);
    expect(await page.evaluate(() => window.__cmhReview.active())).toBe(false);
    // No persistent state badge shows when dormant - only the hover-only unreviewed affordance exists.
    await expect(page.locator("#commentRoot .cmh-review-reviewed, #commentRoot .cmh-review-commented, #commentRoot .cmh-review-changed")).toHaveCount(0);
    await expect(page.locator("#rv-alpha .cmh-review-badge")).toHaveClass(/cmh-review-unreviewed/);
    // Marking a section reviewed via the hover affordance activates the review UI.
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click();
    expect(await page.evaluate(() => window.__cmhReview.active())).toBe(true);
    await expect(page.locator(".cm-side-toc-review")).toBeVisible();
    await expect(page.locator("nav.cm-side-toc .cmh-toc-mark").first()).toBeVisible();
    // The still-unreviewed entries (beta, gamma) carry a decorative hollow mark that stays out of the
    // screen-reader announcement (aria-hidden, no label); only marked states expose a role/label.
    const unrev = page.locator("nav.cm-side-toc .cmh-toc-mark-unreviewed").first();
    await expect(unrev).toBeVisible();
    expect(await unrev.getAttribute("data-cmh-mark")).toBe("");
    expect(await unrev.getAttribute("aria-hidden")).toBe("true");
    expect(await unrev.getAttribute("aria-label")).toBeNull();
    expect(await unrev.getAttribute("role")).toBeNull();
    // marks removed, active() false again.
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click();
    expect(await page.evaluate(() => window.__cmhReview.active())).toBe(false);
    await expect(page.locator(".cm-side-toc-review")).toBeHidden();
    await expect(page.locator("nav.cm-side-toc .cmh-toc-mark")).toHaveCount(0);
  });

  test("adding the first comment activates the dormant review UI (CMH-REVIEW-10)", async ({ page }) => {
    await openReviewDoc(page);
    await expect(page.locator(".cm-side-toc-review")).toBeHidden();
    expect(await page.evaluate(() => window.__cmhReview.active())).toBe(false);
    await addTextComment(page, "#rv-beta-body", "first comment activates review");
    expect(await page.evaluate(() => window.__cmhReview.active())).toBe(true);
    await expect(page.locator(".cm-side-toc-review")).toBeVisible();
    await expect(page.locator("nav.cm-side-toc .cmh-toc-mark").first()).toBeVisible();
  });

  test("each TOC entry shows a single-character status badge reflecting its state (CMH-REVIEW-11)", async ({ page }) => {
    await openReviewDoc(page);
    // alpha reviewed, beta commented, gamma reviewed-then-changed.
    await page.locator("#rv-alpha").hover();
    await page.locator("#rv-alpha .cmh-review-badge").click();
    await page.locator("#rv-gamma").hover();
    await page.locator("#rv-gamma .cmh-review-badge").click();
    await page.evaluate(() => document.getElementById("rv-gamma-body").insertAdjacentText("beforeend", " changed gamma"));
    await addTextComment(page, "#rv-beta-body", "note on beta");
    await refresh(page);
    // Each entry carries a single-character mark rendered as a pseudo-element (data-cmh-mark), so it
    // does not pollute the TOC link text. Reviewed=R, Commented=C, Changed=!, unreviewed is hollow.
    await expect(page.locator('nav.cm-side-toc .cmh-toc-mark-reviewed[data-cmh-mark="R"]')).toHaveCount(1);
    await expect(page.locator('nav.cm-side-toc .cmh-toc-mark-commented[data-cmh-mark="C"]')).toHaveCount(1);
    await expect(page.locator('nav.cm-side-toc .cmh-toc-mark-changed[data-cmh-mark="!"]')).toHaveCount(1);
    // The mark letter is a CSS pseudo-element, so the mark span carries no text of its own (the TOC
    // link text - and the search/deep-link readers - never see the letter).
    const markText = await page.locator('nav.cm-side-toc .cmh-toc-mark-reviewed').first().evaluate((el) => el.textContent);
    expect(markText).toBe("");
    // Pin the pseudo-element rendering (a regression that dropped `content: attr(data-cmh-mark)` would
    // leave the letter invisible) and confirm the TOC link text stays the clean heading title with no
    // leading letter injected.
    const afterContent = await page.locator('nav.cm-side-toc .cmh-toc-mark-reviewed').first().evaluate((el) => getComputedStyle(el, "::after").content);
    expect(afterContent).toContain("R");
    const linkText = await page.locator('nav.cm-side-toc a:has(.cmh-toc-mark-reviewed)').first().evaluate((el) => el.textContent.trim());
    expect(linkText).toMatch(/Alpha$/);
    expect(linkText).not.toMatch(/^R/);
    // Accessibility: a non-unreviewed mark exposes its status to assistive tech (role=img + a text
    // label), while the neutral unreviewed hollow mark stays decorative (aria-hidden) so it is not
    // announced. The letter itself is a pseudo-element, so the label - not the glyph - is the a11y name.
    const reviewedMark = page.locator('nav.cm-side-toc .cmh-toc-mark-reviewed').first();
    expect(await reviewedMark.getAttribute("role")).toBe("img");
    expect(await reviewedMark.getAttribute("aria-label")).toBe("Reviewed");
    expect(await page.locator('nav.cm-side-toc .cmh-toc-mark-commented').first().getAttribute("aria-label")).toBe("Commented");
    expect(await page.locator('nav.cm-side-toc .cmh-toc-mark-changed').first().getAttribute("aria-label")).toBe("Changed");
  });

  test("the reviewed state persists through Portable/Offline export and reopening activates the review UI (CMH-REVIEW-12)", async ({ browser }) => {
    const tmpDir = path.join(DEV, "..", "..", "..", "tmp", "review-export-spec");
    fs.mkdirSync(tmpDir, { recursive: true });
    for (const [btn, name] of [["#btnSaveHtmlTop", "portable"], ["#btnExportOfflineTop", "offline"]]) {
      const authorCtx = await browser.newContext();
      const authorPage = await authorCtx.newPage();
      await openReviewDoc(authorPage);
      await authorPage.locator("#rv-alpha").hover();
      await authorPage.locator("#rv-alpha .cmh-review-badge").click();
      await openToolbarMenu(authorPage);
      const [download] = await Promise.all([authorPage.waitForEvent("download"), authorPage.click(btn)]);
      const exported = await readDownload(download);
      expect(exported, name).toMatch(/id="reviewedSections"/);
      const out = path.join(tmpDir, `${name}.html`);
      fs.writeFileSync(out, exported);
      await authorCtx.close();
      // Reopen in a SEPARATE, clean context (empty localStorage) so the ONLY possible source of the
      // reviewed state is the baked reviewedSections block - not localStorage carried over from the
      // authoring session. This proves the state truly travels inside the exported file.
      const reopenCtx = await browser.newContext();
      const page = await reopenCtx.newPage();
      await denyExternalNetwork(page);
      await page.setViewportSize({ width: 1400, height: 900 });
      await page.goto(fileUrl(out));
      await ready(page);
      expect(await page.evaluate(() => window.__cmhReview.active()), name).toBe(true);
      expect(await stateOf(page, "rv-alpha"), name).toBe("reviewed");
      await expect(page.locator("#rv-alpha .cmh-review-badge"), name).toHaveClass(/cmh-review-reviewed/);
      await expect(page.locator(".cm-side-toc-review"), name).toBeVisible();
      await expect(page.locator('nav.cm-side-toc .cmh-toc-mark-reviewed[data-cmh-mark="R"]'), name).toHaveCount(1);
      await reopenCtx.close();
    }
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });
});
