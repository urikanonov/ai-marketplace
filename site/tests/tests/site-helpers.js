// The plugin page's demo iframe is loading="lazy" and every demo document is a self-contained
// 1-2.5 MB report, so asserting straight on the framed content makes ONE timeout cover both the
// download and the mount - on a cold runner the download eats it and the content assertion is
// what reports the failure. Scroll the frame in (what a reader reaching the section does), wait
// for the expected document to finish loading, and only then hand the caller a frame locator.
// The 30s default is deliberately well under the 90s a caller's test.slow() grants, so this wait
// plus the caller's own mount budget (15-20s) still fits inside the test timeout and a genuinely
// stuck frame reports the message below rather than a bare "test timeout exceeded".
async function demoFrameReady(page, selector, expectedFile, timeout = 30000) {
  await page.locator(selector).scrollIntoViewIfNeeded();
  try {
    await page.waitForFunction(
      ([sel, want]) => {
        const el = document.querySelector(sel);
        const doc = el && el.contentDocument;
        if (!doc || doc.readyState !== "complete") return false;
        return !want || String(doc.location.href).includes(want);
      },
      [selector, expectedFile || ""],
      { timeout },
    );
  } catch (error) {
    // A test-level timeout aborts the wait from outside; reporting it as a frame-load failure
    // would name the wrong cause (and the wrong duration), so let it through untouched.
    if (/Test (?:timeout|ended)/i.test(String(error && error.message))) throw error;
    throw new Error(
      `the demo document ${expectedFile || ""} never finished loading in ${selector} within `
        + `${timeout}ms - the frame load failed, not the content assertion that follows`,
      { cause: error },
    );
  }
  return page.frameLocator(selector);
}

