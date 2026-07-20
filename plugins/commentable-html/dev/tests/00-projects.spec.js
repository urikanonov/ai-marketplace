import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { HEAVY_SPEC_FILES } from "./_projects.mjs";

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));

// The fast/heavy Playwright project split (playwright.config.js) routes specs by filename: the
// `heavy` project is exactly HEAVY_SPEC_FILES, the `fast` project is everything else. The two are
// complements, so every spec runs in exactly one project - EXCEPT that a typo in HEAVY_SPEC_FILES
// (a name matching no file) would make the heavy CI job silently run zero tutorial-shots tests while
// that spec quietly ran in the fast project (where its subprocess-browser thrashes). Guard against
// that: every heavy entry must resolve to a real, unique tests/*.spec.js file.
test("every heavy-project spec name resolves to a real, unique spec file (CMH-BUILD-12)", () => {
  const allSpecs = fs.readdirSync(TESTS_DIR).filter((f) => f.endsWith(".spec.js"));
  expect(HEAVY_SPEC_FILES.length, "expected at least one heavy spec").toBeGreaterThan(0);
  for (const name of HEAVY_SPEC_FILES) {
    expect(allSpecs, `heavy spec '${name}' is not an existing tests/*.spec.js file`).toContain(name);
  }
  expect(new Set(HEAVY_SPEC_FILES).size, "duplicate entry in HEAVY_SPEC_FILES").toBe(HEAVY_SPEC_FILES.length);
});
