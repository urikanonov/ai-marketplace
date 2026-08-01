import test from "node:test";
import assert from "node:assert/strict";

import {
  windowLabel,
  promptFromCommand,
  tokenizeCommand,
  joinCommand,
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
    args,
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
    args,
    xterm: XTERM,
  });
}

test("the launch command is reduced to its program name (DEMO-SAFE-31)", () => {
  assert.equal(windowLabel(LEAKY), "copilot");
  assert.equal(windowLabel("copilot --banner --disable-mcp-server kusto"), "copilot");
  assert.equal(windowLabel("/usr/local/bin/copilot -p 'do the thing'"), "copilot");
  // A quoted program path with spaces is one token, not two.
  assert.equal(windowLabel('"C:\\Program Files\\Copilot\\copilot.exe" --disable-mcp-server azure'), "copilot");
  // ...and so is an UNQUOTED one, which is the shape a legacy cast stores. Splitting on whitespace
  // here published a directory-name fragment - the same internal-inventory leak class.
  assert.equal(windowLabel("C:\\Program Files\\Copilot\\copilot.exe --flag"), "copilot");
  assert.equal(
    windowLabel("C:\\Users\\alice\\Contoso Secret Project\\bin\\copilot.exe --banner"),
    "copilot");
  // ...but recovering that path must NOT run across argument boundaries: a VALUE ending in .exe
  // once dragged the flag before it into the label ("copilot --config secrets").
  assert.equal(windowLabel("copilot --config secrets.exe --disable-mcp-server azure"), "copilot");
  assert.equal(windowLabel("copilot --out C:\\tmp\\report.exe --banner"), "copilot");
  // The scan is greedy, so a DIRECTORY that merely contains a dotted name does not end it early -
  // "contoso.com Projects" used to publish "contoso".
  assert.equal(windowLabel("C:\\Users\\alice\\contoso.com Projects\\bin\\copilot.exe --x"), "copilot");
  assert.equal(windowLabel("C:\\Users\\alice\\My.cmd Tools\\bin\\copilot.exe"), "copilot");
  // A rooted path with NO recognisable executable extension is published only when what follows it
  // is a flag; if the next token could be part of a split path, nothing is published rather than
  // the directory fragment the first token would give.
  assert.equal(windowLabel("/usr/local/bin/copilot -p do the thing"), "copilot");
  assert.equal(windowLabel("/usr/local/bin/copilot"), "copilot");
  assert.equal(windowLabel("C:\\Users\\alice\\Contoso Secret Project\\bin\\copilot --x"), "session");
  assert.equal(windowLabel("/Users/alice/Contoso Secret Project/bin/copilot --x"), "session");
  assert.equal(windowLabel("/opt/Acme Stealth Project/bin/copilot --banner"), "session");
  // A basename that begins with a dash is not a plausible program name either.
  assert.equal(windowLabel("bin/-weird.exe"), "session");
  // A `-p` sitting inside another argument's quoted VALUE is not the prompt flag.
  assert.equal(windowLabel('copilot --note "value -p hidden" --banner'), "copilot");
  // An unterminated quote swallowed the rest of the line, so nothing in it can be trusted -
  // publishing that token put the whole flag tail in the window title.
  assert.equal(windowLabel('"C:\\Program Files\\copilot.exe --banner'), "session");
  assert.equal(windowLabel('"C:\\Contoso Secret Project\\bin\\" --disable-mcp-server kusto'), "session");
  // A token ending in a separator has no basename; falling back to the whole token published the
  // entire path, so this fails closed like every other rejection here.
  assert.equal(windowLabel('"C:\\Contoso Secret Project\\bin\\"'), "session");
  assert.equal(windowLabel(""), "session");
  assert.equal(windowLabel(null), "session");
  assert.equal(windowLabel("   "), "session");

  // A leading environment assignment is the shell's, not the program - and it can carry a token, so
  // publishing it as the window title would be a worse leak than the flags this fix removes.
  assert.equal(windowLabel("FOO=bar copilot --banner"), "copilot");
  assert.equal(windowLabel("API_TOKEN=abc123 KUSTO_HOST=internal.example copilot --banner"), "copilot");
  // An assignment IN FRONT of a spaced path must not skip the path recovery: checking the raw
  // string rather than what follows the assignments republished the directory fragment.
  assert.equal(
    windowLabel("FOO=bar C:\\Users\\alice\\Contoso Secret Project\\bin\\copilot.exe --banner"),
    "copilot");
  assert.equal(
    windowLabel("FOO=bar C:\\Users\\alice\\Contoso Secret Project\\bin\\copilot --banner"),
    "session");
  // Nothing that is not a plausible bare program name may be published at all.
  assert.equal(windowLabel("--disable-mcp-server kusto"), "session");
  assert.equal(windowLabel("API_TOKEN=abc123"), "session");

  for (const label of [windowLabel(LEAKY), windowLabel("FOO=bar copilot --disable-mcp-server nexus")]) {
    assert.ok(!label.includes("--"), `flags survived into ${label}`);
    assert.ok(!/mcp|kusto|geneva|azure|nexus|token/i.test(label), `internal detail survived into ${label}`);
  }
});

