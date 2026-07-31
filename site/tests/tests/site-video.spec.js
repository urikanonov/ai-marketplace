const { test, expect } = require("@playwright/test");
const { installNetworkBlock } = require("./site-helpers");

installNetworkBlock(test);

const openLightbox = async (page, url) => {
  const resp = await page.goto(url, { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  await page.locator(".video-thumb").first().click();
  const overlay = page.locator(".lightbox-video");
  await expect(overlay).toBeVisible();
  return overlay;
};

test("the commentable-html page offers two demo clips between the loop and why sections (SITE-VIDEO-01)", async ({ page }) => {
  const resp = await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  const block = page.locator("#video");
  await expect(block).toBeVisible();
  await expect(block.locator(".video-thumb")).toHaveCount(2);

  // Position is the point: the clips introduce the loop before the argument for it.
  const order = await page.evaluate(() => {
    const ids = Array.from(document.querySelectorAll("section[id]")).map((s) => s.id);
    return { video: ids.indexOf("video"), why: ids.indexOf("why") };
  });
  expect(order.video).toBeGreaterThanOrEqual(0);
  expect(order.video).toBeLessThan(order.why);
});

test("the multi-duck page pairs its copy with a single clip before the why section (SITE-VIDEO-02)", async ({ page }) => {
  const resp = await page.goto("/multi-duck/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  const block = page.locator("#video.video-split, #video .video-split");
  await expect(block.first()).toBeVisible();
  await expect(page.locator("#video .video-thumb")).toHaveCount(1);

  // Copy on the left, clip on the right - a stacked column would read as a different section.
  const box = await page.evaluate(() => {
    const copy = document.querySelector("#video .video-split-copy").getBoundingClientRect();
    const thumb = document.querySelector("#video .video-thumb").getBoundingClientRect();
    return { copyRight: copy.right, thumbLeft: thumb.left };
  });
  expect(box.thumbLeft).toBeGreaterThanOrEqual(box.copyRight - 1);
});

test("a demo thumbnail costs a poster, not a clip, until it is pressed (SITE-VIDEO-03)", async ({ page }) => {
  const requested = [];
  page.on("request", (r) => {
    if (/\.webm(\?|$)/.test(r.url())) requested.push(r.url());
  });
  const resp = await page.goto("/commentable-html/", { waitUntil: "networkidle" });
  expect(resp.status()).toBeLessThan(400);
  // Embedding several multi-megabyte clips directly would bill every visitor for them.
  expect(requested).toEqual([]);

  // The poster carries intrinsic dimensions so the grid reserves its space and nothing shifts.
  const poster = page.locator(".video-thumb .video-thumb-media img").first();
  await expect(poster).toHaveAttribute("width", /\d+/);
  await expect(poster).toHaveAttribute("height", /\d+/);
  await expect(poster).toHaveAttribute("alt", /\S/);
});

test("the lightbox plays the clip and restores focus when dismissed (SITE-VIDEO-04)", async ({ page }) => {
  const overlay = await openLightbox(page, "/commentable-html/");
  await expect(overlay.locator("video")).toHaveAttribute("controls", "");
  await expect(overlay).toHaveAttribute("role", "dialog");
  await expect(overlay).toHaveAttribute("aria-modal", "true");

  await page.keyboard.press("Escape");
  await expect(overlay).toBeHidden();
  // The source is dropped, not merely paused: an attached clip keeps buffering behind a closed
  // overlay and can keep its audio alive.
  expect(await overlay.locator("video").getAttribute("src")).toBeNull();
  await expect(page.locator(".video-thumb").first()).toBeFocused();
});

test("pressing a speed keeps the clip open and actually changes the rate (SITE-VIDEO-05)", async ({ page }) => {
  const overlay = await openLightbox(page, "/commentable-html/");
  const video = overlay.locator("video");

  for (const rate of ["1.5", "2", "1"]) {
    await overlay.locator(`.lightbox-speed[data-rate="${rate}"]`).click();
    // The overlay must SURVIVE the press. A dismiss rule of "anything that is not the video"
    // closes the clip the moment a speed is chosen, while still setting the rate - so asserting
    // the rate alone passes against a lightbox that just slammed shut.
    await expect(overlay).toBeVisible();
    await expect(overlay.locator(`.lightbox-speed[data-rate="${rate}"]`)).toHaveAttribute("aria-pressed", "true");
    // Loading a source resets playbackRate to the default, so a rate set only on the live
    // property silently reverts to 1x as soon as the clip loads. Reading the live rate right after
    // the click does NOT observe that - assert the default too, and force a reload to prove the
    // rate survives it.
    expect(await video.evaluate((v) => v.playbackRate)).toBe(Number(rate));
    expect(await video.evaluate((v) => v.defaultPlaybackRate)).toBe(Number(rate));
    await video.evaluate((v) => new Promise((r) => {
      v.load();
      v.addEventListener("loadedmetadata", r, { once: true });
    }));
    expect(await video.evaluate((v) => v.playbackRate)).toBe(Number(rate));
  }

  // Clicking the video itself is play/pause, not dismiss.
  await video.click({ position: { x: 12, y: 12 } });
  await expect(overlay).toBeVisible();
});

test("the clip is seekable and hides picture-in-picture and download (SITE-VIDEO-06)", async ({ page }) => {
  const overlay = await openLightbox(page, "/commentable-html/");
  const video = overlay.locator("video");
  await video.evaluate((v) => new Promise((r) => (v.readyState >= 1 ? r() : v.addEventListener("loadedmetadata", r, { once: true }))));

  // A browser-recorded webm carries no duration or cues, which leaves duration Infinity and
  // seekable empty - the scrub bar is then dead and every seek hangs. The published clips are
  // remuxed so a reader can skip ahead.
  const media = await video.evaluate((v) => ({
    duration: v.duration,
    seekable: v.seekable.length > 0,
    pipDisabled: v.disablePictureInPicture === true,
    noDownload: v.controlsList ? v.controlsList.contains("nodownload") : false,
    rateAllowed: v.controlsList ? !v.controlsList.contains("noplaybackrate") : true,
  }));
  expect(Number.isFinite(media.duration)).toBe(true);
  expect(media.duration).toBeGreaterThan(1);
  expect(media.seekable).toBe(true);
  expect(media.pipDisabled).toBe(true);
  expect(media.noDownload).toBe(true);
  expect(media.rateAllowed).toBe(true);
});

test("the static server answers byte ranges so a clip can be scrubbed (SITE-VIDEO-07)", async ({ request }) => {
  // Seeking is a Range request. A server that only ever answers 200 with the whole file makes the
  // scrub bar unusable, and would disagree with GitHub Pages, which does serve ranges.
  const partial = await request.get("/assets/demo-multi-duck.webm", { headers: { Range: "bytes=100-199" } });
  expect(partial.status()).toBe(206);
  expect(partial.headers()["content-range"]).toMatch(/^bytes 100-199\/\d+$/);
  expect((await partial.body()).length).toBe(100);

  const whole = await request.get("/assets/poster-multi-duck.jpg");
  expect(whole.status()).toBe(200);
  expect(whole.headers()["accept-ranges"]).toBe("bytes");

  const unsatisfiable = await request.get("/assets/poster-multi-duck.jpg", { headers: { Range: "bytes=99999999-" } });
  expect(unsatisfiable.status()).toBe(416);
});

test("the rationale reads as distinct background slices, not one continuous slab (SITE-VIDEO-08)", async ({ page }) => {
  const resp = await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);

  // The page alternates band colours section by section. Holding the argument, the review-loop
  // explainer and the medium comparison in ONE section painted them as a single unbroken stretch,
  // which reads as a wall rather than as the page's own rhythm.
  const bands = await page.evaluate(() =>
    ["why", "review-loop", "compare"].map((id) => {
      const el = document.getElementById(id);
      return el ? { id: id, tag: el.tagName, bg: getComputedStyle(el).backgroundColor } : { id: id, tag: null };
    }));
  for (const band of bands) {
    expect(band.tag, `${band.id} should be its own section`).toBe("SECTION");
  }
  // Adjacent slices must differ, which is what makes the boundary visible.
  expect(bands[0].bg).not.toBe(bands[1].bg);
  expect(bands[1].bg).not.toBe(bands[2].bg);

  // The two "loop" sections are distinct: the review-loop DIAGRAM here, the three ways to RUN the
  // loop further down. Sharing an id would break the in-page anchors for both.
  const ids = await page.evaluate(() => Array.from(document.querySelectorAll("[id]")).map((e) => e.id));
  const duplicates = ids.filter((id, i) => id && ids.indexOf(id) !== i);
  expect(duplicates).toEqual([]);
});

test("no review step outgrows the diagram it sits beside (SITE-VIDEO-09)", async ({ page }) => {
  const resp = await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);

  // Each step is a title plus at most two lines of body. A step that wraps further drives the whole
  // explainer taller than the diagram beside it, which is what made the section feel padded out.
  const steps = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".loop-step-body p")).map((el) => {
      const lineHeight = parseFloat(getComputedStyle(el).lineHeight);
      return { lines: Math.round(el.getBoundingClientRect().height / lineHeight), text: el.textContent.trim() };
    }));
  expect(steps.length).toBe(4);
  for (const step of steps) {
    expect(step.lines, `"${step.text}" wraps to ${step.lines} lines`).toBeLessThanOrEqual(2);
  }
});

