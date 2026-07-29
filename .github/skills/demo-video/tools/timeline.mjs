// Pure scheduling core for the demo recorder. Deliberately free of playwright, node-pty and the DOM,
// so the part that decides HOW LONG anything is on screen can be tested without a browser or a PTY.

export const MIN_BEAT_MS = 350;

// Largest-remainder apportionment: floor every share, then hand the leftover milliseconds to the
// beats with the biggest fractional part. Plain rounding would let the total drift off the budget.
function apportion(weights, total) {
  const sum = weights.reduce((a, b) => a + b, 0);
  const raw = weights.map((w) => (w / sum) * total);
  const base = raw.map((v) => Math.floor(v));
  const order = raw
    .map((v, i) => ({ i, frac: v - Math.floor(v) }))
    .sort((a, b) => b.frac - a.frac || a.i - b.i);
  let rest = total - base.reduce((a, b) => a + b, 0);
  for (let k = 0; rest > 0; k++) {
    base[order[k % order.length].i] += 1;
    rest -= 1;
  }
  return base;
}

// Split `totalMs` across the beats in proportion to their weight, with a floor so no beat is on
// screen too briefly to read. A beat that lands under the floor is pinned there and the remaining
// time is re-shared among the rest, which keeps the total EXACTLY on budget: a montage is cut to a
// fixed length, so a few stray milliseconds per beat would accumulate into a visibly wrong clip.
export function planBeats(beats, totalMs, opts = {}) {
  const minMs = opts.minMs == null ? MIN_BEAT_MS : opts.minMs;
  if (!Array.isArray(beats) || beats.length === 0) {
    throw new Error("planBeats needs at least one beat");
  }
  // A fractional floor smuggles a fraction into the plan through the back door: the pinned beat
  // keeps it and the budgets no longer sum to the request.
  if (!Number.isInteger(minMs) || minMs <= 0) {
    throw new Error(`planBeats needs a positive floor in whole milliseconds, got ${minMs}`);
  }
  if (!Number.isFinite(totalMs) || totalMs <= 0) {
    throw new Error("planBeats needs a positive duration in milliseconds");
  }
  // The whole point of the apportionment is that the budgets sum EXACTLY to the request, and whole
  // milliseconds cannot sum to a fractional total - so refuse it rather than quietly missing by half.
  if (!Number.isInteger(totalMs)) {
    throw new Error(`planBeats needs whole milliseconds, got ${totalMs}`);
  }
  if (minMs * beats.length > totalMs) {
    throw new Error(
      `duration ${totalMs}ms is too short for ${beats.length} beats at the ${minMs}ms minimum`,
    );
  }
  // A non-finite weight is the dangerous one: Infinity/Infinity is NaN, which would spread silently
  // through every budget and every sleep derived from it. Treat it like a missing weight.
  const weights = beats.map((b) => {
    const weight = Number(b.weight);
    return Number.isFinite(weight) && weight > 0 ? weight : 1;
  });
  const alloc = new Array(beats.length).fill(0);
  const pinned = new Array(beats.length).fill(false);
  for (;;) {
    const free = beats.map((_, i) => i).filter((i) => !pinned[i]);
    const spent = alloc.reduce((a, v, i) => (pinned[i] ? a + v : a), 0);
    if (free.length === 0) {
      alloc[0] += totalMs - spent;
      break;
    }
    const shares = apportion(free.map((i) => weights[i]), totalMs - spent);
    free.forEach((i, k) => { alloc[i] = shares[k]; });
    const short = free.filter((i) => alloc[i] < minMs);
    if (short.length === 0) break;
    for (const i of short) {
      alloc[i] = minMs;
      pinned[i] = true;
    }
  }
  return beats.map((b, i) => ({
    id: b.id,
    label: b.label,
    abilities: b.abilities || [],
    budgetMs: alloc[i],
  }));
}

export const DEFAULT_IDLE_MS = 900;export const DEFAULT_HOLD_MS = 320;
// A fast-forward is a beat, not a scene: past about a second and a half the badge stops reading as
// "time passed" and starts reading as "the clip froze". The floor is the other end of that - below
// roughly a tenth of a second the badge is gone before a viewer can register it.
export const MAX_HOLD_MS = 1500;
export const MIN_HOLD_MS = 80;

