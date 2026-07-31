// DEMO-CLI-01..03. The recorder's pure core is unit tested, but the CLI wiring around it was not -
// and a missing import in the capture path (scrubText) shipped undetected because nothing exercised
// the command line at all. These tests drive the real entry point in a subprocess for every path
// that does NOT need a browser or a PTY: the plan, the argument contract, and the safety gate.

import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchSpec } from "../tools/record_demo.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TOOL = path.join(HERE, "..", "tools", "record_demo.mjs");

function run(args) {
  return spawnSync(process.execPath, [TOOL, ...args], { encoding: "utf8" });
}

// Scratch casts go to the OS temp dir, never into the repo.
function tempCast(cast) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "demo-video-cli-"));
  const file = path.join(dir, "probe.cast.json");
  fs.writeFileSync(file, JSON.stringify(cast));
  return { file, cleanup: () => fs.rmSync(dir, { recursive: true, force: true }) };
}

test("report --list prints a plan that sums to the requested length (DEMO-CLI-01)", () => {
  const res = run(["report", "--list", "--seconds", "12"]);
  assert.equal(res.status, 0, res.stderr);
  const info = JSON.parse(res.stdout);
  assert.equal(info.seconds, 12);
  assert.equal(path.basename(info.example), "report-community-garden.html");
  assert.ok(fs.existsSync(info.example), `the default example is missing: ${info.example}`);
  assert.ok(info.output.endsWith(".webm"), "the output is not a web-embeddable clip");
  assert.equal(info.beats.reduce((a, b) => a + b.budgetMs, 0), 12000);
  assert.ok(info.beats.length > 5, "the montage lost most of its beats");
});

test("the argument contract fails loudly rather than guessing (DEMO-CLI-02)", () => {
  // Each of these used to be accepted and quietly ignored, which means recording the wrong thing.
  const unknown = run(["report", "--list", "--bogus"]);
  assert.notEqual(unknown.status, 0, "an unknown option was accepted");
  assert.match(unknown.stderr, /unknown option --bogus/);

  const twice = run(["report", "--list", "--seconds", "10", "--seconds", "20"]);
  assert.notEqual(twice.status, 0, "a repeated option was accepted");
  assert.match(twice.stderr, /twice/i);

  const noValue = run(["report", "--seconds"]);
  assert.notEqual(noValue.status, 0, "a value-less option was accepted");
  assert.match(noValue.stderr, /requires a value/i);

  const negative = run(["report", "--list", "--seconds", "-5"]);
  assert.notEqual(negative.status, 0, "a negative duration was accepted");

  const unknownSubject = run(["wat"]);
  assert.notEqual(unknownSubject.status, 0, "an unknown subject was accepted");

  // An option that belongs to ANOTHER subject is rejected rather than silently ignored: accepting
  // `scan --out x` tells the caller nothing and does not do what they asked.
  const wrongSubject = run(["scan", "--cast", path.join(os.tmpdir(), "x.cast.json"), "--seconds", "10"]);
  assert.notEqual(wrongSubject.status, 0, "scan accepted an option it does not use");
  assert.match(wrongSubject.stderr, /does not use --seconds/);
  const alsoWrong = run(["report", "--list", "--cast", "x"]);
  assert.notEqual(alsoWrong.status, 0, "report accepted --cast");

  const missingExample = run(["report", "--list", "--example", path.join(HERE, "no-such.html")]);
  assert.notEqual(missingExample.status, 0, "a missing example was accepted");
  assert.match(missingExample.stderr, /no-such\.html/);
});