test("the loop diagram panel contrasts with the card it sits in (SITE-VIDEO-10)", async ({ page }) => {
  // The base fill is --cp-surface, which IS the card's own background on an odd band, so the
  // panel disappeared into the card. Check the rendered colours rather than the rule: the point
  // is a visible edge, in either colour scheme, and on the vertical twin phones get.
  const rgb = (value) => (value.match(/\d+/g) || []).slice(0, 3).map(Number);
  const perceptibleGap = (a, b) => {
    const [ar, ag, ab] = rgb(a);
    const [br, bg, bb] = rgb(b);
    return Math.abs(ar - br) + Math.abs(ag - bg) + Math.abs(ab - bb);
  };

  for (const scheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const width of [1180, 380]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
      const shown = await page.evaluate(() => {
        const card = document.querySelector("#review-loop .section-block");
        // Only one of the horizontal/vertical twins is displayed at a time.
        const panel = Array.from(document.querySelectorAll("#review-loop .loop-fig-bg"))
          .find((n) => n.getBoundingClientRect().width > 0);
        return panel ? { card: getComputedStyle(card).backgroundColor, panel: getComputedStyle(panel).fill } : null;
      });
      expect(shown, `no visible diagram at ${width}px`).not.toBeNull();
      expect(
        perceptibleGap(shown.card, shown.panel),
        `${scheme} at ${width}px: panel ${shown.panel} on card ${shown.card}`,
      ).toBeGreaterThan(20);
    }
  }
});

