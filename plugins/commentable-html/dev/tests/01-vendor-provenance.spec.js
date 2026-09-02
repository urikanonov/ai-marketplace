import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { pinnedVersion, lockedVersion, pinMismatchMessage } from "../tools/mermaid_pin.mjs";
import { vendoredChartJsVersion, chartJsRoutePattern } from "../tools/chartjs_pin.mjs";

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
  if (!fs.existsSync(installedPkg)) {
    // Announce every skip: a skipped guard reads as a green tick in a CI summary, and this is the
    // one place the byte-level check exists, so its absence must be visible in the log.
    console.warn("CMH-BUILD-25: SKIPPED - mermaid is not installed (run npm ci). The vendored bytes were NOT verified against the npm tarball.");
  }
  test.skip(!fs.existsSync(installedPkg), "mermaid is not installed (run npm ci)");

  const declared = JSON.parse(fs.readFileSync(path.join(DEV, "package.json"), "utf8"));
  const spec = (declared.devDependencies || {}).mermaid || (declared.dependencies || {}).mermaid;
  const pinned = String(spec).replace(/^[\^~]/, "");
  const installed = JSON.parse(fs.readFileSync(installedPkg, "utf8")).version;

  // Deliberately a FAILURE, not a skip. `npm ci` installs the LOCKFILE version, and npm is happy
  // whenever that merely SATISFIES the caret range - so a lockfile-only bump (package.json
  // `^11.16.1`, lockfile `11.17.0`: exactly the shape of the Dependabot PR that started this) would
  // otherwise skip the byte comparison and ship the old vendored bytes under a green tick. That is
  // the one case this guard exists for, so a disagreement between the pin and what is installed is
  // itself the defect: the pin must be bumped and the library re-vendored.
  expect(
    installed,
    `package.json pins mermaid ${pinned} but ${installed} is installed (npm ci installs the ` +
    `package-lock.json version). Bump the pin and re-vendor assets/vendor/mermaid.min.js per ` +
    `assets/vendor/UPSTREAM.md - otherwise the offline export ships a different mermaid than the ` +
    `dependency tree resolves.`
  ).toBe(pinned);

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

  // The MIT licence must travel with the redistributed bytes (CMH-LICENSE-01), and a re-vendor that
  // updates the .js and forgets the .LICENSE leaves a STALE notice that still contains the word
  // "MIT" - so presence is not enough; it has to be the licence shipped in this tarball.
  const vendoredLicence = fs.readFileSync(path.join(VENDOR, "mermaid.LICENSE"));
  const tarballLicence = fs.readFileSync(path.join(installedDir, "LICENSE"));
  expect(
    vendoredLicence.equals(tarballLicence),
    `assets/vendor/mermaid.LICENSE does not match node_modules/mermaid/LICENSE for ` +
    `mermaid@${installed}. THIRD_PARTY_NOTICES.md is generated from the vendored copy, so a stale ` +
    `licence means the notices that ship beside the library bytes are not the ones upstream ` +
    `published with them. Re-copy it per assets/vendor/UPSTREAM.md and rebuild.`
  ).toBe(true);
});

