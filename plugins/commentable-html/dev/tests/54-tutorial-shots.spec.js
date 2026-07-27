import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import { DEV, SKILL } from "./helpers.js";
import { DIMENSION_DELTA_PX } from "../tools/shot_clip.mjs";
import { compareImages } from "../tools/shot_compare.mjs";

// These tests each spawn the capture tool (a browser-launching subprocess). They are data-safe to
// run in parallel - the tool isolates its own scratch per process id, and each test below writes to
// its own uniquely named out dir under a per-worker TEST_TMP root - so they run in the `heavy`
// Playwright project (its own CI job with a small worker count) rather than serially. Do NOT wipe a
// SHARED tmp parent here: a per-worker afterAll wiping a dir another worker's subprocess is still
// writing into is the race the old `mode: serial` guarded; per-worker roots remove that need.

// The sixteen screenshots the tutorial (docs/TUTORIAL.md) embeds as garden-*.png.
const SHOTS = [
  "01-top-light", "02-kql", "03-chart", "04-diff", "05-composer",
  "06-comment-saved", "07-help", "08-top-dark", "09-copyall",
  "10-review-badge", "11-side-toc", "12-export-menu", "13-comment-search",
  "14-thread", "15-format-toolbar", "16-rich-card",
];

const EXAMPLES = path.join(SKILL, "..", "..", "examples");
const EXAMPLE = path.join(EXAMPLES, "report-community-garden.html");
// Checklists, notes, and the incident triage board render in their own example reports, so each is
// captured as a small scene of its own (checklist-*.png, note-*.png, triage-*.png).
const EXTRA_SCENES = [
  { prefix: "triage", example: path.join(EXAMPLES, "report-triage.html"), shots: ["01-board"] },
  { prefix: "checklist", example: path.join(EXAMPLES, "report-checklist.html"), shots: ["01-checklist"] },
  { prefix: "note", example: path.join(EXAMPLES, "report-notes.html"), shots: ["01-note"] },
];
const REPO = path.resolve(DEV, "..", "..", "..");
// Per-worker scratch root (process id) so parallel workers never share a dir - and so this file's
// afterAll only ever removes ITS OWN worker's tree, never a dir another worker is writing into.
const TEST_TMP = path.join(REPO, "tmp", "tutorial-shots-spec", String(process.pid));
// Full-viewport clips are a fixed 1320x900 CSS px box, so their height is a constant rather than a
// content-derived (font-metric dependent) measurement and is deliberately NOT quantized.
const FULL_VIEWPORT_PX = 900 * 2;
// The cross-run determinism assertions below diff images with the SAME comparator the --check
// freshness gate uses (tools/shot_compare.mjs), imported rather than copied, so this suite can never
// become stricter - or laxer - than the gate it mirrors. That budget is channel-exact now
// (CMH-BUILD-19): two independent renders of the same scene are byte-identical, so these assertions
// pass with the whole allowance to spare and only a real capture regression can move them.

// Run the capture tool with the example + output dir (and, for the extra scenes, an explicit
// prefix). With no prefix the tool defaults to "garden", so regenerating the garden tutorial
// screenshots stays a single, argument-light command.
function capture(example, outDir, prefix) {
  const args = [path.join(DEV, "tools", "capture_tutorial.mjs"), example, outDir];
  if (prefix) args.push(prefix);
  return spawnSync("node", args, { encoding: "utf8", timeout: 150000, killSignal: "SIGKILL" });
}

function check(example, outDir, prefix) {
  const args = [path.join(DEV, "tools", "capture_tutorial.mjs"), "--check", example, outDir];
  if (prefix) args.push(prefix);
  return spawnSync("node", args, { encoding: "utf8", timeout: 150000, killSignal: "SIGKILL" });
}

// The COMMITTED screenshots may only be rendered by the guarded wrapper (the digest-pinned
// container). Run the raw script against the default out dir with the renderer marker scrubbed, in
// --check mode so a REGRESSION here cannot rewrite the committed PNGs: it can only fail this test.
function rawAgainstCommitted() {
  const env = { ...process.env };
  delete env.CMH_SHOTS_RENDERER;
  return spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--check"],
                   { encoding: "utf8", timeout: 60000, killSignal: "SIGKILL", env });
}

