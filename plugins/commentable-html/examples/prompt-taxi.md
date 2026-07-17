# Example prompt - NYC Yellow Taxi 2014 Operations Report

A minimal prompt that produces the companion `report-taxi.html`. Unlike the garden
plan, this one uses real public data (the NYC yellow taxi dataset on the Kusto help
cluster), so the numbers are reproducible.

## Prompt

> Make me a commentable HTML report on the 2014 New York City yellow taxi data, using
> the public dataset so I can check the numbers. Cover: executive summary, monthly
> volume and revenue, fares and trip distance, payment mix and tipping, passenger
> occupancy, demand by hour, data-quality notes, and recommendations.

## What you get

From that one line, the skill produces a single self-contained HTML file you can open
in any browser and share:

- Every part is commentable: text, tables, charts, code, and diagrams.
- It writes the sections with a table of contents, adds tables and charts, and includes
  the query behind each figure with a link to run it yourself.
- It flags anything in the data that could mislead (for example, cash tips are not
  recorded), and Copy all hands your comments back to the agent.