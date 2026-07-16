import { test, expect } from "@playwright/test";
import fs from "fs";
import { INLINE, ready, denyExternalNetwork } from "./helpers.js";

const INLINE_HTML = fs.readFileSync(INLINE, "utf8");
const ROOT_RE = /<main id="commentRoot"(?=[^>]*data-comment-key="commentable-html-demo")[^>]*>/;

function htmlWithDensity(density) {
  return INLINE_HTML.replace(ROOT_RE, (tag) => {
    if (!density) return tag;
    return tag.replace(/>$/, ' data-cm-density="' + density + '">');
  });
}

async function measureDensity(page, density) {
  const label = density || "default";
  const url = "http://localhost/density-" + label + ".html";
  await page.route(url, (route) => route.fulfill({
    status: 200,
    contentType: "text/html",
    body: htmlWithDensity(density),
  }));
  await page.goto(url);
  await ready(page);
  return page.evaluate(() => {
    const button = document.getElementById("btnToggleSidebar");
    const buttonStyle = getComputedStyle(button);
    const toolbarStyle = getComputedStyle(document.querySelector(".cm-toolbar"));
    const bodyStyle = getComputedStyle(document.body);
    return {
      bodyDensity: document.body.getAttribute("data-cm-density"),
      rootDensity: document.getElementById("commentRoot").getAttribute("data-cm-density"),
      buttonPaddingX: parseFloat(buttonStyle.paddingLeft),
      buttonFontSize: parseFloat(buttonStyle.fontSize),
      toolbarGap: parseFloat(toolbarStyle.columnGap || toolbarStyle.gap),
      tokenButtonX: bodyStyle.getPropertyValue("--cp-chrome-button-x").trim(),
      tokenFont: bodyStyle.getPropertyValue("--cp-chrome-font").trim(),
    };
  });
}

test("root density preset updates chrome spacing tokens while default stays unchanged (CMH-DENSITY-01)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await denyExternalNetwork(page);

  const defaults = await measureDensity(page, "");
  expect(defaults.bodyDensity).toBeNull();
  expect(defaults.rootDensity).toBeNull();
  expect(defaults.tokenButtonX).toBe("0.7rem");
  expect(defaults.tokenFont).toBe("0.85rem");
  expect(defaults.buttonPaddingX).toBeCloseTo(11.2, 1);
  expect(defaults.buttonFontSize).toBeCloseTo(13.6, 1);

  const compact = await measureDensity(page, "compact");
  expect(compact.bodyDensity).toBe("compact");
  expect(compact.rootDensity).toBe("compact");
  expect(compact.tokenButtonX).toBe("0.55rem");
  expect(compact.tokenFont).toBe("0.8rem");
  expect(compact.buttonPaddingX).toBeLessThan(defaults.buttonPaddingX);
  expect(compact.buttonFontSize).toBeLessThan(defaults.buttonFontSize);
  expect(compact.toolbarGap).toBeLessThan(defaults.toolbarGap);

  const comfortable = await measureDensity(page, "comfortable");
  expect(comfortable.bodyDensity).toBe("comfortable");
  expect(comfortable.rootDensity).toBe("comfortable");
  expect(comfortable.tokenButtonX).toBe("0.85rem");
  expect(comfortable.tokenFont).toBe("0.9rem");
  expect(comfortable.buttonPaddingX).toBeGreaterThan(defaults.buttonPaddingX);
  expect(comfortable.buttonFontSize).toBeGreaterThan(defaults.buttonFontSize);
  expect(comfortable.toolbarGap).toBeGreaterThan(defaults.toolbarGap);
});
