/* ---------- The one shared viewport vocabulary (issue #880) ----------
   `window.innerWidth` / `innerHeight` describe the LAYOUT viewport. On mobile that is not what the
   reader can see: an on-screen keyboard (iOS Safari, and Chrome for Android with the default
   `interactive-widget=resizes-visual`) and a pinch zoom shrink and MOVE the VISUAL viewport while
   leaving the layout viewport untouched, and they fire `resize` / `scroll` on
   `window.visualViewport` rather than on `window`. A `position: fixed` control placed from layout
   measurements can therefore sit behind the keyboard - and focusing a comment textarea is exactly
   what opens it. Every floating affordance in this layer measures through these helpers and
   subscribes through `cmhOnViewportChange`, so the surfaces can never disagree about which
   viewport they mean. */

// The VISIBLE viewport box, in the client coordinates `getBoundingClientRect()` and
// `position: fixed` both use. `offsetLeft` / `offsetTop` are the visible box's origin within the
// layout viewport, so they are as load-bearing as the size while a pinch-zoomed page is panned.
function cmhViewportBox() {
  const vv = window.visualViewport;
  if (vv && vv.width && vv.height) {
    return { left: vv.offsetLeft || 0, top: vv.offsetTop || 0, width: vv.width, height: vv.height };
  }
  return { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
}

// The same box as edges, inset by `margin`, for the clamp helpers.
function cmhViewportRect(margin) {
  const b = cmhViewportBox();
  const m = margin || 0;
  return {
    left: b.left + m,
    top: b.top + m,
    right: b.left + b.width - m,
    bottom: b.top + b.height - m,
  };
}

/* ---------- Scroll guard (issue #838) ----------
   Chromium keeps the reader's place across layout changes with SCROLL ANCHORING: it picks an anchor
   node inside the document and silently shifts `window.scrollY` when a later layout moves that node.
   Opening a comment composer is exactly such a mutation (it wraps the selection in preview marks and
   appends a surface), and the browser's adjustment lands a frame AFTER the composer has been placed
   from the anchor's rect - so the document jumps out from under a `position: fixed` composer that
   stays put, and the selected text and its composer come apart. Wrap such a mutation in a guard: it
   makes the CONTENT ROOT ineligible as an anchor (`overflow-anchor` on the document element does not
   suppress the viewport scroller's anchoring, only excluding the subtree the anchor is picked from
   does), restores the scroll offset if the browser moved it anyway, and hands anchoring back once
   the mutation's layout has been through a frame - so the behavior stays available for everything
   else (content growing above the viewport while images or diagrams render). The guard is for a
   SYNCHRONOUS mutation: its watchdog lifts the suppression a frame later, so an async caller would
   lose it mid-mutation. */
var _cmhScrollGuards = 0;
var _cmhScrollGuardPrior = null;
function cmhBeginScrollGuard() {
  const anchored = root || document.body;
  const x = window.scrollX, y = window.scrollY;
  if (_cmhScrollGuards === 0 && anchored && anchored.style) {
    // The content root is the layer's own element, but the `document.body` fallback is the host
    // author's - so put back exactly what was there (value and priority) rather than assuming none.
    _cmhScrollGuardPrior = {
      value: anchored.style.getPropertyValue("overflow-anchor"),
      priority: anchored.style.getPropertyPriority("overflow-anchor"),
    };
    // `!important` so an author rule cannot out-cascade the suppression and let the jump back in.
    anchored.style.setProperty("overflow-anchor", "none", "important");
  }
  _cmhScrollGuards += 1;
  let released = false;
  const restore = function () {
    // The count is dropped HERE, not when the caller ends its guard, so the suppression is held
    // until the LAST guard's frames have run: an earlier guard must not strip the property out
    // from under a composer that opened one frame later.
    _cmhScrollGuards = Math.max(0, _cmhScrollGuards - 1);
    if (_cmhScrollGuards !== 0 || !anchored || !anchored.style) return;
    const prior = _cmhScrollGuardPrior;
    _cmhScrollGuardPrior = null;
    if (prior && prior.value) anchored.style.setProperty("overflow-anchor", prior.value, prior.priority);
    else anchored.style.removeProperty("overflow-anchor");
  };
  const release = function (restoreScroll) {
    if (released) return;
    released = true;
    // A same-turn shift (an engine that compensates synchronously) is put straight back. The
    // DEFERRED adjustment this bug is about is not rewound here - it is prevented by the
    // suppression above, since a frame later a scroll offset may be the reader's own. The behavior
    // is pinned instant: a host `scroll-behavior: smooth` would otherwise animate this restore and
    // land it after the suppression is gone, which is the very fight the guard exists to avoid.
    if (restoreScroll && (window.scrollX !== x || window.scrollY !== y)) {
      try { window.scrollTo({ left: x, top: y, behavior: "instant" }); } catch (e) { /* detached */ }
    }
    // Hand scroll anchoring back only after the frame that lays the mutation out, since that is the
    // layout the browser would otherwise compensate for. The second frame is what makes this hold.
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(function () { requestAnimationFrame(restore); });
    } else {
      restore();
    }
  };
  // A caller that throws before ending its guard must not leave anchoring off for the session. That
  // watchdog only lifts the suppression: a frame later a scroll offset is as likely to be the
  // reader's own as the browser's, so it is never rewound from here. It falls back to a timer where
  // there is no rAF, so a leaked guard cannot stick there either.
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(function () { release(false); });
  else if (typeof setTimeout === "function") setTimeout(function () { release(false); }, 0);
  return function () { release(true); };
}

// Every subscriber shares ONE set of native listeners, so the layer never registers them more than
// once; the returned function unsubscribes. (The Set holds whatever callbacks it is given - a caller
// that passed a FRESH closure per open surface would still have to unsubscribe it; every caller here
// subscribes once.) A subscriber that throws must not stop the others (a stale surface should never
// freeze the live ones).
var _cmhViewportSubs = null;
function cmhOnViewportChange(fn) {
  if (typeof fn !== "function") return function () {};
  if (!_cmhViewportSubs) {
    _cmhViewportSubs = new Set();
    const fire = function (e) {
      _cmhViewportSubs.forEach(function (sub) {
        try { sub(e); } catch (err) { /* one bad subscriber must not stop the rest */ }
      });
    };
    window.addEventListener("resize", fire);
    const vv = window.visualViewport;
    if (vv && vv.addEventListener) {
      vv.addEventListener("resize", fire);
      // Panning a pinch-zoomed page moves the visible box without resizing it.
      vv.addEventListener("scroll", fire);
    }
  }
  _cmhViewportSubs.add(fn);
  return function () { if (_cmhViewportSubs) _cmhViewportSubs.delete(fn); };
}
