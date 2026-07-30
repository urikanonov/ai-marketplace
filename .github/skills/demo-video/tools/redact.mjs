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
// `DB_PASSWORD_PROD` do not - so the keyword is looked for INSIDE the identifier rather than
// anchored to either end.
//
// The identifier is matched ONCE, greedily, and the keyword test happens afterwards in `replace`.
// The previous shape wrapped the keyword alternation in two unbounded lazy runs
// (`[\w.-]*?...[\w.-]*?`), which made the engine retry the whole alternation from every offset of
// every long word-character run: quadratic, and measured at 2.9s for 144KB of `password_` repeated,
// on a rule the safety gate runs over the WHOLE uncompressed session. A cast is megabytes.
//
// The key may contain SPACES, because several of the keywords do (`api key`, `shared access key`,
// `connection string`). A first attempt used a single `[\w.-]` class and silently stopped catching
// every space-separated key - the kind of regression that shows up as a credential in a published
// video, not as a failing test - so the word groups are matched explicitly and bounded.
const ASSIGNED_KEYWORD = /passwords?|passwd|pwd|secrets?|api[-_ ]?keys?|apikey|access[-_ ]?tokens?|auth[-_ ]?tokens?|refresh[-_ ]?tokens?|client[-_ ]?secrets?|tokens?|credentials?|account[-_ ]?keys?|shared[-_ ]?access[-_ ]?keys?|primary[-_ ]?keys?|secondary[-_ ]?keys?|connection[-_ ]?strings?/i;
// Every assignment separator is examined, from the left, and the key is read BACKWARDS from it.
// That is what catches a credential nested inside another assignment: with plain `matchAll` a benign
// outer assignment swallowed its whole value and the engine resumed past it, so
// `env=DB_PASSWORD_PROD=swordfish` and `...?format=json&access_token=abc` scanned CLEAN.
//
// Everything here is deliberately character-at-a-time rather than regex. `\s*[:=]\s*` looks
// harmless but retries its leading `\s*` at every position, which made 80K of spaces take 32
// seconds - the same class of hang the rewrite existed to remove. And the key is grown one word
// group at a time until it NAMES a secret, so the shortest suffix wins: a 250-character variable
// name is still read in full (no arbitrary look-back window), while `API_KEY=x client_secret=y`
// keeps its two keys separate instead of swallowing everything between them.
const KEY_CHAR = /[\w.-]/;
const IS_SPACE = /\s/;
// `&` ends a value: a token in a URL query string must not eat the parameters that follow it.
const VALUE_END = /[\s"';,&]/;
// And a value is BOUNDED. The unwrapped pass (which exists so a hard-wrapped token still matches)
// removes bare newlines with nothing in their place, so consecutive lines are glued together - and
// an unbounded value scan then runs from every keyword separator to the end of the joined
// transcript. That is O(n) per separator over O(n) separators: an env dump of 4000 assignment lines
// took 11.6 SECONDS to scan, it collapsed every following line into one runaway redaction (deleting
// them from the transcript the reviewer is shown, and counting three secrets as one), and the
// resulting fragmented marker made the gate refuse the tool's own correctly-scrubbed cast.
// No real credential is longer than this, and a wrapped one spans a line or two at most.
const MAX_VALUE = 512;
const MAX_KEY_GROUPS = 5;

function readKey(plain, sepStart) {
  let start = sepStart;
  for (let groups = 0; groups < MAX_KEY_GROUPS; groups++) {
    let word = start;
    while (word > 0 && KEY_CHAR.test(plain[word - 1])) word -= 1;
    if (word === start) return null;
    start = word;
    const candidate = plain.slice(start, sepStart);
    if (ASSIGNED_KEYWORD.test(candidate)) return { key: candidate, start };
    // Several keywords are written with spaces (`api key`, `shared access key`), so one space may
    // be crossed to keep looking leftwards.
    if (start > 0 && plain[start - 1] === " ") start -= 1;
    else return null;
  }
  return null;
}

function* findAssignments(plain, { joins } = {}) {
  for (let i = 0; i < plain.length; i++) {
    const ch = plain[i];
    if (ch !== ":" && ch !== "=") continue;
    let sepStart = i;
    while (sepStart > 0 && IS_SPACE.test(plain[sepStart - 1])) sepStart -= 1;
    let sepEnd = i + 1;
    while (sepEnd < plain.length && IS_SPACE.test(plain[sepEnd])) sepEnd += 1;

    const found = readKey(plain, sepStart);
    if (!found) continue;

    let valueStart = sepEnd;
    const quote = plain[valueStart] === '"' || plain[valueStart] === "'" ? plain[valueStart] : null;
    if (quote) valueStart += 1;
    let valueEnd = valueStart;
    const limit = Math.min(plain.length, valueStart + MAX_VALUE);
    while (valueEnd < limit && !VALUE_END.test(plain[valueEnd])) valueEnd += 1;
    const value = plain.slice(valueStart, valueEnd);
    if (value.length < 6) continue;
    // Already scrubbed: re-reporting it would make the gate refuse a cast this tool just cleaned.
    if (value.toLowerCase().startsWith("[redacted]")) continue;

    let end = valueEnd;
    if (quote && plain[end] === quote) end += 1;
    const text = plain.slice(found.start, end);
    yield Object.assign([text, found.key, plain.slice(sepStart, sepEnd), value], {
      index: found.start,
      input: plain,
    });
    // Resume after the SEPARATOR, not after the value, so a nested assignment is still examined.
    i = sepEnd - 1;
  }
}

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
    unwrapSafe: true,
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
    // rule would happily re-redact its own output, reporting a finding forever. It also must not
    // require whitespace AFTER the marker - a redacted value quoted in a transcript
    // (`'Authorization: [redacted]'`) is followed by a quote, and demanding whitespace there made
    // scrubbing non-idempotent, so the render gate tripped on text this tool had already cleaned.
    name: "authorization-header",
    re: /\b(authorization|proxy-authorization)(\s*:)(?!\s*\[redacted\])\s*[^\r\n]+/gi,
    replace: (_m, key, colon) => `${key}${colon} ${REDACTED}`,
  },
  {
    name: "bearer-credential",
    re: /\b(bearer|basic)(\s+)(?!\[redacted\])[A-Za-z0-9._~+/=-]{12,}/gi,
    replace: (_m, scheme, sep) => `${scheme}${sep}${REDACTED}`,
    // The credential half contains no whitespace, so running this over the unwrapped projection
    // cannot make it run away - and that is what catches one the application wrapped mid-value.
    unwrapSafe: true,
  },
  {
    name: "assigned-secret",
    find: findAssignments,
    replace: (match, key, sep) => `${key}${sep}${REDACTED}`,
    // The VALUE half stops at whitespace, so unwrapping cannot make this rule run away across the
    // transcript the way a line-oriented one would - and a wrapped value is exactly the case that
    // otherwise leaves its continuation sitting on the next line.
    unwrapSafe: true,
  },
  {
    // A cast can be captured by one person and rendered by another, and the machine-specific rules
    // below are built from whoever is RENDERING - so a foreign home path would sail through. This
    // covers the SHAPE of a home directory instead, which needs nobody's identity recorded anywhere.
    name: "home-directory-shape",
    // Windows paths turn up in three forms in one session: native `C:\Users\name`, forward-slash
    // `C:/Users/name` (git, node, anything that prints a URL-ish path), and MSYS `/c/Users/name`.
    // Matching only the backslash form let the other two carry an account name into the clip.
    re: /(\/home\/|\/Users\/|[A-Za-z]:[\\/]Users[\\/]|\/[A-Za-z]\/Users\/)(?!demo\b)[^\s\\/:*?"<>|]+/g,
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
  const matches = [...raw.matchAll(skip)];
  // A hard wrap in a real TUI is not a bare newline: the emulator brackets it with cursor and
  // erase sequences, so a credential broken across two lines looks like
  // `...MNOP` ESC[K \n `QRST...`. Mapping every movement escape to a SPACE (which stops unrelated
  // runs being glued into one apparent token) also split the token in the very projection whose
  // job is to rejoin it - so the token matched nothing, scrubbed to nothing, and the gate reported
  // zero findings while both halves stayed legible in the clip.
  //
  // So in the unwrapped projection a RUN of adjacent escapes that contains a newline and is
  // flanked by token characters is dropped whole: that shape is a wrap and nothing else. Any other
  // movement escape still becomes a space, which is what keeps the anti-gluing guarantee.
  const dropWhole = new Set();
  if (dropNewlines) {
    for (let i = 0; i < matches.length;) {
      let end = i;
      let hasEol = /^[\r\n]+$/.test(matches[i][0]);
      while (end + 1 < matches.length
        && matches[end + 1].index === matches[end].index + matches[end][0].length) {
        end += 1;
        if (/^[\r\n]+$/.test(matches[end][0])) hasEol = true;
      }
      const before = raw[matches[i].index - 1];
      const after = raw[matches[end].index + matches[end][0].length];
      if (hasEol && before && after && TOKEN_CHAR.test(before) && TOKEN_CHAR.test(after)) {
        for (let k = i; k <= end; k++) dropWhole.add(k);
      }
      i = end + 1;
    }
  }
  // The projection is built from SLICES and its offset map lives in a typed array. Appending one
  // character at a time and pushing one boxed number per character cost roughly 40x the input in
  // heap - on a rule set the safety gate runs over a whole multi-megabyte session, that made
  // finalisation the thing most likely to run out of memory and lose the recording.
  const parts = [];
  const map = new Int32Array(raw.length + 1);
  // Where a line break was removed to rejoin the text. A rule that scans forward needs to know:
  // without it a value runs from one assignment straight through every line that follows.
  const joins = [];
  let mapped = 0;
  const keep = (from, to) => {
    if (to > from) parts.push(raw.slice(from, to));
    for (let i = from; i < to; i++) map[mapped++] = i;
  };
  let at = 0;
  for (const [index, match] of matches.entries()) {
    keep(at, match.index);
    // A style escape is dropped (so a painted token rejoins); anything that moves or erases the
    // cursor becomes a space (so it can never glue two unrelated runs into one apparent token).
    if (!dropWhole.has(index) && !ANSI_STYLE.test(match[0]) && !/^[\r\n]+$/.test(match[0])) {
      parts.push(" ");
      map[mapped++] = match.index;
    }
    else if (dropNewlines) joins.push(mapped);
    at = match.index + match[0].length;
  }
  keep(at, raw.length);
  map[mapped] = raw.length;
  return { plain: parts.join(""), map, joins: new Set(joins) };
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
  const { plain, map, joins } = project(raw, options);
  const spans = [];
  for (const rule of rules) {
    if (options.unwrapOnly && !rule.unwrapSafe) continue;
    // A rule may bring its own scanner. `matchAll` resumes AFTER each match, which is wrong for a
    // rule whose match can CONTAIN another candidate - see findAssignments.
    const matches = rule.find ? rule.find(plain, { joins }) : (rule.re.lastIndex = 0, plain.matchAll(rule.re));
    for (const match of matches) {
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
    // A rule with its own scanner is applied by SPAN, from the right, so earlier offsets stay valid.
    if (rule.find) {
      const found = [...rule.find(out)];
      for (let i = found.length - 1; i >= 0; i--) {
        const match = found[i];
        const replaced = (rule.replace || (() => REDACTED))(...match);
        const text2 = rule.pad === false ? replaced : fitWidth(replaced, match[0]);
        out = out.slice(0, match.index) + text2 + out.slice(match.index + match[0].length);
      }
      continue;
    }
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
// the current working directory - the operator's home, in a real session. Every OSC sequence is
// stripped, not just the title ones: the projection's ANSI regex consumes the whole body of ANY OSC
// and projects it to a single space, so no rule can ever match inside one, while the raw bytes still
// reach the cast and the transcript. OSC 7 reports the CWD and OSC 8 carries a hyperlink target
// (which can hold a URL password) - both are emitted by default by modern shells, and both were
// invisible to the gate. The replay has no use for any of them.
const OSC_ANY = /\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)/g;

export function scrubText(text, rules = DEFAULT_RULES) {
  const raw = String(text).replace(OSC_ANY, "");
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
  const raw = String(text).replace(OSC_ANY, "");
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
// break? A wrap join is a bare line break with credential characters pressed against it on both
// sides. The class has to span every shape the rules match - base64 and URL-safe values carry `+`,
// `/`, `=`, `%` and `~` as well as the usual identifier characters - or a value that wraps after one
// of those is flushed early and its tail escapes.
const TOKEN_CHAR = /[A-Za-z0-9_.~!$&*+/=%-]/;
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
