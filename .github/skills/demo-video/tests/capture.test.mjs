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

import { captureSession, isQuitKey, handleCaptureInput, captureSummaryLines, captureExitCode } from "../tools/record_demo.mjs";
import { normalizeScript, stallNotice, formatDuration } from "../tools/script.mjs";
import { DEFAULT_RULES } from "../tools/redact.mjs";

const scratch = () => fs.mkdtempSync(path.join(os.tmpdir(), "demo-video-capture-"));

// Time is a counter the sleeper advances, so a two-minute grace costs a few microtasks. `setImmediate`
// rather than a resolved promise: the driver and the supervisor both wait on this, and a macrotask
// boundary lets each of them make progress between ticks the way a real timer would. The budget is
// what turns a regression into an ASSERTION: `node --test` has no default timeout, so a supervisor
// that stops finalizing would otherwise spin here until the CI job's own timeout kills it with no
// indication of which guarantee broke.
function fakeClock(start = 1000000, budgetMs = 24 * 60 * 60 * 1000) {
  let t = start;
  return {
    now: () => t,
    nap: (ms) => {
      t += Math.max(0, ms);
      if (t - start > budgetMs) {
        throw new Error(`the capture never finalized: ${t - start}ms of simulated time elapsed`);
      }
      return new Promise((done) => setImmediate(done));
    },
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
  // After the last turn there is no step to name, but "the operator is driving" would be a lie
  // during exactly the wedge this line exists to diagnose.
  assert.ok(
    h.progress.some((l) => /waiting for the session to exit/.test(l)),
    `no progress line covered the exit grace: ${JSON.stringify(h.progress)}`,
  );
  assert.ok(
    !h.progress.some((l) => /the operator is driving/.test(l)),
    `a scripted capture claimed the operator was driving: ${JSON.stringify(h.progress)}`,
  );
  assert.ok(
    h.warnings.some((w) => /never exited/.test(w) && /grace/.test(w)),
    `the capture did not report the stall it gave up on: ${JSON.stringify(h.warnings)}`,
  );
  // The measured silence travels with the outcome, so the CLOSING summary can repeat the same
  // number instead of claiming the session had been quiet for 0s.
  assert.ok(outcome.quietMs > 0, "the capture did not record how long the session had been silent");
  assert.match(
    stallNotice({ ended: outcome.ended, quietMs: outcome.quietMs, graceMs: 10000 }),
    /printed nothing for \d+/,
  );
  assert.equal(outcome.ended, "no-exit");
  h.cleanup();
});

test("Ctrl+backslash is the escape hatch a raw-mode terminal leaves (DEMO-CAP-04)", () => {
  // In raw mode Ctrl+C is a BYTE the session receives - deliberately, since the operator has to be
  // able to cancel a turn inside the TUI being filmed - so it can never end a wedged interactive
  // capture. Ctrl+\ is what does, and nothing in these sessions types it.
  assert.equal(isQuitKey(Buffer.from([0x1c])), true);
  assert.equal(isQuitKey(Buffer.from("hello\u001cworld", "utf8")), true);
  assert.equal(isQuitKey("\u001c"), true);
  assert.equal(isQuitKey(Buffer.from([0x03])), false, "Ctrl+C must still reach the session");
  assert.equal(isQuitKey(Buffer.from("/exit\r", "utf8")), false);
  assert.equal(isQuitKey(null), false);

  // And the key is really WIRED to the interrupt, not merely recognised: dropping that wire is what
  // would quietly leave an interactive capture with no way out again.
  const wire = (data, isTTY) => {
    const seen = { quit: 0, written: [] };
    const action = handleCaptureInput(data, {
      isTTY,
      onQuit: () => { seen.quit += 1; },
      write: (text) => seen.written.push(text),
    });
    return { action, ...seen };
  };
  assert.deepEqual(wire(Buffer.from([0x1c]), true), { action: "quit", quit: 1, written: [] });
  assert.deepEqual(wire(Buffer.from([0x03]), true), { action: "forwarded", quit: 0, written: ["\u0003"] });
  // Off a terminal there is no raw mode, so nothing is intercepted and the byte is the session's.
  assert.deepEqual(wire(Buffer.from([0x1c]), false), { action: "forwarded", quit: 0, written: ["\u001c"] });
});

