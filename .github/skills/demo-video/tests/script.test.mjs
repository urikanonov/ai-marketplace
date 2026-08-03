// Scripted-capture contract. Everything here is a pure function of (step, clock, buffer), because
// the alternative - asserting against a real pty and a real agent - is neither fast nor repeatable.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  normalizeScript, readScript, stepReady, stepPayload, stepSubmit, fileReady, stepGaveUpNotice, makeSizeGuard, captureLimitBytes, DEFAULT_IDLE_MS,
} from "../tools/script.mjs";

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "demo-video-script-"));
const write = (name, body) => {
  const file = path.join(tmpDir, name);
  fs.writeFileSync(file, body);
  return file;
};

test("a script is validated up front rather than half-run (DEMO-SCRIPT-01)", () => {
  const bad = [
    [{}, /steps array/],
    [{ steps: [] }, /no steps/],
    [{ steps: [{ send: "x" }] }, /needs a mark/],
    [{ steps: [{ mark: "a", send: "x" }, { mark: "a", send: "y" }] }, /duplicate mark/],
    [{ steps: [{ mark: "a" }] }, /neither send nor sendFile/],
    [{ steps: [{ mark: "a", send: "x", sendFile: "y" }] }, /both send and sendFile/],
    [{ steps: [{ mark: "a", send: "x", expect: "" }] }, /empty expect/],
    [{ steps: [{ mark: "a", send: "x", timeoutMs: -1 }] }, /non-negative/],
  ];
  for (const [raw, re] of bad) {
    assert.throws(() => normalizeScript(raw, tmpDir), re, `should have rejected ${JSON.stringify(raw)}`);
  }
  // A step that only waits for quiet gets a default window; one with an explicit condition does not,
  // because an agent that is streaming its answer never goes quiet first.
  const { steps } = normalizeScript({
    steps: [{ mark: "a", send: "x" }, { mark: "b", send: "y", expect: "READY" }],
  }, tmpDir);
  assert.equal(steps[0].idleMs, DEFAULT_IDLE_MS);
  assert.equal(steps[1].idleMs, 0);
});

test("a step waits for quiet, a marker, or a file, and the timeout is the backstop (DEMO-SCRIPT-02)", () => {
  const { steps } = normalizeScript({
    steps: [
      { mark: "quiet", send: "a", idleMs: 1000, timeoutMs: 10000 },
      { mark: "marker", send: "b", expect: "READY", timeoutMs: 10000 },
      { mark: "file", send: "c", expectFile: path.join(tmpDir, "nope.md"), timeoutMs: 10000 },
    ],
  }, tmpDir);
  const [quiet, marker, file] = steps;

  assert.equal(stepReady(quiet, { now: 500, lastDataAt: 0, startedAt: 0 }).ready, false);
  assert.equal(stepReady(quiet, { now: 1500, lastDataAt: 0, startedAt: 0 }).ready, true);

  assert.equal(stepReady(marker, { now: 100, buffer: "still thinking", startedAt: 0 }).ready, false);
  assert.equal(stepReady(marker, { now: 100, buffer: "all READY now", startedAt: 0 }).ready, true);

  assert.equal(stepReady(file, { now: 100, fileExists: false, startedAt: 0 }).ready, false);
  assert.equal(stepReady(file, { now: 100, fileExists: true, startedAt: 0 }).ready, true);

  // The backstop fires even when the condition never came true, so a capture that ran long still
  // yields the session it did record.
  const late = stepReady(marker, { now: 10001, buffer: "nothing", startedAt: 0 });
  assert.equal(late.ready, true);
  assert.equal(late.timedOut, true);
});

test("an optional step is skipped on timeout, not sent blind (DEMO-SCRIPT-03)", () => {
  const { steps } = normalizeScript({
    steps: [{ mark: "trust", send: "2", expect: "Do you trust", timeoutMs: 5000, optional: true }],
  }, tmpDir);
  const step = steps[0];
  // The folder-trust dialog appears once per machine. On every later run it never appears, and a
  // required step would fire its keystroke into whatever is on screen instead - typically the
  // prompt, corrupting the very turn the clip is about.
  const out = stepReady(step, { now: 6000, buffer: "no dialog here", startedAt: 0 });
  assert.equal(out.skip, true);
  assert.notEqual(out.ready, true);
});

