// DEMO-PLAN-01, DEMO-FF-01..03. Unit tests for the demo recorder's pure core: the beat scheduler
// that decides how long each moment of a montage is on screen, and the idle compressor that turns a
// real (mostly-waiting) terminal session into a watchable clip. Neither needs a browser or a PTY, so
// the durable part of an ad-hoc tool is still gated by CI.
//
// Run: node --test .github/skills/demo-video/tests

import test from "node:test";
import assert from "node:assert/strict";

import {
  MIN_BEAT_MS, planBeats,
  DEFAULT_HOLD_MS, MAX_HOLD_MS, compressTimeline, fitTimeline,
} from "../tools/timeline.mjs";
import { REPORT_BEATS, REPORT_ABILITIES } from "../tools/report-beats.mjs";

const sum = (list) => list.reduce((a, b) => a + b, 0);

test("a beat plan always adds up to exactly the requested duration (DEMO-PLAN-01)", () => {
  for (const seconds of [6, 10, 12, 20, 7.5]) {
    const totalMs = Math.round(seconds * 1000);
    const plan = planBeats(REPORT_BEATS, totalMs);
    assert.equal(plan.length, REPORT_BEATS.length, `${seconds}s dropped or invented a beat`);
    assert.equal(sum(plan.map((b) => b.budgetMs)), totalMs, `${seconds}s did not sum to budget`);
    assert.deepEqual(plan.map((b) => b.id), REPORT_BEATS.map((b) => b.id), "the montage was reordered");
    for (const beat of plan) {
      assert.ok(beat.budgetMs >= MIN_BEAT_MS, `${beat.id} at ${seconds}s fell under the readable floor`);
      assert.ok(Number.isInteger(beat.budgetMs), `${beat.id} got a fractional budget`);
    }
  }
});

test("weight decides the share, and a floor is funded by the longest beat (DEMO-PLAN-01)", () => {
  const plan = planBeats([
    { id: "light", label: "light", weight: 1 },
    { id: "heavy", label: "heavy", weight: 3 },
  ], 8000);
  const by = Object.fromEntries(plan.map((b) => [b.id, b.budgetMs]));
  assert.equal(by.heavy + by.light, 8000);
  assert.ok(by.heavy / by.light > 2.5, "tripling the weight must roughly triple the slice");

  // A beat whose proportional share falls under the floor is pinned to it and the time comes out of
  // the longest slice, so the total still lands exactly on the budget.
  const tight = planBeats([
    { id: "tiny", label: "tiny", weight: 1 },
    { id: "huge", label: "huge", weight: 200 },
  ], 4000);
  const tightBy = Object.fromEntries(tight.map((b) => [b.id, b.budgetMs]));
  assert.equal(tightBy.tiny, MIN_BEAT_MS, "a squeezed beat must be raised to the floor");
  assert.equal(tightBy.tiny + tightBy.huge, 4000);
});

test("an impossible or malformed budget is refused, not silently truncated (DEMO-PLAN-01)", () => {
  assert.throws(() => planBeats(REPORT_BEATS, MIN_BEAT_MS * REPORT_BEATS.length - 1), /too short/i);
  assert.throws(() => planBeats([], 10000), /beat/i);
  assert.throws(() => planBeats(REPORT_BEATS, 0), /positive/i);
  assert.throws(() => planBeats(REPORT_BEATS, -1000), /positive/i);
  assert.throws(() => planBeats(REPORT_BEATS, Number.NaN), /positive/i);
  // A fractional duration cannot be split into whole milliseconds that sum to it, so promising an
  // exact total and accepting 1000.5 are incompatible - say so instead of returning 1001.
  assert.throws(() => planBeats(REPORT_BEATS, 10000.5), /whole milliseconds|integer/i);
});

test("a degenerate weight cannot produce a NaN budget (DEMO-PLAN-02)", () => {
  // Weights arrive from a beat list that is edited by hand, and `Infinity / Infinity` is NaN: the
  // plan would then be silently unusable rather than loudly wrong, and every downstream sleep would
  // be NaN. A non-finite or non-positive weight falls back to 1, exactly like a missing one.
  for (const weight of [Number.POSITIVE_INFINITY, Number.NaN, 0, -5, "abc", null, undefined]) {
    const plan = planBeats([
      { id: "a", label: "a", weight },
      { id: "b", label: "b", weight: 1 },
    ], 4000);
    for (const beat of plan) {
      assert.ok(Number.isInteger(beat.budgetMs),
        `weight ${String(weight)} produced a non-integer budget ${beat.budgetMs}`);
      assert.ok(beat.budgetMs >= MIN_BEAT_MS, `weight ${String(weight)} produced ${beat.budgetMs}`);
    }
    assert.equal(sum(plan.map((b) => b.budgetMs)), 4000, `weight ${String(weight)} broke the total`);
  }
});

