// The commentable-html montage: what a viewer sees, in order, and which ability each moment shows.
//
// Kept separate from the recorder so the SHAPE of the demo (and its ability coverage) is unit
// testable without a browser. Each beat gets a weight, not a duration - the scheduler turns weights
// into an exact split of whatever clip length was asked for, so the same montage works at 25 seconds
// or at 40 without re-timing every step by hand.
//
// The point the montage has to land is that ANY content is commentable, so it comments on five
// different kinds in a row: prose, an image, a line of a code diff, a node of a Mermaid diagram, and
// a Chart.js chart. The notes are deliberately terse - time spent watching text being typed is time
// not spent showing the next thing.
//
// Every `run` is best-effort: it reports through `ctx.warn` instead of throwing, so a runtime change
// degrades one beat of the clip rather than aborting a capture that took a browser to produce. The
// beats marked `required` carry the demo - if one of those shows nothing, the recorder fails the run
// rather than publishing a clip of a cursor waving at a document.
//
// ORDERING IS LOAD-BEARING. Saving the first comment opens the sidebar, which collapses the top
// toolbar; opening search takes the sidebar header over; the delete beat needs comments to exist.

export const REPORT_ABILITIES = [
  "selection",
  "composer",
  "anchored-comments",
  "sidebar",
  "images",
  "diff-review",
  "diagrams",
  "charts",
  "threads",
  "delete-comment",
  "comment-search",
  "toolbar-menu",
  "exports",
];

const cardCount = (page) => page.locator("#commentList .cm-card[data-cid]").count().catch(() => 0);

// Finish a comment once its composer is open: type, save, and CONFIRM a card actually appeared.
// Clicking save is not evidence that a comment was filed, and a required beat that trusts the click
// reports success over a clip that shows nothing.
async function finishComment(page, ctx, note, before, share) {
  const composer = page.locator(".cm-composer").last();
  if (!(await ctx.waitVisible(composer, 2500))) { ctx.warn("the composer never opened"); return false; }
  await ctx.type(composer.locator("textarea"), note, ctx.budgetMs * share);
  const save = composer.locator('[data-act="save"]');
  if (!(await save.count())) { ctx.warn("the composer had no save action"); return false; }
  await ctx.click(save);
  await ctx.settle(200);
  if ((await cardCount(page)) <= before) { ctx.warn(`saving filed no comment: ${note}`); return false; }
  return true;
}

// Prose is commented by SELECTING it - the affordance a reader discovers first.
async function commentOnText(page, ctx, selector, note, { index = 0, share = 0.45 } = {}) {
  const before = await cardCount(page);
  if (!(await ctx.dragSelect(selector, { index }))) {
    ctx.warn(`nothing selectable matched ${selector}`);
    return false;
  }
  const menu = page.locator("#menuComment");
  if (!(await ctx.waitVisible(menu, 2000))) { ctx.warn("the selection menu never appeared"); return false; }
  await ctx.click(menu);
  return finishComment(page, ctx, note, before, share);
}

// Everything that is not prose - an image, a diff line, a diagram node, a chart - is commented by
// HOVERING the block, which floats its own add button. Same composer, different way in.
async function commentOnBlock(page, ctx, { target, button, note, share = 0.45 }) {
  const before = await cardCount(page);
  if (!(await ctx.hoverBlock(target))) { ctx.warn(`no element matched ${target}`); return false; }
  const add = page.locator(button);
  if (!(await ctx.waitVisible(add, 2500))) { ctx.warn(`${button} never appeared for ${target}`); return false; }
  await ctx.click(add);
  return finishComment(page, ctx, note, before, share);
}

