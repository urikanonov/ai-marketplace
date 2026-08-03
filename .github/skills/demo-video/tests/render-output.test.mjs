import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import {
  windowLabel,
  promptFromCommand,
  tokenizeCommand,
  joinCommand,
  askFromCast,
  castText,
  publishedSurfaces,
  gateFindings,
  findingCount,
  dirtyGateMessage,
  terminalPage,
  stagePage,
} from "../tools/record_demo.mjs";
import { scanText } from "../tools/redact.mjs";

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
      // That a SAFE label survives is DEMO-SAFE-38's business now: the chrome draws nothing by
      // default, so for a command carrying a prompt the label appears nowhere on the page. What
      // this row pins is the leak - no flags, no operator path, in either page.
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

// What the chrome may say and what it DOES say are separate questions. `scripts/check_clip_chrome.py`
// fails a published clip whose terminal title strip is not FLAT, because flatness is the one property
// that cannot be argued with - it is deliberately not a text recogniser. So a safe label is still text,
// and a clip rendered with one has to be masked by hand before it can ship. That mask is the fragile
// step that already published ten leaking frames when it stopped 0.44s early (#815). Render the chrome
// empty instead, so a freshly recorded clip is born flat and a re-record needs no manual patching.
function chromeTitleOf(html) {
  const m = /getElementById\("title"\)\.textContent = (.*);/.exec(html);
  assert.ok(m, "the page no longer sets the chrome title at all");
  return JSON.parse(m[1]);
}

// The phase caption is an overlay pinned to the top of the loop clip, and it used to start ABOVE
// the bottom of the window chrome - so its rounded top edge and border crossed the title strip.
// That reads as "the title bar is not empty" to `scripts/check_clip_chrome.py`, which fails a clip
// whose terminal title strip is not flat, and it looked wrong too: the pill sat across the traffic
// lights. Derive both numbers from the page's own CSS so this cannot drift back.
function cssPx(css, rule, prop) {
  const block = new RegExp(`${rule}\\s*\\{([^}]*)\\}`).exec(css);
  assert.ok(block, `no ${rule} rule in the stage page`);
  const value = new RegExp(`(?:^|[;\\s])${prop}:\\s*(-?[\\d.]+)px`).exec(block[1]);
  assert.ok(value, `${rule} has no ${prop}`);
  return Number(value[1]);
}

test("the phase caption never overlaps the window chrome (DEMO-SAFE-39)", () => {
  const css = buildStagePage({ cols: 80, rows: 24, command: LEAKY }, {});
  // The chrome block: the wrap's top padding, the traffic lights, and the gap under them.
  const chromeBottom = cssPx(css, "\\.wrap", "padding")
    + cssPx(css, "\\.dot", "height")
    + cssPx(css, "\\.chrome", "padding-bottom");
  // The SHADOW counts, not just the box, and its reach is the RENDERER's, not the CSS length. A
  // blur radius is a Gaussian parameter, not a hard painted edge: Chromium maps it to a sigma of
  // half the radius and Skia allocates the mask out to about three sigma, so the shadow can put ink
  // roughly 1.5 blur radii beyond its own box. The naive `blur - offset` reading of the same
  // declaration claimed 26px where the renderer can reach 46px, and it happened to pass by ONE
  // pixel - a wrong model with no slack, which is how the first cut of this fix cleared the border
  // and left the shadow bleeding into the strip with the gate still failing.
  // Parsed strictly: a `spread` 4th length, or a second comma-separated layer, would each add reach
  // the naive two-capture form silently ignored, so an unexpected shape fails here rather than in a
  // published clip.
  const declaration = /#phase\s*\{[^}]*?box-shadow:\s*([^;}]+)/.exec(css);
  assert.ok(declaration, "#phase has no box-shadow to account for");
  // Split on TOP-LEVEL commas only - a colour like `rgba(0,0,0,.5)` carries its own.
  const layers = declaration[1].replace(/\([^)]*\)/g, "()").split(",");
  assert.equal(layers.length, 1,
    `#phase has ${layers.length} shadow layers; this test only reasons about one`);
  const lengths = layers[0].match(/-?[\d.]+(?:px)?/g) || [];
  assert.equal(lengths.length, 3,
    `#phase box-shadow has ${lengths.length} lengths, expected offset-x, offset-y and blur`);
  const [, offsetY, blur] = lengths.map((v) => Number(v.replace("px", "")));
  const reach = (blur * 1.5) - offsetY;
  const top = cssPx(css, "#phase", "top");
  // A margin, not a touch. Clearing by a single pixel meant any one-pixel change to the chrome's
  // padding or dot size would push the loop clip's flatness back toward the noise ceiling with this
  // test still green - the same zero-slack trap the tolerance itself was in.
  assert.ok(top - reach >= chromeBottom + 4,
    `the phase caption reaches ${top - reach}px, too close to the chrome that ends at ${chromeBottom}px`);
});

