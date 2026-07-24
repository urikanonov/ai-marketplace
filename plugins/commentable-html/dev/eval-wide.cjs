const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  await page.goto('file://C:/Projects/AI/ai-marketplace/.worktrees/issue-635-gallery-contain-fit/plugins/commentable-html/dev/test-wide.html');
  await page.waitForTimeout(3000);
  
  const cards = await page.$$eval('.cmh-diagram-gallery > pre.mermaid', els => 
    els.map(el => {
      const rect = el.getBoundingClientRect();
      const svg = el.querySelector('svg');
      const svgRect = svg ? svg.getBoundingClientRect() : null;
      let drawnBox = null;
      if (svg && svg.viewBox && svg.viewBox.baseVal) {
         const aspect = svg.viewBox.baseVal.width / svg.viewBox.baseVal.height;
         const boxAspect = svgRect.width / svgRect.height;
         if (aspect > boxAspect) {
             drawnBox = { w: svgRect.width, h: svgRect.width / aspect };
         } else {
             drawnBox = { w: svgRect.height * aspect, h: svgRect.height };
         }
      }
      return { cardW: rect.width, cardH: rect.height, svgW: svgRect.width, svgH: svgRect.height, drawnW: drawnBox.w, drawnH: drawnBox.h };
    })
  );
  console.log(cards);
  await browser.close();
})();
