import test from "node:test";
import assert from "node:assert/strict";

import {
  windowLabel,
  promptFromCommand,
  askFromCast,
  terminalPage,
  stagePage,
} from "../tools/record_demo.mjs";

// A realistic leaky invocation: the flags name internal MCP servers, and nothing in them is a
// secret by any rule, so no redaction pass can catch them.
const LEAKY = "C:\\Users\\demo\\AppData\\Local\\copilot.cmd --banner --disable-mcp-server kusto"
  + " --disable-mcp-server geneva-mcp-server --disable-mcp-server azure";

// The page builders read xterm off disk; CI runs this suite without installing it, so the stubs
// keep these tests hermetic while still exercising the real page assembly.
const XTERM = { js: "/* xterm */", css: "/* xterm */" };

function buildTerminalPage(cast, args) {
  return terminalPage({
    cast,
    timeline: { events: [], durationMs: 0 },
    fontSize: 24,
    endHoldMs: 0,
    introMs: 0,
    ask: askFromCast(cast, args),
    title: windowLabel(cast.command, args),
    xterm: XTERM,
  });
}

function buildStagePage(cast, args) {
  return stagePage({
    cast,
    segments: [{ events: [] }],
    fontSize: 24,
    introMs: 0,
    endHoldMs: 0,
    ask: askFromCast(cast, args),
    reportUrl: "./report.html",
    title: windowLabel(cast.command, args),
    xterm: XTERM,
  });
}

test("the launch command is reduced to its program name (DEMO-SAFE-31)", () => {
  assert.equal(windowLabel(LEAKY), "copilot");
  assert.equal(windowLabel("copilot --banner --disable-mcp-server kusto"), "copilot");
  assert.equal(windowLabel("/usr/local/bin/copilot -p 'do the thing'"), "copilot");
  // A quoted program path with spaces is one token, not two.
  assert.equal(windowLabel('"C:\\Program Files\\Copilot\\copilot.exe" --disable-mcp-server azure'), "copilot");
  // ...and so is an UNQUOTED one, which is the shape a cast actually stores. Splitting on
  // whitespace here published a directory-name fragment - the same internal-inventory leak class.
  assert.equal(windowLabel("C:\\Program Files\\Copilot\\copilot.exe --flag"), "copilot");
  assert.equal(
    windowLabel("C:\\Users\\alice\\Contoso Secret Project\\bin\\copilot.exe --banner"),
    "copilot");
  assert.equal(windowLabel(""), "session");
  assert.equal(windowLabel(null), "session");
  assert.equal(windowLabel("   "), "session");

  // A leading environment assignment is the shell's, not the program - and it can carry a token, so
  // publishing it as the window title would be a worse leak than the flags this fix removes.
  assert.equal(windowLabel("FOO=bar copilot --banner"), "copilot");
  assert.equal(windowLabel("API_TOKEN=abc123 KUSTO_HOST=internal.example copilot --banner"), "copilot");
  // Nothing that is not a plausible bare program name may be published at all.
  assert.equal(windowLabel("--disable-mcp-server kusto"), "session");
  assert.equal(windowLabel("API_TOKEN=abc123"), "session");

  for (const label of [windowLabel(LEAKY), windowLabel("FOO=bar copilot --disable-mcp-server nexus")]) {
    assert.ok(!label.includes("--"), `flags survived into ${label}`);
    assert.ok(!/mcp|kusto|geneva|azure|nexus|token/i.test(label), `internal detail survived into ${label}`);
  }
});

test("an operator can still opt into showing the whole command (DEMO-SAFE-32)", () => {
  const command = "copilot --banner -p 'review this'";
  // The CLI spelling is what every production caller passes: parseArgs stores --show-command under
  // the DASHED key, so testing only the camelCase alias would leave the real branch uncovered.
  assert.equal(windowLabel(command, { "show-command": true }), command);
  assert.equal(windowLabel(command, { showCommand: true }), command);
  // Opting in is explicit: any other shape of options keeps the safe default.
  assert.equal(windowLabel(command, {}), "copilot");
  assert.equal(windowLabel(command, { showCommand: false }), "copilot");
  assert.equal(windowLabel(command, { "show-command": "yes" }), "copilot");
});

