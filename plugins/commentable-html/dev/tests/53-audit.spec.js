import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { stageDeck, DEV } from "./helpers.js";

// The audit harness (dev/tools/audit.mjs) must tour a document end to end and emit screenshots
// plus a machine-readable observations.json that a reviewing agent (or several) can consume.
test("CMH-DECK-AUDIT-01: the audit harness tours a deck and emits screenshots + observations", async () => {
  const { html } = stageDeck(
    '<section class="slide active" data-slide-id="slide-aaaaaaaa"><h2>A</h2><p>alpha slide</p></section>'
    + '<section class="slide" data-slide-id="slide-bbbbbbbb"><h2>B</h2><p>beta slide</p></section>');
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_audit_"));
  const r = spawnSync("node", [path.join(DEV, "tools", "audit.mjs"), "--target", html, "--out", out],
    { encoding: "utf8" });
  expect(r.status, r.stderr).toBe(0);

  const obs = JSON.parse(fs.readFileSync(path.join(out, "observations.json"), "utf8"));
  expect(obs.isDeck).toBe(true);
  expect(obs.slideCount).toBe(2);
  expect(Array.isArray(obs.steps)).toBe(true);
  expect(fs.existsSync(path.join(out, "report.md"))).toBe(true);

  // the tour actually toured: it captured each slide and entered comment mode, and each named
  // step points at a screenshot that exists on disk.
  const stepNames = obs.steps.map((s) => s.name);
  for (const req of ["slide-1", "slide-2", "comment-mode"]) {
    expect(stepNames).toContain(req);
  }
  for (const s of obs.steps) {
    expect(fs.existsSync(path.join(out, s.screenshot))).toBe(true);
  }

  const shots = fs.readdirSync(path.join(out, "screenshots")).filter((f) => f.endsWith(".png"));
  expect(shots.length).toBeGreaterThan(4);

  // a bad target fails the harness (exit non-zero)
  const bad = spawnSync("node", [path.join(DEV, "tools", "audit.mjs"), "--target", path.join(out, "nope.html")],
    { encoding: "utf8" });
  expect(bad.status).not.toBe(0);
});
