// A13 / CMH-A11Y-07: honor prefers-reduced-motion. A global reset clamps non-essential
// animations/transitions to near-zero when the user asks for reduced motion, so the composer
// flash, mermaid/diff pulses, and checklist/notes flashes do not animate. Asserted by emulating
// the media feature and reading the computed animation duration of a real keyframed animation.
import { test, expect } from "@playwright/test";
import { readFileSync, readdirSync } from "fs";
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
  // The reset also neutralizes animation delay and multi-iteration loops (mermaid/diff pulses
  // run 3x, checklist/notes flashes 2x) so nothing lingers or repeats under reduced motion.
  await page.emulateMedia({ reducedMotion: "reduce" });
  const anim = await page.evaluate(() => {
    const el = document.createElement("div");
    el.style.animation = "cm-composer-flash 0.6s ease-out 0.4s 3";
    document.body.appendChild(el);
    const s = getComputedStyle(el);
    const out = { delay: s.animationDelay, count: s.animationIterationCount };
    el.remove();
    return out;
  });
  expect(parseFloat(anim.delay)).toBeLessThan(0.05);
  expect(anim.count).toBe("1");
});

test("reduced-motion also clamps transitions (CMH-A11Y-07)", async ({ page }) => {
  await openInline(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const t = await page.evaluate(() => {
    const el = document.createElement("div");
    el.style.transition = "opacity 0.5s ease 0.3s";
    document.body.appendChild(el);
    const s = getComputedStyle(el);
    const out = { dur: s.transitionDuration, delay: s.transitionDelay };
    el.remove();
    return out;
  });
  expect(parseFloat(t.dur)).toBeLessThan(0.05);
  expect(parseFloat(t.delay)).toBeLessThan(0.05);
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

test("no layer JS partial hardcodes behavior:\"smooth\" - all scroll sites route through cmScrollBehavior() (CMH-A11Y-07)", async () => {
  // Static guard: the runtime tests exercise one scroll path each, but there are ~13 programmatic
  // scroll sites. Rather than click through all of them, assert at the source that (a) no literal
  // smooth behavior is written (any quote style, including template literals) and (b) every
  // scroll call that passes a `behavior` routes it through the reduced-motion-aware helper. Calls
  // are single-line in this codebase, so a line-scoped check catches literal, template-literal,
  // and indirect (behavior: someVar) values that would bypass the helper.
  const dir = new URL("../assets/js/", import.meta.url);
  const files = readdirSync(dir).filter((f) => f.endsWith(".js"));
  const offenders = [];
  let helperDefined = false;
  for (const f of files) {
    const src = readFileSync(new URL(f, dir), "utf8");
    if (/function\s+cmScrollBehavior\s*\(/.test(src)) helperDefined = true;
    for (const lit of src.match(/behavior\s*:\s*[`"']smooth[`"']/g) || []) offenders.push(`${f}: ${lit}`);
    for (const line of src.split("\n")) {
      if (/\.(scrollIntoView|scrollTo|scrollBy)\s*\(/.test(line) && /behavior/.test(line) && !/cmScrollBehavior/.test(line)) {
        offenders.push(`${f}: ${line.trim()}`);
      }
    }
  }
  expect(helperDefined).toBe(true);
  expect(offenders).toEqual([]);
});

test("cmScrollBehavior() fails closed to \"auto\" when the preference cannot be determined (CMH-A11Y-07)", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 800 });
  await openInline(page);
  // Simulate an environment where matchMedia is unavailable AFTER startup, so only the scroll
  // helper (which re-reads on each call) hits it. An a11y feature must default to less motion.
  const behavior = await page.evaluate(() => {
    window.matchMedia = undefined;
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
