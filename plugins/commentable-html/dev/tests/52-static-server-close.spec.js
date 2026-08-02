import { test, expect } from "@playwright/test";
import net from "net";
import fs from "fs";
import os from "os";
import path from "path";
import { startStaticServer } from "./helpers.js";

// CMH-BUILD-14: the shared startStaticServer test helper must close DETERMINISTICALLY. Node's
// server.close() resolves only once every connection has ended, and a browser holds HTTP
// keep-alive (and speculative preconnect) sockets open after loading a document and its companion
// assets. A bare server.close() waits for such an idle socket to drain and can hang indefinitely,
// stalling a spec's `finally { await server.close() }` teardown until the whole test times out
// (issue #677, the Export Offline nonshareable region-guard spec). The helper must destroy open
// connections so close() always resolves promptly. This test pins that: it opens a raw TCP socket
// that connects but sends no request (the case that hangs a bare close), then asserts close()
// resolves quickly rather than waiting on that socket.
test("startStaticServer close resolves promptly with an idle client socket open, not hanging teardown (CMH-BUILD-14)", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_srvclose_"));
  fs.writeFileSync(path.join(dir, "index.html"), "<!doctype html><title>x</title>");
  const server = await startStaticServer(dir);
  let sock = null;
  let closed = null;
  try {
    // Connect to the server's own advertised host (mirrors how the browser dials it), open but send
    // no HTTP request - the case that keeps a bare server.close() waiting.
    const url = new URL(server.url);
    sock = net.connect(Number(url.port), url.hostname);
    await new Promise((resolve, reject) => { sock.once("connect", resolve); sock.once("error", reject); });
    // Yield so the server has run its 'connection' handler and is tracking the socket before we
    // close, so a bare close() genuinely has an open connection to wait on (a real red, not a race).
    await new Promise((r) => setTimeout(r, 50));
    closed = server.close();
    let hungTimer;
    const outcome = await Promise.race([
      closed.then(() => "resolved"),
      new Promise((r) => { hungTimer = setTimeout(() => r("hung"), 3000); }),
    ]);
    clearTimeout(hungTimer);
    expect(outcome, "server.close() must resolve promptly, not hang on an idle client socket").toBe("resolved");
  } finally {
    // Destroy the lingering socket so a bare (unfixed) close() can still settle, then make sure the
    // server is fully torn down and the temp dir is removed regardless of how the test ended.
    if (sock) sock.destroy();
    await (closed || server.close()).catch(() => {});
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
