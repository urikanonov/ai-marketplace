// ---- Autogrowing authoring textareas (issue #851) ----
// Every surface a reviewer types a comment into - the floating composer, the side-pane inline
// reply/edit editor, and the in-document comment dialog - sizes itself to its content instead of
// staying a fixed couple of lines that has to be dragged open by hand. The growth cap is the
// element's `--cmh-grow-max` (a custom property enforced by THIS layer, deliberately not a CSS
// `max-height`, which would also bound the native resize handle), so past it the box SCROLLS
// rather than pushing Cancel/Save out of the panel, and removing text shrinks it back (the CSS
// `min-height` is the floor).
function cmhAutogrow(ta, afterResize) {
  if (!ta || ta._cmhAutogrow) return;
  ta._cmhAutogrow = true;
  ta._cmhAutogrowAfter = afterResize || null;
  ta.addEventListener("input", function () { cmhAutogrowResize(ta); });
  cmhAutogrowWatchViewport(ta);
  // A prefilled editor (editing an existing note, or a restored draft) must open at content size.
  if (ta.isConnected) cmhAutogrowResize(ta);
  else setTimeout(function () { cmhAutogrowResize(ta); }, 0);
}

function cmhAutogrowResize(ta) {
  if (!ta || !ta.isConnected || ta._cmhAutogrowManual) return;
  // An inline height this layer did not write means the reviewer dragged the `resize: vertical`
  // handle. Their size wins from then on - autogrow stops fighting it for this editor.
  if (ta._cmhAutogrowH != null && ta.style.height !== ta._cmhAutogrowH) {
    ta._cmhAutogrowManual = true;
    return;
  }
  const previous = ta.style.height;
  // Only a box whose content does NOT already overflow needs the collapse-then-measure round trip.
  // While the content overflows, `scrollHeight` is the full content height, so the collapse can be
  // skipped - which halves the forced layouts per keystroke on the very large notes this runtime
  // tolerates. (Overflow, not text length, is the right test: replacing a multi-line selection with
  // a LONGER single line makes the text grow while the box must shrink.)
  const overflowing = ta.scrollHeight > ta.clientHeight + 1;
  // Collapsing the box can clamp the scroll offset of the list it lives in, and restoring the
  // height does not restore that offset - the panel would jump under the reviewer's cursor.
  const scroller = overflowing ? null : cmhScrollParent(ta);
  const scrollTop = scroller ? scroller.scrollTop : 0;
  if (!overflowing) ta.style.height = "auto";
  const measured = ta.scrollHeight;
  if (!measured) {
    // Not rendered yet (a hidden card, a filtered list): a zero measurement would latch a zero
    // height, so keep what we had and try again shortly (bounded), as well as on the next input.
    ta.style.height = previous;
    if (scroller && scroller.scrollTop !== scrollTop) scroller.scrollTop = scrollTop;
    const tries = ta._cmhAutogrowTries || 0;
    if (tries < 5) {
      ta._cmhAutogrowTries = tries + 1;
      setTimeout(function () { cmhAutogrowResize(ta); }, 100);
    }
    return;
  }
  ta._cmhAutogrowTries = 0;
  const cs = window.getComputedStyle(ta);
  let h = measured;
  // scrollHeight is the padding box, so convert it to the property the box model expects.
  if (cs.boxSizing === "border-box") {
    h += (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0);
  } else {
    h -= (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
  }
  // The cap is declared as `--cmh-grow-max` rather than a CSS `max-height` on purpose: a real
  // `max-height` would also bound the NATIVE resize handle, so a reviewer could not drag the box
  // past the cap even though a manual size is supposed to win. Capping here leaves the drag free.
  const cap = cmhAutogrowCap(cs);
  if (h > cap) h = cap;
  ta.style.height = Math.max(0, Math.ceil(h)) + "px";
  ta._cmhAutogrowH = ta.style.height;
  if (scroller && scroller.scrollTop !== scrollTop) scroller.scrollTop = scrollTop;
  // A floating surface positioned before it grew can end up hanging below the fold, taking its
  // Save button with it, so let the owner pull itself back into view after every resize.
  if (ta._cmhAutogrowAfter) ta._cmhAutogrowAfter(ta);
}

// The growth cap in px, from the element's `--cmh-grow-max` (a `vh`, `rem`, or `px` length).
// Recomputed per resize so a rotation or a window resize re-evaluates a viewport-relative cap.
// The bound is always enforced: a missing or nonsensical value falls back to a default rather than
// meaning "uncapped", and no cap may exceed the viewport (a box taller than the screen could not be
// clamped back into view), so authored CSS cannot talk this layer out of bounding an editor.
function cmhAutogrowCap(cs) {
  const raw = (cs.getPropertyValue("--cmh-grow-max") || "").trim();
  const n = parseFloat(raw);
  const vh = cmhViewportBox().height;
  let px = NaN;
  // Only the units this layer understands count. Anything else (a percentage, a typo, a unit that
  // needs a containing block) falls through to the default rather than being read as pixels.
  if (isFinite(n) && n > 0) {
    const unit = raw.slice(String(n).length).trim().toLowerCase();
    if (unit === "vh") px = vh * n / 100;
    else if (unit === "rem") {
      px = n * (parseFloat(window.getComputedStyle(document.documentElement).fontSize) || 16);
    } else if (unit === "px" || unit === "") px = n;
  }
  if (!isFinite(px) || px <= 0) px = vh * 0.45;
  return Math.min(px, Math.max(120, vh - 16));
}

// The visible viewport box. `visualViewport` accounts for pinch zoom, panning, retractable mobile
// toolbars, and the soft keyboard, and its origin is NOT (0, 0) while the user is panning a
// pinch-zoomed page, so its offsets matter as much as its size.
function cmhViewportBox() {
  const vv = window.visualViewport;
  if (vv && vv.width && vv.height) {
    return { left: vv.offsetLeft || 0, top: vv.offsetTop || 0, width: vv.width, height: vv.height };
  }
  return { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
}

// The nearest scrolling ancestor (the comments list, for a side-pane editor), falling back to the
// document scroller. An editor's ancestry does not change while it is open, so resolve it once.
function cmhScrollParent(el) {
  if (el._cmhScroller !== undefined) return el._cmhScroller;
  let p = el.parentElement;
  while (p && p !== document.body) {
    const oy = window.getComputedStyle(p).overflowY;
    if (oy === "auto" || oy === "scroll") break;
    p = p.parentElement;
  }
  el._cmhScroller = (p && p !== document.body) ? p : (document.scrollingElement || null);
  return el._cmhScroller;
}

// Keep a `position: fixed` floating surface (the composer, the in-document dialog) fully on screen
// after its editor grew: nudge it back inside the viewport on both axes so the whole box, actions
// included, stays reachable. The surfaces also carry a viewport-sized `max-height` in CSS, so one
// can never grow taller than the viewport - which is what would turn this clamp into a dead end
// that pins an unreachable box.
var cmhClampedSurfaces = null;
function cmhClampIntoViewport(el) {
  if (!el || !el.isConnected) return;
  if (!cmhClampedSurfaces) cmhClampedSurfaces = new Set();
  cmhClampedSurfaces.add(el);
  // Prune on every add: a reviewer can open and close many composers, and the Set would otherwise
  // hold every detached one alive (the close paths also unregister explicitly).
  cmhClampedSurfaces.forEach(function (s) { if (!s.isConnected) cmhClampedSurfaces.delete(s); });
  const margin = 8;
  const rect = el.getBoundingClientRect();
  const vp = cmhViewportBox();
  const topLimit = Math.max(vp.top + margin, vp.top + vp.height - el.offsetHeight - margin);
  const nextTop = Math.min(Math.max(vp.top + margin, rect.top), topLimit);
  if (Math.abs(nextTop - rect.top) >= 1) el.style.top = nextTop + "px";
  // Narrowing the window, or panning a pinch-zoomed page, can strand a surface off an edge just as
  // growth strands it below the fold, so bound the horizontal axis on the same terms.
  const leftLimit = Math.max(vp.left + margin, vp.left + vp.width - el.offsetWidth - margin);
  const nextLeft = Math.min(Math.max(vp.left + margin, rect.left), leftLimit);
  if (Math.abs(nextLeft - rect.left) >= 1) el.style.left = nextLeft + "px";
}

// A closed surface unregisters explicitly, so the registry never holds a detached editor.
function cmhForgetClampedSurface(el) {
  if (cmhClampedSurfaces && el) cmhClampedSurfaces.delete(el);
}

// A rotation, a window resize, a browser zoom, or the mobile keyboard changes both the wrap width
// and the viewport-relative cap with no `input` event, so every live editor is re-measured (and
// every floating surface re-clamped) when the viewport changes. `visualViewport` is what actually
// fires when a soft keyboard opens on iOS, so listen there too when it exists.
var cmhAutogrowLive = null;
function cmhAutogrowWatchViewport(ta) {
  if (!cmhAutogrowLive) {
    cmhAutogrowLive = new Set();
    const onViewportChange = function () {
      cmhAutogrowLive.forEach(function (t) {
        if (!t.isConnected) cmhAutogrowLive.delete(t);
        else cmhAutogrowResize(t);
      });
      if (cmhClampedSurfaces) {
        cmhClampedSurfaces.forEach(function (s) {
          if (!s.isConnected) cmhClampedSurfaces.delete(s);
          else cmhClampIntoViewport(s);
        });
      }
    };
    window.addEventListener("resize", onViewportChange);
    const vv = window.visualViewport;
    if (vv && vv.addEventListener) {
      vv.addEventListener("resize", onViewportChange);
      // Panning a pinch-zoomed page moves the visible box without resizing it.
      vv.addEventListener("scroll", onViewportChange);
    }
  }
  // Prune here as well as from the teardown paths, so an editor removed by a route that does not
  // unregister (a sidebar re-render, say) cannot accumulate in the Set.
  cmhAutogrowLive.forEach(function (t) { if (!t.isConnected) cmhAutogrowLive.delete(t); });
  cmhAutogrowLive.add(ta);
}

// An editor whose surface is torn down unregisters explicitly.
function cmhForgetAutogrow(ta) {
  if (cmhAutogrowLive && ta) cmhAutogrowLive.delete(ta);
}

// The height a reviewer set by hand, or null when the box is still auto-sized. A drag that has not
// been followed by an input yet has not latched `_cmhAutogrowManual`, so recognise it here too.
function cmhAutogrowManualHeight(ta) {
  if (!ta || !ta.style.height) return null;
  if (ta._cmhAutogrowManual) return ta.style.height;
  if (ta._cmhAutogrowH != null && ta.style.height !== ta._cmhAutogrowH) return ta.style.height;
  return null;
}
