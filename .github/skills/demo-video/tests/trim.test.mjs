// Trimming contract. A capture keeps recording after the interesting part ends, and every published
// clip so far was cut by a throwaway script - so these pin the awkward decisions (which occurrence
// of the marker, where the tail actually begins) that the throwaway scripts kept getting wrong.

import test from "node:test";
import assert from "node:assert/strict";

import { trimCast } from "../tools/trim.mjs";

// A miniature of the real thing: an ask that CONTAINS the marker it asks for (the trap), the agent
// answering twice, then a long quiet tail before the driver's /exit.
const castFixture = () => ({
  cols: 120,
  rows: 30,
  marks: [
    { label: "ask", t: 1000, eventIndex: 1, text: "finish with a PANEL SUMMARY table" },
    { label: "quit", t: 90000, eventIndex: 8, text: "/exit" },
  ],
  events: [
    { t: 0, data: "$ copilot\r\n" },
    { t: 1000, data: "finish with a PANEL SUMMARY table\r\n" },
    { t: 2000, data: "thinking\r\n" },
    { t: 3000, data: "\u001b[32mPANEL SUMMARY\u001b[0m first draft\r\n" },
    { t: 4000, data: "more work\r\n" },
    { t: 5000, data: "PANEL SUMMARY final\r\n" },
    { t: 5500, data: "repaint\r\n" },
    { t: 90000, data: "idle repaint\r\n" },
    { t: 91000, data: "/exit\r\n" },
  ],
});

test("the marker is found after the mark, not in the ask that names it (DEMO-TRIM-01)", () => {
  const out = trimCast(castFixture(), { until: "PANEL SUMMARY" });
  // Event 1 is the ask and contains the marker; cutting there would leave a clip of nothing. The
  // LAST occurrence after the mark is event 5.
  assert.equal(out.kept, 6, "should keep events 0..5");
  assert.equal(out.cast.events[out.cast.events.length - 1].data, "PANEL SUMMARY final\r\n");
  assert.equal(out.dropped, 3);
});

test("the marker is matched through the escapes that colour it (DEMO-TRIM-02)", () => {
  // The summary is nearly always painted with SGR colour, so matching raw bytes finds nothing.
  const cast = castFixture();
  cast.events = cast.events.slice(0, 5);
  const out = trimCast(cast, { until: "PANEL SUMMARY" });
  assert.equal(out.cast.events[out.cast.events.length - 1].t, 3000);
});

test("a trim keeps the marks it still has events for, and drops the rest (DEMO-TRIM-03)", () => {
  const out = trimCast(castFixture(), { until: "PANEL SUMMARY" });
  assert.deepEqual(out.cast.marks.map((m) => m.label), ["ask"],
    "the quit mark pointed past the cut and must go, or a render can seek into nothing");
  assert.equal(out.droppedMarks, 1);
  // The title card is drawn from the ask mark, so losing it would lose the prompt.
  assert.equal(out.cast.marks[0].text, "finish with a PANEL SUMMARY table");
  assert.equal(out.cast.durationMs, 5000, "the trimmed cast must state its own length");
});

test("untilGap cuts where the session actually went quiet (DEMO-TRIM-04)", () => {
  // The terminal repaints for a moment after the marker, and the ending looks abrupt without it -
  // so the cut belongs at the last event before the silence, not at the marker itself.
  const out = trimCast(castFixture(), { until: "PANEL SUMMARY", untilGap: 30 });
  assert.equal(out.cast.events[out.cast.events.length - 1].t, 5500, "should include the repaint");
  assert.equal(out.kept, 7);
});

test("untilGap alone measures from the mark (DEMO-TRIM-05)", () => {
  const out = trimCast(castFixture(), { untilGap: 30 });
  assert.equal(out.cast.events[out.cast.events.length - 1].t, 5500);
});

test("a gap that never comes keeps the rest of the session (DEMO-TRIM-06)", () => {
  const cast = castFixture();
  cast.events = cast.events.slice(0, 7);
  const out = trimCast(cast, { until: "PANEL SUMMARY", untilGap: 30 });
  assert.equal(out.kept, 7);
  assert.equal(out.dropped, 0);
});

test("a marker that never appears is refused, not silently ignored (DEMO-TRIM-07)", () => {
  // Rendering the whole idle tail because a marker was mistyped is the expensive failure: the
  // operator publishes a clip that ends on an empty prompt.
  assert.throws(() => trimCast(castFixture(), { until: "REVIEW-APPLIED" }),
    /"REVIEW-APPLIED" never appears after the "ask" mark/);
  assert.throws(() => trimCast(castFixture(), { until: "PANEL SUMMARY", after: "nope" }),
    /no "nope" mark to search after \(marks: ask, quit\)/);
  assert.throws(() => trimCast({ events: [] }, { until: "x" }), /no events/);
  assert.throws(() => trimCast(castFixture(), {}), /nothing to trim by/);
  assert.throws(() => trimCast(castFixture(), { untilGap: 0 }), /positive number of seconds/);
});
