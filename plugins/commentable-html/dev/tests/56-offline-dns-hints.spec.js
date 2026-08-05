// The DNS measurement behind the CMH-OFFLINE-04 rule that `preconnect` and `dns-prefetch` are
// removed from an offline export UNCONDITIONALLY (#1076), kept as its own spec because it LAUNCHES
// ITS OWN BROWSER: the configuration is the measurement, so it cannot reuse the suite's managed
// Chromium, and a browser-spawning spec belongs in the `heavy` project rather than thrashing a
// `fast` shard (see tests/_projects.mjs).
//
// The instrument is Chromium's own NetLog, read as HOST_RESOLVER EVENTS rather than as raw text - a
// DNS-capable observer, unlike the TCP listener the scheme probe in 49-offline-export.spec.js uses,
// which by construction cannot see a lookup that never connects (which is why both relations are
// parked in that probe's unobserved list). Reading events matters: Chromium logs the full URL of an
// ordinary request in its `URL_REQUEST` entries, so a substring search over the file would report a
// host as "resolved" on a log that captured no resolver activity at all - the exact vacuity the
// positive control exists to rule out.
//
// The verdict this reproduces (Chromium 149): ZERO resolver activity for a `preconnect`/`dns-prefetch`
// host in ANY scheme - the `http:` and `https:` CONTROL hints included - from a `file:` document AND
// from an `http:` one, while an ordinary image reference in the same document does produce a resolver
// job. (The same result was measured once by hand on the full headed binary; CI runs the headless
// engine, so that half stays a recorded observation rather than something this test re-verifies.)
// A control that measures zero cannot license a boundary: this instrument cannot separate "a
// non-fetchable scheme is inert here" from "this build does not drive the hint at all", so no
// measurement supports keeping such a hint in any scheme, which is exactly why the strip removes
// both relations unconditionally instead of asking the per-resource href predicate.
//
// What the test therefore asserts is the two halves that ARE decidable: the image control must
// produce a resolver job (or the observer is broken and every zero below is vacuous), and if a hint
// host EVER shows up in a resolver event, the "these hints are unmeasurable, so remove them
// unconditionally" reasoning has been overtaken by the engine and the spec row must be re-read - the
// unconditional strip is then not merely safe but load-bearing. It is a tripwire and a record, not a
// regression test: it passes on the pre-change build too, because it measures the ENGINE rather than
// the exporter. The product test in 49-offline-export.spec.js is the red-first one.
import { test, expect, chromium } from "@playwright/test";
import fs from "fs";
import path from "path";
import { DEV, fileUrl, startStaticServer } from "./helpers.js";

function makeTmpDir() {
  const repoRoot = path.resolve(DEV, "..", "..", "..");
  const tmpRoot = path.join(repoRoot, "tmp");
  fs.mkdirSync(tmpRoot, { recursive: true });
  return fs.mkdtempSync(path.join(tmpRoot, "cmh_dns_"));
}

const HINT_CHANNELS = ["ftp-preconnect", "ftp-dns-prefetch", "custom-dns-prefetch",
                       "http-preconnect", "http-dns-prefetch", "https-preconnect"];

// Every host is under the reserved `.invalid` TLD (RFC 6761), so nothing this probe asks for can
// reach a real machine even where a resolver is configured. What is measured is whether Chromium
// creates a resolver JOB at all, which it logs before any query leaves the process - so the
// measurement does not depend on a lookup succeeding, or on the runner having DNS.
const hintMarkup = (tag) => [
  `<link rel="preconnect" href="ftp://cmh-${tag}-ftp-preconnect.invalid">`,
  `<link rel="dns-prefetch" href="ftp://cmh-${tag}-ftp-dns-prefetch.invalid">`,
  `<link rel="dns-prefetch" href="x-cmh-probe://cmh-${tag}-custom-dns-prefetch.invalid">`,
  `<link rel="preconnect" href="http://cmh-${tag}-http-preconnect.invalid">`,
  `<link rel="dns-prefetch" href="http://cmh-${tag}-http-dns-prefetch.invalid">`,
  `<link rel="preconnect" href="https://cmh-${tag}-https-preconnect.invalid">`,
].join("\n");
const controlHost = (tag) => `cmh-${tag}-img-control.invalid`;
const probeDoc = (tag) => `<!DOCTYPE html><html><head><meta charset="utf-8"><title>dns probe</title>
${hintMarkup(tag)}
</head><body><p id="probe-ready">probe</p>
<img src="http://${controlHost(tag)}/control.png" alt=""></body></html>`;