test("a file-backed step is read at send time, not at parse time (DEMO-SCRIPT-04)", () => {
  const target = path.join(tmpDir, "late.md");
  fs.rmSync(target, { force: true });
  // Parsing must succeed even though the file does not exist yet: in the loop capture the review
  // bundle is produced by the browser phase, which runs while the session sits on the prompt.
  const { steps } = normalizeScript({
    steps: [{ mark: "paste", sendFile: "late.md", expectFile: "late.md" }],
  }, tmpDir);
  assert.throws(() => stepPayload(steps[0]), /never appeared/);
  fs.writeFileSync(target, "the review");
  assert.equal(stepPayload(steps[0]), "the review");
});

test("Enter is a separate write, and a paste is bracketed (DEMO-SCRIPT-05)", () => {
  const { steps } = normalizeScript({
    steps: [
      { mark: "typed", send: "hello" },
      { mark: "pasted", send: "line one\r\nline two", paste: true },
      { mark: "noenter", send: "abc", enter: false },
    ],
  }, tmpDir);
  const [typed, pasted, noenter] = steps;

  // The payload must NOT carry the carriage return: a TUI composer that receives a long string and
  // a trailing return in one burst treats the return as typed text, and the prompt just sits there.
  assert.equal(typed.text, "hello");
  assert.equal(stepPayload(typed), "hello");
  assert.equal(stepSubmit(typed), "\r");
  assert.equal(stepSubmit(noenter), "");

  // A multi-line paste has to arrive bracketed or every newline submits its own turn, and CRLF is
  // normalized first because a bare CR inside the brackets submits in some readline implementations.
  const payload = stepPayload(pasted);
  assert.ok(payload.startsWith("\u001b[200~"), "a paste must open a bracketed paste");
  assert.ok(payload.endsWith("\u001b[201~"), "a paste must close a bracketed paste");
  assert.ok(!payload.includes("\r"), "no carriage return may survive inside a bracketed paste");
  assert.ok(payload.includes("line one\nline two"));
});

test("readScript reports the file it could not use (DEMO-SCRIPT-06)", () => {
  assert.throws(() => readScript(path.join(tmpDir, "missing.json")), /file not found/);
  const broken = write("broken.json", "{ not json");
  assert.throws(() => readScript(broken), /not valid JSON/);
  const good = write("good.json", JSON.stringify({ steps: [{ mark: "a", send: "hi" }] }));
  assert.equal(readScript(good).steps[0].mark, "a");
});

// A capture holds everything it records in memory, because the raw stream is never written to disk
// unscrubbed. Memory is therefore the binding constraint, and running out of it loses a recording
// that took twenty minutes to make - so the size is bounded and the session is ended cleanly at the
// limit rather than dying with nothing.
test("the capture size limit fires once and keeps what was recorded (DEMO-CAP-01)", () => {
  const fired = [];
  const guard = makeSizeGuard(1000, (total) => fired.push(total));

  assert.equal(guard(400), false, "under the limit is not an overflow");
  assert.equal(guard(500), false, "exactly at the limit is not an overflow");
  assert.equal(fired.length, 0);

  assert.equal(guard(200), true, "crossing the limit reports an overflow");
  assert.equal(fired.length, 1, "the session is ended once, not once per chunk");
  assert.equal(fired[0], 1100, "the callback is told how much had been captured");

  // Data keeps arriving while the child is being torn down; it must not re-fire.
  guard(5000);
  guard(5000);
  assert.equal(fired.length, 1, "an already-ended session must not be ended again");

  assert.throws(() => makeSizeGuard(0, () => {}), /positive number of bytes/);
  assert.throws(() => makeSizeGuard(Number.NaN, () => {}), /positive number of bytes/);
});

test("the capture limit is parsed strictly (DEMO-CAP-02)", () => {
  assert.equal(captureLimitBytes(1), 1024 * 1024);
  assert.equal(captureLimitBytes("0.5"), 512 * 1024);
  // A silently ignored limit is the failure this exists to prevent: the operator would believe the
  // capture was bounded when it was not.
  for (const bad of ["abc", "", 0, -1, Number.NaN, Infinity, null, undefined]) {
    assert.throws(() => captureLimitBytes(bad), /--max-mb must be a positive number/,
      `should have rejected ${JSON.stringify(bad)}`);
  }
});