test("the safety gate refuses a dirty cast before any browser starts (DEMO-CLI-03)", () => {
  // The gate must fail FAST and by default. This also pins that `scan` and the render gate read the
  // cast's COMMAND, not just its output - a credential passed on the command line is still a leak.
  const dirty = tempCast({
    version: 1,
    command: "gh auth login --with-token ghp_0123456789abcdefghijklmnopqrstuvwxyzAB",
    cols: 80,
    rows: 24,
    events: [{ t: 0, data: "ok\r\n" }],
  });
  try {
    const scan = run(["scan", "--cast", dirty.file]);
    assert.notEqual(scan.status, 0, "scan passed a cast whose command carries a token");
    assert.match(scan.stdout, /findings:\s*[1-9]/);

    const render = run(["render", "--cast", dirty.file]);
    assert.notEqual(render.status, 0, "render filmed a cast that scans dirty");
    assert.match(render.stderr, /scans dirty/i);
  } finally {
    dirty.cleanup();
  }

  const clean = tempCast({
    version: 1,
    command: "npm test",
    cols: 80,
    rows: 24,
    scrubbedBy: "demo-video",
    events: [{ t: 0, data: "86 passing\r\n" }],
  });
  try {
    const scan = run(["scan", "--cast", clean.file]);
    assert.equal(scan.status, 0, scan.stderr);
    assert.match(scan.stdout, /findings:\s*0/);
  } finally {
    clean.cleanup();
  }

  const missing = run(["scan", "--cast", path.join(os.tmpdir(), "definitely-not-here.cast.json")]);
  assert.notEqual(missing.status, 0, "a missing cast was accepted");
});

test("a Windows shim is launched through its interpreter (DEMO-CLI-04)", () => {
  // resolveExecutable finds `copilot.cmd` on PATH, but node-pty cannot spawn a .cmd or .ps1
  // directly - so the documented `capture -- copilot` flow failed for every CLI that installs as a
  // shim (which is most of them on Windows) even though the file was right there.
  const cmd = launchSpec("C:\\tools\\copilot.cmd", ["-p", "hi"], "win32");
  assert.match(cmd.file, /cmd\.exe$/i);
  assert.deepEqual(cmd.args.slice(-3), ["C:\\tools\\copilot.cmd", "-p", "hi"]);

  const ps = launchSpec("C:\\tools\\thing.ps1", ["--flag"], "win32");
  assert.match(ps.file, /powershell\.exe$/i);
  assert.ok(ps.args.includes("-File"));
  assert.deepEqual(ps.args.slice(-2), ["C:\\tools\\thing.ps1", "--flag"]);

  // A real executable is launched directly, and nothing is wrapped off Windows.
  const exe = launchSpec("C:\\tools\\copilot.exe", ["-p", "hi"], "win32");
  assert.deepEqual(exe, { file: "C:\\tools\\copilot.exe", args: ["-p", "hi"] });
  assert.deepEqual(launchSpec("/usr/bin/copilot", ["-p"], "linux"), { file: "/usr/bin/copilot", args: ["-p"] });
});


test("a trim cannot decide what the safety gate sees (DEMO-TRIM-06)", () => {
  // The whole point of trimming is to drop the tail - so if the gate ran on the KEPT span, an
  // operator could trim a leaked credential out of the gate's view and publish everything before
  // it. The scan runs on the whole cast, before any trim, and still refuses.
  const dirty = tempCast({
    version: 1,
    command: "npm test",
    cols: 80,
    rows: 24,
    scrubbedBy: "demo-video",
    marks: [{ label: "ask", t: 0, eventIndex: 0, text: "do the thing" }],
    events: [
      { t: 0, data: "do the thing\r\n" },
      { t: 1000, data: "DONE\r\n" },
      // Only in the tail, which --until drops.
      { t: 2000, data: "gh auth login --with-token ghp_0123456789abcdefghijklmnopqrstuvwxyzAB\r\n" },
    ],
  });
  try {
    const render = run(["render", "--cast", dirty.file, "--until", "DONE"]);
    assert.notEqual(render.status, 0, "a trim hid a credential from the gate");
    assert.match(render.stderr, /scans dirty/i);
  } finally {
    dirty.cleanup();
  }
});

test("render refuses a trim it cannot honour rather than filming the whole tail (DEMO-TRIM-07)", () => {
  const cast = tempCast({
    version: 1,
    command: "npm test",
    cols: 80,
    rows: 24,
    scrubbedBy: "demo-video",
    marks: [{ label: "ask", t: 0, eventIndex: 0, text: "do the thing" }],
    events: [{ t: 0, data: "do the thing\r\n" }, { t: 1000, data: "DONE\r\n" }],
  });
  try {
    const res = run(["render", "--cast", cast.file, "--until", "NEVER-PRINTED"]);
    assert.notEqual(res.status, 0, "a mistyped marker silently rendered the whole session");
    assert.match(res.stderr, /never appears after the "ask" mark/);
  } finally {
    cast.cleanup();
  }
});