test("a cast's argv gives the program name exactly, with no guessing (DEMO-SAFE-35)", () => {
  // Reverse engineering the program out of a joined string is lossy in both directions: a path with
  // spaces looks like several arguments, and a VALUE ending in .exe looks like a path. A cast now
  // stores argv, so the label is read straight off argv[0] and neither shape can mislead it.
  assert.equal(windowLabel(["C:\\Program Files\\Copilot\\copilot.exe", "--config", "secrets.exe"]), "copilot");
  assert.equal(windowLabel(["/usr/local/bin/copilot", "--disable-mcp-server", "kusto"]), "copilot");
  assert.equal(windowLabel([]), "session");
  assert.equal(windowLabel(["--disable-mcp-server", "kusto"]), "session");
  // Opting in still renders the whole invocation, re-quoted so it stays readable.
  assert.match(
    windowLabel(["C:\\Program Files\\Copilot\\copilot.exe", "--banner"], { "show-command": true }),
    /^"C:\\Program Files\\Copilot\\copilot\.exe" --banner$/);
  // The prompt is read off argv too, where each element is an EXACT token: a prompt may begin with
  // a dash, and a following positional argument is never joined onto it.
  assert.equal(promptFromCommand(["copilot", "-p", "review this", "--disable-mcp-server", "kusto"]),
    "review this");
  assert.equal(promptFromCommand(["copilot", "-p", "--summarize the log"]), "--summarize the log");
  assert.equal(promptFromCommand(["copilot", "-p", "review", "internal-host-name"]), "review");
  // An unterminated quote means the rest of the line was swallowed, so no prompt is trusted.
  assert.equal(promptFromCommand('copilot -p "never closed --disable-mcp-server kusto'), null);
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
  // `-p` inside ANOTHER argument's quoted value is not the prompt flag, so an unrelated argument is
  // never painted across the card.
  assert.equal(promptFromCommand('copilot --note "value -p hidden words" --banner'), null);
  // A quoted prompt is one token, so it may legitimately begin with a dash.
  assert.equal(promptFromCommand('copilot -p "-leading dash prompt" --banner'), "-leading dash prompt");
  assert.equal(promptFromCommand("copilot -p=inline --banner"), "inline");
  // `-p="x y"` starts BARE, so the flag is still recognised even though its value is quoted.
  assert.equal(promptFromCommand('copilot -p="review this" --disable-mcp-server kusto'), "review this");
});