// The committed recipes are the only reason these clips can be re-recorded: a published clip is a
// 90-minute unattended capture, and nobody rebuilds one from memory. So they are treated as shipped
// artifacts - they must parse, they must carry the ask whose text becomes the title card, and they
// must be reachable from SKILL.md, because a recipe nobody can find is a recipe nobody re-runs.
test("every committed capture recipe parses and is documented (DEMO-SCRIPT-07)", () => {
  const dir = path.join(import.meta.dirname, "..", "examples");
  // Match the recipes by name rather than taking every .json here, so a fixture or a config dropped
  // beside them later fails on its own terms instead of failing this test for the wrong reason.
  const recipes = fs.readdirSync(dir).filter((f) => f.endsWith("-session.json"));
  assert.ok(recipes.length, "examples/ should ship at least one capture recipe");

  const skill = fs.readFileSync(path.join(import.meta.dirname, "..", "SKILL.md"), "utf8");
  for (const name of recipes) {
    const script = readScript(path.join(dir, name));
    const ask = script.steps.find((s) => s.mark === "ask");
    assert.ok(ask, `${name} needs an "ask" step; render quotes its text on the title card`);
    // The card quotes the prompt VERBATIM, and 200 is where the card drops to a smaller font, so an
    // ask past it is a card the viewer has to squint at.
    assert.ok(ask.text && ask.text.length <= 200,
      `${name} ask is ${ask.text?.length} chars; keep it to one sentence so the title card stays readable`);
    // Enter must be its own write after a pause, or a TUI composer takes the return as typed text
    // and the capture sits on a full prompt line forever. The 450ms default is not enough for it.
    assert.ok(ask.enter && ask.submitMs >= 1000, `${name} ask needs enter with submitMs >= 1000`);
    // Naming the file is not enough - it has to be shown as the runnable thing, or the reader still
    // cannot re-record the clip. The command addresses the recipe by absolute path (the session must
    // not run from the checkout), so look for the flag and the filename on one line rather than
    // matching one literal spelling of the path.
    const documented = skill.split("\n").some((line) => line.includes("--script") && line.includes(name));
    assert.ok(documented,
      `SKILL.md should show ${name} as a runnable --script command so the clip can be re-recorded`);
  }
});

