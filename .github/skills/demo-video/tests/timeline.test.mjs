// DEMO-PLAN-01, DEMO-FF-01..03. Unit tests for the demo recorder's pure core: the beat scheduler
// that decides how long each moment of a montage is on screen, and the idle compressor that turns a
// real (mostly-waiting) terminal session into a watchable clip. Neither needs a browser or a PTY, so
// the durable part of an ad-hoc tool is still gated by CI.
//
// Run: node --test .github/skills/demo-video/tests

import test from "node:test";
import assert from "node:assert/strict";

import {
  applySpeedWindows,
  parseSpeedWindows,
  MIN_BEAT_MS, planBeats,
  DEFAULT_HOLD_MS, MAX_HOLD_MS, MIN_HOLD_MS, coalesceEvents, compressTimeline, fitTimeline,
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

test("a target just under the source keeps the session whole (DEMO-FF-08)", () => {
  // The uncompressed option was only considered when the source already fitted, so a 700s session
  // asked for 690s came back as a 1.5s clip - missing by 688s when leaving it alone missed by 10s.
  // Uncompressed has to compete on the same footing as every other candidate; the small remaining
  // overshoot is then absorbed by playback rate rather than by butchering the timeline.
  const events = [{ t: 0, data: "a" }, { t: 700000, data: "b" }];
  const fitted = fitTimeline(events, 690000);
  assert.equal(fitted.fastForwards, 0, `compressed a session that was nearly the right length: ${fitted.durationMs}ms`);
  assert.equal(fitted.durationMs, 690000, "the target was not reached");
  assert.ok(fitted.speed > 1 && fitted.speed < 1.05, `absorbed by an implausible speed: ${fitted.speed}`);
  // With speed-up disabled the session is returned at its true length, never chopped.
  const whole = fitTimeline(events, 690000, { noSpeedUp: true });
  assert.equal(whole.fastForwards, 0);
  assert.equal(whole.durationMs, 700000);
});

test("the hold shrinks as well as grows to hit the target (DEMO-FF-09)", () => {
  // The solver could only raise the hold above its default, so a session with many gaps overshot:
  // 84 fast-forwards at a 320ms floor is 27s of holds alone. Asking for 35s got 63s.
  const events = Array.from({ length: 200 }, (_, i) => ({ t: i * 1400, data: `line ${i}\r\n` }));
  const fitted = fitTimeline(events, 45000);
  assert.ok(Math.abs(fitted.durationMs - 45000) <= 3000,
    `fit overshot the target: ${fitted.durationMs}ms for a 45000ms request`);
  assert.ok(fitted.holdMs < DEFAULT_HOLD_MS, `the hold never shrank: ${fitted.holdMs}`);
  assert.ok(fitted.holdMs >= MIN_HOLD_MS, `the hold shrank below the perceptible floor: ${fitted.holdMs}`);
  // An explicitly pinned hold is still honoured exactly - it is an instruction, not a hint.
  const pinned = fitTimeline(events, 45000, { holdMs: 500, pinHold: true });
  assert.equal(pinned.holdMs, 500);
});

test("the hold can never exceed its cap or its threshold (DEMO-FF-10)", () => {
  const events = [{ t: 0, data: "a" }, { t: 10000, data: "b" }, { t: 20000, data: "c" }];
  // A cap below the requested hold is a contradiction, not something to silently ignore.
  assert.throws(() => fitTimeline(events, 5000, { holdMs: 500, maxHoldMs: 100 }), /cap|maxHold/i);
  assert.throws(() => fitTimeline(events, 5000, { holdMs: Number.NaN }), /hold/i);
  assert.throws(() => fitTimeline(events, 5000, { holdMs: -5 }), /hold/i);
  // Rounding must not push the hold past a fractional threshold, which would trip
  // compressTimeline's own guard and surface as an internal error.
  const fitted = fitTimeline(events, 1500, { idleCandidates: [500.6] });
  assert.ok(fitted.holdMs <= 500.6, `hold ${fitted.holdMs} exceeded its threshold`);
  const replay = compressTimeline(events, { idleMs: fitted.idleMs, holdMs: fitted.holdMs });
  assert.equal(replay.durationMs, fitted.durationMs);
});

test("skipped time adds up the same way twice (DEMO-FF-11)", () => {
  // Per-event and aggregate skipped time were rounded independently, so the parts did not sum to
  // the total that the render summary prints.
  const out = compressTimeline([{ t: 0, data: "a" }, { t: 1000.4, data: "b" }, { t: 2000.8, data: "c" }],
    { idleMs: 500, holdMs: 300 });
  const parts = out.events.reduce((a, e) => a + e.skippedMs, 0);
  assert.equal(parts, out.skippedMs, "the per-event skips do not sum to the reported total");
});

test("uniform speed-up lands a busy session on the requested length (DEMO-FF-12)", () => {
  // Collapsing the waits is not always enough: a TUI redraws constantly, so a long session carries
  // real sub-threshold streaming that no idle threshold touches. A 17 minute panel run still came to
  // 81 seconds against a 40 second request. A uniform factor keeps the rhythm (which compressing
  // small gaps further would destroy) and is how anyone watches a terminal recording anyway.
  const busy = Array.from({ length: 600 }, (_, i) => ({ t: i * 120, data: `chunk ${i}` }));
  const fitted = fitTimeline(busy, 20000);
  assert.ok(Math.abs(fitted.durationMs - 20000) <= 200, `did not reach the target: ${fitted.durationMs}ms`);
  assert.ok(fitted.speed > 1, "the clip was not sped up at all");
  assert.equal(fitted.events.length, busy.length, "speeding up must not drop output");
  for (let i = 1; i < fitted.events.length; i++) {
    assert.ok(fitted.events[i].t >= fitted.events[i - 1].t, "speeding up produced a backwards clock");
  }
  // A session that already fits is played at normal speed.
  const brisk = [{ t: 0, data: "a" }, { t: 500, data: "b" }];
  const kept = fitTimeline(brisk, 20000);
  assert.equal(kept.speed, 1);
  assert.equal(kept.durationMs, 500);
});

test("the closing stretch is exempt from the speed-up (DEMO-FF-13)", () => {
  // The end of a session is usually the whole point - the consolidated summary, the verdict - and a
  // uniform speed-up races through exactly that. `tailMs` marks a stretch of SOURCE time at the end
  // that replays at its natural pace while the earlier bulk absorbs the compression.
  const events = Array.from({ length: 400 }, (_, i) => ({ t: i * 200, data: `line ${i}\r\n` }));
  const sourceMs = 399 * 200;
  const tailMs = 20000;
  const fitted = fitTimeline(events, 30000, { tailMs });
  assert.ok(Math.abs(fitted.durationMs - 30000) <= 500, `missed the target: ${fitted.durationMs}ms`);

  // Everything from the cut onward keeps its ORIGINAL spacing, so the summary is readable.
  const cut = sourceMs - tailMs;
  const tail = fitted.events.filter((e) => e.sourceT >= cut);
  assert.ok(tail.length > 10, "the tail selection found almost nothing");
  for (let i = 1; i < tail.length; i++) {
    const clipGap = tail[i].t - tail[i - 1].t;
    const sourceGap = tail[i].sourceT - tail[i - 1].sourceT;
    assert.equal(clipGap, sourceGap, "the tail was re-timed instead of played at its natural pace");
  }
  // ...while the body before it was compressed to make room.
  const body = fitted.events.filter((e) => e.sourceT < cut);
  assert.ok(body[body.length - 1].t < cut, "the body was not compressed at all");
  // Order is preserved across the join.
  for (let i = 1; i < fitted.events.length; i++) {
    assert.ok(fitted.events[i].t >= fitted.events[i - 1].t, "the clock went backwards at the join");
  }
  assert.throws(() => fitTimeline(events, 30000, { tailMs: -1 }), /tailMs/i);
});

test("the opening is exempt from the speed-up as well as the ending (DEMO-FF-14)", () => {
  // The start is where a viewer reads what was ASKED FOR and the end is where the answer lands.
  // Racing through either defeats the clip, so both spans keep their natural pace and the middle -
  // the long stretch of the panel grinding away - absorbs the compression.
  const events = Array.from({ length: 600 }, (_, i) => ({ t: i * 200, data: `line ${i}\r\n` }));
  const headMs = 8000;
  const tailMs = 15000;
  const fitted = fitTimeline(events, 40000, { headMs, tailMs });
  assert.ok(Math.abs(fitted.durationMs - 40000) <= 600, `missed the target: ${fitted.durationMs}ms`);

  const head = fitted.events.filter((e) => e.sourceT <= headMs);
  assert.ok(head.length > 5, "the head selection found almost nothing");
  for (let i = 1; i < head.length; i++) {
    assert.equal(head[i].t - head[i - 1].t, head[i].sourceT - head[i - 1].sourceT,
      "the opening was re-timed instead of played at its natural pace");
  }
  const cut = (600 - 1) * 200 - tailMs;
  const tail = fitted.events.filter((e) => e.sourceT >= cut);
  for (let i = 1; i < tail.length; i++) {
    assert.equal(tail[i].t - tail[i - 1].t, tail[i].sourceT - tail[i - 1].sourceT,
      "the ending was re-timed instead of played at its natural pace");
  }
  // The middle carried the compression, and the clock never goes backwards across either join.
  assert.ok(fitted.speed > 1, "the middle was not compressed at all");
  for (let i = 1; i < fitted.events.length; i++) {
    assert.ok(fitted.events[i].t >= fitted.events[i - 1].t, "the clock went backwards at a join");
  }
  assert.throws(() => fitTimeline(events, 40000, { headMs: -1 }), /headMs/i);
});

test("writes that share a moment are merged without losing a byte (DEMO-FF-15)", () => {
  // A compressed middle asks the player to write thousands of chunks milliseconds apart, and each
  // write costs real time to parse and paint - so the replay cannot keep up and the clip runs long
  // however aggressive the schedule is. Merging chunks that share a moment removes that floor.
  const events = [
    { t: 0, data: "a", fastForward: false, skippedMs: 0 },
    { t: 5, data: "b", fastForward: false, skippedMs: 0 },
    { t: 12, data: "c", fastForward: false, skippedMs: 0 },
    { t: 400, data: "d", fastForward: false, skippedMs: 0 },
    { t: 700, data: "e", fastForward: true, skippedMs: 9000 },
    { t: 705, data: "f", fastForward: false, skippedMs: 0 },
  ];
  const merged = coalesceEvents(events, 40);
  // Not one byte lost, and the order is exactly as captured.
  assert.equal(merged.map((e) => e.data).join(""), "abcdef");
  assert.ok(merged.length < events.length, "nothing was merged at all");
  assert.equal(merged[0].data, "abc", "the shared moment was not merged");
  // A fast-forward keeps its own chunk so the badge and skipped time stay on the right moment.
  const ff = merged.find((e) => e.fastForward);
  assert.equal(ff.data, "e");
  assert.equal(ff.skippedMs, 9000);
  // A zero window merges nothing but still preserves the stream.
  assert.equal(coalesceEvents(events, 0).map((e) => e.data).join(""), "abcdef");
  assert.throws(() => coalesceEvents(events, -1), /windowMs/i);
  assert.throws(() => coalesceEvents("nope"), /array/i);
});

// A montage that opens on a still document reads as a stuck video, and the biggest source of that
// stillness was waiting for every diagram and chart to draw BEFORE the first beat ran. A beat that
// needs a rendered figure declares it instead, so the wait happens at the beat that needs it - by
// which time the figure has long since drawn - and the clip opens on an interaction.
test("the montage opens on an interaction and declares its own diagram waits (DEMO-PLAN-04)", () => {
  const first = REPORT_BEATS[0];
  assert.ok(first.required, "the opening beat must be a required interaction, not an establishing shot");
  assert.ok(first.abilities.includes("selection"), "the clip should open on the affordance a reader finds first");

  const needsRendering = REPORT_BEATS.filter((b) =>
    b.abilities.includes("diagrams") || b.abilities.includes("charts"));
  assert.ok(needsRendering.length >= 2, "the montage should comment on both a diagram and a chart");
  for (const beat of needsRendering) {
    assert.equal(beat.needsDiagrams, true, `${beat.id} draws a figure, so it must declare needsDiagrams`);
  }
  for (const beat of REPORT_BEATS.filter((b) => !needsRendering.includes(b))) {
    assert.ok(!beat.needsDiagrams, `${beat.id} does not need a figure and must not wait for one`);
  }
});

// Letting the fitter choose the idle threshold quietly defeats a protected tail: the threshold that
// lands closest to the target also collapses the gaps INSIDE the summary, so the summary arrives
// pre-compressed and the body speed-up has nothing left to give. Pinning the threshold keeps the
// source pacing and pushes all the fitting into the hold and the body.
test("a pinned idle threshold is honoured, so a protected tail keeps its pace (DEMO-FF-16)", () => {
  // A long stretch of slow work, then a burst that must stay readable.
  const events = [];
  for (let i = 0; i < 60; i++) events.push({ t: i * 4000, data: `work ${i}\n` });
  const burstFrom = 60 * 4000;
  for (let i = 0; i < 40; i++) events.push({ t: burstFrom + i * 400, data: `summary ${i}\n` });
  const sourceMs = events[events.length - 1].t;
  const tailMs = sourceMs - burstFrom + 400;

  const free = fitTimeline(events, 20000, { tailMs });
  const pinned = fitTimeline(events, 20000, { tailMs, idleMs: 3000, holdMs: 320, pinHold: true });

  // The pinned run must actually use the threshold it was given, not a better-fitting one.
  const gapsKept = (tl) => {
    const tail = tl.events.filter((e) => e.sourceT >= burstFrom);
    return tail[tail.length - 1].t - tail[0].t;
  };
  assert.ok(gapsKept(pinned) > 0, "the pinned tail must still occupy real time");
  assert.equal(pinned.events.length, events.length, "no event may be dropped");
  // The point of pinning: a free fit is allowed to choose a threshold below the burst's own 400ms
  // gaps, which collapses the summary itself. The pinned 3000ms threshold sits above the 400ms gaps
  // and below the 4000ms waits, so the waits collapse and the summary keeps every original gap -
  // its clip span must equal its SOURCE span exactly, not merely be longer than the free fit's.
  assert.equal(
    gapsKept(pinned), 39 * 400,
    `a pinned threshold above the tail's own gaps must leave them untouched (got ${gapsKept(pinned)}ms)`,
  );
  assert.ok(
    gapsKept(free) < gapsKept(pinned),
    `the free fit is expected to collapse the tail (free ${gapsKept(free)}ms)`,
  );
  // Order is preserved and the schedule is still monotonic.
  for (let i = 1; i < pinned.events.length; i++) {
    assert.ok(pinned.events[i].t >= pinned.events[i - 1].t, "the pinned schedule must not go backwards");
    assert.ok(pinned.events[i].sourceT >= pinned.events[i - 1].sourceT, "source order must be preserved");
  }
  assert.ok(free.events.length === pinned.events.length, "both fits carry every event");
});

// A review note about a clip is almost always local - "the stretch around twenty seconds drags" -
// and re-fitting the whole thing to fix it disturbs the parts that were already right.
test("a window of the clip can be re-timed without disturbing the rest (DEMO-FF-17)", () => {
  const events = [];
  for (let i = 0; i <= 40; i++) events.push({ t: i * 1000, data: `line ${i}\n` });

  const out = applySpeedWindows(events, parseSpeedWindows("20:27:2"));
  assert.equal(out.length, events.length, "no event may be dropped");
  // Before the window: untouched.
  assert.equal(out[10].t, 10000);
  assert.equal(out[20].t, 20000);
  // Inside: half the elapsed time.
  assert.equal(out[24].t, 22000);
  assert.equal(out[27].t, 23500);
  // After: shifted earlier by exactly what the window saved (7s at 2x saves 3.5s), never re-scaled.
  assert.equal(out[40].t, 40000 - 3500);
  for (let i = 1; i < out.length; i++) {
    assert.ok(out[i].t >= out[i - 1].t, "the schedule must stay monotonic");
  }

  // Several windows compose, and a malformed one is refused rather than silently ignored - a clip
  // that quietly came back at the old pace is the failure this is meant to prevent.
  const two = applySpeedWindows(events, parseSpeedWindows("5:10:2,20:30:5"));
  assert.equal(two[40].t, 40000 - 2500 - 8000);
  assert.throws(() => parseSpeedWindows("20:27"), /from:to:factor/);
  assert.throws(() => parseSpeedWindows("a:b:c"), /three numbers/);
  assert.throws(() => applySpeedWindows(events, [{ fromMs: 5000, toMs: 1000, factor: 2 }]), /does not move forward/);
  assert.throws(() => applySpeedWindows(events, [{ fromMs: 0, toMs: 1000, factor: 0 }]), /must be positive/);
  assert.throws(() => applySpeedWindows(events, parseSpeedWindows("5:15:2,10:20:2")), /must not overlap/);
});

// A montage moves fast and has no narrator. Every beat names itself on screen, and the names are
// part of the demo's contract, not decoration.
test("every beat names itself on screen (DEMO-PLAN-05)", () => {
  for (const beat of REPORT_BEATS) {
    const toast = beat.toast || beat.label;
    assert.ok(typeof toast === "string" && toast.trim().length > 3, `${beat.id} has no readable toast`);
    assert.ok(toast.length <= 40, `${beat.id}'s toast is too long to read at speed: ${toast}`);
  }
  const toasts = REPORT_BEATS.map((b) => b.toast || b.label);
  assert.equal(new Set(toasts).size, toasts.length, "two beats must not claim the same caption");
});

// If the head and tail between them cover the whole session there is no body left to absorb the
// compression. Falling through to the uniform speed-up then raced through exactly the spans the
// caller asked to protect - and said nothing about it.
test("a fully protected clip overruns honestly instead of racing its protected spans (DEMO-FF-18)", () => {
  const events = [];
  for (let i = 0; i <= 10; i++) events.push({ t: i * 1000, data: `line ${i}\n` });
  const uncompressed = Number.MAX_SAFE_INTEGER;

  for (const [name, opts] of [
    ["the head covers everything", { headMs: 11000 }],
    ["the tail covers everything", { tailMs: 11000 }],
    ["head and tail overlap", { headMs: 7000, tailMs: 7000 }],
  ]) {
    const out = fitTimeline(events, 3000, { ...opts, idleMs: uncompressed });
    assert.equal(out.protectedOverrun, true, `${name}: should report the overrun`);
    assert.equal(out.durationMs, 10000, `${name}: the protected span must keep its own pace`);
    assert.equal(out.events.length, events.length, `${name}: no event may be dropped`);
  }

  // A genuine body is still compressed - the guard must not disable the feature it protects.
  const normal = fitTimeline(events, 3000, { headMs: 1000, tailMs: 1000, idleMs: uncompressed });
  assert.notEqual(normal.protectedOverrun, true);
  assert.ok(normal.durationMs <= 3000, `a real body should still be fitted, got ${normal.durationMs}`);
});
