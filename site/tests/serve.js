const http = require("http");
const fs = require("fs");
const path = require("path");

// Minimal static file server for the built site/dist/ folder, used only by the
// Playwright suite. No dependencies so the test install stays tiny.
const ROOT = path.resolve(__dirname, "..", "dist");
const PORT = 4173;
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  // Without this the clips are served as application/octet-stream: Chromium sniffs and plays them
  // anyway, but that diverges from Pages and is exactly what makes Firefox refuse a local preview.
  ".webm": "video/webm",
  ".ico": "image/x-icon",
  ".zip": "application/zip",
};

const server = http.createServer((req, res) => {
  const urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
  let filePath = path.join(ROOT, urlPath);
  if (filePath !== ROOT && !filePath.startsWith(ROOT + path.sep)) {
    res.writeHead(403);
    res.end("forbidden");
    return;
  }
  let stat;
  try {
    stat = fs.statSync(filePath);
  } catch (e) {
    res.writeHead(404);
    res.end("not found");
    return;
  }
  if (stat.isDirectory()) {
    filePath = path.join(filePath, "index.html");
    if (!fs.existsSync(filePath)) {
      res.writeHead(404);
      res.end("not found");
      return;
    }
    // Re-stat: the size below must be the index file's, not the directory's.
    stat = fs.statSync(filePath);
  }
  const ext = path.extname(filePath).toLowerCase();
  const type = TYPES[ext] || "application/octet-stream";
  // Byte ranges matter for the demo clips: a browser seeks by asking for a range, so a server
  // that only ever returns 200 with the whole file makes the scrub bar unusable. GitHub Pages
  // serves ranges, so without this the local preview and the suite would disagree with production.
  const total = stat.size;
  const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || "");
  if (range) {
    const startRaw = range[1];
    const endRaw = range[2];
    let start;
    let end;
    if (startRaw === "") {
      // A suffix range ("bytes=-500") asks for the LAST n bytes.
      const suffix = Number(endRaw);
      if (!endRaw || Number.isNaN(suffix)) {
        res.writeHead(416, { "Content-Range": "bytes */" + total });
        res.end();
        return;
      }
      start = Math.max(0, total - suffix);
      end = total - 1;
    } else {
      start = Number(startRaw);
      end = endRaw === "" ? total - 1 : Number(endRaw);
    }
    if (Number.isNaN(start) || Number.isNaN(end) || start > end || start >= total) {
      res.writeHead(416, { "Content-Range": "bytes */" + total });
      res.end();
      return;
    }
    end = Math.min(end, total - 1);
    res.writeHead(206, {
      "Content-Type": type,
      "Accept-Ranges": "bytes",
      "Content-Range": "bytes " + start + "-" + end + "/" + total,
      "Content-Length": end - start + 1,
    });
    fs.createReadStream(filePath, { start: start, end: end }).pipe(res);
    return;
  }
  res.writeHead(200, { "Content-Type": type, "Accept-Ranges": "bytes", "Content-Length": total });
  fs.createReadStream(filePath).pipe(res);
});

server.listen(PORT, "127.0.0.1", () => {
  console.log("serving " + ROOT + " at http://127.0.0.1:" + PORT + "/");
});
