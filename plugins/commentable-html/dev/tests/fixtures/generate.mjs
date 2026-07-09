// Generates the rich edge-case sample fixtures the E2E suite runs against, so the
// anchoring is exercised on nested inline elements, entities, Unicode/emoji, RTL,
// links, tables and code blocks - not just the skill's own demo content.
//
//   node tests/fixtures/generate.mjs           # (re)generate the fixtures
//   node tests/fixtures/generate.mjs --check   # fail if committed fixtures are stale
//
// Fixtures are DERIVED from the current TEMPLATE.html + dist/ (which tools/build.py
// generates), so after changing the layer run tools/build.py then this. The --check mode
// is wired into the test suite so stale fixtures fail CI.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url)); // dev/tests/fixtures
const DEV = path.resolve(HERE, "..", "..");                // dev
// Marketplace pkg/dev split: the fixtures are written here under dev, but they are DERIVED
// from the shipped skill (TEMPLATE.html + dist/) which lives under pkg.
const SKILL = path.resolve(DEV, "..", "pkg", "skills", "commentable-html");
const DIST = path.join(SKILL, "dist");
// Relative path from the economy fixture's own directory to the shipped dist/, so its
// companion <link>/<script src> references resolve across the pkg/dev split over file://.
const DIST_REL = path.relative(path.join(HERE, "economy"), DIST).replace(/\\/g, "/") + "/";
const lf = (s) => s.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
const read = (p) => lf(fs.readFileSync(p, "utf8"));

const content = read(path.join(HERE, "sample-content.html")).replace(/^<!--[\s\S]*?-->\s*/, "").replace(/\s+$/, "");
const CONTENT_RE = /(<!-- BEGIN: commentable-html v2 - CONTENT[^>]*-->)[\s\S]*?(<!-- END: commentable-html v2 - CONTENT -->)/;

function mustReplace(html, needle, repl, label) {
  if (!html.includes(needle)) throw new Error("generate.mjs: expected to find " + label + " (" + JSON.stringify(needle) + ") in the source template");
  return html.replace(needle, repl);
}

function inject(html, o) {
  if (!CONTENT_RE.test(html)) throw new Error("no CONTENT region in source template");
  html = html.replace(CONTENT_RE, (_m, a, b) => a + "\n" + content + "\n" + b);
  html = mustReplace(html, 'data-comment-key="' + o.oldKey + '"', 'data-comment-key="' + o.key + '"', "comment-key");
  html = mustReplace(html, 'data-doc-source="' + o.oldDocSource + '"', 'data-doc-source="' + o.docSource + '"', "doc-source");
  if (!/<title>[\s\S]*?<\/title>/.test(html)) throw new Error("generate.mjs: no <title> in source template");
  html = html.replace(/<title>[\s\S]*?<\/title>/, "<title>" + o.title + "</title>");
  return html;
}

// The economy fixture is a real economy document whose companion <link>/<script src>
// normally sit next to it. To avoid a THIRD copy of the css/js/assets.js in the repo
// (they already live in the shipped dist/), point the fixture's companion refs at the
// shipped dist/ via DIST_REL. Only the load attributes are rewritten, not the filenames
// shown as <code> in the missing-asset banner.
function referenceDistCompanions(html) {
  return html
    .replace(/(<link\b[^>]*\bhref=")(commentable-html\.v[0-9.]+\.css")/i, "$1" + DIST_REL + "$2")
    .replace(/(<script\b[^>]*\bsrc=")(commentable-html\.v[0-9.]+\.assets\.js")/i, "$1" + DIST_REL + "$2")
    .replace(/(<script\b[^>]*\bsrc=")(commentable-html\.v[0-9.]+\.js")/i, "$1" + DIST_REL + "$2");
}

function buildOutputs() {
  const outputs = {};
  outputs[path.join(HERE, "kitchen-sink.html")] = inject(read(path.join(SKILL, "TEMPLATE.html")), {
    oldKey: "commentable-html-demo-v1", key: "kitchen-sink-inline-v1",
    oldDocSource: "TEMPLATE.html", docSource: "kitchen-sink.html",
    title: "Kitchen-sink sample (inline)",
  });
  outputs[path.join(HERE, "economy", "kitchen-sink.html")] = referenceDistCompanions(
    inject(read(path.join(DIST, "ECONOMY.html")), {
      oldKey: "commentable-html-economy-demo-v1", key: "kitchen-sink-economy-v1",
      oldDocSource: "ECONOMY.html", docSource: "kitchen-sink.html",
      title: "Kitchen-sink sample (economy)",
    }));
  return outputs;
}

const outputs = buildOutputs();
if (process.argv.includes("--check")) {
  const drift = [];
  for (const [p, text] of Object.entries(outputs)) {
    if (!fs.existsSync(p)) drift.push(path.relative(DEV, p) + " (missing)");
    else if (read(p) !== lf(text)) drift.push(path.relative(DEV, p) + " (out of date)");
  }
  if (drift.length) {
    console.error("fixtures --check FAILED; run `node tests/fixtures/generate.mjs`:\n  " + drift.join("\n  "));
    process.exit(1);
  }
  console.log("fixtures --check OK (" + Object.keys(outputs).length + " files in sync)");
} else {
  for (const [p, text] of Object.entries(outputs)) {
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, lf(text), "utf8");
  }
  console.log("generated " + Object.keys(outputs).length + " fixture files");
}