test("the stored command round-trips a path with spaces (DEMO-SAFE-36)", () => {
  // This is the line that keeps windowLabel safe for tool-produced casts: joining argv bare loses
  // the boundary, and the path then reads as several tokens. It had no test, so reverting it was
  // silent - the same "safety lives in an uncovered line" class as the page-builder gap.
  const argv = ["/opt/Acme Stealth Project/bin/copilot", "--banner", "--disable-mcp-server", "kusto"];
  const stored = joinCommand(argv);
  assert.equal(stored, '"/opt/Acme Stealth Project/bin/copilot" --banner --disable-mcp-server kusto');
  assert.equal(windowLabel(stored), "copilot");
  // Without the quoting the path is unrecoverable, and nothing may be published.
  assert.equal(windowLabel(argv.join(" ")), "session");
  // An embedded quote is escaped rather than closing the value early, and so is a backslash - a
  // value ending in a path separator must round-trip rather than escaping its own closing quote.
  assert.equal(joinCommand(['say "hi" now']), '"say \\"hi\\" now"');
  assert.equal(joinCommand(["C:\\Contoso Secret Project\\bin\\"]),
    '"C:\\\\Contoso Secret Project\\\\bin\\\\"');
  assert.equal(tokenizeCommand(joinCommand(["C:\\Contoso Secret Project\\bin\\"]))[0].value,
    "C:\\Contoso Secret Project\\bin\\");
  assert.equal(joinCommand([]), "");

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
  // A real prompt is still preferred, an explicit --ask still wins, and the ask MARK beats both.
  assert.equal(askFromCast({ command: "copilot -p write the docs" }, {}), "write the docs");
  assert.equal(askFromCast({ command: LEAKY }, { ask: "a short ask" }), "a short ask");
  assert.equal(
    askFromCast({ command: LEAKY, marks: [{ label: "ask", text: " from the mark " }] }, {}),
    "from the mark");
  // Precedence: an explicit --ask, then the ask mark, then the -p prompt, then the program name.
  assert.equal(
    askFromCast({ command: "copilot -p from the prompt", marks: [{ label: "ask", text: "from the mark" }] },
      { ask: "from the flag" }),
    "from the flag");
  assert.equal(
    askFromCast({ command: "copilot -p from the prompt", marks: [{ label: "ask", text: "from the mark" }] }, {}),
    "from the mark");
  // But ONLY that mark. Falling back to "any mark with text" published whatever the next step
  // carried - a paste step's payload is a whole review bundle, in the largest type in the clip.
  assert.equal(
    askFromCast({
      command: "copilot --disable-mcp-server kusto",
      marks: [{ label: "ask", text: "" }, { label: "paste", text: "host.internal review bundle" }],
    }, {}),
    "copilot");
});

test("the command tokenizer keeps quoted values whole (DEMO-SAFE-37)", () => {
  // Both label and prompt extraction read tokens, so the quoting rules are load-bearing for two
  // separate leak guards and are worth pinning on their own.
  assert.deepEqual(tokenizeCommand('copilot --note "a b" -p x'), [
    { value: "copilot", quoted: false, closed: true },
    { value: "--note", quoted: false, closed: true },
    { value: "a b", quoted: true, closed: true },
    { value: "-p", quoted: false, closed: true },
    { value: "x", quoted: false, closed: true },
  ]);
  // A token that merely CONTAINS a quoted section is not itself a quoted value, which is what lets
  // `-p="x y"` still be recognised as the flag while `"value -p hidden"` is not.
  assert.deepEqual(tokenizeCommand('-p="x y"'), [{ value: "-p=x y", quoted: false, closed: true }]);
  // An escaped quote stays in the value instead of closing it early.
  assert.deepEqual(tokenizeCommand('"say \\"hi\\" now"'),
    [{ value: 'say "hi" now', quoted: true, closed: true }]);
  // A backslash escapes a quote OR another backslash, so a value ending in a separator round-trips
  // instead of turning its own closing quote into an escaped one.
  assert.deepEqual(tokenizeCommand('"C:\\\\Contoso Secret Project\\\\bin\\\\" --banner'), [
    { value: "C:\\Contoso Secret Project\\bin\\", quoted: true, closed: true },
    { value: "--banner", quoted: false, closed: true },
  ]);
  // An unterminated quote is reported, so callers can refuse to trust it.
  assert.deepEqual(tokenizeCommand('"never closed'),
    [{ value: "never closed", quoted: true, closed: false }]);
  assert.deepEqual(tokenizeCommand(""), []);
  assert.deepEqual(tokenizeCommand(null), []);
  // An empty quoted argument is a real, distinct token.
  assert.deepEqual(tokenizeCommand('copilot ""'), [
    { value: "copilot", quoted: false, closed: true },
    { value: "", quoted: true, closed: true },
  ]);
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

    // A cast that carries argv is labelled from argv, not from the flattened string - so the
    // exact-program path is actually wired into the pages and is not dead code.
    const fromArgv = build({
      cols: 80,
      rows: 24,
      command: "C:\\Users\\demo\\Contoso Secret Project\\bin\\copilot --disable-mcp-server kusto",
      argv: ["C:\\Users\\demo\\Contoso Secret Project\\bin\\copilot", "--disable-mcp-server", "kusto"],
    }, {});
    assert.ok(fromArgv.includes('"copilot"'), `${name} page did not label from argv`);
    assert.ok(!fromArgv.includes("Contoso"), `${name} page published a path fragment`);
    assert.ok(!fromArgv.includes("disable-mcp-server"), `${name} page published the flags`);
  }
});
