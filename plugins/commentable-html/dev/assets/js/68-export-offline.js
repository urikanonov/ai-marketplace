/* ---------- Export Offline (portable + zero-network rich-content embedding) ---------- */
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
// content scan that ignored it would miss real code.
function _offlineIsRunnableScriptType(type) {
  const t = String(type || "").split(";")[0].trim().toLowerCase();
  if (!t || t === "module") return true;
  return /^(?:text|application)\/(?:x-)?(?:java|ecma)script$/.test(t) ||
    /^text\/(?:javascript1\.[0-5]|jscript|livescript)$/.test(t);
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
  return "<!DOCTYPE html>\n" + doc.documentElement.outerHTML;
}
function _offlineIsNetworkUrl(v) {
  return /^(?:https?:)?\/\//i.test(String(v || "").trim());
}
function _offlineSrcsetHasNetwork(v) {
  return String(v || "").split(",").some(function (part) {
    return _offlineIsNetworkUrl(part.trim().split(/\s+/)[0]);
  });
}
function _offlineCssNoNetwork(css) {
  return String(css || "")
    .replace(/@import\s+(?:url\()?["']?(?:https?:)?\/\/[^;"')]+["']?\)?\s*;/gi, "")
    .replace(/url\(\s*(["']?)(?:https?:)?\/\/[^)"']+\1\s*\)/gi, 'url("data:,")');
}
function _stripOfflineEventHandlers(doc) {
  doc.querySelectorAll("*").forEach(function (el) {
    Array.from(el.attributes || []).forEach(function (attr) {
      if (/^on/i.test(attr.name || "")) el.removeAttribute(attr.name);
    });
  });
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
  doc.querySelectorAll("meta[name]").forEach(function (m) {
    if ((m.getAttribute("name") || "").toLowerCase() === "referrer") m.remove();
  });
  // The pragma spelling is not in the HTML spec's pragma-directive list, so a conformant browser
  // ignores it - but it appears in the wild, this whole strip is precautionary anyway, and leaving
  // an authored `unsafe-url` in the file would be a confusing contradiction of the meta beside it.
  doc.querySelectorAll("meta[http-equiv]").forEach(function (m) {
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
// Every metacharacter whose meaning DIFFERS between JavaScript and Python is spelled out instead:
// `\w` is ASCII-only in JS but Unicode-aware in Python, and JS whitespace includes U+FEFF while
// Python's does not, so a shared `\s`/`\w` made the two copies disagree on real inputs (the
// validator would then certify a file the exporter strips, and vice versa). The literal classes
// below make the pattern mean the same thing in both engines.
// Deliberately literal, matching the import test next to it - and therefore NOT a boundary. It sees
// only these sinks, written out directly: an alias (`var l = location; l.href = ...`), computed
// access (`location["href"]`), a comment between the sink and the URL, a URL assembled at runtime,
// or an entirely different sink (a synthesized anchor click, a script-injected refresh meta) all
// pass through. A BARE unprefixed `open(<url>)` is deliberately not matched either: in raw source
// it cannot be told apart from a local `open` helper, and deleting the wrong script is the costlier
// error. A bare `location = <url>` is matched only after a delimiter that cannot begin a
// declaration (`;`, `}`, `)`, `>`, or a line break), so a purely local binding - a `var`/`let`/
// `const` declaration, a parameter default, a destructuring default - is left alone; the cost is
// that a same-line `{ location = <url> }` is missed. It also over-matches: the URL literal is found
// in raw source, so a script whose COMMENT or STRING merely spells one of these shapes is stripped
// too. Both directions are stated in CMH-OFFLINE-05 rather than papered over.
// Each optional `?` is bound inside its own group rather than sitting between two unbounded
// whitespace runs: the earlier `WS*\??WS*\.` let one input run split every way, which took ~2.7s in
// Python and ~10s in node on a 20k-space input - a denial of service on exactly the hostile
// document this defends against. `test_the_navigation_pattern_cannot_be_made_to_backtrack` pins it.
// This comment must not spell out a navigation sink followed by a network URL literal: the layer's
// own script is stripped by the same pass, so writing the pattern out here deletes the runtime from
// every offline export (it did, once - the whole suite went red at "JS region has no closing
// script tag"). `test_the_layer_script_survives_its_own_offline_strips` guards it.
const _OFFLINE_NAV_TO_NETWORK_RE = /(?:(?:^|[^.A-Za-z0-9_$])(?:(?:window|self|top|parent|globalThis|document|frames)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:\?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)?\.[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)*location[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:\?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)?\.[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:href[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*=(?!=)|(?:assign|replace)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\()|(?:^|[^.A-Za-z0-9_$])(?:(?:window|self|top|parent|globalThis|document|frames)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:\?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)?\.[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)+(?:location[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*=(?!=)|open[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\()|(?:^|[;})>\n\r\u2028\u2029])[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*location[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*=(?!=))[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*["'`](?:https?:)?\/\//i;
const _OFFLINE_NAV_PREFIXED_RE = /(?:(?:^|[^.A-Za-z0-9_$])(?:(?:window|self|top|parent|globalThis|document|frames)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:\?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)?\.[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)+location[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:\?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)?\.[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:href[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*=(?!=)|(?:assign|replace)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\()|(?:^|[^.A-Za-z0-9_$])(?:(?:window|self|top|parent|globalThis|document|frames)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:\?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)?\.[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)+(?:location[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*=(?!=)|open[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\())[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*["'`](?:https?:)?\/\//i;
const _OFFLINE_LOCAL_LOCATION_RE = /(?:^|[^.A-Za-z0-9_$])(?:(?:var|let|const|function|class)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+location(?![A-Za-z0-9_$])|(?:var|let|const)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*[{\[][^}\]]{0,400}location(?![A-Za-z0-9_$])|function[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*[A-Za-z0-9_$]{0,100}[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\([^)]{0,400}location(?![A-Za-z0-9_$])|catch[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\([ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*location(?![A-Za-z0-9_$]))/i;
function _offlineScriptNavigatesToNetwork(body) {
  const src = String(body || "");
  if (!_OFFLINE_NAV_TO_NETWORK_RE.test(src)) return false;
  // A script that declares its OWN `location` binding is talking about that object, not the
  // document's - `const location = { href: "" }; location.href = <url>` navigates nothing, and
  // deleting the whole script over it is the content loss this strip must not cause. So when a
  // local binding is present, only the PREFIXED sinks still count: `window.location` names the real
  // one no matter what a local `location` shadows. This costs nothing an attacker did not already
  // have - aliasing (`var l = location; l.href = <url>`) is a cheaper bypass that has always
  // worked, and both are listed in the CMH-OFFLINE-05 residual.
  if (_OFFLINE_LOCAL_LOCATION_RE.test(src)) return _OFFLINE_NAV_PREFIXED_RE.test(src);
  return true;
}
function _offlineScriptHasNetworkEgress(body) {
  return _offlineScriptHasNetworkImport(body) || _offlineScriptNavigatesToNetwork(body);
}
function _stripOfflineNetworkLoads(doc) {
  let dropped = 0;
  doc.querySelectorAll("script[src]").forEach(function (s) {
    if (_offlineIsNetworkUrl(s.getAttribute("src"))) { s.remove(); dropped += 1; }
  });
  doc.querySelectorAll("script").forEach(function (s) {
    const id = s.getAttribute("id") || "";
    // The layer's own data blocks carry reviewer text and must not be read as code. The vendored
    // payload is deliberately NOT exempt: it is inert `application/json` (so the type check below
    // already skips it) and it is stripped later anyway, while an AUTHORED script that merely
    // borrows the payload id is preserved as content by the strip - so exempting the id would hand
    // that script a free pass past the network-import scan every other script has to clear.
    if (/^(?:embeddedComments|handledCommentIds|commentableHtmlLayer)$/.test(id)) return;
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return;
    const body = s.textContent || "";
    if (_offlineScriptHasNetworkEgress(body)) {
      s.remove();
      dropped += 1;
    }
  });
  // A per-element `referrerpolicy` overrides the document policy for that request, so a permissive
  // one would defeat the no-referrer meta on exactly the anchor an attacker planted.
  doc.querySelectorAll("[referrerpolicy]").forEach(function (el) { el.removeAttribute("referrerpolicy"); });
  doc.querySelectorAll("link[href]").forEach(function (link) {
    if (!_offlineIsNetworkUrl(link.getAttribute("href"))) return;
    const rel = (link.getAttribute("rel") || "").toLowerCase().split(/\s+/);
    const loads = ["stylesheet", "preload", "modulepreload", "preconnect", "dns-prefetch", "icon", "apple-touch-icon", "manifest", "prefetch", "prerender"];
    if (rel.some(function (r) { return loads.includes(r); })) link.remove();
  });
  const clearAttr = function (el, attr) {
    if (!el.hasAttribute(attr)) return;
    const value = el.getAttribute(attr) || "";
    const network = attr === "srcset" ? _offlineSrcsetHasNetwork(value) : _offlineIsNetworkUrl(value);
    if (!network) return;
    if (el.tagName === "IMG" && attr === "src") el.setAttribute("src", "data:image/gif;base64,R0lGODlhAQABAAAAACw=");
    else el.removeAttribute(attr);
  };
  doc.querySelectorAll("meta[http-equiv]").forEach(function (m) {
    if ((m.getAttribute("http-equiv") || "").toLowerCase() === "refresh") m.remove();
  });
  doc.querySelectorAll("img").forEach(function (el) { clearAttr(el, "src"); clearAttr(el, "srcset"); });
  doc.querySelectorAll("iframe").forEach(function (el) { clearAttr(el, "src"); });
  doc.querySelectorAll("video").forEach(function (el) { clearAttr(el, "src"); clearAttr(el, "poster"); });
  doc.querySelectorAll("audio").forEach(function (el) { clearAttr(el, "src"); });
  doc.querySelectorAll("source").forEach(function (el) { clearAttr(el, "src"); clearAttr(el, "srcset"); });
  doc.querySelectorAll("track").forEach(function (el) { clearAttr(el, "src"); });
  doc.querySelectorAll("image").forEach(function (el) { clearAttr(el, "href"); clearAttr(el, "xlink:href"); });
  doc.querySelectorAll("use").forEach(function (el) { clearAttr(el, "href"); clearAttr(el, "xlink:href"); });
  doc.querySelectorAll("input[src]").forEach(function (el) {
    if ((el.getAttribute("type") || "").toLowerCase() === "image") clearAttr(el, "src");
  });
  doc.querySelectorAll("form[action]").forEach(function (el) { clearAttr(el, "action"); });
  doc.querySelectorAll("button[formaction], input[formaction]").forEach(function (el) { clearAttr(el, "formaction"); });
  doc.querySelectorAll("object").forEach(function (el) { clearAttr(el, "data"); });
  doc.querySelectorAll("embed").forEach(function (el) { clearAttr(el, "src"); });
  doc.querySelectorAll("[background]").forEach(function (el) { clearAttr(el, "background"); });
  doc.querySelectorAll("style").forEach(function (style) {
    style.textContent = _offlineCssNoNetwork(style.textContent || "");
  });
  doc.querySelectorAll("[style]").forEach(function (el) {
    const next = _offlineCssNoNetwork(el.getAttribute("style") || "");
    if (next) el.setAttribute("style", next);
    else el.removeAttribute("style");
  });
  return dropped;
}
function _stripOfflineRichRenderers(doc) {
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
    const src = s.getAttribute("src") || "";
    if (/(^|\/)(?:mermaid(?:\.esm)?(?:\.min)?\.mjs|mermaid(?:\.min)?\.js|chart(?:\.umd)?(?:\.min)?\.js)(?:[?#]|$)/i.test(src) ||
        /\/chart\.js@/i.test(src)) {
      s.remove();
    }
  });
  doc.querySelectorAll("script").forEach(function (s) {
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return;
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
  // An id SELECTOR (unlike getElementById) matches every element carrying the id, so a duplicate is
  // visible here rather than silently resolved away.
  const roots = d.querySelectorAll("#commentRoot");
  return roots.length === 1 ? roots[0] : null;
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
    // library to call.
    if (/^(?:embeddedComments|handledCommentIds|commentableHtmlLayer|reviewedSections)$/.test(s.getAttribute("id") || "")) return false;
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
    if (!code.trim() || _offlineScriptHasNetworkEgress(code)) { found[lib + "Rejected"] = true; return; }
    if (_OFFLINE_SCRIPT_DATA_ESCAPE_RE.test(code)) { found[lib + "Rejected"] = true; return; }
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
      + "  var run = function () {\n"
      + "    var theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default';\n"
      + "    var htmlLabels = !document.querySelector('.deck-stage');\n"
      + "    try { window.mermaid.initialize({ startOnLoad: false, theme: theme, securityLevel: 'strict', htmlLabels: htmlLabels, flowchart: { htmlLabels: htmlLabels, curve: 'basis' } }); }\n"
      + "    catch (e) { return; }\n"
      + "    var all = Array.prototype.slice.call(document.querySelectorAll(" + JSON.stringify(CMH_MERMAID_SEL) + "));\n"
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
async function _buildOfflineHtml(portableHtml) {
  const doc = _offlineDocFromHtml(portableHtml);
  // Read the "does this document use Chart.js" evidence BEFORE anything is stripped, so a script the
  // loader strip removes cannot take the only sign of the library with it.
  const referencesChartLib = _offlineDocReferencesChartLib(doc);
  // Resolve the payload against the PRISTINE document, before any strip or hoist runs: the hoist
  // legitimately moves an author chart script out of the content root, so resolving later would let
  // this exporter's own rearrangement turn an authored payload-id script into a second
  // "infrastructure" candidate and refuse a document that is perfectly fine.
  const vendoredPayload = _offlineResolveVendoredPayload(doc);
  const inlinedRichLibs = _offlineCaptureInlinedRichLibs(doc);
  _stripOfflineRichRenderers(doc);
  const droppedScripts = _stripOfflineNetworkLoads(doc);
  _stripOfflineEventHandlers(doc);
  _offlineHoistChartScripts(doc);
  await _offlineInlineRichLibs(doc, referencesChartLib, inlinedRichLibs, vendoredPayload);
  _ensureOfflineCsp(doc);
  const html = _retargetLayerDescriptor(_serializeOfflineDoc(doc), "offline").replace(/\n{3,}/g, "\n\n");
  return { html: html, droppedScripts: droppedScripts };
}
// An export that FAILED is the one toast a user must actually finish reading: it names the cause
// and the action to take, and some of those messages are long. The 3s default is a confirmation
// timing, so give a failure an assertive announcement and enough time to read it.
const _OFFLINE_EXPORT_ERROR_TOAST = { alert: true, duration: 10000 };
async function saveOffline() {
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { showToast("Could not load base HTML.", _OFFLINE_EXPORT_ERROR_TOAST); return; }
  baseHtml = _applyWidgetLayoutToHtml(baseHtml);
  baseHtml = _applyChecklistStateToHtml(baseHtml);
  baseHtml = _applyNoteStateToHtml(baseHtml);
  baseHtml = _applyReviewStateToHtml(baseHtml);
  const exportComments = _exportableComments();
  let portable;
  try {
    portable = NONPORTABLE_MODE
      ? _buildStandaloneHtml(baseHtml, exportComments)
      : _buildSavedHtml(baseHtml, exportComments);
  } catch (e) { showToast(e.message, _OFFLINE_EXPORT_ERROR_TOAST); return; }
  let built;
  try { built = await _buildOfflineHtml(portable); }
  catch (e) { showToast(e.message, _OFFLINE_EXPORT_ERROR_TOAST); return; }
  const filename = _suggestedOfflineFilename();
  _downloadHtml(built.html, filename);
  // Say when a script was dropped. The strip is deliberately literal, so it can remove a script
  // whose comment or string merely spells an egress shape; removing content silently would leave
  // the author guessing why their document behaves differently offline.
  const n = built.droppedScripts;
  const note = n > 0
    ? " " + n + " script" + (n === 1 ? " that loads or navigates to the network was" : "s that load or navigate to the network were") + " removed."
    : "";
  showToast("Downloaded " + filename + " - offline HTML with zero-network mermaid and Chart.js embedded." + note, { center: true });
}
["btnExportOffline", "btnExportOfflineTop"].forEach(function (id) {
  const b = document.getElementById(id);
  if (b) b.addEventListener("click", saveOffline);
});
_primeOfflineVendoredRichLibs();