test("the closing summary repeats what the supervisor measured (DEMO-CAP-05)", () => {
  // The summary is the last thing an operator reads, so it must not contradict the warning printed
  // an hour earlier: it claimed the session had "printed nothing for 0s" because the measured quiet
  // never travelled out of the supervisor.
  const outcome = {
    outFile: "C:\\tmp\\probe.cast.json",
    transcriptFile: "C:\\tmp\\probe.transcript.txt",
    redactions: 2,
    timedOutSteps: [{ mark: "quit", reason: "timed out after 60000ms" }],
    overflowed: false,
    driverError: null,
    ended: "no-exit",
    quietMs: 3960000,
    exitCode: null,
    leftover: [],
  };
  const text = captureSummaryLines(outcome, { maxMb: 48, exitGraceMs: 120000 }).map((l) => l.text).join("\n");
  assert.match(text, new RegExp(`printed nothing for ${formatDuration(outcome.quietMs)}`));
  assert.match(text, /step "quit" timed out after 60000ms/);
  assert.match(text, /probe\.cast\.json/);
  assert.match(text, /probe\.transcript\.txt/);
  assert.match(text, /2 match\(es\) scrubbed/);
  assert.match(text, /READ THE TRANSCRIPT/);

  const cut = captureSummaryLines({ ...outcome, ended: "overflow", overflowed: true, timedOutSteps: [] });
  assert.match(cut.map((l) => l.text).join("\n"), /cut short at the 48MB capture limit/);

  // An ending that was not the session's own is a failed capture, whatever landed on disk.
  assert.equal(captureExitCode({ ended: "exit", exitCode: 0 }), 0);
  assert.equal(captureExitCode({ ended: "exit", exitCode: 3 }), 3);
  assert.equal(captureExitCode({ ended: "interrupt" }), 130);
  assert.equal(captureExitCode({ ended: "no-exit", exitCode: 0 }), 1);
  assert.equal(captureExitCode({ ended: "overflow", overflowed: true }), 1);
  assert.equal(captureExitCode({ ended: "exit", exitCode: 0, driverError: new Error("x") }), 1);
});

test("a size-limit kill the session ignores still finalizes (DEMO-CAP-01)", async () => {
  // The guard ends the session at the limit, but ENDING IT was all it used to do: a child that
  // ignores the kill would then sit in the supervisor's "still running" state forever, holding the
  // very recording the limit exists to save.
  const h = harness({ killGraceMs: 1000 });
  const child = fakeChild();
  const running = captureSession({ ...h.options, child, maxBytes: 8 });
  child.emit("far more than eight bytes of output\r\n");
  const outcome = await running;

  assert.equal(outcome.overflowed, true, "the size guard never fired");
  assert.equal(outcome.ended, "overflow", "an overflowed capture reported a clean ending");
  assert.equal(child.kills, 1, "the session was ended more than once");
  assert.ok(fs.existsSync(outcome.outFile), "the overflowed capture lost the session");
  const cast = JSON.parse(fs.readFileSync(outcome.outFile, "utf8"));
  assert.match(cast.events.map((e) => e.data).join(""), /eight bytes/);
  h.cleanup();

  // And the ending is reported the same way when the child DOES die on the kill, which is the
  // ordinary case: keying the ending off "the child exited" alone reported a forced ending as a
  // clean one, on the path production actually takes.
  const obedient = harness({ killGraceMs: 1000 });
  const dies = fakeChild({ diesOnKill: true });
  const secondRun = captureSession({ ...obedient.options, child: dies, maxBytes: 8 });
  dies.emit("far more than eight bytes of output\r\n");
  const second = await secondRun;
  assert.equal(second.ended, "overflow", "an obedient child made an overflow look like a clean exit");
  assert.equal(second.overflowed, true);
  assert.ok(fs.existsSync(second.outFile));
  obedient.cleanup();
});

