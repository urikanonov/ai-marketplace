// A13 / CMH-A11Y-07: honor prefers-reduced-motion. A global reset clamps non-essential
// animations/transitions to near-zero when the user asks for reduced motion, so the composer
// flash, mermaid/diff pulses, and checklist/notes flashes do not animate. Asserted by emulating
// the media feature and reading the computed animation duration of a real keyframed animation.
import { test, expect } from "@playwright/test";
import { openInline, ready } from "./helpers.js";

// Probe a real layer keyframe animation (cm-composer-flash, defined in 20-chrome.css) under a
// given reduced-motion preference and return its computed animation-duration.
async function probeDuration(page, motion) {
  await page.emulateMedia({ reducedMotion: motion });
  return page.evaluate(() => {
    const el = document.createElement("div");
    el.style.animation = "cm-composer-flash 0.6s ease-out 1";
    document.body.appendChild(el);
    const d = getComputedStyle(el).animationDuration;
    el.remove();
    return d;
  });
}

test("reduced-motion clamps a keyframe animation to near-zero, normal keeps it (CMH-A11Y-07)", async ({ page }) => {
  await openInline(page);
  const reduced = await probeDuration(page, "reduce");
  const normal = await probeDuration(page, "no-preference");
  // Without the preference the animation keeps its authored 0.6s; with it the global reset
  // clamps every animation to a near-instant duration.
  expect(normal).toBe("0.6s");
  expect(parseFloat(reduced)).toBeLessThan(0.05);
});

test("reduced-motion also clamps transitions (CMH-A11Y-07)", async ({ page }) => {
  await openInline(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const dur = await page.evaluate(() => {
    const el = document.createElement("div");
    el.style.transition = "opacity 0.5s ease";
    document.body.appendChild(el);
    const d = getComputedStyle(el).transitionDuration;
    el.remove();
    return d;
  });
  expect(parseFloat(dur)).toBeLessThan(0.05);
});

test("programmatic smooth scrolling becomes instant under reduced motion (CMH-A11Y-07)", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1600, height: 800 });
  await openInline(page);
  // The side-TOC "Scroll to Top" button calls window.scrollTo; under reduced motion the shared
  // cmScrollBehavior() helper must pass behavior:"auto" (JS behavior overrides CSS scroll-behavior).
  const behavior = await page.evaluate(async () => {
    let captured;
    const orig = window.scrollTo;
    window.scrollTo = (opts) => { captured = opts && opts.behavior; };
    const btn = [...document.querySelectorAll("#cmSideToc .cm-side-toc-top")]
      .find((b) => /Scroll to Top/i.test(b.textContent));
    if (btn) btn.click();
    window.scrollTo = orig;
    return captured;
  });
  expect(behavior).toBe("auto");
});

test("programmatic smooth scrolling stays smooth without the preference (CMH-A11Y-07)", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1600, height: 800 });
  await openInline(page);
  const behavior = await page.evaluate(() => {
    let captured;
    const orig = window.scrollTo;
    window.scrollTo = (opts) => { captured = opts && opts.behavior; };
    const btn = [...document.querySelectorAll("#cmSideToc .cm-side-toc-top")]
      .find((b) => /Scroll to Top/i.test(b.textContent));
    if (btn) btn.click();
    window.scrollTo = orig;
    return captured;
  });
  expect(behavior).toBe("smooth");
});
