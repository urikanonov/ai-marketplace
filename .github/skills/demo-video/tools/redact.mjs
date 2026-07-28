// Redaction for demo captures. A recorded terminal session is published, so anything in it that a
// public clip must not carry - credentials, tokens, private keys, the operator's home path and
// account name - is scrubbed before it is ever written to disk.
//
// This is a SAFETY NET, not the gate. Pattern matching cannot understand a session, and a full-screen
// TUI can split or interleave text arbitrarily, so the tool always writes a plain transcript for a
// HUMAN to read and requires an explicit acknowledgement before it films anything. Treat a miss here
// as a bug worth a new rule, never as a reason to skip the review.

export const REDACTED = "[redacted]";

// Enough context to span the longest credential shape below, so a token cut in half by a PTY chunk
// boundary is still matched once the two halves are joined.
const CARRY = 256;
const MAX_BUFFER = 64 * 1024;

// Keyword-anchored assignments: `password: hunter2`, `AZURE_CLIENT_SECRET=...`, `SECRET_KEY=...`.
// The key is kept (it is what makes the clip readable) and only the VALUE is replaced. The keyword
// can sit ANYWHERE in the identifier - `AZURE_CLIENT_SECRET` has it at the end, `SECRET_KEY` and
// `DB_PASSWORD_PROD` do not - so the identifier is matched loosely on BOTH sides. Anchoring only at
// the tail (or relying on a leading `\b`, which never fires after `_`) misses how environment
// variables are really named. The negative lookahead stops an already-redacted value from being
// reported as a fresh finding.
const ASSIGNED = /\b[\w.-]*?(?:passwords?|passwd|pwd|secrets?|api[-_ ]?keys?|apikey|access[-_ ]?tokens?|auth[-_ ]?tokens?|refresh[-_ ]?tokens?|client[-_ ]?secrets?|tokens?|credentials?|account[-_ ]?keys?|shared[-_ ]?access[-_ ]?keys?|primary[-_ ]?keys?|secondary[-_ ]?keys?|connection[-_ ]?strings?)[\w.-]*?\b(\s*[:=]\s*)["']?(?!\[redacted\])[^\s"';,]{6,}["']?/gi;

// A PEM block is the one credential shape that spans lines, so the streaming scrubber has to treat
// it specially: everything else is guaranteed whitespace-free.
const PEM_BEGIN = /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/;
const PEM_END = /-----END [A-Z0-9 ]*PRIVATE KEY-----/;

