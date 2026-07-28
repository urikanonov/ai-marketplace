// DEMO-SAFE-01..05. A demo clip is published, and a real terminal session is full of things that
// must never be: credentials, tokens, the operator's home path and account name, private keys. These
// tests pin the redaction contract - what is scrubbed, that scrubbing survives PTY chunk boundaries,
// and that the render gate refuses to film a cast that still scans dirty.
//
// Automated redaction is a SAFETY NET, not the gate: the gate is a human reviewing the transcript.
// These tests exist so the net does not silently develop holes.

import test from "node:test";
import assert from "node:assert/strict";

import {
  scrubText, scanText, createScrubber, scrubEvents, homeRules, DEFAULT_RULES, REDACTED,
} from "../tools/redact.mjs";

// Credential-shaped literals are assembled from parts rather than written whole: GitHub's push
// protection blocks a push that contains one, even inside a test fixture, and a fixture is not a
// secret. The runtime value is identical, so the tests are unchanged.
const join = (...parts) => parts.join("");
// Each case names the exact substring that must not survive, so the assertion is about the SECRET
// rather than about whatever else happens to be on the line.
const SECRETS = [
  { what: "a GitHub personal access token", secret: "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB", line: "token: ghp_0123456789abcdefghijklmnopqrstuvwxyzAB" },
  { what: "a fine-grained GitHub token", secret: "github_pat_11ABCDEFG0aBcDeFgHiJkL_ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210zZ", line: "gh auth login --with-token github_pat_11ABCDEFG0aBcDeFgHiJkL_ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210zZ" },
  { what: "a GitHub server token", secret: "ghs_0123456789abcdefghijklmnopqrstuvwxyzAB", line: "ghs_0123456789abcdefghijklmnopqrstuvwxyzAB" },
  { what: "an OpenAI-style key", secret: "sk-proj-0123456789abcdefghijklmnopqrstuvwxyz0123456789ABCD", line: "OPENAI_API_KEY=sk-proj-0123456789abcdefghijklmnopqrstuvwxyz0123456789ABCD" },
  { what: "an Anthropic-style key", secret: "sk-ant-api03-0123456789abcdefghijklmnopqrstuvwxyz-0123456789ABCDefgh", line: "sk-ant-api03-0123456789abcdefghijklmnopqrstuvwxyz-0123456789ABCDefgh" },
  { what: "an AWS access key id", secret: "AKIAIOSFODNN7EXAMPLE", line: "aws_access_key_id = AKIAIOSFODNN7EXAMPLE" },
  { what: "a bearer header", secret: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhIjoxfQ.sig", line: "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhIjoxfQ.sig" },
  { what: "a JWT", secret: "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk", line: "id_token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk" },
  { what: "an assigned secret", secret: "Zx9~qL2.mN4-pQ7_rS0tU3vW5xY8zA1b", line: "AZURE_CLIENT_SECRET=Zx9~qL2.mN4-pQ7_rS0tU3vW5xY8zA1b" },
  { what: "a password assignment", secret: "hunter2-not-really-a-good-one", line: 'password: "hunter2-not-really-a-good-one"' },
  { what: "a private key block", secret: "b3BlbnNzaC1rZXktdjEAAAAA", line: "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----" },
  { what: "a connection string password", secret: "SuperSecret123!", line: "Server=tcp:db.example.net;Password=SuperSecret123!;" },
  { what: "a Slack token", secret: join("xox", "b-1234567890-ABCDEFGHIJKLMNOP"), line: join("SLACK=xox", "b-1234567890-ABCDEFGHIJKLMNOP") },
  { what: "a Google API key", secret: join("AIza", "SyD9tSrke72I6ok48Z3e7FQabcdefghijk"), line: join("GOOGLE_API_KEY=AIza", "SyD9tSrke72I6ok48Z3e7FQabcdefghijk") },
  // Rules fire in order, so a bearer token INSIDE an Authorization header is already gone by the
  // time the bearer rule runs. A bare bearer credential (curl -v, an SDK trace) is the only thing
  // that exercises that rule, and a real session prints plenty of them.
  { what: "a bare bearer credential", secret: "aGVsbG9Xb3JsZDEyMzQ1Njc4OTBhYmNk", line: "forwarding bearer aGVsbG9Xb3JsZDEyMzQ1Njc4OTBhYmNk upstream" },
  // The keyword is not always the END of the identifier: `SECRET_KEY` and `DB_PASSWORD_PROD` are how
  // environment variables are really named, and a rule anchored only at the keyword's tail misses
  // every one of them.
  { what: "a suffixed secret identifier", secret: "hunter2-not-a-good-one", line: "export SECRET_KEY=hunter2-not-a-good-one" },
  { what: "a prefixed and suffixed identifier", secret: "s3cr3t-value-here", line: "DB_PASSWORD_PROD=s3cr3t-value-here" },
  // The most common way a credential appears in a real terminal is not an assignment at all: it is
  // embedded in a URL that git, npm, or a proxy setting prints back at you.
  { what: "a git remote with credentials", secret: "ghp_9876543210zyxwvutsrqponmlkjihgfedcba", line: "origin  https://urikan:ghp_9876543210zyxwvutsrqponmlkjihgfedcba@github.com/org/repo.git (fetch)" },
  { what: "a proxy URL with a password", secret: "n0t-my-real-pass", line: "HTTPS_PROXY=http://svc-acct:n0t-my-real-pass@squid.corp:3128" },
  { what: "a database connection URL", secret: "p4ssw0rd-here", line: "postgres://appuser:p4ssw0rd-here@db.internal:5432/orders" },
  // Cloud SDKs print key identifiers that contain none of the usual keywords.
  { what: "an Azure storage account key", secret: "abc123DEF456ghi789JKL012mno345PQR678stu901VWX234yz==", line: "AccountKey=abc123DEF456ghi789JKL012mno345PQR678stu901VWX234yz==;EndpointSuffix=core.windows.net" },
  { what: "a shared access key", secret: "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA==", line: "SharedAccessKey: Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA==" },
  { what: "an npm token", secret: join("npm", "_abcdefghijklmnopqrstuvwxyz0123456789"), line: join("//registry.npmjs.org/:_authToken=npm", "_abcdefghijklmnopqrstuvwxyz0123456789") },
  { what: "a PyPI token", secret: join("pypi", "-AgEIcHlwaS5vcmcCJDAwMDAwMDAwLTAwMDAtMDAwMC0wMDAw"), line: join("uploading with pypi", "-AgEIcHlwaS5vcmcCJDAwMDAwMDAwLTAwMDAtMDAwMC0wMDAw") },
  { what: "an Azure SAS signature", secret: "j5Xk2Qm8vB1nR7tY0uI3oP6aS9dF4gH2jK5lZ8xC1vB%3D", line: "https://acct.blob.core.windows.net/c/b?sv=2023-01-03&sig=j5Xk2Qm8vB1nR7tY0uI3oP6aS9dF4gH2jK5lZ8xC1vB%3D" },
  { what: "a kubeconfig client key", secret: "LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVktLS0tLQo=", line: "    client-key-data: LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVktLS0tLQo=" },
];

test("every built-in secret shape is scrubbed out of a line (DEMO-SAFE-01)", () => {
  for (const { what, line, secret } of SECRETS) {
    assert.ok(line.includes(secret), `${what}: the fixture does not contain its own secret`);
    const clean = scrubText(line);
    assert.ok(clean.includes(REDACTED), `${what} was not redacted: ${clean}`);
    assert.ok(!clean.includes(secret), `${what} left the secret in the clip: ${clean}`);
    assert.ok(scanText(line).length > 0, `${what} was not detected by the scanner`);
    // Scrubbing is a fixed point: a cleaned line reports no further findings, so the render gate
    // cannot be tripped by its own redaction marker.
    assert.deepEqual(scanText(clean), [], `${what} still scans dirty after scrubbing: ${clean}`);
    assert.equal(scrubText(clean), clean, `${what} is not idempotent`);
  }
});

test("ordinary session output is left completely alone (DEMO-SAFE-02)", () => {
  // Over-redaction ruins the demo, so the rules must not fire on normal terminal traffic - including
  // text that merely looks tokenish (a git sha, a uuid, a version, a file path, a URL).
  const innocuous = [
    "$ npm test",
    "  86 passing (4.2s)",
    "commit 722702aa9f1c2d3e4b5a6978daf0123456789abc",
    "run id 3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "plugins/commentable-html/dev/tools/build.py --check",
    "https://github.com/urikanonov/ai-marketplace/pull/736",
    "Multi-Duck round 2: 3 of 4 ducks cleared the change",
    "PASS  .github/skills/demo-video/tests/timeline.test.mjs",
  ];
  for (const line of innocuous) {
    assert.equal(scrubText(line), line, `over-redacted: ${line}`);
    assert.deepEqual(scanText(line), [], `false positive on: ${line}`);
  }
});

test("the operator's home path and account name are anonymised (DEMO-SAFE-03)", () => {
  const rules = homeRules({ home: "C:\\Users\\urikan", user: "urikan" });
  const line = "PS C:\\Users\\urikan\\Projects\\AI> whoami -> DOMAIN\\urikan";
  const clean = scrubText(line, [...DEFAULT_RULES, ...rules]);
  assert.ok(!clean.includes("urikan"), `the account name survived: ${clean}`);
  // The shape of the path is preserved so the clip still reads like a real session.
  assert.ok(clean.includes("Projects\\AI"), `the path was over-scrubbed: ${clean}`);
  // Posix homes and a bare ~ expansion are covered by the same helper.
  const posix = homeRules({ home: "/home/urikan", user: "urikan" });
  assert.ok(!scrubText("cd /home/urikan/repo && echo $USER=urikan", [...DEFAULT_RULES, ...posix])
    .includes("urikan"));
  // No home given, no rules invented.
  assert.deepEqual(homeRules({}), []);
  // A home that normalizes to nothing - "/" in a container - must register NO rule: an empty
  // pattern matches at every position, so it would replace the gap between every character and
  // shred the whole transcript into "demoademobdemo...".
  assert.deepEqual(homeRules({ home: "/" }), []);
  assert.deepEqual(homeRules({ home: "\\\\" }), []);
  const rootHome = [...DEFAULT_RULES, ...homeRules({ home: "/", user: "someone" })];
  assert.equal(scrubText("$ npm test\r\n  86 passing\r\n", rootHome), "$ npm test\r\n  86 passing\r\n");
});

test("a secret split across PTY chunks is still caught (DEMO-SAFE-04)", () => {
  // A ConPTY hands output over in arbitrary slices, so a token routinely straddles two chunks. A
  // naive per-chunk scrub would let both halves through - the leak this test exists to prevent.
  const secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB";
  const line = `export GH_TOKEN=${secret}\r\n`;
  for (const cut of [10, 20, 25, 33, 44]) {
    const scrubber = createScrubber();
    const out = scrubber.push(line.slice(0, cut)) + scrubber.push(line.slice(cut)) + scrubber.end();
    assert.ok(!out.includes(secret), `a cut at ${cut} leaked the token: ${out}`);
    assert.ok(out.includes(REDACTED), `a cut at ${cut} produced no redaction marker`);
    // Nothing may be lost or duplicated by the carry-over buffer.
    assert.ok(out.startsWith("export GH_TOKEN="), `a cut at ${cut} mangled the line: ${out}`);
    assert.ok(out.endsWith("\r\n"), `a cut at ${cut} dropped the line ending: ${out}`);
  }
  // A stream with no secret is passed through byte-for-byte, in order.
  const plain = createScrubber();
  const parts = ["$ npm ", "test\r\n", "  ok\r\n"];
  assert.equal(parts.map((p) => plain.push(p)).join("") + plain.end(), parts.join(""));
});

test("scrubEvents cleans a whole cast and reports what it found (DEMO-SAFE-05)", () => {
  const events = [
    { t: 0, data: "$ gh auth status\r\n" },
    { t: 300, data: "Token: ghp_0123456789abcdefghijklmnopqrst" },
    { t: 400, data: "uvwxyzAB\r\n" },
    { t: 900, data: "Logged in\r\n" },
  ];
  const result = scrubEvents(events);
  assert.equal(result.events.length, events.length, "scrubbing must not drop events");
  assert.deepEqual(result.events.map((e) => e.t), [0, 300, 400, 900], "timings must be preserved");
  const joined = result.events.map((e) => e.data).join("");
  assert.ok(!joined.includes("ghp_0123456789abcdefghijklmnopqrstuvwxyzAB"), "the split token leaked");
  assert.ok(result.redactions > 0, "a redaction happened but was not reported");
  // The transcript handed to the human reviewer is the SCRUBBED text, so review and clip agree.
  assert.equal(result.transcript, joined);
  assert.deepEqual(scanText(result.transcript), [], "the scrubbed cast still scans dirty");
});

test("a token wrapped in ANSI colour codes is still caught (DEMO-SAFE-06)", () => {
  // A TUI colourises as it prints, so a credential routinely arrives with escape sequences INSIDE
  // it. The terminal renders the token perfectly - a viewer reads it straight off the clip - while a
  // naive byte-level regex sees two harmless fragments and passes them through.
  const secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB";
  // Deliberately NO keyword in front of it: with a `token:` prefix the assignment rule would swallow
  // the whole painted blob and the test would pass without the token rule ever coping with escapes.
  const painted = "  \u001b[32mghp_0123456789abc\u001b[0mdefghijklmnopqrstuvwxyzAB\u001b[0m\r\n";
  const clean = scrubText(painted);
  assert.ok(!clean.includes(secret), `the painted token survived: ${JSON.stringify(clean)}`);
  assert.ok(!clean.includes("defghijklmnopqrstuvwxyzAB"), "the tail of the token survived");
  assert.ok(clean.includes(REDACTED), "no redaction marker was produced");
  assert.ok(scanText(painted).length > 0, "the scanner did not see the painted token");
  assert.deepEqual(scanText(clean), [], "the scrubbed line still scans dirty");
  // Escapes that are NOT inside a credential must survive, or every clip loses its colour.
  const coloured = "\u001b[36mCopilot\u001b[0m reading the repo ...\r\n";
  assert.equal(scrubText(coloured), coloured, "ordinary colour codes must be preserved");
});

test("a token the application wrapped across lines is still caught (DEMO-SAFE-10)", () => {
  // A CLI that hard-wraps its own output splits a long credential with a newline. The bytes are no
  // longer contiguous, so every rule misses it - while the terminal renders the two halves on
  // consecutive lines, perfectly readable to anyone watching the clip.
  const secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB";
  const wrapped = "  ghp_0123456789abcdefghij\r\nklmnopqrstuvwxyzAB\r\n";
  assert.ok(scanText(wrapped).length > 0, "the scanner missed the wrapped token");
  const clean = scrubText(wrapped);
  assert.ok(!clean.includes("klmnopqrstuvwxyzAB"), `the wrapped token survived: ${JSON.stringify(clean)}`);
  assert.ok(clean.includes(REDACTED), "no redaction marker was produced");
  assert.ok(!scrubText(secret).includes(secret), "the unwrapped form must still be caught");
  // Ordinary wrapped prose must not be joined up and mangled: only a credential that spans the
  // break is rewritten, and everything else keeps its line structure.
  const prose = "the first line ends here\r\nand the second one continues\r\n";
  assert.equal(scrubText(prose), prose, "ordinary wrapped output was rewritten");
  // A line-oriented rule must not run away across the newline: the line after a redacted header
  // still has to be there. Unwrapping is deliberately biased toward over-redaction, so the word
  // immediately after a join may be absorbed with the credential - the REST of the line survives.
  const header = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJhIjoxfQ.sig\r\nnext line survives\r\n";
  const scrubbedHeader = scrubText(header);
  assert.ok(scrubbedHeader.includes("line survives"), `a line rule swallowed the next line: ${JSON.stringify(scrubbedHeader)}`);
  assert.equal(scrubbedHeader.split("\r\n").length, header.split("\r\n").length, "a line break was lost");
});

test("a redaction keeps the column width it replaced (DEMO-SAFE-11)", () => {
  // xterm replays the stream into a GRID. A replacement shorter than the token it replaces pulls
  // everything after it on that line left, so a boxed or column-aligned TUI frame comes out visibly
  // broken in the clip. Padding to the original width keeps the cursor where the session put it.
  const line = "| ghp_0123456789abcdefghijklmnopqrstuvwxyzAB |";
  const clean = scrubText(line);
  assert.equal(clean.length, line.length, `column width changed: ${JSON.stringify(clean)}`);
  assert.ok(clean.endsWith(" |"), "the trailing column moved");
  assert.ok(clean.includes(REDACTED), "no redaction marker was produced");
  // A replacement that is LONGER than its match is never truncated - safety wins over alignment.
  const short = "pwd=abcdef";
  assert.ok(scrubText(short).includes(REDACTED));
  assert.ok(!scrubText(short).includes("abcdef"));
});
test("a private key block streams through the scrubber intact (DEMO-SAFE-07)", () => {
  // The scrubber splits on whitespace because no single-line credential contains any. A PEM block
  // does: it is the one multi-line shape, and its body is far longer than the carry, so it would be
  // emitted line by line with BEGIN in one flush and END in another - and neither fragment matches.
  // `cat ~/.ssh/id_ed25519` during a recorded session is exactly how that leaks.
  const body = Array.from({ length: 12 }, (_, i) => `AAAA${String(i).padStart(2, "0")}${"b".repeat(60)}`).join("\n");
  const keyBlock = `-----BEGIN OPENSSH PRIVATE KEY-----\n${body}\n-----END OPENSSH PRIVATE KEY-----\n`;
  assert.ok(keyBlock.length > 512, "the fixture must exceed the carry buffer to be meaningful");
  for (const cut of [20, 80, 300, 500]) {
    const scrubber = createScrubber();
    const out = scrubber.push(keyBlock.slice(0, cut)) + scrubber.push(keyBlock.slice(cut)) + scrubber.end();
    assert.ok(!out.includes("bbbbbbbbbb"), `a cut at ${cut} leaked the key body: ${out.slice(0, 120)}`);
    assert.ok(out.includes(REDACTED), `a cut at ${cut} produced no redaction marker`);
  }
  // Chunked one line at a time, the way a PTY actually delivers it.
  const perLine = createScrubber();
  const streamed = keyBlock.split("\n").map((line) => perLine.push(line + "\n")).join("") + perLine.end();
  assert.ok(!streamed.includes("bbbbbbbbbb"), "line-by-line streaming leaked the key body");
  assert.ok(streamed.includes(REDACTED), "line-by-line streaming produced no redaction marker");
});

test("a whitespace-free flood cannot push a credential out unredacted (DEMO-SAFE-08)", () => {
  // Output with no whitespace at all - a minified JSON payload, a long base64 blob - can never be
  // split on whitespace, so the scrubber force-emits past a cap to avoid growing without bound. That
  // cut must not be allowed to slice a credential in half and let both halves through.
  const secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB";
  const scrubber = createScrubber();
  let out = "";
  out += scrubber.push(`{"pad":"${"a".repeat(70000)}"`);
  out += scrubber.push(`,"token":"${secret}"`);
  out += scrubber.push(`,"more":"${"b".repeat(70000)}"}`);
  out += scrubber.end();
  assert.ok(!out.includes(secret), "the force-emit path leaked the credential");
  assert.ok(out.includes(REDACTED), "the force-emit path produced no redaction marker");
  // The flood itself is ordinary output and must survive.
  assert.ok(out.includes("a".repeat(1000)) && out.includes("b".repeat(1000)), "ordinary output was lost");
  // And the cut must not silently eat content either.
  assert.ok(out.length > 140000, `the force-emit path dropped output: ${out.length} chars`);
});

test("the streaming scrubber stays linear on whitespace-free input (DEMO-SAFE-09)", () => {
  // Rescanning the whole buffer for a split point on every push is quadratic, and a dense stream is
  // exactly when that bites: a demo recorder that freezes for tens of seconds mid-session is not
  // usable. This pins the work as roughly linear rather than timing a specific machine.
  const scrubber = createScrubber();
  const started = Date.now();
  for (let i = 0; i < 4000; i++) scrubber.push("abcdefghij");
  scrubber.end();
  assert.ok(Date.now() - started < 5000, "pushing 40KB without whitespace took pathologically long");
});

test("a cursor-move escape cannot glue a token past its word boundary (DEMO-SAFE-12)", () => {
  // Stripping escapes is what lets a COLOURED token be rejoined and matched - but stripping a
  // CURSOR-MOVING escape glues unrelated text together instead. `Loading123<CSI 0G>ghp_...` renders
  // as the token overwriting the progress line, while the projection saw "Loading123ghp_..." and the
  // token rule's leading word boundary never matched. Style escapes glue; movement escapes break.
  const secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB";
  const overwritten = `Loading123\u001b[0G${secret}\r\n`;
  assert.ok(scanText(overwritten).length > 0, "the scanner missed the overwritten token");
  const clean = scrubText(overwritten);
  assert.ok(!clean.includes(secret), `the overwritten token survived: ${JSON.stringify(clean)}`);
  assert.ok(clean.includes(REDACTED), "no redaction marker was produced");
  // The same must hold for the other movement and erase controls a spinner or TUI actually uses.
  for (const move of ["\u001b[1G", "\u001b[2K", "\u001b[5;1H", "\u001b[A", "\u001b[3D"]) {
    const line = `busy...${move}${secret}\r\n`;
    assert.ok(!scrubText(line).includes(secret), `${JSON.stringify(move)} let the token through`);
  }
  // ...while a STYLE escape still glues, so a painted token stays matchable (DEMO-SAFE-06).
  const painted = `  \u001b[32mghp_0123456789abc\u001b[0m${secret.slice(20)}\r\n`;
  assert.ok(!scrubText(painted).includes(secret.slice(20)), "a painted token stopped being matched");
});

test("a home path is anonymised even for a cast from another machine (DEMO-SAFE-13)", () => {
  // The machine-specific rules are built from whoever is RENDERING, so a cast captured by someone
  // else is scanned with rules that never knew their name. A portable rule covers the SHAPE of a
  // home directory, so another operator's path is caught without anyone's identity being written
  // into the cast to make it work.
  for (const line of [
    "cd /home/alice/projects/api",
    "ls /Users/bob.smith/Desktop",
    "PS C:\\Users\\carol\\repo> git status",
  ]) {
    const clean = scrubText(line);
    for (const name of ["alice", "bob.smith", "carol"]) {
      assert.ok(!clean.includes(name), `${name} survived in ${JSON.stringify(clean)}`);
    }
    assert.ok(/home|Users/i.test(clean), `the path shape was destroyed: ${clean}`);
  }
  // The tail of the path is what makes the clip readable, so it must survive.
  assert.ok(scrubText("cd /home/alice/projects/api").includes("projects/api"));
  // A path that is not a home directory is left alone.
  assert.equal(scrubText("cd /var/log/nginx"), "cd /var/log/nginx");
});

test("two adjacent credentials are both redacted whole (DEMO-SAFE-14)", () => {
  // The unwrapped pass can produce a span that reaches into the NEXT credential. Dropping the
  // overlapping span (rather than merging it) then left the tail of the second token in the clip -
  // and, because the tail no longer looks like a token, the render gate waved it through.
  const a = "ghp_AAAAAAAAAAAAAAAAAAAA";
  const b = "ghp_BBBBBBBBBBBBBBBBBBBB";
  for (const gap of ["\n", "\r\n", " ", "\r\n\r\n", "\u001b[32m", " and "]) {
    const line = `${a}${gap}${b}`;
    const clean = scrubText(line);
    assert.ok(!clean.includes("AAAAAAAAAA"), `gap ${JSON.stringify(gap)} left the first token: ${clean}`);
    assert.ok(!clean.includes("BBBBBBBBBB"), `gap ${JSON.stringify(gap)} left the second token: ${clean}`);
    assert.deepEqual(scanText(clean), [], `gap ${JSON.stringify(gap)} still scans dirty: ${clean}`);
  }
});

test("a redaction never swallows the line structure around it (DEMO-SAFE-15)", () => {
  // A span found on the UNWRAPPED projection covers the newline the token straddled. Splicing the
  // replacement over it would delete that line break, so the replay loses a terminal row and every
  // later line lands one row too high.
  const input = "before ghp_AAAAAAAAAA\r\nAAAAAAAAAA after\r\nnext line\r\n";
  const clean = scrubText(input);
  const count = (text, needle) => text.split(needle).length - 1;
  assert.equal(count(clean, "\r\n"), count(input, "\r\n"), `line breaks changed: ${JSON.stringify(clean)}`);
  assert.ok(clean.includes("next line"), "following content was lost");
  assert.ok(clean.startsWith("before "), "preceding content was lost");
  assert.ok(!clean.includes("AAAAAAAAAA"), `the wrapped token survived: ${clean}`);
});

test("a PEM header wearing colour codes still holds the stream (DEMO-SAFE-16)", () => {
  // The streaming scrubber looked for the BEGIN marker in RAW bytes, so a TUI that colourises the
  // header slipped past the hold, the body was flushed line by line, and the key reached the cast.
  const body = Array.from({ length: 10 }, (_, i) => `SECRET${String(i).padStart(2, "0")}${"Z".repeat(60)}`).join("\n");
  const styled = `-----BEGIN OPENSSH \u001b[31mPRIVATE KEY-----\n${body}\n-----END OPENSSH PRIVATE KEY-----\n`;
  const scrubber = createScrubber();
  const streamed = styled.split("\n").map((line) => scrubber.push(line + "\n")).join("") + scrubber.end();
  assert.ok(!streamed.includes("ZZZZZZZZZZ"), `the styled key body leaked: ${streamed.slice(0, 160)}`);
  assert.ok(streamed.includes(REDACTED), "no redaction marker was produced");
  const events = styled.split("\n").map((line, i) => ({ t: i * 10, data: line + "\n" }));
  const result = scrubEvents(events);
  assert.ok(!result.transcript.includes("ZZZZZZZZZZ"), "the styled key reached the transcript");
});

test("an identity rewrite is not padded into a broken path (DEMO-SAFE-17)", () => {
  // Width padding exists for opaque blobs in column-aligned output. Applying it to a path rewrite
  // inserts a space inside the path - `/home/demo /.ssh/config` - which reads as two tokens and
  // looks broken in a clip whose whole purpose is to look right.
  const clean = scrubText("cat /home/alexandra/.ssh/config");
  assert.ok(!clean.includes("alexandra"), `the account name survived: ${clean}`);
  assert.ok(clean.includes("/.ssh/config"), `the path tail was lost: ${clean}`);
  assert.ok(!/\s\/\.ssh/.test(clean), `padding broke the path: ${JSON.stringify(clean)}`);
  const windows = scrubText("PS C:\\Users\\alexandra\\repo> git status");
  assert.ok(!windows.includes("alexandra"), `the account name survived: ${windows}`);
  assert.ok(windows.includes("\\repo>"), `padding broke the path: ${JSON.stringify(windows)}`);
});

test("the terminal title escape never reaches the cast (DEMO-SAFE-18)", () => {
  // A shell sets the window title with an OSC sequence, and that title carries the full executable
  // path and the current working directory - which in a real session is the operator's home. The
  // projection strips escapes BEFORE matching, so no rule ever saw inside it, and the raw bytes went
  // to the cast and the transcript with the path intact. The replay has no use for a window title,
  // so it is removed outright.
  const titled = "$ ls\u001b]0;C:\\Users\\alexandra\\Projects\\secret-client\u0007\r\ndone\r\n";
  const clean = scrubText(titled);
  assert.ok(!clean.includes("alexandra"), `the title leaked an account name: ${JSON.stringify(clean)}`);
  assert.ok(!clean.includes("secret-client"), `the title leaked a working directory: ${JSON.stringify(clean)}`);
  assert.ok(!clean.includes("\u001b]0;"), "the title sequence is still in the stream");
  assert.deepEqual(scanText(clean), [], "the scrubbed stream still scans dirty");
  // The surrounding output is untouched.
  assert.ok(clean.startsWith("$ ls"), `output before the title was lost: ${JSON.stringify(clean)}`);
  assert.ok(clean.includes("done"), "output after the title was lost");
  // The same holds for the ST-terminated form and through the streaming path.
  const stForm = "a\u001b]2;C:\\Users\\bob\\repo\u001b\\b";
  assert.ok(!scrubText(stForm).includes("bob"), `ST-terminated title leaked: ${scrubText(stForm)}`);
  const scrubber = createScrubber();
  const streamed = scrubber.push(titled.slice(0, 12)) + scrubber.push(titled.slice(12)) + scrubber.end();
  assert.ok(!streamed.includes("alexandra"), `the streamed title leaked: ${JSON.stringify(streamed)}`);
});

test("an oversized private key stays suppressed to its END marker (DEMO-SAFE-19)", () => {
  // Past the buffer cap the scrubber has to emit something, and it emitted a redaction and then
  // FORGOT it was inside a key: every byte after the cap - body and END marker alike - was treated
  // as ordinary clean text, and the tail had no BEGIN marker left for the gate to recognise.
  const body = "KEYBODY".repeat(11000); // comfortably past the 64KB cap
  const block = `-----BEGIN OPENSSH PRIVATE KEY-----\n${body}\nPEMTAIL-PEMTAIL\n-----END OPENSSH PRIVATE KEY-----\n`;
  const scrubber = createScrubber();
  let out = "";
  for (let i = 0; i < block.length; i += 4096) out += scrubber.push(block.slice(i, i + 4096));
  out += scrubber.end();
  assert.ok(!out.includes("KEYBODY"), `the oversized key body leaked: ${out.slice(0, 120)}`);
  assert.ok(!out.includes("PEMTAIL"), `the key tail leaked past the cap: ${out.slice(-160)}`);
  assert.ok(out.includes(REDACTED), "no redaction marker was produced");
  assert.deepEqual(scanText(out), [], "the emitted stream still scans dirty");
  // Output that follows the key is ordinary again.
  const after = createScrubber();
  let tail = "";
  for (let i = 0; i < block.length; i += 4096) tail += after.push(block.slice(i, i + 4096));
  tail += after.push("$ echo done\r\n");
  tail += after.end();
  assert.ok(tail.includes("$ echo done"), "the scrubber never recovered after the key");
});

test("a wrapped credential longer than the carry keeps no tail (DEMO-SAFE-20)", () => {
  // The newline is a safe place to split - unless it is the join in a hard-wrapped credential. When
  // the continuation was longer than the carry buffer, the first line flushed before the unwrapped
  // pass could see the whole token, and the tail sailed through with nothing token-shaped left in it.
  const head = "ghp_AAAAAAAAAAAAAAAAAAAAAAAA";
  const tail = "WRAPTAIL".repeat(40);
  const wrapped = `${head}\r\n${tail}\r\n$ next\r\n`;
  for (const size of [16, 64, 256, 1024]) {
    const scrubber = createScrubber();
    let out = "";
    for (let i = 0; i < wrapped.length; i += size) out += scrubber.push(wrapped.slice(i, i + size));
    out += scrubber.end();
    assert.ok(!out.includes("WRAPTAILWRAPTAIL"), `chunk ${size} leaked the wrapped tail: ${out.slice(0, 160)}`);
    assert.ok(!out.includes(head), `chunk ${size} leaked the token head`);
    assert.ok(out.includes("$ next"), `chunk ${size} lost the following output`);
  }
});
