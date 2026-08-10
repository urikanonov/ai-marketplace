import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const DEV = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const VENDOR = path.join(DEV, "assets", "vendor");

// CMH-BUILD-25 (the strong half). `assets/vendor/mermaid.min.js` is HAND-COPIED, and it is the copy
// an Export Offline artifact inlines - so it is the only mermaid a reader of an offline document
// ever runs. Its Python sibling (tests/test_vendored_mermaid_provenance.py) pins what the bundle
// SAYS about itself, which holds with no install and no network. This spec pins the thing that
// claim cannot: that the bytes really are the npm tarball package-lock.json resolves, rather than
// something merely reporting that version.
//
// It lives here because it needs `node_modules`, and the `fast` CI job runs after
// `npm ci --ignore-scripts` - which verifies each tarball against the lockfile's `integrity` hash.
// Comparing the vendored file to the installed one therefore extends that cryptographic guarantee
// to the shipped offline bytes, which nothing else in the repo does.
//
// This matters concretely: the 11.16.1 security bump had to be hand-vendored from a public CDN
// because the developer's npm registry could not resolve the new version, and no gate would have
// noticed the wrong bytes.
//
// Skips (rather than fails) when the dependency is not installed, so a checkout without `npm ci`
// is not a red herring; CI always installs, so the guard is always live where it counts.
test("the vendored mermaid bundle is the npm tarball the lockfile pins (CMH-BUILD-25)", () => {
  const installedDir = path.join(DEV, "node_modules", "mermaid");
  const installedPkg = path.join(installedDir, "package.json");
  test.skip(!fs.existsSync(installedPkg), "mermaid is not installed (run npm ci)");

  const declared = JSON.parse(fs.readFileSync(path.join(DEV, "package.json"), "utf8"));
  const spec = (declared.devDependencies || {}).mermaid || (declared.dependencies || {}).mermaid;
  const pinned = String(spec).replace(/^[\^~]/, "");
  const installed = JSON.parse(fs.readFileSync(installedPkg, "utf8")).version;

  // A caret range legitimately resolves ABOVE the pin, and then the vendored copy is expected to
  // differ. Only the exact-match case can be compared byte for byte, so say plainly why it skipped
  // rather than passing silently on a comparison that never happened.
  test.skip(installed !== pinned,
    `installed mermaid ${installed} != pinned ${pinned}; byte comparison only meaningful on an exact match`);

  const vendored = fs.readFileSync(path.join(VENDOR, "mermaid.min.js"));
  const fromTarball = fs.readFileSync(path.join(installedDir, "dist", "mermaid.min.js"));
  expect(
    vendored.equals(fromTarball),
    `assets/vendor/mermaid.min.js does not match node_modules/mermaid/dist/mermaid.min.js for ` +
    `mermaid@${installed}. The vendored copy is what Export Offline inlines, so it must be the ` +
    `tarball npm verified against package-lock.json's integrity hash - not a copy fetched from ` +
    `anywhere else. Re-copy it per assets/vendor/UPSTREAM.md and rerun ` +
    `'python tools/build.py --regen-vendor-gz'.`
  ).toBe(true);
});
