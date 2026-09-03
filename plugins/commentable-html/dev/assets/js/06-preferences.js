/* ---------- Reviewer preferences (scoped: a cross-document default + a per-document override) ----------
   Today's only preference is "Auto-open panel on comment". It governs every path where the panel
   opens ITSELF - a saved comment, the load-time restore, and the first note/checklist/widget change
   that raises a card - which is the right default; a reviewer who reads full width with the panel
   collapsed turns it off. An EXPLICIT Show/panel action always opens it. The DEFAULT is cross-document (AUTO_OPEN_PANEL_KEY); a document that must differ
   pins its own value in AUTO_OPEN_PANEL_DOC_KEY, and dropping that key re-inherits the default.
   Every read and write is try/catch guarded, so a browser that denies storage (private mode) simply
   degrades to the ON default instead of throwing. */
const CMH_PREF_ON = "1";
const CMH_PREF_OFF = "0";

function cmhReadPref(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}
function cmhWritePref(key, value) {
  try { localStorage.setItem(key, value); return true; } catch (e) { return false; }
}
function cmhClearPref(key) {
  try { localStorage.removeItem(key); return true; } catch (e) { return false; }
}

// The cross-document default. ON unless a stored value explicitly says otherwise.
function autoOpenPanelDefault() {
  return cmhReadPref(AUTO_OPEN_PANEL_KEY) !== CMH_PREF_OFF;
}
function setAutoOpenPanelDefault(on) {
  return cmhWritePref(AUTO_OPEN_PANEL_KEY, on ? CMH_PREF_ON : CMH_PREF_OFF);
}
// The per-document override: true/false when pinned, null when the document inherits the default.
function autoOpenPanelOverride() {
  const raw = cmhReadPref(AUTO_OPEN_PANEL_DOC_KEY);
  if (raw === CMH_PREF_ON) return true;
  if (raw === CMH_PREF_OFF) return false;
  return null;
}
function setAutoOpenPanelOverride(value) {
  if (value === null) return cmhClearPref(AUTO_OPEN_PANEL_DOC_KEY);
  return cmhWritePref(AUTO_OPEN_PANEL_DOC_KEY, value ? CMH_PREF_ON : CMH_PREF_OFF);
}
// What this document actually does: its own pinned value, else the cross-document default.
function autoOpenPanelEnabled() {
  const pinned = autoOpenPanelOverride();
  return pinned === null ? autoOpenPanelDefault() : pinned;
}
// The deck's "Comments off" state is a present-only lock that is only valid with ZERO comments, so a
// comment landing there must still surface the panel (issue #659) even when auto-open is off -
// otherwise that comment is stranded behind a lock that now contradicts it. The deck registers its
// predicate here at startup; a flow document never registers one. This is a CLOSURE variable, not a
// window global: the partials share one IIFE scope, so nothing outside the runtime can define it
// and force the panel open against the reviewer's preference.
let _cmhForcePanelPredicate = null;
function cmhRegisterForcePanelOnComment(fn) {
  _cmhForcePanelPredicate = (typeof fn === "function") ? fn : null;
}
function cmhPanelForcedOnComment() {
  try { return !!(_cmhForcePanelPredicate && _cmhForcePanelPredicate()); } catch (e) { return false; }
}
// Should the panel open ITSELF for a state change that raises a card - the load-time restore and
// the first note/checklist/widget change? An EXPLICIT Show/panel action never asks.
function cmhShouldAutoOpenPanel() {
  return autoOpenPanelEnabled();
}
// The same question for a SAVED COMMENT, which carries the deck carve-out above. Kept separate so
// the carve-out cannot leak to a caller where it is not valid: forcing the panel open for a
// note/checklist/widget change in a comments-off deck would be reverted by the deck observer, and
// the reader of either function does not have to reason about the other's call sites.
function cmhShouldAutoOpenPanelOnComment() {
  return autoOpenPanelEnabled() || cmhPanelForcedOnComment();
}

/* "Show times in UTC": the display zone every rendered timestamp is formatted in. Off by default,
   so an existing document reads exactly as it always has - local time, now with the local zone
   named beside it. On, the instant is normalized to UTC and labelled UTC. Cross-document only:
   a reviewer reads in one zone, whatever document they happen to open. */
function utcTimesEnabled() {
  return cmhReadPref(UTC_TIMES_KEY) === CMH_PREF_ON;
}
function setUtcTimes(on) {
  return cmhWritePref(UTC_TIMES_KEY, on ? CMH_PREF_ON : CMH_PREF_OFF);
}
// The display zone the RENDERED output currently carries. A `storage` event fires for every key in
// the origin - and on file:// every commentable-html document shares one - so re-stamping on each
// one would rebuild the comment list, and drop the reviewer's scroll position, for a preference
// that did not change. These answer "did the zone REALLY change since we last drew it?".
let _cmhAppliedUtcTimes = utcTimesEnabled();
function cmhUtcTimesChanged() {
  return _cmhAppliedUtcTimes !== utcTimesEnabled();
}
function cmhMarkUtcTimesApplied() {
  _cmhAppliedUtcTimes = utcTimesEnabled();
}