test("the backdrop and the close button dismiss, but a drag off a control does not (SITE-VIDEO-11)", async ({ page }) => {
  const overlay = await openLightbox(page, "/commentable-html/");

  // A click is dispatched on the nearest common ancestor of press and release, so a drag that
  // starts on a control and ends on the backdrop reports the OVERLAY as its target. Without
  // tracking where the press began, a 20px slip off a speed pill closes the clip.
  const pill = overlay.locator('.lightbox-speed[data-rate="2"]');
  const box = await pill.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y - 80);
  await page.mouse.up();
  await expect(overlay).toBeVisible();

  // The same for a scrub that leaves the video.
  const video = overlay.locator("video");
  const vb = await video.boundingBox();
  await page.mouse.move(vb.x + vb.width / 2, vb.y + vb.height / 2);
  await page.mouse.down();
  await page.mouse.move(vb.x + vb.width / 2, vb.y - 60);
  await page.mouse.up();
  await expect(overlay).toBeVisible();

  // The backdrop still dismisses - it is the primary affordance for a modal, and nothing else
  // pinned it, so a rule that only honoured the close button would have shipped green.
  await page.mouse.click(4, 4);
  await expect(overlay).toBeHidden();

  // ...and so does the close button.
  await page.locator(".video-thumb").first().click();
  await expect(overlay).toBeVisible();
  await overlay.locator(".lightbox-close").click();
  await expect(overlay).toBeHidden();
});

test("the overlay shows the poster while the clip loads, and clears it after (SITE-VIDEO-12)", async ({ page }) => {
  const overlay = await openLightbox(page, "/commentable-html/");
  const video = overlay.locator("video");
  // preload="none" leaves the element with no intrinsic size, so without a poster a real network
  // shows a 300x150 black box until metadata arrives. The poster is already downloaded.
  await expect(video).toHaveAttribute("poster", /poster-commentable-html\.jpg/);
  await page.keyboard.press("Escape");
  // Cleared on close, or the next clip opens showing the previous one's still.
  expect(await video.getAttribute("poster")).toBeNull();
});

test("the clips and posters are served with their real media types (SITE-VIDEO-13)", async ({ request }) => {
  // Served as application/octet-stream, Chromium sniffs and plays anyway - but that diverges from
  // Pages and is what makes a local preview fail in Firefox.
  const clip = await request.get("/assets/demo-multi-duck.webm");
  expect(clip.status()).toBe(200);
  expect(clip.headers()["content-type"]).toBe("video/webm");
  const poster = await request.get("/assets/poster-multi-duck.jpg");
  expect(poster.headers()["content-type"]).toBe("image/jpeg");
});