test("an overflow does not consume the operator's one interrupt (DEMO-CAP-04)", async () => {
  // The size limit and the operator's interrupt are different endings. Sharing one latch meant that
  // after an overflow the operator's FIRST Ctrl+C counted as their second - the "I will not wait for
  // the write" case - and the session was thrown away, which is the loss this all exists to prevent.
  const h = harness({ killGraceMs: 1000 });
  const child = fakeChild();
  let interrupt = null;
  const running = captureSession({
    ...h.options,
    child,
    maxBytes: 8,
    attachInterrupt: (fn) => { interrupt = fn; },
  });
  child.emit("far more than eight bytes\r\n");
  assert.equal(interrupt("interrupt"), true, "the overflow swallowed the operator's first interrupt");
  assert.equal(interrupt("interrupt"), false, "a second interrupt was treated as the first");
  const outcome = await running;

  // The ending stays the one that actually stopped the session.
  assert.equal(outcome.ended, "overflow");
  assert.ok(fs.existsSync(outcome.outFile), "the interrupt after an overflow lost the session");
  h.cleanup();
});

test("an interrupt does not wait out a step's own sleep (DEMO-CAP-04)", async () => {
  // A step may legitimately ask for a long delay before it types. Waiting that out after the
  // operator asked to stop would rebuild the hang this whole change exists to remove.
  const h = harness();
  const child = fakeChild();
  const startedAt = h.clock.now();
  const script = normalizeScript({
    steps: [{ mark: "ask", send: "hello", idleMs: 0, timeoutMs: 60000, delayMs: 3600000 }],
  }, h.dir);
  let interrupt = null;
  const running = captureSession({
    ...h.options,
    child,
    script,
    attachInterrupt: (fn) => { interrupt = fn; },
  });
  child.emit("ready\r\n");
  interrupt("interrupt");
  const outcome = await running;

  assert.equal(outcome.ended, "interrupt");
  assert.ok(
    h.clock.now() - startedAt < 60000,
    `the capture waited out the step's hour-long delay: ${h.clock.now() - startedAt}ms`,
  );
  assert.deepEqual(child.written, [], "the step typed after the operator stopped the capture");
  assert.ok(fs.existsSync(outcome.outFile));
  h.cleanup();
});

test("a script that cannot continue ends the session on the kill grace, not the exit grace (DEMO-CAP-03)", async () => {
  // The driver kills the session when a step can no longer be satisfied, but the supervisor used to
  // know nothing about that kill and would sit out the whole exit grace waiting for a child it had
  // already killed - two minutes of nothing, on the path that is already going badly.
  const h = harness({ exitGraceMs: 120000, killGraceMs: 1000 });
  const child = fakeChild();
  const startedAt = h.clock.now();
  const script = normalizeScript({
    steps: [{ mark: "paste", sendFile: "never-written.md", idleMs: 0, timeoutMs: 1000 }],
  }, h.dir);

  const running = captureSession({ ...h.options, child, script });
  child.emit("ready\r\n");
  const outcome = await running;

  assert.match(outcome.driverError.message, /never appeared/);
  assert.equal(outcome.ended, "driver-error");
  assert.ok(
    h.clock.now() - startedAt < 60000,
    `a failed script sat out the exit grace: ${h.clock.now() - startedAt}ms`,
  );
  assert.ok(fs.existsSync(outcome.outFile), "a failed script lost the partial session");
  h.cleanup();

  // Same when the child obeys the kill: the ending is what FORCED it, not "the child exited".
  const obedient = harness({ killGraceMs: 1000 });
  const dies = fakeChild({ diesOnKill: true });
  const run2 = captureSession({
    ...obedient.options,
    child: dies,
    script: normalizeScript({
      steps: [{ mark: "paste", sendFile: "never-written.md", idleMs: 0, timeoutMs: 1000 }],
    }, obedient.dir),
  });
  dies.emit("ready\r\n");
  const second = await run2;
  assert.equal(second.ended, "driver-error", "an obedient child made a failed script look clean");
  obedient.cleanup();
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
