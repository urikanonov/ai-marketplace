// Link comment layer (CMH-LINK): render-time new-tab stamping for author-facing
// references, plus per-link commenting anchored by (linkIndex) + href/text.
import { test, expect } from "@playwright/test";
import {
  ready, fileUrl, stageContent, copiedBundle, installClipboardCapture, clickSidebarExport,
} from "./helpers.js";
import fs from "fs";
import os from "os";
import path from "path";

const KEY = "cmh-link-test";
const CONTENT = `
<h2 id="links-lead">Links</h2>
<p id="lead">See the <a id="ext" href="https://example.com/docs">Example docs</a> and the
<a id="rel" href="/guide/setup">setup guide</a> for details. Jump to
<a id="frag" href="#section-2">section 2</a> in-page.
<span class="cm-skip"><a id="skip" href="https://skip.example/x">skip me</a></span>
<a id="self" href="https://example.com/self" target="_self">already targeted</a>
<a id="js" href="javascript:void(0)">run</a>
<a id="mail" href="mailto:x@example.com">email</a>
<a id="blank" href="https://example.com/pre" target="_blank">pre blank</a>
<a id="caps" href="https://example.com/caps" target="_BLANK">case variant</a>
<a id="nav" href="nav-target.html">local nav</a>
<a id="proto" href="//example.com/p">proto rel</a>
<a id="upper" href="HTTPS://example.com/u">upper scheme</a>
<a id="tel" href="tel:+15551234">call</a>
<a id="data" href="data:text/html,x" target="_blank">data blank</a></p>
<h2 id="section-2">Section 2</h2>
<p id="vt-rel-lead"><a id="vtrel" href="https://example.com/vt" target="_blank" rel="noopener&#x0b;x noreferrer&#x0b;y">vt rel</a></p>`;

async function stage(page, { init } = {}) {
  const { dir, html } = stageContent(CONTENT, { key: KEY });
  // A real local sibling file so the #nav link's new-tab click resolves to a loadable
  // file:// URL (hermetic - no network) for the CMH-LINK-03 navigation proof.
  fs.writeFileSync(path.join(dir, "nav-target.html"), "<!doctype html><title>nav target</title><p>nav target</p>");
  if (init) await page.addInitScript(init);
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
  return html;
}

// Links whose EFFECTIVE target a browser resolves from something other than the anchor's own
// attribute. All are NON-commentable (a fragment, a mailto:), because the runtime hands every
// commentable document reference an explicit target="_blank" of its own - so only these can show
// whether the stamper reads the raw attribute or the target a browser actually resolves. The SVG
// anchor is here for the opposite reason: HTML's "get an element's target" is defined for an HTML
// anchor, so a foreign one must inherit NOTHING.
const BASE_CONTENT = `
<h2 id="base-lead">Base target</h2>
<p id="base-p"><a id="binherit" href="#base-section">inherits</a>
<a id="bmail" href="mailto:x@example.com">email</a>
<a id="bself" href="#base-section" target="_self">explicit self</a>
<a id="bcoerce" href="#base-section" target="x&#10;&lt;">coerced to blank</a>
<a id="bname" href="#base-section" target="x&lt;">plain name</a></p>
<svg id="bsvg" width="10" height="10"><a id="bsvga" href="#base-section"><title>svg link</title></a></svg>
<h2 id="base-section">Base section</h2>`;

// Hrefs whose ENDS carry padding the two candidate readings disagree about, so a test can measure
// which trim the classifier uses. The first group pads with a character JS `.trim()` REMOVES but the
// URL parser KEEPS (so a browser resolves each to a DIFFERENT document than the bare `#fragment` it
// resembles); the second pads with one the parser removes and JS keeps, or with one both remove, so
// each really is the same-page fragment it looks like. Every link authors `target="_self"`, which is
// exactly the harm CMH-LINK-01 exists to prevent on a document reference and exactly what a real
// same-page fragment is entitled to keep. `#cctl` additionally authors the marks an OLDER runtime
// stamped on it (it classified a C0-padded fragment as a document reference), which this one must
// clear - see the stale-mark test below.
//
// The padding is written as a JS `\uXXXX` escape, NOT an HTML numeric character reference: HTML maps
// a reference in the 0x80-0x9F range to its Windows-1252 equivalent, so `&#x85;` would have staged
// U+2026 (an ellipsis) and quietly tested a character other than the U+0085 it names. PAD_CODE below
// pins what actually reached the DOM.
const PADS = {
  pnbsp: 0x00a0, pls: 0x2028, pps: 0x2029, pideo: 0x3000, pbom: 0xfeff, pnel: 0x0085,
  ponly: 0x00a0, ctab: 0x0009, cvt: 0x000b, cspace: 0x0020, cctl: 0x0001, cctlonly: 0x0001,
};
const pad = (id) => String.fromCharCode(PADS[id]);
const PADDED_CONTENT = `
<h2 id="padded-lead">Padded hrefs</h2>
<p id="padded-p">
<a id="pnbsp" href="${pad("pnbsp")}#padded-section" target="_self">nbsp</a>
<a id="pls" href="${pad("pls")}#padded-section" target="_self">line separator</a>
<a id="pps" href="${pad("pps")}#padded-section" target="_self">paragraph separator</a>
<a id="pideo" href="${pad("pideo")}#padded-section" target="_self">ideographic space</a>
<a id="pbom" href="${pad("pbom")}#padded-section" target="_self">zero width no-break space</a>
<a id="pnel" href="${pad("pnel")}#padded-section" target="_self">next line</a>
<a id="ponly" href="${pad("ponly")}" target="_self">nbsp only</a>
<a id="ctab" href="${pad("ctab")}#padded-section" target="_self">tab</a>
<a id="cvt" href="${pad("cvt")}#padded-section" target="_self">vertical tab</a>
<a id="cspace" href="${pad("cspace")}#padded-section" target="_self">space</a>
<a id="cctl" href="${pad("cctl")}#padded-section" target="_self" class="cm-link-commentable" data-cm-link-index="42">c0 control</a>
<a id="cctlonly" href="${pad("cctlonly")}" target="_self">c0 control only</a>
<a id="cfrag" href="#padded-section" target="_self">plain fragment</a>
<a id="cdoc" href="doc-target.html" target="_self">unique document reference</a>
<span class="cm-skip"><a id="pskip" href="#padded-section" target="_self">chrome fragment</a></span>
</p>
<h2 id="padded-section">Padded section</h2>`;

