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
// How long a SCRIPTED capture waits for the session to end itself once the last turn has been sent,
// before it stops waiting on the child and finalizes anyway. Two minutes is generous for a TUI
// shutting down and trivial next to the ninety minutes a capture can cost.
export const DEFAULT_EXIT_GRACE_MS = 120000;
// And how long the kill it then sends is given to land before the capture stops waiting for the
// child at all. A pty child that ignores a kill must not be able to hold the recording hostage.
export const DEFAULT_KILL_GRACE_MS = 5000;
// How often a running capture says where it is. A wedge is otherwise indistinguishable from a slow
// agent, and the only way to tell them apart was watching a log file's mtime by eye.
export const DEFAULT_PROGRESS_MS = 60000;

// Every key a step is allowed to carry. Unknown keys are REFUSED rather than ignored, because the
// failure they cause is silent and expensive: `expects` for `expect`, or `submitMS` for `submitMs`,
// parses clean and then degrades the step to a bare idle wait - which is exactly the gate that ends
// a ninety-minute capture early. A typo should cost a second at parse time, not the whole session.
const STEP_KEYS = new Set([
  "mark", "expect", "expectFile", "idleMs", "timeoutMs", "delayMs",
  "enter", "paste", "optional", "submitMs", "send", "sendFile",
]);

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
    for (const key of Object.keys(step)) {
      if (!STEP_KEYS.has(key)) fail(`step ${i} has unknown key "${key}"`);
    }
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
  // A marker the recipe TYPED cannot mean "the agent produced it". The TUI paints the submitted turn
  // back into the transcript, so an `expect` that appears in an earlier `send` is satisfied by the
  // echo within seconds - silently demoting the step to a bare idle wait, which is the only thing
  // then standing between a ninety-minute capture and an early `/exit`. Measured on a real 65 minute
  // multi-duck session: the stream fell quiet for 5 to 6 seconds 73 times while the agent was
  // working, against an idle gate of 6s. That capture survived by under a second, 73 times over.
  // Refuse it at parse time - the recipe is wrong, and finding out at minute 20 costs the session.
  for (let i = 0; i < normalized.length; i++) {
    const expect = normalized[i].expect;
    if (!expect) continue;
    for (let j = 0; j < i; j++) {
      const earlier = normalized[j].text;
      if (earlier && earlier.includes(expect)) {
        fail(`step ${i} ("${normalized[i].mark}") waits for ${JSON.stringify(expect)}, but step ${j} `
          + `("${normalized[j].mark}") sends it - the terminal echoes the prompt, so the wait would be `
          + `satisfied by the recipe's own text. Wait for something only the agent can produce, or `
          + `drop expect and raise idleMs.`);
      }
    }
  }
  return { steps: normalized };
}

// A step that gave up is reported TWICE on purpose: once where it happens, and once in the closing
// summary. A capture runs for up to ninety minutes, so a warning printed at minute twenty has
// scrolled far out of sight by the end - and the shipped loop recipe really did spend its whole
// twenty-five minute timeout waiting for a marker the agent never printed, while the closing lines
// still read like a clean take. Deciding to re-run is much cheaper than publishing the wrong ending.
export function stepGaveUpNotice(step) {
  return `step "${step.mark}" ${step.reason} - the session never produced what it was waiting for, `
    + "so this cast may not show the ending the recipe asked for.";
}