test("CMH-OFFLINE-04: a DNS-capable observer measures what a preconnect or dns-prefetch hint resolves from a file: document", async () => {
  test.setTimeout(180000);
  const dir = makeTmpDir();
  let probeBrowser;
  let server;
  try {
    // Two documents, one hint host each, so a resolver job can be attributed to the ORIGIN the hint
    // was written in: a `file:` document (the shipped case) and an `http:` one (the control for
    // "maybe the opaque origin is what suppressed it").
    const probe = path.join(dir, "dns-probe.html");
    fs.writeFileSync(probe, probeDoc("file"));
    const httpDir = path.join(dir, "served");
    fs.mkdirSync(httpDir, { recursive: true });
    fs.writeFileSync(path.join(httpDir, "dns-probe.html"), probeDoc("http"));
    server = await startStaticServer(httpDir);

    const netlog = path.join(dir, "netlog.json");
    probeBrowser = await chromium.launch({
      // Playwright disables background networking by default, which is exactly the machinery a
      // speculative hint drives - measuring with it on would make every zero below meaningless.
      ignoreDefaultArgs: ["--disable-background-networking"],
      args: [`--log-net-log=${netlog}`, "--net-log-capture-mode=Everything",
             "--enable-features=NetworkPrediction"],
    });
    for (const url of [fileUrl(probe), server.url + "/dns-probe.html"]) {
      const probePage = await probeBrowser.newPage();
      // `domcontentloaded`, not `load`: the control image points at a host that cannot resolve, so
      // waiting for the load event would wait out its request rather than the document, and a
      // black-holed resolver on a CI runner would turn that into a navigation timeout. The resolver
      // job is created when the request STARTS, which is all this measures.
      await probePage.goto(url, { waitUntil: "domcontentloaded" });
      await expect(probePage.locator("#probe-ready")).toHaveCount(1);
      // Give a hint every chance to act AFTER the document has settled, so a zero is a measurement
      // rather than a race.
      await probePage.waitForTimeout(5000);
    }
    // The log is finalized on browser shutdown, so it is read only after the browser is gone.
    await probeBrowser.close();
    probeBrowser = null;

    const log = JSON.parse(fs.readFileSync(netlog, "utf8"));
    const resolverTypeIds = new Set(
      Object.entries((log.constants || {}).logEventTypes || {})
        .filter(([name]) => name.includes("HOST_RESOLVER"))
        .map(([, id]) => id));
    expect(resolverTypeIds.size,
           "this netlog declares no HOST_RESOLVER event types, so it cannot answer the question - "
           + "the capture mode or the constants layout changed and this probe must be re-pointed")
      .toBeGreaterThan(0);
    const resolverEvents = (log.events || [])
      .filter((e) => resolverTypeIds.has(e.type))
      .map((e) => JSON.stringify(e));
    const resolverJobs = (host) => resolverEvents.filter((e) => e.includes(host)).length;

    for (const tag of ["file", "http"]) {
      expect(resolverJobs(controlHost(tag)),
             `the image control in the ${tag}: document produced no HOST_RESOLVER event, so this `
             + "netlog cannot say anything about the hints beside it - the observer, not the "
             + "browser, is what failed").toBeGreaterThan(0);
    }
    const resolved = [];
    for (const tag of ["file", "http"]) {
      for (const channel of HINT_CHANNELS) {
        if (resolverJobs(`cmh-${tag}-${channel}.invalid`) > 0) resolved.push(`${tag}:${channel}`);
      }
    }
    expect(resolved,
           "a preconnect/dns-prefetch hint reached the host resolver, which the measurement behind "
           + "CMH-OFFLINE-04 did not observe. That does not make the unconditional strip wrong - it "
           + "makes it load-bearing - but re-read the spec row: the channel is now measurable, and "
           + "any future proposal to keep such a hint when its href is not a network URL has to "
           + "answer this evidence. Channels seen: " + resolved.join(", "))
      .toEqual([]);
  } finally {
    if (probeBrowser) await probeBrowser.close();
    if (server) await server.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
