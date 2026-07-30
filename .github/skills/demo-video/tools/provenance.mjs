// Provenance for a cast, kept OUT OF BAND.
//
// `render` warns when a cast was captured somewhere else, because the home-path and account-name
// rules are built from whoever is RENDERING - a cast captured on another machine is scanned with
// the wrong rules and a clean scan means very little. That warning used to be decided by a
// `scrubbedBy` field inside the cast, which is a claim the file makes about itself: anyone can
// write it, and writing it suppresses the one signal that says the scan was not authoritative.
//
// So the claim moves out of the file. `capture` records the hash of exactly the bytes it wrote in a
// local ledger; `render` hashes the file it was handed and looks for it there. A cast from anywhere
// else is simply not in this machine's ledger, whatever it says about itself. Forging now means
// writing the ledger too, which is a different and much less accidental act - and the ledger holds
// only hashes, so it reveals nothing about what was captured.

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export const LEDGER_NAME = ".provenance.json";
// Bounded so a long-lived ledger cannot grow without limit; the oldest entries fall off first.
export const MAX_LEDGER_ENTRIES = 500;

export function castDigest(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

export function ledgerPath(dir) {
  return path.join(dir, LEDGER_NAME);
}

function readLedger(file) {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    return Array.isArray(parsed.captures) ? parsed.captures : [];
  } catch (e) {
    return [];
  }
}

// Records that THIS machine produced these exact bytes. Best-effort: a recorder that cannot write
// its ledger should still finish the capture, it just means a later render will warn.
export function recordCapture(dir, bytes, { now = () => new Date().toISOString(), maxEntries = MAX_LEDGER_ENTRIES } = {}) {
  const digest = castDigest(bytes);
  const file = ledgerPath(dir);
  const captures = readLedger(file).filter((entry) => entry && entry.digest !== digest);
  captures.push({ digest, at: now() });
  const trimmed = captures.slice(-maxEntries);
  try {
    fs.mkdirSync(dir, { recursive: true });
    // Written to a unique temporary file and renamed into place. A read-modify-write of the whole
    // ledger is not atomic, so two captures finishing together could otherwise leave a
    // half-written file - which a later read would reject, marking a cast this machine really did
    // capture as foreign. Rename is atomic, so a reader always sees one whole ledger or the other.
    const staging = `${file}.${process.pid}.${Date.now()}.tmp`;
    fs.writeFileSync(staging, JSON.stringify({ captures: trimmed }, null, 2));
    fs.renameSync(staging, file);
  } catch (e) { /* a ledger we cannot write just means a later render warns */ }
  return digest;
}

// Was this exact cast captured on this machine? Nothing inside the cast is consulted.
export function wasCapturedHere(dir, bytes) {
  const digest = castDigest(bytes);
  return readLedger(ledgerPath(dir)).some((entry) => entry && entry.digest === digest);
}
