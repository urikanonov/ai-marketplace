// The capture control path, driven end to end with a stubbed stream and a fake clock.
//
// The failure these cover is the worst one this tool has: a capture that finished its session and
// then sat forever without writing anything, losing a live agent run that took over an hour to
// produce. Reproducing a wedge is timing-dependent and hopeless in a test, so the session is a stub
// that behaves exactly like the wedged one did - it prints, it goes quiet, and it NEVER exits - and
// the clock is a counter the test advances. Every assertion here is about the file on disk: a
// capture that does not finalize is the bug.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { captureSession } from "../tools/record_demo.mjs";
import { normalizeScript } from "../tools/script.mjs";
import { DEFAULT_RULES } from "../tools/redact.mjs";

const scratch = () => fs.mkdtempSync(path.join(os.tmpdir(), "demo-video-capture-"));

// Time is a counter the sleeper advances, so a two-minute grace costs a few microtasks. `setImmediate`
// rather than a resolved promise: the driver and the supervisor both wait on this, and a macrotask
// boundary lets each of them make progress between ticks the way a real timer would.
function fakeClock(start = 1000000) {
  let t = start;
  return {
    now: () => t,
    nap: (ms) => { t += Math.max(0, ms); return new Promise((done) => setImmediate(done)); },
  };
}

// A session that prints and then stops, exactly like the wedged capture: `kill()` is recorded but
// changes nothing unless the test asked for a child that actually dies. `exitAfterWrites` ends the
// session on a WRITE rather than on a timer, so "the session ended by itself" is ordered against
// what the driver did rather than against the event loop.
function fakeChild({ diesOnKill = false, exitAfterWrites = 0 } = {}) {
  let onData = () => {};
  let onExit = () => {};
  const child = {
    written: [],
    kills: 0,
    exited: false,
    onData: (cb) => { onData = cb; },
    onExit: (cb) => { onExit = cb; },
    write: (data) => {
      child.written.push(data);
      if (exitAfterWrites && child.written.length >= exitAfterWrites) child.exit(0);
    },
    resize: () => {},
    kill: () => {
      child.kills += 1;
      if (diesOnKill) child.exit(0);
    },
    emit: (text) => onData(text),
    exit: (code = 0) => {
      if (child.exited) return;
      child.exited = true;
      onExit({ exitCode: code });
    },
  };
  return child;
}

function harness(overrides = {}) {
  const dir = scratch();
  const clock = fakeClock();
  const warnings = [];
  const progress = [];
  return {
    dir,
    clock,
    warnings,
    progress,
    options: {
      outFile: path.join(dir, "probe.cast.json"),
      outRoot: dir,
      rules: DEFAULT_RULES,
      command: ["copilot"],
      exitGraceMs: 120000,
      killGraceMs: 5000,
      progressMs: 60000,
      pollMs: 200,
      now: clock.now,
      nap: clock.nap,
      warn: (line) => warnings.push(line),
      progress: (line) => progress.push(line),
      ...overrides,
    },
    cleanup: () => fs.rmSync(dir, { recursive: true, force: true }),
  };
}

test("a step whose condition never appears still finalizes on the wall clock (DEMO-CAP-03)", async () => {
  const h = harness();
  const child = fakeChild();
  const script = normalizeScript({
    steps: [
      { mark: "ask", send: "review this", idleMs: 0, timeoutMs: 5000 },
      // The marker the agent never printed, and then the `/exit` that the TUI never acted on.
      { mark: "quit", send: "/exit", expect: "PANEL SUMMARY", idleMs: 30000, timeoutMs: 60000 },
    ],
  }, h.dir);

  const running = captureSession({ ...h.options, child, script });
  child.emit("copilot session\r\n");
  const outcome = await running;

  // The whole point: the session never ended itself, and the capture ended it and kept the take.
  assert.equal(outcome.ended, "no-exit", "the wall clock did not end the wedged session");
  assert.ok(child.kills > 0, "the wedged session was never killed");
  assert.ok(fs.existsSync(outcome.outFile), "the cast was not written");
  const cast = JSON.parse(fs.readFileSync(outcome.outFile, "utf8"));
  assert.equal(cast.events.length, 1);
  assert.match(cast.events[0].data, /copilot session/);
  assert.ok(fs.existsSync(outcome.transcriptFile), "the transcript was not written");
  // Both turns were still sent - the timeout reports, it does not abandon the recipe.
  assert.deepEqual(outcome.marks.map((m) => m.label), ["ask", "quit"]);
  assert.deepEqual(outcome.timedOutSteps.map((s) => s.mark), ["quit"]);
  h.cleanup();
});