export const REPORT_BEATS = [
  {
    id: "comment-text",
    label: "Select any prose and comment on it",
    abilities: ["selection", "composer", "anchored-comments", "sidebar"],
    weight: 1.5,
    required: true,
    async run(page, ctx) {
      // The clip opens ON the first interaction. An establishing beat that just sits at the top of
      // the document reads as a stuck video before the demo has said anything.
      await ctx.scrollTo(0);
      await ctx.moveCursor(720, 260);
      await commentOnText(page, ctx, "#commentRoot p", "Is this window realistic?");
    },
  },
  {
    id: "comment-image",
    label: "Comment on an image",
    abilities: ["images", "anchored-comments"],
    weight: 1.2,
    required: true,
    async run(page, ctx) {
      await commentOnBlock(page, ctx, {
        target: "#commentRoot img",
        button: "#imageAddBtn",
        note: "Label the beds?",
      });
    },
  },
  {
    id: "comment-diff",
    label: "Comment on a line of a code diff",
    abilities: ["diff-review", "anchored-comments"],
    weight: 1.2,
    async run(page, ctx) {
      await commentOnBlock(page, ctx, {
        target: "#commentRoot .cmh-dl-add",
        button: "#diffAddBtn",
        note: "Guard the zero case.",
      });
    },
  },
  {
    id: "comment-mermaid",
    label: "Comment on a node of a Mermaid diagram",
    abilities: ["diagrams", "anchored-comments"],
    weight: 1.2,
    async run(page, ctx) {
      await commentOnBlock(page, ctx, {
        target: "#commentRoot .mermaid svg g.node",
        button: "#mermaidAddBtn",
        note: "Missing a retry path.",
      });
    },
  },
  {
    id: "comment-chart",
    label: "Comment on a Chart.js chart",
    abilities: ["charts", "anchored-comments"],
    weight: 1.2,
    async run(page, ctx) {
      const ok = await commentOnBlock(page, ctx, {
        // A chart canvas is commented through the MEDIA affordance, the same one images use - the
        // runtime treats a canvas as media and files the comment as an image anchor.
        target: "#commentRoot figure.chart canvas, #commentRoot canvas",
        button: "#imageAddBtn",
        note: "Source for July?",
      });
      // A chart part only exists once Chart.js has drawn; fall back to the caption so the beat still
      // lands a comment on the chart rather than showing nothing at all.
      if (!ok) await commentOnText(page, ctx, "#commentRoot figcaption", "Source for July?");
    },
  },
  {
    id: "thread",
    label: "Threads: reply to a comment in the sidebar",
    abilities: ["threads"],
    weight: 1,
    async run(page, ctx) {
      const card = page.locator("#commentList .cm-card[data-cid]").first();
      if (!(await card.count())) return ctx.warn("no comment card to reply to");
      await ctx.scrollIntoView(card);
      const replyBtn = card.locator(".cm-reply-btn").first();
      if (!(await replyBtn.count())) return ctx.warn("this build has no reply affordance");
      await ctx.click(replyBtn);
      const box = card.locator(".cm-reply-compose textarea").first();
      if (!(await ctx.waitVisible(box, 1500))) return ctx.warn("the reply box never opened");
      await ctx.type(box, "Agreed - push it two weeks.", ctx.budgetMs * 0.45);
      const saveReply = card.locator(".cm-reply-save").first();
      if (await saveReply.count()) await ctx.click(saveReply);
      await ctx.holdRemaining(120);
    },
  },
  {
    id: "delete",
    label: "Delete a comment you no longer need",
    abilities: ["delete-comment"],
    weight: 0.9,
    async run(page, ctx) {
      const before = await cardCount(page);
      if (before < 2) return ctx.warn("not enough comments to demonstrate a delete");
      // Delete the LAST card, so the thread built above survives for the rest of the clip.
      const card = page.locator("#commentList .cm-card[data-cid]").last();
      await ctx.scrollIntoView(card);
      const del = card.locator('[data-act="del"]').first();
      if (!(await del.count())) return ctx.warn("this build has no delete affordance");
      await ctx.click(del);
      // The runtime confirms with a native dialog; the recorder accepts it (see recordReport).
      await ctx.settle(350);
      if ((await cardCount(page)) >= before) ctx.warn("the comment count did not drop after the delete");
      await ctx.holdRemaining(120);
    },
  },
  {
    id: "search",
    label: "Search and filter the review",
    abilities: ["comment-search"],
    weight: 0.8,
    async run(page, ctx) {
      const toggle = page.locator("#btnSearchToggle");
      if (!(await toggle.count())) return ctx.warn("no comment search in this build");
      await ctx.click(toggle);
      const input = page.locator("#cmSearchInput");
      if (!(await ctx.waitVisible(input, 1500))) return ctx.warn("the search box never opened");
      await ctx.type(input, "beds", ctx.budgetMs * 0.4);
      await ctx.holdRemaining(120);
    },
  },
  {
    id: "menu",
    label: "Export the review: portable HTML, Markdown, offline copy",
    abilities: ["toolbar-menu", "exports"],
    weight: 1,
    async run(page, ctx) {
      // The search panel takes the header over while it is open, so close it before reaching for a
      // menu, or this beat films nothing.
      const clear = page.locator("#cmSearchClear");
      if (await clear.count() && await clear.isVisible().catch(() => false)) await ctx.click(clear);
      await page.keyboard.press("Escape").catch(() => {});
      await ctx.settle(150);
      // Once a comment is saved the sidebar is open and the top toolbar collapses into it, so the
      // export affordance to film is the SIDEBAR's, with the toolbar menu as the fallback.
      for (const { button, menu } of [
        { button: "#btnSidebarExportMenu", menu: "#sidebarExportMenu" },
        { button: "#btnToolbarMenu", menu: "#toolbarMenu" },
      ]) {
        const btn = page.locator(button);
        if (!(await btn.count())) continue;
        if (!(await btn.isVisible().catch(() => false))) continue;
        await ctx.click(btn);
        if (await ctx.waitVisible(menu, 1200)) {
          // Hold the menu OPEN for what is left of the beat; closing it early hands the remaining
          // budget to the pacing sleep, which films a closed menu instead.
          await ctx.holdRemaining(150);
          await page.keyboard.press("Escape").catch(() => {});
          return;
        }
      }
      ctx.warn("no export or toolbar menu was reachable");
    },
  },
];