// CMH-SIZE-08 made Chart.js provenance load-bearing in a way it never was before. The vendored
// `chart.umd.min.js` used to be EMBEDDED in every document, so its only requirement was "be a
// working Chart.js". Now the payload names `chart.js@<read_chartjs_version()>` as a jsDelivr URL
// while `chartjsIntegrity` hashes these local BYTES, and the export refuses anything that does not
// match - so the version string and the bytes must describe the same release or EVERY chart
// document's offline export fails permanently, with a message ("regenerate the payload") that
// regenerating cannot fix.
//
// The failure shape is concrete: `read_chartjs_version` parses the package.json RANGE BASE
// (`^4.5.1` -> `4.5.1`), but `npm ci` installs the LOCKFILE version. A lockfile-only bump to 4.5.2
// followed by a re-vendor per UPSTREAM.md would hash 4.5.2's bytes under a 4.5.1 URL. Nothing else
// in the repo would notice: the Playwright route stubs match `chart.js@[^/]+` and serve the local
// vendored file whatever version is asked for, so the hermetic tests stay green by construction.
//
// Same structure and same rationale as CMH-BUILD-25 for mermaid, including the announced skip when
// the dependency is not installed.
test("the vendored Chart.js bundle is the npm tarball the lockfile pins (CMH-SIZE-08)", () => {
  const installedDir = path.join(DEV, "node_modules", "chart.js");
  const installedPkg = path.join(installedDir, "package.json");
  if (!fs.existsSync(installedPkg)) {
    console.warn("CMH-SIZE-08: SKIPPED - chart.js is not installed (run npm ci). The vendored bytes were NOT verified against the npm tarball.");
  }
  test.skip(!fs.existsSync(installedPkg), "chart.js is not installed (run npm ci)");

  const declared = JSON.parse(fs.readFileSync(path.join(DEV, "package.json"), "utf8"));
  const spec = (declared.devDependencies || {})["chart.js"] || (declared.dependencies || {})["chart.js"];
  const pinned = String(spec).replace(/^[\^~]/, "");
  const installed = JSON.parse(fs.readFileSync(installedPkg, "utf8")).version;

  // A FAILURE, not a skip, for the same reason as mermaid's: this exact disagreement is what would
  // put the wrong version in the descriptor URL.
  expect(
    installed,
    `package.json pins chart.js ${pinned} but ${installed} is installed (npm ci installs the ` +
    `package-lock.json version). The vendored payload's chartjsUrl is built from the package.json ` +
    `pin while chartjsIntegrity hashes assets/vendor/chart.umd.min.js, so a disagreement here ` +
    `ships a URL and a hash for different releases and every chart document's Offline export ` +
    `fails verification. Bump the pin and re-vendor per assets/vendor/UPSTREAM.md.`
  ).toBe(pinned);

  const vendored = fs.readFileSync(path.join(VENDOR, "chart.umd.min.js"));
  const fromTarball = fs.readFileSync(path.join(installedDir, "dist", "chart.umd.min.js"));
  expect(
    vendored.equals(fromTarball),
    `assets/vendor/chart.umd.min.js does not match node_modules/chart.js/dist/chart.umd.min.js ` +
    `for chart.js@${installed}. That file's hash is what an Offline export checks the downloaded ` +
    `jsDelivr copy against, so it must be the tarball npm verified against package-lock.json's ` +
    `integrity hash. Re-copy it per assets/vendor/UPSTREAM.md and rerun ` +
    `'python tools/build.py --regen-vendor-gz'.`
  ).toBe(true);

  const vendoredLicence = fs.readFileSync(path.join(VENDOR, "chart.umd.LICENSE"));
  const tarballLicence = fs.readFileSync(path.join(installedDir, "LICENSE.md"));
  expect(
    vendoredLicence.equals(tarballLicence),
    `assets/vendor/chart.umd.LICENSE does not match node_modules/chart.js/LICENSE.md for ` +
    `chart.js@${installed}. The notice is embedded in every document and emitted beside the ` +
    `inlined library, so a stale copy misstates the terms the shipped bytes travel under. ` +
    `Re-copy it per assets/vendor/UPSTREAM.md and rebuild.`
  ).toBe(true);
});

