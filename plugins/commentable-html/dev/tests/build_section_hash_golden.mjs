// Regenerate the JS/Python section-hash golden: `node tests/build_section_hash_golden.mjs`
// (add --check to verify it is in sync). The `hash` values are the authoritative shared contract
// pinned by tests/test_section_hash_golden.py (Python) and tests/NN-review.spec.js (the runtime).
// cmhSectionHash MUST stay byte-identical to assets/js/84-section-review.js.
import { readFileSync, writeFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
const here = dirname(fileURLToPath(import.meta.url));
const goldenPath = join(here, "fixtures", "section_hash", "golden.json");
function cmhSectionHash(text) {
  const s = String(text == null ? "" : text).replace(/[ \t\n\r\f\v\u00a0]+/g, " ").replace(/^ | $/g, "");
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(36);
}
const samples = [
  "",
  "Summary",
  "1. Goals This section states the goals of the plan.",
  "  leading and   collapsed\twhitespace\nacross\nlines  ",
  "Unicode: cafe\u0301 na\u00efve \u4e2d\u6587 review",
  "Emoji rocket \ud83d\ude80 and check \u2713",
  "Comparisons: keep p95 < 200ms and rps > 1k",
  "A longer body paragraph. It has several sentences. Numbers 1 2 3, and punctuation!",
  "Section with a nested heading 2.1 Details and its body text.",
  "Non-breaking\u00a0spaces\u00a0between\u00a0words",
];
const golden = samples.map((text) => ({ text, hash: cmhSectionHash(text) }));
const json = JSON.stringify(golden, null, 2) + "\n";
if (process.argv.includes("--check")) {
  const cur = readFileSync(goldenPath, "utf8");
  if (cur !== json) { console.error("section-hash golden is stale; run: node tests/build_section_hash_golden.mjs"); process.exit(1); }
  console.log("section-hash golden OK (" + golden.length + " entries)");
} else {
  writeFileSync(goldenPath, json);
  console.log("wrote " + golden.length + " golden entries to " + goldenPath);
}