// A recipe's longest wait is a COST decision, not a detail: it is what an unattended capture bills
// when the ending never arrives, and picking one from memory is how a 90 minute budget outlived a
// two hour run. The budget therefore has to be written down next to the number it was derived from.
test("every recipe's longest wait is a documented budget, not a bare number (DEMO-SCRIPT-12)", () => {
  const dir = path.join(import.meta.dirname, "..", "examples");
  const recipes = fs.readdirSync(dir).filter((f) => f.endsWith("-session.json"));
  assert.ok(recipes.length, "examples/ should ship at least one capture recipe");

  // Written the way the budgets table writes it, so the committed number and the documented one are
  // the same number rather than two roundings of it.
  const plural = (n, unit) => `${n} ${unit}${n === 1 ? "" : "s"}`;
  const spell = (ms) => (ms % 60_000 === 0 ? plural(ms / 60_000, "minute") : plural(ms / 1000, "second"));

  const skill = fs.readFileSync(path.join(import.meta.dirname, "..", "SKILL.md"), "utf8");
  const rows = skill.split("\n").filter((line) => line.trim().startsWith("|"));
  for (const name of recipes) {
    // normalizeScript gives every step a timeout, so this is the effective backstop - a wait nobody
    // declared is still a wait the capture can sit on.
    const longest = Math.max(...readScript(path.join(dir, name)).steps.map((s) => s.timeoutMs));
    // The recipe cell has to BE the filename, not merely contain it, or a later `session.json` would
    // answer for `duck-session.json` and the row nobody wrote would look present.
    const row = rows.find((line) => line.split("|")[1]?.trim().replace(/`/g, "") === name);
    assert.ok(row,
      `SKILL.md needs a "Capture budgets" row for ${name}: its longest wait, and where that number came from`);
    const cells = row.split("|");
    const declared = cells[2] ?? "";
    // The rationale is the REST of the row, rejoined: a pipe inside it (an inline command, say) is
    // prose, not a column, and splitting on it would judge a full paragraph by its first fragment.
    const why = cells.slice(3).join("|").replace(/\|\s*$/, "");
    // Match the budget CELL, not the line: the row's rationale names the numbers this budget
    // replaced ("its 90 minute quit timeout", "ran 36 minutes"), so a line-level match would let a
    // timeout drift back onto one of them and still report the doc as current.
    assert.equal(declared.trim(), spell(longest),
      `the "Capture budgets" row for ${name} records "${declared.trim()}", but its longest wait is ${spell(longest)}`);
    // A number with no provenance is the thing this test exists to prevent, so the row has to say
    // where it came from in a sentence rather than restating the timeout in words.
    assert.ok(why.trim().length >= 40,
      `the "Capture budgets" row for ${name} needs to say where ${spell(longest)} came from`);
  }
});

test("a marker the recipe types itself is refused, not silently demoted to an idle wait (DEMO-SCRIPT-08)", () => {
  // The terminal paints the submitted turn back into the transcript, so an expect that appears in an
  // earlier send is satisfied by the echo. The step then rests entirely on idleMs - measured against
  // a real 65 minute multi-duck session, the stream fell quiet for 5-6s seventy-three times while
  // the agent worked, so a 6s idle gate was under a second from ending the capture each time.
  assert.throws(() => normalizeScript({
    steps: [
      { mark: "ask", send: "finish with a PANEL SUMMARY table" },
      { mark: "quit", expect: "PANEL SUMMARY", send: "/exit" },
    ],
  }), /step 1 \("quit"\) waits for "PANEL SUMMARY", but step 0 \("ask"\) sends it/);

  // A marker the agent alone can produce is exactly what this is asking for, so it must still pass.
  const ok = normalizeScript({
    steps: [
      { mark: "ask", send: "review the plan" },
      { mark: "quit", expect: "REVIEW-APPLIED", send: "/exit" },
    ],
  });
  assert.equal(ok.steps[1].expect, "REVIEW-APPLIED");

  // Only EARLIER steps can have echoed; a step may wait for a marker a LATER step goes on to send.
  assert.doesNotThrow(() => normalizeScript({
    steps: [
      { mark: "quit", expect: "DONE", send: "/exit" },
      { mark: "after", send: "DONE" },
    ],
  }));
});

test("an unknown step key is refused rather than ignored (DEMO-SCRIPT-09)", () => {
  // `expects` for `expect` parses clean and degrades the step to a bare idle wait - the same silent
  // failure, arrived at by a typo.
  assert.throws(() => normalizeScript({ steps: [{ mark: "a", send: "x", expects: "done" }] }),
    /step 0 has unknown key "expects"/);
  assert.throws(() => normalizeScript({ steps: [{ mark: "a", send: "x", submitMS: 1500 }] }),
    /step 0 has unknown key "submitMS"/);
  assert.doesNotThrow(() => normalizeScript({ steps: [{ mark: "a", send: "x", submitMs: 1500 }] }));
});

test("a step that gave up says so where it cannot scroll away (DEMO-SCRIPT-11)", () => {
  // The loop recipe really did spend its whole 25 minute timeout waiting for a marker the agent
  // never printed, and the closing lines still read like a clean take. The notice has to name the
  // step and say what it means for the cast, or the operator publishes the wrong ending.
  const notice = stepGaveUpNotice({ mark: "quit", reason: "timed out after 1500000ms" });
  assert.match(notice, /step "quit"/);
  assert.match(notice, /timed out after 1500000ms/);
  assert.match(notice, /never produced what it was waiting for/);
  assert.match(notice, /may not show the ending the recipe asked for/);
});

test("a file-backed wait requires the file THIS run produced (DEMO-SCRIPT-10)", () => {
  // The loop capture waits on a review bundle at a fixed path in the scratch dir, so last run's
  // bundle is already sitting there when the step starts. Existence alone would paste the STALE
  // review into a session that has not finished the new report - a clip that is coherently wrong.
  const startedAt = 10_000;
  assert.equal(fileReady("/x/review.md", startedAt, () => ({ mtimeMs: 9_999 })), false, "stale file");
  assert.equal(fileReady("/x/review.md", startedAt, () => ({ mtimeMs: 10_000 })), true, "written at step start");
  assert.equal(fileReady("/x/review.md", startedAt, () => ({ mtimeMs: 10_001 })), true, "fresh file");
  assert.equal(fileReady("/x/review.md", startedAt, () => { throw new Error("ENOENT"); }), false, "absent");
  assert.equal(fileReady(null, startedAt), false, "no file wanted");

  // And it is really wired into the wait, not just exported: a stale file must not satisfy the step.
  const step = normalizeScript({ steps: [{ mark: "paste", expectFile: "review.md", send: "x" }] }).steps[0];
  assert.equal(stepReady(step, { now: startedAt, startedAt, fileExists: false }).ready, false);
});