test("the report montage covers every advertised ability (DEMO-PLAN-01)", () => {
  const ids = REPORT_BEATS.map((b) => b.id);
  assert.equal(new Set(ids).size, ids.length, "two beats share an id");
  for (const beat of REPORT_BEATS) {
    assert.ok(beat.abilities.length > 0, `${beat.id} shows no ability`);
    assert.equal(typeof beat.run, "function", `${beat.id} has no run step`);
  }
  const covered = [...new Set(REPORT_BEATS.flatMap((b) => b.abilities))].sort();
  assert.deepEqual(covered, [...REPORT_ABILITIES].sort(),
    "the beats and the advertised ability list disagree");
});

// A capture whose gaps are all short (streaming output) and one long think, so the tests can tell
// preserved rhythm from collapsed dead air.
const CAPTURE = [
  { t: 0, data: "$ copilot\r\n" },
  { t: 200, data: "thinking" },
  { t: 400, data: "." },
  { t: 30400, data: "done\r\n" },
  { t: 30600, data: "$ " },
];

test("dead air collapses to a hold and short gaps are left alone (DEMO-FF-01)", () => {
  const out = compressTimeline(CAPTURE, { idleMs: 1000, holdMs: 300 });
  assert.equal(out.events.length, CAPTURE.length, "compression must never drop output");
  assert.deepEqual(out.events.map((e) => e.data), CAPTURE.map((e) => e.data),
    "compression must never reorder or rewrite output");
  // The natural rhythm below the threshold is untouched...
  assert.deepEqual(out.events.slice(0, 3).map((e) => e.t), [0, 200, 400]);
  // ...and the 30 second wait replays as the hold, not as 30 seconds.
  assert.equal(out.events[3].t, 700);
  assert.equal(out.events[3].fastForward, true);
  assert.equal(out.events[3].skippedMs, 29700);
  assert.equal(out.events[4].t, 900);
  assert.equal(out.events[4].fastForward, false);
  assert.equal(out.durationMs, 900);
  assert.equal(out.sourceDurationMs, 30600);
  assert.equal(out.skippedMs, 29700);
  assert.equal(out.fastForwards, 1);
});

test("a compressed timeline stays monotonic and never grows (DEMO-FF-02)", () => {
  for (const idleMs of [250, 500, 900, 5000, 60000]) {
    const out = compressTimeline(CAPTURE, { idleMs, holdMs: Math.min(DEFAULT_HOLD_MS, idleMs) });
    assert.ok(out.durationMs <= out.sourceDurationMs, `idle ${idleMs} made the clip longer`);
    for (let i = 1; i < out.events.length; i++) {
      assert.ok(out.events[i].t >= out.events[i - 1].t, `idle ${idleMs} produced a backwards clock`);
    }
    // Nothing is skipped when the threshold is above every gap in the capture.
    if (idleMs >= 30000) assert.equal(out.fastForwards, 0);
  }
  // A hold longer than the threshold would EXPAND a gap, which is never what fast-forward means.
  assert.throws(() => compressTimeline(CAPTURE, { idleMs: 500, holdMs: 900 }), /exceed/i);
  assert.throws(() => compressTimeline(CAPTURE, { idleMs: 0 }), /positive/i);
  assert.throws(() => compressTimeline([{ t: 5 }, { t: 1 }], {}), /monotonic/i);
  assert.throws(() => compressTimeline("nope", {}), /array/i);
});

test("fitTimeline lands a long session near the requested clip length (DEMO-FF-03)", () => {
  // A session that is mostly waiting: 40 chunks, each after a 20 second think.
  const slow = Array.from({ length: 40 }, (_, i) => ({ t: i * 20000, data: `line ${i}\r\n` }));
  const fitted = fitTimeline(slow, 15000);
  // A tight bound on purpose: a loose one passes for an implementation that never solves the hold
  // at all (39 default holds is 12.5s, which would sit inside a 1.5x bound and prove nothing).
  assert.ok(Math.abs(fitted.durationMs - 15000) <= 2000,
    `fit missed the target: ${fitted.durationMs}ms vs 15000ms`);
  assert.ok(fitted.fastForwards > 0, "a session of pure waiting must be fast-forwarded");
  assert.equal(fitted.events.length, slow.length, "fitting must never drop output");
  // A session that is already short is not stretched to fill the target.
  const brisk = [{ t: 0, data: "a" }, { t: 120, data: "b" }, { t: 240, data: "c" }];
  const kept = fitTimeline(brisk, 15000);
  assert.equal(kept.durationMs, 240);
  assert.equal(kept.fastForwards, 0);
  assert.throws(() => fitTimeline(brisk, 0), /positive/i);
});

test("a session shorter than the target is never compressed, however long it is (DEMO-FF-05)", () => {
  // The candidate list has a ceiling, so a session with a gap LONGER than the largest candidate used
  // to be fast-forwarded even when the whole session already fitted the target - the clip lost ten
  // minutes of real time it was explicitly asked to keep.
  const longGap = [{ t: 0, data: "start\r\n" }, { t: 700000, data: "done\r\n" }];
  const fitted = fitTimeline(longGap, 900000);
  assert.equal(fitted.fastForwards, 0, "a session inside the target must not be compressed");
  assert.equal(fitted.durationMs, 700000);
  assert.deepEqual(fitted.events.map((e) => e.data), longGap.map((e) => e.data));
});