test("the raw capture refuses to touch the committed screenshots without the guarded renderer (CMH-BUILD-16)", () => {
  const res = rawAgainstCommitted();
  expect(res.status).toBe(2);
  const err = res.stderr || "";
  expect(err).toContain("refusing");
  expect(err).toContain("pinned Playwright container");
  expect(err).toContain("npm run shots:check");
});

function freshDir(name) {
  const dir = path.join(TEST_TMP, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

test.afterAll(() => {
  // Only this worker's own scratch tree. The capture tool cleans its own per-process check/generate
  // scratch (tmp/tutorial-shots-check/<pid>, tmp/tutorial-shots-generate/<pid>) on success, so do
  // NOT wipe those shared parents here - that would race a sibling worker's in-flight subprocess.
  fs.rmSync(TEST_TMP, { recursive: true, force: true });
});

// dev/tools/capture_tutorial.mjs must regenerate every tutorial screenshot with one easy command
// and do it reproducibly. These behaviors were one monolithic (~5-capture, serial) test; they are
// split into focused tests, each with its OWN out dir, so the `heavy` project can run them in
// parallel across a few workers instead of one long serial block. They keep the same CMH-TUT-SHOTS-01
// coverage: default resolution, regenerate + clean --check, cross-run determinism, and stale detection.
test("--print-paths resolves the shipped tutorial defaults (CMH-TUT-SHOTS-01)", async () => {
  // The no-argument invocation (what `npm run shots` runs) resolves to the shipped tutorial defaults.
  const dry = spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--print-paths"],
    { encoding: "utf8" });
  expect(dry.error, String(dry.error)).toBeFalsy();
  expect(dry.status, dry.stderr).toBe(0);
  const defaults = JSON.parse(dry.stdout);
  expect(defaults.example.replace(/\\/g, "/")).toMatch(/plugins\/commentable-html\/examples\/report-community-garden\.html$/);
  expect(defaults.outDir.replace(/\\/g, "/")).toMatch(/plugins\/commentable-html\/docs\/assets$/);
  expect(defaults.prefix).toBe("garden");
  expect(defaults.check).toBe(false);
});

test("regenerates every garden shot into a nested out dir, and --check passes on fresh output (CMH-TUT-SHOTS-01)", async () => {
  test.setTimeout(180000);
  // A nonexistent NESTED output dir also exercises recursive out-dir creation.
  const outA = path.join(freshDir("regen"), "nested", "assets");
  const r1 = capture(EXAMPLE, outA);
  expect(r1.error, String(r1.error)).toBeFalsy();
  expect(r1.status, r1.stderr).toBe(0);
  for (const name of SHOTS) {
    expect(fs.existsSync(path.join(outA, `garden-${name}.png`)), `missing garden-${name}.png`).toBe(true);
  }
  // CMH-BUILD-17: the garden scene is the ONLY place the fixed-region clip (11-side-toc, 14-thread)
  // and the comment-search clip run, so assert HERE, on freshly captured output, that every
  // content-derived clip landed on the shared grid. Dropping quantization from any of those call
  // sites turns this red without waiting for a rebaseline.
  const offGrid = SHOTS
    .map((name) => ({ name, height: pngHeight(path.join(outA, `garden-${name}.png`)) }))
    .filter((s) => s.height % DIMENSION_DELTA_PX !== 0 && s.height !== FULL_VIEWPORT_PX)
    .map((s) => `garden-${s.name} (h=${s.height})`);
  expect(offGrid, "these fresh garden clips are neither on the clip grid nor the fixed full-viewport "
    + "height, so their height can drift with the renderer's font metrics").toEqual([]);
  const clean = check(EXAMPLE, outA);
  expect(clean.error, String(clean.error)).toBeFalsy();
  expect(clean.status, clean.stderr).toBe(0);
  expect(clean.stdout).toContain("tutorial screenshots are in sync");
});

// Overwrite / idempotency is a filesystem behavior independent of shot count or scene (`npm run
// shots` regenerates over the committed images), so verify it with a cheap 1-shot scene rather than
// a full 13-shot garden re-capture - keeping the coverage while shrinking the heavy job's floor.
test("capturing into an already-populated out dir overwrites without erroring (CMH-TUT-SHOTS-01)", () => {
  test.setTimeout(120000);
  const scene = EXTRA_SCENES.find((s) => s.prefix === "checklist");
  const out = path.join(freshDir("overwrite"), "nested", "assets");
  const target = path.join(out, `${scene.prefix}-${scene.shots[0]}.png`);
  const first = capture(scene.example, out, scene.prefix);
  expect(first.error, String(first.error)).toBeFalsy();
  expect(first.status, first.stderr).toBe(0);
  expect(fs.existsSync(target), `missing ${scene.prefix}-${scene.shots[0]}.png`).toBe(true);
  // Skip branch: re-capturing into a populated dir whose shot already MATCHES the fresh capture must
  // NOT rewrite it (imagesMatch true -> copy skipped, "(0 updated)"). This is the branch the old
  // garden 3rd capture ran but never asserted; assert it explicitly here.
  const noop = capture(scene.example, out, scene.prefix);
  expect(noop.error, String(noop.error)).toBeFalsy();
  expect(noop.status, noop.stderr).toBe(0);
  expect(noop.stdout, noop.stderr).toContain("(0 updated)");
  // Overwrite branch: replace the committed shot with non-image bytes so the re-capture cannot take
  // the compare-and-skip fast path (imagesMatch returns false on an undecodable target) and must run
  // the real copyFileSync overwrite branch - proving overwrite-in-place, not just a no-op re-run.
  fs.writeFileSync(target, Buffer.from("not a png"));
  const overwrite = capture(scene.example, out, scene.prefix);
  expect(overwrite.error, String(overwrite.error)).toBeFalsy();
  expect(overwrite.status, overwrite.stderr).toBe(0);
  expect(overwrite.stdout, overwrite.stderr).toContain("(1 updated)");
  // The garbage must have been overwritten back to a real PNG (89 50 4E 47 magic bytes).
  const after = fs.readFileSync(target);
  expect(after.subarray(0, 4).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47])),
    "re-capture did not overwrite the corrupted shot with a real PNG").toBe(true);
});

