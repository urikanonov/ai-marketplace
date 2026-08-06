/* ---------- Export Offline (shareable + zero-network rich-content embedding) ---------- */
// Whether a document uses Chart.js is decided on a deliberately LOOSE signal: any mention of the
// `Chart` global. The two failure directions are not symmetric - a false positive inlines a library
// the document did not need (bytes), a false negative ships a chart that never renders - so this
// errs toward inlining, and it also catches indirect construction (`const C = window.Chart;
// new C(...)`, `new (Chart)(...)`, destructuring) that a literal `new Chart(` test would miss. The
// same signal keeps such a script out of the loader strip and hoists it below the inlined library,
// so provisioning and ordering can never disagree. It is read from the document BEFORE any script
// is stripped, so a script the loader strip removes cannot take the evidence with it.
const _OFFLINE_CHART_GLOBAL_RE = /\bChart\b/;
// The narrower "this script CONSTRUCTS a chart" signal. Hoisting is still keyed on it for scripts
// anywhere in the document, because the authoring validator requires chart init to sit after the
// layer's JS region (so Save-as-plain preserves the chart) - and because moving an in-content script
// changes the text offsets the comment anchors are measured against, so the move must stay rare and
// deliberate rather than firing on any mention of the global.
const _OFFLINE_CHART_CTOR_RE = /\bnew\s+(?:Chart|(?:window|globalThis|self)\.Chart)\s*\(/;
// The review layer's own script ships inside every exported document and its source text mentions
// "Chart.js" (the third-party notice it emits), so every content scan must skip it or it matches
// every document. The strip below keeps its historical broad signature (skipping too much there only
// leaves a script alone), but the EVIDENCE scan skips on a much narrower one - the layer's own
// version declaration, plus its position outside the authored content root - because there a wrong
// skip means a dropped library. `__commentableHtmlReady` is a documented public hook and
// `COMMENT_KEY = ` is generic, so an author script may legitimately contain either.
const _OFFLINE_LAYER_SCRIPT_RE = /__commentableHtmlReady|const CMH_VERSION|COMMENT_KEY = /;
const _OFFLINE_LAYER_DECL_RE = /const CMH_VERSION\s*=/;
// A script THIS exporter inlined on an earlier pass, recognized by the marker AND a value the
// exporter itself emits - so an authored script that carries the attribute for its own bookkeeping
// is neither deleted nor excluded from the evidence scan.
function _offlineIsInlinedLibScript(s) {
  const lib = s.getAttribute("data-cmh-offline-lib") || s.getAttribute("data-cmh-offline-lib-init") || "";
  return lib === "chartjs" || lib === "mermaid";
}
// The HTML "JavaScript MIME type" set: a legacy type such as `text/ecmascript` still executes, so a
// content scan that ignored it would miss real code. The trim is HTML's own ASCII whitespace class,
// written as literal code points rather than left to `trim()`, because the two engines' defaults
// disagree in BOTH directions and this predicate now decides whether a `src` is a LOAD: JS `trim()`
// also takes NBSP and U+FEFF while Python's `str.strip()` also takes U+001C-U+001F, so a
// `type="&#xFEFF;text/javascript"` was runnable to the exporter and inert to the gate (the export
// deleted an element the gate had just blessed) and a U+001C-padded one was the reverse. A browser
// trims ASCII whitespace only, so both of those are DATA BLOCKS and both sides now say so.
function _offlineIsRunnableScriptType(type) {
  const t = String(type || "").split(";")[0].replace(/^[\t\n\f\r ]+|[\t\n\f\r ]+$/g, "").toLowerCase();
  return _offlineIsJsTypeEssence(t);
}
// The set membership on its own, shared so the type-only predicate above and the element-level one
// below can never disagree about WHICH strings name JavaScript while they deliberately disagree
// about how the attribute is normalized into one.
function _offlineIsJsTypeEssence(t) {
  if (!t || t === "module") return true;
  return /^(?:text|application)\/(?:x-)?(?:java|ecma)script$/.test(t) ||
    /^text\/(?:javascript1\.[0-5]|jscript|livescript)$/.test(t);
}
// HTML folds ASCII only. `toLowerCase()` is Unicode-aware, so a look-alike that folds onto an ASCII
// letter would make a type a browser never matches look runnable - the fail-OPEN direction for the
// predicate below, and a divergence from the validator's `_ascii_lower` besides.
function _offlineAsciiLower(value) {
  return String(value == null ? "" : value).replace(/[A-Z]/g, function (c) {
    return String.fromCharCode(c.charCodeAt(0) + 32);
  });
}
function _offlineTrimHtmlWs(value) {
  return String(value == null ? "" : value).replace(/^[\t\n\f\r ]+|[\t\n\f\r ]+$/g, "");
}
// Whether a browser would run THIS `<script>` element's code at all - HTML's "prepare the script
// element" reduced to the questions a static reader can answer, and the exporter half of a pair
// pinned to the strict validator's `script_code_runs` by
// `test_the_python_and_js_script_code_runs_predicates_agree`, which evaluates THIS function in a
// real JS engine over a shared corpus of ATTRIBUTE SETS.
//
// It is deliberately NARROWER than `_offlineIsRunnableScriptType` above, and the split is by what
// the caller does with the answer (issue #1171). A caller that DELETES an element, or that decides
// whether a `src` is a real load, must be exact: the type string has to be a whole essence match, so
// a MIME PARAMETER defeats it (`type="text/javascript; charset=utf-8"` executes in no modern
// browser), and `nomodule`, the legacy `event`+`for` pair, a whitespace-only `type` and the
// `language` fallback all decide it too. Calling one of those runnable cost an author the whole
// element and its body for code no browser ran. A caller that only SCANS an inline body for egress
// keeps the broader predicate, where over-inclusion is the safe direction - a body it skips is a
// network import nobody looked at.
//
// The branches are HTML's, not a simplification of them:
// - an ABSENT `type` takes the `language` fallback (HTML only, and NOT trimmed: the block type is
//   the concatenation of `text/` with the raw attribute value), an explicitly EMPTY one is classic,
//   and any other value is trimmed of ASCII whitespace and must be a whole essence match. The
//   asymmetry between `type=""` and `type=" "` is the algorithm's own: the raw value is tested
//   against the empty string BEFORE it is stripped, so only a literally empty one is classic.
// - `nomodule`, and the legacy `event`+`for` pair, are HTMLScriptElement attributes and only apply
//   on the CLASSIC branch in the HTML namespace. An SVG script carrying one still runs, so reading
//   them there would delete a script that works.
function _offlineScriptCodeRuns(s) {
  const htmlNs = !s.namespaceURI || s.namespaceURI === _OFFLINE_HTML_NS;
  const raw = s.getAttribute("type");
  let block;
  if (raw === null || raw === undefined) {
    const lang = htmlNs ? (s.getAttribute("language") || "") : "";
    block = lang ? "text/" + _offlineAsciiLower(lang) : "";
  } else if (raw === "") {
    block = "";
  } else {
    block = _offlineAsciiLower(_offlineTrimHtmlWs(raw));
    if (!block) return false;
  }
  if (!_offlineIsJsTypeEssence(block)) return false;
  if (block === "module" || !htmlNs) return true;
  if (s.hasAttribute("nomodule")) return false;
  if (s.hasAttribute("event") && s.hasAttribute("for")) {
    const target = _offlineAsciiLower(_offlineTrimHtmlWs(s.getAttribute("for")));
    const evt = _offlineAsciiLower(_offlineTrimHtmlWs(s.getAttribute("event")));
    return target === "window" && (evt === "onload" || evt === "onload()");
  }
  return true;
}
// Two script types that are ACTIVE without being JavaScript, so the predicate above never looked at
// either. They get DIFFERENT rules because their risk is not the same shape.
//
// `speculationrules` is removed OUTRIGHT. It exists only to make the browser fetch something early,
// it shows a reader nothing, and it needs no URL literal at all to reach the network: a
// `"source": "document"` ruleset prefetches the links the document already carries, so any
// URL-shaped test is the wrong tool for it. A single-file offline export has nothing to pre-warm.
//
// `importmap` has a legitimate local use - it makes a relative module graph resolve - so it is
// removed only when it carries a reference the file cannot resolve on its own. That is decided by
// PARSING the JSON rather than scanning its text, because JSON spells the same URL many ways
// (`\/`, `\u002f`, leading whitespace, an embedded tab the URL parser strips) and a text scan closes
// one spelling while leaving the rest. Every string in the parsed value counts - KEY as well as
// value, since an import map's `imports` and `scopes` keys are references too - and a reference is
// non-local when it carries a scheme (not only `https:`: `data:` and `blob:` map a bare specifier
// onto code the document did not contain) or an authority prefix. A body that is not valid JSON is
// removed as well: a browser hard-fails such a map, so failing closed loses nothing. A `src` removes
// the block too - an external ruleset or map is unreviewable and cannot be self-contained. The
// strict validator mirrors the type list and the pattern (`OFFLINE_ACTIVE_DATA_TYPES` /
// `OFFLINE_NONLOCAL_REF_RE`), pinned by a parity test that runs the real engine.
const _OFFLINE_ACTIVE_DATA_TYPES = ["importmap", "speculationrules"];
// These two are HTML KEYWORD types, not MIME types, so a browser matches them exactly after
// trimming ASCII whitespace - `importmap;charset=utf-8` is inert data. Splitting on `;` here would
// delete an author's inert block, which this repo treats as the costlier error.
function _offlineActiveDataScriptType(type) {
  const t = String(type || "").replace(/^[\t\n\f\r ]+|[\t\n\f\r ]+$/g, "").toLowerCase();
  return _OFFLINE_ACTIVE_DATA_TYPES.indexOf(t) !== -1 ? t : "";
}
// Mirrors the URL parser's own input cleanup - it strips ASCII tab and newline ANYWHERE and leading
// C0-or-space - so neither a padded nor a tab-split spelling can pass itself off as relative. The
// authority prefix accepts a BACKSLASH as well as a slash in either position, because for a special
// scheme the parser's relative and relative-slash states treat the two alike, so a reference
// beginning with any two of them resolves to a network (or, from a `file:` document, a UNC)
// authority. Every character class is spelled out because `\s`/`\w` mean different things in the JS
// and Python engines, the same reason the navigation pattern below spells its whitespace out.
const _OFFLINE_NONLOCAL_REF_RE = /^(?:[A-Za-z][A-Za-z0-9+.\-]*:|[\/\\][\/\\])/;
function _offlineIsNonLocalRef(value) {
  const s = String(value).replace(/[\t\n\r]/g, "").replace(/^[\x00-\x20]+/, "");
  return _OFFLINE_NONLOCAL_REF_RE.test(s);
}
function _offlineJsonHasNonLocalRef(value) {
  if (typeof value === "string") return _offlineIsNonLocalRef(value);
  if (Array.isArray(value)) return value.some(function (v) { return _offlineJsonHasNonLocalRef(v); });
  if (value && typeof value === "object") {
    return Object.keys(value).some(function (k) {
      return _offlineIsNonLocalRef(k) || _offlineJsonHasNonLocalRef(value[k]);
    });
  }
  return false;
}
function _offlineActiveDataBlockIsRemovable(type, el) {
  if (type === "speculationrules") return true;
  if (el.hasAttribute("src")) return true;
  // The WALK sits inside the same guard as the parse: a body nested deeply enough to exhaust the
  // stack must fail closed like an unparseable one, not throw an engine message out of the export.
  try { return _offlineJsonHasNonLocalRef(JSON.parse(el.textContent || "")); }
  catch (e) { return true; }
}
// The MIT notice wording is single-sourced here because THREE places must agree on it byte for
// byte - the emitter, the re-export strip that removes a previous pass's notice, and the capture
// that reads one back. Wording that drifted in one of them used to fail silently: the strip would
// stop pruning (notices accumulate) or the capture would miss (the license is dropped from the
// re-export, breaking the MIT redistribution requirement).
const _OFFLINE_LIB_NOTICE_LEAD = "Third-party notice - ";
const _OFFLINE_LIB_NOTICE_TAIL = " is bundled inline for offline use under the MIT License:";
function _offlineReEscape(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
const _OFFLINE_LIB_NOTICE_ANY_RE = new RegExp(
  _offlineReEscape(_OFFLINE_LIB_NOTICE_LEAD) + "[^\\n]*" + _offlineReEscape(_OFFLINE_LIB_NOTICE_TAIL));
// Tolerate CRLF: an offline file re-saved by a Windows editor carries `\r\n`, and a notice that no
// longer matched would be silently dropped from the next export rather than travelling with the
// bytes it licenses.
const _OFFLINE_LIB_NOTICE_RE = new RegExp(
  "^\\s*" + _offlineReEscape(_OFFLINE_LIB_NOTICE_LEAD) + "(\\S+)"
  + _offlineReEscape(_OFFLINE_LIB_NOTICE_TAIL) + "\\r?\\n([\\s\\S]*)$");
const _OFFLINE_LIB_NOTICE_KEYS = { "Chart.js": "chartjsLicense", mermaid: "mermaidLicense" };
function _offlineDocFromHtml(html) {
  return new DOMParser().parseFromString(String(html || ""), "text/html");
}
function _serializeOfflineDoc(doc) {
  return "<!DOCTYPE html>\n" + cmhSerializeElement(doc.documentElement);
}
// A network URL in an attribute value, read AFTER the URL parser's own input cleanup (see
// `_offlineNormalizeUrlValue`), so the spellings a browser normalizes into a network load - an
// embedded ASCII tab or newline, a backslash authority - are not read as relative references. The
// character ranges are written out as literal code points because the strict validator carries
// an INDEPENDENT Python copy of this predicate (`NETWORK_URL_RE`) and the two engines do not agree
// about what `\s` means (Python's is Unicode-aware and matches U+001C-U+001F; JS's excludes them but
// includes U+FEFF). A drift is the CMH-OFFLINE-04 failure mode - the gate blesses a file this strip
// would have cleaned, or rejects one the exporter just produced.
function _offlineNormalizeUrlValue(v) {
  // Three cleanups, all of them the URL parser's own: strip leading and trailing C0-or-space,
  // remove ASCII tab/LF/CR from anywhere, and map every backslash onto a slash (for a special
  // scheme the parser's relative and authority-slash states treat the two alike, so
  // `https:/\host/x.js` and `\\host/x.js` both open an authority and really do fetch).
  return String(v || "")
    .replace(/[\u0009\u000a\u000d]/g, "")
    .replace(/^[\u0000-\u0020]+/, "")
    .replace(/[\u0000-\u0020]+$/, "")
    .replace(/\\/g, "/");
}
// An explicit `file:` authority counts as a network load: on Windows `file://host/x.js` is an SMB
// fetch off the machine. How many separators open that authority is NOT "two or more" - a real
// Chromium (checked, not assumed) reads exactly two OR four-or-more as an authority, while THREE is
// the empty host of an ordinary local path (`file:///C:/x`), so `file:////host/x.js` really
// does fetch and a `(?!/)` test alone called it local. Two host spellings that stay on the machine
// are excluded whatever the separator count: `localhost` - in every PERCENT-ENCODED and CASE
// spelling, see `_OFFLINE_PCT_LOCALHOST` below for what that does and does not cover -
// and a Windows DRIVE LETTER, which the file-host state turns into a path rather than a host,
// because reporting either would delete an author's local reference and make the gate reject a file
// with no egress. The percent-tolerance is right for the FOUR-or-more-slash arm too, even though
// there is no host there to decode: that arm's UNC name comes out of the PATH, and a real Chromium
// was measured percent-decoding a `file:` path before it touches the filesystem (a directory named
// `loc alhost` opened through `loc%20alhost`), so `file:////local%68ost/x.js` reaches the same local
// name that `file:////localhost/x.js` does. The drive-letter test deliberately does NOT require a separator after the `:` or
// `|`: a real Chromium resolves EVERY `file://` authority that STARTS with one to a local drive
// path, so `file://C:/x`, `file://C:foo/x` and even `file://c:not-a-host/x` are all the local file
// `file:///C:/...` with an empty host, and demanding the separator over-detected the last two.
// A TRAILING DOT is deliberately outside the localhost exclusion, and that is the parser-faithful
// reading rather than an accepted over-detection: the file-host state special-cases the exact string
// `localhost`, and `localhost.` is not it, so `file://localhost./x` keeps a NON-EMPTY host (checked:
// the href stays `file://localhost./x`) and on Windows resolves to the SMB path `\\localhost.\x` -
// the same call the scheme-relative `\\localhost\C$\x` gets, since an authority-bearing share is
// egress even to the loopback. Percent-encoding cannot reach the DRIVE-LETTER exclusion the way it
// reaches the host one: that test reads the raw buffer the file-host state reads, and `%3A`/`%7C`
// decode to forbidden host code points that fail to parse at all.
// The `(?!/)` after the long run stops the engine BACKTRACKING out of those exclusions: a greedy
// `/{4,}` alone matches five slashes, fails the `localhost` lookahead, gives a slash back and then
// matches on the four-slash reading, so `file://///localhost/x` (local) came out network.
// Every arm also requires a NON-EMPTY authority: one terminated at once by `?`, `#` or the end of
// the value fetches nothing (a special scheme cannot even parse it), so `//?q`, `https://` and the
// Windows extended-length path `\\?\C:\x` - which the backslash mapping turns into `//?/C:/x` - are
// left alone rather than stripped out of an author's document.
// The http/https arm CONSUMES the slash run after the scheme rather than counting it, so the
// scheme-only `https:host/x.js` and single-slash `https:/host/x.js` - which the special-authority
// states resolve to the same host as `https://host/x.js` - are network URLs here too, and one host
// character is required so an empty authority stays local. That widening moved with the CSS strips
// below and the validator's copies of all three, both sides at once (issue #961).
// The scheme set is CLOSED at http/https, scheme-relative and `file:`, and that is EVIDENCE rather
// than an omission: from a `file:` document a current Chromium produces no connection at all for
// `ftp:`, `ws:`, `wss:`, `filesystem:` or a custom scheme with no registered handler, through any
// automatic subresource channel this strip covers. Widening would therefore buy no egress protection
// while DELETING an author's reference - the same over-detection trade the `localhost` and
// drive-letter exclusions make. The measurement, its limits (a scripted `WebSocket`, which no
// attribute can carry and `connect-src 'none'` closes; a REGISTERED protocol handler; DNS-only
// `preconnect`/`dns-prefetch`; engines other than Chromium; and the durable backstop for a file
// already on disk, which is the export's own zero-network CSP rather than this predicate. Recorded
// in the CMH-OFFLINE-04 spec row with the tests that re-run them; `tests/test_vendored_libs.py`
// holds this predicate and the validator's to the same verdicts, so a widening has to move both
// sides at once.
// `localhost` as the URL PARSER compares a file host, not as a literal: the parser percent-decodes
// the host and lowercases it through domain-to-ASCII BEFORE the file-host state turns the exact
// string `localhost` into the EMPTY host, so `file://local%68ost/x` parses to href `file:///x` in a
// real WHATWG parser, exactly like `file://localhost/x`. A literal test reported that local
// reference as egress, which strips the author's value and leaves the gate rejecting a file with no
// egress at all. One alternation per character, with BOTH hex rows per letter, because a `/i` regex
// folds `%6c` onto `%6C` but never onto `%4c` - and `%4c` decodes to `L`, which domain-to-ASCII
// lowercases back. Nothing that decodes to anything OTHER than `localhost` can match, so this
// cannot smuggle a host past the strip: `%2F` and `%00` are forbidden host code points that fail to
// parse (both checked), and a host that merely STARTS with `localhost` is stopped by the terminator
// that follows. Mirrored character for character in the validator's `_PCT_LOCALHOST`, and pinned to
// it by a TEXT-equality parity assertion (matching verdicts over a corpus cannot see a drift on a
// spelling the corpus does not carry).
// It covers PERCENT-ENCODING and CASE, which is the half of canonicalization a regex can model. It
// does NOT model the IDNA/UTS-46 half, so a spelling that only IDNA maps onto `localhost` is an
// ACCEPTED, deliberate over-detection: `file://\uFF4Cocalhost/x`, its percent-encoded UTF-8
// `file://%EF%BD%8Cocalhost/x`, `file://LOCALHO\u017FT/x` and the soft-hyphen
// `file://local%C2%ADhost/x` all parse to href `file:///x` (measured) and are still stripped here.
// That residual is deliberate: UTS-46 mapping cannot be written as a regex either side would agree
// on, and Python's `re.IGNORECASE` folds `s` onto U+017F where a JS `/i` never does, so ATTEMPTING
// it is how the two engines drift. Over-detecting costs the author's rare reference; under-detecting
// is a beacon the gate blesses, so the boundary is drawn on the safe side.
const _OFFLINE_PCT_LOCALHOST =
  "(?:l|%[46]c)(?:o|%[46]f)(?:c|%[46]3)(?:a|%[46]1)(?:l|%[46]c)"
  + "(?:h|%[46]8)(?:o|%[46]f)(?:s|%[57]3)(?:t|%[57]4)";
// What may FOLLOW that host for the exclusion to fire: the end of the value, a `?` or `#`, or a
// SINGLE path slash. A second slash is an egress MISS, not a local path:
// `file://localhost//not-a-host/x.js` empties the host and keeps `//not-a-host/x.js` as the PATH, so
// the parser canonicalizes it to `file:////not-a-host/x.js` (measured) - which the four-or-more-slash
// arm above calls an off-machine SMB load. The backslash spelling `file://localhost/\not-a-host/x.js`
// reaches it too, since the cleanup maps `\` onto `/`. The cost is that `file://localhost//C:/x.js`,
// canonically the LOCAL `file:////C:/x.js`, is over-reported; that is the fail-CLOSED direction this
// predicate takes everywhere else.
const _OFFLINE_PCT_LOCALHOST_END = "(?:[?#]|$|/(?!/))";
// The rule both of the following exist to keep is CANONICALIZATION STABILITY: a value and the href
// the URL parser canonicalizes it to must get the SAME verdict, or a spelling hides an authority
// that only the parser sees. Two shapes broke it, and neither is reachable by a test that reads only
// the START of the value, because the parser's path state runs AFTER the host is emptied.
// (1) A DOUBLE-DOT segment pops the segment before it - including the very label an exclusion just
// matched. `file:////localhost/../not-a-host/x` and `file:////C:/../x.js` both canonicalize onto the
// four-separator UNC form with a different leading label, so a `..` anywhere in the path makes the
// arm match REGARDLESS of the exclusions. Every spelling the parser treats as a double-dot segment
// is covered - `..`, `.%2e`, `%2e.`, `%2e%2e`, case-insensitively.
// (2) An EMPTY path segment IS the four-separator form: `file:///.//x.js` and `file:/a/..//x.js`
// canonicalize to `file:////x.js` from a THREE-slash or even slash-less value the arms above never
// look at, so it needs an arm of its own that ignores the leading separator count entirely. The
// leading `/*(?!/)` consumes the whole separator run unbacktrackably, so only a `//` in the PATH
// counts, and `[^?#]` stops at the query, which cannot change the path.
// A fuzz of 421,560 values against a real URL parser measured the result: ZERO remain where the
// predicate says local while the value's own canonical form is egress. The cost is over-detection in
// the safe direction (93,789 of those values, all absurd spellings): an authored
// `file:///C:/a//b.png` or `file://localhost/a/../b.js` is now reported.
const _OFFLINE_FILE_DOTDOT_SEGMENT = "(?:\\.|%2e)(?:\\.|%2e)";
const _OFFLINE_FILE_EMPTY_SEGMENT = "file:/*(?!/)[^?#]*?//";
const _OFFLINE_NETWORK_URL_RE = new RegExp(
  "^(?:(?:https?:/*|/{2,})[^/?#]"
  + "|file:(?://(?!/)|/{4,}(?!/))(?![?#]|$)"
  + "(?:(?=[^?#]*/" + _OFFLINE_FILE_DOTDOT_SEGMENT + "(?:[/?#]|$))"
  + "|(?!" + _OFFLINE_PCT_LOCALHOST + _OFFLINE_PCT_LOCALHOST_END + ")(?![A-Za-z][:|]))"
  + "|" + _OFFLINE_FILE_EMPTY_SEGMENT + ")",
  "i");

function _offlineIsNetworkUrl(v) {
  return _OFFLINE_NETWORK_URL_RE.test(_offlineNormalizeUrlValue(v));
}
// HTML's srcset parser splits candidates on ASCII whitespace ONLY - tab, LF, FF, CR and space - so
// tokenizing with the ENGINE's idea of whitespace was wrong twice over: U+000B is engine whitespace
// but not ASCII whitespace, so `"\u0001\u000bhttps://host/x 1x"` was cut at the U+000B and both
// sides tested `"\u0001"` while the browser fetched the host; and the two engines disagree about
// the rest (JS `trim()` strips U+FEFF, Python's `str.strip()` strips U+001C-U+001F), which is the
// CMH-OFFLINE-04 drift. Only the candidate BOUNDARY is decided here; every character the URL parser
// itself removes is left to `_offlineNormalizeUrlValue`.
const _OFFLINE_SRCSET_WS = "\t\n\f\r ";
// HTML's own srcset candidate state machine, not an approximation of it: skip a run of ASCII
// whitespace and commas, collect a run of NON-whitespace as the URL, then either strip that URL's
// trailing commas (which end the candidate with no descriptors at all) or run the descriptor
// tokenizer forward to the first comma OUTSIDE parentheses.
//
// It replaced a UNION of two approximations - a comma split and a whitespace split - taken because
// a descriptor (`1x`, `320w`) can never match the network predicate, so over-inclusion was thought
// free. A `data:` URL breaks that reasoning: a comma is legal INSIDE one (it separates the media
// type from the data), so `data:text/plain,https://example.com/payload 1x` was comma-split into
// `data:text/plain` and `https://example.com/payload`, and the second half matched. Fail-CLOSED,
// but it made an offline export clear a `srcset` that reaches no network and the strict validator
// reject a document with no egress (issue #1084). Both cases the union existed for survive: a comma
// inside the URL run belongs to the URL (`srcset="https://,host/x.png 1x"` really does request
// `https://,host/x.png`), and a comma that follows the DESCRIPTORS still separates two candidates
// even with no space around it (`local.png 1x,https://host/x.png 2x` is two). A comma that abuts
// the URL run is NOT a separator: `a.png,b.png` is the single relative reference `a.png,b.png`,
// which a browser resolves against the document and never fetches off-host. All three measured in
// a real Chromium.
//
// One step of HTML's algorithm is deliberately NOT taken: descriptor VALIDATION. HTML appends a
// candidate only once its descriptors parse cleanly, so it DISCARDS `https://host/x.png 1x 2x`
// (repeated `x`) and never fetches it; both sides here keep the candidate and report the load.
// That is the fail-CLOSED direction, and the alternative is a second, larger state machine (the
// `w`/`x`/`h`/`d` grammar and its duplicate rules) to hold identical across two languages - the
// drift this pair exists to prevent - where a mistake would cost a MISSED load rather than an
// over-strip. Mirrored in the validator's `srcset_candidate_urls`.
function _offlineSrcsetCandidateUrls(v) {
  const text = String(v || "");
  const urls = [];
  let pos = 0;
  const end = text.length;
  while (pos < end) {
    while (pos < end && (_OFFLINE_SRCSET_WS.indexOf(text[pos]) !== -1 || text[pos] === ",")) pos += 1;
    const start = pos;
    while (pos < end && _OFFLINE_SRCSET_WS.indexOf(text[pos]) === -1) pos += 1;
    let url = text.slice(start, pos);
    if (url.endsWith(",")) {
      url = url.replace(/,+$/, "");
      if (url) urls.push(url);
      continue;
    }
    if (url) urls.push(url);
    let inParens = false;
    while (pos < end) {
      const c = text[pos];
      pos += 1;
      if (inParens) {
        if (c === ")") inParens = false;
      } else if (c === ",") {
        break;
      } else if (c === "(") {
        inParens = true;
      }
    }
  }
  return urls;
}
function _offlineSrcsetHasNetwork(v) {
  return _offlineSrcsetCandidateUrls(v).some(function (url) {
    return _offlineIsNetworkUrl(url);
  });
}
// The CSS network strips, assembled from string parts rather than written as regex LITERALS. The
// pieces are shared, so the two patterns cannot drift apart, and - this is the load-bearing reason -
// the assembled source never contains the at-keyword's name followed directly by an opening paren:
// this file's own text is scanned by the offline export's dynamic-import egress check, which reads
// that sequence as a dynamic import and DELETES the script it sits in, which is this one.
const _OFF_CSS_WS = "[\\t\\n\\f\\r ]";
// The same CLOSED scheme set as `_OFFLINE_NETWORK_URL_RE` above, for the same measured reason: a
// `url(ftp://host/x)`, and the at-rule form beside it, fetch nothing from a `file:` document.
const _OFF_CSS_NET = "(?:https?:\\/*|\\/{2,})";
// One host character, the same approximation the validator's `_CSS_HOST_CHAR` makes.
const _OFF_CSS_HOST = "[^/?#\"')\\t\\n\\f\\r ]";
// A run that stops at a comment boundary in either direction (see `_offlineCssNoNetwork`), plus
// whatever else its caller must not cross.
const _OFF_CSS_RUN = function (extra) {
  return "(?:[^" + extra + "/*]|\\/(?!\\*)|\\*(?!\\/))*";
};
const _OFF_CSS_QUOTED = function (q) {
  return q + _OFF_CSS_WS + "*" + _OFF_CSS_NET + _OFF_CSS_HOST + "[^" + q + "]*" + q;
};
const _OFFLINE_CSS_IMPORT_RE = new RegExp(
  "@" + "import" + "(?:" + _OFF_CSS_WS + "+|(?=[\"']))"
  + "(?:url\\(" + _OFF_CSS_WS + "*)?"
  + "(?:" + _OFF_CSS_QUOTED("\"") + "|" + _OFF_CSS_QUOTED("'")
  + "|" + _OFF_CSS_NET + _OFF_CSS_HOST + _OFF_CSS_RUN(";{}\"')")
  + "|[\"']" + _OFF_CSS_WS + "*" + _OFF_CSS_NET + _OFF_CSS_HOST + _OFF_CSS_RUN(";{}")
  + ")" + _OFF_CSS_RUN(";{}\"'@") + ";?", "gi");
const _OFFLINE_CSS_URL_RE = new RegExp(
  "url\\(" + _OFF_CSS_WS + "*(?:" + _OFF_CSS_QUOTED("\"") + "|" + _OFF_CSS_QUOTED("'")
  + "|" + _OFF_CSS_NET + _OFF_CSS_HOST + "[^)\"'\\t\\n\\f\\r ]*"
  + "|(?:[\"']" + _OFF_CSS_WS + "*)?" + _OFF_CSS_NET + _OFF_CSS_HOST + _OFF_CSS_RUN(");{}")
  + ")(?:" + _OFF_CSS_WS + "*\\)|$|(?=[;{}]))", "gi");
function _offlineCssNoNetwork(css) {
  // Mirrors the validator's `CSS_NETWORK_IMPORT_RE` / `CSS_NETWORK_URL_RE`, and moves with them
  // (issue #961): the slash run after a special scheme is CONSUMED rather than counted, so the
  // scheme-only `url(https:host/x.png)` the URL parser resolves to the same host is stripped too,
  // and one host character is required so an empty authority - `url(https://)`, `url(//)`, which
  // fetch nothing - is left in the author's stylesheet rather than rewritten.
  // Both replaces have to remove EVERYTHING the gate reports, or an export fails its own `--strict`
  // run. Shapes that used to escape them while the gate flagged them: an at-rule whose URL is
  // followed by a media query, a `layer()`/`supports()` clause, or nothing at all (the terminator
  // was required immediately after the URL); a QUOTED value carrying a `)` or the other quote
  // character; a value or string the CSS tokenizer closes but the author did not; and an at-keyword
  // with NO whitespace before its quoted URL, which is valid CSS that really fetches. So the at-rule
  // strip consumes the prelude the way a CSS parser does - to its `;`, its block boundary, or the
  // end of the sheet - and the value strip reads a quoted value as a CSS STRING.
  // Whitespace is spelled out as the ASCII set rather than `\s`, because a JS `\s` also takes
  // U+00A0 and U+FEFF (neither of which is CSS whitespace, and neither of which Python's `\s`
  // takes under `re.ASCII`), which would classify `url(<U+FEFF>https:host/x)` differently here than
  // in the gate.
  // Both are BOUNDED: they stop at `;`, `{`, `}` (and the at-rule tail also at `@`), so a false hit
  // on `url(`/at-rule text written INSIDE a CSS string costs at most the declaration it sits in
  // rather than the rest of the stylesheet, and a LOCAL at-rule written after a network one
  // survives. Neither crosses a comment boundary in either direction: consuming a `/*` would delete
  // a comment's OPENER and leave its `*/`, turning commented-out CSS into live CSS - a net-new fetch
  // created by the strip itself, verified in a real Chromium. The cost is that a reference written
  // inside a comment is left alone while the (raw-text) gate still reports it; that is the shared
  // raw-text residual issue #1029 tracks, and the only shape where this pair is not a fixed point.
  // Applied until it converges, and a removed at-rule is replaced by a SPACE rather than by nothing,
  // because a deletion can otherwise bring two halves of the sheet together into a NEW reference and
  // the contract the gate holds the export to is a fixed point: what is written out must no longer
  // match.
  let out = String(css || "");
  for (let i = 0; i < 5; i++) {
    const next = out.replace(_OFFLINE_CSS_IMPORT_RE, " ").replace(_OFFLINE_CSS_URL_RE, 'url("data:,")');
    if (next === out) break;
    out = next;
  }
  return out;
}
// An SVG PRESENTATION ATTRIBUTE carries a CSS declaration VALUE, so `clip-path="url(https://...)"`
// is a network fetch on open that no element strip above reaches (they clear attributes whose WHOLE
// value is a URL) and no CSS strip below reaches either (they take a `<style>` body and a `style=`
// attribute). Neutralized through `_offlineCssNoNetwork`, the same paired reading the `[style]`
// strip uses, so the strict gate's `CSS_NETWORK_URL_RE` and this cannot drift apart and a LOCAL
// `url(#clip)` - which is how these attributes are almost always written - survives byte-identical
// (issue #1186). The attribute list is the MEASURED one (`checks/resources.py`'s
// `SVG_URL_PRESENTATION_ATTRS`, pinned to this literal by tests/test_egress_list_parity.py), and it
// is written INSIDE this helper rather than as a shared constant so that reading can see it.
function _offlineStripPresentationUrl(el) {
  ["clip-path", "cursor", "fill", "filter", "marker-end", "marker-mid", "marker-start", "mask",
   "stroke"]
    .forEach(function (name) {
      if (!el.hasAttribute(name)) return;
      const next = _offlineCssNoNetwork(el.getAttribute(name) || "");
      if (next) el.setAttribute(name, next);
      else el.removeAttribute(name);
    });
}
function _stripOfflineEventHandlers(doc) {
  // Template-parked too: an `on*` attribute on a fragment a script later adopts and inserts is a
  // live handler the moment it enters the document.
  _offlineQueryAll(doc, "*").forEach(function (el) {
    Array.from(el.attributes || []).forEach(function (attr) {
      if (/^on/i.test(attr.name || "")) el.removeAttribute(attr.name);
    });
  });
}
// A `</noscript` END-TAG-OPEN: the name, then any character that can end a tag name (HTML lets an end
// tag carry whitespace or a slash before its `>`). Written out rather than spelled `<\/noscript>` for
// the same reason the close scanners in 65-export-shareable.js are: a space before the `>` still
// closes the element, and a name-end class that forgot one would read a live seam as text.
const _OFFLINE_NOSCRIPT_END_RE = /<\/noscript[\t\n\f\r />]/i;
const _OFFLINE_HTML_NS = "http://www.w3.org/1999/xhtml";
// Whether `el` sits inside an HTML `<noscript>` - fallback markup a scripting-ENABLED reader gets as
// inert TEXT. Only the HTML namespace counts, for the reason the strip below gives (an
// `<svg><noscript>` switches no tokenizer, so a script inside one really does run and moving it
// changes nothing). The walk stops at a `<template>`'s content fragment, whose `parentNode` is null:
// that matches the only caller, which selects with `doc.querySelectorAll` and so never reaches a
// template-parked node either. A caller that switched to `_offlineQueryAll` would need the host
// chain as well.
function _offlineInHtmlNoscript(el) {
  for (let n = el.parentNode; n; n = n.parentNode) {
    if (n.localName === "noscript" && n.namespaceURI === _OFFLINE_HTML_NS) return true;
  }
  return false;
}
// A `<noscript>` body has TWO readings and this export re-parses with only one of them. The
// `DOMParser` every strip walks has scripting OFF, so the body is MARKUP; the reviewer who opens the
// exported file has scripting ON, so it is RAW TEXT that ends at the FIRST `</noscript`. The two
// agree exactly while the serialized body carries no such seam - then one reader sees inert text and
// the other sees the markup the strips already scrubbed - and disagree the moment it does, because
// everything past that seam becomes live markup for the reviewer while it was fallback content the
// strips saw (or, worse, content they could not see at all: a comment or a raw-text `<style>` child
// is serialized VERBATIM, which is how `<noscript><!-- </noscript><img onload=...> --></noscript>`
// rides out of an unguarded export as a live handler). It cannot be reconciled from here - escaping
// the seam would change what the scripting-disabled reader is shown - so the body is DROPPED. The
// strict validator already fails closed on the same seam, so leaving one in would ship a file this
// exporter's own gate rejects. This is deliberately the ONLY reason a fallback is removed: an
// ordinary one (the layer's own print fallback included) reads the same both ways and is content.
// Runs after every pass that can rewrite a fallback body - the handler scrub and the CSS strip both
// can take a seam away with the attribute or declaration that carried it - and the count is
// returned so the removal is named rather than silent.
function _stripOfflineStraddlingNoscript(doc) {
  let dropped = 0;
  // Walked root by root rather than through `_offlineQueryAll`, because the skip below has to be
  // exact: `Node.contains` does NOT reach into a `<template>`'s content fragment, so a flat list
  // could not tell a fallback that was already taken with its ancestor from one still standing, and
  // would report the same content loss twice. Within a root `contains` answers precisely, and a
  // template whose own subtree has just been removed is simply never descended into.
  const walk = function (root) {
    root.querySelectorAll("noscript").forEach(function (el) {
      // A nested fallback serializes its own `</noscript>` into its ancestor's body, so the OUTER
      // one is always flagged too and this one has already gone with it.
      if (!root.contains(el)) return;
      // The HTML namespace ONLY. A type selector matches a local name in ANY namespace, but an
      // `<svg><noscript>` is an ordinary foreign element that switches no tokenizer on either side -
      // both readings agree about it, seam or no seam - so removing one would be pure content loss.
      // An HTML fallback CONTAINING foreign content is still caught: the seam is in ITS body.
      if (el.namespaceURI !== _OFFLINE_HTML_NS) return;
      if (!_OFFLINE_NOSCRIPT_END_RE.test(el.innerHTML || "")) return;
      el.remove();
      dropped += 1;
    });
    root.querySelectorAll("template").forEach(function (t) {
      if (t.content && root.contains(t)) walk(t.content);
    });
  };
  walk(doc);
  return dropped;
}
// A `<noscript>` in the HEAD is the one place the strip above cannot reach, because there the
// fallback is not an ordinary element to a scripting-DISABLED parse at all. The "in head noscript"
// insertion mode allows only `link`, `style`, `meta`, `basefont`, `bgsound`, `noframes`, comments
// and whitespace; anything else is a parse error that POPS the fallback and REPROCESSES that node -
// and everything after it - under the "in head" rules, so it becomes a head SIBLING (a `<script>`)
// or ends the head and lands in the body (a `<p>`, a line of prose). `DOMParser` has scripting off,
// so that promotion happens INSIDE `_offlineDocFromHtml`, before any pass or ancestry check can see
// it, and a promoted node is indistinguishable in the DOM from one the author really wrote as a
// sibling. The export therefore ACTIVATES what the source document never ran: opening the source
// leaves a head `<noscript><script>` inert (raw text to a scripting-ENABLED reader), while opening
// the export runs it. So this is decided BEFORE the parse, on the SOURCE STRING, read the way the
// reviewer's tokenizer reads it - a start tag, then raw text to the first `</noscript` - and the
// whole fallback is dropped, for the same reason a straddling one is: the two readings cannot be
// reconciled from here, and the reviewer's is the one that matters.
// What the mode ALLOWS is untouched, so this is not a blanket head-fallback removal: a fallback
// carrying only those elements stays inside its `<noscript>` under both readings and travels.
const _OFFLINE_HEAD_NOSCRIPT_OK_RE = /^(?:link|style|meta|basefont|bgsound|noframes)$/;
// What keeps a parser in "in head". A start tag outside this set (`<body>` included), an explicit
// `</head>`, or non-whitespace character data ends the head, and a `<noscript>` after that is an
// ordinary element both readings agree about.
const _OFFLINE_HEAD_ELEMENT_RE =
  /^(?:html|head|base|basefont|bgsound|link|meta|noframes|noscript|script|style|template|title)$/;
const _OFFLINE_NON_SPACE_RE = /[^\t\n\f\r ]/;
// A tag name folded the way HTML folds one: ASCII ONLY. `String.prototype.toLowerCase` is
// Unicode-aware, so it reads `lin<U+212A>` (KELVIN SIGN) as `link` while a browser does not - and
// measured in chromium that element really does POP a head fallback, so folding it into the allowed
// set would leave the promotion undetected. Mirrored by `_offline_ascii_tag_name` in the strict
// validator, which uses the `_ascii_lower` the other predicates there already fold with.
function _offlineAsciiTagName(html, from) {
  let i = from;
  while (i < html.length && !_CMH_NAME_END_CH.test(html[i])) i += 1;
  return html.slice(from, i).replace(/[A-Z]/g, function (c) { return c.toLowerCase(); });
}
// A character reference that decodes to ASCII whitespace, spelled out because HTML decodes
// references in CHARACTER DATA while a byte scan reads them as content. Measured in chromium: a
// `&Tab;` before a head fallback keeps the parser in the head (so the fallback is still head
// content the mode judges), and a `&#9;` inside one leaves the fallback standing. The numeric forms
// may omit the semicolon, so each carries the class that stops `&#320;` (U+0140) being read as
// `&#32` plus a `0`.
const _OFFLINE_WS_CHAR_REF_RE =
  /&(?:Tab;|NewLine;|#(?:0*(?:9|10|12|13|32)(?![0-9])|[xX]0*(?:9|[aAcCdD]|20)(?![0-9A-Fa-f]));?)/g;
// Character data as the PARSER reads it rather than as the bytes read. Besides the references
// above, a U+0000 is dropped outright (measured: a NUL before a head fallback keeps the parser in
// the head, and one inside a fallback body leaves it standing), so neither ends the head nor pops a
// fallback. Mirrored by `_offline_char_data_has_content` in the strict validator.
function _offlineCharDataHasContent(text) {
  return _OFFLINE_NON_SPACE_RE.test(
    String(text).replace(/\u0000/g, "").replace(_OFFLINE_WS_CHAR_REF_RE, " "));
}
// The comment open, spelled in two pieces because this source is served INSIDE a `<script>`: a
// literal comment-open sequence in script data puts the tokenizer in the escaped state, where the
// layer's own closing script tag stops closing the element and the rest of the document becomes
// script text. (A comment here that merely NAMES the sequence has the same effect, so the prose
// above spells it out only where a closing `-->` balances it.)
const _OFFLINE_COMMENT_OPEN = "<" + "!--";
// Would a scripting-disabled parse take this head fallback apart? Mirrored predicate for predicate
// by `offline_head_noscript_promotes` in the strict validator, so the gate rejects exactly what
// this drops.
function _offlineHeadNoscriptPromotes(body) {
  const src = String(body == null ? "" : body);
  let pos = 0;
  while (pos < src.length) {
    const lt = src.indexOf("<", pos);
    // Promoted content need not be an element: a character token that is not whitespace is
    // "anything else" too, so a line of fallback prose becomes the start of the BODY.
    if (_offlineCharDataHasContent(lt < 0 ? src.slice(pos) : src.slice(pos, lt))) return true;
    if (lt < 0) return false;
    if (src.slice(lt, lt + 4) === _OFFLINE_COMMENT_OPEN) { pos = _cmhCommentEnd(src, lt); continue; }
    const lead = src.charAt(lt + 1);
    if (lead === "!" || lead === "?") {
      // A DOCTYPE and a bogus comment are both tokens this mode ignores.
      const gt = src.indexOf(">", lt + 1);
      pos = gt < 0 ? src.length : gt + 1;
      continue;
    }
    if (lead === "/") {
      const endName = _offlineAsciiTagName(src, lt + 2);
      const gt = _cmhTagEnd(src, lt);
      // `</br>` is the one end tag the mode treats as "anything else"; every other one is a parse
      // error it ignores, so it promotes nothing.
      if (endName === "br") return true;
      pos = gt < 0 ? src.length : gt + 1;
      continue;
    }
    if (!/[A-Za-z]/.test(lead)) return true;  // a `<` that opens no tag is character data
    const end = _cmhTagEnd(src, lt);
    if (end < 0) return true;  // a truncated tag: fail closed rather than guess how it ends
    const name = _offlineAsciiTagName(src, lt + 1);
    // An `<html>` or a nested `<noscript>` start tag is NOT a pop: this mode processes the first
    // with the in-body rules (which only merge its attributes) and ignores the second as a parse
    // error, and a real chromium agrees with the spec on both (measured - a `<meta>` written after
    // either stays inside the fallback). A `<head>` start tag is a parse error the SPEC also says
    // to ignore, but chromium POPS the fallback on it (measured), and the browser that does the
    // promoting is the one that matters, so it is read as "anything else" like everything below.
    if (name === "html" || name === "noscript") { pos = end + 1; continue; }
    if (!_OFFLINE_HEAD_NOSCRIPT_OK_RE.test(name)) return true;
    pos = end + 1;
    if (_CMH_RAW_TEXT.test(name)) {
      const close = _cmhRawTextClose(src, name, pos);
      const closeEnd = close < 0 ? -1 : _cmhTagEnd(src, close);
      // A raw-text child the fallback never closes runs PAST the seam the scripting-enabled reader
      // stops at, so the two readings disagree about the rest of the document: fail closed.
      if (closeEnd < 0) return true;
      pos = closeEnd + 1;
    }
  }
  return false;
}
// Drop every head `<noscript>` the mode above would take apart, on the SOURCE STRING. Returns the
// rewritten HTML and the count, so the removal is named in the toast rather than silent.
function _stripOfflineHeadNoscript(html) {
  const src = String(html == null ? "" : html);
  const cuts = [];
  // A leading BOM is dropped when a browser DECODES the file, so a real load never sees it as
  // character data and the head runs on past it. `DOMParser` is the exception - it takes a STRING,
  // does no decode, and reads a leading U+FEFF as content (measured) - but the exporter's own base
  // never carries one (`Response.text()` strips it), while the file the GATE reads does. Skipping it
  // keeps the two sides identical and models the reviewer's own load; reading it as content would
  // stop the walk at position 0 and turn the rule off for exactly the hand-authored file it exists
  // to catch.
  let pos = src.charAt(0) === "\ufeff" ? 1 : 0;
  let templateDepth = 0;
  for (;;) {
    const lt = src.indexOf("<", pos);
    if (lt < 0) break;
    // Character data is only the head's business outside a `<template>`, whose content is parsed
    // in its own fragment and never reaches the "in head noscript" mode at all.
    if (templateDepth === 0 && _offlineCharDataHasContent(src.slice(pos, lt))) break;
    if (src.slice(lt, lt + 4) === _OFFLINE_COMMENT_OPEN) { pos = _cmhCommentEnd(src, lt); continue; }
    const lead = src.charAt(lt + 1);
    if (lead === "!" || lead === "?") {
      const gt = src.indexOf(">", lt + 1);
      pos = gt < 0 ? src.length : gt + 1;
      continue;
    }
    if (lead === "/") {
      const endName = _offlineAsciiTagName(src, lt + 2);
      const gt = _cmhTagEnd(src, lt);
      if (templateDepth > 0) {
        if (endName === "template") templateDepth -= 1;
      } else if (endName === "head" || endName === "html" || endName === "body" || endName === "br") {
        // Every end tag "in head" treats as "anything else" leaves the head, `</br>` included
        // (measured - a fallback written after one is BODY content, which the mode never judges).
        break;
      }
      pos = gt < 0 ? src.length : gt + 1;
      continue;
    }
    if (!/[A-Za-z]/.test(lead)) {
      if (templateDepth === 0) break;
      pos = lt + 1;
      continue;
    }
    const end = _cmhTagEnd(src, lt);
    if (end < 0) break;
    const name = _offlineAsciiTagName(src, lt + 1);
    if (templateDepth === 0 && !_OFFLINE_HEAD_ELEMENT_RE.test(name)) break;
    let next = end + 1;
    if (_CMH_RAW_TEXT.test(name)) {
      const close = _cmhRawTextClose(src, name, end + 1);
      const closeEnd = close < 0 ? -1 : _cmhTagEnd(src, close);
      if (closeEnd < 0) {
        // The element never closes (or its end tag is truncated), so its body runs to the end of
        // the document for both readings. A head fallback the insertion mode would still take
        // apart is cut to EOF rather than left standing - the scripting-disabled parse pops it and
        // promotes what follows just the same (measured) - and either way there is no further head
        // markup to judge.
        if (templateDepth === 0 && name === "noscript"
            && _offlineHeadNoscriptPromotes(src.slice(end + 1, close < 0 ? src.length : close))) {
          cuts.push([lt, src.length]);
        }
        break;
      }
      if (templateDepth === 0 && name === "noscript"
          && _offlineHeadNoscriptPromotes(src.slice(end + 1, close))) {
        cuts.push([lt, closeEnd + 1]);
      }
      next = closeEnd + 1;
    } else if (name === "template") {
      templateDepth += 1;
    }
    pos = next;
  }
  if (!cuts.length) return { html: src, dropped: 0 };
  // Built in ONE forward pass. Slicing the document per cut would rebuild the whole multi-megabyte
  // string each time, so a head carrying N promoting fallbacks would cost O(N x document).
  const kept = [];
  let at = 0;
  for (let i = 0; i < cuts.length; i += 1) {
    kept.push(src.slice(at, cuts[i][0]));
    at = cuts[i][1];
  }
  kept.push(src.slice(at));
  return { html: kept.join(""), dropped: cuts.length };
}
// The strip is a SINGLE pass, and a single pass is not a fixed point: removing a fallback splices
// the bytes on either side of it together, and that can put a LATER fallback in head scope that the
// walk had already stopped short of (`&#9` followed by a cut, then a `;`, fuses into a whitespace
// reference and the head runs on). Measured: the once-stripped document then parses with the second
// fallback's script promoted into the head - the very activation this rule exists to close, and one
// the gate would bless, since it only ever sees the finished file. So the export runs the pass to a
// FIXED POINT. It terminates because every iteration that does anything removes at least one
// fallback. The gate deliberately does NOT iterate: it judges the document in front of it.
function _stripOfflineHeadNoscriptStable(html) {
  let out = String(html == null ? "" : html);
  let dropped = 0;
  for (;;) {
    const pass = _stripOfflineHeadNoscript(out);
    if (!pass.dropped) return { html: out, dropped: dropped };
    out = pass.html;
    dropped += pass.dropped;
  }
}
function _ensureOfflineCsp(doc) {
  const html = doc.documentElement || doc.querySelector("html");
  let head = doc.head || doc.querySelector("head");
  if (!head) {
    head = doc.createElement("head");
    if (html && html.firstChild) html.insertBefore(head, html.firstChild);
    else if (html) html.appendChild(head);
  }
  if (!head) return;
  doc.querySelectorAll("meta[http-equiv]").forEach(function (m) {
    if ((m.getAttribute("http-equiv") || "").toLowerCase() === "content-security-policy") m.remove();
  });
  const meta = doc.createElement("meta");
  meta.setAttribute("http-equiv", "Content-Security-Policy");
  meta.setAttribute("content", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
  head.insertBefore(meta, head.firstChild);
  // No CSP directive delivered in a <meta> can restrict TOP-LEVEL NAVIGATION (`navigate-to` was
  // dropped from CSP Level 3 and ships in no browser; `sandbox` is ignored in a meta-delivered
  // policy), so a navigation that does happen - a reader clicking an authored link, or a preserved
  // script the strip's literal-URL test cannot see through - is not blockable here. It can at
  // least carry no provenance: an authored referrer policy is replaced rather than merged, because
  // the LAST referrer meta a document declares wins and a permissive one (`unsafe-url`) would
  // otherwise leak the local file path of the reviewed document to whatever it navigates to.
  // Template content is walked too, the way the LOAD strips are: a parked referrer meta is inert
  // until a script adopts the fragment, but the strict validator's flat tokenizer reads it plainly,
  // so leaving one would make the gate reject a file this export just produced.
  _offlineQueryAll(doc, "meta[name]").forEach(function (m) {
    if ((m.getAttribute("name") || "").toLowerCase() === "referrer") m.remove();
  });
  // The pragma spelling is not in the HTML spec's pragma-directive list, so a conformant browser
  // ignores it - but it appears in the wild, this whole strip is precautionary anyway, and leaving
  // an authored `unsafe-url` in the file would be a confusing contradiction of the meta beside it.
  _offlineQueryAll(doc, "meta[http-equiv]").forEach(function (m) {
    if ((m.getAttribute("http-equiv") || "").toLowerCase() === "referrer-policy") m.remove();
  });
  const referrer = doc.createElement("meta");
  referrer.setAttribute("name", "referrer");
  referrer.setAttribute("content", "no-referrer");
  head.insertBefore(referrer, meta.nextSibling);
}
function _offlineScriptHasNetworkImport(body) {
  const src = String(body || "");
  return /\bimport\s*\(\s*["'](?:https?:)?\/\//i.test(src) ||
    (/\bimport\s*\(/.test(src) && /["'](?:https?:)?\/\/[^"']*["']/i.test(src)) ||
    /\bfrom\s+["'](?:https?:)?\/\//i.test(src) ||
    /\bimport\s+["'](?:https?:)?\/\//i.test(src);
}
// A DIRECT scripted top-level navigation to a network URL. This is the one egress channel the
// zero-network CSP cannot close (see `_ensureOfflineCsp`), and it is the WHOLE document that leaks
// - every reviewer comment with it - so a script carrying one is dropped exactly like one carrying
// a remote dynamic module load. Four shapes are recognized: an assignment to a `location` property
// (`href`, or an `assign`/`replace` call), an assignment to `location` itself through a global
// prefix chain, a bare assignment to `location` in statement position, and a prefixed `open` call.
// The prefix chain is repeatable and tolerates optional chaining, so `window.top.location...` and
// `window?.location...` are covered, not just a single prefix.
// The URL literal is recognized in the literal prefixes a browser resolves to a network host, and
// in the spellings that NORMALIZE into one of those before anything resolves them - by the URL
// parser, or by the JavaScript parser that produced the string. The prefixes are scheme plus
// slashes, protocol-relative (slashes only), and SCHEME-ONLY - a quoted `https:`/`http:` with NO
// slashes after it, which resolves to the same host and needs no indirection at all to write, so
// requiring the slashes left the whole channel open to a one-token spelling change. On top of any
// of them the literal may carry:
//   (a) leading C0-or-space padding, which the URL parser strips before it parses. U+0000 is
//       EXCLUDED: the HTML parser replaces a NUL in script data with U+FFFD, which the URL parser
//       does not strip, so a NUL-padded literal can never navigate and matching it would only make
//       the validator - which reads the RAW text - reject a file this strip preserves.
//   (b) an ASCII tab, LF or CR anywhere inside the scheme or between the two slashes, which the URL
//       parser removes from its whole input and which an ordinary string literal can carry as a
//       real character.
//   (c) a backslash in place of either slash (for a special scheme the parser treats the two
//       alike), written as a slash, an escaped slash, or - since a literal spends TWO source
//       backslashes per runtime one - four source backslashes.
//   (d) a LineContinuation, a backslash followed by a line terminator, which evaluates to NOTHING
//       in an ordinary and a template literal alike, so it pads or splits with no parser help.
//   (e) an escaping backslash before any literal element, because a backslash before a character
//       that begins no escape sequence is a NonEscapeCharacter and evaluates to that character.
//       That is the cheapest spelling of all - one keystroke, no decoder - so `\\?` sits in front
//       of every literal the tail requires.
// What stays out is the class raw source genuinely cannot READ: a MULTI-character escape that
// stands for one of those characters (`\u0068`, `\x68`, an octal), which needs a string-literal
// decoder rather than a regex - it can sit at any position, in several spellings, and only the
// literal's own quoting context says whether a backslash starts one. (The single-character cases
// are exactly what (d) and (e) close, so the residual is escapes that ENCODE a character rather
// than erase one.) A `javascript:` wrapper that assigns the real URL at runtime is left out for a
// DIFFERENT reason: the prefix is perfectly visible, but the URL is not in the source at all and
// matching the wrapper would buy nothing, since a script able to write it already runs arbitrary
// code in that document - a deliberate trade, not a visibility limit. Both are in the
// CMH-OFFLINE-05 residual.
// Each added run's two alternatives are told apart by their SECOND character (the line-terminator
// branch keeps only U+2028/U+2029, because a backslash before LF or CR already falls inside the
// class beside it), so no input has two parses of a run. The two AUTHORITY alternatives can both
// begin with a backslash, but both are fixed-width, so choosing between them costs a bounded retry
// rather than a split - the tail cannot backtrack superlinearly.
// The authority branch deliberately does NOT require a host character after the two slashes: a
// sink assigned a quoted protocol-relative prefix CONCATENATED with a host variable assembles a
// real beacon, and the tail fails CLOSED on it, at the cost of also removing a host-less two-slash
// reference a browser would resolve locally - the over-match direction the CMH-OFFLINE-05 row
// already owns.
// Every metacharacter whose meaning DIFFERS between JavaScript and Python is spelled out instead:
// `\w` is ASCII-only in JS but Unicode-aware in Python, and JS whitespace includes U+FEFF while
// Python's does not, so a shared `\s`/`\w` made the two copies disagree on real inputs (the
// validator would then certify a file the exporter strips, and vice versa). The literal classes
// below make the pattern mean the same thing in both engines.
// Deliberately literal, matching the import test next to it - and therefore NOT a boundary. It sees
// only these sinks, written out directly: an alias (`var l = location; l.href = ...`), computed
// access (`location["href"]`), an IDENTIFIER ESCAPE in any identifier of the chain, a
// comment between the sink and the URL, a URL assembled at runtime, or an entirely different sink
// (a synthesized anchor click, a script-injected refresh meta) all pass through. The identifier
// escape is the one worth naming, because the anchors below are what the widened URL literal is
// matched FROM: a UnicodeEscapeSequence that decodes to a legal identifier character may appear
// inside an IdentifierName and names exactly the same property, so an escaped prefix name, an
// escaped sink name, or an escaped `href`/`assign`/`replace` (`locatio\u006E`, `\u006Fpen`,
// `hre\u0066`, either the `\u006E` or the `\u{6E}` form, at any character position including the
// first) steps around text matched literally. The ONE shape that survives the escape is a prefix
// name separated from its `.` (or `?.`) by WHITESPACE: the walk below skips that run and finds a
// legal boundary at it, so the literal remainder of the chain qualifies on its own and
// `windo\u0077 . top.location` is caught where the tight `windo\u0077.top.location` is not. That is
// incidental rather than a defence - the same whitespace makes an arbitrary `zzz . location` match
// - and the corpus pins it beside a non-escaped control so it cannot be read as one. The same
// literal matching runs the other way too, and that direction costs an author content rather than
// letting a beacon out: `_OFFLINE_LOCAL_LOCATION_RE` reads a local `location` binding literally, so
// an ESCAPED declaration does not register as a shadow and a script that navigates nothing is
// deleted whole. Both are DECIDED rather than overlooked. Recognizing each name as literal-or-
// escaped per character is possible without backtracking, but it turns a plain literal anchor
// search into a per-position automaton over every inline script - the vendored payload's inflated
// megabytes included - to close a channel computed access already leaves open for a shorter edit;
// that is also why hardening the URL LITERAL further has reached its useful limit, since an author
// who will not write an encoded scheme can write an encoded sink name.
// A BARE unprefixed `open(<url>)` is deliberately not matched either: in raw source
// it cannot be told apart from a local `open` helper, and deleting the wrong script is the costlier
// error. A bare `location = <url>` is matched only after a delimiter that cannot begin a
// declaration (`;`, `}`, `)`, `>`, or a line break), so a purely local binding - a `var`/`let`/
// `const` declaration, a parameter default, a destructuring default - is left alone; the cost is
// that a same-line `{ location = <url> }` is missed. It also over-matches: the URL literal is found
// in raw source, so a script whose COMMENT or STRING merely spells one of these shapes is stripped
// too. Both directions are stated in CMH-OFFLINE-05 rather than papered over.
// It is a SCAN, not one big pattern, and that is a cost property rather than a style choice. The
// single pattern this replaced carried the global-prefix chain as an unbounded repetition in front
// of the sink, so the engine re-entered that chain at EVERY position a prefix could follow - which
// is every whitespace run - and a long NEAR-match cost quadratic time: `window . ` repeated took
// 2.3s at 18 KB and 174s at 144 KB in Python, 4x the time for 2x the input. Nothing bounded it: the
// exporter runs this over every runnable script in the document AND over the vendored payload's
// INFLATED bytes, so a few hundred base64 bytes bought megabytes of near-match and an export that
// looked hung. Every shape it recognizes requires the literal `location` or `open`, so the scan is
// driven from THOSE anchors instead. Forward from an anchor the tail stays a regex, matched STICKY
// so it cannot wander, and every unbounded whitespace run inside one is followed by a distinct
// non-whitespace literal, so no run can be split two ways (the earlier `WS*\??WS*\.` could, which
// took ~2.7s in Python and ~10s in node on a 20k-space input). Backward from an anchor the prefix
// chain is walked once in code; chains for two different anchors cannot overlap, because no sink
// name is a prefix name, so the whole scan is linear in the input.
// `test_the_navigation_scan_stays_linear_as_the_near_match_grows` pins the SCALING, not just one
// fixed-size input, so the quadratic term cannot come back unnoticed.
// This comment must not spell out a navigation sink followed by a network URL literal: the layer's
// own script is stripped by the same pass, so writing the pattern out here deletes the runtime from
// every offline export (it did, once - the whole suite went red at "JS region has no closing
// script tag"). `test_the_layer_script_survives_its_own_offline_strips` guards it.
const _OFFLINE_NAV_ANCHOR_RE = /location|open/gi;
const _OFFLINE_NAV_PROP_TAIL_RE = /[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:\?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)?\.[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:href[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*=(?!=)|(?:assign|replace)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\()[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*["'`](?:\\?[\u0001-\u0020]|\\[\u2028\u2029])*(?:\\?h(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?p(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?s(?:\\?[\t\n\r]|\\[\u2028\u2029])*)?\\?:|(?:\\?\/|\\\\)(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?\/|\\\\))/iy;
const _OFFLINE_NAV_ASSIGN_TAIL_RE = /[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*=(?!=)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*["'`](?:\\?[\u0001-\u0020]|\\[\u2028\u2029])*(?:\\?h(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?p(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?s(?:\\?[\t\n\r]|\\[\u2028\u2029])*)?\\?:|(?:\\?\/|\\\\)(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?\/|\\\\))/iy;
const _OFFLINE_NAV_OPEN_TAIL_RE = /[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\([ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*["'`](?:\\?[\u0001-\u0020]|\\[\u2028\u2029])*(?:\\?h(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?p(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?s(?:\\?[\t\n\r]|\\[\u2028\u2029])*)?\\?:|(?:\\?\/|\\\\)(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?\/|\\\\))/iy;
const _OFFLINE_NAV_WS_RE = /[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]/;
// An IDENTIFIER character, spelled as the complement of the BOUNDARY characters. It decides where
// a prefix chain may start, so a character it gets wrong in the identifier direction turns a purely
// local binding whose name merely ENDS in `location` into the document's own sink and deletes an
// author's whole script. The class was ASCII-only and did exactly that. `\w` cannot fix it (ASCII
// in JS, Unicode-aware in Python) and Python's `re` has no Unicode property escape, so the
// complement is spelled out and stays byte-identical in both copies: every ASCII character that
// cannot appear in an identifier EXCEPT `.`, plus the exact whitespace set the scan uses.
// Everything else, ASCII or not, is an identifier character. The `.` exception predates this
// spelling and is load-bearing: a member-expression dot must CONTINUE the chain, so
// `cfg.location.href = <url>` reads as some other object's `location` and stays benign. A surrogate
// code unit is an identifier character too, which is how a supplementary code point reads here and
// is what keeps `charAt` agreeing with Python's whole-code-point view. Non-ASCII WHITESPACE stays a
// boundary; a non-ASCII character that is not a legal IdentifierPart now reads as one, which only
// ever removes matches (CMH-OFFLINE-05's residual).
const _OFFLINE_NAV_IDENT_RE = /[^\u0000-\u0023\u0025-\u002d\u002f\u003a-\u0040\u005b-\u005e\u0060\u007b-\u007f\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]/;
const _OFFLINE_NAV_STATEMENT_RE = /[;})>\n\r\u2028\u2029]/;
const _OFFLINE_NAV_LINE_BREAK_RE = /[\n\r\u2028\u2029]/;
const _OFFLINE_NAV_PREFIX_NAMES = ["window", "self", "top", "parent", "globalThis", "document", "frames"];
const _OFFLINE_SHADOW_IDENT_ASCII_RE = /[A-Za-z0-9_$]/;
// `import` and `using` are here because a named `import` and `using location = res` bind the name
// exactly as `const` does. Neither is a reserved word in every position, so a declaration is only
// recognized when the keyword is FOLLOWED by the name or pattern it binds
// (`_offlineShadowDeclStarts`), which is what keeps the expression and call spellings out of
// binding mode.
const _OFFLINE_SHADOW_DECL_KEYWORDS = ["var", "let", "const", "import", "using"];
const _OFFLINE_SHADOW_NON_METHOD = ["if", "while", "for", "switch", "with", "do", "else", "return", "typeof", "void", "delete", "new", "in", "of", "instanceof", "case", "throw", "yield", "await", "function", "catch", "try", "finally", "var", "let", "const", "class", "import", "export", "default", "break", "continue", "debugger", "this", "super", "null", "true", "false"];
const _OFFLINE_SHADOW_REGEX_PRECEDERS = ["return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield", "await"];
const _OFFLINE_SHADOW_COMPOUND_OPS = ["=", "!", "<", ">", "+", "-", "*", "/", "%", "&", "|", "^"];
// The deepest bracket nesting the frame stack tracks. Beyond it the scan keeps COUNTING depth but
// stops allocating, so a hostile script that is nothing but openers costs constant memory instead of
// one object per character - 2 million of them measured 168 MB of heap in node, and the export runs
// in the reviewer's own tab. Real nesting is two orders of magnitude below this.
const _OFFLINE_SHADOW_MAX_DEPTH = 1000;
function _offlineNavAsciiLower(text) {
  let out = "";
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    out += code >= 65 && code <= 90 ? String.fromCharCode(code + 32) : text.charAt(i);
  }
  return out;
}
const _OFFLINE_NAV_PREFIX_LOWER = _OFFLINE_NAV_PREFIX_NAMES.map(function (n) { return _offlineNavAsciiLower(n); });
const _OFFLINE_NAV_PREFIX_MAX = _OFFLINE_NAV_PREFIX_LOWER.reduce(function (m, n) { return Math.max(m, n.length); }, 0);
function _offlineNavSkipWsBack(src, pos) {
  while (pos > 0 && _OFFLINE_NAV_WS_RE.test(src.charAt(pos - 1))) pos--;
  return pos;
}
function _offlineNavBoundaryOk(src, pos) {
  return pos === 0 || !_OFFLINE_NAV_IDENT_RE.test(src.charAt(pos - 1));
}
// One ASCII fold per chain element rather than one per candidate name: the tail is folded once at
// the longest name's width and every name is then tested against it. Seven folds per element cost
// 3s on a 1.4 MB chain of them, which is linear but with a constant big enough to matter.
function _offlineNavPrefixStart(src, pos) {
  const tail = _offlineNavAsciiLower(src.slice(Math.max(0, pos - _OFFLINE_NAV_PREFIX_MAX), pos));
  for (let i = 0; i < _OFFLINE_NAV_PREFIX_LOWER.length; i++) {
    const name = _OFFLINE_NAV_PREFIX_LOWER[i];
    if (pos >= name.length && tail.endsWith(name)) return pos - name.length;
  }
  return -1;
}
// The global-prefix chain, read BACKWARDS from a sink, standing in for the pattern's old
// `(?:^|[^.A-Za-z0-9_$])(?:PREFIX WS* (?:\? WS*)? \. WS*)*` head. The boundary is tested at EVERY
// chain length rather than only the longest, because a shorter chain can end on a whitespace
// character that is itself a legal boundary - `$window . ` in front of a bare sink matches with no
// chain at all, and only testing the longest chain would miss it.
function _offlineNavChainOk(src, index, requirePrefix) {
  let pos = index;
  let taken = 0;
  for (;;) {
    if ((taken > 0 || !requirePrefix) && _offlineNavBoundaryOk(src, pos)) return true;
    let scan = _offlineNavSkipWsBack(src, pos);
    if (scan === 0 || src.charAt(scan - 1) !== ".") return false;
    scan = _offlineNavSkipWsBack(src, scan - 1);
    if (scan > 0 && src.charAt(scan - 1) === "?") scan = _offlineNavSkipWsBack(src, scan - 1);
    const start = _offlineNavPrefixStart(src, scan);
    if (start < 0) return false;
    pos = start;
    taken++;
  }
}
// The `(?:^|[;})>\n\r\u2028\u2029])WS*` head a bare statement-position sink must follow. The run
// is inspected rather than skipped because a line break inside it is itself a legal delimiter.
function _offlineNavStatementStart(src, index) {
  let pos = index;
  while (pos > 0 && _OFFLINE_NAV_WS_RE.test(src.charAt(pos - 1))) {
    if (_OFFLINE_NAV_LINE_BREAK_RE.test(src.charAt(pos - 1))) return true;
    pos--;
  }
  return pos === 0 || _OFFLINE_NAV_STATEMENT_RE.test(src.charAt(pos - 1));
}
function _offlineNavTailAt(rx, src, index) {
  rx.lastIndex = index;
  return rx.test(src);
}
// The index of the first sink that navigates to a network URL literal, or -1. `prefixedOnly`
// drops the two UNPREFIXED shapes, for a script that declares its own binding.
function _offlineNavSinkIndex(src, prefixedOnly) {
  _OFFLINE_NAV_ANCHOR_RE.lastIndex = 0;
  for (let m = _OFFLINE_NAV_ANCHOR_RE.exec(src); m; m = _OFFLINE_NAV_ANCHOR_RE.exec(src)) {
    const at = m.index;
    const after = at + m[0].length;
    _OFFLINE_NAV_ANCHOR_RE.lastIndex = at + 1;
    if (m[0].length === 4) {
      if (_offlineNavTailAt(_OFFLINE_NAV_OPEN_TAIL_RE, src, after) &&
          _offlineNavChainOk(src, at, true)) return at;
      continue;
    }
    if (_offlineNavTailAt(_OFFLINE_NAV_PROP_TAIL_RE, src, after) &&
        _offlineNavChainOk(src, at, prefixedOnly)) return at;
    if (_offlineNavTailAt(_OFFLINE_NAV_ASSIGN_TAIL_RE, src, after) &&
        (_offlineNavChainOk(src, at, true) ||
         (!prefixedOnly && _offlineNavStatementStart(src, at)))) return at;
  }
  return -1;
}
// Does this script declare its OWN binding named `location`? Decided by TOKENIZING the declaration
// rather than by matching a character window over raw source, and MIRRORED helper for helper by
// `_offline_shadow_*` in the strict validator (`tools/validate/checks/resources.py`).
// This arm is a FALSE-POSITIVE REDUCER, not a security boundary. An author who wants an unprefixed
// sink ignored already has the aliasing bypass the CMH-OFFLINE-05 residual accepts, so a wrong
// SHADOW costs nothing new; a missed binding, on the other hand, deletes a script that navigates
// nothing. The window this replaced was wrong in both directions at once: a `location` merely
// MENTIONED in a comment, a string or a parameter default disarmed it, while a real binding it
// could not see (an arrow parameter, a method or `constructor` shorthand, a generator, a nested
// pattern that spends a bracket inside the window, a comment after `catch (`, a non-ASCII function
// name, anything past 400 characters) was missed. Neither was fixable inside the window: a boundary
// allowlist rejects the legitimate `const {href: location}` rename, and a non-ASCII identifier class
// breaks a real `var location<NBSP>= 1`, NBSP being JS whitespace.
// One LEFT-TO-RIGHT pass, no backtracking: each character is classified once, each comment, string,
// template and regex literal is skipped once, and the only look-ahead is a peek at the token that
// follows a name or a `)`, which reads the run after that token and nothing else - so the pass is
// linear, which is what #973 and #1045 bought and must not be traded away.
function _offlineShadowIdentChar(ch) {
  if (_OFFLINE_SHADOW_IDENT_ASCII_RE.test(ch)) return true;
  return ch.charCodeAt(0) >= 128 && !_OFFLINE_NAV_WS_RE.test(ch);
}
function _offlineShadowLineEnd(src, i) {
  while (i < src.length && !_OFFLINE_NAV_LINE_BREAK_RE.test(src.charAt(i))) i++;
  return i;
}
// An HTML comment opener is a line comment in a classic script (Annex B), so text after it is not
// code. The opener is ASSEMBLED rather than written out: this file is served INSIDE a script
// element, and a literal one in script data puts the HTML parser into its escaped state, after
// which the next start-tag sequence in the layer's own text starts double-escaped data and the end
// tag stops ending the element - which silently breaks the runtime in every document that embeds
// it. For the same reason no comment here may spell either tag out.
const _OFFLINE_SHADOW_HTML_COMMENT = "<" + "!--";
function _offlineShadowSkipComment(src, i) {
  if (src.startsWith("//", i) || src.startsWith(_OFFLINE_SHADOW_HTML_COMMENT, i)) return _offlineShadowLineEnd(src, i + 2);
  if (src.startsWith("/*", i)) {
    const at = src.indexOf("*/", i + 2);
    return at < 0 ? src.length : at + 2;
  }
  return -1;
}
// The identifier that follows `i`, ASCII-folded, or "" when the next token is not one.
function _offlineShadowNextWord(src, i) {
  const n = src.length;
  while (i < n) {
    const ch = src.charAt(i);
    if (_OFFLINE_NAV_WS_RE.test(ch)) { i++; continue; }
    const skipped = _offlineShadowSkipComment(src, i);
    if (skipped >= 0) { i = skipped; continue; }
    if (!_offlineShadowIdentChar(ch)) return "";
    let j = i + 1;
    while (j < n && _offlineShadowIdentChar(src.charAt(j))) j++;
    return _offlineNavAsciiLower(src.slice(i, j));
  }
  return "";
}
// `same_line` stops at a line terminator, for the two decisions where the grammar forbids one: no
// LineTerminator may precede `=>`, and a `{` on the next line after a call is a separate block
// statement rather than a method body (ASI puts a `;` between them).
function _offlineShadowNextSig(src, i, sameLine) {
  const n = src.length;
  while (i < n) {
    const ch = src.charAt(i);
    if (_OFFLINE_NAV_WS_RE.test(ch)) {
      if (sameLine && _OFFLINE_NAV_LINE_BREAK_RE.test(ch)) return "";
      i++;
      continue;
    }
    const skipped = _offlineShadowSkipComment(src, i);
    if (skipped >= 0) {
      if (sameLine && _OFFLINE_NAV_LINE_BREAK_RE.test(src.slice(i, skipped))) return "";
      i = skipped;
      continue;
    }
    return src.startsWith("=>", i) ? "=>" : ch;
  }
  return "";
}
// A `'`/`"` literal cannot carry a raw line terminator, so a quote with no partner on its own line
// is punctuation rather than the start of a literal that swallows the rest of the script - and
// swallowing it would hide a real binding, the direction that deletes an author's script. A
// LineContinuation is the exception the check must not trip over: a backslash before CRLF escapes
// BOTH characters, and reading only the CR left the LF looking like a bare line terminator, which
// ended the literal and handed its text to the tokenizer as code.
function _offlineShadowSkipQuoted(src, i) {
  const quote = src.charAt(i);
  const n = src.length;
  let j = i + 1;
  while (j < n) {
    const ch = src.charAt(j);
    if (ch === "\\") { j += src.startsWith("\r\n", j + 1) ? 3 : 2; continue; }
    if (ch === quote) return j + 1;
    if (_OFFLINE_NAV_LINE_BREAK_RE.test(ch)) return -1;
    j++;
  }
  return -1;
}
// Returns `[index, opened]`, where `opened` says a `${` substitution was entered - what follows is
// CODE, and an arrow parameter inside one binds a name like any other.
function _offlineShadowSkipTemplate(src, i) {
  const n = src.length;
  let j = i + 1;
  while (j < n) {
    const ch = src.charAt(j);
    if (ch === "\\") { j += src.startsWith("\r\n", j + 1) ? 3 : 2; continue; }
    if (ch === "`") return [j + 1, false];
    if (ch === "$" && src.charAt(j + 1) === "{") return [j + 2, true];
    j++;
  }
  return [n, false];
}
function _offlineShadowSkipRegex(src, i) {
  const n = src.length;
  let j = i + 1;
  let inClass = false;
  while (j < n) {
    const ch = src.charAt(j);
    if (ch === "\\") { j += 2; continue; }
    if (_OFFLINE_NAV_LINE_BREAK_RE.test(ch)) return -1;
    if (inClass) {
      if (ch === "]") inClass = false;
    } else if (ch === "[") {
      inClass = true;
    } else if (ch === "/") {
      j++;
      while (j < n && _offlineShadowIdentChar(src.charAt(j))) j++;
      return j;
    }
    j++;
  }
  return -1;
}
function _offlineShadowRegexOk(prev, prevWord) {
  if (prev === "w") return _OFFLINE_SHADOW_REGEX_PRECEDERS.indexOf(prevWord) >= 0;
  return prev !== ")" && prev !== "]";
}
// A declaration keyword is followed by the name or pattern it binds, so anything else means the
// word is not opening a declaration at all: a dynamic `import` call and `import.meta` are
// expressions, a side-effect `import "./x"` and a `using` CALL bind nothing, and `{const: 1}` or
// `{let: 1}` is a property key. Every one of those used to put the enclosing frame into binding
// mode and report a shadow for the next `location` it saw, which suppressed a real sink.
function _offlineShadowDeclStarts(after) {
  if (after === "{" || after === "[" || after === "*") return true;
  return after.length === 1 && _offlineShadowIdentChar(after);
}
function _offlineShadowFrame(ch, binding, decl, key, opener, template) {
  return { ch: ch, binding: binding, decl: decl, key: key, named: false, inDefault: false, candidate: false, opener: opener, template: template };
}
// A frame is pushed per bracket. It is a BINDING context when it is a declaration list, a parameter
// list (`function`, a generator, `catch`, a method or `constructor` shorthand, an arrow) or a
// destructuring pattern nested inside one, and an EXPRESSION context otherwise. Inside a binding
// context a name is a binding unless it is a property KEY, a computed key, or sits in a
// default-value expression - the shapes that used to disarm the rule by merely mentioning the name.
function _offlineLocalLocationShadow(src) {
  const n = src.length;
  const stack = [_offlineShadowFrame("", false, false, false, "", false)];
  let overDepth = 0;
  let pendingParams = false;
  let expectName = false;
  let pendingBreak = false;
  let prev = "";
  let prevWord = "";
  let noRegexBefore = 0;
  let i = 0;
  while (i < n) {
    const frame = stack[stack.length - 1];
    const ch = src.charAt(i);
    if (_OFFLINE_NAV_WS_RE.test(ch)) {
      if (_OFFLINE_NAV_LINE_BREAK_RE.test(ch)) pendingBreak = true;
      i++;
      continue;
    }
    if (ch === "/" || ch === "<") {
      const skipped = _offlineShadowSkipComment(src, i);
      if (skipped >= 0) {
        // A comment can carry the line break that ends a declaration, so it feeds the same ASI
        // flag rather than being skipped silently.
        if (_OFFLINE_NAV_LINE_BREAK_RE.test(src.slice(i, skipped))) pendingBreak = true;
        i = skipped;
        continue;
      }
    }
    // ASI ends a declaration at a line break once it has bound a name, unless the next token
    // continues the list. Without this, `let x` on its own line put every following `location` in
    // binding position and reported a shadow the source never declared. The decision is made HERE,
    // at the first token after the break, rather than by peeking from the break: peeking re-scanned
    // the whole run of trivia at every newline in it, which is quadratic (20,000 newlines cost 4.5s
    // in node and 57s in Python).
    if (pendingBreak) {
      pendingBreak = false;
      if (frame.decl && frame.named && !frame.inDefault) {
        if (!(ch === "," || (ch === "=" && !src.startsWith("=>", i)))) {
          frame.binding = false;
          frame.decl = false;
          frame.named = false;
        }
      }
    }
    if (ch === "/") {
      if (i >= noRegexBefore && _offlineShadowRegexOk(prev, prevWord)) {
        const end = _offlineShadowSkipRegex(src, i);
        if (end >= 0) { i = end; prev = "]"; prevWord = ""; continue; }
        // A literal that never closes would be re-scanned from every later `/` on the same line,
        // which is quadratic; one failed scan settles the whole line instead.
        noRegexBefore = _offlineShadowLineEnd(src, i);
      }
      prev = "/"; prevWord = ""; i++; continue;
    }
    if (ch === "'" || ch === '"') {
      const end = _offlineShadowSkipQuoted(src, i);
      if (end >= 0) { i = end; prev = "]"; prevWord = ""; continue; }
      prev = ch; prevWord = ""; i++; continue;
    }
    if (ch === "`") {
      const scanned = _offlineShadowSkipTemplate(src, i);
      i = scanned[0];
      if (scanned[1]) {
        if (stack.length < _OFFLINE_SHADOW_MAX_DEPTH) stack.push(_offlineShadowFrame("$", false, false, false, "", true));
        else overDepth++;
      }
      prev = "]"; prevWord = ""; continue;
    }
    if (_offlineShadowIdentChar(ch)) {
      let j = i + 1;
      while (j < n && _offlineShadowIdentChar(src.charAt(j))) j++;
      const word = _offlineNavAsciiLower(src.slice(i, j));
      const member = prev === ".";
      i = j;
      prev = "w";
      prevWord = member ? "" : word;
      if (member) continue;
      if (expectName) {
        // The name a `function` or `class` declaration binds.
        expectName = false;
        if (word === "location") return true;
        continue;
      }
      if (_OFFLINE_SHADOW_DECL_KEYWORDS.indexOf(word) >= 0) {
        if (_offlineShadowDeclStarts(_offlineShadowNextSig(src, i, false))) {
          frame.binding = true;
          frame.decl = true;
          frame.named = false;
          frame.inDefault = false;
        }
        continue;
      }
      if (word === "function" || word === "class" || word === "catch") {
        // Gated the same way a declaration keyword is: `{class: location}` and
        // `[{catch: 1}, f(location)]` are property KEYS, and letting them arm the
        // name/parameter-list state made an unrelated later call look like a declaration.
        if (_offlineShadowNextSig(src, i, false) !== ":") {
          expectName = word !== "catch";
          pendingParams = word !== "class";
        }
        continue;
      }
      if ((word === "of" || word === "in") && frame.ch === "(" && frame.binding) {
        // The head of `for (const x of EXPR)` turns to an EXPRESSION after `of`/`in`, exactly as a
        // declarator does after `=`. Without this, the ordinary
        // `for (const [k, v] of Object.entries({location, ...}))` idiom read `location` as a nested
        // pattern and reported a shadow nothing declared.
        frame.inDefault = true;
        continue;
      }
      if (frame.binding && !frame.inDefault) frame.named = true;
      if (word !== "location") continue;
      // A property KEY, a member access, a call or an index - a declarator name is never followed
      // by any of them, so none of these is the binding the arm looks for.
      const nextAfterName = _offlineShadowNextSig(src, i, false);
      if (nextAfterName === ":" || nextAfterName === "." || nextAfterName === "(" || nextAfterName === "[") continue;
      // `import {location as renamed}` binds `renamed`; the name before `as` is the imported one,
      // exactly like the key half of `{location: renamed}`.
      if (_offlineShadowNextWord(src, i) === "as") continue;
      if (frame.binding && !frame.inDefault) return true;
      // The arrow test comes BEFORE the default-value skip: `let f = location => {}` reads
      // `location` inside an initializer, and it is still that arrow's parameter.
      if (_offlineShadowNextSig(src, i, true) === "=>") return true;
      if (frame.inDefault) continue;
      frame.candidate = true;
      continue;
    }
    if (ch === "(" || ch === "[" || ch === "{") {
      const params = pendingParams && ch === "(";
      // A `[` where an object pattern expects a KEY is a computed key, not a nested pattern:
      // `const {[location]: x}` reads the outer binding rather than declaring one.
      const computedKey = ch === "[" && frame.ch === "{" && (prev === "{" || prev === ",");
      const binding = params || (frame.binding && !frame.inDefault && !computedKey);
      // A parameter list carries no opener, so the method rule below cannot fire on the function's
      // own name: `function f(a = location) {}` declares no `location`. A `]` or a closing quote IS
      // kept, because a computed or quoted method name ends in one.
      const opener = params || ch !== "(" ? "" : (prev === "]" ? "]" : prevWord);
      if (stack.length < _OFFLINE_SHADOW_MAX_DEPTH) stack.push(_offlineShadowFrame(ch, binding, false, computedKey, opener, false));
      else overDepth++;
      pendingParams = false;
      expectName = false;
      prev = ch; prevWord = ""; i++; continue;
    }
    if (ch === ")" || ch === "]" || ch === "}") {
      if (overDepth > 0) {
        overDepth--;
      } else if (stack.length > 1) {
        const done = stack.pop();
        const parent = stack[stack.length - 1];
        if (done.template && ch === "}") {
          const scanned = _offlineShadowSkipTemplate(src, i);
          i = scanned[0];
          if (scanned[1]) {
            if (stack.length < _OFFLINE_SHADOW_MAX_DEPTH) stack.push(_offlineShadowFrame("$", false, false, false, "", true));
            else overDepth++;
          }
          prev = "]"; prevWord = ""; continue;
        }
        if (ch === ")" && done.candidate) {
          // `=>` may not be preceded by a line terminator, and a `{` on a later line is a separate
          // block statement - `report(location)` then a block is a CALL, not a method definition -
          // so both peeks are same-line. A method shorthand also only exists inside an object
          // literal or a class body.
          const after = _offlineShadowNextSig(src, i + 1, true);
          if (after === "=>") return true;
          if (after === "{" && parent.ch === "{" && done.opener &&
              _OFFLINE_SHADOW_NON_METHOD.indexOf(done.opener) < 0) return true;
        }
        // A name read inside a computed KEY, or inside a default-value expression, is a reference
        // rather than a parameter, so it must not travel outwards and make the group it sits in
        // look like a parameter list: `(q = foo(location)) => {}` and `({[location]: x}) => {}`
        // declare nothing.
        if (done.candidate && !done.key && !parent.inDefault) parent.candidate = true;
        if (parent.binding && !parent.inDefault) parent.named = true;
      }
      // A keyword read INSIDE a group cannot arm a bracket outside it.
      pendingParams = false;
      expectName = false;
      prev = ch; prevWord = ""; i++; continue;
    }
    if (ch === "." && src.startsWith("...", i)) {
      // A rest element is a BINDING (`function f(...location)`, `const {a, ...location}`), so its
      // dots must not leave the name looking like a member access.
      i += 3; prev = ","; prevWord = ""; continue;
    }
    if ((ch === "+" && src.startsWith("++", i)) || (ch === "-" && src.startsWith("--", i))) {
      // A postfix `++`/`--` ends a VALUE, so the `/` after it divides rather than opening a regex
      // literal whose scan would swallow the declaration behind it.
      i += 2; prev = "]"; prevWord = ""; continue;
    }
    if (ch === ";") {
      frame.binding = false;
      frame.decl = false;
      frame.named = false;
      frame.inDefault = false;
      pendingParams = false;
      expectName = false;
    } else if (ch === ",") {
      frame.inDefault = false;
      frame.named = false;
    } else if (ch === "=") {
      if (src.startsWith("=>", i)) { i += 2; prev = ">"; prevWord = ""; continue; }
      if (!src.startsWith("==", i) && _OFFLINE_SHADOW_COMPOUND_OPS.indexOf(prev) < 0) frame.inDefault = true;
    }
    prev = ch; prevWord = ""; i++;
  }
  return false;
}
function _offlineScriptNavigatesToNetwork(body) {
  const src = String(body || "");
  if (_offlineNavSinkIndex(src, false) < 0) return false;
  // A script that declares its OWN `location` binding is talking about that object, not the
  // document's - `const location = { href: "" }; location.href = <url>` navigates nothing, and
  // deleting the whole script over it is the content loss this strip must not cause. So when a
  // local binding is present, only the PREFIXED sinks still count: `window.location` names the real
  // one no matter what a local `location` shadows. This costs nothing an attacker did not already
  // have - aliasing (`var l = location; l.href = <url>`) is a cheaper bypass that has always
  // worked, and both are listed in the CMH-OFFLINE-05 residual.
  if (_offlineLocalLocationShadow(src)) return _offlineNavSinkIndex(src, true) >= 0;
  return true;
}
function _offlineScriptHasNetworkEgress(body) {
  return _offlineScriptHasNetworkImport(body) || _offlineScriptNavigatesToNetwork(body);
}
// The ids the review layer owns as DATA. Every one is emitted as `type="application/json"` (the
// strict validator requires exactly that for all four), and their text is written by REVIEWERS, so a
// comment that legitimately quotes an egress shape must not be read as code. That exemption used to
// be claimed by ID ALONE and tested BEFORE the runnable-type test, so a decoy that merely BORROWED
// one of the ids sailed past both offline strips with no aliasing and no obfuscation - and past
// nothing else, since the strict validator's own egress check never had such a skip and would then
// REJECT the very file the exporter had preserved it in. The vendored payload id is deliberately NOT
// in this set: it is infrastructure resolved by position (see `_offlineResolveVendoredPayload`), and
// a script that merely borrows the id is authored CONTENT that must clear the same scan as any other.
const _OFFLINE_RESERVED_DATA_ID_RE = /^(?:embeddedComments|handledCommentIds|commentableHtmlLayer|reviewedSections)$/;
// So the exemption is EARNED rather than claimed: a reserved-id script whose type would RUN is
// retyped to inert data before anything else reads the document, and the strips then exempt it on
// the ordinary type test - the same rule the validator applies. Retyping rather than DELETING is the
// point: these blocks hold the review state, and a legacy or hand-authored document may spell one
// without a type, so the safe move is to keep the bytes verbatim and take away only the ability to
// run them. It also repairs such a block's TYPE for the strict validator, and protects it from the
// renderer strip, which never had an id skip at all.
function _neutralizeOfflineReservedDataScripts(doc) {
  const neutralized = [];
  // Template-parked too, so a reserved-id block a script later adopts is inert data by then.
  _offlineQueryAll(doc, "script[id]").forEach(function (s) {
    if (!_OFFLINE_RESERVED_DATA_ID_RE.test(s.getAttribute("id") || "")) return;
    // Broad on purpose: this pass REPAIRS a type rather than deleting anything, so retyping one
    // block more than a browser would have run costs nothing, and the validator requires exactly
    // `application/json` on these ids anyway. It is also what makes the `neutralized` override in
    // `_offlineScriptSrcFetches` mean "was runnable as authored" for every spelling this pass has
    // already rewritten.
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return;
    s.setAttribute("type", "application/json");
    neutralized.push(s);
  });
  return neutralized;
}
// How many neutralized blocks the exported file actually KEEPS. Counting at neutralization time
// would over-report: a later pass legitimately removes some of the same elements (a network `src`
// script), and the toast would then claim one script was both removed and kept. Membership is
// decided by RE-WALKING the document, which is the only test that is right for a template-parked
// block: `doc.contains` reports every one of them as gone (a fragment node is inside no element),
// and a `parentNode` test would report a block left orphaned inside a detached subtree as kept.
function _offlineCountKeptNeutralized(doc, neutralized) {
  // A Set, not indexOf: a document may legitimately (or hostilely) carry many reserved-id blocks,
  // and a linear scan per neutralized element would make the count quadratic in that number.
  const live = new Set(_offlineQueryAll(doc, "script[id]"));
  return neutralized.filter(function (s) { return live.has(s); }).length;
}
// A script does not always load through `src`: an SVG <script> uses `href` (SVG2) or the legacy
// `xlink:href`, and its body is EMPTY - so a `script[src]` selector never saw it and the inline
// egress scan below (which reads `textContent`) had nothing to read. Such a script rode into a file
// that promises zero network with only the CSP between it and the fetch, and the strict validator
// mirrored the same blind spot. The set is mirrored by the validator's `SCRIPT_LOAD_ATTRS`, pinned
// by `test_the_python_and_js_script_load_attributes_agree`.
const _OFFLINE_SCRIPT_LOAD_ATTRS = ["src", "href", "xlink:href"];
const _OFFLINE_SVG_NS = "http://www.w3.org/2000/svg";
// The URLs a `ping` list really names, tokenized the way HTML tokenizes it: on ASCII whitespace
// ONLY (tab, LF, FF, CR, space), written as literal code points because the two engines' whitespace
// classes disagree exactly where this boundary decides whether a beacon is live. Mirrored by the
// validator's own split, so an empty or ASCII-whitespace-only value is a no-op on BOTH sides while
// an NBSP or U+FEFF value - which a browser resolves as a relative target and POSTs to - is a real
// one on both. Returns the count, so a caller can ask "does this name anything?" without repeating
// the split.
function _offlinePingTargets(value) {
  return (value || "").split(/[\t\n\f\r ]+/).filter(function (t) { return t !== ""; }).length;
}
// Whether this `<script>`'s `src` is a reference a browser would really request. The strict
// validator's self-contained `src` arm asks the same question with `script_code_runs`, pinned to
// `_offlineScriptCodeRuns` over a shared corpus of ATTRIBUTE SETS - the whitespace class and every
// residual shape included - by `test_the_python_and_js_script_code_runs_predicates_agree`, which
// evaluates that function in a real JS engine.
// HTML decides it by TYPE, and the answer is exactly the set of scripts a browser RUNS: "prepare the
// script element" makes a script whose type is not a JavaScript MIME type, `module`, `importmap` or
// `speculationrules` a DATA BLOCK and returns BEFORE the fetch step, and for the last two keyword
// types the `src` step fires an `error` event and returns, because external import maps and external
// speculation rule sets are not supported (a ruleset arrives inline or through the
// `Speculation-Rules` response header, never through `src`). So only a classic or module script
// fetches. It reads the whole ELEMENT rather than the type string alone (issue #1171): a MIME
// PARAMETER, `nomodule`, the legacy `event`+`for` pair, a whitespace-only `type` and the `language`
// fallback each make a script a browser never runs, so its `src` is a dead attribute and deleting
// the element over it cost the author their content for a request nobody makes. Named separately
// from the runnable-type predicate because it answers a DIFFERENT question - would a browser FETCH
// this, not would it RUN this - and a future HTML change adding an external path for either keyword
// type lands here. The `neutralized` branch has no validator counterpart on purpose: the gate reads
// the document as AUTHORED, where such a block is still a runnable script, so both sides call it a
// loader.
function _offlineScriptSrcFetches(s, neutralized) {
  // A block the exporter itself neutralized was RUNNABLE as authored, so its `src` was a real load
  // and the element goes - a decoy that borrowed a reserved layer id must not buy itself the
  // data-block treatment with a type this very export just rewrote.
  if (neutralized && neutralized.has(s)) return true;
  return _offlineScriptCodeRuns(s);
}
// Take the load away, and take no more than that. `src` loads on a script a browser RUNS, and an
// `href` / `xlink:href` loads on an SVG one, so those elements go (dropping just the attribute from
// an SVG script would start EXECUTING a body SVG2 says is ignored while `href` is present). On a
// DATA BLOCK the same `src` is inert - the browser never requests it - so removing the element would
// destroy an author's data over a dead attribute; the attribute alone goes, exactly as it does for
// the inert `href` case below, which keeps the export free of network-looking references without
// costing content. An ACTIVE-DATA block (`importmap`, `speculationrules`) is the one shape whose
// `src` is left ALONE here: the active-data pass judges the BLOCK by it - a browser hard-fails a map
// or a ruleset that carries one, so that pass removes the whole element - and clearing the attribute
// first would hide it from that pass and leave a map the SOURCE browser ignored live in the export.
// An exporter must never add behavior the source did not have. On an HTML script the `href` /
// `xlink:href` spellings are inert too - they fetch nothing, in HTML or in XHTML - so deleting the
// element would destroy an author's running code for a dead attribute; the attribute alone is
// removed instead, which leaves the strict validator (whose flat tokenizer has no namespace to
// consult and so reads both those attributes on every script) nothing to complain about. Returns
// whether the ELEMENT was removed, so one carrying two network attributes is counted exactly once.
function _offlineStripScriptLoad(s, neutralized) {
  if (_offlineIsNetworkUrl(s.getAttribute("src"))) {
    if (_offlineScriptSrcFetches(s, neutralized)) { s.remove(); return true; }
    if (!_offlineActiveDataScriptType(s.getAttribute("type"))) s.removeAttribute("src");
  }
  const loading = ["href", "xlink:href"].filter(function (attr) {
    return _offlineIsNetworkUrl(s.getAttribute(attr));
  });
  if (!loading.length) return false;
  if (s.namespaceURI === _OFFLINE_SVG_NS) { s.remove(); return true; }
  loading.forEach(function (attr) { s.removeAttribute(attr); });
  return false;
}
// Every matching element, INCLUDING the ones parked inside a <template>. A template's children live
// in its inert `content` fragment, which `doc.querySelectorAll` cannot see - but the validator's
// flat tokenizer reads those tags plainly, so a network-loading element parked in a template used to
// ride untouched into the export and then be REJECTED by the exporter's own `--strict` gate.
// Templates nest, so the walk recurses.
function _offlineQueryAll(root, selector) {
  const found = [];
  const walk = function (node) {
    node.querySelectorAll(selector).forEach(function (el) { found.push(el); });
    node.querySelectorAll("template").forEach(function (t) { if (t.content) walk(t.content); });
  };
  walk(root);
  return found;
}
// The link relations that make a `<link>` FETCH, and the reading of the `rel` list that decides
// it. Both are the exporter's copy of the strict validator's `FETCHING_LINK_RELS` and
// `link_rel_tokens`, pinned to them by a parity test over one corpus: a relation only the GATE
// knows is a link this strip keeps and the export's own `--strict` run then rejects, and one only
// the STRIP knows is a link the export deletes while the gate certifies the file.
const _OFFLINE_FETCHING_LINK_RELS = ["stylesheet", "preload", "modulepreload", "preconnect", "dns-prefetch", "icon", "apple-touch-icon", "apple-touch-icon-precomposed", "manifest", "prefetch", "prerender"];
// HTML tokenizes a `rel` list on ASCII WHITESPACE only, which is neither engine's own class: a JS
// `\s` also takes U+FEFF and Python's argument-less `str.split()` also takes U+001C-U+001F, and
// both take NBSP and the vertical tab - so each of those made one side see two relations where the
// other saw one, in both directions. Written out as literal escapes on both sides for the same
// reason the CSS and network-URL classes are (#961).
const _OFFLINE_REL_WS_RE = /[\t\n\f\r ]+/;
function _offlineLinkRelTokens(rel) {
  // ASCII-only case folding, because a `rel` keyword is matched ASCII case-insensitively: a
  // Unicode fold maps look-alikes (U+212A onto `k`, U+017F onto `s`) onto a real relation, and it
  // does so differently in the two engines.
  return String(rel || "").replace(/[A-Z]/g, function (c) {
    return String.fromCharCode(c.charCodeAt(0) + 32);
  }).split(_OFFLINE_REL_WS_RE).filter(Boolean);
}
function _offlineLinkLoads(rel) {
  return _offlineLinkRelTokens(rel).some(function (r) {
    return _OFFLINE_FETCHING_LINK_RELS.indexOf(r) >= 0;
  });
}
// The two SPECULATIVE-CONNECTION relations, a strict subset of the fetching set above. They are
// singled out because an offline export may not carry one AT ALL, whatever its href resolves to
// (#1076), while every other fetching relation goes only when its href is a network URL.
const _OFFLINE_SPECULATIVE_LINK_RELS = ["preconnect", "dns-prefetch"];
function _offlineLinkSpeculates(rel) {
  return _offlineLinkRelTokens(rel).some(function (r) {
    return _OFFLINE_SPECULATIVE_LINK_RELS.indexOf(r) >= 0;
  });
}
// The `rel` list with every speculative token dropped, or null when nothing else is left - in which
// case the ELEMENT goes rather than the attribute. Mirrored by the validator's `_link_speculates`,
// which rejects on the same reading; both are evaluated over one corpus by a parity test.
function _offlineRelWithoutHints(rel) {
  const kept = _offlineLinkRelTokens(rel).filter(function (r) {
    return _OFFLINE_SPECULATIVE_LINK_RELS.indexOf(r) < 0;
  });
  return kept.length ? kept.join(" ") : null;
}
// What counts as a nested document worth keeping. The HTML ASCII whitespace set, written as literal
// escapes for exactly the reason `_OFFLINE_REL_WS_RE` above is: JS `String.prototype.trim()` also
// takes NBSP, U+FEFF and the whole Unicode Zs class, while Python's `str.strip()` also takes
// U+001C-U+001F and U+0085 - so "whitespace-only" meant two different things on the two sides, and
// the gate's advisory promised a preserved block the exporter never inserted (`srcdoc="&#xFEFF;"`)
// and denied one it did (`srcdoc="&#28;"`). One literal class, spelled the same in both engines, is
// the only way they agree. The validator's copy is the matching `nested.strip(" \t\n\f\r")` in
// `tools/validate/checks/layer_parts/20-resources.py`.
const _OFFLINE_SRCDOC_CONTENT_RE = /[^\t\n\f\r ]/;
// True when the frame did not render at all because it, or an ancestor, is declaratively HIDDEN.
// The placement rule is that the block is visible to exactly the reader the nested document was
// visible to, and a `hidden` frame showed nobody anything - so its block is hidden too, or an export
// would newly EXPOSE markup that never rendered (worse for a `<p hidden>`, where the paragraph
// re-anchor lifts the block out of the hidden container). Only the declarative attribute is read:
// the exporter parses a detached document with no stylesheets and no layout, so a CSS-hidden
// subtree is not knowable here, and guessing would be worse than the bounded rule.
function _offlineSrcdocHidden(frame) {
  for (let n = frame; n && n.nodeType === 1; n = n.parentNode) {
    if (n.namespaceURI === _OFFLINE_HTML_NS && n.hasAttribute("hidden")) return true;
  }
  return false;
}
// Where a preserved block may legally sit. The block is FLOW content and an `<iframe>` is PHRASING,
// so a block left inside a `<p>` would make the recipient's parser close the paragraph at the
// `<details>` start tag - re-parenting any text after the frame and leaving a stray empty `<p>`, so
// the export would not be serialize/reparse stable. A frame inside a paragraph therefore anchors
// after that PARAGRAPH. `<p>` is the whole rule rather than a phrasing-host list, because it is the
// only element the parser auto-closes on a `details` start tag. The walk stops at the first
// NON-HTML ancestor: an `<iframe>` inside `<svg><foreignObject>` is HTML-namespaced and does render,
// but the `<p>` auto-close does not reach across foreign content, so re-anchoring to an HTML `<p>`
// outside the `<svg>` would move the text out of the container the frame actually renders in.
function _offlineSrcdocAnchor(frame) {
  for (let n = frame.parentNode; n && n.nodeType === 1 && n.namespaceURI === _OFFLINE_HTML_NS; n = n.parentNode) {
    if (n.localName === "p") return n.parentNode ? n : frame;
  }
  return frame;
}
// Keep a removed `srcdoc` beside its frame as escaped inert TEXT (issue #1119). The four grounds
// that rejected SANITIZING the nested document (CMH-OFFLINE-04) all turn on PARSING it; this parses
// nothing. It needs only escaping on this side and NOTHING on the gate side - the presence rule is
// unchanged, so the exporter and the strict validator still agree by construction - and it lands
// content both sides already read as text, which is the same precedent that lets a `<base>` keep its
// `target` and a reserved-id block become inert JSON.
//
// The placement rule is one sentence: the block goes where the FRAME is, so it is visible to exactly
// the reader the nested document was visible to. That is what settles the parked cases rather than a
// list of exceptions - a `<template>`-parked frame renders nothing and neither does its block; a
// `<noscript>`-parked one renders nothing for a scripting-ON reader (the body is raw text in a
// `display:none` element) and renders for the scripting-OFF reader, and the block follows it in both
// directions. Nothing is lost that was ever shown, and nothing is shown that was not.
//
// Bounds, each of which would otherwise add content where none was lost:
// - EMPTY or WHITESPACE-ONLY value (`_OFFLINE_SRCDOC_CONTENT_RE`): nothing to keep, so no block - a
//   `<summary>` announcing a preserved document over an empty `<pre>` is noise. Trimming is safe
//   HERE and would not be on the removal rule: the attribute still goes on PRESENCE, so what is
//   PRESERVED and what is REMOVED are separate questions and only the second one the gate sees.
// - FOREIGN namespace: an `<iframe>` inside `<svg>` renders nothing in any browser, so its nested
//   document was never visible - and an HTML block serialized inside foreign content would not
//   render either. The frame is still emptied; only the block is skipped. An `<iframe>` inside
//   `<foreignObject>` IS HTML-namespaced and does render, so it correctly gets one.
// - The anchor is `_offlineSrcdocAnchor`'s (see there), and a block already sitting after that
//   anchor is stepped over: two frames in ONE paragraph share an anchor, so inserting each at
//   `anchor.nextSibling` would emit them in REVERSE order and pair each nested document with the
//   wrong frame - the one thing a reader auditing preserved markup must be able to trust.
// - `cm-skip`: the block is layer-injected content inside the content root, exactly like every other
//   in-root control, so it must stay out of the section-hash and document-hash walks (`_cmhScanSkip`
//   here, `_SKIP_CLASSES` in the Python `section_hash`) and out of the anchor/selection walks.
//   Without it an export would shift its own section hashes, flip an already-reviewed section to
//   "changed", and invalidate the validated stamp it carries - trading one loss for a worse one. It
//   also means a Markdown export omits the block, which loses nothing: an `<iframe>` has no Markdown
//   representation either, so the nested document was never in a `.md` export to begin with.
// Collapsed `<details>`, because a `srcdoc` can be a whole document and an always-open `<pre>` would
// dominate the page; bounding the LAYOUT beats capping the TEXT, which would reintroduce the loss.
// The text is never capped or truncated. Two normalizations reach it, and both are there so the
// export is a FIXED POINT: CR and CRLF become LF here (the HTML tokenizer does that to any text it
// reparses, so a script-built `srcdoc` carrying CRLF would otherwise come back different on the
// second export), and the file-wide `\n{3,}` -> `\n\n` collapse every offline serialization already
// applies reaches it exactly as it reaches an authored `<pre>` - the block is treated as the code
// block it is rather than specially.
// Idempotent by construction: the attribute is gone, so a re-export finds no `srcdoc` and inserts
// nothing, and `textContent` means the markup is escaped once, by the serializer, never re-escaped.
function _offlinePreserveSrcdoc(frame, nested) {
  if (!nested || !_OFFLINE_SRCDOC_CONTENT_RE.test(nested)) return null;
  if (frame.namespaceURI !== _OFFLINE_HTML_NS) return null;
  let anchor = _offlineSrcdocAnchor(frame);
  const parent = anchor.parentNode;
  if (!parent) return null;
  while (anchor.nextElementSibling && anchor.nextElementSibling.classList
    && anchor.nextElementSibling.classList.contains("cmh-srcdoc-export")) {
    anchor = anchor.nextElementSibling;
  }
  const doc = frame.ownerDocument;
  const block = doc.createElementNS(_OFFLINE_HTML_NS, "details");
  block.setAttribute("class", "cm-skip cmh-srcdoc-export");
  if (_offlineSrcdocHidden(frame)) block.setAttribute("hidden", "");
  const summary = doc.createElementNS(_OFFLINE_HTML_NS, "summary");
  summary.textContent = "Nested <iframe srcdoc> document, emptied by Export Offline and kept here as inert text";
  const pre = doc.createElementNS(_OFFLINE_HTML_NS, "pre");
  const code = doc.createElementNS(_OFFLINE_HTML_NS, "code");
  code.textContent = nested.replace(/\r\n?/g, "\n");
  pre.appendChild(code);
  block.appendChild(summary);
  block.appendChild(pre);
  parent.insertBefore(block, anchor.nextSibling);
  return block;
}
// A preserved block that survived every later pass, counted the way `_offlineCountKeptNeutralized`
// counts a neutralized script: by IDENTITY, never by the class name. `cmh-srcdoc-export` is public
// markup a source can legitimately (or hostilely) already carry - a previously exported file
// re-imported, say - so a class-name walk would report an authored block as preserved markup and
// could claim more kept documents than there were emptied frames.
function _offlineCountKeptSrcdocs(doc, preserved) {
  if (!preserved.length) return 0;
  const mine = new Set(preserved);
  return _offlineQueryAll(doc, "details.cmh-srcdoc-export")
    .filter(function (el) { return mine.has(el); }).length;
}
function _stripOfflineNetworkLoads(doc, neutralized) {
  let dropped = 0;
  let clearedBases = 0;
  let clearedSrcdocs = 0;
  const preservedSrcdocs = [];
  const all = function (selector) { return _offlineQueryAll(doc, selector); };
  all("script").forEach(function (s) {
    if (_offlineStripScriptLoad(s, neutralized)) { dropped += 1; }
  });
  // The inline-egress scan walks templates too. Template content does not execute ON ITS OWN, but
  // serialization preserves it verbatim and a second, benign-looking script can adopt the fragment
  // and insert it, at which point a parked script runs - so a parked remote import or navigation
  // beacon is a real channel, not a dead one. It costs no false content loss either, because the
  // strict validator now reads template-parked scripts through its own separate view
  // (`template_scripts`) and applies the same rules, so the two agree in both directions.
  all("script").forEach(function (s) {
    // No id is exempt here any more. The layer's own data blocks are exempt because they are inert
    // DATA by the time this runs (`_neutralizeOfflineReservedDataScripts` made sure of it), which is
    // exactly the rule the strict validator applies; and an AUTHORED script that merely borrows a
    // reserved id - the vendored payload id included - is preserved as content by the strip only if
    // it clears the network-egress scan every other script has to clear.
    const active = _offlineActiveDataScriptType(s.getAttribute("type"));
    if (active) {
      if (_offlineActiveDataBlockIsRemovable(active, s)) { s.remove(); dropped += 1; }
      return;
    }
    // The broad type-only predicate on purpose: this pass only SCANS an inline body, where
    // over-inclusion is the safe direction - a body it skipped would be a network import nobody
    // looked at. The passes that DELETE on the element itself use `_offlineScriptCodeRuns`.
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return;
    const body = s.textContent || "";
    if (_offlineScriptHasNetworkEgress(body)) {
      s.remove();
      dropped += 1;
    }
  });
  // A per-element `referrerpolicy` overrides the document policy for that request, so a permissive
  // one would defeat the no-referrer meta on exactly the anchor an attacker planted.
  all("[referrerpolicy]").forEach(function (el) { el.removeAttribute("referrerpolicy"); });
  // `preconnect` and `dns-prefetch` go UNCONDITIONALLY, whatever their href parses as (#1076).
  // Every other fetching relation is removed only when its href is a network URL, because deleting
  // a local reference would take an author's CONTENT away - a stylesheet, an icon, a prefetched
  // page. These two take nothing: their whole purpose is to make the browser reach out EARLY, and
  // they show a reader nothing at all, so the same reasoning that drops a `speculationrules` block
  // outright applies. The network-URL predicate is the wrong LAYER for them rather than merely too
  // narrow. Their leak is a NAME RESOLUTION rather than a connection, so the TCP-listener probe
  // that settled that predicate's scheme boundary (#993) structurally cannot see one - which is why
  // a hint in a scheme the predicate reads as local (`ftp:`, a custom scheme), and a relative or
  // same-document one, used to ride into a zero-network export. A DNS-capable observer (a Chromium
  // netlog, read as HOST_RESOLVER events rather than as raw text) then measured ZERO resolver
  // activity for these two rels in Chromium 149 - not only for a non-fetchable scheme but for the
  // `http:` and `https:` CONTROL hints too, from a `file:` and an `http:` document alike, with
  // Playwright's `--disable-background-networking` removed and `NetworkPrediction` enabled, while
  // an ordinary image reference to an http host in the same document did produce a resolver job. A
  // control that measures zero cannot license a boundary: the instrument cannot separate "this
  // scheme is inert" from "this build does not drive the hint", so no measurement supports keeping
  // a hint in ANY scheme. Removing them outright costs nothing and needs no engine to be right.
  // What goes is the HINT, not necessarily the ELEMENT: a `rel` that mixes a hint with a content
  // relation (`rel="alternate preconnect"`) still names a reference a reader USES, so the
  // speculative tokens are dropped from the list and the element is removed only when nothing else
  // is left. What survives is then judged by the network-href pass below as the relation it also
  // is, so a remote stylesheet that also carried a hint is still stripped as a loader.
  // The strict validator applies the same rule to an offline document on the REL ALONE, so the two
  // sides agree by construction rather than by two predicates staying in step. Namespace-blind on
  // purpose, exactly as the script LOAD attributes and the `base` href are: the validator's flat
  // tokenizer has no namespace to consult, so scoping this to the HTML namespace would make the
  // exporter KEEP a hint the gate then REJECTS.
  all("link[rel]").forEach(function (link) {
    const rel = link.getAttribute("rel");
    if (!_offlineLinkSpeculates(rel)) return;
    const kept = _offlineRelWithoutHints(rel);
    if (kept === null) link.remove();
    else link.setAttribute("rel", kept);
  });
  all("link[href]").forEach(function (link) {
    if (!_offlineIsNetworkUrl(link.getAttribute("href"))) return;
    if (_offlineLinkLoads(link.getAttribute("rel"))) link.remove();
  });
  const clearAttr = function (el, attr) {
    if (!el.hasAttribute(attr)) return;
    const value = el.getAttribute(attr) || "";
    const network = attr === "srcset" ? _offlineSrcsetHasNetwork(value) : _offlineIsNetworkUrl(value);
    if (!network) return;
    if (el.tagName === "IMG" && attr === "src") el.setAttribute("src", "data:image/gif;base64,R0lGODlhAQABAAAAACw=");
    else el.removeAttribute(attr);
  };
  all("meta[http-equiv]").forEach(function (m) {
    if ((m.getAttribute("http-equiv") || "").toLowerCase() === "refresh") m.remove();
  });
  // A <base href> loads nothing itself, which is why no pass here used to look at one - and every
  // pass above leaves a RELATIVE reference alone, which is the whole control case. A base element
  // REBASES every relative reference in the document onto the base it names, so the very relative
  // image or script reference this strip reads as local resolves off-host instead. Its blast radius
  // is what makes it different: one attribute re-points EVERY safe reference, so it is held to the
  // stricter `_offlineIsNonLocalRef` (ANY scheme, or an authority of two slashes/backslashes in
  // either order, after the URL parser's own input cleanup) rather than the network predicate the
  // per-resource passes use. The two are different KINDS of predicate, not two strictness settings:
  // the per-resource one asks "would a browser FETCH this", which is why its scheme set is closed
  // at what one measurably does (#993), while this one asks "is this reference self-contained",
  // which any scheme fails. The slash-less `https:host/` and backslash-authority `https:/\host/`
  // spellings the per-resource arm now also catches (#961) were caught here first, and a `blob:` or
  // `data:` base is caught only here. `base-uri 'none'` cannot be leaned on instead - a
  // meta-delivered policy does not bind a base element the parser already resolved before it. The href alone goes: a `target`
  // is not egress, and a RELATIVE base reaches no network at all (a root-relative one resolves
  // against the filesystem, which the ordinary local-path rules already cover), so clearing either
  // would be content loss. Namespace-blind on purpose, exactly as the script LOAD attributes
  // are: the strict validator's flat tokenizer has no namespace to consult, so scoping this to the
  // HTML namespace here would make the exporter KEEP an SVG-namespaced `base` href the gate then
  // REJECTS. An SVG `base` is a meaningless element either way, so agreement is worth more.
  // Counted, because this is the one strip that changes references which still WORK: it re-points
  // every relative reference, author `<a href>` navigation included, which no other pass here
  // touches. Silently doing that would leave the author guessing why their links moved.
  all("base").forEach(function (el) {
    if (el.hasAttribute("href") && _offlineIsNonLocalRef(el.getAttribute("href") || "")) {
      el.removeAttribute("href");
      clearedBases += 1;
    }
  });
  all("img").forEach(function (el) { clearAttr(el, "src"); clearAttr(el, "srcset"); });
  // `srcdoc` carries a WHOLE NESTED DOCUMENT as an attribute VALUE, which no pass here can see
  // into: every walk above visits ELEMENTS, and the markup in that string never becomes elements,
  // so an inline handler, a meta refresh, or a network loader parked inside it rode untouched into
  // an export - and past the strict validator, whose tag index reads the same string as attribute
  // text. The offline CSP does not close it either: `frame-src 'none'` blocks a `src` LOAD, but a
  // srcdoc frame is content the policy is INHERITED into rather than a fetch, and the inherited
  // policy still allows inline script, which can navigate the top-level document. So an offline
  // document may not carry one at all (issue #996) - the attribute goes unconditionally, and the
  // strict validator rejects any that remains, which is what makes the two sides agree by
  // construction. Recursively parsing the nested document on both sides is the alternative, and
  // keeping two independent parsers in step is the drift this whole file is written to avoid.
  // Unconditional, not value-inspected: a nested document is not something the zero-network promise
  // can judge, and a narrower test would leave the validator rejecting what this kept. The ELEMENT
  // stays (an author's `title`, sizing, and any local `src` are content); the nested document stops
  // RENDERING, but it is no longer LOST: `_offlinePreserveSrcdoc` keeps the markup beside the frame
  // as escaped inert text (issue #1119). Counted twice in the toast for that reason - what changed,
  // and what survived.
  all("iframe").forEach(function (el) {
    clearAttr(el, "src");
    if (!el.hasAttribute("srcdoc")) return;
    const nested = el.getAttribute("srcdoc") || "";
    el.removeAttribute("srcdoc");
    clearedSrcdocs += 1;
    // A preservation must never cost the export. The frame is already emptied at this point, which
    // is the pre-#1119 behavior and still passes `--strict`, so any failure here degrades to that
    // rather than aborting `_buildOfflineHtml` and turning Export Offline into an error toast. No
    // shape in the corpus reaches it - this is the invariant, not a known crash, so do not delete
    // it as defensive noise.
    try {
      const block = _offlinePreserveSrcdoc(el, nested);
      if (block) preservedSrcdocs.push(block);
    } catch (err) { void err; }
  });
  all("video").forEach(function (el) { clearAttr(el, "src"); clearAttr(el, "poster"); });
  all("audio").forEach(function (el) { clearAttr(el, "src"); });
  all("source").forEach(function (el) { clearAttr(el, "src"); clearAttr(el, "srcset"); });
  all("track").forEach(function (el) { clearAttr(el, "src"); });
  // An SVG `<image>` loads through `href` / `xlink:href`, and the `src` / `srcset` pair rides
  // along because the OTHER `<image>` - one authored in HTML content - is renamed to `img` by tree
  // construction and fetches through exactly those two. That HTML spelling is already cleared by
  // the `all("img")` pass above (it IS an `img` element in the DOM), so the two attributes here
  // only ever reach an SVG-namespaced `image`, where they fetch nothing. Clearing them anyway is
  // deliberate: the shared egress index the strict validator reads deliberately does not carry the
  // namespace its parser computes, so it must report `<image src>` to catch the HTML one, and a
  // strip that left the SVG one behind would have the gate REJECT a file this export just produced
  // - the CMH-OFFLINE-04 drift (#1165). Keeping both sides identical is the point; the namespace is
  // reachable here (`el.namespaceURI`) should that over-detection ever become worth closing.
  all("image").forEach(function (el) {
    clearAttr(el, "href"); clearAttr(el, "xlink:href"); clearAttr(el, "src"); clearAttr(el, "srcset");
  });
  all("use").forEach(function (el) { clearAttr(el, "href"); clearAttr(el, "xlink:href"); });
  // An SVG filter primitive fetches exactly like the `image` and `use` above, and was in neither
  // this list nor the strict validator's, so one rode into a zero-network export the gate then
  // certified clean (#992). One spelling reaches both namespaces: CSS compares a type selector
  // case-SENSITIVELY for an SVG-namespaced element and case-INSENSITIVELY for an HTML one, so
  // `feImage` is the portable spelling that matches both the SVG primitive and an `<feimage>`
  // authored outside `<svg>` (a current Chromium is laxer still and matches any casing, which is an
  // implementation detail nothing here relies on). That keeps this pass namespace-blind, exactly as
  // the validator's flat tokenizer is forced to be.
  all("feImage").forEach(function (el) { clearAttr(el, "href"); clearAttr(el, "xlink:href"); });
  // Hyperlink auditing: a click POSTs to every URL in `ping`. The offline CSP most likely absorbs
  // it (CSP Level 3 folds auditing into `connect-src`, which the offline policy sets to `'none'`),
  // but this strip is the layer that must not DEPEND on the CSP, and the directive's `ping-src`
  // history makes that coverage version-dependent. The attribute goes whatever it names, the way a
  // meta refresh does: a relative ping still POSTs, it shows the reader nothing, and it is
  // meaningless in a single-file export - and an unconditional rule is one this strip and the gate
  // cannot drift apart on. Scoped to the two elements HTML gives the attribute any meaning on (an
  // SVG anchor included, which the tag-name selector matches in either namespace), so an author's
  // `ping` bookkeeping on some other element is not silently deleted; the validator scopes it the
  // same way, which its tokenizer can do exactly since it reads tag NAMES.
  //
  // A value that names NO URL is left byte-identical instead, and what that means is read off
  // HTML's own tokenization rather than off either engine's idea of whitespace: the list is split
  // on ASCII whitespace ONLY. `String.trim()` and Python's `str.strip()` disagree about NBSP,
  // U+FEFF and U+001C-U+001F, so trimming would drift the two sides in both directions - an NBSP
  // ping is a live relative beacon (it POSTs to `/%C2%A0`) that a trimming gate would call empty
  // and bless, and an empty-after-trim value is one a trimming strip would remove from a file the
  // gate had certified byte-clean.
  all("a[ping], area[ping]").forEach(function (el) {
    if (!_offlinePingTargets(el.getAttribute("ping"))) return;
    el.removeAttribute("ping");
  });
  all("input[src]").forEach(function (el) {
    if ((el.getAttribute("type") || "").toLowerCase() === "image") clearAttr(el, "src");
  });
  all("form[action]").forEach(function (el) { clearAttr(el, "action"); });
  all("button[formaction], input[formaction]").forEach(function (el) { clearAttr(el, "formaction"); });
  all("object").forEach(function (el) { clearAttr(el, "data"); });
  all("embed").forEach(function (el) { clearAttr(el, "src"); });
  all("[background]").forEach(function (el) { clearAttr(el, "background"); });
  all("style").forEach(function (style) {
    style.textContent = _offlineCssNoNetwork(style.textContent || "");
  });
  all("[style]").forEach(function (el) {
    const next = _offlineCssNoNetwork(el.getAttribute("style") || "");
    if (next) el.setAttribute("style", next);
    else el.removeAttribute("style");
  });
  all("[clip-path], [cursor], [fill], [filter], [marker-end], [marker-mid], [marker-start], [mask], [stroke]").forEach(function (el) {
    _offlineStripPresentationUrl(el);
  });
  return { dropped: dropped, clearedBases: clearedBases, clearedSrcdocs: clearedSrcdocs, preservedSrcdocs: preservedSrcdocs };
}
function _stripOfflineRichRenderers(doc, neutralized) {
  // On a re-export of an already-offline document, remove any previously inlined library notice
  // comments so they are re-emitted exactly once (the inlined lib scripts below are stripped and
  // re-added the same way); otherwise each re-export would append another duplicate notice.
  const head = doc.head || doc.querySelector("head");
  if (head) {
    Array.prototype.slice.call(head.childNodes).forEach(function (n) {
      if (n.nodeType === 8 && _OFFLINE_LIB_NOTICE_ANY_RE.test(n.nodeValue || "")) {
        if (n.parentNode) n.parentNode.removeChild(n);
      }
    });
    // Libraries this exporter inlined on a previous pass carry their own marker, so remove them by
    // that marker rather than by recognizing their bundled text: a text heuristic that ever failed
    // would leave a stale 1 MB copy behind and append another on every re-export. The marker VALUE
    // must be one this exporter emits, so an authored element carrying the attribute for its own
    // bookkeeping is never silently deleted from the document.
  }
  doc.querySelectorAll("script[data-cmh-offline-lib], script[data-cmh-offline-lib-init]").forEach(function (s) {
    if (_offlineIsInlinedLibScript(s)) s.remove();
  });
  doc.querySelectorAll("script[src]").forEach(function (s) {
    // A renderer-shaped FILENAME is not on its own a reason to delete an element: the same
    // type test the load strip applies decides this too, so a DATA BLOCK that merely points at a
    // chart-shaped name keeps its body (its `src` fetches nothing, and the load strip below takes
    // the dead attribute). Without this, an `application/json` block whose `src` ended in a
    // chart bundle name was blessed by the gate and deleted here - exactly the gate/strip
    // divergence CMH-OFFLINE-04 exists to prevent.
    if (!_offlineScriptSrcFetches(s, neutralized)) return;
    const src = s.getAttribute("src") || "";
    if (/(^|\/)(?:mermaid(?:\.esm)?(?:\.min)?\.mjs|mermaid(?:\.min)?\.js|chart(?:\.umd)?(?:\.min)?\.js)(?:[?#]|$)/i.test(src) ||
        /\/chart\.js@/i.test(src)) {
      s.remove();
    }
  });
  doc.querySelectorAll("script").forEach(function (s) {
    // This pass DELETES an element on what its body says, so it asks the exact question - a
    // MIME-parameter, `nomodule`, `event`+`for`, whitespace-only-`type` or `language`-fallback
    // block is a stale shim no browser ever ran, and removing it costs an author content for
    // nothing (issue #1171). Same reasoning as the `script[src]` arm above, one step further in.
    if (!_offlineScriptCodeRuns(s)) return;
    const body = s.textContent || "";
    if (_OFFLINE_LAYER_SCRIPT_RE.test(body)) return;
    if (/mermaid/i.test(body) && (/\bimport\s*\(/.test(body) || /\bmermaid\.(?:initialize|run)\b/i.test(body) || /\.run\s*\(/.test(body))) {
      s.remove();
      return;
    }
    // Author code that USES the Chart global is kept: naming a bundle file (in a comment, say) must
    // not delete the very script the inlined library exists for. Only a loader shim - one that names
    // a bundle without using the global, or that disables it - is removed.
    if (/window\.Chart\s*=\s*undefined/i.test(body)) {
      s.remove();
      return;
    }
    if (!_OFFLINE_CHART_GLOBAL_RE.test(body) &&
        /chart(?:\.umd)?(?:\.min)?\.js|chart\.js@/i.test(body)) {
      s.remove();
    }
  });
}
// The vendored payload is INFRASTRUCTURE, not content: `tools/authoring/vendored_libs.py` places it
// outside the authored content root (immediately before `</body>`), and this exporter is the only
// thing that writes one. Resolving it as "the first element with that id" would instead hand an
// AUTHORED decoy inside the content region the win, and its compressed bytes would be inflated and
// inlined into an export whose own CSP is `script-src 'unsafe-inline'` - document-supplied bytes
// executing in a file the recipient believes is a clean skill-generated export. So require the id on
// a script OUTSIDE `#commentRoot`, and require EXACTLY one.
//
// Ambiguity is a distinct state from ABSENCE, and only absence is benign. A document with no
// infrastructure payload is the normal re-export case (an earlier Offline export consumed it), which
// legitimately falls back to the library copies already inlined in the file. So two candidates - or
// a document whose content boundary cannot be pinned down - must THROW rather than report "no
// payload": reporting absence would quietly hand the same export to those document-supplied copies,
// which is the substitution this whole rule exists to prevent.
//
// The BOUNDARY itself must be unambiguous for that rule to mean anything. A duplicate id is legal
// HTML and `getElementById` silently takes the first one, so a planted `id="commentRoot"` wrapped
// around the genuine root would re-point the boundary: the real payload would count as content and a
// decoy placed after the wrapper as infrastructure, handing the win straight back to the decoy.
//
// The payload id is matched as an ATTRIBUTE VALUE, never written as an id-attribute selector
// literal: this source is inlined verbatim into every export, and a literal would make an exported
// file look like it still carries a payload block to anything scanning its text.
//
// WHAT THIS DOES AND DOES NOT AUTHENTICATE (the boundary, stated so the next reader does not
// overestimate it). Position and uniqueness authenticate the payload against an author of the
// CONTENT REGION - the untrusted part of a tool-generated document - by making displacement of the
// genuine payload impossible without becoming visibly ambiguous. They prove nothing against an
// author of the WHOLE FILE, who can simply omit the genuine payload and put their own block before
// `</body>`: no rule about position can tell those apart, and such an author can already run script
// in the document anyway. Against that adversary the argument is the same as CMH-OFFLINE-07's - the
// zero-network CSP, and the fact that capture grants no capability the source document did not
// already have. Resolution deliberately runs on the DOCUMENT BEING EXPORTED rather than the live
// DOM, so a content-region script cannot rewrite the candidate set after the fact for a document
// served over http(s); under `file://` the export base falls back to a snapshot of the live DOM, so
// there the two are the same document and only the boundary above applies.
const _OFFLINE_PAYLOAD_ID = "cmhVendoredRichLibs";
const _OFFLINE_PAYLOAD_UNRESOLVED = "Offline export cannot identify the vendored rich-content payload in this document: it carries more than one, or its content root is missing or duplicated.";
function _offlineVendoredPayloadBlocks(node) {
  return Array.prototype.filter.call(node.querySelectorAll("script"), function (s) {
    return s.getAttribute("id") === _OFFLINE_PAYLOAD_ID;
  });
}
// `querySelectorAll` does not descend into a `<template>`'s content (it is a separate fragment), yet
// serialization preserves it and a script adopted out of a template runs, so a payload parked in a
// template would ride into an export that claims to carry none. The STRIP therefore walks template
// content recursively, carrying the outermost template ELEMENT as the block's anchor so containment
// is judged where the template actually sits in the document (a fragment node is inside no element).
// RESOLUTION deliberately does not walk templates: a template-parked block is inert and can never be
// this document's live payload.
function _offlinePayloadBlocksWithAnchor(node, anchor) {
  const found = _offlineVendoredPayloadBlocks(node).map(function (s) {
    return { el: s, anchor: anchor || s };
  });
  Array.prototype.forEach.call(node.querySelectorAll("template"), function (t) {
    if (t.content) Array.prototype.push.apply(found, _offlinePayloadBlocksWithAnchor(t.content, anchor || t));
  });
  return found;
}
function _offlineContentRoot(d) {
  // One boundary primitive for the whole layer (cmhContentRoot in 01-config.js): an id SELECTOR
  // (unlike getElementById) matches every element carrying the id, so a duplicate is visible there
  // rather than silently resolved away. The differing NULL POLICY stays here at the call site -
  // this resolver treats "no single content root" as ambiguous and refuses.
  return cmhContentRoot(d);
}
// Decide, ONCE and against the PRISTINE document, both which block is the payload and which blocks
// are infrastructure to strip. Deciding either later would judge containment against a document this
// exporter has already rearranged - the chart hoist legitimately moves an author script out of the
// content root - so an authored payload-id script would first become a second "infrastructure"
// candidate and then be deleted as one.
function _offlineResolveVendoredPayload(d) {
  const contentRoot = _offlineContentRoot(d);
  // Without a single content root there is no boundary to be outside OF, so nothing can be verified
  // as authored content - but a document with no block at all is still plainly payload-less.
  const infrastructure = _offlinePayloadBlocksWithAnchor(d, null).filter(function (b) {
    return !(contentRoot && contentRoot.contains(b.anchor));
  });
  const strip = infrastructure.map(function (b) { return b.el; });
  // Only a block that is not parked in a template can be this document's live payload.
  const live = infrastructure.filter(function (b) { return b.el === b.anchor; });
  if (!live.length) return { text: "", ambiguous: false, strip: strip };
  if (!contentRoot || live.length > 1) return { text: "", ambiguous: true, strip: strip };
  return { text: live[0].el.textContent || "{}", ambiguous: false, strip: strip };
}
function _offlineLiveDocNeedsRichLibs() {
  return !!root.querySelector(CMH_RICH_CONTENT_SEL);
}
// Inflating the bundle costs a megabyte of gunzip, so it is cached - but keyed on the PAYLOAD TEXT,
// never on "whichever document was asked first". The bytes that ship must come from the document
// being exported, and a script inside the content region can rewrite the live DOM before an export
// runs; keying on the text means a live-document prewarm is reused only when the export resolves
// byte-identical payload text, and anything else is resolved and inflated afresh.
let _offlineVendoredRichLibsCache = null;
function _offlineInflateVendoredPayload(text) {
  if (_offlineVendoredRichLibsCache && _offlineVendoredRichLibsCache.text === text) {
    return _offlineVendoredRichLibsCache.promise;
  }
  const pending = (async function () {
    const payload = JSON.parse(text || "{}");
    return {
      mermaid: await _offlineInflateVendoredScript(payload.mermaidGzipBase64),
      chartjs: await _offlineInflateVendoredScript(payload.chartjsGzipBase64),
      mermaidLicense: _offlinePayloadLicense(payload.mermaidLicense),
      chartjsLicense: _offlinePayloadLicense(payload.chartjsLicense),
    };
  })();
  // Only a SUCCESS is worth memoizing. A rejection cached forever would make one bad state - an idle
  // prewarm that raced a half-loaded document, say - stick for the rest of the session, so every
  // later export keeps failing on a document that is fine.
  const promise = pending.catch(function (e) {
    if (_offlineVendoredRichLibsCache && _offlineVendoredRichLibsCache.text === text) {
      _offlineVendoredRichLibsCache = null;
    }
    throw e;
  });
  _offlineVendoredRichLibsCache = { text: text, promise: promise };
  return promise;
}
// A notice read out of the payload JSON is untrusted input, so only a STRING counts. Coercing
// whatever the JSON held would turn `{}` or `true` into "[object Object]" / "true" - text that is
// not blank, so it would sail past the missing-notice refusal below and be emitted AS the MIT
// notice, which is the compliance break dressed up as a notice.
function _offlinePayloadLicense(value) {
  return typeof value === "string" ? value : "";
}
async function _offlineInflateVendoredScript(b64) {
  const raw = String(b64 || "").trim();
  if (!raw) return "";
  if (typeof DecompressionStream !== "function") {
    throw new Error("Offline export needs DecompressionStream support to unpack its vendored rich-content bundle.");
  }
  const bytes = Uint8Array.from(atob(raw), function (ch) { return ch.charCodeAt(0); });
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).text();
}
async function _offlineVendoredRichLibs(resolved) {
  if (resolved.ambiguous) {
    const err = new Error(_OFFLINE_PAYLOAD_UNRESOLVED);
    err.cmhPayloadUnresolved = true;
    throw err;
  }
  if (!resolved.text) return {};
  try { return await _offlineInflateVendoredPayload(resolved.text); }
  catch (e) {
    // An unresolvable payload is a different failure from a corrupt one, and saying so is what makes
    // the fail-closed path actionable instead of misleading.
    if (e && e.cmhPayloadUnresolved) throw e;
    throw new Error("Offline export could not parse the vendored rich-content bundle.");
  }
}
function _primeOfflineVendoredRichLibs() {
  if (!_offlineLiveDocNeedsRichLibs()) return;
  const warm = function () {
    const resolved = _offlineResolveVendoredPayload(document);
    if (!resolved.text) return;
    _offlineInflateVendoredPayload(resolved.text).catch(function () {});
  };
  if (typeof requestIdleCallback === "function") requestIdleCallback(warm, { timeout: 2000 });
  else setTimeout(warm, 0);
}
function _offlineDocUsesMermaid(doc) {
  const docRoot = doc.getElementById("commentRoot") || doc.body;
  return !!(docRoot && docRoot.querySelector(CMH_MERMAID_SEL));
}
function _offlineDocUsesCharts(doc) {
  const docRoot = doc.getElementById("commentRoot") || doc.body;
  return !!(docRoot && docRoot.querySelector(CMH_CHART_CANVAS_SEL));
}
// The chart-canvas selector above is a deliberate SUPERSET of what any one renderer draws, so the
// shape of a canvas is not evidence that Chart.js is needed: a canvas carrying
// data-cmh-chart-points / data-cmh-chart-source is drawn by the runtime's own 2D renderer
// (setupInteractiveCharts) and never calls Chart.js. Decide on evidence instead - a chart canvas the
// built-in renderer will NOT draw, or a surviving script that mentions the `Chart` global - so a
// document whose charts are all built-in does not carry a megabyte of dead library. The superset
// stays load-bearing: an author may attach their own Chart.js to any canvas, including a built-in
// one, and that still wins. Detection is deliberately lopsided - a false positive costs bytes, a
// false negative ships a chart that never renders - so it errs toward inlining. Two shapes are still
// out of its reach, both unchanged from before this decision existed: an author script loaded from a
// relative `src` (its body cannot be read here, and such a document is not self-contained anyway),
// and a chart canvas placed OUTSIDE the content root (the shape gate, and the author-time decision
// about which documents carry the vendored payload at all, are both scoped to that root).
function _offlineDocReferencesChartLib(doc) {
  const docRoot = doc.getElementById("commentRoot");
  return Array.prototype.some.call(doc.querySelectorAll("script:not([src])"), function (s) {
    // The layer's own data blocks carry reviewer text; skip them by id exactly as the network strip
    // does, so a comment quoting "Chart" cannot decide a megabyte. The vendored payload is NOT on
    // that list: it is inert `application/json` (the runnable-type check below already skips it),
    // while an AUTHORED runnable script that borrows the payload id is now preserved into the
    // export, so ignoring its evidence would ship a document whose chart script survives with no
    // library to call. The id list is shared with the neutralize pass, so the two can never drift;
    // it is redundant here now that such a block is inert data before this runs, and kept so the
    // evidence scan does not depend on that ordering to stay data-safe.
    if (_OFFLINE_RESERVED_DATA_ID_RE.test(s.getAttribute("id") || "")) return false;
    // A library THIS exporter inlined on an earlier pass is not the author's evidence; counting it
    // would make every re-export re-inline it forever.
    if (_offlineIsInlinedLibScript(s)) return false;
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return false;
    const body = s.textContent || "";
    // Only a script OUTSIDE the authored content root can be the review layer, so an author script
    // that happens to quote the layer's own tokens still counts as evidence.
    if ((!docRoot || !docRoot.contains(s)) && _OFFLINE_LAYER_DECL_RE.test(body)) return false;
    return _OFFLINE_CHART_GLOBAL_RE.test(body);
  });
}
// Mirror the bail conditions of the built-in renderer's own _chartConfig(): data that does not parse,
// or that yields no usable point, draws nothing - so such a canvas is NOT one the built-in renderer
// covers, and the library must still travel.
function _offlineParseChartData(raw) {
  try { return { ok: true, value: JSON.parse(String(raw || "").trim() || "null") }; }
  catch (e) { return { ok: false, value: null }; }
}
function _offlineChartDataUsable(parsed) {
  const points = Array.isArray(parsed) ? parsed : (parsed && parsed.points);
  if (!Array.isArray(points)) return false;
  return points.some(function (point) {
    return point && typeof point.label === "string" && point.label.trim() && Number.isFinite(Number(point.value));
  });
}
function _offlineDocNeedsChartLib(doc, referencesChartLib) {
  if (!_offlineDocUsesCharts(doc)) return false;
  const docRoot = doc.getElementById("commentRoot") || doc.body;
  const canvases = Array.prototype.slice.call(docRoot.querySelectorAll(CMH_CHART_CANVAS_SEL));
  const drawnByRuntime = function (canvas) {
    // Follow _chartConfig's precedence exactly: a resolvable source element WINS - unparseable
    // source JSON makes the renderer give up entirely, and only a source that parses FALSY lets it
    // fall back to the inline points.
    const sourceId = (canvas.getAttribute("data-cmh-chart-source") || "").trim();
    const source = sourceId ? doc.getElementById(sourceId) : null;
    if (source) {
      const parsed = _offlineParseChartData(source.textContent);
      if (!parsed.ok) return false;
      if (parsed.value) return _offlineChartDataUsable(parsed.value);
    }
    const inline = _offlineParseChartData(canvas.getAttribute("data-cmh-chart-points"));
    return inline.ok && _offlineChartDataUsable(inline.value);
  };
  if (!canvases.every(drawnByRuntime)) return true;
  return referencesChartLib === undefined ? _offlineDocReferencesChartLib(doc) : !!referencesChartLib;
}
function _offlineAppendInlineScript(doc, head, code, attrs) {
  const s = doc.createElement("script");
  Object.keys(attrs || {}).forEach(function (name) { s.setAttribute(name, attrs[name]); });
  s.textContent = _escClose(String(code || ""));
  head.appendChild(s);
}
function _offlineAppendLibNotice(doc, head, name, license) {
  // MIT requires the copyright + permission notice to accompany a redistributed copy of the library.
  // The Offline export inlines the library bytes, so emit its notice as an HTML comment beside it.
  // Neutralize any "--" so the comment cannot terminate early or serialize as invalid HTML (the
  // vendored MIT texts have none today; this keeps it safe if an upstream refresh introduces one).
  const text = String(license || "").replace(/-{2,}/g, function (m) { return m.split("").join(" "); });
  // Unreachable while every caller resolves the notice with the library (below), and it stays a
  // THROW rather than a quiet return so a future caller cannot reintroduce the silent omission this
  // whole path exists to prevent.
  if (!text.trim()) throw new Error("Offline export is missing the MIT notice for the vendored " + name + " bundle.");
  head.appendChild(doc.createComment(
    " " + _OFFLINE_LIB_NOTICE_LEAD + name + _OFFLINE_LIB_NOTICE_TAIL + "\n"
    + text + "\n"));
}
function _offlineHoistChartScripts(doc) {
  const body = doc.body || doc.querySelector("body");
  const head = doc.head || doc.querySelector("head");
  if (!body || !head) return;
  const scripts = Array.from(doc.querySelectorAll("script:not([src])")).filter(function (s) {
    if (_offlineIsInlinedLibScript(s)) return false;
    // Never hoist fallback content OUT of an HTML `<noscript>`. To this scripting-disabled
    // `DOMParser` such a script is a real element, but to the reader who opens the exported file it
    // is inert TEXT - so moving it into the body would not relocate author code, it would START
    // EXECUTING code the source document never ran. (The chart EVIDENCE scan is left alone: a false
    // positive there only costs bytes, which is the trade that row already documents.)
    if (_offlineInHtmlNoscript(s)) return false;
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return false;
    const text = s.textContent || "";
    if (_OFFLINE_LAYER_DECL_RE.test(text)) return false;
    if (_OFFLINE_CHART_CTOR_RE.test(text)) return true;
    // A HEAD script that only references the global still has to move: the library is appended as
    // the head's last child, so anything already in the head would otherwise run before it. Body
    // scripts already run after it, and moving one would shift comment-anchor offsets for nothing.
    return head.contains(s) && _OFFLINE_CHART_GLOBAL_RE.test(text);
  });
  scripts.forEach(function (s) { body.appendChild(s); });
}
function _offlineRemoveVendoredBundleScript(payload) {
  // EVERY infrastructure payload block, not just the resolved one, and including any parked in a
  // `<template>`: an export carries the libraries inline and no payload at all, so a second copy
  // must not ride along as a megabyte of inflatable base64 in a file that claims to have none.
  //
  // The set was decided against the PRISTINE document (see `_offlineResolveVendoredPayload`), so a
  // block INSIDE the content root is never in it: an authored document may legitimately show one as
  // an EXAMPLE, `tools/authoring/vendored_libs.py` refuses to cut it for exactly that reason (review
  // found real cases twice), and deleting it would be silent content loss that also shifts every
  // comment anchor measured after it.
  payload.strip.forEach(function (el) { el.remove(); });
}
// An Offline export CONSUMES the vendored payload and removes it, so the file it produces carries
// the libraries inline and no payload at all. Re-exporting that file therefore has nothing to
// re-inline from - so read the copies already in the document (and the MIT notices beside them)
// BEFORE the strip removes them, and let the strip stay unconditional. Capturing and re-emitting,
// rather than leaving them in place, keeps the strip's exactly-one-copy and ordering guarantees.
//
// Re-emitting a captured script GRANTS IT EXECUTION in the exported file, and the document reaching
// here is UNTRUSTED (it may be hand-authored, or crafted), so the `data-cmh-offline-lib` marker is
// NOT on its own proof that this exporter wrote it. Four provenance gates make an impersonation
// grant no capability the source document did not already have://   1. it sits in <head>, where this exporter appends it and never in the authored content root;
//   2. it carries EXACTLY the attribute shape this exporter emits - the marker and nothing else.
//      That is stricter than enumerating disqualifying attributes and cannot be outflanked by one
//      nobody thought of. It rules out `src` (whose inline text never ran), any `type` (so inert
//      `application/json` / `text/plain` data is never promoted from data to code, and a bare
//      marker means the type was runnable), and - the reason a denylist would have failed -
//      `nomodule`, which every module-supporting browser SKIPS, so its body never ran, yet
//      re-emission drops the attribute and would run it;
//   3. it passes the same network-egress check `_stripOfflineNetworkLoads` applies to every other
//      surviving script - capture happens BEFORE the strips and re-emission AFTER, so without this
//      a smuggled remote module load, or a scripted navigation to a remote URL, would ride straight
//      past a strip that had already run. This is a strip-parity gate, NOT an egress proof: like
//      the strip it only recognizes literal-URL import and navigation forms, and the zero-network
//      CSP is what actually enforces no SUBRESOURCE egress. Both vendored bundles are clean under
//      it, so the legitimate path pays nothing;
//   4. its bytes cannot open a script-data escape. A body containing a script start tag (or a
//      script/style end tag) re-serializes into an element the parser does not close where the
//      exporter thinks it does: an HTML comment opener followed by a script start tag puts the
//      re-parse into the script-data-double-escaped state, so the emitted end tag stops closing
//      the element and the rest of the head (including the mermaid init shim) is swallowed into
//      it. `_escClose` neutralizes an end tag but cannot fix that state, so the bytes are rejected
//      instead. The vendored bundles contain none of these sequences (mermaid does contain a bare
//      comment opener, which is harmless on its own - the double-escaped state needs a script
//      start tag too - so the gate deliberately does not look for it). This very comment must
//      therefore avoid spelling those sequences out: doing so swallowed the whole runtime once.
// An adjacent MIT notice is required as well (below), but that is a LICENSING requirement, not
// authentication: the wording is a public constant and a forgery can copy it. The security
// argument rests only on gates 1-4.
//
// THREAT MODEL (deliberate, and the reason this stops here rather than at a pinned hash): these
// gates exist to ensure capture grants NO capability the source document did not already have.
// They close every case where it did - inert data, a MIME-parameter type (`text/javascript;
// charset=utf-8` does not execute: HTML matches the type's essence), or a skipped `nomodule` body
// promoted to code; a `src` script's dead inline text promoted; code carrying a remote import that
// the strip would have deleted being resurrected after the strip ran; and bytes that break the
// document's own parse. What they deliberately do NOT try to prove is that the bytes ARE the
// genuine library: an attacker who authors the document can put arbitrary executable code in a head
// script WITHOUT the marker, and the export preserves benign inline scripts by design
// (CMH-OFFLINE-04), so refusing a marked copy would not take that ability away. Verifying the bytes
// would need a build-pinned digest, and `crypto.subtle` is unavailable in a `file://` document -
// exactly where these exports are opened - so it would also reject every file produced by a
// different exporter version, reintroducing the false-rejection bug this fixes. The zero-network
// CSP is the backstop for what any preserved script can LOAD; it cannot restrict where a script
// NAVIGATES the top-level document (CMH-OFFLINE-05), which is why the strips also drop a direct
// scripted navigation to a network URL.
const _OFFLINE_SCRIPT_DATA_ESCAPE_RE = /<\/?script|<\/style/i;
// The two CONTENT gates every set of library bytes has to clear before this exporter appends them
// as an executable script. Shared by the capture path and the payload path so the two can never
// drift: whichever source `_offlineInlineRichLibs` chooses, the bytes face the same scan.
function _offlineLibBytesUnsafe(code) {
  return _offlineScriptHasNetworkEgress(code) || _OFFLINE_SCRIPT_DATA_ESCAPE_RE.test(code);
}
function _offlineAdjacentLibNotice(script, lib) {
  let n = script.previousSibling;
  while (n && n.nodeType === 3 && !String(n.nodeValue || "").trim()) n = n.previousSibling;
  if (!n || n.nodeType !== 8) return "";
  const m = _OFFLINE_LIB_NOTICE_RE.exec(n.nodeValue || "");
  // Bind the notice to THIS library, and only to the notice immediately before it, so an earlier
  // duplicate or forged comment elsewhere in the head cannot shadow the authentic one. The name
  // is read from an untrusted comment, so look it up as an OWN key - `constructor` / `__proto__`
  // would otherwise resolve to an inherited value.
  if (!m || !Object.prototype.hasOwnProperty.call(_OFFLINE_LIB_NOTICE_KEYS, m[1])) return "";
  if (_OFFLINE_LIB_NOTICE_KEYS[m[1]] !== lib + "License") return "";
  return m[2].replace(/\r?\n$/, "");
}
function _offlineCaptureInlinedRichLibs(doc) {
  const found = { chartjs: "", mermaid: "", chartjsLicense: "", mermaidLicense: "" };
  const head = doc.head || doc.querySelector("head");
  if (!head) return found;
  head.querySelectorAll("script[data-cmh-offline-lib]").forEach(function (s) {
    const lib = s.getAttribute("data-cmh-offline-lib") || "";
    if (lib !== "chartjs" && lib !== "mermaid") return;
    // A copy this exporter refused for PROVENANCE is remembered separately from one it refused for
    // LICENSING: the specific unlicensed-copy message below may only be shown when licensing was
    // the sole blocker, or a document holding both an unsafe copy and a notice-less one would send
    // the user after a licence when the real problem was a tampered bundle.
    if (s.attributes.length !== 1) { found[lib + "Rejected"] = true; return; }
    const code = s.textContent || "";
    if (!code.trim() || _offlineLibBytesUnsafe(code)) { found[lib + "Rejected"] = true; return; }
    const license = _offlineAdjacentLibNotice(s, lib);
    // A blank notice would make `_offlineAppendLibNotice` a no-op, redistributing the library with
    // no MIT notice at all, so treat it as no notice. The marker was introduced before the notice
    // was, so an offline file from an exporter version in between carries the library UNLICENSED:
    // remember that, because the bundle IS in the file and only the licence blocks re-emitting it -
    // the generic missing-bundle error would send the user looking for the wrong thing.
    if (!license.trim()) { found[lib + "Unlicensed"] = true; return; }
    // LAST match wins: this exporter appends the library as the head's last child, so a marker
    // placed earlier must never displace the genuine copy (that would "succeed" with a diagram
    // that never renders). The flag describes the WINNING copy, so a later licensed copy clears an
    // earlier unlicensed one rather than leaving a stale reason behind.
    found[lib] = code;
    found[lib + "License"] = license;
    found[lib + "Unlicensed"] = false;
  });
  return found;
}
// Synthesising the notice is NOT an option: with the payload consumed the exporter has no copy of
// the licence text to emit, which is exactly why the copy is refused. Point at the source document
// that does still carry the payload instead. The message states only what the exporter can actually
// see - a marked copy with no usable notice - and asserts nothing it cannot verify: the capture
// gates authenticate no provenance, so neither "an older exporter wrote this" nor "your source
// document still has the payload" may be claimed as fact about a document it has never seen.
function _offlineMissingLibError(name, unlicensed) {
  if (unlicensed) {
    return new Error("Offline export cannot re-emit the inlined " + name + " library: it has no MIT license"
      + " notice beside it, so re-emitting it would redistribute it unlicensed. Re-export from the source"
      + " document that still carries the vendored payload.");
  }
  return new Error("Offline export is missing the vendored " + name + " bundle.");
}
// The payload's inflated bytes are appended as an EXECUTABLE script AFTER both offline strips have
// run, so nothing downstream ever scans them. Position and uniqueness (CMH-OFFLINE-08) authenticate
// the payload against an author of the CONTENT REGION and prove nothing against an author of the
// WHOLE FILE - but "they can already run script in the document anyway" is only true of the SOURCE
// document. The export exists to strip egress out of the file it PRODUCES: an authored script
// carrying a remote dynamic import, or a direct scripted navigation to a network URL literal, is
// deleted by `_stripOfflineNetworkLoads`, so routing the same code through the payload would grant
// a capability the authored path does not have - egress inside a file whose whole promise is zero
// network. So the bytes clear the same content gates the captured-copy path applies, and a refusal
// says so: the bundle IS in the document, and the fix is refreshing the payload, which the generic
// missing-bundle message would send the user away from. The wording claims only what each predicate
// decides - that the bytes MATCH a pattern - for BOTH halves: the egress pattern is deliberately
// literal and can match a comment or a string (CMH-OFFLINE-05), and the escape pattern is a
// deliberate superset too (a start tag alone is inert until something has already escaped the
// state, and a style end tag cannot close a script element at all). In practice only PAYLOAD bytes
// can reach this, since a captured copy that failed the same scan was never recorded as a candidate.
function _offlineUnsafeLibError(name) {
  return new Error("Offline export refused the vendored " + name + " bundle: its bytes match the"
    + " network-egress pattern the offline strips apply to every runnable inline script, or the"
    + " script-data escape pattern, so they cannot be inlined safely. Re-run the authoring finalize"
    + " step to refresh the vendored payload from the shipped libraries.");
}
async function _offlineInlineRichLibs(doc, referencesChartLib, inlinedLibs, payload) {
  const head = doc.head || doc.querySelector("head");
  if (!head) return;
  const needMermaid = _offlineDocUsesMermaid(doc);
  const needCharts = _offlineDocNeedsChartLib(doc, referencesChartLib);
  if (!needMermaid && !needCharts) {
    _offlineRemoveVendoredBundleScript(payload);
    return;
  }
  const bundle = await _offlineVendoredRichLibs(payload);
  const captured = inlinedLibs || {};
  // The payload wins when it carries the library (a fresh copy of the vendored bytes); the captured
  // copy is the fallback for a document that no longer has a payload. Whichever source is chosen,
  // its bytes and its MIT notice travel as ONE unit: an Offline export inlines the library, which
  // makes it a redistribution, and MIT requires the notice to accompany it. A missing notice is
  // therefore a refusal, not a silent omission. There is deliberately no cross-source fallback on
  // the notice alone: letting a noticeless payload fall through to the captured copy would let
  // anyone who can strip a notice force document-supplied bytes instead.
  const lib = function (key, name) {
    const source = bundle[key] ? bundle : captured;
    const code = String(source[key] || "");
    if (!code.trim()) {
      // Only when licensing was the SOLE reason nothing could be reused: a copy this exporter
      // rejected for provenance makes the licence an unproven cause, so fall back to the generic
      // message rather than name a cause that may be wrong.
      throw _offlineMissingLibError(name, !!captured[key + "Unlicensed"] && !captured[key + "Rejected"]);
    }
    // Every set of bytes this exporter is about to make executable clears the same content scan,
    // whatever its source (see `_offlineUnsafeLibError`). Checked HERE, at the point of use, rather
    // than at inflation: this is the last place before the bytes become a script, and it is after
    // both strips have run.
    if (_offlineLibBytesUnsafe(code)) throw _offlineUnsafeLibError(name);
    const license = String(source[key + "License"] || "");
    if (!license.trim()) {
      throw new Error("Offline export is missing the MIT notice for the vendored " + name
        + " bundle. Re-run the authoring finalize step to refresh the vendored payload.");
    }
    return { code: code, license: license };
  };
  if (needCharts) {
    const chartjs = lib("chartjs", "Chart.js");
    _offlineAppendLibNotice(doc, head, "Chart.js", chartjs.license);
    _offlineAppendInlineScript(doc, head, chartjs.code, { "data-cmh-offline-lib": "chartjs" });
  }
  if (needMermaid) {
    const mermaid = lib("mermaid", "mermaid");
    _offlineAppendLibNotice(doc, head, "mermaid", mermaid.license);
    _offlineAppendInlineScript(doc, head, mermaid.code, { "data-cmh-offline-lib": "mermaid" });
    _offlineAppendInlineScript(doc, head,
      "(function(){\n"
      + "  if (!window.mermaid || !window.mermaid.initialize || !window.mermaid.run) return;\n"
      + "  var isHidden = function (el) { return !(el.offsetWidth || el.offsetHeight || el.getClientRects().length); };\n"
      + "  var chain = Promise.resolve();\n"
      + "  var runVisible = function (nodes) {\n"
      + "    if (!nodes.length) return;\n"
      + "    chain = chain.then(function () { var r = window.mermaid.run({ nodes: nodes }); return r && r.catch ? r.catch(function () {}) : r; }, function () {});\n"
      + "  };\n"
      + "  var renderHidden = function (el) {\n"
      + "    if (el.hasAttribute('data-processed')) return;\n"
      + "    chain = chain.then(function () {\n"
      + "      if (el.hasAttribute('data-processed')) return;\n"
      + "      var sandbox = document.createElement('div');\n"
      + "      sandbox.setAttribute('aria-hidden', 'true');\n"
      + "      sandbox.style.cssText = 'position:fixed;left:-99999px;top:0;width:1000px;visibility:hidden;pointer-events:none;';\n"
      + "      var clone = el.cloneNode(true);\n"
      + "      clone.removeAttribute('id');\n"
      + "      clone.removeAttribute('data-processed');\n"
      + "      sandbox.appendChild(clone);\n"
      + "      document.body.appendChild(sandbox);\n"
      + "      var cleanup = function () { if (sandbox.parentNode) sandbox.parentNode.removeChild(sandbox); };\n"
      + "      var ran;\n"
      + "      try { ran = window.mermaid.run({ nodes: [clone] }); } catch (e) { cleanup(); return; }\n"
      + "      return Promise.resolve(ran).then(function () {\n"
      + "        var svg = clone.querySelector('svg');\n"
      + "        if (svg && !el.hasAttribute('data-processed')) {\n"
      + "          el.textContent = '';\n"
      + "          el.appendChild(svg);\n"
      + "          el.setAttribute('data-processed', 'true');\n"
      + "        }\n"
      + "        cleanup();\n"
      + "      }, cleanup);\n"
      + "    }, function () {});\n"
      + "  };\n"
      + "  var initLabels = function (v) { window.mermaid.initialize({ startOnLoad: false, theme: document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default', securityLevel: 'strict', htmlLabels: v, flowchart: { htmlLabels: v, curve: 'basis' } }); };\n"
      + "  var pristine = new WeakMap();\n"
      + "  window.__cmhMermaidRerender = function (el, opts) {\n"
      + "    var src = pristine.get(el);\n"
      + "    if (!src) return Promise.resolve(false);\n"
      + "    var want = !!(opts && opts.htmlLabels);\n"
      + "    var base = !document.querySelector('.deck-stage');\n"
      + "    chain = chain.then(function () {\n"
      + "      var sandbox = document.createElement('div');\n"
      + "      sandbox.setAttribute('aria-hidden', 'true');\n"
      + "      sandbox.style.cssText = 'position:fixed;left:-99999px;top:0;width:1000px;visibility:hidden;pointer-events:none;';\n"
      + "      var clone = src.cloneNode(true);\n"
      + "      clone.removeAttribute('id');\n"
      + "      clone.removeAttribute('data-processed');\n"
      + "      sandbox.appendChild(clone);\n"
      + "      document.body.appendChild(sandbox);\n"
      + "      var cleanup = function () {\n"
      + "        if (sandbox.parentNode) sandbox.parentNode.removeChild(sandbox);\n"
      + "        try { initLabels(base); } catch (e) {}\n"
      + "      };\n"
      + "      var ran;\n"
      + "      try { initLabels(want); ran = window.mermaid.run({ nodes: [clone] }); } catch (e) { cleanup(); return false; }\n"
      + "      return Promise.resolve(ran).then(function () {\n"
      + "        var svg = clone.querySelector('svg');\n"
      + "        if (!svg) return false;\n"
      + "        el.textContent = '';\n"
      + "        el.appendChild(svg);\n"
      + "        el.setAttribute('data-processed', 'true');\n"
      + "        return true;\n"
      + "      }, function () { return false; }).then(function (ok) { cleanup(); return ok; }, function () { cleanup(); return false; });\n"
      + "    }, function () { return false; });\n"
      + "    window.__cmhMermaidReady = chain;\n"
      + "    return chain;\n"
      + "  };\n"
      + "  var run = function () {\n"
      + "    var theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default';\n"
      + "    var htmlLabels = !document.querySelector('.deck-stage');\n"
      + "    try { window.mermaid.initialize({ startOnLoad: false, theme: theme, securityLevel: 'strict', htmlLabels: htmlLabels, flowchart: { htmlLabels: htmlLabels, curve: 'basis' } }); }\n"
      + "    catch (e) { return; }\n"
      + "    var all = Array.prototype.slice.call(document.querySelectorAll(" + JSON.stringify(CMH_MERMAID_SEL) + "));\n"
      + "    all.forEach(function (el) { if (!pristine.has(el)) pristine.set(el, el.cloneNode(true)); });\n"
      + "    runVisible(all.filter(function (el) { return !el.hasAttribute('data-processed') && !isHidden(el); }));\n"
      + "    all.filter(function (el) { return !el.hasAttribute('data-processed') && isHidden(el); }).forEach(renderHidden);\n"
      + "    window.__cmhMermaidReady = chain;\n"
      + "  };\n"
      + "  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, { once: true });\n"
      + "  else run();\n"
      + "})();",
      { "data-cmh-offline-lib-init": "mermaid" });
  }
  _offlineRemoveVendoredBundleScript(payload);
}
async function _buildOfflineHtml(shareableHtml) {
  // Declare the mode BEFORE the document is parsed and neutralized. The neutralizer retypes every
  // reserved-id script that would RUN to inert JSON, so retargeting afterwards would see an
  // author's runnable script as inert data and overwrite the very bytes the neutralizer promises
  // to keep verbatim. Stamping first means the descriptor rule judges the document as authored.
  const retargeted = _retargetLayerDescriptor(shareableHtml, "offline");
  // BEFORE the parse, because the parse is where the damage happens: a head `<noscript>` body the
  // "in head noscript" insertion mode does not allow is promoted out of the fallback by `DOMParser`
  // itself, and no pass that walks the resulting DOM can tell a promoted node from an authored one.
  const headFallbacks = _stripOfflineHeadNoscriptStable(retargeted);
  const doc = _offlineDocFromHtml(headFallbacks.html);
  // Make the layer's reserved-id data blocks inert BEFORE anything else reads or strips the
  // document, so every later pass exempts them on the ordinary runnable-type test and a decoy that
  // borrowed one of those ids cannot buy itself an exemption from either strip.
  const neutralizedScripts = _neutralizeOfflineReservedDataScripts(doc);
  // Read the "does this document use Chart.js" evidence BEFORE anything is stripped, so a script the
  // loader strip removes cannot take the only sign of the library with it.
  const referencesChartLib = _offlineDocReferencesChartLib(doc);
  // Resolve the payload against the PRISTINE document, before any strip or hoist runs: the hoist
  // legitimately moves an author chart script out of the content root, so resolving later would let
  // this exporter's own rearrangement turn an authored payload-id script into a second
  // "infrastructure" candidate and refuse a document that is perfectly fine.
  const vendoredPayload = _offlineResolveVendoredPayload(doc);
  const inlinedRichLibs = _offlineCaptureInlinedRichLibs(doc);
  const neutralizedSet = new Set(neutralizedScripts);
  _stripOfflineRichRenderers(doc, neutralizedSet);
  const stripped = _stripOfflineNetworkLoads(doc, neutralizedSet);
  _stripOfflineEventHandlers(doc);
  // Last of the passes that read a fallback body, because it judges what those passes LEFT: a seam
  // the handler scrub or the CSS strip has just taken away is no longer a disagreement.
  const droppedFallbacks = _stripOfflineStraddlingNoscript(doc);
  _offlineHoistChartScripts(doc);
  await _offlineInlineRichLibs(doc, referencesChartLib, inlinedRichLibs, vendoredPayload);
  _ensureOfflineCsp(doc);
  const html = _serializeOfflineDoc(doc).replace(/\n{3,}/g, "\n\n");
  return {
    html: html,
    droppedScripts: stripped.dropped,
    droppedFallbacks: droppedFallbacks,
    droppedHeadFallbacks: headFallbacks.dropped,
    clearedBases: stripped.clearedBases,
    clearedSrcdocs: stripped.clearedSrcdocs,
    // Counted from the FINISHED document, not banked when each block is inserted: a later pass can
    // still take one away (`_stripOfflineStraddlingNoscript` removes a `<noscript>` whose body
    // straddles its own end tag, and a block parked inside goes with it). Reporting "N are kept" for
    // markup the file does not carry would reintroduce exactly the silent loss this feature ends,
    // now with a positive claim behind it. By IDENTITY, never by the class name, for the same reason
    // `_offlineCountKeptNeutralized` is.
    keptSrcdocs: _offlineCountKeptSrcdocs(doc, stripped.preservedSrcdocs),
    neutralizedScripts: _offlineCountKeptNeutralized(doc, neutralizedScripts),
  };
}
// An export that FAILED is the one toast a user must actually finish reading: it names the cause
// and the action to take, and some of those messages are long. The 3s default is a confirmation
// timing, so give a failure an assertive announcement and enough time to read it.
const _OFFLINE_EXPORT_ERROR_TOAST = { alert: true, duration: 10000 };
async function saveOffline() {
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { _reportExportFailure(e, _EXPORT_FAILURE_LOAD, _OFFLINE_EXPORT_ERROR_TOAST); return; }
  let review;
  let headFallbacks;
  try {
    // FIRST, on the authored bytes, before ANY pass that parses and re-serializes the document. The
    // state appliers below each round-trip through `DOMParser` when they have something to write, and
    // that parse promotes a head fallback's body out of it exactly as the export's own parse does -
    // so a document with a pending checklist, note, widget or review change would reach
    // `_buildOfflineHtml` with the promotion already baked in and no fallback left to judge. The pass
    // inside `_buildOfflineHtml` still runs (nothing downstream may depend on the order of two
    // callers), and finds nothing left once this one has run.
    headFallbacks = _stripOfflineHeadNoscriptStable(baseHtml);
    baseHtml = headFallbacks.html;
    baseHtml = _applyWidgetLayoutToHtml(baseHtml);
    baseHtml = _applyChecklistStateToHtml(baseHtml);
    baseHtml = _applyNoteStateToHtml(baseHtml);
    review = _applyReviewStateToHtml(baseHtml);
    baseHtml = review.html;
  } catch (e) { _reportExportFailure(e, _EXPORT_FAILURE_PREPARE); return; }
  const canonical = _exportableCommentsOrReport();
  if (!canonical) return;
  const exportComments = canonical.comments;
  let shareable;
  try {
    shareable = NONSHAREABLE_MODE
      ? _buildStandaloneHtml(baseHtml, exportComments)
      : _buildSavedHtml(baseHtml, exportComments);
  } catch (e) { _reportExportBuildFailure(e, _OFFLINE_EXPORT_ERROR_TOAST); return; }
  let built;
  try { built = await _buildOfflineHtml(shareable); }
  catch (e) { _reportExportBuildFailure(e, _OFFLINE_EXPORT_ERROR_TOAST); return; }
  const filename = _suggestedOfflineFilename();
  // An Offline export is precisely the one that inlines base64 assets into a multi-megabyte
  // document, so the Blob/object-URL step here is the likeliest of all of them to throw (#1108).
  try { _downloadHtml(built.html, filename); }
  catch (e) { _reportExportFailure(e, _EXPORT_FAILURE_DOWNLOAD); return; }
  // Say when a script was dropped. The strip is deliberately literal, so it can remove a script
  // whose comment or string merely spells an egress shape; removing content silently would leave
  // the author guessing why their document behaves differently offline.
  const n = built.droppedScripts;
  const note = n > 0
    ? " " + n + " script" + (n === 1 ? " that loads, prefetches, or navigates to the network was" : "s that load, prefetch, or navigate to the network were") + " removed."
    : "";
  // A script that keeps its bytes but loses the ability to run is a quieter change than a removal,
  // and just as surprising to an author who used a reserved id, so it is named too.
  const m = built.neutralizedScripts;
  const inertNote = m > 0
    ? " " + m + " script" + (m === 1 ? " carrying a reserved commentable-html data id was" : "s carrying a reserved commentable-html data id were") + " kept as inert data."
    : "";
  // A dropped fallback is author content too, and it goes for a reason no reader could guess from
  // the file: the two tokenizers could not be made to agree about where its body ends.
  const f = built.droppedFallbacks;
  const fallbackNote = f > 0
    ? " " + f + " noscript fallback " + (f === 1 ? "block whose end a scripting-enabled reader reads differently was" : "blocks whose end a scripting-enabled reader reads differently were") + " removed."
    : "";
  // A head fallback goes for a different reason again: not a seam, but an insertion mode that takes
  // its body apart before any pass can read it - so keeping it would ACTIVATE code the source
  // document never ran.
  const hf = built.droppedHeadFallbacks + headFallbacks.dropped;
  const headFallbackNote = hf > 0
    ? " " + hf + " noscript fallback " + (hf === 1 ? "block in the document head, whose body a scripting-disabled parse takes apart, was" : "blocks in the document head, whose bodies a scripting-disabled parse takes apart, were") + " removed."
    : "";
  // Clearing a base href is the one change here that re-points references which still WORK -
  // author links included - so the author is told rather than left to discover it.
  const b = built.clearedBases;
  const baseNote = b > 0
    ? " " + b + " <base href> pointing away from this file " + (b === 1 ? "was" : "were") + " cleared, so relative references and links now resolve beside the file."
    : "";
  // An `<iframe srcdoc>` renders offline perfectly well, so unlike every network strip this one
  // changes content that WORKED - a nested document the zero-network promise simply cannot inspect.
  // Silently emptying the frame would leave the author hunting for their missing content. Two
  // counts, because two different things happened: every one of them stopped RENDERING, and most of
  // them were kept beside their frame as inert escaped text (issue #1119). "Emptied" rather than
  // "removed", because the markup is no longer gone. The kept count is reported only when there is
  // one, so a document whose only frames were empty or foreign - which keep nothing, and lose
  // nothing a reader could see - says only what was emptied.
  const s = built.clearedSrcdocs;
  const k = built.keptSrcdocs;
  const srcdocNote = s > 0
    ? " " + s + " <iframe srcdoc> nested document" + (s === 1 ? " was" : "s were")
      + " emptied from " + (s === 1 ? "its frame" : "their frames")
      + " - an offline export cannot inspect a document carried inside an attribute"
      + (k > 0
        ? "; " + k + (k === 1 ? " is kept beside its frame" : " are kept beside their frames")
          + " as inert escaped text."
        : ".")
    : "";
  showToast("Downloaded " + filename + " - offline HTML with zero-network mermaid and Chart.js embedded." + note + inertNote + fallbackNote + headFallbackNote + baseNote + srcdocNote + review.note, { center: true });
}
["btnExportOffline", "btnExportOfflineTop"].forEach(function (id) {
  const b = document.getElementById(id);
  if (b) b.addEventListener("click", saveOffline);
});
_primeOfflineVendoredRichLibs();