test("fitTimeline compares candidates by their SOLVED length, not their default one (DEMO-FF-06)", () => {
  // Choosing the threshold with the default hold and only then stretching picks a loser: another
  // threshold can hit the target exactly once its own hold is solved. The choice has to be made on
  // the length each candidate can actually achieve.
  const events = [
    { t: 0, data: "a" }, { t: 29845, data: "b" }, { t: 34953, data: "c" },
    { t: 46778, data: "d" }, { t: 50986, data: "e" },
  ];
  const target = 8704;
  const fitted = fitTimeline(events, target);
  assert.ok(Math.abs(fitted.durationMs - target) <= 60,
    `a better-fitting threshold existed: got ${fitted.durationMs}ms for a ${target}ms target`);
  assert.equal(fitted.events.length, events.length);
  assert.ok(fitted.durationMs <= fitted.sourceDurationMs);
});

test("the hold stretches to use the target when few gaps carry the session (DEMO-FF-04)", () => {
  // Idle thresholds are discrete, so with only a couple of long waits no threshold lands near the
  // target: a 30 second session with two big pauses collapses to ~4s and wastes the budget. Solving
  // the HOLD for the chosen threshold uses the time that was asked for, and the viewer gets a
  // readable pause on the fast-forward badge instead of a blink.
  const twoPauses = [
    { t: 0, data: "a" }, { t: 500, data: "b" },
    { t: 14500, data: "c" }, { t: 15000, data: "d" },
    { t: 28000, data: "e" },
  ];
  // Reachable target: the two holds have room to absorb it exactly.
  const fitted = fitTimeline(twoPauses, 3000);
  assert.equal(fitted.fastForwards, 2);
  assert.ok(Math.abs(fitted.durationMs - 3000) <= 50, `expected ~3s, got ${fitted.durationMs}ms`);
  assert.ok(fitted.holdMs > DEFAULT_HOLD_MS, "the hold should have stretched toward the target");
  // Unreachable target: the hold clamps at the cap rather than turning a fast-forward into a stare,
  // so the clip is as long as it can legibly be and no longer. (A target so large that leaving the
  // session uncompressed is closer is a different case - then nothing is fast-forwarded at all.)
  const capped = fitTimeline(twoPauses, 5000);
  assert.equal(capped.fastForwards, 2);
  assert.equal(capped.holdMs, MAX_HOLD_MS, "an unreachable target must clamp at the cap");
  assert.equal(capped.durationMs, 1000 + 2 * MAX_HOLD_MS);
  // A target longer than the session itself is best served by not compressing at all.
  const untouched = fitTimeline(twoPauses, 600000);
  assert.equal(untouched.fastForwards, 0);
  assert.equal(untouched.durationMs, 28000);
  // Stretching never reorders or drops output, and never exceeds the source length.
  assert.deepEqual(fitted.events.map((e) => e.data), twoPauses.map((e) => e.data));
  assert.ok(fitted.durationMs <= fitted.sourceDurationMs);
  // The default (no stretching) would have been far shorter, which is the waste this fixes.
  assert.ok(compressTimeline(twoPauses, { idleMs: 10000 }).durationMs < fitted.durationMs);
});

test("a fractional floor cannot break the exact-budget contract (DEMO-PLAN-03)", () => {
  // Whole milliseconds cannot sum to a fractional total, and a fractional floor smuggles one in
  // through the back door: the pinned beat keeps the fraction and the plan overshoots.
  assert.throws(() => planBeats([{ id: "a" }, { id: "b" }], 701, { minMs: 350.5 }), /whole milliseconds|integer/i);
  assert.throws(() => planBeats([{ id: "a" }], 1000, { minMs: -1 }), /positive|integer/i);
  assert.throws(() => planBeats([{ id: "a" }], 1000, { minMs: Number.NaN }), /positive|integer/i);
  const plan = planBeats([{ id: "a" }, { id: "b" }], 701, { minMs: 350 });
  assert.equal(plan.reduce((a, b) => a + b.budgetMs, 0), 701);
});

test("the fit it reports reproduces the timeline it returns (DEMO-FF-07)", () => {
  // fitTimeline computes with a fractional hold but reports a rounded one, so replaying its own
  // reported configuration produced a different clip length than the one it just returned.
  const events = [{ t: 0, data: "a" }, { t: 9000, data: "b" }, { t: 21000, data: "c" }];
  for (const target of [757, 1500, 3000, 4321]) {
    const fit = fitTimeline(events, target);
    const replay = compressTimeline(events, { idleMs: fit.idleMs, holdMs: fit.holdMs });
    assert.equal(replay.durationMs, fit.durationMs,
      `target ${target}: reported hold ${fit.holdMs} replays to ${replay.durationMs}, not ${fit.durationMs}`);
    assert.deepEqual(replay.events.map((e) => e.t), fit.events.map((e) => e.t));
  }
});