test("garden capture is deterministic across two independent runs (CMH-TUT-SHOTS-01)", async ({ browser }) => {
  test.setTimeout(180000);
  const comparePage = await browser.newPage();
  try {
    const outA = path.join(freshDir("det-a"), "nested", "assets");
    const outB = path.join(freshDir("det-b"), "nested", "assets");
    for (const [dir, label] of [[outA, "A"], [outB, "B"]]) {
      const r = capture(EXAMPLE, dir);
      expect(r.error, String(r.error)).toBeFalsy();
      expect(r.status, `capture ${label}: ${r.stderr}`).toBe(0);
    }
    for (const name of SHOTS) {
      const result = await compareImages(
        comparePage,
        path.join(outA, `garden-${name}.png`),
        path.join(outB, `garden-${name}.png`),
      );
      expect(result.ok, `${name} drifted between two runs: ${result.reason}`).toBe(true);
    }
  } finally {
    await comparePage.close();
  }
});

test("--check flags a stale garden shot (CMH-TUT-SHOTS-01)", async () => {
  test.setTimeout(180000);
  const outA = path.join(freshDir("stale"), "nested", "assets");
  const r1 = capture(EXAMPLE, outA);
  expect(r1.error, String(r1.error)).toBeFalsy();
  expect(r1.status, r1.stderr).toBe(0);
  fs.writeFileSync(path.join(outA, "garden-01-top-light.png"), Buffer.from("stale screenshot"));
  const stale = check(EXAMPLE, outA);
  expect(stale.error, String(stale.error)).toBeFalsy();
  expect(stale.status, stale.stdout + stale.stderr).toBe(1);
  expect(stale.stderr).toContain("garden-01-top-light.png differs");
});