// The refusal DECISION (CMH-BUILD-24) exercised directly, rather than asserted about as source
// text: the capture reads three versions and must (a) proceed on agreement, (b) tell a maintainer
// with a stale install to run `npm ci`, and (c) NOT say that when the lockfile itself has moved
// above the pin, because `npm ci` reproduces that mismatch and the advice would loop.
test("the mermaid pin-agreement decision covers match, stale install and lockfile-ahead (CMH-BUILD-24)", () => {
  expect(pinnedVersion({ devDependencies: { mermaid: "^11.16.1" } })).toBe("11.16.1");
  expect(pinnedVersion({ dependencies: { mermaid: "~11.16.1" } })).toBe("11.16.1");
  expect(pinnedVersion({ devDependencies: { mermaid: "11.16.1" } })).toBe("11.16.1");
  expect(pinnedVersion({})).toBe("");
  expect(lockedVersion({ packages: { "node_modules/mermaid": { version: "11.17.0" } } })).toBe("11.17.0");
  expect(lockedVersion({ packages: {} })).toBeNull();
  expect(lockedVersion({})).toBeNull();

  // (a) agreement - no refusal at all.
  expect(pinMismatchMessage({ pinned: "11.16.1", installed: "11.16.1", locked: "11.16.1" })).toBeNull();

  // (b) stale install: the lockfile still agrees with the pin, so `npm ci` really is the fix.
  const stale = pinMismatchMessage({ pinned: "11.16.1", installed: "11.16.0", locked: "11.16.1" });
  expect(stale).toContain("11.16.0");
  expect(stale).toContain("npm ci");
  expect(stale).not.toContain("Bump the package.json pin");

  // (c) lockfile ahead of the pin: `npm ci` would reproduce it, so the advice must be to bump the
  // pin and re-vendor. This is the Dependabot lockfile-only shape.
  const ahead = pinMismatchMessage({ pinned: "11.16.1", installed: "11.17.0", locked: "11.17.0" });
  expect(ahead).toContain("package-lock.json resolves 11.17.0");
  expect(ahead).toContain("Bump the package.json pin");
  expect(ahead).toContain("re-vendor");

  // A missing lockfile entry must not be mistaken for the lockfile-ahead case.
  const noLock = pinMismatchMessage({ pinned: "11.16.1", installed: "11.17.0", locked: null });
  expect(noLock).toContain("npm ci");
  expect(noLock).not.toContain("Bump the package.json pin");
});

test("the tutorial capture's Chart.js route pins the vendored version and nothing else (CMH-SIZE-09)", () => {
  // Behavioral, not source-text: the route is BUILT from the vendored bundle, so what matters is
  // which URLs it answers. Serving the vendored bytes to a document that asked for another version
  // fails that document's `integrity` check, and the `typeof Chart === "undefined"` guard turns
  // that into a silently blank canvas in a committed screenshot - so every near-miss below must
  // fall through to the capture's deny-all abort instead.
  const vendored = fs.readFileSync(path.join(DEV, "assets", "vendor", "chart.umd.min.js"), "utf8").slice(0, 4000);
  const version = vendoredChartJsVersion(vendored);
  expect(version, "the vendored bundle reports an exact version").toMatch(/^\d+\.\d+\.\d+$/);

  const re = chartJsRoutePattern(version);
  const base = "https://cdn.jsdelivr.net/npm/chart.js@";
  expect(re.test(base + version + "/dist/chart.umd.min.js"), "the vendored build is served").toBe(true);

  for (const [why, url] of [
    ["another version's minified build", base + "4.4.0/dist/chart.umd.min.js"],
    ["the unminified build report-triage asks for", base + version + "/dist/chart.umd.js"],
    ["a floating major specifier", base + "4/dist/chart.umd.min.js"],
    ["a different package", "https://cdn.jsdelivr.net/npm/chart.js-plugin@" + version + "/dist/chart.umd.min.js"],
    ["a different host", "https://evil.example/npm/chart.js@" + version + "/dist/chart.umd.min.js"],
    ["a suffixed path", base + version + "/dist/chart.umd.min.js.map"],
  ]) {
    expect(re.test(url), why + " must fall through to the deny-all abort").toBe(false);
  }

  // A non-exact version can never become a route: a wildcard built by accident is the whole bug.
  for (const bad of ["4", "4.5", "4.5.x", "", "*", "[^/]+"]) {
    expect(() => chartJsRoutePattern(bad), JSON.stringify(bad) + " must be refused").toThrow();
  }
  expect(() => vendoredChartJsVersion("no banner here"), "a bundle with no banner is refused").toThrow();
});
