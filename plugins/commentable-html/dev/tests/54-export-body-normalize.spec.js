import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  ready, fileUrl, openInline, stageContent, stageNonPortable, startStaticServer, readDownload, openToolbarMenu,
} from "./helpers.js";

// CMH-EXP-09: transient runtime body-state classes (toggled on document.body by the
// layer at runtime) must never be baked into a saved/exported file. A persisted
// "sidebar-open" makes the exported document render full width with an empty sidebar
// gutter (the body.sidebar-open .app layout rule) for a sidebar that is not shown.
const TRANSIENT = ["sidebar-open", "cm-sidebar-resizing", "cm-widget-dragging"];
const BODY_WITH_TRANSIENT =
  '<body class="sidebar-open cm-sidebar-resizing cm-widget-dragging cmh-keep-me">';

function bodyOpenTag(html) {
  const m = html.match(/<body\b[^>]*>/i);
  if (!m) throw new Error("no <body> open tag in exported HTML");
  return m[0];
}

function assertBodyNormalized(html) {
  const body = bodyOpenTag(html);
  for (const cls of TRANSIENT) {
    expect(body, `exported <body> must not carry transient class ${cls}`).not.toContain(cls);
  }
  // A non-transient class on <body> is preserved (only the transient state is stripped).
  expect(body, "a non-transient body class must survive export").toContain("cmh-keep-me");
}

// Bake the transient classes into the on-disk <body> to simulate a stale/open-sidebar
// source. Over http this is what _getBaseHtml() fetches; over file:// it is what the
// load-time snapshot captures. Both must be normalized on export. The shipped template
// now ships a plain <body> (the transient state is never baked in), so replace whatever
// the <body> open tag is with the transient-laden one.
function bakeTransientBody(html) {
  const out = html.replace(/<body\b[^>]*>/i, BODY_WITH_TRANSIENT);
  if (out === html || !out.includes("cmh-keep-me")) {
    throw new Error("fixture setup: could not bake transient body classes");
  }
  return out;
}

const CONTENT =
  '<section><p id="p">Transient body state must never be persisted into an export.</p></section>';

async function stageInlineServer() {
  const staged = stageContent(CONTENT, {
    key: "cmh-export-body-normalize",
    source: "export-body-normalize.html",
  });
  fs.writeFileSync(staged.html, bakeTransientBody(fs.readFileSync(staged.html, "utf8")));
  const server = await startStaticServer(staged.dir);
  return { staged, server };
}

test.describe("Export strips transient body state (CMH-EXP-09)", () => {
  test("Save/Portable export drops sidebar-open and other transient body classes (CMH-EXP-09)", async ({ page }) => {
    const { staged, server } = await stageInlineServer();
    try {
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnSaveHtmlTop").click(),
      ]);
      assertBodyNormalized(await readDownload(download));
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Offline export drops sidebar-open and other transient body classes (CMH-EXP-09)", async ({ page }) => {
    const { staged, server } = await stageInlineServer();
    try {
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnExportOfflineTop").click(),
      ]);
      assertBodyNormalized(await readDownload(download));
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Plain export drops sidebar-open and other transient body classes (CMH-EXP-09)", async ({ page }) => {
    const { staged, server } = await stageInlineServer();
    try {
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnSavePlainTop").click(),
      ]);
      assertBodyNormalized(await readDownload(download));
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  // NonPortable Portable export over file:// exercises the _snapshotWithTail() fallback
  // base (fetch is blocked) and the _buildStandaloneHtml() inlining path.
  test("Portable export from a nonportable file (snapshot fallback) drops transient body classes (CMH-EXP-09)", async ({ page }) => {
    const staged = stageNonPortable({ mutate: bakeTransientBody });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnSaveHtmlTop").click(),
      ]);
      assertBodyNormalized(await readDownload(download));
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });
});

// Unit tests for the pure body-class normalizer (exposed as window.__cmhStripTransientBody).
// These pin the robustness fixes: only the FIRST <body> open tag is touched, all three quote
// styles are handled, whole tokens are matched (no \b over-strip), and an emptied class attr
// is removed.
test.describe("Body-class normalizer unit (CMH-EXP-09)", () => {
  async function strip(page, html) {
    return page.evaluate((h) => window.__cmhStripTransientBody(h), html);
  }

  test("single-quoted transient class is stripped to the kept classes (CMH-EXP-09)", async ({ page }) => {
    await openInline(page);
    expect(await strip(page, "<body class='sidebar-open keep'>")).toBe("<body class='keep'>");
  });

  test("a <body class> literal after the real body (in a script) is not mutated (CMH-EXP-09)", async ({ page }) => {
    await openInline(page);
    const input = '<body>\n<script>var x=\'<body class="sidebar-open other">\';</script>';
    expect(await strip(page, input)).toBe(input);
  });

  test("a superstring host class like x-sidebar-open is preserved (CMH-EXP-09)", async ({ page }) => {
    await openInline(page);
    expect(await strip(page, '<body class="x-sidebar-open keep">')).toBe('<body class="x-sidebar-open keep">');
  });

  test("the existing double-quoted case still strips only the transient token (CMH-EXP-09)", async ({ page }) => {
    await openInline(page);
    expect(await strip(page, '<body class="sidebar-open app">')).toBe('<body class="app">');
  });

  test("an emptied class attribute is removed and unquoted values are handled (CMH-EXP-09)", async ({ page }) => {
    await openInline(page);
    expect(await strip(page, '<body class="sidebar-open">')).toBe("<body>");
    expect(await strip(page, "<body class=sidebar-open>")).toBe("<body>");
  });
});
