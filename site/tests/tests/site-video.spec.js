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
    // property silently reverts to 1x as soon as the clip loads.
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