test("the window chrome carries no text unless the operator opts in (DEMO-SAFE-38)", () => {
  for (const [name, build] of [["terminal", buildTerminalPage], ["stage", buildStagePage]]) {
    for (const cast of [
      { cols: 80, rows: 24, command: LEAKY },
      { cols: 80, rows: 24, command: "copilot --banner" },
      {
        cols: 80,
        rows: 24,
        command: "C:\\Users\\demo\\Contoso Secret Project\\bin\\copilot --disable-mcp-server kusto",
        argv: ["C:\\Users\\demo\\Contoso Secret Project\\bin\\copilot", "--disable-mcp-server", "kusto"],
      },
    ]) {
      assert.equal(chromeTitleOf(build(cast, {})), "",
        `${name} page drew text in the chrome, so the clip cannot pass the flatness gate`);
    }
    // Opting in still shows the whole command, so the flag is not silently dead.
    assert.equal(
      chromeTitleOf(build({ cols: 80, rows: 24, command: LEAKY }, { "show-command": true })),
      LEAKY,
      `${name} page ignored --show-command`,
    );
    // A cast can carry an EMPTY argv (a foreign or truncated one). `[]` is truthy in JS, so a bare
    // `argv || command` picks it and the usable command is silently dropped - the opted-in chrome
    // then reads "session" and the operator is told nothing about why.
    assert.equal(
      chromeTitleOf(build({ cols: 80, rows: 24, argv: [], command: "copilot --banner" }, { "show-command": true })),
      "copilot --banner",
      `${name} page let an empty argv shadow the command`,
    );
  }
});

// Every scan gate reads `castText`, and what it does NOT read cannot be caught. The title card is
// the largest type in the clip and `askFromCast` fills it from a cast MARK, so a foreign, legacy or
// hand-edited cast whose mark text carries the launch command (or a host, a home path, a token)
// sails through `scan`/`render`/`loop` and is published in the opening frames. The marks were
// outside the scan the whole time; it only became load-bearing now that the chrome draws nothing,
// which makes the card the primary text surface.
test("the credential scan reads the text the title card will publish (DEMO-SAFE-40)", () => {
  const cast = {
    cols: 80,
    rows: 24,
    command: "copilot",
    argv: ["copilot"],
    events: [],
    marks: [{ label: "ask", text: `please review ${LEAKY}` }],
  };
  const scanned = castText(cast);
  assert.ok(scanned.includes("disable-mcp-server"),
    "the scan does not read mark text, so it cannot catch a leak the title card will publish");
  // And what the card actually renders is that same text, so the two cannot drift apart.
  assert.ok(askFromCast(cast, {}).includes("disable-mcp-server"),
    "the title card no longer renders the ask mark; re-point this test at whatever it renders");
});

// `--ask` never touches the cast, so scanning the cast alone left the operator-supplied string -
// painted at up to 30px, the largest type in the clip - completely unchecked. It is the documented
// render recipe, and it matters more now the chrome draws nothing and the card leads the clip.
test("the render gate scans an operator-supplied --ask too (DEMO-SAFE-41)", () => {
  const clean = { cols: 80, rows: 24, command: "copilot", argv: ["copilot"], events: [], marks: [] };
  const surfaces = (args) => Object.values(publishedSurfaces(clean, args)).join("\n");
  assert.ok(!surfaces({}).includes("disable-mcp-server"),
    "a clean cast should not read dirty");
  assert.ok(surfaces({ ask: `please review ${LEAKY}` }).includes("disable-mcp-server"),
    "--ask reaches the title card unscanned");
});

