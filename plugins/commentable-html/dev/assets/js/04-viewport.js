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

// Every subscriber shares ONE set of listeners, so a layer that re-subscribes per open surface
// cannot multiply them; the returned function unsubscribes. A subscriber that throws must not stop
// the others (a stale surface should never freeze the live ones).
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
