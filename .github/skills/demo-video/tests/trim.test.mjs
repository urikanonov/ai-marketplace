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


test("a mark-less capture can still be trimmed by gap alone (DEMO-TRIM-08)", () => {
  // marks are only written by the SCRIPT driver, so every hand-driven capture ships none - and
  // dead-air trimming is most useful on exactly those. Demanding an "ask" mark for a flag that
  // never needed one refused the case it was built for.
  const cast = {
    events: [{ t: 0, data: "hi\r\n" }, { t: 500, data: "working\r\n" }, { t: 90000, data: "idle\r\n" }],
  };
  const out = trimCast(cast, { untilGap: 30 });
  assert.equal(out.kept, 2);
  assert.equal(out.cast.events[out.cast.events.length - 1].t, 500);

  // ...and --until on a mark-less cast searches everything, but SAYS so, because that is the very
  // trap the mark anchor exists to avoid.
  const withMarker = trimCast({
    events: [{ t: 0, data: "run it\r\n" }, { t: 800, data: "DONE\r\n" }, { t: 90000, data: "x\r\n" }],
  }, { until: "DONE" });
  assert.equal(withMarker.searchedWholeCast, true);
  assert.equal(withMarker.kept, 2);
});

test("an explicitly named mark must exist, and a mark with no index is refused (DEMO-TRIM-09)", () => {
  const cast = {
    marks: [{ label: "ask", t: 0, eventIndex: 0 }],
    events: [{ t: 0, data: "a\r\n" }, { t: 1000, data: "DONE\r\n" }],
  };
  // A typo in --until-after must not quietly become a whole-cast search.
  assert.throws(() => trimCast(cast, { until: "DONE", after: "quit" }), /no "quit" mark to search after/);

  // A mark that carries no usable index is the same trap wearing a disguise: it would silently
  // search from the start, and the last hit can be the echoed prompt itself.
  const noIndex = { marks: [{ label: "ask", t: 0 }], events: cast.events };
  assert.throws(() => trimCast(noIndex, { until: "DONE" }), /"ask" mark .* has no eventIndex/);
});

test("a marker split across two pty writes is still found (DEMO-TRIM-10)", () => {
  // capture pushes one event per onData chunk and the boundaries are arbitrary, so a short token
  // can straddle two events. Testing each event alone reports the marker "never appears" and
  // refuses to trim - the expensive failure, on a session that did exactly what was asked.
  const cast = {
    marks: [{ label: "ask", t: 0, eventIndex: 0 }],
    events: [
      { t: 0, data: "ask\r\n" },
      { t: 1000, data: "PANEL SUM" },
      { t: 1100, data: "MARY here\r\n" },
      { t: 90000, data: "idle\r\n" },
    ],
  };
  const out = trimCast(cast, { until: "PANEL SUMMARY" });
  assert.equal(out.kept, 3, "should cut at the event that completed the marker");
});

test("a trim that keeps no time at all is refused (DEMO-TRIM-11)", () => {
  // An agent that thinks for longer than the gap before printing anything leaves a "clip" of the
  // echoed prompt. Rendering takes minutes, so say it now rather than after.
  const cast = {
    marks: [{ label: "ask", t: 0, eventIndex: 0 }],
    events: [{ t: 0, data: "ask\r\n" }, { t: 90000, data: "late\r\n" }],
  };
  assert.throws(() => trimCast(cast, { untilGap: 30 }), /keeps nothing after the mark/);
});


test("a marker split inside the escape that colours it is still found (DEMO-TRIM-14)", () => {
  // A pty can split a chunk anywhere, including mid-CSI. Stripping each event on its own leaves a
  // half-escape wedged in the middle of the marker, and the trim refuses a session that did
  // exactly what was asked. SGR carries no position, so dropping it rejoins the token.
  const cast = {
    marks: [{ label: "ask", t: 0, eventIndex: 0 }],
    events: [
      { t: 0, data: "ask\r\n" },
      { t: 1000, data: "PANEL \u001b[3" },
      { t: 1100, data: "2mSUMMARY here\r\n" },
      { t: 90000, data: "idle\r\n" },
    ],
  };
  assert.equal(trimCast(cast, { until: "PANEL SUMMARY" }).kept, 3);
});

test("cursor motion does not glue unrelated runs into a marker (DEMO-TRIM-15)", () => {
  // Dropping every escape would splice text that the terminal never showed side by side: after a
  // cursor home the next run is painted somewhere else entirely. A positional escape is a break.
  const cast = {
    marks: [{ label: "ask", t: 0, eventIndex: 0 }],
    events: [
      { t: 0, data: "ask\r\n" },
      { t: 1000, data: "PANEL SUM" },
      { t: 1100, data: "\u001b[HMARY\r\n" },
      { t: 90000, data: "idle\r\n" },
    ],
  };
  assert.throws(() => trimCast(cast, { until: "PANEL SUMMARY" }), /never appears/);
});

test("a trim that keeps nothing after the anchor is refused (DEMO-TRIM-16)", () => {
  // The guard has to measure from the ANCHOR, not from event zero: a session with a long startup
  // and an ask 45s in has plenty of "duration" while showing nothing but the prompt.
  const cast = {
    marks: [{ label: "ask", t: 45000, eventIndex: 1 }],
    events: [{ t: 0, data: "banner\r\n" }, { t: 45000, data: "ask\r\n" }, { t: 90000, data: "late\r\n" }],
  };
  assert.throws(() => trimCast(cast, { untilGap: 30 }), /nothing after the .* mark|no duration/);
});

test("an explicitly named default mark is still required (DEMO-TRIM-17)", () => {
  // Omitting `after` means "use the ask if there is one"; naming it means "there must be one".
  const markless = { events: [{ t: 0, data: "a\r\n" }, { t: 800, data: "DONE\r\n" }, { t: 90000, data: "x\r\n" }] };
  assert.equal(trimCast(markless, { until: "DONE" }).kept, 2);
  assert.throws(() => trimCast(markless, { until: "DONE", after: "ask" }), /no "ask" mark to search after/);
});