test("a -p prompt never drags the flags that follow it (DEMO-SAFE-33)", () => {
  // The extraction used to run to end-of-string, so everything after the prompt was painted across
  // the title card in the largest type in the clip.
  assert.equal(
    promptFromCommand('copilot -p "review this" --disable-mcp-server kusto --disable-mcp-server azure'),
    "review this");
  assert.equal(
    promptFromCommand("copilot --banner -p write the docs --disable-mcp-server azure"),
    "write the docs");
  assert.equal(promptFromCommand("copilot -p short"), "short");
  assert.equal(promptFromCommand("copilot -p 'single quoted prompt' --banner"), "single quoted prompt");
  assert.equal(promptFromCommand("copilot --banner"), null);
  assert.equal(promptFromCommand("copilot -p"), null);
  assert.equal(promptFromCommand(null), null);

  for (const command of [
    'copilot -p "review this" --disable-mcp-server kusto',
    "copilot -p review this --disable-mcp-server geneva-mcp-server",
  ]) {
    const prompt = promptFromCommand(command);
    assert.ok(!prompt.includes("--"), `flags survived into the prompt: ${prompt}`);
    assert.ok(!/mcp|kusto|geneva/i.test(prompt), `internal detail survived into the prompt: ${prompt}`);
  }
});

test("the title card never falls back to the raw command (DEMO-SAFE-33)", () => {
  // With no -p prompt and no --ask there is nothing to state, so it degrades to the program name
  // rather than painting the invocation across the card.
  const ask = askFromCast({ command: LEAKY }, {});
  assert.equal(ask, "copilot");
  assert.ok(!ask.includes("--disable-mcp-server"), "the card published the launch flags");
  // The card is fed through the same bounded extraction, so flags AFTER the prompt never ride onto
  // it either - the ordering that made this the loudest surface in the clip.
  assert.equal(
    askFromCast({ command: 'copilot -p "review this" --disable-mcp-server kusto' }, {}),
    "review this");
  // A real prompt is still preferred, an explicit --ask still wins, and a mark beats both.
  assert.equal(askFromCast({ command: "copilot -p write the docs" }, {}), "write the docs");
  assert.equal(askFromCast({ command: LEAKY }, { ask: "a short ask" }), "a short ask");
  assert.equal(
    askFromCast({ command: LEAKY, marks: [{ label: "ask", text: " from the mark " }] }, {}),
    "from the mark");
});

// The helpers above are only worth anything if the PAGES actually use them. Reverting either page
// builder to interpolate cast.command - the exact regression that shipped - must not stay green.
test("neither rendered page publishes the launch command (DEMO-SAFE-34)", () => {
  const commands = [
    LEAKY,
    // -p FIRST, flags after: the ordering that leaks through a greedy prompt extraction.
    'copilot -p "review this" --disable-mcp-server kusto --disable-mcp-server geneva-mcp-server',
    `${LEAKY} -p "review this"`,
  ];
  for (const [name, build] of [["terminal", buildTerminalPage], ["stage", buildStagePage]]) {
    for (const command of commands) {
      const html = build({ cols: 80, rows: 24, command }, {});
      assert.ok(html.includes('"copilot"'), `${name} page lost the safe label`);
      assert.ok(!html.includes("disable-mcp-server"),
        `${name} page published the launch flags for: ${command}`);
    }
    assert.ok(!build({ cols: 80, rows: 24, command: LEAKY }, {}).includes("AppData"),
      `${name} page published the operator's path`);
    // Opting in still works, so the flag is not silently dead.
    const shown = build({ cols: 80, rows: 24, command: LEAKY }, { "show-command": true });
    assert.ok(shown.includes("disable-mcp-server"), `${name} page ignored --show-command`);
  }
});