// A file-backed wait must mean "the file this run produced", not "a file exists". The loop capture
// waits on a review bundle at a FIXED path in the scratch directory, so a bundle left by the
// previous recording is already there when the step starts - and an existence check would paste the
// STALE review into a session that has not finished the new report, producing a clip that is
// coherently wrong rather than obviously broken. Freshness is the whole guarantee.
export function fileReady(file, startedAt, stat = fs.statSync) {
  if (!file) return false;
  let info;
  try {
    info = stat(file);
  } catch {
    return false;
  }
  return info.mtimeMs >= startedAt;
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
  // Readiness is checked BEFORE the deadline. A condition that arrived just before the timeout but
  // is only observed on the next poll would otherwise be reported as a timeout - and for an
  // optional step that means skipping a dialog that is actually on screen.
  const waiting = (step.expectFile && !fileExists)
    ? `waiting for ${step.expectFile}`
    : (step.expect && !buffer.includes(step.expect))
      ? `waiting for ${JSON.stringify(step.expect)}`
      : (step.idleMs > 0 && now - lastDataAt < step.idleMs)
        ? `waiting for ${step.idleMs}ms of quiet`
        : null;
  if (!waiting) return { ready: true, timedOut: false, reason: "ready" };
  if (now - startedAt >= step.timeoutMs) {
    return {
      ready: !step.optional,
      skip: step.optional,
      timedOut: true,
      reason: `timed out after ${step.timeoutMs}ms`,
    };
  }
  return { ready: false, reason: waiting };
}

// Everything a capture records is held in memory until the child exits, because the raw stream is
// never written to disk unscrubbed - so memory is the binding constraint, and running out of it
// loses a recording that took twenty minutes to make. This bounds it: the guard fires ONCE, at the
// moment the limit is crossed, so the caller can end the session cleanly and keep what it has
// instead of dying with nothing.
export function makeSizeGuard(maxBytes, onOverflow) {
  if (!Number.isFinite(maxBytes) || maxBytes <= 0) fail("the capture size limit must be a positive number of bytes");
  let total = 0;
  let fired = false;
  return (length) => {
    total += length;
    if (fired || total <= maxBytes) return fired;
    fired = true;
    onOverflow(total);
    return true;
  };
}

export function captureLimitBytes(mb) {
  const value = Number(mb);
  if (!Number.isFinite(value) || value <= 0) fail(`--max-mb must be a positive number, got ${JSON.stringify(mb)}`);
  return Math.round(value * 1024 * 1024);
}

// What actually goes down the pipe. Kept separate from the sending so a test can assert the Enter
// policy without a pty, and so a bracketed-paste terminal cannot swallow the newline: the text and
// the Enter are written as one string in the order a person would produce them. A file-backed step
// is read HERE, not at parse time, because its file may not exist until the moment it is needed.
export const MAX_SEND_BYTES = 1024 * 1024;

// Bracketed paste has NO escaping mechanism: the terminal ends the paste at the first `ESC[201~` it
// sees. Text that contains one - and the pasted text here is a review bundle quoting a document
// somebody else may have written - would end the paste early and have the remainder interpreted as
// live keystrokes, which in a Copilot session means submitting whatever followed as a command. So
// every escape and control byte is stripped before the delimiters go on. Fail closed: this is a
// protocol that cannot express "a literal ESC", so a literal ESC must not be sent.
export function sanitizePasteText(text) {
  return String(text)
    // eslint-disable-next-line no-control-regex
    .replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, "")
    // eslint-disable-next-line no-control-regex
    .replace(/\u001b[\]P^_][\s\S]*?(?:\u0007|\u001b\\)/g, "")
    // C0 AND C1. U+009B is an 8-bit CSI: a C1-aware parser reads `\u009b201~` as the paste
    // terminator just as it reads `ESC[201~`, so stripping only C0 left the injection open.
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/g, "")
    .replace(/\r\n?/g, "\n");
}

export function stepPayload(step) {
  let text = step.text;
  if (text == null) {
    let stat;
    try { stat = fs.statSync(step.file); } catch (e) { stat = null; }
    if (!stat) fail(`step "${step.mark}" sendFile never appeared: ${step.file}`);
    // A bundle is generated, so its size is not a promise. Refuse an implausible one rather than
    // pulling it into memory (twice, after normalization) and leaving a pty running behind it.
    if (stat.size > MAX_SEND_BYTES) {
      fail(`step "${step.mark}" sendFile is ${stat.size} bytes, over the ${MAX_SEND_BYTES} limit: ${step.file}`);
    }
    text = fs.readFileSync(step.file, "utf8");
  }
  if (step.paste) text = `\u001b[200~${sanitizePasteText(text)}\u001b[201~`;
  return text;
}