// A refusal that cannot be reproduced or acted on is worse than none: the operator is told the
// publication is unsafe and every remedy offered applies to the surface that is clean. The two
// surfaces are fixed by OPPOSITE actions, so the gate has to know which one fired.
const TOKEN = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB";

test("the safety gate tells the cast and the ask apart (DEMO-SAFE-42)", () => {
  const clean = { cols: 80, rows: 24, command: "npm test", argv: ["npm", "test"], events: [], marks: [] };
  const onlyAsk = gateFindings(clean, { ask: `review ${TOKEN}` });
  assert.deepEqual(onlyAsk.cast, [], "a clean cast was reported dirty");
  assert.ok(onlyAsk.ask.length, "the operator-supplied ask was not scanned");

  const dirtyCast = { ...clean, events: [{ t: 0, data: `gh auth login --with-token ${TOKEN}\r\n` }] };
  const onlyCast = gateFindings(dirtyCast, {});
  assert.ok(onlyCast.cast.length, "the cast scan stopped catching its own stream");
  assert.deepEqual(onlyCast.ask, [], "a cast finding was blamed on an ask the operator never passed");

  // An ask the tool derives from the cast (a mark, or a `-p` prompt) IS cast text, so it stays the
  // cast's finding - blaming an ask nobody typed would be the same dead end in the other direction.
  const dirtyMark = { ...clean, marks: [{ label: "ask", text: `review ${TOKEN}` }] };
  const fromMark = gateFindings(dirtyMark, {});
  assert.ok(fromMark.cast.length, "mark text left the cast scan");
  assert.deepEqual(fromMark.ask, [], "a mark-derived ask was reported as operator-supplied");
});

// Splitting one scan into two must not drop what only the JOIN caught: `scanText` rejoins a
// hard-wrapped value across a line break, so a credential whose halves sit at the end of the cast
// and the start of the ask matched when the two were one string and matches in neither alone. Both
// halves are published, and together they read as one credential.
test("a credential split across the cast and the ask is still caught (DEMO-SAFE-42)", () => {
  const cast = {
    cols: 80,
    rows: 24,
    command: "npm test",
    argv: ["npm", "test"],
    marks: [],
    events: [{ t: 0, data: "run this: ghp_0123456789" }],
  };
  const found = gateFindings(cast, { ask: "abcdefghijklmnopqrstuvwxyzAB now" });
  assert.deepEqual(found.cast, [], "half a token should not match on its own");
  assert.deepEqual(found.ask, [], "the other half should not match on its own");
  assert.ok(found.boundary.length, "a credential spanning the two surfaces was let through");
  // The clip is marked UNSAFE from this count, so a bucket left out of it is a clip that ships
  // looking clean.
  assert.equal(findingCount(found), found.boundary.length);

  const message = dirtyGateMessage(found, "probe.cast.json");
  assert.match(message, /span/i, "the refusal does not say the finding spans both surfaces");
  assert.match(message, /--ask/);

  // The same split with a DERIVED ask: both halves come from the cast, so the remedy is the cast's
  // and the refusal must not tell the operator to retype a flag they never passed.
  const derived = {
    ...cast,
    marks: [{ label: "ask", text: "abcdefghijklmnopqrstuvwxyzAB now" }],
    events: [{ t: 0, data: "trailing half: ghp_0123456789" }],
  };
  const fromCast = gateFindings(derived, {});
  assert.ok(fromCast.boundary.length, "a derived split was let through");
  assert.doesNotMatch(dirtyGateMessage(fromCast, "probe.cast.json"), /retype the --ask/,
    "the refusal prescribes retyping a flag the operator never passed");
});

