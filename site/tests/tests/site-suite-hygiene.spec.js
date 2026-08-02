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

function testBlocks(source) {
  const starts = [];
  const re = /^test\s*\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)')/gm;
  let match = re.exec(source);
  while (match) {
    starts.push({ index: match.index, title: match[1] || match[2] });
    match = re.exec(source);
  }
  return starts.map((start, i) => ({
    title: start.title,
    body: source.slice(start.index, i + 1 < starts.length ? starts[i + 1].index : source.length),
  }));
}

test("demo-document assertions wait for the load instead of racing it (SITE-DEMO-14)", () => {
  const dir = __dirname;
  const files = fs.readdirSync(dir).filter((name) => name.endsWith(".spec.js") && name !== SELF);
  expect(files.length).toBeGreaterThan(0);

  const bareFrameLocator = [];
  const unbudgeted = [];
  for (const file of files) {
    const source = fs.readFileSync(path.join(dir, file), "utf8");
    source.split("\n").forEach((line, i) => {
      if (/\.frameLocator\s*\(/.test(line)) bareFrameLocator.push(`${file}:${i + 1}`);
    });
    for (const block of testBlocks(source)) {
      if (!LOADS_A_DEMO_DOCUMENT.some((marker) => marker.test(block.body))) continue;
      if (!/\btest\.slow\s*\(\s*\)/.test(block.body)) unbudgeted.push(`${file} - ${block.title}`);
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
