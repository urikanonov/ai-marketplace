import test from "node:test";
import assert from "node:assert/strict";

import { windowLabel, askFromCast } from "../tools/record_demo.mjs";

// The launch command is drawn as the terminal's title bar and, when a cast carries no -p prompt,
// across the title card in large type. A real invocation carries an inventory of internal tooling,
// which is not a secret by any rule and so survives every redaction pass.
test("the launch command is reduced to its program name (DEMO-SAFE-31)", () => {
  const leaky = "copilot --banner --no-remote --disable-mcp-server kusto --disable-mcp-server geneva-mcp-server";
  assert.equal(windowLabel(leaky), "copilot");
  // A resolved shim keeps neither its directory nor its extension.
  assert.equal(windowLabel("C:\\Users\\demo\\AppData\\copilot.cmd --allow-all"), "copilot");
  assert.equal(windowLabel("/usr/local/bin/copilot -p 'do the thing'"), "copilot");
  // A quoted program path with spaces is one token, not two.
  assert.equal(windowLabel('"C:\\Program Files\\Copilot\\copilot.exe" --disable-mcp-server azure'), "copilot");
  assert.equal(windowLabel(""), "session");
  assert.equal(windowLabel(null), "session");
  // Nothing that looked like a flag may survive.
  for (const label of [windowLabel(leaky), windowLabel("copilot --disable-mcp-server nexus-meridian")]) {
    assert.ok(!label.includes("--"), `flags survived into ${label}`);
    assert.ok(!/mcp|kusto|geneva|azure|nexus/i.test(label), `internal detail survived into ${label}`);
  }
});

test("an operator can still opt into showing the whole command (DEMO-SAFE-32)", () => {
  const command = "copilot --banner -p 'review this'";
  assert.equal(windowLabel(command, { showCommand: true }), command);
  // Opting in is explicit: any other shape of options keeps the safe default.
  assert.equal(windowLabel(command, {}), "copilot");
  assert.equal(windowLabel(command, { showCommand: false }), "copilot");
});

test("the title card never falls back to the raw command (DEMO-SAFE-33)", () => {
  const cast = { command: "copilot --banner --disable-mcp-server kusto --disable-mcp-server azure" };
  // With no -p prompt and no --ask there is nothing to state, so it must degrade to the program
  // name rather than painting the invocation across the card.
  const ask = askFromCast(cast, {});
  assert.equal(ask, "copilot");
  assert.ok(!ask.includes("--disable-mcp-server"), "the card published the launch flags");
  // A real prompt is still preferred, and an explicit --ask still wins.
  assert.equal(askFromCast({ command: "copilot -p write the docs" }, {}), "write the docs");
  assert.equal(askFromCast(cast, { ask: "a short ask" }), "a short ask");
});
