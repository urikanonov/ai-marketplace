# Kusto query blocks


## Kusto query blocks (Run in Azure Data Explorer deep link)

Whenever a report embeds a Kusto (KQL) query, render the query as a normal commentable code block **and place a "Run in Azure Data Explorer" deep link right next to it**. The report is static and self-contained, so the link is the reader's one-click path from "here is the query" to opening it, pre-loaded and ready to run, in the Azure Data Explorer web UX. This is a required convention: a framed KQL figure (`figure.cmh-kql`) **MUST** carry a run link built with `tools/kusto_link.py`. `validate.py` enforces this - a framed KQL figure with no `cmh-kql-run` link is a hard validation **error** (not a warning), so the document does not pass validation until the link is added.

**Escape hatch for illustrative queries.** The rule applies only to framed `figure.cmh-kql` cards. If a query is purely illustrative - a syntax example with no real cluster/database to run against - render it as a plain `<pre><code class="language-kusto">...</code></pre>` code block instead of a framed figure. A bare `<pre>` is not a `figure.cmh-kql`, so it is exempt from the run-link rule (still HTML-escape the query text). Reserve the framed figure for queries that target a reachable cluster/database.

> **Data safety:** the query text round-trips inside the URL (gzip + base64 is compression, **not** encryption - it is trivially reversible). Anyone with the link recovers the full query, and following it sends that text to a live Microsoft site and into browser history. **Never embed secrets, tokens, connection strings, or customer PII as literals** in a query that gets a run link - parameterize or redact them first, or omit the run link for that query.

### Building the link

Use the helper (deterministic, so the same query always yields the same URL; line endings are normalized so a CRLF `.kql` file and an LF query produce the same link):

```bash
python tools/kusto_link.py <cluster> <database> "<query>" # query as an argument
python tools/kusto_link.py <cluster> <database> < query.kql # or piped on stdin
```

It emits `https://dataexplorer.azure.com/clusters/<cluster>/databases/<database>?query=<payload>`, where `<payload>` is the query **gzip-compressed (mtime pinned to 0), base64-encoded, then percent-encoded** - the same scheme the Kusto web UX uses for share links. `<cluster>` may be a bare host (`help.kusto.windows.net`) or a full `https://...` URL; the helper validates it is a plain DNS host and rejects anything with quotes/spaces/URL-structural characters (which would otherwise break the `href`). Very large queries can exceed browser URL limits (the helper warns past ~8k chars) - trim or parameterize them.

**Choosing cluster + database:** target the cluster/database where the query's tables and functions actually resolve. If the query already pins its sources with inline `cluster('...').database('...')` references, those win at runtime, so the URL cluster/db only sets the initial connection - pick a **reachable** cluster (ideally the one named in the query), not a placeholder, or ADE lands on a connection error before the reader sees the query. If the query calls a bare table or function (no inline `cluster()`/`database()`), the URL cluster/db **must** be where that function/table lives, or the query will not resolve.

### Building the whole block

The easiest path is the one-call helper, which emits the complete figure - caption, "Run in Azure Data Explorer" link (via `kusto_link.py`), and syntax-highlighted code:

```bash
python tools/kql_highlight.py <cluster> <database> "<title>" "<query>" # full figure
python tools/kql_highlight.py <cluster> <database> "<title>" < query.kql # query on stdin
python tools/kql_highlight.py --code-only "<query>" # just the <pre><code>
```

### Markup

```html
<figure class="cmh-kql">
 <figcaption class="cm-skip cmh-kql-cap">
 <button type="button" class="cmh-kql-title cmh-kql-cluster cm-skip"
 data-cmh-copy="help.kusto.windows.net"
 title="Copy cluster name (help.kusto.windows.net) to the clipboard">help / Samples</button>
 <a class="cmh-kql-run" href="https://dataexplorer.azure.com/clusters/help.kusto.windows.net/databases/Samples?query=H4sIAAAA..."
 target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer &#9654;</a>
 </figcaption>
 <pre><code class="language-kusto"><span class="cmh-kql-kw">StormEvents</span> <span class="cmh-kql-op">|</span> <span class="cmh-kql-kw">where</span> State <span class="cmh-kql-op">==</span> <span class="cmh-kql-str">"TEXAS"</span></code></pre>
</figure>
```

- The **query** stays a normal `<pre><code class="language-kusto">` block - commentable, so a reviewer can select and comment on it. `kql_highlight.py` escapes the query and wraps tokens in `cmh-kql-*` spans; the spans only add structure, so `textContent` (what commenting and the Copy bundle read) is the exact raw query. If you write a KQL block by hand, still HTML-escape the query text (`<` as `&lt;`, `>` as `&gt;`, `&` as `&amp;`) like a diff block.
- **Syntax highlighting** is applied at author time (baked-in spans), not by a runtime script, so it never has to coexist with the comment layer. Token classes: `cmh-kql-kw` (keyword), `cmh-kql-fn` (function), `cmh-kql-str` (string), `cmh-kql-num` (number), `cmh-kql-com` (comment), `cmh-kql-op` (operator / pipe).
- The **caption and the run link are `cm-skip` chrome** (the `<figcaption>` carries `cm-skip`), so the "Run in Azure Data Explorer" affordance is not itself selectable or commentable.
- The **caption title is the cluster-copy affordance**. It carries `data-cmh-copy` with the cluster name and copies it on click. Do not add a separate cluster chip.
- Always set `target="_blank" rel="noopener noreferrer"` on the link. `validate.py` warns if a `cmh-kql-run` link is not an `https://dataexplorer.azure.com/` origin or is missing `rel="noopener"`, and it **errors** if a framed `figure.cmh-kql` has no `cmh-kql-run` link at all (the run link is mandatory on a framed figure; use a plain `<pre>` for an illustrative query with no real cluster).
- The link is a plain external `href`: it needs no runtime JS and degrades gracefully when connectivity is unavailable (it simply cannot be followed), so it does not affect the review layer itself.

### Styling

The layer ships the styling, so **no per-report CSS is needed**: `figure.cmh-kql` renders as one framed card (bordered, rounded, with the caption bar and the code sharing the frame), and the `cmh-kql-*` token spans are colored (primer-style, with dark-theme variants). Both are scoped to `#commentRoot` and carry no `!important`, so a host stylesheet can still override them.