// The board, checklist, and note features render only in their own example reports, so the tool
// captures each as a prefixed scene. Each scene gets the SAME three focused tests the garden scene
// has - regenerate + clean --check, cross-run determinism, and stale detection - as SEPARATE test()s
// (not one monolith). They are emitted in THREE type-grouped loops (all regens, then all determinism,
// then all stale) rather than three-per-scene, so Playwright's by-count sharding spreads each
// mermaid-heavy scene's three tests across DIFFERENT heavy shards instead of piling one scene's
// captures onto a single shard - the point of splitting the slow (mermaid) triage monolith.
for (const scene of EXTRA_SCENES) {
  test(`regenerates the ${scene.prefix} scene and --check passes on fresh output (CMH-TUT-SHOTS-01)`, () => {
    test.setTimeout(180000);
    const outA = path.join(freshDir(`${scene.prefix}-regen`), "nested", "assets");
    const r1 = capture(scene.example, outA, scene.prefix);
    expect(r1.error, String(r1.error)).toBeFalsy();
    expect(r1.status, r1.stderr).toBe(0);
    for (const name of scene.shots) {
      expect(fs.existsSync(path.join(outA, `${scene.prefix}-${name}.png`)),
        `missing ${scene.prefix}-${name}.png`).toBe(true);
    }
    const clean = check(scene.example, outA, scene.prefix);
    expect(clean.error, String(clean.error)).toBeFalsy();
    expect(clean.status, clean.stderr).toBe(0);
    expect(clean.stdout).toContain("tutorial screenshots are in sync");
  });
}

for (const scene of EXTRA_SCENES) {
  test(`${scene.prefix} capture is deterministic across two independent runs (CMH-TUT-SHOTS-01)`, async ({ browser }) => {
    test.setTimeout(180000);
    const comparePage = await browser.newPage();
    try {
      const outA = path.join(freshDir(`${scene.prefix}-det-a`), "nested", "assets");
      const outB = path.join(freshDir(`${scene.prefix}-det-b`), "nested", "assets");
      for (const [dir, label] of [[outA, "A"], [outB, "B"]]) {
        const r = capture(scene.example, dir, scene.prefix);
        expect(r.error, String(r.error)).toBeFalsy();
        expect(r.status, `capture ${label}: ${r.stderr}`).toBe(0);
      }
      for (const name of scene.shots) {
        const result = await compareImages(
          comparePage,
          path.join(outA, `${scene.prefix}-${name}.png`),
          path.join(outB, `${scene.prefix}-${name}.png`),
        );
        expect(result.ok, `${scene.prefix}-${name} drifted between two runs: ${result.reason}`).toBe(true);
      }
    } finally {
      await comparePage.close();
    }
  });
}

for (const scene of EXTRA_SCENES) {
  test(`--check flags a stale ${scene.prefix} shot (CMH-TUT-SHOTS-01)`, () => {
    test.setTimeout(180000);
    const outA = path.join(freshDir(`${scene.prefix}-stale`), "nested", "assets");
    const r1 = capture(scene.example, outA, scene.prefix);
    expect(r1.error, String(r1.error)).toBeFalsy();
    expect(r1.status, r1.stderr).toBe(0);
    const firstShot = `${scene.prefix}-${scene.shots[0]}.png`;
    fs.writeFileSync(path.join(outA, firstShot), Buffer.from("stale screenshot"));
    const stale = check(scene.example, outA, scene.prefix);
    expect(stale.error, String(stale.error)).toBeFalsy();
    expect(stale.status, stale.stdout + stale.stderr).toBe(1);
    expect(stale.stderr).toContain(`${firstShot} differs`);
  });
}

// The exact #698 symptom, end to end: the committed baseline was rendered by a DIFFERENT font stack,
// so the same element measures a couple of CSS pixels shorter or taller there. Quantizing the clip
// collapses that onto one grid value; a baseline that sits one grid line away is the residual
// straddle case the budget allows. Cropping only removes bottom rows, so the overlap the comparator
// comes down to is the same content.
function pngHeight(file) {
  // PNG dimensions live in the IHDR chunk: height is a big-endian uint32 at byte 20.
  return fs.readFileSync(file).readUInt32BE(20);
}

async function cropPngHeight(page, srcFile, dstFile, cropDevicePx) {
  const encoded = await page.evaluate(async ({ b64, crop }) => {
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = Math.max(1, img.naturalHeight - crop);
    canvas.getContext("2d").drawImage(img, 0, 0);
    return canvas.toDataURL("image/png").split(",")[1];
  }, { b64: fs.readFileSync(srcFile).toString("base64"), crop: cropDevicePx });
  fs.writeFileSync(dstFile, Buffer.from(encoded, "base64"));
}

