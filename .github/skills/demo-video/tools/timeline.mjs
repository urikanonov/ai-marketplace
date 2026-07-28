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

export const DEFAULT_IDLE_MS = 900;
export const DEFAULT_HOLD_MS = 320;
// A fast-forward is a beat, not a scene: past about a second and a half the badge stops reading as
// "time passed" and starts reading as "the clip froze".
export const MAX_HOLD_MS = 1500;

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
    if (fastForward) skippedMs += gap - holdMs;
    clock += fastForward ? holdMs : gap;
    out.push({
      t: Math.round(clock),
      data: event.data,
      fastForward,
      skippedMs: fastForward ? Math.round(gap - holdMs) : 0,
    });
    previous = at;
  }
  return {
    events: out,
    durationMs: Math.round(clock),
    sourceDurationMs: Math.round(previous),
    skippedMs: Math.round(skippedMs),
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
export function fitTimeline(events, targetMs, opts = {}) {
  if (!Number.isFinite(targetMs) || targetMs <= 0) throw new Error("targetMs must be positive");
  const holdMs = opts.holdMs == null ? DEFAULT_HOLD_MS : opts.holdMs;
  const maxHoldMs = opts.maxHoldMs == null ? MAX_HOLD_MS : opts.maxHoldMs;

  // A session that already fits is kept whole. The candidate list has a ceiling, so without this a
  // single gap longer than the largest candidate would be fast-forwarded even when the clip was
  // explicitly asked to be longer than the session.
  const uncompressed = compressTimeline(events, { idleMs: Number.MAX_SAFE_INTEGER, holdMs: 0 });
  if (uncompressed.sourceDurationMs <= targetMs) {
    return { idleMs: Number.MAX_SAFE_INTEGER, holdMs: 0, ...uncompressed };
  }

  const candidates = (opts.idleCandidates
    || [600000, 60000, 30000, 10000, 5000, 4000, 3000, 2000, 1500, 1200, 900, 700, 500, 350, 250])
    .filter((ms) => ms >= holdMs);
  if (candidates.length === 0) throw new Error("no idle threshold is compatible with the hold");

  // Each candidate is judged by the length it can ACTUALLY achieve once its own hold is solved.
  // Picking the threshold with the default hold and only then stretching chooses a loser: another
  // threshold often hits the target exactly once its hold is solved for.
  let best = null;
  for (const idleMs of candidates) {
    const withDefault = compressTimeline(events, { idleMs, holdMs });
    let chosenHold = holdMs;
    let result = withDefault;
    if (withDefault.fastForwards > 0 && withDefault.durationMs < targetMs) {
      // Everything except the holds is fixed, so the hold that spends the budget is exact arithmetic.
      // It is ROUNDED before use: reporting a rounded hold while computing with a fractional one
      // means replaying the reported configuration produces a different clip than the one returned.
      const withoutHolds = compressTimeline(events, { idleMs, holdMs: 0 });
      const solved = (targetMs - withoutHolds.durationMs) / withDefault.fastForwards;
      chosenHold = Math.round(Math.max(holdMs, Math.min(solved, maxHoldMs, idleMs)));
      result = compressTimeline(events, { idleMs, holdMs: chosenHold });
    }
    const miss = Math.abs(result.durationMs - targetMs);
    if (!best || miss < best.miss) best = { miss, idleMs, holdMs: chosenHold, result };
  }
  return { idleMs: best.idleMs, holdMs: best.holdMs, ...best.result };
}
