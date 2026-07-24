const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1000, height: 1000 } });
  await page.goto('file://C:/Projects/AI/ai-marketplace/.worktrees/issue-635-gallery-contain-fit/plugins/commentable-html/dev/test-live.html');
  await page.waitForTimeout(3000);
  
  const cards = await page.$$eval('.cmh-diagram-gallery > pre.mermaid, .cmh-diagram-gallery > figure', els => 
    els.map(el => {
      const rect = el.getBoundingClientRect();
      const svg = el.querySelector('svg');
      const svgRect = svg ? svg.getBoundingClientRect() : null;
      let drawnBox = null;
      if (svg && svg.viewBox && svg.viewBox.baseVal) {
         // rough drawn height for meet
         const aspect = svg.viewBox.baseVal.width / svg.viewBox.baseVal.height;
         const boxAspect = svgRect.width / svgRect.height;
         if (aspect > boxAspect) {
             drawnBox = { w: svgRect.width, h: svgRect.width / aspect };
         } else {
             drawnBox = { w: svgRect.height * aspect, h: svgRect.height };
         }
      }
      return { 
        className: el.className, 
        cardW: rect.width, cardH: rect.height, 
        svgW: svgRect ? svgRect.width : 0, svgH: svgRect ? svgRect.height : 0,
        drawnW: drawnBox ? drawnBox.w : 0, drawnH: drawnBox ? drawnBox.h : 0
      };
    })
  );
  console.log(cards);
  await browser.close();
})();