// A copy button's feedback is deliberately TRANSIENT: the runtime sets the label, the state class,
// and the live-region text only when the clipboard call RESOLVES, then reverts all three 1500ms
// (success) or 2000ms (failure) later. Asserting on the live DOM therefore races that revert twice
// over - a poll can miss the window outright on a cold or loaded runner, and separate assertions
// spread across it so the later ones read an already-reverted button. Both showed up as rare
// full-suite flakes (#859). Record every state the button passes through instead, installed BEFORE
// the click, so the assertions read a log that cannot expire rather than a live sample.
async function recordCopyFeedback(btn) {
  // The live region is created when the click handler is wired, so waiting for it also removes the
  // separate race of clicking a button whose handler is not attached yet.
  await btn.locator(":scope + .copy-status").waitFor({ state: "attached" });
  await btn.evaluate((el) => {
    const sibling = el.nextElementSibling;
    const live = sibling && sibling.classList.contains("copy-status") ? sibling : null;
    const snapshot = () => ({
      label: (el.textContent || "").trim(),
      copied: el.classList.contains("copied"),
      failed: el.classList.contains("copy-failed"),
      status: live ? (live.textContent || "").trim() : null,
    });
    const states = [snapshot()];
    el.__copyFeedback = states;
    const record = () => {
      const next = snapshot();
      const last = states[states.length - 1];
      if (last.label !== next.label || last.copied !== next.copied
        || last.failed !== next.failed || last.status !== next.status) {
        states.push(next);
      }
    };
    // The label, the state class, and the live-region text are set together in one task, so one
    // observer delivery yields one snapshot carrying all three - which is what lets a spec assert
    // on them atomically instead of sampling each in turn.
    const observer = new MutationObserver(record);
    observer.observe(el, {
      childList: true,
      characterData: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class"],
    });
    if (live) observer.observe(live, { childList: true, characterData: true, subtree: true });
  });
  const states = () => btn.evaluate((el) => {
    if (!el.__copyFeedback) {
      throw new Error(
        "recordCopyFeedback's recorder is missing on this element - it was re-rendered or the page "
          + "navigated since the recorder was installed",
      );
    }
    return el.__copyFeedback;
  });
  return {
    states,
    // The distinct labels the button has shown, in order, so a transition can be asserted whole.
    labels: async () => (await states())
      .map((state) => state.label)
      .filter((label, index, all) => index === 0 || all[index - 1] !== label),
    // Resolves once no new state has been recorded for `quietMs`, so an assertion on the FINAL
    // state cannot land while a revert timer (or a second, slower clipboard write) is still in
    // flight. The default is comfortably past the 2000ms failure revert.
    waitForQuiet: async (quietMs = 2500, timeout = 20000) => {
      const deadline = Date.now() + timeout;
      let recorded = await states();
      let lastChange = Date.now();
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        const next = await states();
        if (next.length !== recorded.length) {
          recorded = next;
          lastChange = Date.now();
        } else if (Date.now() - lastChange >= quietMs) {
          return next;
        }
        if (Date.now() >= deadline) {
          throw new Error(
            `copy-button feedback never went quiet for ${quietMs}ms within ${timeout}ms - recorded: `
              + JSON.stringify(next),
          );
        }
      }
    },
    waitForState: async (match, what, timeout = 20000) => {
      const deadline = Date.now() + timeout;
      for (;;) {
        const recorded = await states();
        const hit = recorded.find(match);
        if (hit) return hit;
        if (Date.now() >= deadline) {
          throw new Error(
            `no recorded copy-button state matched ${what} within ${timeout}ms - recorded: `
              + JSON.stringify(recorded),
          );
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    },
  };
}

function contrastRatio(foreground, background) {
  const channel = (value) => {
    const normalized = value / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : Math.pow((normalized + 0.055) / 1.055, 2.4);
  };
  const luminance = (color) => {
    const r = channel(color.r);
    const g = channel(color.g);
    const b = channel(color.b);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

async function compositedContrast(page, selector) {
  return page.locator(selector).first().evaluate((el) => {
    const parseColor = (value) => {
      const raw = (value || "").trim().toLowerCase();
      if (!raw || raw === "transparent") return { r: 0, g: 0, b: 0, a: 0 };
      const hex = raw.match(/^#([0-9a-f]{6})$/i);
      if (hex) {
        return {
          r: parseInt(hex[1].slice(0, 2), 16),
          g: parseInt(hex[1].slice(2, 4), 16),
          b: parseInt(hex[1].slice(4, 6), 16),
          a: 1,
        };
      }
      const rgb = raw.match(/^rgba?\((.*)\)$/);
      if (rgb) {
        const parts = rgb[1].replace(/\//g, " ").split(/[,\s]+/).filter(Boolean);
        const channel = (part) => part.endsWith("%") ? Number(part.slice(0, -1)) * 2.55 : Number(part);
        return {
          r: channel(parts[0]),
          g: channel(parts[1]),
          b: channel(parts[2]),
          a: parts[3] === undefined ? 1 : Number(parts[3]),
        };
      }
      const srgb = raw.match(/^color\(srgb\s+(.+)\)$/);
      if (srgb) {
        const parts = srgb[1].replace(/\//g, " ").split(/\s+/).filter(Boolean);
        return {
          r: Number(parts[0]) * 255,
          g: Number(parts[1]) * 255,
          b: Number(parts[2]) * 255,
          a: parts[3] === undefined ? 1 : Number(parts[3]),
        };
      }
      throw new Error("unsupported color format: " + value);
    };
    const blend = (top, bottom) => {
      const alpha = top.a + bottom.a * (1 - top.a);
      if (alpha === 0) return { r: 0, g: 0, b: 0, a: 0 };
      return {
        r: (top.r * top.a + bottom.r * bottom.a * (1 - top.a)) / alpha,
        g: (top.g * top.a + bottom.g * bottom.a * (1 - top.a)) / alpha,
        b: (top.b * top.a + bottom.b * bottom.a * (1 - top.a)) / alpha,
        a: alpha,
      };
    };
    let background = { r: 0, g: 0, b: 0, a: 0 };
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE) {
      background = blend(background, parseColor(getComputedStyle(node).backgroundColor));
      if (background.a >= 0.999) break;
      node = node.parentElement;
    }
    if (background.a < 0.999) {
      background = blend(background, { r: 255, g: 255, b: 255, a: 1 });
    }
    return {
      foreground: parseColor(getComputedStyle(el).color),
      background: background,
    };
  });
}

function installNetworkBlock(test) {
  test.beforeEach(async ({ context }) => {
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.protocol === "data:" || url.hostname === "127.0.0.1" || url.hostname === "localhost") {
        return route.continue();
      }
      return route.abort();
    });
  });
}

module.exports = {
  contrastRatio,
  compositedContrast,
  demoFrameReady,
  installNetworkBlock,
  recordCopyFeedback,
};
