// The tutorial capture's Chart.js route, extracted from capture_tutorial.mjs so it can be tested
// behaviorally rather than asserted about as source text (CMH-SIZE-09). Pure: it takes the vendored
// bundle's contents and returns the version and the route pattern. All file reading stays in the
// caller.
//
// Why it is EXACT about the version, where the mermaid route (CMH-BUILD-24) is deliberately
// agnostic: the two routes serve different things. Mermaid is served from `node_modules`, so the
// route has to follow whatever is installed and a separate pin check keeps that honest. Chart.js is
// served from the COMMITTED `assets/vendor/chart.umd.min.js`, so the bytes are known and so is
// their version - and answering a request for any OTHER version with them fails that document's
// `integrity` check, which the `typeof Chart === "undefined"` guard then turns into a silently
// blank canvas. The capture can be pointed at an arbitrary example, so that is reachable rather
// than hypothetical. Falling through to the capture's catch-all abort is the honest outcome.
//
// The version is DERIVED from the bundle rather than written down, so re-vendoring Chart.js moves
// the route with it and there is no literal to forget to update.

/** The version the vendored bundle reports about itself, from its `Chart.js v<x.y.z>` banner. */
export function vendoredChartJsVersion(source) {
  const m = /Chart\.js v(\d+\.\d+\.\d+)/.exec(String(source || "").slice(0, 4000));
  if (!m) {
    throw new Error("capture_tutorial: assets/vendor/chart.umd.min.js carries no "
      + "`Chart.js v<x.y.z>` banner, so the route cannot pin the version it serves.");
  }
  return m[1];
}

/**
 * The route pattern for that exact version's MINIFIED build on jsDelivr.
 *
 * Narrow on every axis that matters: host, package, version, and the minified filename. A request
 * for the unminified build, another version, another package or another host falls through to the
 * capture's deny-all route and aborts loudly.
 */
export function chartJsRoutePattern(version) {
  if (!/^\d+\.\d+\.\d+$/.test(String(version))) {
    throw new Error("capture_tutorial: refusing to build a Chart.js route from the non-exact "
      + "version " + JSON.stringify(version));
  }
  const escaped = escapeRegExp(String(version));
  return new RegExp("^https://cdn\\.jsdelivr\\.net/npm/chart\\.js@" + escaped
    + "/dist/chart\\.umd\\.min\\.js$");
}

/**
 * Every regex metacharacter escaped, backslash included.
 *
 * The version is already constrained to `\d+\.\d+\.\d+` above, so nothing exotic can reach this -
 * but escaping only `.` was incomplete in isolation (CodeQL's incomplete-string-escaping rule), and
 * a partial escaper is exactly the thing that turns into a hole the day the validation upstream is
 * loosened. Backslash is replaced first by being part of the same single pass.
 */
export function escapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
