// Provenance is the one thing a cast must NOT be able to assert about itself.
//
// `render` warns when a cast was captured elsewhere, because the home-path and account-name rules
// are built from whoever is RENDERING - so a cast captured on another machine is scanned with the
// wrong rules and a clean scan means very little. That decision used to read a `scrubbedBy` field
// from inside the cast, which any file can write, so forging it suppressed exactly the warning that
// said the scan was not authoritative.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  castDigest, recordCapture, wasCapturedHere, ledgerPath, MAX_LEDGER_ENTRIES,
} from "../tools/provenance.mjs";

const freshDir = () => fs.mkdtempSync(path.join(os.tmpdir(), "demo-video-prov-"));

test("provenance cannot be asserted by the cast's own contents (DEMO-SAFE-26)", () => {
  const dir = freshDir();
  const real = JSON.stringify({ version: 1, scrubbedBy: "demo-video", events: [{ t: 0, data: "hi" }] });
  assert.equal(wasCapturedHere(dir, real), false, "nothing is trusted before it is recorded");

  recordCapture(dir, real);
  assert.equal(wasCapturedHere(dir, real), true, "the bytes this machine wrote are recognised");

  // The forgery this exists to defeat: a cast from somewhere else that CLAIMS to be ours.
  const forged = JSON.stringify({ version: 1, scrubbedBy: "demo-video", events: [{ t: 0, data: "elsewhere" }] });
  assert.equal(wasCapturedHere(dir, forged), false, "a self-asserted marker must not confer provenance");

  // Any edit at all breaks the match, because the digest covers the whole file.
  const tampered = real.replace("hi", "hj");
  assert.equal(wasCapturedHere(dir, tampered), false, "an edited cast is no longer the one we captured");

  // The ledger holds only digests - it must never become a second copy of what was captured.
  const ledger = fs.readFileSync(ledgerPath(dir), "utf8");
  assert.ok(!ledger.includes("hi"), "the ledger must not contain captured content");
  assert.ok(ledger.includes(castDigest(real)), "the ledger records the digest");
});

test("the ledger stays bounded and survives a damaged file (DEMO-SAFE-27)", () => {
  const dir = freshDir();
  for (let i = 0; i < MAX_LEDGER_ENTRIES + 25; i++) recordCapture(dir, `cast-${i}`);
  const entries = JSON.parse(fs.readFileSync(ledgerPath(dir), "utf8")).captures;
  assert.equal(entries.length, MAX_LEDGER_ENTRIES, "the ledger must not grow without bound");
  assert.equal(wasCapturedHere(dir, `cast-${MAX_LEDGER_ENTRIES + 24}`), true, "the newest entry is kept");
  assert.equal(wasCapturedHere(dir, "cast-0"), false, "the oldest entries fall off");

  // A corrupt ledger must fail CLOSED - unrecognised, therefore warned about - not throw and not
  // silently vouch for everything.
  fs.writeFileSync(ledgerPath(dir), "{ not json");
  assert.equal(wasCapturedHere(dir, "cast-1"), false);
  assert.doesNotThrow(() => recordCapture(dir, "cast-after-damage"));
  assert.equal(wasCapturedHere(dir, "cast-after-damage"), true, "recording recovers from a damaged ledger");

  // Recording the same bytes twice leaves one entry, not a growing pile of duplicates.
  const before = JSON.parse(fs.readFileSync(ledgerPath(dir), "utf8")).captures.length;
  recordCapture(dir, "cast-after-damage");
  const after = JSON.parse(fs.readFileSync(ledgerPath(dir), "utf8")).captures.length;
  assert.equal(after, before, "re-recording the same cast must not duplicate its entry");
});
