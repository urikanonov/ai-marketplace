# Example prompt - Planning a Community Garden

This is a ready-to-reuse prompt that generates the companion `community-garden.html`
in this folder. It is a benign, non-work planning document that exercises **every**
feature of the commentable-html skill, so it doubles as the walkthrough subject in
[`../TUTORIAL.md`](../TUTORIAL.md).

The prompt below is written the way a real person would ask - it says *what* they
want, not *how* to build it. All of the build machinery (self-contained review layer,
table of contents, "Run in Kusto" links, the version-pinned offline-guarded chart
loader, mermaid handling, inlined images, validation) is the skill's job, not the
user's. See "What the skill does for you" further down for the mapping.

## Prompt

> Make me a shareable, commentable web page for planning a community garden - call it
> **"Planning a Community Garden"**. I want to open it in a browser and be able to
> leave comments on any part of it, and I want to hand it to other people so they can
> comment too, even offline.
>
> Cover these sections: Overview, Goals & Success Criteria, Site Selection, Garden
> Layout, Planting Schedule, Budget, Timeline & Milestones, Risks & Mitigations, and
> Next Steps. Add a table of contents so I can jump around, and keep the writing
> polished with practical bullet points in each section.
>
> Please also include:
> - A budget table and a planting schedule table.
> - A chart of the estimated monthly watering needs.
> - A "should I plant today?" decision flowchart, and a timeline diagram for the
>   milestones.
> - A couple of simple pictures of the garden layout and the raised beds.
> - A little analysis of past severe weather by month so I can plan around frosts and
>   storms - and give me a way to run that query myself.
> - A small example of a code change that adjusts the watering schedule for rainfall.
>
> Make it a single file I can email to people.

## What the skill does for you

The user never has to know the plumbing. From the request above, the skill:

- Wraps the content in the self-contained commentable review layer (no CDN for the
  review UI) so any paragraph, list item, table cell, code block, chart, image, or
  diagram is selectable and commentable, online or offline.
- Generates the table of contents + heading `id`s and wires the scroll-spy side menu.
- Renders the tables and prose.
- Turns "a chart" into a Chart.js bar chart using the version-pinned, SRI-pinned,
  offline-guarded loader the skill's chart checks require, with a caption.
- Turns "a flowchart" and "a timeline" into two mermaid diagrams that degrade to
  readable source text when offline.
- Turns "a way to run that query myself" into a KQL block against the public Kusto
  help cluster (`https://help.kusto.windows.net`, database `Samples`, table
  `StormEvents`) with an adjacent "Run in Kusto" deep link.
- Turns "a small example of a code change" into a unified diff rendered as a
  `<pre class="cmh-diff">` code-review block.
- Stores the two pictures in `examples/images/` and inlines them as `data:` URIs at
  build time so the file stays a single portable document.
- Validates the result with `python tools/validate.py` and fixes anything it flags.

## Build

The images live in the skill folder and are inlined into the HTML at build time:

```
python tools/inline_images.py examples/community-garden.html --base examples --strict
python tools/validate.py examples/community-garden.html
```

The committed `community-garden.html` already has its images inlined, so it opens as a
single self-contained file with no dependency on the `images/` folder.
