// The commentable-html montage: what a viewer sees, in order, and which ability each moment shows.
//
// Kept separate from the recorder so the SHAPE of the demo (and its ability coverage) is unit
// testable without a browser. Each beat gets a weight, not a duration - the scheduler turns weights
// into an exact split of whatever clip length was asked for, so the same montage works at 10 seconds
// or at 30 without re-timing every step by hand.
//
// Every `run` is best-effort: it reports through `ctx.warn` instead of throwing, so a runtime change
// degrades one beat of the clip rather than aborting a capture that took a browser to produce.

export const REPORT_ABILITIES = [
  "rich-report",
  "diagrams",
  "selection",
  "composer",
  "anchored-comments",
  "sidebar",
  "threads",
  "comment-search",
  "toc",
  "toolbar-menu",
  "exports",
  "diff",
];

const NOTE = "Is the spring planting window realistic?";

export const REPORT_BEATS = [
  {
    id: "open",
    label: "A self-contained report opens in the browser",
    abilities: ["rich-report"],
    weight: 0.4,
    async run(page, ctx) {
      // Motion from the first frame, and the cursor on screen straight away. A beat that just sits
      // at the top of the document reads as a stuck video before the clip has said anything.
      await ctx.scrollTo(0);
      await ctx.moveCursor(760, 300);
      await ctx.sleep(120);
      await ctx.moveCursor(560, 210);
      await ctx.glideTo(320, ctx.budgetMs * 0.75);
    },
  },
  {
    id: "tour",
    label: "Rich content: tables, callouts and live diagrams",
    abilities: ["rich-report", "diagrams"],
    weight: 1,
    async run(page, ctx) {
      const target = await ctx.offsetOf(
        ["#commentRoot .mermaid", "#commentRoot .cmh-chart", "#commentRoot figure", "#commentRoot table"],
        { after: 700 },
      );
      // Falling back to a hard-coded offset silently is how a beat ends up filming blank page: the
      // selectors belong to another part of the repo and can change without this tool noticing.
      if (target == null) {
        ctx.warn("no diagram, chart, figure or table found to tour");
        await ctx.glideTo(1100, ctx.budgetMs * 0.85);
        return;
      }
      await ctx.glideTo(target - 150, ctx.budgetMs * 0.85);
    },
  },
  {
    id: "select",
    label: "Select any text to review it",
    abilities: ["selection"],
    required: true,
    weight: 1,
    async run(page, ctx) {
      // Glide back rather than jump: a hard cut to the top mid-clip reads as a glitch.
      await ctx.glideTo(0, Math.min(500, ctx.budgetMs * 0.3));
      const ok = await ctx.dragSelect("#commentRoot p");
      if (!ok) return ctx.warn("no paragraph was selectable");
      await ctx.waitVisible("#menuComment", 2000);
      await ctx.holdRemaining(120);
    },
  },
  {
    id: "compose",
    label: "The composer opens where the selection is",
    abilities: ["composer"],
    required: true,
    weight: 1.6,
    async run(page, ctx) {
      const menu = page.locator("#menuComment");
      if (!(await menu.count())) return ctx.warn("the selection menu never appeared");
      await ctx.click(menu);
      const composer = page.locator(".cm-composer").last();
      if (!(await ctx.waitVisible(composer, 2500))) return ctx.warn("the composer never opened");
      await ctx.type(composer.locator("textarea"), NOTE, ctx.budgetMs * 0.6);
    },
  },
  {
    id: "save",
    label: "Saving anchors a highlight and files the comment",
    abilities: ["anchored-comments", "sidebar"],
    required: true,
    weight: 1.1,
    async run(page, ctx) {
      const save = page.locator(".cm-composer").last().locator('[data-act="save"]');
      if (!(await save.count())) return ctx.warn("the composer had no save action");
      await ctx.click(save);
      await ctx.settle(400);
      const mark = page.locator("#commentRoot mark[data-cid]").first();
      if (await mark.count()) await ctx.scrollIntoView(mark);
    },
  },
  {
    id: "thread",
    label: "Threads: reply to a comment in the sidebar",
    abilities: ["threads"],
    weight: 1.3,
    async run(page, ctx) {
      const card = page.locator("#commentList .cm-card[data-cid]").first();
      if (!(await card.count())) return ctx.warn("no comment card to reply to");
      await ctx.scrollIntoView(card);
      const replyBtn = card.locator(".cm-reply-btn").first();
      if (!(await replyBtn.count())) return ctx.warn("this build has no reply affordance");
      await ctx.click(replyBtn);
      const box = card.locator(".cm-reply-compose textarea").first();
      if (!(await ctx.waitVisible(box, 1500))) return ctx.warn("the reply box never opened");
      await ctx.type(box, "Agreed - let us push it two weeks.", ctx.budgetMs * 0.4);
      const saveReply = card.locator(".cm-reply-save").first();
      if (await saveReply.count()) await ctx.click(saveReply);
    },
  },
  {
    id: "search",
    label: "Search and filter the review",
    abilities: ["comment-search"],
    weight: 0.9,
    async run(page, ctx) {
      const toggle = page.locator("#btnSearchToggle");
      if (!(await toggle.count())) return ctx.warn("no comment search in this build");
      await ctx.click(toggle);
      const input = page.locator("#cmSearchInput");
      if (!(await ctx.waitVisible(input, 1500))) return ctx.warn("the search box never opened");
      await ctx.type(input, "planting", ctx.budgetMs * 0.55);
    },
  },
  {
    id: "toc",
    label: "A table of contents tracks review progress",
    abilities: ["toc"],
    weight: 0.9,
    async run(page, ctx) {
      const toc = page.locator("#cmSideToc");
      if (!(await toc.count())) return ctx.warn("no side table of contents in this build");
      const toggle = page.locator(".cm-side-toc-toggle").first();
      if (await toggle.count()) await ctx.click(toggle);
      await ctx.settle(250);
      if (await toc.isVisible().catch(() => false)) await ctx.scrollIntoView(toc);
    },
  },
  {
    id: "menu",
    label: "Export the review: portable HTML, Markdown, offline copy",
    abilities: ["toolbar-menu", "exports"],
    weight: 1.1,
    async run(page, ctx) {
      // The search panel takes the header over while it is open, so close it before reaching for a
      // menu, or this beat films nothing.
      const clear = page.locator("#cmSearchClear");
      if (await clear.count() && await clear.isVisible().catch(() => false)) await ctx.click(clear);
      await page.keyboard.press("Escape").catch(() => {});
      await ctx.settle(200);
      // Once a comment is saved the sidebar is open, and the top toolbar collapses into it - so the
      // export affordance to film is the SIDEBAR's, with the toolbar menu as the fallback for a
      // document that has no comments yet.
      const candidates = [
        { button: "#btnSidebarExportMenu", menu: "#sidebarExportMenu" },
        { button: "#btnToolbarMenu", menu: "#toolbarMenu" },
      ];
      for (const { button, menu } of candidates) {
        const btn = page.locator(button);
        if (!(await btn.count())) continue;
        if (!(await btn.isVisible().catch(() => false))) continue;
        await ctx.click(btn);
        if (await ctx.waitVisible(menu, 1200)) {
          // Hold the menu OPEN for what is left of the beat. Closing it and returning early hands
          // the remaining budget back to the pacing sleep, which films a closed menu instead.
          await ctx.holdRemaining(150);
          await page.keyboard.press("Escape").catch(() => {});
          return;
        }
      }
      ctx.warn("no export or toolbar menu was reachable");
    },
  },
  {
    id: "closeout",
    label: "Review a proposed change, diff and all",
    abilities: ["diff"],
    weight: 0.9,
    async run(page, ctx) {
      const target = await ctx.offsetOf(
        ["#commentRoot .cmh-diff", "#commentRoot pre", "#commentRoot .mermaid"],
        { after: 1400 },
      );
      if (target == null) {
        ctx.warn("no diff, code block or diagram found for the close-out");
        await ctx.glideTo(2600, ctx.budgetMs * 0.8);
        return;
      }
      await ctx.glideTo(target - 120, ctx.budgetMs * 0.8);
    },
  },
];