// Collapse the dead air out of a captured terminal timeline.
//
// A real Copilot CLI session spends most of its wall clock waiting - on a model, on a test run, on a
// duck panel - and replaying that verbatim is unwatchable. Any gap longer than `idleMs` replays as a
// short `holdMs` beat flagged `fastForward`, so the viewer sees that time passed (the renderer puts a
// badge up) without sitting through it. Gaps under the threshold are the natural rhythm of output and
// are left EXACTLY alone, so streaming and typing still look real.
//
// Events are re-timed, never dropped or reordered: the output a session produced is the output the
// clip shows.
export function compressTimeline(events, opts = {}) {
  const idleMs = opts.idleMs == null ? DEFAULT_IDLE_MS : opts.idleMs;
  const holdMs = opts.holdMs == null ? DEFAULT_HOLD_MS : opts.holdMs;
  if (!Array.isArray(events)) throw new Error("compressTimeline needs an array of events");
  if (!Number.isFinite(idleMs) || idleMs <= 0) throw new Error("idleMs must be a positive number");
  if (!Number.isFinite(holdMs) || holdMs < 0) throw new Error("holdMs must not be negative");
  if (holdMs > idleMs) throw new Error("holdMs must not exceed idleMs, or a gap would grow");

  let previous = 0;
  let clock = 0;
  let skippedMs = 0;
  const out = [];
  for (const event of events) {
    const at = Number(event.t);
    if (!Number.isFinite(at) || at < previous) {
      throw new Error("compressTimeline needs monotonic, finite timestamps");
    }
    const gap = at - previous;
    const fastForward = gap > idleMs;
    const skipped = fastForward ? Math.round(gap - holdMs) : 0;
    if (fastForward) skippedMs += skipped;
    clock += fastForward ? holdMs : gap;
    out.push({
      t: Math.round(clock),
      // The ORIGINAL timestamp travels with the event, so a later pass can tell which part of the
      // session an event belongs to (the closing summary, say) without re-deriving it.
      sourceT: at,
      data: event.data,
      fastForward,
      skippedMs: skipped,
    });
    previous = at;
  }
  return {
    events: out,
    durationMs: Math.round(clock),
    sourceDurationMs: Math.round(previous),
    // Summed from the ROUNDED per-event values, so the total the render summary prints is the sum
    // of the parts rather than a separately-rounded figure that disagrees with them.
    skippedMs,
    fastForwards: out.filter((e) => e.fastForward).length,
  };
}

// Pick the idle threshold that brings a captured session closest to a target clip length without
// disturbing the sub-threshold rhythm, so a 40 minute session and a 3 minute one both land near the
// length that was asked for. A session already shorter than the target is never stretched.
//
// Idle thresholds are DISCRETE, so with only a couple of long waits no threshold lands near the
// target (a 30 second session with two pauses collapses to 4 seconds however it is sliced). Once the
// threshold is chosen, the HOLD is solved for the remaining budget - capped, so a fast-forward stays
// a beat rather than becoming a stare - which spends the requested length instead of wasting it.
// Pick the idle threshold AND the hold that bring a captured session closest to a target clip
// length, without disturbing the sub-threshold rhythm.
//
// Two things make this less obvious than it looks. Idle thresholds are DISCRETE, so with only a
// couple of long waits no threshold lands near the target - the HOLD has to be solved for the
// remainder. And "do not compress at all" is a legitimate candidate at EVERY target, not just when
// the session already fits: a 700 second session asked for 690 seconds was coming back as a 1.5
// second clip, missing by 688 seconds where leaving it alone missed by 10.
//
// The hold moves in BOTH directions within [MIN_HOLD_MS, maxHoldMs]. Only letting it grow meant a
// session with many gaps could not be brought DOWN to the target - 84 fast-forwards at the default
// hold is 27 seconds of holds alone, so a 35 second request produced 63 seconds. A hold the caller
// passed explicitly is an instruction, not a hint, and is honoured exactly (`pinHold`).

// Re-time a WINDOW of the finished clip. Fitting gives a whole clip one budget, but a review note is
// almost always local - "the stretch around twenty seconds drags" - and the only honest answer is to
// speed up exactly that stretch rather than re-fit everything and disturb the parts that were right.
// Windows are given in CLIP time, because that is what the person watching it can point at. Events
// after a window shift earlier by the time it saved, so nothing is dropped or reordered.
export function applySpeedWindows(events, windows) {
  if (!Array.isArray(windows) || !windows.length) return events;
  const sorted = [...windows]
    .map((w) => ({ fromMs: Number(w.fromMs), toMs: Number(w.toMs), factor: Number(w.factor) }))
    .sort((a, b) => a.fromMs - b.fromMs);
  for (const w of sorted) {
    if (!Number.isFinite(w.fromMs) || !Number.isFinite(w.toMs) || !Number.isFinite(w.factor)) {
      throw new Error("a speed window needs finite from, to and factor values");
    }
    if (w.toMs <= w.fromMs) throw new Error(`speed window ${w.fromMs}-${w.toMs} does not move forward`);
    if (w.factor <= 0) throw new Error("a speed window factor must be positive");
  }
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i].fromMs < sorted[i - 1].toMs) throw new Error("speed windows must not overlap");
  }
  // How much time is removed before a given original moment.
  const savedBefore = (t) => {
    let saved = 0;
    for (const w of sorted) {
      if (t <= w.fromMs) break;
      const end = Math.min(t, w.toMs);
      saved += (end - w.fromMs) * (1 - 1 / w.factor);
    }
    return saved;
  };
  return events.map((e) => ({ ...e, t: Math.max(0, Math.round(e.t - savedBefore(e.t))) }));
}