// A DERIVED ask is not a copy of cast text - it is REBUILT from it. `promptFromCommand` drops the
// quotes around a `-p` value, so a command that scans clean on disk renders a contiguous credential
// on the title card. The old single scan caught that because it scanned the resolved ask; a split
// that skipped the derived half would publish it.
test("the title card is scanned even when nobody passed --ask (DEMO-SAFE-42)", () => {
  const cast = {
    cols: 80,
    rows: 24,
    command: `copilot -p ghp_"${TOKEN.slice(4)}"`,
    events: [],
    marks: [],
  };
  assert.deepEqual(scanText(castText(cast)), [], "the quoted command should read clean as cast text");
  assert.ok(askFromCast(cast, {}).includes(TOKEN), "the card no longer rebuilds the prompt");

  const found = gateFindings(cast, {});
  assert.ok(found.card.length, "the rebuilt title card was published unscanned");
  assert.deepEqual(found.ask, [], "a card finding was blamed on an --ask nobody passed");

  const message = dirtyGateMessage(found, "probe.cast.json");
  assert.match(message, /title card/i, "the refusal does not name the title card");
  assert.match(message, /re-capture or add a rule/i, "the refusal withholds the remedy that works");
  assert.doesNotMatch(message, /--ask you passed/, "the refusal blames a flag the operator never used");

  // A card REBUILT from the cast is kept whole rather than deduped by rule: a cast that already
  // leaks one token must not hide a SECOND, different one that only the card renders.
  const other = `ghp_${"9".repeat(36)}`;
  const two = {
    ...cast,
    command: `copilot -p ghp_"${TOKEN.slice(4)}"`,
    events: [{ t: 0, data: `earlier: ${other}\r\n` }],
  };
  const bothTokens = gateFindings(two, {});
  assert.ok(bothTokens.cast.length, "the cast's own token stopped matching");
  assert.ok(bothTokens.card.length, "a second credential of the same rule was deduped away");

  // A card the tool merely COPIES out of the cast (a mark) reports once, not twice.
  const copied = gateFindings({ ...cast, command: "npm test", marks: [{ label: "ask", text: `review ${TOKEN}` }] }, {});
  assert.ok(copied.cast.length, "mark text left the cast scan");
  assert.deepEqual(copied.card, [], "a card copied verbatim from the cast was counted twice");
});

// Findings are indexed into the OSC-stripped text the rules ran over. A cast carrying a shell title
// or a hyperlink - which modern shells emit by default, so every imported recording has them - is
// shorter there than on disk, and an offset measured on disk files an ordinary ask finding as a
// boundary one, handing back the re-capture instruction this gate exists to stop giving.
test("an OSC sequence in the cast does not misfile an ask finding (DEMO-SAFE-42)", () => {
  const cast = {
    cols: 80,
    rows: 24,
    command: "npm test",
    argv: ["npm", "test"],
    marks: [],
    events: [{ t: 0, data: "\u001b]0;a long window title set by the shell\u0007ok\r\n" }],
  };
  const found = gateFindings(cast, { ask: `review ${TOKEN}` });
  assert.equal(found.ask.length, 1, "the ask finding was lost");
  assert.deepEqual(found.boundary, [], "an ordinary ask finding was filed as a boundary finding");
  assert.equal(findingCount(found), 1, "the same finding was counted twice");

  // An UNTERMINATED escape (a capture cut at the size limit ends mid-sequence) must not let the
  // ask supply the terminator it is missing: joined, that sequence would swallow the ask and the
  // one credential would be reported twice, with the boundary paragraph's re-capture prescribed
  // for a string the operator typed.
  const dangling = { ...cast, events: [{ t: 0, data: "ok\r\n\u001b]0;unterminated title" }] };
  const straddled = gateFindings(dangling, { ask: `\u0007 review ${TOKEN}` });
  assert.equal(straddled.ask.length, 1, "the ask finding was lost");
  assert.deepEqual(straddled.boundary, [], "a dangling escape turned one finding into two");
  assert.equal(findingCount(straddled), 1);
});

