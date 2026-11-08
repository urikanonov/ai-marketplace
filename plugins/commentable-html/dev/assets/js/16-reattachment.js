/* ---------- Local, revision-aware text selectors ---------- */
const CMH_ANCHOR_SNAPSHOT = 4096;
const CMH_ANCHOR_TEXT_LIMIT = 8000000;
const CMH_ANCHOR_SCAN_BUDGET = 64000000;
const CMH_ANCHOR_CANDIDATES = 128;
// Capture before startup adds heading/TOC ids; those are chrome, not authored revision evidence.
const cmhAuthoredIds = new Set([...root.querySelectorAll("[id]")].map(el => el.id));
function cmhIsTextAnchor(c) {
  return !!c && !c.parentId && (!c.anchorType || c.anchorType === "text")
    && (typeof c.quote === "string" || Number.isFinite(c.start) || !!c.cmAnchor);
}
function cmhIsDetached(c) {
  if (!c) return false;
  if (c.parentId) {
    const parent = comments.find(p => p.id === c.parentId && !p.parentId);
    return !!parent && cmhIsDetached(parent);
  }
  return cmhIsTextAnchor(c) && (c.detached === true
    || (c.start === CMH_MAX_OFFSET && c.end === CMH_MAX_OFFSET));
}
function cmhAnchorHash(text) {
  let a = 2166136261, b = 5381;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charCodeAt(i);
    a = Math.imul(a ^ ch, 16777619); b = Math.imul(b, 33) ^ ch;
  }
  return text.length + ":" + (a >>> 0).toString(36) + ":" + (b >>> 0).toString(36);
}
function cmhAnchorIndex() {
  const nodes = getTextNodes(), chunks = [], blocks = [], byElement = new Map();
  let length = 0;
  for (const node of nodes) {
    const start = length; length += node.nodeValue.length;
    if (length > CMH_ANCHOR_TEXT_LIMIT) return { text: "", blocks: [], nodes, limited: true };
    chunks.push(node.nodeValue);
    let el = node.parentElement;
    while (el && el !== root && !BLOCK_TAG_RE.test(el.tagName)) el = el.parentElement;
    el = el || root;
    let block = byElement.get(el);
    if (!block) {
      let identified = el;
      while (identified && identified !== root && !identified.id) identified = identified.parentElement;
      block = { el, start, end: length, id: identified && identified !== root && identified.id.length <= 1024 ? identified.id : "",
        tag: el.tagName.toLowerCase(), code: !!el.closest("pre"), heading: "" };
      blocks.push(block); byElement.set(el, block);
    } else block.end = length;
  }
  const text = chunks.join("");
  const headings = [];
  let headingHash = "";
  for (const block of blocks) {
    if (/^h[1-6]$/.test(block.tag)) {
      const level = +block.tag.slice(1);
      while (headings.length && headings[headings.length - 1].level >= level) headings.pop();
      headings.push({ level, text: text.slice(block.start, Math.min(block.end, block.start + MAX_BLOCK_LEN)).trim().replace(/\s+/g, " ") });
      headingHash = cmhAnchorHash(JSON.stringify(headings));
    }
    block.heading = headingHash;
  }
  // Highlight extraction can split block elements without changing source text or identities.
  const identities = [], seenIds = new Set();
  for (const el of root.querySelectorAll("[id]")) {
    if (!cmhAuthoredIds.has(el.id) || el.closest(".cm-skip") || seenIds.has(el.id)) continue;
    seenIds.add(el.id); identities.push(el.id.slice(0, 1024));
  }
  return { text, blocks, nodes, revision: cmhAnchorHash(text) + ":" + cmhAnchorHash(JSON.stringify(identities)),
    budget: CMH_ANCHOR_SCAN_BUDGET, matches: new Map() };
}
function cmhAnchorBlock(index, start, end) {
  // Nested containers may span other blocks; prefer the smallest enclosing block.
  let found = null;
  for (const block of index.blocks) {
    if (block.start <= start && end <= block.end
      && (!found || block.end - block.start < found.end - found.start)) found = block;
  }
  return found;
}
function cmhAnchorOriginal(c) {
  const original = { start: c.start, end: c.end };
  for (const key of ["quote", "before", "after", "blockText", "section"]) {
    if (typeof c[key] === "string") {
      const limit = key === "quote" ? CMH_ANCHOR_SNAPSHOT : MAX_BLOCK_LEN;
      original[key] = c[key].slice(0, limit);
      if (c[key].length > limit) original[key + "Truncated"] = true;
    }
  }
  if (Array.isArray(c.headingPath)) original.headingPath = c.headingPath.slice(0, 6).map(h => ({
    level: h && h.level, text: h && typeof h.text === "string" ? h.text.slice(0, MAX_BLOCK_LEN) : "" }));
  return original;
}
function cmhCaptureTextAnchor(c, index) {
  if (!cmhIsTextAnchor(c) || cmhIsDetached(c)) return false;
  index = index && typeof index.text === "string" ? index : cmhAnchorIndex();
  const start = c.start, end = c.end;
  if (index.limited || !Number.isInteger(start) || !Number.isInteger(end)
    || start < 0 || end <= start || end > index.text.length) return false;
  const prior = c.cmAnchor && typeof c.cmAnchor === "object" && !Array.isArray(c.cmAnchor) ? c.cmAnchor : {};
  if (prior.v !== undefined && prior.v !== 1) return false;
  const block = cmhAnchorBlock(index, start, end);
  const from = block ? Math.max(block.start, Math.min(start - 1024, block.end - CMH_ANCHOR_SNAPSHOT)) : start;
  const to = block ? Math.min(block.end, Math.max(end, from + CMH_ANCHOR_SNAPSHOT)) : end;
  const bounded = to - from <= CMH_ANCHOR_SNAPSHOT;
  const exact = end - start <= CMH_ANCHOR_SNAPSHOT ? index.text.slice(start, end) : undefined;
  const blockText = block && bounded ? index.text.slice(from, to) : "";
  const normalized = !(block && block.code || c.isCode);
  const prefix = index.text.slice(Math.max(block ? block.start : 0, start - CTX_PAD), start);
  const suffix = index.text.slice(end, Math.min(block ? block.end : index.text.length, end + CTX_PAD));
  const unique = exact === undefined ? undefined : cmhAnchorUnique(index, exact, normalized);
  const hits = exact === undefined ? null : index.matches.get((normalized ? "np" : "rp") + exact);
  const rawHits = exact === undefined ? null : index.matches.get("rp" + exact);
  const identityUnique = !!(block && block.id && hits
    && rawHits && [hits, rawHits].every(list => list.filter(hit => hit.block && hit.block.id === block.id).length === 1));
  const blockUnique = block && from === block.start && to === block.end
    ? cmhAnchorUnique(index, blockText, normalized, block.tag) : false;
  const contextUnique = exact === undefined ? undefined : cmhAnchorUnique(index, prefix + exact + suffix, normalized);
  const sameBasis = prior.normalizedEvidence === normalized;
  c.cmAnchor = { ...prior, v: 1, revision: index.revision, start, end,
    exact, normalizedEvidence: normalized,
    unique: unique === undefined && sameBasis && prior.exact === exact ? prior.unique : unique,
    identityUnique: unique === undefined && sameBasis && prior.exact === exact ? prior.identityUnique : identityUnique,
    contextUnique: contextUnique === undefined && sameBasis && prior.exact === exact
      && prior.prefix === prefix && prior.suffix === suffix ? prior.contextUnique : contextUnique,
    blockUnique: blockUnique === undefined && sameBasis && prior.block && prior.block.text === blockText
      ? prior.blockUnique : blockUnique,
    prefix, suffix,
    heading: block ? block.heading : "",
    code: block ? block.code : !!c.isCode,
    block: block ? { id: block.id, tag: block.tag, from: from - block.start,
      start: start - from, end: end - from, text: blockText } : null,
    original: prior.original || cmhAnchorOriginal(c) };
  delete c.cmAnchor.reason;
  delete c.cmAnchor.discontiguous;
  return true;
}
function cmhDetachComment(c, reason) {
  if (!cmhIsTextAnchor(c)) return;
  if (!c.cmAnchor) c.cmAnchor = { v: 1, original: cmhAnchorOriginal(c) };
  c.detached = true;
  c.start = c.end = CMH_MAX_OFFSET;
  // Future selector objects are retained verbatim, not "migrated" by an older reader.
  if (c.cmAnchor && c.cmAnchor.v === 1) c.cmAnchor.reason = reason;
}
function cmhAnchorMetadataValid(a) {
  if (!a || typeof a !== "object" || Array.isArray(a) || a.v !== 1) return false;
  for (const key of ["unique", "blockUnique", "identityUnique", "contextUnique", "normalizedEvidence", "discontiguous"]) {
    if (a[key] !== undefined && typeof a[key] !== "boolean") return false;
  }
  for (const key of ["exact", "prefix", "suffix", "revision", "heading"]) {
    if (a[key] !== undefined && (typeof a[key] !== "string" || a[key].length >
      CMH_ANCHOR_SNAPSHOT)) return false;
  }
  if (a.revision !== undefined && (!Number.isInteger(a.start) || !Number.isInteger(a.end)
    || a.start < 0 || a.end <= a.start || a.end > CMH_MAX_OFFSET)) return false;
  if (a.block != null) {
    const b = a.block;
    if (typeof b !== "object" || typeof b.text !== "string" || b.text.length > CMH_ANCHOR_SNAPSHOT
      || typeof b.id !== "string" || b.id.length > 1024 || typeof b.tag !== "string"
      || !Number.isInteger(b.from) || b.from < 0 || !Number.isInteger(b.start)
      || !Number.isInteger(b.end) || b.start < 0 || b.end < b.start
      || (b.text && b.end > b.text.length)) return false;
  }
  return true;
}
function cmhAnchorNormalize(text, code, mapping) {
  let chunk = "", last = "", count = 0;
  const chunks = [];
  const starts = mapping ? new Uint32Array(text.length) : null;
  const ends = mapping ? new Uint32Array(text.length) : null;
  for (let i = 0; i < text.length; i++) {
    const original = text[i];
    let ch = original;
    if (!code) {
      if (/\s/.test(ch)) ch = " ";
      else if (/[\u2018\u2019]/.test(ch)) ch = "'";
      else if (/[\u201c\u201d]/.test(ch)) ch = '"';
      else if (/[\u2013\u2014]/.test(ch)) ch = "-";
    }
    if (!code && ch === " " && last === " ") {
      if (mapping) ends[count - 1] = i + 1;
      continue;
    }
    chunk += ch; last = ch;
    if (mapping) { starts[count] = i; ends[count] = i + 1; }
    count++;
    if (chunk.length >= 8192) { chunks.push(chunk); chunk = ""; }
  }
  chunks.push(chunk);
  return { text: chunks.join(""), starts, ends };
}
function cmhAnchorOccurrences(index, quote, code, normalized) {
  if (typeof quote !== "string" || quote.length > CMH_ANCHOR_SNAPSHOT) return null;
  const key = (normalized ? "n" : "r") + (code ? "c" : "p") + quote;
  if (index.matches.has(key)) return index.matches.get(key);
  if (!quote || index.budget < index.text.length) return null;
  index.budget -= index.text.length;
  let text = index.text, map = null, needle = quote;
  if (normalized) {
    if (!index.normalized) index.normalized = cmhAnchorNormalize(text, false, true);
    map = index.normalized; text = map.text;
    needle = cmhAnchorNormalize(quote, false, false).text;
  }
  const hits = [];
  let pos = 0, examined = 0;
  while (needle && (pos = text.indexOf(needle, pos)) !== -1) {
    if (examined++ >= CMH_ANCHOR_CANDIDATES) { index.matches.set(key, null); return null; }
    const start = map ? map.starts[pos] : pos;
    const end = map ? map.ends[pos + needle.length - 1] : pos + needle.length;
    const block = cmhAnchorBlock(index, start, end);
    if (!normalized || !(block && block.code)) hits.push({ start, end, block });
    pos++;
  }
  index.matches.set(key, hits);
  return hits;
}
function cmhAnchorUnique(index, quote, normalized, tag) {
  const raw = normalized ? cmhAnchorUnique(index, quote, false, tag) : true;
  const hits = cmhAnchorOccurrences(index, quote, false, !!normalized);
  const unique = hits ? hits.filter(hit => !tag || hit.block && hit.block.tag === tag).length === 1
    : index.matches.has((normalized ? "np" : "rp") + quote) ? false : undefined;
  return raw === false || unique === false ? false : raw === undefined ? undefined : unique;
}
function cmhAnchorContextScore(index, hit, a, c) {
  const b = hit.block, text = index.text;
  const clean = value => cmhAnchorNormalize(value || "", !!(a && a.code || c.isCode), false).text;
  let prefix = a && a.prefix !== undefined ? a.prefix : c.before;
  let suffix = a && a.suffix !== undefined ? a.suffix : c.after;
  prefix = typeof prefix === "string" ? prefix.slice(-CTX_PAD * 2) : "";
  suffix = typeof suffix === "string" ? suffix.slice(0, CTX_PAD * 2) : "";
  if (!a || a.prefix === undefined) prefix = prefix.replace(/^\.\.\./, "");
  if (!a || a.suffix === undefined) suffix = suffix.replace(/\.\.\.$/, "");
  prefix = clean(prefix); suffix = clean(suffix);
  const before = clean(text.slice(Math.max(b ? b.start : 0, hit.start - CTX_PAD * 2), hit.start));
  const after = clean(text.slice(hit.end, Math.min(b ? b.end : text.length, hit.end + CTX_PAD * 2)));
  let left = 0, right = 0;
  while (left < Math.min(prefix.length, before.length) && prefix[prefix.length - left - 1] === before[before.length - left - 1]) left++;
  while (right < Math.min(suffix.length, after.length) && suffix[right] === after[right]) right++;
  const heading = a && a.heading !== undefined ? a.heading
    : cmhAnchorLegacyHeading(c);
  const id = !!(a && a.block && a.block.id && b && a.block.id === b.id);
  const sameBlock = !!(a && a.block && b && a.block.text
    && a.block.tag === b.tag && a.block.from === 0 && b.end - b.start <= CMH_ANCHOR_SNAPSHOT
    && clean(a.block.text) === clean(text.slice(b.start, b.end)));
  return { score: Math.min(left, 40) + Math.min(right, 40) + (id ? 24 : 0)
    + (b && heading && heading === b.heading ? 20 : 0) + (sameBlock ? 32 : 0),
    context: left + right, left, right, id, sameBlock };
}
function cmhAnchorChoose(index, hits, a, c, quote) {
  if (!hits || !hits.length) return null;
  const work = hits.length * (CTX_PAD * 8 + MAX_BLOCK_LEN * 6 + CMH_ANCHOR_SNAPSHOT * 2);
  if (index.budget < work) return null;
  index.budget -= work;
  const ranked = hits.map(hit => ({ ...hit, evidence: cmhAnchorContextScore(index, hit, a, c) }))
    .sort((x, y) => y.evidence.score - x.evidence.score);
  const best = ranked[0], evidence = best.evidence;
  if (!cmhAnchorRepeatedSafe(a, evidence)) return null;
  if (a && a.block && a.block.id && index.blocks.some(b => b.id === a.block.id)
    && !evidence.id && evidence.context < 16) return null;
  if (ranked.length === 1) {
    if (a && a.block && !evidence.sameBlock && !evidence.id
      && evidence.context < 8 && quote.trim().length < 32) return null;
    if (evidence.sameBlock || (!a && best.start === c.start && best.end === c.end)
      || quote.trim().length >= 8 || evidence.context >= 8
      || (evidence.id && evidence.context >= 3)) return best;
    return null;
  }
  if (evidence.score < 16 || evidence.score - ranked[1].evidence.score < 12
    || (!evidence.sameBlock && evidence.context < 6)) return null;
  return best;
}
function cmhAnchorRepeatedSafe(a, evidence) {
  if (!a || a.unique !== false) return true;
  const clean = value => cmhAnchorNormalize(value || "", !!a.code, false).text;
  return !!(a.blockUnique && evidence.sameBlock || evidence.id && a.identityUnique !== false
    || a.contextUnique && evidence.context >= 16
      && evidence.left === clean((a.prefix || "").slice(-CTX_PAD * 2)).length
      && evidence.right === clean((a.suffix || "").slice(0, CTX_PAD * 2)).length);
}
function cmhAnchorEditMap(oldText, newText, index) {
  // A bounded character alignment is used only for a small, locally identified block.
  const cells = (oldText.length + 1) * (newText.length + 1);
  if (cells > 1000000 || index.budget < cells) return null;
  index.budget -= cells;
  const width = newText.length + 1;
  const dp = new Uint32Array(cells);
  for (let i = 0; i <= oldText.length; i++) dp[i * width] = i;
  for (let j = 0; j <= newText.length; j++) dp[j] = j;
  for (let i = 1; i <= oldText.length; i++) {
    for (let j = 1; j <= newText.length; j++) dp[i * width + j] = Math.min(
      dp[(i - 1) * width + j] + 1, dp[i * width + j - 1] + 1,
      dp[(i - 1) * width + j - 1] + (oldText[i - 1] === newText[j - 1] ? 0 : 1));
  }
  const distance = dp[cells - 1];
  if (distance > Math.max(3, Math.floor(Math.max(oldText.length, newText.length) * 0.2))) return null;
  const map = new Int32Array(oldText.length).fill(-1);
  let i = oldText.length, j = newText.length;
  while (i || j) {
    const current = dp[i * width + j];
    if (i && j && current === dp[(i - 1) * width + j - 1]
      + (oldText[i - 1] === newText[j - 1] ? 0 : 1)) {
      if (oldText[i - 1] === newText[j - 1]) map[i - 1] = j - 1;
      i--; j--;
    } else if (i && current === dp[(i - 1) * width + j] + 1) i--;
    else if (j > 0) j--;
    else return null;
  }
  return map;
}
function cmhAnchorFuzzy(index, a) {
  if (!a || !a.block || !a.block.text || a.block.from !== 0 || a.code) return null;
  const old = a.block, candidates = [];
  const blocks = index.blocks.filter(b => b.tag === old.tag
    && (old.id ? b.id === old.id : (!a.heading || b.heading === a.heading)));
  if (blocks.length > 16) return null;
  for (const block of blocks) {
    const cells = (old.text.length + 1) * (block.end - block.start + 1);
    const work = a.unique === false ? CTX_PAD * 8 + MAX_BLOCK_LEN * 6 + CMH_ANCHOR_SNAPSHOT * 2 : 0;
    if (cells > 1000000 || index.budget < cells + work) continue;
    index.budget -= work;
    const current = index.text.slice(block.start, block.end);
    const map = cmhAnchorEditMap(old.text, current, index);
    if (!map) continue;
    const s = old.start, e = old.end;
    let left = s - 1, right = e;
    while (left >= 0 && map[left] < 0) left--;
    while (right < map.length && map[right] < 0) right++;
    let start, end;
    if (s === 0 && e === old.text.length) { start = 0; end = current.length; }
    else if ((s === 0 || (left >= 0 && s - left <= 4))
      && (e === map.length || (right < map.length && right - e <= 4))) {
      start = s === 0 ? (map[0] >= 0 ? map[0] : 0) : map[left] + 1;
      end = e === map.length ? (map[e - 1] >= 0 ? map[e - 1] + 1 : current.length) : map[right];
    }
    else continue;
    if (end <= start) continue;
    let unchanged = 0;
    for (let k = s; k < e; k++) if (map[k] >= start && map[k] < end) unchanged++;
    // Never turn deletion into a neighbouring word, or accept id-only rewritten content.
    if (unchanged < Math.max(3, (e - s) * 0.45)) continue;
    let flank = 0;
    for (let k = Math.max(0, s - 24); k < s; k++) if (map[k] >= 0) flank++;
    for (let k = e; k < Math.min(map.length, e + 24); k++) if (map[k] >= 0) flank++;
    if (!(s === 0 && e === map.length) && flank < 16) continue;
    const hit = { start: block.start + start, end: block.start + end, block };
    if (a.unique === false && !cmhAnchorRepeatedSafe(a, cmhAnchorContextScore(index, hit, a, {}))) continue;
    candidates.push(hit);
  }
  return candidates.length === 1 ? candidates[0] : null;
}
function cmhAnchorLegacySelector(c) {
  if (c.isCode || typeof c.blockText !== "string" || !c.blockText
    || c.blockText.length > CMH_ANCHOR_SNAPSHOT || /\.\.\.$|\u2026$/.test(c.blockText)
    || typeof c.quote !== "string" || !c.quote || c.quote.length > CMH_ANCHOR_SNAPSHOT
    || typeof c.blockTag !== "string") return null;
  const quote = cmhAnchorNormalize(c.quote, false, false).text;
  const text = cmhAnchorNormalize(c.blockText, false, false).text;
  const start = text.indexOf(quote);
  if (start < 0 || text.indexOf(quote, start + 1) >= 0) return null;
  return { heading: cmhAnchorLegacyHeading(c),
    block: { id: "", tag: c.blockTag, from: 0, text, start, end: start + quote.length } };
}
function cmhAnchorLegacyHeading(c) {
  if (!Array.isArray(c.headingPath) || !c.headingPath.length) return "";
  return cmhAnchorHash(JSON.stringify(c.headingPath.slice(0, 6).map(h => ({
    level: h && typeof h.level === "number" ? h.level : 0,
    text: h && typeof h.text === "string" ? h.text.slice(0, MAX_BLOCK_LEN) : ""
  }))));
}
function cmhAnchorFlanked(index, a) {
  if (!a || a.code || typeof a.exact !== "string" || !a.exact
    || typeof a.prefix !== "string" || typeof a.suffix !== "string"
    || a.prefix.length < 12 || a.suffix.length < 12) return null;
  const prefix = a.prefix.slice(-48), suffix = a.suffix.slice(0, 48);
  const left = cmhAnchorOccurrences(index, prefix, false, false);
  const right = cmhAnchorOccurrences(index, suffix, false, false);
  if (!left || !right) return null;
  const candidates = [];
  for (const l of left) {
    for (const r of right) {
      const start = l.end, end = r.start;
      if (end <= start || end - start > a.exact.length * 1.5 + 16) continue;
      const block = cmhAnchorBlock(index, l.start, r.end);
      if (!block || block.code || (a.block && a.block.id && block.id !== a.block.id)) continue;
      if (a.unique === false) {
        const work = CTX_PAD * 8 + MAX_BLOCK_LEN * 6 + CMH_ANCHOR_SNAPSHOT * 2;
        if (index.budget < work) return null;
        index.budget -= work;
        if (!cmhAnchorRepeatedSafe(a, cmhAnchorContextScore(index, { start, end, block }, a, {}))) continue;
      }
      const old = prefix + a.exact + suffix;
      const current = index.text.slice(l.start, r.end);
      const map = cmhAnchorEditMap(old, current, index);
      if (!map) continue;
      let unchanged = 0;
      for (let k = prefix.length; k < prefix.length + a.exact.length; k++) {
        if (map[k] >= prefix.length && map[k] < current.length - suffix.length) unchanged++;
      }
      if (unchanged < Math.max(3, a.exact.length * 0.45)) continue;
      candidates.push({ start, end, block });
      if (candidates.length > 1) return null;
    }
  }
  return candidates.length === 1 ? candidates[0] : null;
}
function cmhReattachComments() {
  const roots = comments.filter(cmhIsTextAnchor);
  if (!roots.length) return;
  const index = cmhAnchorIndex();
  let changed = false;
  for (const c of roots) {
    const prior = JSON.stringify([c.start, c.end, c.detached, c.cmAnchor]);
    const hasMetadata = c.cmAnchor != null, raw = hasMetadata ? c.cmAnchor : null;
    const valid = cmhAnchorMetadataValid(raw);
    const a = valid ? raw : null;
    const knownVersion = raw && typeof raw === "object" && !Array.isArray(raw) && raw.v === 1;
    let hit = null;
    if (!index.limited && (!hasMetadata || valid || knownVersion)) {
      const quote = a && typeof a.exact === "string" && a.exact ? a.exact : typeof c.quote === "string" ? c.quote : "";
      if (a && !quote && a.revision === index.revision && a.end <= index.text.length)
        hit = { start: a.start, end: a.end };
      else if (a && a.revision === index.revision && a.start === c.start && a.end === c.end
        && Number.isInteger(c.start) && c.start >= 0 && c.end > c.start && c.end <= index.text.length
        && index.text.slice(c.start, c.end) === quote) hit = { start: c.start, end: c.end };
      else if (!quote && !hasMetadata && Number.isInteger(c.start) && Number.isInteger(c.end)
        && c.start >= 0 && c.end > c.start && c.end <= index.text.length) hit = { start: c.start, end: c.end };
      else if (quote) {
        hit = cmhAnchorChoose(index, cmhAnchorOccurrences(index, quote, !!(a && a.code || c.isCode), false), a, c, quote);
        if (!hit && !(a && a.code || c.isCode)) hit = cmhAnchorChoose(index,
          cmhAnchorOccurrences(index, quote, false, true), a, c, quote);
        if (!hit && !(a && a.discontiguous)) hit = cmhAnchorFuzzy(index, a && a.block ? a : cmhAnchorLegacySelector(c));
        if (!hit && !(a && a.discontiguous)) hit = cmhAnchorFlanked(index, a);
      }
    }
    if (hit) {
      if (!a) c.cmAnchor = { ...(knownVersion ? raw : {}), v: 1,
        original: raw && raw.original || cmhAnchorOriginal(c) };
      c.start = hit.start; c.end = hit.end; c.detached = false;
      cmhCaptureTextAnchor(c, index);
      if (c.cmAnchor && c.cmAnchor.v === 1) delete c.cmAnchor.reason;
    } else if (a && a.discontiguous && c.start === undefined && c.end === undefined) {
      c.detached = true;
    } else if (!hasMetadata && c.start === undefined && c.end === undefined
      && typeof c.quote === "string" && /\.\.\.|\u2026/.test(c.quote)) {
      // Older sorted-table exports deliberately retain a discontiguous quote without offsets.
    } else cmhDetachComment(c, index.limited ? "budget" : "unresolved");
    if (JSON.stringify([c.start, c.end, c.detached, c.cmAnchor]) !== prior) changed = true;
  }
  if (changed && !saveComments() && _cmhLastSaveQuota) {
    showStartupDiagnostic("Reattached comment locations NOT saved to this browser (storage full) "
      + "- use Manage storage or Export as Shareable before reloading.", { alert: true, duration: 8000 });
  }
}
