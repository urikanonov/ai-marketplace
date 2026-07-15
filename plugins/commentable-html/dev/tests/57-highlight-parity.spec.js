import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { stageContent, fileUrl, ready } from "./helpers.js";

// GH-REGRESS-HIGHLIGHT-PARITY: the runtime JS diff highlighter (cmhHighlightCode) must classify
// tokens the same way the author-time Python tool (highlight_code.py) does. Both consume the SAME
// shared fixture (tests/fixtures/highlight_parity.json): tests/test_highlight_parity.py pins the
// Python side, this test pins the runtime side. A divergence (e.g. re-introducing the PR #33
// single-quote over-match in one implementation) fails one of the two suites.

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CASES = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "highlight_parity.json"), "utf8"),
).cases;

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// One diff block per parity case, in fixture order, so the Nth .cmh-diff-view is the Nth case.
function buildContent() {
  return CASES.map((c, i) =>
    '<pre class="cmh-diff" data-diff-lang="' + c.lang + '" data-diff-label="case' + i + '">'
    + "@@ -1 +1 @@\n-removed\n+" + esc(c.code) + "</pre>").join("\n");
}

test("the runtime diff highlighter matches the shared parity fixture (GH-REGRESS-HIGHLIGHT-PARITY)", async ({ page }) => {
  const staged = stageContent(buildContent(), { key: "cmh-highlight-parity" });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const views = page.locator(".cmh-diff-view");
    await expect(views).toHaveCount(CASES.length);

    for (let i = 0; i < CASES.length; i++) {
      const c = CASES[i];
      const view = views.nth(i);
      const joined = async (cls) =>
        (await view.locator(".cmh-code-" + cls).allTextContents()).join("");
      const str = await joined("str");
      const com = await joined("com");
      const kw = await joined("kw");
      const kwTokens = await view.locator(".cmh-code-kw").allTextContents();
      for (const tok of c.str || []) {
        expect(str, c.lang + ": " + JSON.stringify(tok) + " should be a string token").toContain(tok);
      }
      for (const tok of c.com || []) {
        expect(com, c.lang + ": " + JSON.stringify(tok) + " should be a comment token").toContain(tok);
      }
      for (const tok of c.kw || []) {
        expect(kw, c.lang + ": " + JSON.stringify(tok) + " should be a keyword token").toContain(tok);
      }
      for (const tok of c.notKw || []) {
        const forbidden = [tok];
        if (/^\.[A-Za-z_$][A-Za-z0-9_$]*$/.test(tok)) forbidden.push(tok.slice(1));
        for (const text of forbidden) {
          expect(kwTokens, c.lang + ": " + JSON.stringify(tok) + " must NOT be wrapped as a keyword")
            .not.toContain(text);
        }
      }
      for (const tok of c.notStr || []) {
        expect(str, c.lang + ": " + JSON.stringify(tok) + " must NOT be swallowed as a string").not.toContain(tok);
      }
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
