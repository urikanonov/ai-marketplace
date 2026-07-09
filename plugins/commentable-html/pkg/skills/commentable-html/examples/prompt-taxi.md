# Example prompt - NYC Yellow Taxi 2014 Operations Report

This is a ready-to-reuse prompt that generates the companion `nyc-taxi-2014.html` in
this folder. Unlike the benign planning document in [`prompt.md`](./prompt.md), this
one is built on **real data**: the public NYC yellow taxi dataset on the Kusto help
cluster (`help.kusto.windows.net`, database `Samples`, table `nyc_taxi`, 165,114,361
rows for all of 2014). It exercises the same feature set (tables, a chart, KQL blocks
with "Run in Kusto" links, a code diff, a mermaid diagram) against numbers a reader can
reproduce.

The prompt below is written the way a real person would ask - it says *what* they want,
not *how* to build it. All of the build machinery (self-contained review layer, table
of contents, "Run in Kusto" links, the version-pinned offline-guarded chart loader,
mermaid handling, validation) is the skill's job, not the user's. See "What the skill
does for you" further down for the mapping.

## Prompt

> Build me a shareable, commentable status report on the 2014 New York City yellow taxi
> data. Call it **"NYC Yellow Taxi - 2014 Operations Status Report"**. The numbers
> should come from the public taxi dataset on the Kusto help cluster so anyone can check
> them. I want to open it in a browser, leave comments on any part of it, and hand it to
> other people so they can comment too, even offline.
>
> Cover these sections: an executive summary, monthly volume and revenue, fares and
> trip distance, the payment mix and tipping, passenger occupancy, demand by hour of
> day, data quality notes, and recommendations. Add a table of contents so I can jump
> around, and keep the writing tight with clear takeaways.
>
> Please also include:
> - A monthly table (trips, revenue, average fare, average distance) and a chart of
>   monthly trips.
> - Tables for the payment mix, passenger counts, and the busiest and quietest hours.
> - For each analysis, the actual query I can run myself against the taxi table.
> - A short before/after code change that adds a data-cleaning filter for bad fares.
> - A small diagram of how the report is produced, from the raw table to the tables I
>   see here.
>
> Call out anything in the data that could mislead a reader - I already know cash tips
> look wrong. Make it a single file I can email around.

## What the skill does for you

The user never has to know the plumbing. From the request above, the skill:

- Wraps the content in the self-contained commentable review layer (no CDN for the
  review UI) so any paragraph, list item, table cell, code block, chart, or diagram is
  selectable and commentable, online or offline.
- Generates the table of contents + heading `id`s and wires the scroll-spy side menu.
- Renders the monthly, payment, passenger, and hourly tables and the prose around them.
- Turns "a chart of monthly trips" into a Chart.js bar chart using the version-pinned,
  SRI-pinned, offline-guarded loader the skill's chart checks require, with a caption.
- Turns "the actual query I can run myself" into one KQL block per analysis against the
  public help cluster (`https://help.kusto.windows.net`, database `Samples`, table
  `nyc_taxi`), each with an adjacent "Run in Kusto" deep link that opens the exact query
  in Azure Data Explorer.
- Turns "a short before/after code change" into a unified diff rendered as a
  `<pre class="cmh-diff">` code-review block that drops non-positive fares.
- Turns "a small diagram of how the report is produced" into a mermaid flowchart that
  degrades to readable source text when offline.
- Surfaces the data-quality caveats (cash tips are not recorded, non-positive fares,
  noisy minor payment codes, the June distance outlier) as an explicit section so the
  headline numbers are not read naively.
- Validates the result with `python tools/validate.py` and fixes anything it flags.

## Build

This report has no images, so there is nothing to inline - it is already a single
self-contained file. Just validate it:

```
python tools/validate.py examples/nyc-taxi-2014.html
```

The committed `nyc-taxi-2014.html` opens as one portable document with no external
dependencies: the review layer and Chart.js are inlined, and the mermaid diagram
degrades to source text when opened offline.
