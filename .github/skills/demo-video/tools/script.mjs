// Scripted input for `capture`.
//
// A capture normally forwards the operator's own keystrokes, which is fine for filming a single
// prompt but cannot produce the clip this skill exists to show: the LOOP, where an agent generates a
// commentable report, a human reviews it in the browser, and the review is pasted back into the SAME
// session. That is a two-turn session with a long gap in the middle, and a demo has to be
// re-recordable on demand rather than re-typed by hand, so the turns are declared in a file.
//
// The waiting rules are deliberately pure functions of (buffer, clock): the driver in record_demo.mjs
// owns the pty and the timers, and everything that decides WHEN to send is testable without one.

import fs from "node:fs";
import path from "node:path";

export const DEFAULT_TIMEOUT_MS = 900000;
export const DEFAULT_IDLE_MS = 4000;

function fail(message) {
  throw new Error(`capture script: ${message}`);
}

// A step's text can be inline or come from a file, because the interesting one - a Copy-all review
// bundle - is far too big to sit legibly in a JSON string. A file is resolved now but READ at send
// time: in the loop capture the bundle does not exist yet when the script is parsed, because it is
// produced by the browser phase that runs while the session waits.
function stepSource(step, baseDir, index) {
  const hasSend = typeof step.send === "string";
  const hasFile = typeof step.sendFile === "string";
  if (hasSend && hasFile) fail(`step ${index} has both send and sendFile; pick one`);
  if (!hasSend && !hasFile) fail(`step ${index} has neither send nor sendFile`);
  if (hasSend) return { text: step.send, file: null };
  return { text: null, file: path.resolve(baseDir, step.sendFile) };
}


export function normalizeScript(raw, baseDir = process.cwd()) {
  if (!raw || typeof raw !== "object") fail("the script must be a JSON object");
  const steps = Array.isArray(raw.steps) ? raw.steps : null;
  if (!steps) fail("the script needs a steps array");
  if (!steps.length) fail("the script has no steps");
  const seen = new Set();
  const normalized = steps.map((step, i) => {
    if (!step || typeof step !== "object") fail(`step ${i} is not an object`);
    const mark = typeof step.mark === "string" && step.mark.trim() ? step.mark.trim() : null;
    if (!mark) fail(`step ${i} needs a mark; the mark is how a render finds this turn in the cast`);
    if (seen.has(mark)) fail(`duplicate mark "${mark}"; marks name split points and must be unique`);
    seen.add(mark);
    const expect = step.expect == null ? null : String(step.expect);
    if (expect !== null && !expect.length) fail(`step ${i} has an empty expect`);
    // Waiting for a FILE is what lets one session span the browser phase: the capture sits on the
    // prompt until the review bundle the montage produces appears on disk, then pastes it.
    const expectFile = step.expectFile == null ? null : path.resolve(baseDir, String(step.expectFile));
    const num = (name, dflt) => {
      if (step[name] == null) return dflt;
      const value = Number(step[name]);
      if (!Number.isFinite(value) || value < 0) fail(`step ${i} ${name} must be a non-negative number`);
      return value;
    };
    const source = stepSource(step, baseDir, i);
    return {
      mark,
      expect,
      expectFile,
      idleMs: num("idleMs", expect || expectFile ? 0 : DEFAULT_IDLE_MS),
      timeoutMs: num("timeoutMs", DEFAULT_TIMEOUT_MS),
      delayMs: num("delayMs", 0),
      // A terminal turn is only submitted when Enter arrives, and forgetting it is the difference
      // between a captured session and one sitting on a full prompt line forever. Default it on,
      // since every real turn wants it, and let a step that is only typing opt out.
      enter: step.enter === false ? false : true,
      // A multi-line paste into a TUI is only ONE turn if it arrives as a bracketed paste. Sent
      // raw, every newline in a review bundle submits its own turn - a hundred junk turns instead
      // of the paste the clip is meant to show - so a step can ask for the real thing.
      paste: step.paste === true,
      // A one-time prompt (the folder-trust dialog) appears on the first run and never again, so a
      // step that waits for it must be able to give up and SKIP rather than send its keystroke into
      // whatever is on screen instead. Without this the script only works on a fresh machine, which
      // is the opposite of re-recordable.
      optional: step.optional === true,
      // How long to wait between typing and pressing Enter. See stepSubmit.
      submitMs: num("submitMs", 450),
      text: source.text,
      file: source.file,
    };
  });
  return { steps: normalized };
}

export function readScript(file) {
  const resolved = path.resolve(file);
  if (!fs.existsSync(resolved)) fail(`file not found: ${resolved}`);
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(resolved, "utf8"));
  } catch (e) {
    fail(`${resolved} is not valid JSON: ${e.message}`);
  }
  return normalizeScript(raw, path.dirname(resolved));
}

// Waiting on an IDLE window alone is fragile against an agent that pauses mid-thought, and waiting
// on a marker alone hangs forever if the marker never prints. A step can ask for either or both, and
// the timeout is always the backstop - it reports rather than throws, so a capture that ran long
// still yields the session it did record instead of losing it.
export function stepReady(step, { buffer = "", lastDataAt = 0, now = 0, startedAt = 0, fileExists = false } = {}) {
  if (now - startedAt >= step.timeoutMs) {
    return {
      ready: !step.optional,
      skip: step.optional,
      timedOut: true,
      reason: `timed out after ${step.timeoutMs}ms`,
    };
  }
  if (step.expectFile && !fileExists) {
    return { ready: false, reason: `waiting for ${step.expectFile}` };
  }
  if (step.expect && !buffer.includes(step.expect)) {
    return { ready: false, reason: `waiting for ${JSON.stringify(step.expect)}` };
  }
  if (step.idleMs > 0 && now - lastDataAt < step.idleMs) {
    return { ready: false, reason: `waiting for ${step.idleMs}ms of quiet` };
  }
  return { ready: true, timedOut: false, reason: "ready" };
}

// What actually goes down the pipe. Kept separate from the sending so a test can assert the Enter
// policy without a pty, and so a bracketed-paste terminal cannot swallow the newline: the text and
// the Enter are written as one string in the order a person would produce them. A file-backed step
// is read HERE, not at parse time, because its file may not exist until the moment it is needed.
export function stepPayload(step) {
  let text = step.text;
  if (text == null) {
    if (!fs.existsSync(step.file)) fail(`step "${step.mark}" sendFile never appeared: ${step.file}`);
    text = fs.readFileSync(step.file, "utf8");
  }
  // Normalize to bare newlines first: a CRLF inside a bracketed paste submits on the CR in some
  // readline implementations, which is the very thing bracketing is meant to prevent.
  if (step.paste) text = `\u001b[200~${text.replace(/\r\n?/g, "\n")}\u001b[201~`;
  return text;
}

// Enter is written SEPARATELY, after a pause. A TUI composer that receives a long string and a
// trailing carriage return in one burst treats the return as part of the text being typed - the
// prompt lands in the composer and simply sits there, which is exactly how a fifteen minute capture
// produced no session at all. A human types, stops, then presses Enter; so does this.
export function stepSubmit(step) {
  return step.enter ? "\r" : "";
}