// Enter is written SEPARATELY, after a pause. A TUI composer that receives a long string and a
// trailing carriage return in one burst treats the return as part of the text being typed - the
// prompt lands in the composer and simply sits there, which is exactly how a fifteen minute capture
// produced no session at all. A human types, stops, then presses Enter; so does this.
export function stepSubmit(step) {
  return step.enter ? "\r" : "";
}

// WHEN A CAPTURE ENDS IS DECIDED BY THE WALL CLOCK, NEVER BY THE STREAM.
//
// The stream is not a dependable signal against a TUI: it repaints, it goes quiet mid-thought, and
// after `/exit` it can simply stop while the child stays alive. A capture that only waited on
// `child.onExit` therefore had no bound at all - one sat for seventeen hours holding a ninety minute
// session in memory and never wrote a byte, because the cast is only produced at finalization.
//
// So the supervisor polls this instead. `driverDoneAt` is set once the script has sent its last turn
// (an UNSCRIPTED capture never sets it - the operator is sitting there, and an interactive session
// must not be killed for being quiet). `interruptedAt` is set by a signal, which kills at once
// because the operator already decided to stop. Either way the kill gets `killGraceMs` to land, and
// then the capture finalizes whether the child is gone or not.
export function sessionEndState({
  now,
  driverDoneAt = null,
  interruptedAt = null,
  killedAt = null,
  exitGraceMs = DEFAULT_EXIT_GRACE_MS,
  killGraceMs = DEFAULT_KILL_GRACE_MS,
} = {}) {
  const stage = (since, graceMs, reason) => {
    if (killedAt === null) {
      return now - since >= graceMs ? { action: "kill", reason } : { action: "wait", reason };
    }
    return now - killedAt >= killGraceMs ? { action: "finalize", reason } : { action: "wait", reason };
  };
  if (interruptedAt !== null) return stage(interruptedAt, 0, "interrupt");
  if (driverDoneAt !== null) return stage(driverDoneAt, exitGraceMs, "no-exit");
  return { action: "wait", reason: "running" };
}

export function formatDuration(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours}h${String(minutes).padStart(2, "0")}m`;
  if (minutes) return `${minutes}m${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

export function formatBytes(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)}MB`;
  if (value >= 1024) return `${Math.round(value / 1024)}KB`;
  return `${Math.round(value)}B`;
}

// A wedged capture has to be detectable WITHOUT reading the log by eye. The only symptom was a log
// file whose last write stopped advancing, which nobody notices for an hour, so the capture says
// where it is on its own clock: how long it has run, how long the session has been silent, how much
// it is holding, and what it is waiting for.
export function progressLine({ now, startedAt, lastDataAt, bytes = 0, waiting = null }) {
  return [
    `capture: ${formatDuration(now - startedAt)} elapsed`,
    `${formatDuration(now - lastDataAt)} since the last output`,
    `${formatBytes(bytes)} captured`,
    waiting || "no script; the operator is driving",
  ].join(", ");
}

// What the capture says when it stops waiting. Both endings mean the same thing for the cast - it is
// whatever had been recorded, not the ending the recipe asked for - so both say so plainly rather
// than letting a closing summary read like a clean take.
export function stallNotice({ ended, quietMs = 0, graceMs = DEFAULT_EXIT_GRACE_MS }) {
  if (ended === "interrupt") {
    return "the capture was interrupted; the cast holds what had been recorded, so it may not show "
      + "the ending the recipe asked for.";
  }
  return `the session printed nothing for ${formatDuration(quietMs)} and never exited; ending it `
    + `after the ${formatDuration(graceMs)} exit grace and keeping what was recorded, so this cast `
    + "may not show the ending the recipe asked for.";
}

