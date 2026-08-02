import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import os from "os";
import {
  PYTHON, SKILL, fileUrl, openToolbarMenu, readDownload, ready, stageContent, stageNonShareable,
} from "./helpers.js";

// The pre-rename vocabulary, assembled from fragments so a future sweeping rename cannot quietly
// rewrite the very strings this suite exists to pin (the Python compat suite does the same).
const OLD = "PORT" + "ABLE";
const OLD_LOWER = OLD.toLowerCase();
const LEGACY_BEGIN = `<!-- BEGIN: commentable-html - NON${OLD} BOOTSTRAP -->`;
const LEGACY_END = `<!-- END: commentable-html - NON${OLD} BOOTSTRAP -->`;
const LEGACY_ONLY_CLASS = `cm-non${OLD_LOWER}-only`;

// Turn the freshly built companion template back into the document an EARLIER release shipped:
// the legacy descriptor mode, the legacy bootstrap anchor pair, and a control carrying the legacy
// companion-only class. Everything else (the companion files it loads) is the CURRENT build, which
// is exactly the situation a user is in after upgrading the skill beside an old document.
function toLegacyCompanionDocument(html) {
  let out = html
    .replace('"mode":"nonshareable"', `"mode":"non${OLD_LOWER}"`)
    .replace("<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->", LEGACY_BEGIN)
    .replace("<!-- END: commentable-html - NONSHAREABLE BOOTSTRAP -->", LEGACY_END);
  // A companion-only control in the document's own markup, spelled the pre-rename way. The
  // stylesheet it is styled by is the CURRENT companion file, so this is what proves the legacy
  // selector is still honored.
  out = out.replace(
    '<div class="cm-toolbar cm-skip" role="toolbar" aria-label="Comments toolbar">',
    '<div class="cm-toolbar cm-skip" role="toolbar" aria-label="Comments toolbar">'
      + `<span id="cmhLegacyOnlyProbe" class="cm-skip ${LEGACY_ONLY_CLASS}">legacy</span>`
  );
  return out;
}

test.describe("legacy (pre-rename) documents keep working (CMH-PORT-06/07)", () => {
  test("a legacy companion document loads, reports its mode, and honors legacy companion-only controls", async ({ page }) => {
    const staged = stageNonShareable({ mutate: toLegacyCompanionDocument });
    const source = fs.readFileSync(staged.html, "utf8");
    expect(source).toContain(LEGACY_BEGIN);
    expect(source).toContain(LEGACY_ONLY_CLASS);
    await page.goto(fileUrl(staged.html));
    await ready(page);

    // The layer loads from the CURRENT companions even though the document is pre-rename.
    await expect(page.locator("#cmhModeBadge")).toHaveText("Not shareable");
    // Both body hooks are set, so a stylesheet keyed on either spelling still applies.
    expect(await page.evaluate(() => document.body.classList.contains("cm-nonshareable"))).toBe(true);
    expect(await page.evaluate(() => document.body.classList.contains("cm-nonportable"))).toBe(true);
    // The legacy companion-only control is REVEALED by the current stylesheet, which is the
    // behavior the retained legacy selectors exist for (a string-presence check cannot show this).
    await expect(page.locator("#cmhLegacyOnlyProbe")).toBeVisible();
    // The missing-asset banner stayed hidden, i.e. the runtime really initialized.
    await expect(page.locator("#cmhAssetBanner")).toBeHidden();
  });

  test("exporting a legacy companion document strips the legacy anchor and yields one valid shareable file", async ({ page }) => {
    const staged = stageNonShareable({ mutate: toLegacyCompanionDocument });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSaveHtmlTop"),
    ]);
    const html = await readDownload(download);

    // The legacy bootstrap block is gone, and so are the companion references. (The inlined
    // runtime SOURCE still mentions the banner id in a string literal, so assert the ELEMENT is
    // gone rather than the bare id.)
    expect(html).not.toContain(LEGACY_BEGIN);
    expect(html).not.toMatch(/<div\b[^>]*\bid\s*=\s*["']?cmhAssetBanner/i);
    expect(html).not.toMatch(/<link\b[^>]*\bhref\s*=\s*["'][^"']*commentable-html/i);
    expect(html).not.toMatch(/<script\b[^>]*\bsrc\s*=\s*["'][^"']*commentable-html/i);
    // The exported descriptor is re-stamped to the CURRENT mode value.
    expect(html).toMatch(/"mode"\s*:\s*"shareable"/);

    // And the result validates as an ordinary self-contained document.
    const tmp = path.join(os.tmpdir(), "cmh_legacy_export_" + Date.now() + ".html");
    fs.writeFileSync(tmp, html);
    try {
      execFileSync(PYTHON, ["tools/validate/validate.py", tmp], { cwd: SKILL });
    } finally {
      fs.rmSync(tmp, { force: true });
    }
  });

  test("re-exporting a file named by an earlier release does not stack the legacy suffix (CMH-EXP-01)", async ({ page }) => {
    const staged = stageNonShareable({ mutate: toLegacyCompanionDocument });
    // Name the staged document the way the pre-rename export named its output.
    const legacyName = path.join(staged.dir, `report-${OLD_LOWER}.html`);
    fs.renameSync(staged.html, legacyName);
    await page.goto(fileUrl(legacyName));
    await ready(page);
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSaveHtmlTop"),
    ]);
    expect(download.suggestedFilename()).toBe("report-shareable.html");
  });

  test("a self-contained document that QUOTES a legacy bootstrap anchor keeps it through Plain export", async ({ page }) => {
    // Accepting a second anchor spelling doubles the literals a document about this skill can
    // quote in its own prose. A Shareable document has no real bootstrap, so the export must not
    // treat an authored quotation as one and delete the reader's content.
    const quoted = `<h1>Anchors</h1>\n<p id="quoted-anchor">${LEGACY_BEGIN.replace(/</g, "&lt;")}</p>\n<p>${LEGACY_END.replace(/</g, "&lt;")}</p>`;
    const staged = stageContent(quoted, { key: "cmh-legacy-anchor-quote", source: "quote.html" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSavePlainTop"),
    ]);
    const html = await readDownload(download);
    expect(html).toContain("quoted-anchor");
    expect(html).toContain(`NON${OLD} BOOTSTRAP`);
  });
});
