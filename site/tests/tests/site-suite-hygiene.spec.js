const fs = require("fs");
const path = require("path");
const { test, expect } = require("@playwright/test");

// Every demo document is a self-contained 1-2.5 MB report and the plugin page's demo iframe is
// loading="lazy", so an assertion on the framed content races the DOWNLOAD inside the same fixed
// timeout that is meant to cover the mount. That is what failed once on a cold full-suite run
// (#814), and because the line reporter prints a failure next to the progress line of whichever
// test started last, it read as a regression in an unrelated test. These two invariants keep the
// wait explicit, so the load can never be what a content assertion is timing out on.

const SELF = path.basename(__filename);
const LOADS_A_DEMO_DOCUMENT = [/\bdemoFrameReady\s*\(/, /demo\//];
// Every way of reaching into a frame, not just the one the specs happen to use today: switching to
// contentFrame() would restore the same race with the guard still green. Scoped to the demo frame,
// so an unrelated iframe test is not forced through a demo-specific helper.
const BARE_FRAME_ACCESS = /\.(?:frameLocator|contentFrame)\s*\(|\[\s*["'](?:frameLocator|contentFrame)["']\s*\]/;
const DEMO_FRAME = /demo/i;

function testBlocks(source) {
  const starts = [];
  const re = /^[ \t]*(?:test|it)(?:\.(?:only|skip|fixme|serial|parallel))*\s*\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|`((?:\\.|[^`\\])*)`)/gm;
  let match = re.exec(source);
  while (match) {
    starts.push({ index: match.index, title: match[1] || match[2] || match[3] });
    match = re.exec(source);
  }
  return starts.map((start, i) => ({
    title: start.title,
    body: source.slice(start.index, i + 1 < starts.length ? starts[i + 1].index : source.length),
  }));
}

test("demo-document assertions wait for the load instead of racing it (SITE-DEMO-14)", () => {
  // A scanner that quietly stops matching is worse than no scanner, so prove the detectors still
  // fire on a reintroduced race - including one nested inside a describe block, where the
  // column-0-only version of this scan saw nothing at all.
  const racy = [
    'test.describe("demo", () => {',
    '  test("racy", async ({ page }) => {',
    '    await page.goto("/commentable-html/demo/report-taxi.html");',
    '    const frame = page.frameLocator("#demo-iframe");',
    '    await expect(frame.locator(".cm-toolbar")).toHaveCount(1);',
    "  });",
    "});",
  ].join("\n");
  const racyBlocks = testBlocks(racy);
  expect(racyBlocks.map((block) => block.title)).toEqual(["racy"]);
  expect(LOADS_A_DEMO_DOCUMENT.some((marker) => marker.test(racyBlocks[0].body))).toBe(true);
  expect(/\btest\.slow\s*\(/.test(racyBlocks[0].body)).toBe(false);
  expect(racy.split("\n").some((line) => BARE_FRAME_ACCESS.test(line) && DEMO_FRAME.test(line))).toBe(true);

  const dir = __dirname;
  const files = fs.readdirSync(dir).filter((name) => name.endsWith(".spec.js") && name !== SELF);
  expect(files.length).toBeGreaterThan(0);

  const bareFrameLocator = [];
  const unbudgeted = [];
  for (const file of files) {
    const source = fs.readFileSync(path.join(dir, file), "utf8");
    source.split("\n").forEach((line, i) => {
      if (BARE_FRAME_ACCESS.test(line) && DEMO_FRAME.test(line)) bareFrameLocator.push(`${file}:${i + 1}`);
    });
    for (const block of testBlocks(source)) {
      if (!LOADS_A_DEMO_DOCUMENT.some((marker) => marker.test(block.body))) continue;
      if (!/\btest\.slow\s*\(/.test(block.body)) unbudgeted.push(`${file} - ${block.title}`);
    }
  }

  expect(
    bareFrameLocator,
    "reach the framed demo through demoFrameReady() in site-helpers.js, which waits for that "
      + "document to finish loading, rather than a bare frameLocator() whose first assertion "
      + "absorbs the download",
  ).toEqual([]);
  expect(
    unbudgeted,
    "a test that loads a multi-megabyte demo document must declare test.slow(), or a cold runner "
      + "spends the whole 30s budget on the download and fails in the assertion that follows",
  ).toEqual([]);
});