test("the reproduce command survives a path with spaces (DEMO-SAFE-42)", () => {
  const clean = { cols: 80, rows: 24, command: "npm test", argv: ["npm", "test"], events: [], marks: [] };
  const found = gateFindings(clean, { ask: `review ${TOKEN}` });
  const spaced = "/tmp/demo video/probe.cast.json";
  assert.match(dirtyGateMessage(found, spaced), /"\/tmp\/demo video\/probe\.cast\.json"/,
    "the advertised command splits the path into two arguments");

  // Quoting rules differ between shells, so a path that cannot be quoted the same way everywhere
  // is advertised as a placeholder rather than as a command that would break where it is pasted.
  const quoted = dirtyGateMessage(found, '/tmp/od"d/probe.cast.json');
  assert.match(quoted, /<file>/, "an unquotable path was pasted into the command anyway");
  assert.doesNotMatch(quoted, /od"d/);
});

test("a dirty ask is refused in its own words (DEMO-SAFE-42)", () => {
  const clean = { cols: 80, rows: 24, command: "npm test", argv: ["npm", "test"], events: [], marks: [] };
  const askOnly = dirtyGateMessage(gateFindings(clean, { ask: `review ${TOKEN}` }), "probe.cast.json");
  assert.match(askOnly, /--ask/, "the refusal does not name the ask");
  assert.doesNotMatch(askOnly, /this cast still scans dirty/i, "the refusal blames the clean cast");
  assert.doesNotMatch(askOnly, /Re-capture or add a rule/, "the refusal prescribes a useless re-capture");
  // The one command that CAN reproduce it, named with the file the operator actually passed.
  assert.match(askOnly, /probe\.cast\.json/);

  const dirtyCast = { ...clean, events: [{ t: 0, data: `gh auth login --with-token ${TOKEN}\r\n` }] };
  const castOnly = dirtyGateMessage(gateFindings(dirtyCast, {}), "probe.cast.json");
  assert.match(castOnly, /this cast still scans dirty/i);
  assert.match(castOnly, /Re-capture or add a rule/);
  assert.doesNotMatch(castOnly, /--ask/, "a clean ask was blamed for the cast's finding");

  // Both dirty: each surface is named, so neither remedy is guessed at.
  const both = dirtyGateMessage(gateFindings(dirtyCast, { ask: `review ${TOKEN}` }), "probe.cast.json");
  assert.match(both, /this cast still scans dirty/i);
  assert.match(both, /--ask/);
});

// `--show-command` reads as a chrome control - that is how SKILL.md introduced it, and since the
// chrome draws nothing by default an operator reaching for it is thinking about a title bar. But
// `askFromCast`'s last fallback is `windowLabel(...)`, which the flag turns into the RAW command,
// so for a cast with no ask mark and no `-p` prompt the flag paints the whole invocation across the
// title card at up to 30px - the largest type in the clip. The reach is intended (the flag is an
// explicit opt-in to publishing the command) but it was undocumented, so both halves are pinned:
// the behavior, and the sentence in SKILL.md that warns about it.
test("--show-command reaches the title card, not just the chrome (DEMO-SAFE-43)", () => {
  const bare = { command: LEAKY };
  assert.equal(askFromCast(bare, {}), "copilot",
    "the safe fallback stopped applying without the flag");
  // Both spellings: parseArgs produces the dashed one, a direct caller uses the camelCase alias.
  assert.equal(askFromCast(bare, { "show-command": true }), LEAKY);
  assert.equal(askFromCast(bare, { showCommand: true }), LEAKY);
  // Only the FALLBACK is affected. A cast that has something to state still states it, so opting in
  // never overwrites a real ask with the invocation.
  assert.equal(
    askFromCast({ command: LEAKY, marks: [{ label: "ask", text: "review the panel" }] },
      { "show-command": true }),
    "review the panel");
  assert.equal(
    askFromCast({ command: 'copilot -p "review this" --disable-mcp-server kusto' }, { "show-command": true }),
    "review this");
  assert.equal(askFromCast(bare, { "show-command": true, ask: "a short ask" }), "a short ask");

  // The doc half. A flag introduced purely as chrome control hides its loudest effect, so the
  // SENTENCE that introduces it must name the title card - a mention elsewhere in the paragraph is
  // what the operator already had, and it read as a note about the chrome fallback.
  const skill = fs.readFileSync(path.join(import.meta.dirname, "..", "SKILL.md"), "utf8");
  const sentences = skill.replace(/\s+/g, " ").split(/(?<=[.!?])\s+/)
    .filter((s) => s.includes("--show-command"));
  assert.ok(sentences.length, "SKILL.md no longer mentions --show-command at all");
  assert.ok(
    sentences.some((s) => /title card/i.test(s)),
    "SKILL.md introduces --show-command without saying it also arms the title card");
});