test("an interrupted capture still writes its cast (DEMO-CAP-04)", async () => {
  const h = harness();
  const child = fakeChild();
  let interrupt = null;
  const running = captureSession({
    ...h.options,
    child,
    attachInterrupt: (fn) => { interrupt = fn; },
  });
  child.emit("half a session\r\n");
  assert.equal(typeof interrupt, "function", "the caller was never given a way to interrupt");
  assert.equal(interrupt("interrupt"), true, "the first interrupt was refused");
  // A second signal is the operator asking to stop waiting; the caller uses this to exit hard.
  assert.equal(interrupt("interrupt"), false, "a second interrupt was treated as the first");
  const outcome = await running;

  assert.equal(outcome.ended, "interrupt");
  assert.ok(fs.existsSync(outcome.outFile), "an interrupted capture lost the session");
  const cast = JSON.parse(fs.readFileSync(outcome.outFile, "utf8"));
  assert.match(cast.events.map((e) => e.data).join(""), /half a session/);
  assert.ok(
    h.warnings.some((w) => /interrupt/i.test(w) && /may not show the ending/i.test(w)),
    `no warning said the ending is not the recipe's: ${JSON.stringify(h.warnings)}`,
  );
  h.cleanup();
});

test("an interrupt stops the script mid-step, not just the session (DEMO-CAP-04)", async () => {
  // The interrupt ends the SESSION, but a driver left waiting out a step's timeout would hold the
  // finalize for the rest of that timeout - which the shipped recipes measure in tens of minutes,
  // so the operator would still be watching a wedged process after asking it to stop.
  const h = harness();
  const child = fakeChild();
  const script = normalizeScript({
    steps: [{ mark: "quit", send: "/exit", expect: "NEVER PRINTED", idleMs: 0, timeoutMs: 3600000 }],
  }, h.dir);
  let interrupt = null;
  const running = captureSession({
    ...h.options,
    child,
    script,
    attachInterrupt: (fn) => { interrupt = fn; },
  });
  child.emit("working\r\n");
  interrupt("interrupt");
  const outcome = await running;

  assert.equal(outcome.ended, "interrupt");
  assert.deepEqual(child.written, [], "the step was sent after the operator stopped the capture");
  assert.deepEqual(outcome.timedOutSteps, [], "the driver waited out the step timeout anyway");
  assert.match(outcome.driverError.message, /session ended/);
  assert.ok(fs.existsSync(outcome.outFile), "an interrupted scripted capture lost the session");
  h.cleanup();
});

test("a wedged capture reports progress and says why it gave up (DEMO-CAP-05)", async () => {
  const h = harness({ progressMs: 1000, exitGraceMs: 10000, killGraceMs: 1000 });
  const child = fakeChild();
  const script = normalizeScript({
    steps: [{ mark: "quit", send: "/exit", expect: "NEVER PRINTED", idleMs: 0, timeoutMs: 4000 }],
  }, h.dir);

  const running = captureSession({ ...h.options, child, script });
  child.emit("working\r\n");
  const outcome = await running;

  assert.ok(h.progress.length >= 3, `a wedged capture printed no progress: ${h.progress.length}`);
  const line = h.progress[0];
  assert.match(line, /^capture: /);
  assert.match(line, /elapsed/);
  assert.match(line, /since the last output/);
  assert.match(line, /captured/);
  // The line names the step it is waiting on, so a stalled recipe is readable at a glance.
  assert.ok(
    h.progress.some((l) => /"quit"/.test(l) && /NEVER PRINTED/.test(l)),
    `no progress line named the step being waited on: ${JSON.stringify(h.progress)}`,
  );
  assert.ok(
    h.warnings.some((w) => /never exited/.test(w) && /grace/.test(w)),
    `the capture did not report the stall it gave up on: ${JSON.stringify(h.warnings)}`,
  );
  assert.equal(outcome.ended, "no-exit");
  h.cleanup();
});

test("a session that ends on its own is not killed or warned about (DEMO-CAP-03)", async () => {
  const h = harness();
  // The turn is typed, Enter follows as its own write, and the session ends - the happy path.
  const child = fakeChild({ exitAfterWrites: 2 });
  const script = normalizeScript({
    steps: [{ mark: "ask", send: "hello", expect: "READY", idleMs: 0, timeoutMs: 60000 }],
  }, h.dir);

  const running = captureSession({ ...h.options, child, script });
  child.emit("READY\r\n");
  const outcome = await running;

  assert.equal(outcome.ended, "exit");
  assert.equal(outcome.exitCode, 0);
  assert.equal(child.kills, 0, "a session that ended on its own was killed anyway");
  assert.deepEqual(outcome.timedOutSteps, []);
  assert.equal(h.warnings.length, 0, `a clean capture warned: ${JSON.stringify(h.warnings)}`);
  assert.ok(fs.existsSync(outcome.outFile));
  h.cleanup();
});