// Ordered so the most specific shape wins; every rule is anchored on a literal marker rather than an
// entropy heuristic, because a git sha, a uuid and a build id all look "random" and must survive.
export const DEFAULT_RULES = [
  {
    name: "private-key-block",
    re: /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----/g,
    replace: () => REDACTED,
  },
  {
    // The most common credential in a real terminal is not an assignment at all: it is the userinfo
    // in a URL that git, npm or a proxy setting prints back at you. The user half is kept because it
    // is what makes the line readable; only the password is replaced.
    name: "url-credential",
    re: /(:\/\/[^\s/:@]+:)(?!\[redacted\])[^\s/:@]+@/g,
    replace: (_m, prefix) => `${prefix}${REDACTED}@`,
    unwrapSafe: true,
  },
  { name: "github-token", re: /\bgh[pousr]_[A-Za-z0-9_]{20,}/g, replace: () => REDACTED, unwrapSafe: true },
  { name: "github-fine-grained-token", re: /\bgithub_pat_[A-Za-z0-9_]{20,}/g, replace: () => REDACTED, unwrapSafe: true },
  { name: "openai-anthropic-key", re: /\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}/g, replace: () => REDACTED, unwrapSafe: true },
  { name: "aws-access-key-id", re: /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/g, replace: () => REDACTED, unwrapSafe: true },
  { name: "slack-token", re: /\bxox[abposr]-[A-Za-z0-9-]{10,}/g, replace: () => REDACTED, unwrapSafe: true },
  { name: "google-api-key", re: /\bAIza[0-9A-Za-z_-]{35}\b/g, replace: () => REDACTED, unwrapSafe: true },
  { name: "npm-token", re: /\bnpm_[A-Za-z0-9]{20,}/g, replace: () => REDACTED, unwrapSafe: true },
  { name: "pypi-token", re: /\bpypi-[A-Za-z0-9_-]{20,}/g, replace: () => REDACTED, unwrapSafe: true },
  {
    // An Azure SAS URL is a credential in a query string: the signature is the secret, and no
    // keyword rule sees it because `sig` is a URL parameter rather than an assignment.
    name: "azure-sas-signature",
    re: /([?&]sig=)(?!\[redacted\])[^\s&"']{10,}/gi,
    replace: (_m, prefix) => `${prefix}${REDACTED}`,
    unwrapSafe: true,
  },
  {
    // kubeconfig embeds a private key and a client certificate as base64 under fixed keys.
    name: "kubeconfig-data",
    re: /\b(client-key-data|client-certificate-data|certificate-authority-data)(\s*:\s*)(?!\[redacted\])\S{16,}/gi,
    replace: (_m, key, sep) => `${key}${sep}${REDACTED}`,
  },
  {
    name: "jwt",
    re: /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{2,}/g,
    replace: () => REDACTED,
    unwrapSafe: true,
  },
  {
    // The guard sits immediately after the colon and swallows the whitespace itself: written as
    // `(\s*:\s*)(?!\[redacted\])`, the separator could give the space back on backtracking and the
    // rule would happily re-redact its own output, reporting a finding forever.
    name: "authorization-header",
    re: /\b(authorization|proxy-authorization)(\s*:)(?!\s*\[redacted\](?:\s|$))\s*[^\r\n]+/gi,
    replace: (_m, key, colon) => `${key}${colon} ${REDACTED}`,
  },
  {
    name: "bearer-credential",
    re: /\b(bearer|basic)(\s+)(?!\[redacted\])[A-Za-z0-9._~+/=-]{12,}/gi,
    replace: (_m, scheme, sep) => `${scheme}${sep}${REDACTED}`,
  },
  {
    name: "assigned-secret",
    re: ASSIGNED,
    replace: (match, sep) => `${match.slice(0, match.indexOf(sep))}${sep}${REDACTED}`,
  },
  {
    // A cast can be captured by one person and rendered by another, and the machine-specific rules
    // below are built from whoever is RENDERING - so a foreign home path would sail through. This
    // covers the SHAPE of a home directory instead, which needs nobody's identity recorded anywhere.
    name: "home-directory-shape",
    re: /(\/home\/|\/Users\/|[A-Za-z]:\\Users\\)(?!demo\b)[^\s\\/:*?"<>|]+/g,
    replace: (_m, prefix) => `${prefix}demo`,
    // An identity rewrite is not an opaque blob: padding it to the original width would insert a
    // space inside a path (`/home/demo /.ssh/config`), which reads as two tokens and looks broken.
    pad: false,
  },
];

function escapeRe(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Machine-identifying rules are composed at call time, never baked into the defaults: they depend on
// who is recording. The home path keeps its SHAPE (only the account segment changes) so the clip
// still reads like a real session instead of a censored one.
export function homeRules({ home, user, homeLabel = "demo", userLabel = "demo" } = {}) {
  const rules = [];
  const normalized = home ? String(home).replace(/[\\/]+$/, "") : "";
  // A home of "/" (or "\") normalizes to the empty string, and an empty pattern matches at every
  // position - it would replace the gaps between every character and destroy the whole transcript.
  if (normalized) {
    const parent = normalized.slice(0, normalized.length - normalized.split(/[\\/]/).pop().length);
    const both = escapeRe(normalized).replace(/\\\\|\//g, "[\\\\/]");
    rules.push({
      name: "home-path",
      re: new RegExp(both, "gi"),
      replace: () => `${parent}${homeLabel}`,
      pad: false,
    });
  }
  if (user) {
    rules.push({
      name: "account-name",
      re: new RegExp(`\\b${escapeRe(String(user))}\\b`, "gi"),
      replace: () => userLabel,
      pad: false,
    });
  }
  return rules;
}

// A TUI colourises as it prints, so a credential routinely arrives with escape sequences INSIDE it
// (`ESC[32m` after the first few characters of a token). The terminal renders the token perfectly -
// a viewer reads it straight off the clip - but a byte-level regex sees two harmless fragments. So
// matching runs against the VISIBLE text, and the redaction is applied back to the raw bytes.
// Escape sequences fall into two classes that must be projected DIFFERENTLY.
//
// A STYLE escape (SGR) only paints; removing it rejoins a token a TUI colourised mid-way, which is
// what makes a painted credential matchable at all. Every OTHER escape MOVES or ERASES: removing one
// glues unrelated text together, so `Loading123<CSI 0G>ghp_...` - which renders as the token
// overwriting the progress line - would look like one long word and lose the token rule's leading
// word boundary. Movement escapes therefore project to a SPACE, which both breaks the glue and stays
// outside every credential shape.
const ANSI_STYLE = /^\u001b\[[0-9;:]*m$/;
const ANSI = /\u001b\[[0-?]*[ -/]*[@-~]|\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)|\u001b[@-Z\\-_]/g;
// The same, plus line breaks: used only for the pass that hunts credential shapes an application
// hard-wrapped across two lines.
const ANSI_OR_EOL = /\r\n|\r|\n|\u001b\[[0-?]*[ -/]*[@-~]|\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)|\u001b[@-Z\\-_]/g;

// Build a projection of the raw bytes plus, for every projected character, the index it came from,
// so a match found in the projection can be mapped back onto the bytes it covers. `dropNewlines`
// additionally joins wrapped lines, which is how a credential the APPLICATION hard-wrapped is
// matched at all - its bytes are not contiguous, but what the viewer reads is.
function project(raw, { dropNewlines = false } = {}) {
  const skip = dropNewlines ? ANSI_OR_EOL : ANSI;
  skip.lastIndex = 0;
  let plain = "";
  const map = [];
  let at = 0;
  for (const match of raw.matchAll(skip)) {
    for (let i = at; i < match.index; i++) { plain += raw[i]; map.push(i); }
    // A style escape is dropped (so a painted token rejoins); anything that moves or erases the
    // cursor becomes a space (so it can never glue two unrelated runs into one apparent token).
    if (!ANSI_STYLE.test(match[0]) && !/^[\r\n]+$/.test(match[0])) {
      plain += " ";
      map.push(match.index);
    }
    at = match.index + match[0].length;
  }
  for (let i = at; i < raw.length; i++) { plain += raw[i]; map.push(i); }
  map.push(raw.length);
  return { plain, map };
}

// xterm replays the stream into a GRID, so a replacement shorter than what it replaced pulls the
// rest of the line left and visibly breaks a boxed or column-aligned frame. Pad to the original
// width; never truncate, because safety wins over alignment.
function fitWidth(replacement, original) {
  return replacement.length < original.length
    ? replacement.padEnd(original.length, " ")
    : replacement;
}

function collectSpans(raw, rules, options) {
  const { plain, map } = project(raw, options);
  const spans = [];
  for (const rule of rules) {
    if (options.unwrapOnly && !rule.unwrapSafe) continue;
    rule.re.lastIndex = 0;
    for (const match of plain.matchAll(rule.re)) {
      const replacement = (rule.replace || (() => REDACTED))(...match);
      if (replacement === match[0]) continue;
      spans.push({
        rule: rule.name,
        start: map[match.index],
        // One past the LAST matched character, not `map[end]`: the map's final entry is a sentinel
        // for the end of the raw string, so a match that runs to the end of the projection would
        // otherwise swallow the trailing newline (and every control byte the projection dropped
        // after it) into the redacted span.
        end: map[match.index + match[0].length - 1] + 1,
        replacement: rule.pad === false ? replacement : fitWidth(replacement, match[0]),
      });
    }
  }
  return spans;
}

function applyRules(text, rules) {
  let out = text;
  for (const rule of rules) {
    rule.re.lastIndex = 0;
    out = out.replace(rule.re, (...args) => {
      const replaced = (rule.replace || (() => REDACTED))(...args);
      return rule.pad === false ? replaced : fitWidth(replaced, args[0]);
    });
  }
  return out;
}

// Replace the VISIBLE characters of a raw slice while re-emitting every control byte in place. A
// span found on the unwrapped projection can straddle a newline (that is the point - it is how a
// hard-wrapped token is matched), and splicing the replacement straight over it would delete the
// line break, costing the replay a terminal row and shifting everything after it up.
function spliceSpan(rawSlice, replacement) {
  ANSI_OR_EOL.lastIndex = 0;
  const controls = [...rawSlice.matchAll(ANSI_OR_EOL)];
  if (controls.length === 0) return replacement;
  let out = "";
  let taken = 0;
  let at = 0;
  for (const control of controls) {
    const visible = control.index - at;
    out += replacement.slice(taken, taken + visible);
    taken += visible;
    out += control[0];
    at = control.index + control[0].length;
  }
  return out + replacement.slice(taken);
}

// Overlapping spans are MERGED, never dropped. Two credentials separated only by a newline can each
// produce a span that reaches into the other on the unwrapped projection; skipping the second one
// left its tail in the clip - and, no longer looking like a token, it sailed past the gate too.
//
// Containment is kept distinct from partial overlap: an assignment span CONTAINS the token span
// inside it, and there the outer replacement wins so `GH_TOKEN=[redacted]` keeps the key that makes
// the clip readable. Only a partial overlap - two different credentials bleeding into each other -
// collapses to a single opaque redaction.
function mergeSpans(spans) {
  const sorted = [...spans].sort((a, b) => a.start - b.start || b.end - a.end);
  const merged = [];
  for (const span of sorted) {
    const last = merged[merged.length - 1];
    if (!last || span.start >= last.end) { merged.push({ ...span }); continue; }
    if (span.end <= last.end) continue; // fully contained: the outer replacement already covers it
    last.end = span.end;
    last.replacement = REDACTED;
    last.merged = true;
  }
  return merged;
}

// A shell sets the window title with an OSC sequence, and that title carries the executable path and
// the current working directory - the operator's home, in a real session. It is stripped from the
// PROJECTION like any other escape, so no rule ever sees inside it, while the raw bytes would still
// reach the cast and the transcript. The replay has no use for a window title, so it is removed
// from the stream outright before anything else runs.
const OSC_TITLE = /\u001b\][0-2];[^\u0007\u001b]*(?:\u0007|\u001b\\)/g;

export function scrubText(text, rules = DEFAULT_RULES) {
  const raw = String(text).replace(OSC_TITLE, "");
  // Two passes, both mapped back onto the raw bytes: the VISIBLE text (escapes handled, line
  // structure kept) with every rule, and the UNWRAPPED text (newlines removed too) with only the
  // rules whose shapes cannot contain whitespace. Running the line-oriented rules unwrapped would
  // let `[^\r\n]+` run away across the whole transcript and redact the entire clip.
  const spans = mergeSpans([
    ...collectSpans(raw, rules, {}),
    ...collectSpans(raw, rules, { dropNewlines: true, unwrapOnly: true }),
  ]);
  if (spans.length === 0) return raw;
  let out = "";
  let cursor = 0;
  for (const span of spans) {
    const original = raw.slice(span.start, span.end);
    const replacement = span.merged ? fitWidth(span.replacement, original) : span.replacement;
    out += raw.slice(cursor, span.start) + spliceSpan(original, replacement);
    cursor = span.end;
  }
  out += raw.slice(cursor);
  // A second pass over the spliced result catches any rule that only became matchable once the
  // spans were joined up.
  return applyRules(out, rules);
}

// Report what WOULD be redacted, without changing anything: used to gate rendering and to tell a
// reviewer what the net caught. Scans what the VIEWER would see, wrapped or painted.
export function scanText(text, rules = DEFAULT_RULES) {
  const raw = String(text).replace(OSC_TITLE, "");
  const spans = mergeSpans([
    ...collectSpans(raw, rules, {}),
    ...collectSpans(raw, rules, { dropNewlines: true, unwrapOnly: true }),
  ]);
  return spans.map((span) => ({ rule: span.rule, index: span.start }));
}

// The PEM markers are found through the same projection as everything else, then mapped back to raw
// offsets: a TUI that colourises the header (`-----BEGIN OPENSSH <SGR>PRIVATE KEY-----`) would
// otherwise slip past a raw-byte search, and the streaming scrubber would flush the body line by
// line straight into the cast.
function findPem(raw) {
  const { plain, map } = project(raw);
  const begin = plain.search(PEM_BEGIN);
  if (begin < 0) return { begin: -1, end: -1 };
  const endMatch = plain.slice(begin).match(PEM_END);
  if (!endMatch) return { begin: map[begin], end: -1 };
  return { begin: map[begin], end: map[begin + endMatch.index + endMatch[0].length] };
}

// A ConPTY hands output over in arbitrary slices, so a credential routinely straddles two chunks and
// a naive per-chunk scrub would pass both halves through. The scrubber holds back a tail until it
// can be split on whitespace - which no credential shape contains - so a token is never cut.
// The END marker on its own, for resuming after an oversized key was suppressed.
function findPemEnd(raw) {
  const { plain, map } = project(raw);
  const match = plain.match(PEM_END);
  if (!match) return -1;
  return map[match.index + match[0].length - 1] + 1;
}

// Is the whitespace run ending at `index` the JOIN of a hard-wrapped credential rather than a real
// break? A wrap join is a bare line break with token characters pressed against it on both sides.
// Splitting there flushes the first half before the unwrapped pass can see the whole token, and the
// second half then carries nothing token-shaped for the gate to catch.
const TOKEN_CHAR = /[A-Za-z0-9_.-]/;
function isWrapJoin(buffer, runStart, runEnd) {
  const run = buffer.slice(runStart, runEnd);
  if (!/^[\r\n]+$/.test(run)) return false;
  const before = buffer[runStart - 1];
  const after = buffer[runEnd];
  return Boolean(before) && Boolean(after) && TOKEN_CHAR.test(before) && TOKEN_CHAR.test(after);
}

export function createScrubber(opts = {}) {
  const rules = opts.rules || DEFAULT_RULES;
  const carry = opts.carry == null ? CARRY : opts.carry;
  let buffer = "";
  // Whitespace-free stretches are re-scanned on every push otherwise, which is quadratic exactly
  // when the stream is densest. Remember how far back is known to hold no whitespace.
  let scannedFloor = 0;
  // Set once an oversized key has been redacted at the cap: everything up to its END marker still
  // belongs to that key, and forgetting this let the rest of the body through as ordinary text.
  let suppressingPem = false;
  return {
    push(chunk) {
      buffer += String(chunk);
      if (suppressingPem) {
        const end = findPemEnd(buffer);
        if (end < 0) {
          // Still inside the key: keep nothing, emit nothing.
          if (buffer.length > MAX_BUFFER) buffer = buffer.slice(-CARRY);
          return "";
        }
        buffer = buffer.slice(end);
        suppressingPem = false;
      }
      if (buffer.length <= carry) return "";
      const limit = buffer.length - carry;

      // A PEM block is the one credential that contains whitespace, so splitting on whitespace would
      // emit BEGIN in one flush and END in another and match neither half. The markers are located
      // through the PROJECTION, so a colourised header cannot slip past the hold.
      const pem = findPem(buffer);
      if (pem.begin >= 0) {
        if (pem.end < 0) {
          // Hold the whole block until its END arrives, or the cap forces a decision.
          if (buffer.length < MAX_BUFFER) return "";
          // A key too large to buffer must not be emitted in the clear: redact from BEGIN onward and
          // stay suppressed until the END marker turns up.
          const head = scrubText(buffer.slice(0, pem.begin), rules) + REDACTED;
          buffer = "";
          scannedFloor = 0;
          suppressingPem = true;
          return head;
        }
        // The block is complete: emit everything up to and including it as ONE piece, so the
        // multi-line rule sees the whole block rather than a whitespace-split fragment of it.
        const head = scrubText(buffer.slice(0, pem.end), rules);
        buffer = buffer.slice(pem.end);
        scannedFloor = 0;
        return head;
      }

      let split = -1;
      for (let i = limit - 1; i >= scannedFloor; i--) {
        if (!/\s/.test(buffer[i])) continue;
        let runEnd = i + 1;
        let runStart = i;
        while (runStart > 0 && /\s/.test(buffer[runStart - 1])) runStart -= 1;
        if (isWrapJoin(buffer, runStart, runEnd)) { i = runStart; continue; }
        split = runEnd;
        break;
      }
      if (split <= 0) {
        // Output with no whitespace at all must not grow the buffer without bound. Past the cap,
        // scrub the WHOLE buffer first so no credential is straddling the cut, then emit.
        if (buffer.length < MAX_BUFFER) { scannedFloor = Math.max(0, limit); return ""; }
        buffer = scrubText(buffer, rules);
        const keep = Math.min(carry, buffer.length);
        const head = buffer.slice(0, buffer.length - keep);
        buffer = buffer.slice(buffer.length - keep);
        scannedFloor = 0;
        return head;
      }
      const head = buffer.slice(0, split);
      buffer = buffer.slice(split);
      scannedFloor = 0;
      return scrubText(head, rules);
    },
    end() {
      const rest = buffer;
      buffer = "";
      scannedFloor = 0;
      // Still inside an oversized key at end of stream: nothing after its BEGIN may be emitted.
      if (suppressingPem) {
        suppressingPem = false;
        const end = findPemEnd(rest);
        return end < 0 ? "" : scrubText(rest.slice(end), rules);
      }
      return rest ? scrubText(rest, rules) : "";
    },
  };
}

// Scrub a whole captured cast. Event COUNT and TIMINGS are preserved so the replay keeps the rhythm
// of the real session; only the text moves (a held-back tail lands on the next event, and the final
// flush on the last one). The returned transcript is exactly what the clip will show, so the human
// review and the video can never disagree.
export function scrubEvents(events, opts = {}) {
  if (!Array.isArray(events)) throw new Error("scrubEvents needs an array of events");
  const scrubber = createScrubber(opts);
  const out = events.map((event) => ({ ...event, data: scrubber.push(event.data) }));
  const tail = scrubber.end();
  if (tail) {
    if (out.length === 0) return { events: [], transcript: "", redactions: 0, findings: [] };
    out[out.length - 1].data += tail;
  }
  const transcript = out.map((e) => e.data).join("");
  const source = events.map((e) => String(e.data)).join("");
  const findings = scanText(source, opts.rules || DEFAULT_RULES);
  return { events: out, transcript, redactions: findings.length, findings };
}