// `20:27:2` - speed the clip between 20s and 27s up by two. Several windows are comma separated.
export function parseSpeedWindows(spec) {
  if (!spec) return [];
  return String(spec).split(",").map((part) => {
    const bits = part.trim().split(":");
    if (bits.length !== 3) throw new Error(`a speed window looks like from:to:factor, not "${part.trim()}"`);
    const [fromS, toS, factor] = bits.map(Number);
    if (![fromS, toS, factor].every(Number.isFinite)) {
      throw new Error(`a speed window needs three numbers, not "${part.trim()}"`);
    }
    return { fromMs: Math.round(fromS * 1000), toMs: Math.round(toS * 1000), factor };
  });
}

export function fitTimeline(events, targetMs, opts = {}) {
  if (!Number.isFinite(targetMs) || targetMs <= 0) throw new Error("targetMs must be positive");
  const preferredHold = opts.holdMs == null ? DEFAULT_HOLD_MS : opts.holdMs;
  if (!Number.isFinite(preferredHold) || preferredHold < 0) {
    throw new Error("holdMs must be a non-negative number");
  }
  const maxHoldMs = opts.maxHoldMs == null ? MAX_HOLD_MS : opts.maxHoldMs;
  if (!Number.isFinite(maxHoldMs) || maxHoldMs <= 0) throw new Error("maxHoldMs must be positive");
  if (opts.pinHold && preferredHold > maxHoldMs) {
    throw new Error(`holdMs ${preferredHold} exceeds the maxHoldMs cap ${maxHoldMs}`);
  }
  if (!opts.pinHold && maxHoldMs < preferredHold) {
    throw new Error(`maxHoldMs cap ${maxHoldMs} is below the requested hold ${preferredHold}`);
  }
  const floorHold = opts.pinHold ? preferredHold : Math.min(MIN_HOLD_MS, preferredHold);

  // Uncompressed always competes, on the same footing as every threshold - UNLESS the caller pinned
  // a threshold. Choosing the threshold that lands closest to the target quietly collapses the gaps
  // INSIDE a protected head or tail too, so a summary meant to play at its natural pace ends up
  // pre-compressed and the speed-up has nothing left to give the body. A pinned idle keeps the
  // source pacing intact and leaves the fitting entirely to the hold and the body speed-up.
  const candidates = (opts.idleMs != null
    ? [opts.idleMs]
    : [
      Number.MAX_SAFE_INTEGER,
      ...(opts.idleCandidates
        || [600000, 60000, 30000, 10000, 5000, 4000, 3000, 2000, 1500, 1200, 900, 700, 500, 350, 250]),
    ])
    .filter((ms) => Number.isFinite(ms) || ms === Number.MAX_SAFE_INTEGER)
    // A pinned hold must come out exactly as asked, so a threshold it could not fit under (which
    // would clamp it, or trip compressTimeline's hold <= idle guard) is not a candidate at all.
    .filter((ms) => !opts.pinHold || ms >= preferredHold);
  if (candidates.length === 0) throw new Error("no idle threshold is compatible with the hold");

  let best = null;
  for (const idleMs of candidates) {
    if (!(idleMs > 0)) continue;
    const probe = compressTimeline(events, { idleMs, holdMs: 0 });
    let chosenHold = Math.min(preferredHold, idleMs);
    if (!opts.pinHold && probe.fastForwards > 0) {
      // Everything except the holds is fixed, so the hold that spends the budget is exact
      // arithmetic. Floor rather than round, so it can never land above the threshold and trip
      // compressTimeline's own guard.
      const solved = (targetMs - probe.durationMs) / probe.fastForwards;
      const ceiling = Math.min(maxHoldMs, idleMs);
      chosenHold = Math.floor(Math.max(floorHold, Math.min(solved, ceiling)));
      if (chosenHold > ceiling) chosenHold = Math.floor(ceiling);
      if (chosenHold < 0) chosenHold = 0;
    }
    const result = compressTimeline(events, { idleMs, holdMs: chosenHold });
    const miss = Math.abs(result.durationMs - targetMs);
    if (!best || miss < best.miss) best = { miss, idleMs, holdMs: chosenHold, result };
  }

  // Collapsing the waits is not always enough. A TUI redraws constantly, so a long session can carry
  // a minute of genuine sub-threshold streaming that no idle threshold touches - the 17 minute panel
  // run still came to 81 seconds against a 40 second request. When even the best fit overshoots,
  // play the whole thing faster: a uniform factor keeps the rhythm intact (which compressing small
  // gaps further would destroy) and is exactly how anyone watches a terminal recording anyway.
  //
  // `tailMs` protects the ENDING from that speed-up, and `headMs` the OPENING. The start is where a
  // viewer reads what was asked for and the end is where the answer lands; racing through either
  // defeats the clip. Both spans replay at their natural pace and the middle - the long stretch of
  // the panel grinding away - absorbs the compression.
  let { result } = best;
  let speed = 1;
  const tailMs = opts.tailMs == null ? 0 : opts.tailMs;
  const headMs = opts.headMs == null ? 0 : opts.headMs;
  if (!Number.isFinite(tailMs) || tailMs < 0) throw new Error("tailMs must not be negative");
  if (!Number.isFinite(headMs) || headMs < 0) throw new Error("headMs must not be negative");
  if (!opts.noSpeedUp && result.durationMs > targetMs && targetMs > 0) {
    const tailCut = result.sourceDurationMs - tailMs;
    const firstTail = tailMs > 0 ? result.events.findIndex((e) => e.sourceT >= tailCut) : -1;
    const lastHead = headMs > 0
      ? result.events.findIndex((e) => e.sourceT > headMs)
      : -1;
    const bodyStart = lastHead > 0 ? lastHead : 0;
    const bodyEnd = firstTail > bodyStart ? firstTail : result.events.length;
    // Head and tail can be asked for spans that between them cover the whole session. There is then
    // no body to absorb the compression, and quietly falling through to a uniform speed-up would
    // race through the very stretches the caller asked to protect. Leave the clip alone instead and
    // say so - an honest overshoot beats a silently unprotected summary.
    const bodyIsEmpty = bodyEnd <= bodyStart;
    const headClipMs = bodyStart > 0 ? result.events[bodyStart - 1].t : 0;
    const bodyClipMs = (bodyEnd > 0 ? result.events[bodyEnd - 1].t : 0) - headClipMs;
    const tailClipMs = result.durationMs - headClipMs - bodyClipMs;
    const budgetForBody = targetMs - headClipMs - tailClipMs;
    if ((headMs > 0 || tailMs > 0) && !bodyIsEmpty && budgetForBody > 0 && bodyClipMs > budgetForBody) {
      speed = bodyClipMs / budgetForBody;
      const events = result.events.map((e, i) => {
        if (i < bodyStart) return e;
        if (i >= bodyEnd) return { ...e, t: Math.round(headClipMs + budgetForBody + (e.t - headClipMs - bodyClipMs)) };
        return { ...e, t: Math.round(headClipMs + (e.t - headClipMs) / speed) };
      });
      result = { ...result, events, durationMs: Math.round(headClipMs + budgetForBody + tailClipMs) };
    }
    if (speed === 1 && result.durationMs > targetMs) {
      // A fully protected clip is left alone. Speeding it up here would race through exactly the
      // spans `headMs`/`tailMs` were asked to preserve.
      if (bodyIsEmpty && (headMs > 0 || tailMs > 0)) return { ...result, speed: 1, protectedOverrun: true };
      speed = result.durationMs / targetMs;
      result = {
        ...result,
        events: result.events.map((e) => ({ ...e, t: Math.round(e.t / speed) })),
        durationMs: Math.round(result.durationMs / speed),
      };
    }
  }
  return { idleMs: best.idleMs, holdMs: best.holdMs, speed, ...result };
}

// Merge writes that land within the same instant of the replay.
//
// A compressed middle asks the player to write thousands of chunks a few milliseconds apart, and
// every write costs real time to parse and paint - so the replay cannot keep up and the clip runs
// long however aggressive the schedule is. Concatenating chunks that share a moment removes that
// floor without dropping a single byte: the terminal renders exactly the same text, in the same
// order, in fewer calls. A fast-forward event is a BOUNDARY - it neither joins the chunk before it
// nor absorbs the one after - so its badge and its skipped time stay attached to the right moment.
export function coalesceEvents(events, windowMs = 40) {
  if (!Array.isArray(events)) throw new Error("coalesceEvents needs an array of events");
  if (!Number.isFinite(windowMs) || windowMs < 0) throw new Error("windowMs must not be negative");
  const out = [];
  for (const event of events) {
    const last = out[out.length - 1];
    if (last && !event.fastForward && !last.fastForward && event.t - last.t <= windowMs) {
      last.data += event.data;
      continue;
    }
    out.push({ ...event });
  }
  return out;
}
