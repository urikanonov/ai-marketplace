// Trimming a cast to the part worth filming.
//
// A capture does not stop when the interesting part does: the session keeps recording until the
// script's quit step fires, so a real cast carries a long idle tail (the shipped multi-duck
// recording sat idle for 26 minutes between its summary and the `/exit`). Every published clip so
// far was trimmed by a throwaway script written from scratch each time, which is exactly the step
// that made "re-record this clip" not actually reproducible.
//
// It is a pure function of (cast, options) so the awkward parts - which occurrence of the marker,
// where the tail really begins - are testable without rendering anything.

// One escape, anchored, so a chunk can be walked sequence by sequence. Three forms, in order:
// an OSC (window title, hyperlink) run through its BEL or ST terminator - its payload is NOT on
// screen, so leaving it as visible text would let a window title satisfy the marker; a CSI, whose
// parameter bytes include the private `<=>?` a TUI sends constantly (omit them and the sequence
// looks truncated, swallowing the text after it); and the two-character C1 form, which deliberately
// EXCLUDES `[` and `]` because those introduce the first two.
const ESC_ONE = /^(?:\u001b\][\s\S]*?(?:\u0007|\u001b\\)|\u001b\[[0-9;:<=>?]*[ -\/]*[@-~]|\u001b[@-Z\\^_])/;
// Colour and weight carry no position, so removing them REJOINS a token the terminal drew in two
// colours. Everything else moves the cursor or erases, which means the runs either side were never
// adjacent on screen - replacing those with a space keeps them from being spliced into a marker
// that was never displayed. This is the same split `redact.mjs` makes, for the same reason.
const SGR_ONE = /^\u001b\[[0-9;:?]*m$/;
// An escape truncated by a chunk boundary is held until the next event completes it, but a stream
// of malformed bytes must not accumulate forever.
const MAX_PENDING = 64;

function fail(message) {
  throw new Error(`trim: ${message}`);
}

function markIndex(cast, after, required) {
  const marks = cast.marks || [];
  const mark = marks.find((m) => m.label === after);
  if (!mark) {
    // A mark the caller NAMED must exist - a typo silently becoming a whole-cast search is the
    // trap this anchor exists to prevent. The DEFAULT mark is different: `marks` are only written
    // by the script driver, so every hand-driven capture has none, and refusing those would turn
    // away the case dead-air trimming is most useful for.
    if (required) {
      const known = marks.map((m) => m.label).join(", ") || "none";
      fail(`this cast has no "${after}" mark to search after (marks: ${known})`);
    }
    return -1;
  }
  // A mark that is present but carries no usable index is the same trap in disguise: it would
  // search from the start, where the last hit can be the echoed prompt itself.
  if (!Number.isInteger(mark.eventIndex)) {
    fail(`the "${after}" mark in this cast has no eventIndex, so there is nothing to search after`);
  }
  return mark.eventIndex;
}

// A pty chunk boundary is arbitrary, so a short marker can straddle two events - and the split can
// land INSIDE the escape that colours it. Testing each event alone reports the marker "never
// appears", refusing to trim a session that did exactly what was asked. This walks the stream
// statefully: escapes are classified rather than blanket-stripped, a truncated escape is held for
// the next event to complete, and the visible tail is carried so the match ignores chunking.
function findLastMarker(events, from, until) {
  let found = -1;
  let carry = "";
  let pending = "";
  for (let i = from + 1; i < events.length; i++) {
    const raw = pending + String(events[i].data);
    pending = "";
    let visible = "";
    let j = 0;
    while (j < raw.length) {
      const esc = raw.indexOf("\u001b", j);
      if (esc < 0) { visible += raw.slice(j); break; }
      visible += raw.slice(j, esc);
      const rest = raw.slice(esc);
      const match = ESC_ONE.exec(rest);
      if (!match) {
        // Truncated by the chunk boundary: hold it so the next event can finish it. If it never
        // completes within a sane length it is not an escape, so treat it as a break and move on.
        if (rest.length < MAX_PENDING) { pending = rest; break; }
        visible += " ";
        j = esc + 1;
        continue;
      }
      visible += SGR_ONE.test(match[0]) ? "" : " ";
      j = esc + match[0].length;
    }
    const text = carry + visible;
    if (text.includes(until)) found = i;
    carry = until.length > 1 ? text.slice(-(until.length - 1)) : "";
  }
  return found;
}

// The marker is searched ONLY after a named mark, because the prompt that ASKS the agent for the
// artifact almost always contains the marker word itself - so a naive search matches the ask, cuts
// the clip at the very moment the session starts, and leaves nothing worth watching.
export function trimCast(cast, { until = null, untilGap = null, after = null } = {}) {
  const events = cast.events || [];
  if (!events.length) fail("this cast has no events");
  if (until == null && untilGap == null) fail("nothing to trim by: pass until or untilGap");

  const from = markIndex(cast, after == null ? "ask" : after, after != null);
  let cut = events.length - 1;

  if (until != null) {
    if (!String(until).length) fail("--until needs a marker to look for");
    const found = findLastMarker(events, from, String(until));
    if (found < 0) {
      fail(`${JSON.stringify(until)} never appears after the "${after == null ? "ask" : after}" mark, `
        + "so there is nothing to trim to. Check the marker, or render without --until to see what "
        + "the session did print.");
    }
    cut = found;
  } else {
    cut = Math.max(from, 0);
  }

  // The tail is not the marker itself - the terminal keeps repainting for a moment afterwards, and
  // the ending looks abrupt without it. Cut at the last event before the session goes quiet, which
  // is where "the interesting part ended" actually is.
  if (untilGap != null) {
    const gapMs = Number(untilGap) * 1000;
    if (!Number.isFinite(gapMs) || gapMs <= 0) fail("untilGap must be a positive number of seconds");
    for (let i = cut + 1; i < events.length; i++) {
      if (events[i].t - events[i - 1].t > gapMs) {
        cut = i - 1;
        break;
      }
      cut = i;
    }
  }

  const kept = events.slice(0, cut + 1);
  // Measured from the ANCHOR, not from event zero. A session with a long banner and an ask 45
  // seconds in has plenty of "duration" while showing nothing but the prompt, and rendering costs
  // minutes - so a clip with nothing after the anchor should say so now rather than after.
  const anchor = Math.max(from, 0);
  if (cut <= anchor) {
    fail("the trim keeps nothing after the mark; raise --until-gap, or check the marker");
  }
  const marks = (cast.marks || []).filter((m) => !Number.isInteger(m.eventIndex) || m.eventIndex <= cut);
  return {
    cast: { ...cast, marks, events: kept, durationMs: kept[kept.length - 1].t },
    kept: kept.length,
    dropped: events.length - kept.length,
    droppedMarks: (cast.marks || []).length - marks.length,
    cutAtMs: kept[kept.length - 1].t,
    sourceMs: events[events.length - 1].t,
    // The anchor was missing, so the marker search covered the ask as well. Worth saying out loud.
    searchedWholeCast: until != null && from < 0,
  };
}
