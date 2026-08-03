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
// Every way of reaching into a frame, not just the one the specs happen to use today: switching to
// contentFrame() would otherwise restore the same race with the guard still green.
const BARE_FRAME_ACCESS = /\.(?:frameLocator|contentFrame)\s*\(|\[\s*["'](?:frameLocator|contentFrame)["']\s*\]/;
const DEMO_FRAME_SELECTOR = /#demo-iframe|#demo\s+iframe|#demo-panel/;
const DEMO_DOCUMENT_URL = /demo\//;
const USES_HELPER = /\bdemoFrameReady\s*\(/;
const HAS_BUDGET = /\btest\.(?:slow|setTimeout)\s*\(/;

// A copy button's feedback is transient: the runtime sets the label, the state class, and the
// live-region text when the clipboard call RESOLVES and reverts all three 1500ms (success) or
// 2000ms (failure) later. A spec that reads that live races the revert twice over - a poll can
// miss the window on a cold or loaded runner, and separate assertions spread across it so the
// later ones read a reverted button (#859). The recorder captures every state from before the
// click, so it must be installed BEFORE the click to see any of them, its recorded states must
// actually be what the spec asserts on, and no live feedback assertion may remain beside it.
const COPY_BUTTON = /\.copy-btn/;
// Not just .click(): a keyboard or synthetic activation copies too, and treating one as "no click"
// would make the whole block EXEMPT rather than merely unordered.
const ACTIVATE =
  /\.(?:click|dblclick|dispatchEvent)\s*\(|\.press\s*\(|mouse\s*\.\s*click\s*\(|keyboard\s*\.\s*press\s*\(/;
const COPY_FEEDBACK =
  /["']copied["']|copy-failed|copy-status|copy manually|Copied to clipboard|clipboard\s*\.\s*readText/;
const USES_RECORDER = /\brecordCopyFeedback\s*\(/;
// The handle the recorder was assigned to, and the button it was installed on, so "the states are
// read" and "the recorder came first" are judged against THOSE and not any same-named method or
// any other element's click.
const RECORDER_CALL = /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*await\s+recordCopyFeedback\s*\(\s*([A-Za-z_$][\w$]*)/;
const RECORDED_METHODS = "(?:waitForState|waitForSettled|labels|states)";
// A binding for a copy button. Global and newline-tolerant: a test may bind more than one, and a
// locator chain wraps across lines.
const COPY_BINDING = /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=[^;]{0,200}?\.copy-btn/g;
const STATUS_BINDING = /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=[^;]{0,200}?\.copy-status/g;
// The racy shapes an unbound locator can still take.
const LIVE_FEEDBACK_ASSERTION =
  /(?:toHaveText|toContainText)\s*\(\s*["'\/](?:copied|copy manually|Copied to clipboard\.|Copy unavailable\.[^"'\/]*)["'\/]|toHaveClass\s*\(\s*\/copy-failed/;

function allBindings(body, pattern) {
  const names = [];
  const re = new RegExp(pattern.source, "g");
  let match = re.exec(body);
  while (match) {
    names.push(match[1]);
    match = re.exec(body);
  }
  return names;
}

function copyBindings(body) {
  const names = allBindings(body, COPY_BINDING);
  const call = body.match(RECORDER_CALL);
  // The recorder's own argument names the button even when its binding is shaped unusually.
  if (call && !names.includes(call[2])) names.push(call[2]);
  return names;
}

// Any read of the clicked button's own text or class is a feedback assertion, whatever value it
// expects: waiting for the ORIGINAL label to come back races the revert exactly as waiting for
// "copied" does, and keying only on the feedback strings would wave that shape through.
function readsCopyButtonState(body) {
  return copyBindings(body).some((name) =>
    new RegExp("expect\\s*\\(\\s*" + name + "\\b").test(body)
      || new RegExp("\\b" + name + "\\s*\\.\\s*(?:textContent|innerText|getAttribute)\\s*\\(").test(body));
}

function assertsCopyFeedback(body) {
  return COPY_BUTTON.test(body) && ACTIVATE.test(body)
    && (COPY_FEEDBACK.test(body) || readsCopyButtonState(body));
}

// The recorded states have to be the thing the spec reads, or the recorder is decoration - and the
// read has to be on the recorder's OWN handle, not any object that happens to share a method name.
function readsRecordedStates(body) {
  const call = body.match(RECORDER_CALL);
  if (!call) return false;
  return new RegExp("\\b" + call[1] + "\\s*\\.\\s*" + RECORDED_METHODS + "\\s*\\(").test(body);
}

function copyActivationIndex(body) {
  // The EARLIEST activation of any copy button in the block: the recorder must precede all of them.
  const indexes = copyBindings(body)
    // Allow a chained locator (`btn.first().click()`), or the fallback below would judge ordering
    // against an unrelated element and read a compliant test as racy.
    .map((name) => body.search(new RegExp(
      "\\b" + name + "\\s*(?:\\.\\s*\\w+\\s*\\([^)]*\\)\\s*)*\\.\\s*(?:click|dblclick|press|dispatchEvent)\\s*\\(",
    )))
    .filter((index) => index >= 0);
  if (indexes.length) return Math.min.apply(null, indexes);
  return body.search(ACTIVATE);
}

// Reading the button or its live region AFTER the activation is the race itself, whatever the
// assertion expects and whichever matcher it uses; before the activation nothing has changed yet,
// so reading the original label there is harmless.
function hasLiveFeedbackAssertion(body) {
  if (LIVE_FEEDBACK_ASSERTION.test(body)) return true;
  const activation = copyActivationIndex(body);
  if (activation < 0) return false;
  const names = copyBindings(body).concat(allBindings(body, STATUS_BINDING));
  return names.some((name) => {
    // Every occurrence is checked, not just the first: reading the original label BEFORE the
    // activation is legitimate and would otherwise mask a live read after it.
    const live = new RegExp(
      "expect\\s*\\(\\s*" + name + "\\b[^)]*\\)\\s*(?:\\.\\s*not)?\\s*\\.\\s*(?:toHaveText|toContainText|toHaveClass)\\s*\\("
        + "|\\b" + name + "\\s*(?:\\.\\s*\\w+\\s*\\([^)]*\\)\\s*)*\\.\\s*(?:textContent|innerText|getAttribute)\\s*\\(",
      "g",
    );
    let match = live.exec(body);
    while (match) {
      if (match.index > activation) return true;
      match = live.exec(body);
    }
    return false;
  });
}
// Installing the recorder after the click would miss the very transition it exists to capture, so
// position is checked, not just presence.
function recorderPrecedesClick(body) {
  const recorder = body.search(USES_RECORDER);
  const activation = copyActivationIndex(body);
  return recorder >= 0 && activation >= 0 && recorder < activation;
}

// Judged on the WHOLE test body rather than one line: holding the selector in a variable
// (`const el = page.locator("#demo-iframe"); await el.contentFrame();`) splits the two halves
// across lines, and a line-scoped check waves that straight through.
function readsFramedDemo(body) {
  return BARE_FRAME_ACCESS.test(body)
    && (DEMO_FRAME_SELECTOR.test(body) || DEMO_DOCUMENT_URL.test(body));
}

function loadsDemoDocument(body) {
  return USES_HELPER.test(body) || DEMO_DOCUMENT_URL.test(body) || readsFramedDemo(body);
}

function testBlocks(source) {
  const { text, code } = stripComments(source);
  const starts = [];
  const re = /^[ \t]*(?:test|it)(?:\.(?:only|skip|fixme|serial|parallel))*\s*\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|`((?:\\.|[^`\\])*)`)/gm;
  let match = re.exec(text);
  while (match) {
    starts.push({ index: match.index, title: match[1] || match[2] || match[3] });
    match = re.exec(text);
  }
  const blocks = [];
  let cursor = 0;
  let outside = "";
  for (let i = 0; i < starts.length; i += 1) {
    const limit = i + 1 < starts.length ? starts[i + 1].index : text.length;
    const end = blockEnd(code, starts[i].index, limit);
    outside += text.slice(cursor, starts[i].index);
    cursor = Math.max(cursor, end);
    blocks.push({ title: starts[i].title, body: text.slice(starts[i].index, end) });
  }
  outside += text.slice(cursor);
  // Everything OUTSIDE a test body (module scope, a local helper, a trailing statement) is scanned
  // as well, so frame access cannot hide by moving out of a test.
  return [{ title: "<module scope>", body: outside }].concat(blocks);
}

// The body ends at the brace that closes the callback, NOT at the next test: slicing between test
// starts sweeps up whatever sits between them, so a helper or a stray line would be blamed on the
// preceding test. Braces are counted on the string-blanked projection, so a brace inside a
// selector or a message cannot unbalance it.
function blockEnd(code, start, limit) {
  // Find the CALLBACK's opening brace: the first `{` after the arrow, not the one in the
  // destructured fixture list (`async ({ page }) =>`), which would close immediately.
  const arrow = code.indexOf("=>", start);
  const open = code.indexOf("{", arrow >= 0 ? arrow : start);
  if (open < 0) return limit;
  let depth = 0;
  for (let i = open; i < code.length; i += 1) {
    if (code[i] === "{") depth += 1;
    else if (code[i] === "}") {
      depth -= 1;
      if (depth === 0) return i + 1;
    }
  }
  return limit;
}

// Returns two same-length projections of the source: `text` with comments blanked (so a
// commented-out test.slow() or a commented demo path is not read as code), and `code` with string
// and template contents blanked as well (used only for counting braces).
function stripComments(source) {
  let text = "";
  let code = "";
  let state = "code";
  let i = 0;
  const push = (inText, inCode) => { text += inText; code += inCode; };
  while (i < source.length) {
    const ch = source[i];
    const next = source[i + 1];
    if (state === "code") {
      if (ch === "/" && next === "/") { state = "line"; push("  ", "  "); i += 2; continue; }
      if (ch === "/" && next === "*") { state = "block"; push("  ", "  "); i += 2; continue; }
      if (ch === "'" || ch === '"' || ch === "`") state = ch;
      push(ch, ch);
      i += 1;
      continue;
    }
    if (state === "line") {
      if (ch === "\n") { state = "code"; push(ch, ch); } else push(" ", " ");
      i += 1;
      continue;
    }
    if (state === "block") {
      if (ch === "*" && next === "/") { state = "code"; push("  ", "  "); i += 2; continue; }
      push(ch === "\n" ? ch : " ", ch === "\n" ? ch : " ");
      i += 1;
      continue;
    }
    // Inside a string or template literal: keep it in `text`, blank it in `code`.
    if (ch === "\\" && next !== undefined) { push(ch + next, "  "); i += 2; continue; }
    if (ch === state) state = "code";
    push(ch, ch === "\n" ? ch : " ");
    i += 1;
  }
  return { text: text, code: code };
}

test("demo-document assertions wait for the load instead of racing it (SITE-DEMO-14)", () => {
  // A scanner that quietly stops matching is worse than no scanner, so prove the detectors still
  // fire on a reintroduced race that dodges the two obvious scan shapes: nested in a describe
  // block (invisible to a column-0-only split) and reaching the frame through a variable
  // (invisible to a line-scoped match).
  const racy = [
    'test.describe("demo", () => {',
    '  test("racy", async ({ page }) => {',
    '    await page.goto("/commentable-html/");',
    '    const el = page.locator("#demo-iframe");',
    "    const frame = await el.contentFrame();",
    '    await expect(frame.locator(".cm-toolbar")).toHaveCount(1);',
    "  });",
    "});",
  ].join("\n");
  const racyBlocks = testBlocks(racy).filter((block) => block.title !== "<module scope>");
  expect(racyBlocks.map((block) => block.title)).toEqual(["racy"]);
  expect(readsFramedDemo(racyBlocks[0].body)).toBe(true);
  expect(USES_HELPER.test(racyBlocks[0].body)).toBe(false);
  expect(loadsDemoDocument(racyBlocks[0].body)).toBe(true);
  expect(HAS_BUDGET.test(racyBlocks[0].body)).toBe(false);

  // A commented-out budget is not a budget, and a demo path in a comment is not a load: both are
  // stripped before the markers run, and a test body stops at its own closing brace rather than
  // swallowing whatever follows it.
  const commented = [
    'test("commented", async ({ page }) => {',
    "  // test.slow()",
    '  await page.goto("/commentable-html/");',
    "});",
    "",
    '// a note about commentable-html/demo/report-taxi.html',
    'const stray = "demo/report-taxi.html";',
  ].join("\n");
  const commentedBlock = testBlocks(commented).find((block) => block.title === "commented");
  expect(HAS_BUDGET.test(commentedBlock.body)).toBe(false);
  expect(loadsDemoDocument(commentedBlock.body)).toBe(false);

  const dir = __dirname;
  const files = fs.readdirSync(dir).filter((name) => name.endsWith(".spec.js") && name !== SELF);
  expect(files.length).toBeGreaterThan(0);

  const racyFrameAccess = [];
  const unbudgeted = [];
  for (const file of files) {
    const source = fs.readFileSync(path.join(dir, file), "utf8");
    for (const block of testBlocks(source)) {
      const where = `${file} - ${block.title}`;
      if (readsFramedDemo(block.body) && !USES_HELPER.test(block.body)) racyFrameAccess.push(where);
      // A budget only exists inside a test, so the module-scope pseudo-block is exempt from it.
      if (block.title === "<module scope>") continue;
      if (loadsDemoDocument(block.body) && !HAS_BUDGET.test(block.body)) unbudgeted.push(where);
    }
  }

  expect(
    racyFrameAccess,
    "reach the framed demo through demoFrameReady() in site-helpers.js, which waits for that "
      + "document to finish loading, rather than a bare frameLocator()/contentFrame() whose first "
      + "content assertion absorbs the download",
  ).toEqual([]);
  expect(
    unbudgeted,
    "a test that loads a multi-megabyte demo document must declare test.slow(): the default 30s "
      + "test timeout is shorter than the explicit load wait plus the mount budget, so without it "
      + "the test expires mid-wait on a cold runner",
  ).toEqual([]);
});


test("copy-button assertions read a recorded transition instead of racing the revert (SITE-COPY-04)", () => {
  // Prove the detectors still fire on a reintroduced race before trusting a clean scan: this is
  // exactly the shape both #859 flakes had - click, then sample the live button.
  const racy = [
    'test("racy", async ({ page }) => {',
    '  await page.goto("/");',
    '  const btn = page.locator("#install .copy-btn").first();',
    "  await btn.click();",
    '  await expect(btn).toHaveText("copied");',
    "});",
  ].join("\n");
  const racyBlock = testBlocks(racy).find((block) => block.title === "racy");
  expect(assertsCopyFeedback(racyBlock.body)).toBe(true);
  expect(recorderPrecedesClick(racyBlock.body)).toBe(false);
  expect(HAS_BUDGET.test(racyBlock.body)).toBe(false);

  // A recorder installed AFTER the click has already missed the transition, so presence alone is
  // not enough - and a click that asserts nothing about the feedback (the card-overlay test) is
  // not this class of test and stays exempt.
  const late = [
    'test("late", async ({ page }) => {',
    "  test.slow();",
    '  const btn = page.locator("#install .copy-btn").first();',
    "  await btn.click();",
    "  const feedback = await recordCopyFeedback(btn);",
    '  await feedback.waitForState((state) => state.copied, "copied");',
    "});",
  ].join("\n");
  const lateBlock = testBlocks(late).find((block) => block.title === "late");
  expect(assertsCopyFeedback(lateBlock.body)).toBe(true);
  expect(recorderPrecedesClick(lateBlock.body)).toBe(false);

  const unrelated = [
    'test("unrelated", async ({ page }) => {',
    '  await page.locator(".plugin-card .copy-btn").first().click();',
    '  await expect(page).toHaveURL(/\\/$/);',
    "});",
  ].join("\n");
  const unrelatedBlock = testBlocks(unrelated).find((block) => block.title === "unrelated");
  expect(assertsCopyFeedback(unrelatedBlock.body)).toBe(false);

  // Ordering is judged against the COPY button's own activation, so clicking something else first
  // (a tab, a consent prompt) is not mistaken for the copy click.
  const tabFirst = [
    'test("tab first", async ({ page }) => {',
    "  test.slow();",
    '  await page.locator(".install-tab").first().click();',
    '  const btn = page.locator("#install .copy-btn").first();',
    "  const feedback = await recordCopyFeedback(btn);",
    "  await btn.click();",
    '  await feedback.waitForState((state) => state.copied, "copied");',
    "});",
  ].join("\n");
  const tabFirstBlock = testBlocks(tabFirst).find((block) => block.title === "tab first");
  expect(assertsCopyFeedback(tabFirstBlock.body)).toBe(true);
  expect(recorderPrecedesClick(tabFirstBlock.body)).toBe(true);
  expect(readsRecordedStates(tabFirstBlock.body)).toBe(true);
  expect(hasLiveFeedbackAssertion(tabFirstBlock.body)).toBe(false);
  expect(HAS_BUDGET.test(tabFirstBlock.body)).toBe(true);

  // A keyboard activation copies just as a click does, so it must not make the block exempt.
  const keyboard = [
    'test("keyboard", async ({ page }) => {',
    '  const btn = page.locator("#install .copy-btn").first();',
    "  await btn.press(\"Enter\");",
    '  await expect(btn).toHaveText("copied");',
    "});",
  ].join("\n");
  const keyboardBlock = testBlocks(keyboard).find((block) => block.title === "keyboard");
  expect(assertsCopyFeedback(keyboardBlock.body)).toBe(true);
  expect(recorderPrecedesClick(keyboardBlock.body)).toBe(false);

  // A recorder that is installed and then ignored is decoration: the live assertion beside it is
  // still the race, so both the missing read and the surviving live assertion are caught.
  const decorative = [
    'test("decorative", async ({ page }) => {',
    "  test.slow();",
    '  const btn = page.locator("#install .copy-btn").first();',
    "  const feedback = await recordCopyFeedback(btn);",
    "  await btn.click();",
    '  await expect(btn).toHaveText("copied");',
    "});",
  ].join("\n");
  const decorativeBlock = testBlocks(decorative).find((block) => block.title === "decorative");
  expect(recorderPrecedesClick(decorativeBlock.body)).toBe(true);
  expect(readsRecordedStates(decorativeBlock.body)).toBe(false);
  expect(hasLiveFeedbackAssertion(decorativeBlock.body)).toBe(true);

  // A test that waits for the ORIGINAL label to come back races the revert exactly as one waiting
  // for "copied" does, and names none of the feedback strings - so it must still be caught.
  const restoreOnly = [
    'test("restore only", async ({ page }) => {',
    '  const btn = page.locator("#install .copy-btn").first();',
    "  const label = (await btn.textContent()).trim();",
    "  await btn.click();",
    "  await expect(btn).toHaveText(label, { timeout: 4000 });",
    "});",
  ].join("\n");
  const restoreOnlyBlock = testBlocks(restoreOnly).find((block) => block.title === "restore only");
  expect(COPY_FEEDBACK.test(restoreOnlyBlock.body)).toBe(false);
  expect(assertsCopyFeedback(restoreOnlyBlock.body)).toBe(true);
  expect(recorderPrecedesClick(restoreOnlyBlock.body)).toBe(false);
  expect(hasLiveFeedbackAssertion(restoreOnlyBlock.body)).toBe(true);

  // Bypass shapes the literal-string detector alone would miss: a different matcher, a regex
  // expectation, a raw live read, and a copy button bound across a wrapped locator chain.
  const bypass = [
    'test("bypass", async ({ page }) => {',
    "  test.slow();",
    "  const btn = page",
    '    .locator("#install .copy-btn")',
    "    .first();",
    "  const feedback = await recordCopyFeedback(btn);",
    "  await btn.click();",
    '  await feedback.waitForState((state) => state.copied, "copied");',
    "  await expect.poll(() => btn.textContent()).toContain(\"copied\");",
    "});",
  ].join("\n");
  const bypassBlock = testBlocks(bypass).find((block) => block.title === "bypass");
  expect(copyBindings(bypassBlock.body)).toContain("btn");
  expect(recorderPrecedesClick(bypassBlock.body)).toBe(true);
  expect(readsRecordedStates(bypassBlock.body)).toBe(true);
  expect(hasLiveFeedbackAssertion(bypassBlock.body)).toBe(true);

  // A same-named method on another object is not a read of the recorded states.
  const borrowed = [
    'test("borrowed", async ({ page }) => {',
    "  test.slow();",
    '  const btn = page.locator("#install .copy-btn").first();',
    "  const feedback = await recordCopyFeedback(btn);",
    "  await btn.click();",
    '  await page.waitForState("idle");',
    "});",
  ].join("\n");
  const borrowedBlock = testBlocks(borrowed).find((block) => block.title === "borrowed");
  expect(readsRecordedStates(borrowedBlock.body)).toBe(false);

  const dir = __dirname;
  const files = fs.readdirSync(dir).filter((name) => name.endsWith(".spec.js") && name !== SELF);
  expect(files.length).toBeGreaterThan(0);

  const racyFeedback = [];
  const unbudgeted = [];
  const outsideATest = [];
  for (const file of files) {
    const source = fs.readFileSync(path.join(dir, file), "utf8");
    for (const block of testBlocks(source)) {
      const where = `${file} - ${block.title}`;
      if (!assertsCopyFeedback(block.body)) continue;
      // A budget can only be declared inside a test, so a copy flow extracted to module scope would
      // escape it entirely - keep the flow in the test rather than exempting it.
      if (block.title === "<module scope>") {
        outsideATest.push(where);
        continue;
      }
      if (!recorderPrecedesClick(block.body)
        || !readsRecordedStates(block.body)
        || hasLiveFeedbackAssertion(block.body)) {
        racyFeedback.push(where);
      }
      if (!HAS_BUDGET.test(block.body)) unbudgeted.push(where);
    }
  }
  expect(
    outsideATest,
    "keep a copy-button flow inside the test that owns it: a helper at module scope cannot declare "
      + "test.slow(), so extracting the flow there hides it from the budget check",
  ).toEqual([]);
  expect(
    racyFeedback,
    "install recordCopyFeedback() from site-helpers.js BEFORE activating a copy button, assert on "
      + "the states it records, and drop any live feedback assertion: the label, the state class, "
      + "and the live-region text revert 1500-2000ms after the clipboard call resolves, so a live "
      + "assertion races that revert and a second one reads an already-reverted button",
  ).toEqual([]);
  expect(
    unbudgeted,
    "a test that waits for copy-button feedback must declare test.slow(): the wait covers a "
      + "clipboard round trip on a cold runner, which the default 30s test timeout does not budget for",
  ).toEqual([]);
});