// `head` is raw markup injected into <head>, so a test can give the document a `<base href>`;
// `init` is an init script (seeded storage, as the poisoned-metadata test does).
async function stagePadded(page, head = null, init = null) {
  const { html } = stageContent(PADDED_CONTENT, { key: KEY + "-padded" });
  if (head !== null) {
    const src = fs.readFileSync(html, "utf8");
    const injected = src.replace("<head>", "<head>\n" + head);
    if (injected === src) throw new Error("stagePadded: no <head> to inject into");
    fs.writeFileSync(html, injected);
  }
  if (init) await page.addInitScript(init);
  await page.goto(fileUrl(html));
  await ready(page);
}

// The `<base>` shapes a browser never applies. Shared with the validator's own parked-base test
// (`tests/test_validate_kql.py` - `PARKED_BASES`), pinned to it as TEXT by
// `tests/test_vendored_libs.py` so the two readers can never be checked against different corpora.
const PARKED_BASES = [
  '<template><base target="%s"></template>',
  '<svg><base target="%s"></svg>',
  '<math><base target="%s"></math>',
  '<div><template shadowrootmode="open"><base target="%s"></template></div>',
];

// Stage BASE_CONTENT with (or, for the control, without) `<base target>` markup in the head.
// `head` is raw markup, so a test can park a base a browser never applies before the live one.
async function stageBase(page, head) {
  const { html } = stageContent(BASE_CONTENT, { key: KEY + "-base" });
  if (head !== null) {
    const src = fs.readFileSync(html, "utf8");
    const injected = src.replace("<head>", "<head>\n" + head);
    // A silent no-op replace would turn every negative assertion below green rather than red, so
    // fail loudly the way stageContent does when its CONTENT region is missing.
    if (injected === src) throw new Error("stageBase: no <head> to inject into");
    fs.writeFileSync(html, injected);
  }
  await page.goto(fileUrl(html));
  await ready(page);
}

const relTokens = async (page, id) =>
  ((await page.locator("#" + id).getAttribute("rel")) || "").split(/[\t\n\f\r ]+/).filter(Boolean);

async function hoverLink(page, id) {
  await page.evaluate((sel) => {
    const a = document.querySelector(sel);
    a.scrollIntoView({ block: "center" });
    a.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
  }, "#" + id);
}

