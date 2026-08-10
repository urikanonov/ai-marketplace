// The mermaid-pin agreement decision, extracted from capture_tutorial.mjs so it can be tested
// directly (CMH-BUILD-24). Pure: it takes the three versions and returns either null (agreement) or
// the message to refuse with. All file reading stays in the caller.
//
// Why this exists at all: the tutorial capture serves mermaid from `node_modules` through a
// deliberately version-AGNOSTIC route, and the entry module's relative chunk imports resolve back
// through that same route - so a render is internally consistent at WHATEVER version is on disk.
// Without this check the committed screenshots can be rendered from a mermaid that never ships, and
// the only symptom is an unexplained exact-pixel drift failure in a different CI job.

/** The version a `^`/`~`/exact dependency spec pins to, or "" when there is no spec. */
export function pinnedVersion(pkg) {
  const deps = pkg || {};
  const spec = (deps.devDependencies || {}).mermaid || (deps.dependencies || {}).mermaid;
  return String(spec || "").replace(/^[\^~]/, "");
}

/** The mermaid version a package-lock.json resolves, or null when it does not resolve one. */
export function lockedVersion(lock) {
  const entry = (((lock || {}).packages) || {})["node_modules/mermaid"];
  return (entry && entry.version) || null;
}

/**
 * null when the installed mermaid is the pinned one; otherwise the refusal message.
 *
 * The two mismatch causes need DIFFERENT advice, which is the whole reason this is not a one-liner:
 * a stale install is fixed by `npm ci`, but a lockfile that has moved ABOVE the pin is REPRODUCED
 * by `npm ci`, so advising it there would loop forever.
 */
export function pinMismatchMessage({ pinned, installed, locked }) {
  if (installed === pinned) return null;
  const remedy = locked && locked === installed
    ? `package.json pins ${pinned} but package-lock.json resolves ${locked}, so \`npm ci\` will ` +
      "keep reproducing this. Bump the package.json pin to match and re-vendor " +
      "assets/vendor/mermaid.min.js per assets/vendor/UPSTREAM.md."
    : "Run `npm ci` in plugins/commentable-html/dev and re-run the capture.";
  return `capture_tutorial: installed mermaid ${installed} does not match the pinned ${pinned}. ` +
    "The capture serves mermaid from node_modules, so it would render the committed tutorial " +
    "screenshots with a version that never ships, and CI (which installs the pinned version) " +
    "would then fail the exact-pixel drift gate for no visible reason. " + remedy;
}

export const NOT_INSTALLED_MESSAGE =
  "capture_tutorial: mermaid is not installed; run `npm ci` in plugins/commentable-html/dev";