test("a grid-line straddle in the baseline does not fail --check, a smaller shift does (CMH-BUILD-17)", async ({ browser }) => {
  test.setTimeout(180000);
  const scene = EXTRA_SCENES.find((s) => s.prefix === "checklist");
  const shot = `${scene.prefix}-${scene.shots[0]}.png`;
  const page = await browser.newPage();
  try {
    const straddled = path.join(freshDir("drift-tolerated"), "assets");
    fs.mkdirSync(straddled, { recursive: true });
    const seed = capture(scene.example, straddled, scene.prefix);
    expect(seed.error, String(seed.error)).toBeFalsy();
    expect(seed.status, seed.stderr).toBe(0);

    // The capture itself is what makes the shot renderer-independent: an element clip must land on
    // the shared grid, so the same scene yields the same height under either font stack.
    const captured = path.join(straddled, shot);
    expect(pngHeight(captured) % DIMENSION_DELTA_PX,
      "the checklist element clip is not on the shared clip grid").toBe(0);
    // Keep the PRISTINE capture: every case below must be built from it, so each crop is measured
    // against the fresh capture at exactly its own delta. Deriving a case from an already-cropped
    // copy would compound the crops, and a lax `delta <= one quantum` implementation would still
    // pass because the compounded delta lands outside the band either way.
    const pristine = path.join(freshDir("drift-pristine"), shot);
    fs.mkdirSync(path.dirname(pristine), { recursive: true });
    fs.copyFileSync(captured, pristine);

    // Quantizing cannot be boundary-free: two heights either side of a grid line land exactly one
    // quantum apart. That case must pass.
    await cropPngHeight(page, pristine, captured, DIMENSION_DELTA_PX);
    const tolerated = check(scene.example, straddled, scene.prefix);
    expect(tolerated.error, String(tolerated.error)).toBeFalsy();
    expect(tolerated.status, tolerated.stdout + tolerated.stderr).toBe(0);
    expect(tolerated.stdout).toContain("tutorial screenshots are in sync");

    // The allowance is that ONE exact value between two ON-GRID heights, not a tolerance band. A
    // SUB-quantum shift is the case that distinguishes the two: a band would wave it through, but it
    // can only be real content added or removed at the bottom edge, which the overlap-cropped pixel
    // diff cannot see. An OVER-quantum shift must fail too, so the allowance is not simply a floor.
    for (const crop of [DIMENSION_DELTA_PX - 1, DIMENSION_DELTA_PX + 1]) {
      const broken = path.join(freshDir(`drift-rejected-${crop}`), "assets");
      fs.mkdirSync(broken, { recursive: true });
      await cropPngHeight(page, pristine, path.join(broken, shot), crop);
      const rejected = check(scene.example, broken, scene.prefix);
      expect(rejected.error, String(rejected.error)).toBeFalsy();
      expect(rejected.status, `crop ${crop}: ${rejected.stdout}${rejected.stderr}`).toBe(1);
      expect(rejected.stderr).toContain(`${shot} differs`);
    }
  } finally {
    await page.close();
  }
});

// The no-positional default run (`npm run shots` / rebuild_all) drives ALL scenes at once. This test
// guards the tool/spec shot contract: a SCENE_ORDER drift that dropped a scene, or a shot added to
// the tool but not the spec (or vice versa), is caught here. The actual all-scenes `--check` freshness
// run is NOT repeated here (it would re-capture every scene, the heaviest single step): the required
// `plugin-tests` heavy-job shard 1/3 `shots:check` step already runs `capture_tutorial.mjs --check`,
// so duplicating it in the suite only slowed the heavy job.
test("the no-arg default run's shot registry matches the spec's scene lists (CMH-TUT-SHOTS-01)", async () => {
  const dry = spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--print-paths"], { encoding: "utf8" });
  expect(dry.error, String(dry.error)).toBeFalsy();
  expect(dry.status, dry.stderr).toBe(0);
  const registry = JSON.parse(dry.stdout).scenes;
  // The spec's own shot lists are the tool's authoritative lists - no silent drift either way.
  expect(registry.garden).toEqual(SHOTS);
  for (const scene of EXTRA_SCENES) expect(registry[scene.prefix]).toEqual(scene.shots);
  expect(Object.keys(registry).sort()).toEqual(["checklist", "garden", "note", "triage"]);
});