async function commentLink(page, id, note) {
  await hoverLink(page, id);
  await expect(page.locator("#linkAddBtn")).toBeVisible();
  await page.locator("#linkAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toBeHidden();
}

test.describe("link handling", () => {
  test("external reference links are stamped to open in a new tab (CMH-LINK-01)", async ({ page }) => {
    await stage(page);
    for (const id of ["ext", "rel"]) {
      const a = page.locator("#" + id);
      await expect(a).toHaveAttribute("target", "_blank");
      const rel = await a.getAttribute("rel");
      expect(rel).toContain("noopener");
      expect(rel).toContain("noreferrer");
    }
  });

  test("the rel stamp reads the authored list the way HTML tokenizes one (CMH-LINK-01)", async ({ page }) => {
    await stage(page);
    // #vtrel is authored `rel="noopener&#x0b;x noreferrer&#x0b;y"`. A JS `\s` split takes the
    // vertical tab, so the stamper used to see BOTH required tokens, rewrite nothing, and leave the
    // attribute exactly as authored; a browser tokenizes a `rel` list on ASCII whitespace ONLY, so
    // it read TWO opaque relations, honored neither, and left `window.opener` exposed to the opened
    // page. Assert on the tokens a BROWSER would read.
    const rel = await page.locator("#vtrel").getAttribute("rel");
    const tokens = rel.split(/[\t\n\f\r ]+/).filter(Boolean);
    expect(tokens, rel).toContain("noopener");
    expect(tokens, rel).toContain("noreferrer");
    // The authored relations themselves survive - the stamp adds, it never rewrites author content.
    expect(tokens, rel).toContain("noopener\u000bx");
    expect(tokens, rel).toContain("noreferrer\u000by");
  });

  test("fragment, cm-skip, javascript, mailto, tel and data links are excluded; only document references are stamped (CMH-LINK-01)", async ({ page }) => {
    await stage(page);
    // Document references (http/https/file, incl. protocol-relative and uppercase scheme) are
    // commentable and stamped to open in a new tab.
    for (const id of ["ext", "rel", "proto", "upper", "nav"]) {
      await expect(page.locator("#" + id), id + " commentable").toHaveClass(/cm-link-commentable/);
      await expect(page.locator("#" + id), id + " target").toHaveAttribute("target", "_blank");
    }
    // Non-document schemes and same-page fragments are neither commentable nor stamped.
    for (const id of ["frag", "skip", "js", "mail", "tel", "data"]) {
      await expect(page.locator("#" + id), id + " not commentable").not.toHaveClass(/cm-link-commentable/);
    }
    for (const id of ["frag", "js", "mail", "tel"]) {
      expect(await page.locator("#" + id).getAttribute("target"), id + " target").toBeNull();
    }
    // Hovering an excluded link never reveals the affordance.
    await page.evaluate(() => document.getElementById("frag")
      .dispatchEvent(new MouseEvent("mouseenter", { bubbles: true })));
    await expect(page.locator("#linkAddBtn")).toBeHidden();
    // An author-set target on a document reference is OVERRIDDEN to _blank (forced to a new
    // tab so the reviewer is never navigated away from the report and their comments).
    expect((await page.locator("#self").getAttribute("target")).toLowerCase()).toBe("_blank");
    const selfRel = await page.locator("#self").getAttribute("rel");
    expect(selfRel).toContain("noopener");
    expect(selfRel).toContain("noreferrer");
  });

  test("an href padded with characters the URL parser keeps is not a same-page fragment (CMH-LINK-01)", async ({ page }) => {
    await stagePadded(page);
    // Pin the character that actually reached the DOM before measuring anything with it: an HTML
    // numeric reference in the 0x80-0x9F range is remapped to Windows-1252, so a test that names
    // U+0085 can silently be exercising U+2026 - and pass, because both are kept by both readings.
    const staged = await page.evaluate(() => {
      const out = {};
      document.querySelectorAll("#padded-p a[href]").forEach((a) => {
        if (a.closest(".cm-skip")) return; // runtime chrome is never classified
        out[a.id] = (a.getAttribute("href") || "").charCodeAt(0);
      });
      return out;
    });
    for (const id of Object.keys(PADS)) {
      expect(staged[id], id + " staged padding code point").toBe(PADS[id]);
    }
    // The browser's own resolution, applied OFF the classifier: `a.href` is the URL a click
    // navigates to, so a link that resolves to a URL other than this document's is not a same-page
    // fragment however much its markup looks like one - and the author's `target="_self"` on it
    // navigates the reviewer's own tab away from the report and their comments. The classifier now
    // asks the same question internally, so this is a cross-check rather than an independent
    // oracle; the real assertions are the `target`, `rel` and `cm-link-commentable` ones below,
    // whose expected values are the hard-coded `away`/`stay` lists.
    const samePage = await page.evaluate(() => {
      const doc = location.href.split("#")[0];
      const out = {};
      document.querySelectorAll("#padded-p a[href]").forEach((a) => {
        if (a.closest(".cm-skip")) return; // runtime chrome is never classified
        out[a.id] = a.href.split("#")[0] === doc;
      });
      return out;
    });
    // Padded with a character the URL parser KEEPS: a different document, so the stamp must apply.
    // JS `.trim()` removes NBSP, U+2028, U+2029, every Zs (U+3000 stands for the category) and
    // U+FEFF, so the classifier read all of these as same-page fragments and stamped none of them.
    // U+0085 is in the list for the opposite reason: JS `.trim()` does NOT take it (it is neither a
    // LineTerminator nor Zs), so it is a non-regression control on the same side of the boundary.
    const away = ["pnbsp", "pls", "pps", "pideo", "pbom", "pnel", "ponly", "cdoc"];
    // Padded with a character the parser REMOVES: really is this document, so the exemption stands.
    // U+0001 is the other direction of the same defect - JS `.trim()` keeps a non-whitespace C0
    // control, so the classifier used to call `href="&#x1;#frag"` a document reference and stamp a
    // fragment navigation - while tab, VT and space are the ASCII controls both readings trim, and
    // must keep behaving exactly as they do today.
    const stay = ["ctab", "cvt", "cspace", "cctl", "cctlonly", "cfrag"];
    // Every staged link is accounted for, so a link added to PADDED_CONTENT cannot be silently
    // skipped by both loops below.
    expect(Object.keys(samePage).sort(), "every staged link is classified")
      .toEqual([...away, ...stay].sort());
    for (const id of away) expect(samePage[id], id + " resolves to another document").toBe(false);
    for (const id of stay) expect(samePage[id], id + " resolves to this document").toBe(true);
    for (const id of away) {
      const a = page.locator("#" + id);
      expect(await a.getAttribute("target"), id + " target").toBe("_blank");
      const rel = await a.getAttribute("rel");
      expect(rel, id + " rel").toContain("noopener");
      expect(rel, id + " rel").toContain("noreferrer");
      // The same predicate gates INDEXING, so an unstamped link was also never commentable.
      await expect(a, id + " commentable").toHaveClass(/cm-link-commentable/);
    }
    for (const id of stay) {
      const a = page.locator("#" + id);
      expect(String(await a.getAttribute("target")).toLowerCase(), id + " target").toBe("_self");
      // The newly-EXEMPT direction (the C0-padded pair) must lose the secure rel along with the
      // target, since a same-tab in-page navigation is what it is entitled to.
      expect(await a.getAttribute("rel"), id + " rel").toBeNull();
      await expect(a, id + " not commentable").not.toHaveClass(/cm-link-commentable/);
    }
  });

  test("a padded link's comment stores the href the classifier read (CMH-LINK-02)", async ({ page }) => {
    await stagePadded(page);
    await commentLink(page, "pnbsp", "note on the padded link");
    await commentLink(page, "ponly", "note on the nbsp-only link");
    // The anchor key must be the href the CLASSIFIER read, padding and all. A JS-trimmed key
    // ("#padded-section") is a string no commentable link's attribute can ever equal, so href
    // healing would be silently dead for exactly the links the parser trim newly admits - and an
    // NBSP-only href would store an EMPTY key, which the healing branch skips entirely.
    const stored = await page.evaluate(() => window.__cmhStorageCodec.read());
    const keys = stored.filter((c) => c.anchorType === "link").map((c) => c.linkHref);
    expect(keys, "stored anchor keys").toContain("\u00a0#padded-section");
    expect(keys, "an NBSP-only href stores a non-empty key").toContain("\u00a0");
  });

  test("a padded link's comment heals by that href when its index is stale (CMH-LINK-02)", async ({ page }) => {
    // The key exists to relocate a comment whose index went stale, so measure that it does. The
    // seeded index resolves to nothing, so only the href can find the link - and the target is
    // deliberately NOT the first commentable link, so a "fell back to linkEls[0]" bug fails here.
    await stagePadded(page, null, () => {
      localStorage.setItem("cmh-link-test-padded", JSON.stringify([{
        id: "cpadheal1", anchorType: "link", linkIndex: 99, linkHref: "\ufeff#padded-section",
        linkText: "bom", quote: "bom", note: "healed by href",
        createdAt: new Date().toISOString(),
      }]));
    });
    await expect(page.locator('a.cm-link-hl[data-cid="cpadheal1"]#pbom')).toHaveCount(1);
    await expect(page.locator('a.cm-link-hl[data-cid="cpadheal1"]')).toHaveCount(1);
  });

  test("a comment stored by an older runtime still finds its own link (CMH-LINK-02)", async ({ page }) => {
    // A pre-1.790.0 record carries a JS-trimmed key. Two things must hold. (1) It must still
    // resolve after its index shifts (the classifier newly admits the padded links before it):
    // an ordinary link's key reads the same under both readings, so the exact search finds it.
    // (2) It must not resolve to the WRONG link: `href="&#x1;#frag"` and `href="&#x9;#frag"` are
    // distinct attributes that the CURRENT reading collapses to the same key, so normalizing the
    // stored side as well would silently move an old `&#x1;` comment onto the `&#x9;` link.
    // Staged under a `<base href>` so both of those links are commentable and the collision is
    // reachable.
    await stagePadded(page, '<base href="elsewhere/">', () => {
      localStorage.setItem("cmh-link-test-padded", JSON.stringify([
        { id: "coldplain1", anchorType: "link", linkIndex: 99, linkHref: "doc-target.html",
          linkText: "unique document reference", quote: "unique", note: "old ordinary key",
          createdAt: new Date().toISOString() },
        { id: "coldctrl1", anchorType: "link", linkIndex: 99, linkHref: "\u0001#padded-section",
          linkText: "c0 control", quote: "c0 control", note: "old c0 key",
          createdAt: new Date().toISOString() },
      ]));
    });
    await expect(page.locator('a.cm-link-hl[data-cid="coldplain1"]#cdoc')).toHaveCount(1);
    await expect(page.locator('a.cm-link-hl[data-cid="coldctrl1"]#cctl')).toHaveCount(1);
    // ...and never on the link whose padding the current reading collapses to the same key.
    await expect(page.locator('a.cm-link-hl[data-cid="coldctrl1"]#ctab')).toHaveCount(0);
  });

  test("marks an older runtime left on a link this one does not index are cleared (CMH-LINK-02)", async ({ page }) => {
    // `#cctl` is authored with the `cm-link-commentable` class and a `data-cm-link-index` an older
    // runtime stamped, the way a saved or exported document carries them. This classifier does not
    // admit that link, and `findLinkEl` falls back to `[data-cm-link-index]`, so leaving the mark in
    // place would resolve an index-only comment onto a link that is not commentable at all.
    await stagePadded(page, null, () => {
      localStorage.setItem("cmh-link-test-padded", JSON.stringify([{
        id: "cstalemark1", anchorType: "link", linkIndex: 42, linkHref: "",
        linkText: "c0 control", quote: "c0 control", note: "index-only comment",
        createdAt: new Date().toISOString(),
      }]));
    });
    const marks = await page.evaluate(() => {
      const a = document.getElementById("cctl");
      return { cls: a.classList.contains("cm-link-commentable"), idx: a.getAttribute("data-cm-link-index") };
    });
    expect(marks.cls, "stale cm-link-commentable class").toBe(false);
    expect(marks.idx, "stale data-cm-link-index").toBeNull();
    // ...and with the mark gone the index-only comment rings no link at all (the sidebar card still
    // lists it, so scope the assertion to the anchor).
    await expect(page.locator('a[data-cid="cstalemark1"]')).toHaveCount(0);
    await expect(page.locator("a.cm-link-hl")).toHaveCount(0);
  });

  test("a <base href> makes an empty or fragment href a cross-document navigation (CMH-LINK-01)", async ({ page }) => {
    // The same-page exemption is about where a click GOES, not what the href looks like. With a
    // `<base href>` pointing elsewhere, a browser resolves BOTH an empty href and a bare `#fragment`
    // against the base, so a click leaves this document - and the author's `target="_self"` would
    // take the reviewer's tab, and their comments, with it. Deciding the exemption on the string
    // alone (as the classifier's early return did) exempts exactly those navigations.
    await stagePadded(page, '<base href="elsewhere/">');
    const samePage = await page.evaluate(() => {
      const doc = location.href.split("#")[0];
      const out = {};
      document.querySelectorAll("#padded-p a[href]").forEach((a) => {
        if (a.closest(".cm-skip")) return; // runtime chrome is never classified
        out[a.id] = a.href.split("#")[0] === doc;
      });
      return out;
    });
    for (const id of Object.keys(samePage)) {
      expect(samePage[id], id + " resolves away from this document under <base href>").toBe(false);
      const a = page.locator("#" + id);
      expect(await a.getAttribute("target"), id + " target").toBe("_blank");
      await expect(a, id + " commentable").toHaveClass(/cm-link-commentable/);
    }
    // Runtime chrome is exempt BEFORE any of this: a `.cm-skip` link is never touched however a
    // browser resolves it, so the new rule cannot start stamping the layer's own navigation.
    expect(await page.locator("#pskip").getAttribute("target"), "pskip target").toBe("_self");
    await expect(page.locator("#pskip")).not.toHaveClass(/cm-link-commentable/);
    // The control: with no `<base href>` the same links stay in the document and keep the
    // exemption, so this is not a blanket "stamp every fragment" rewrite.
    await stagePadded(page);
    for (const id of ["ctab", "cvt", "cspace", "cctl", "cctlonly", "cfrag"]) {
      expect(await page.locator("#" + id).getAttribute("target"), id + " without base").toBe("_self");
    }
    // ...and a `<base href>` that re-points at this very document is a no-op, so it must not move
    // the exemption either (a comparison written on `location.pathname` would pass the test above
    // and fail here). Note `test-doc.html`, the staged file's own name, not `.` - a bare `.` points
    // at the DIRECTORY, which a fragment click really does navigate to.
    await stagePadded(page, '<base href="test-doc.html">');
    expect(await page.locator("#cfrag").getAttribute("target"), "cfrag with a no-op base").toBe("_self");
    await expect(page.locator("#cfrag")).not.toHaveClass(/cm-link-commentable/);
  });

  test("an author-set target=_blank without rel gains the secure rel regardless of scheme (CMH-LINK-01)", async ({ page }) => {
    await stage(page);
    // Commentable http link (#blank), case-variant (#caps), AND a non-commentable data: link
    // (#data) all get rel enforced because their effective target is _blank (reverse-tabnabbing).
    for (const id of ["blank", "caps", "data"]) {
      const a = page.locator("#" + id);
      expect((await a.getAttribute("target")).toLowerCase(), id + " target").toBe("_blank");
      const rel = await a.getAttribute("rel");
      expect(rel, id + " rel").toContain("noopener");
      expect(rel, id + " rel").toContain("noreferrer");
    }
    // The data: link is still NOT commentable (rel enforcement is decoupled from commentability).
    await expect(page.locator("#data")).not.toHaveClass(/cm-link-commentable/);
  });

  test("a link that inherits the document's <base target> is stamped like a targeted one (CMH-LINK-01)", async ({ page }) => {
    // The stamper must read the target a BROWSER resolves, not the raw attribute. An anchor with no
    // `target` of its own inherits the document's first `<base target>`, so in a
    // `<base target="_blank">` document these links open an auxiliary context with a live
    // `window.opener` - and the raw read saw `null` and stamped nothing.
    await stageBase(page, '<base target="_blank">');
    for (const id of ["binherit", "bmail"]) {
      const tokens = await relTokens(page, id);
      expect(tokens, id).toContain("noopener");
      expect(tokens, id).toContain("noreferrer");
    }
    // Proof this really is a new tab, not a theory: clicking the inheriting fragment link opens one.
    const [popup] = await Promise.all([
      page.context().waitForEvent("page"),
      page.locator("#binherit").click(),
    ]);
    await popup.waitForLoadState("domcontentloaded").catch(() => {});
    expect(popup.url()).toContain("#base-section");
    await popup.close();
    // An explicit same-context target on the link WINS over the base, so it stays unstamped.
    expect(await relTokens(page, "bself"), "bself").toEqual([]);
    // A FOREIGN anchor inherits nothing: HTML's "get an element's target" is defined for an HTML
    // anchor, so an SVG one (mermaid emits these for clickable nodes) navigates the CURRENT tab.
    // Stamping it would suppress the Referer on a same-tab navigation.
    expect(await relTokens(page, "bsvga"), "bsvga").toEqual([]);

    // The control: the same document with NO `<base target>` navigates all of these in the current
    // tab, so none of them may gain the rel - the stamp follows the effective target, it is not a
    // blanket rewrite of every non-commentable link.
    await stageBase(page, null);
    for (const id of ["binherit", "bmail", "bself", "bsvga"]) {
      expect(await relTokens(page, id), id).toEqual([]);
    }
  });

  test("a <base target> a browser never applies cannot decide the stamp (CMH-LINK-01)", async ({ page }) => {
    // "The document contains a base element" is the BROWSER's view. A `<base>` parked in an inert
    // `<template>` or a declarative shadow root is not in the document tree, and one written under
    // `<svg>`/`<math>` is a foreign element (`base` is not a foreign breakout tag, so it stays
    // there) - a browser applies neither. A bare CSS type selector matches ANY namespace, so
    // `querySelector("base[target]")` returned the SVG one and an author who wrote a same-context
    // base before the real one (in document order) silently lost the stamp on every link that
    // inherits it.
    for (const shape of PARKED_BASES) {
      const head = shape.replace("%s", "_self") + '<base target="_blank">';
      await stageBase(page, head);
      const tokens = await relTokens(page, "binherit");
      expect(tokens, head).toContain("noopener");
      expect(tokens, head).toContain("noreferrer");
    }
    // ...and on its own such a base inherits NOTHING, so no link may be stamped.
    for (const shape of PARKED_BASES) {
      const head = shape.replace("%s", "_blank");
      await stageBase(page, head);
      expect(await relTokens(page, "binherit"), head).toEqual([]);
    }
    // Only the FIRST live base is inherited, as HTML ignores all but the first.
    await stageBase(page, '<base target="_self"><base target="_blank">');
    expect(await relTokens(page, "binherit"), "first live base wins").toEqual([]);
  });

  test("a padded or case-variant inherited _blank is still stamped (CMH-LINK-01)", async ({ page }) => {
    // The stamper matches the keyword with a JS `.trim().toLowerCase()`, deliberately BROADER than
    // HTML's untrimmed ASCII-case-insensitive match. That is the safe direction and must stay: HTML
    // reads ` _blank ` as a NAME, and a name this document does not declare opens a brand-new
    // auxiliary context with a live `window.opener` - so tightening the match to the letter of the
    // spec would REMOVE a stamp these links need.
    for (const value of [" _blank ", "&#9;_BLANK&#10;", "_BLAN&#x212a;"]) {
      await stageBase(page, '<base target="' + value + '">');
      const tokens = await relTokens(page, "binherit");
      expect(tokens, value).toContain("noopener");
      expect(tokens, value).toContain("noreferrer");
    }
  });

  test("a target HTML coerces to _blank is stamped like the keyword (CMH-LINK-01)", async ({ page }) => {
    // HTML replaces a target name containing BOTH an ASCII tab-or-newline and a U+003C with
    // `_blank`, so `x&#10;<` opens a new tab that a raw string compare against `_blank` misses.
    await stageBase(page, null);
    const coerced = await relTokens(page, "bcoerce");
    expect(coerced, "bcoerce").toContain("noopener");
    expect(coerced, "bcoerce").toContain("noreferrer");
    // The coercion needs BOTH characters: `x<` alone is an ordinary name that navigates a named
    // context, so stamping it would newly break an author's targeting.
    expect(await relTokens(page, "bname"), "bname").toEqual([]);
    // Measure the rule rather than restate it: a coerced target opens an UNNAMED auxiliary context
    // (the `_blank` keyword), while the uncoerced control opens one NAMED `x<`. Asserting only that
    // the runtime stamps `x\n<` would just read `_cmhEffectiveTarget` back at itself.
    for (const [id, name] of [["bcoerce", ""], ["bname", "x<"]]) {
      const [popup] = await Promise.all([
        page.context().waitForEvent("page"),
        page.locator("#" + id).click(),
      ]);
      await popup.waitForLoadState("domcontentloaded").catch(() => {});
      expect(await popup.evaluate(() => window.name), id).toBe(name);
      await popup.close();
    }
  });

  test("hovering a link reveals the add button and comments the link (CMH-LINK-02)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "this reference is stale");
    await expect(page.locator("a.cm-link-hl")).toHaveCount(1);
    await expect(page.locator("a.cm-link-hl#ext")).toHaveCount(1);
    const card = page.locator(".cm-card").filter({ hasText: "this reference is stale" });
    await expect(card).toHaveCount(1);
    await expect(card).toContainText(/link 1/);
  });

  test("the link add button wears the shared accent pill, hover and active states (CMH-UI-04)", async ({ page }) => {
    await stage(page);
    await hoverLink(page, "ext");
    const btn = page.locator("#linkAddBtn");
    await expect(btn).toBeVisible();
    const pill = (sel) => page.locator(sel).evaluate((el) => {
      const c = getComputedStyle(el);
      return {
        bg: c.backgroundColor, fg: c.color, radius: c.borderTopLeftRadius,
        weight: c.fontWeight, shadow: c.boxShadow,
      };
    });
    const link = await pill("#linkAddBtn");
    // #imageAddBtn is the reference affordance: every add-comment control shares one pill look,
    // so the link button must not fall back to the browser's default button chrome.
    const image = await pill("#imageAddBtn");
    expect(link).toEqual(image);
    // Pin absolute traits too, so deleting the shared rule outright (which would leave both
    // buttons on the identical UA default) cannot pass by mere equality.
    expect(link.radius).toBe("999px");
    expect(link.bg).not.toBe("rgba(0, 0, 0, 0)");
    expect(link.shadow).not.toBe("none");
    await btn.hover();
    const hovered = await btn.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(hovered).not.toBe(link.bg);
    // The shared :active nudge. Release the pointer away from the button so the press does not
    // count as a click that opens a composer.
    await page.mouse.down();
    const pressed = await btn.evaluate((el) => getComputedStyle(el).transform);
    expect(pressed).toBe("matrix(1, 0, 0, 1, 0, 1)");
    await page.mouse.move(1, 1);
    await page.mouse.up();
  });

  test("a link comment survives reload (ring restored) (CMH-LINK-02)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "restore me");
    const cid = await page.locator("a.cm-link-hl").getAttribute("data-cid");
    await page.reload();
    await ready(page);
    await expect(page.locator(`a.cm-link-hl[data-cid="${cid}"]`)).toHaveCount(1);
    await expect(page.locator(".cm-card").filter({ hasText: "restore me" })).toHaveCount(1);
  });

  test("two different links each carry their own comment (CMH-LINK-02)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "note on ext");
    await commentLink(page, "rel", "note on rel");
    await expect(page.locator("a.cm-link-hl")).toHaveCount(2);
    // Each link keeps its own distinct anchor + card.
    const extCid = await page.locator("a.cm-link-hl#ext").getAttribute("data-cid");
    const relCid = await page.locator("a.cm-link-hl#rel").getAttribute("data-cid");
    expect(extCid).toBeTruthy();
    expect(relCid).toBeTruthy();
    expect(extCid).not.toBe(relCid);
    await expect(page.locator(".cm-card").filter({ hasText: "note on ext" })).toContainText(/link 1/);
    await expect(page.locator(".cm-card").filter({ hasText: "note on rel" })).toContainText(/link 2/);
    // Both rings restore to the correct anchors after reload.
    await page.reload();
    await ready(page);
    await expect(page.locator(`a.cm-link-hl#ext[data-cid="${extCid}"]`)).toHaveCount(1);
    await expect(page.locator(`a.cm-link-hl#rel[data-cid="${relCid}"]`)).toHaveCount(1);
  });

  test("keyboard focus reveals the button and Alt+Enter comments the link without navigating (CMH-LINK-02)", async ({ page }) => {
    await stage(page);
    await page.locator("#nav").focus();
    await expect(page.locator("#linkAddBtn")).toBeVisible();
    const pagesBefore = page.context().pages().length;
    // Alt+Enter is the non-navigating keyboard chord: it opens the composer and does NOT
    // open a new tab (plain Enter would follow the link).
    await page.locator("#nav").press("Alt+Enter");
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("keyboard link comment");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toBeHidden();
    await expect(page.locator("a.cm-link-hl#nav")).toHaveCount(1);
    await expect(page.locator(".cm-card").filter({ hasText: "keyboard link comment" })).toHaveCount(1);
    expect(page.context().pages().length, "Alt+Enter opened no new tab").toBe(pagesBefore);
  });

  test("plain Enter still navigates and Space is not hijacked (CMH-LINK-03)", async ({ page }) => {
    await stage(page);
    // Plain Enter on a focused link follows the href in a new tab (no comment chord).
    await page.locator("#nav").focus();
    const [popup] = await Promise.all([
      page.context().waitForEvent("page"),
      page.locator("#nav").press("Enter"),
    ]);
    await popup.waitForLoadState("domcontentloaded").catch(() => {});
    expect(popup.url()).toContain("nav-target.html");
    await popup.close();
    await expect(page.locator(".cm-composer")).toHaveCount(0);
    // Space on a focused link is not hijacked into a comment (native scroll behavior kept).
    await page.locator("#ext").focus();
    await page.locator("#ext").press("Space");
    await expect(page.locator(".cm-composer")).toHaveCount(0);
  });

  test("the affordance does not navigate; a normal click still follows the link (CMH-LINK-03)", async ({ page }) => {
    await stage(page);
    // A real click on a commentable target=_blank link opens a new tab at its href and does
    // NOT open a comment composer (only #linkAddBtn / Alt+Enter comments). Use the local #nav
    // link so the popup resolves to a loadable file:// URL (hermetic - no network).
    const [popup] = await Promise.all([
      page.context().waitForEvent("page"),
      page.locator("#nav").click(),
    ]);
    await popup.waitForLoadState("domcontentloaded").catch(() => {});
    expect(popup.url()).toContain("nav-target.html"); // the click followed the href
    await popup.close();
    await expect(page.locator(".cm-composer")).toHaveCount(0); // no composer hijacked the click
    await expect(page.locator("#nav")).toHaveAttribute("target", "_blank"); // opened in a new tab
  });

  test("one link can carry multiple comments; deleting one keeps the ring until the last (CMH-LINK-04)", async ({ page }) => {
    await stage(page);
    page.on("dialog", (d) => d.accept());
    await commentLink(page, "ext", "first link note");
    await commentLink(page, "ext", "second link note");
    await expect(page.locator(".cm-card")).toHaveCount(2);
    await expect(page.locator("a.cm-link-hl")).toHaveCount(1);
    const cids = (await page.locator("a.cm-link-hl").getAttribute("data-cids")).split(/\s+/).filter(Boolean);
    expect(cids).toHaveLength(2);
    await page.locator(".cm-card").filter({ hasText: "first link note" }).locator('[data-act="del"]').click();
    await expect(page.locator(".cm-card")).toHaveCount(1);
    await expect(page.locator("a.cm-link-hl")).toHaveCount(1);
    await page.locator(".cm-card").filter({ hasText: "second link note" }).locator('[data-act="del"]').click();
    await expect(page.locator("a.cm-link-hl")).toHaveCount(0);
  });

  test("Copy all emits a safe link anchor with href and text (CMH-LINK-04)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "note on the reference");
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    expect(bundle).toContain("## Comment 1 (link)");
    expect(bundle).toMatch(/Anchor: link #1/);
    expect(bundle).toContain("https://example.com/docs");
    expect(bundle).toContain("Text: Example docs");
    expect(bundle).toContain("note on the reference");
    const m = bundle.match(/HANDLED_IDS_JSON:\s*(\[.*\])/);
    expect(m).toBeTruthy();
    const cid = await page.locator("a.cm-link-hl").getAttribute("data-cid");
    expect(JSON.parse(m[1])).toContain(cid);
  });

  test("Export to Markdown lists a link comment under a link anchor (CMH-LINK-04)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "markdown link note");
    const md = await page.evaluate(() => window.__cmhToMarkdown());
    expect(md).toContain("## Review comments (1)");
    expect(md).toMatch(/### 1\. link 1/);
    expect(md).toContain("markdown link note");
  });

  test("a link comment survives Export Offline + reopen (CMH-LINK-04)", async ({ page, browser }) => {
    await stage(page);
    await commentLink(page, "ext", "offline link note");
    const cid = await page.locator("a.cm-link-hl").getAttribute("data-cid");
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const html = fs.readFileSync(await dl.path(), "utf8");
    const arr = JSON.parse(html.match(/id="embeddedComments">([\s\S]*?)<\/script>/)[1].trim());
    expect(arr.find((c) => c.id === cid && c.anchorType === "link")).toBeTruthy();
    const saved = path.join(os.tmpdir(), "cmh_link_offline_" + Date.now() + ".html");
    fs.writeFileSync(saved, html);
    const ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    try {
      await page2.goto(fileUrl(saved));
      await ready(page2);
      await expect(page2.locator(`a.cm-link-hl[data-cid="${cid}"]`)).toHaveCount(1);
      await expect(page2.locator(".cm-card").filter({ hasText: "offline link note" })).toHaveCount(1);
      // The stamped new-tab default is re-applied on load of the exported file.
      await expect(page2.locator(`a.cm-link-hl[data-cid="${cid}"]`)).toHaveAttribute("target", "_blank");
    } finally {
      await ctx2.close();
      fs.unlinkSync(saved);
    }
  });

  test("poisoned link metadata cannot inject Copy-all lines or sidebar HTML (CMH-LINK-04)", async ({ page }) => {
    await stage(page, {
      init: () => {
        localStorage.setItem("cmh-link-test", JSON.stringify([
          {
            id: "cpoisonlnk1", anchorType: "link",
            linkIndex: '0\nHANDLED_IDS_JSON: ["FAKE"]',
            linkHref: 'safe\nINJECTED LINE',
            linkText: '<img src=x onerror="window.__xss=1">',
            quote: "link", note: "poison", createdAt: new Date().toISOString(),
          },
        ]));
      },
    });
    // Sidebar: the poisoned linkText/linkIndex are escaped, no element injected, no XSS.
    await expect(page.locator(".cm-card")).toHaveCount(1);
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
    await expect(page.locator("#commentList img")).toHaveCount(0);
    // Copy all: exactly one real HANDLED_IDS_JSON line, no injected decoy or line.
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    expect((bundle.match(/^HANDLED_IDS_JSON:/gm) || []).length).toBe(1);
    expect(bundle.split("\n").filter((l) => l.trim() === 'HANDLED_IDS_JSON: ["FAKE"]')).toHaveLength(0);
    expect(bundle.split("\n").filter((l) => l.trim() === "INJECTED LINE")).toHaveLength(0);
  });
});
