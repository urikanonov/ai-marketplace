/* ---------- Help dialog ---------- */
// Static, trusted help content (no user input) describing every feature and control.
function showHelp(restoreEl) {
  if (document.querySelector(".cm-help-overlay")) return; // one at a time
  const prevFocus = restoreEl || document.activeElement;
  const overlay = document.createElement("div");
  overlay.className = "cm-modal-overlay cm-help-overlay cm-skip";
  const box = document.createElement("div");
  box.className = "cm-modal cm-help";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", "Commentable HTML help");
  const T = function (title, body, open) {
    return '<details class="cm-help-topic' + (open ? ' cm-help-default-open' : '') + '"' + (open ? ' open' : '') + '>'
      + '<summary>' + title + '</summary>'
      + '<div class="cm-help-topic-body">' + body + '</div>'
      + '</details>';
  };
  box.innerHTML =
    '<div class="cm-help-head">' +
      '<h2>' + CMH_ICON_SVG + ' Commentable HTML v' + CMH_VERSION + ' - Help</h2>' +
      '<button type="button" class="cm-help-close" title="Close help" aria-label="Close help">&times;</button>' +
    '</div>' +
    '<div class="cm-help-search">' +
      _cmIco("search", 15) +
      '<input type="search" class="cm-help-search-input" placeholder="Search help (e.g. export, diff, shortcuts)..." aria-label="Search help" autocomplete="off" spellcheck="false">' +
    '</div>' +
    '<div class="cm-help-body">' +
      T('Getting started',
        '<p>Commentable HTML turns any report into a review you can hand straight back to an AI agent. The loop has four steps:</p>' +
        '<ol>' +
          '<li><strong>Generate</strong> - ask an AI chat or terminal agent to produce the report or document as a commentable HTML file.</li>' +
          '<li><strong>Review</strong> - open the file in your browser and leave inline comments anywhere: text, code, tables, charts, diagrams, diffs or images.</li>' +
          '<li><strong>Hand back</strong> - click <strong>Copy all</strong> and paste the bundle back to the agent (or export the file and send it along).</li>' +
          '<li><strong>Refresh and repeat</strong> - the agent edits the source and marks your comments handled; reload the updated file and the addressed comments disappear. Repeat until none remain.</li>' +
        '</ol>' +
        '<figure class="cm-loop-figure">' +
          '<svg viewBox="0 0 640 250" role="img" aria-labelledby="cmLoopTitle cmLoopDesc">' +
            '<title id="cmLoopTitle">Commentable HTML self-review loop</title>' +
            '<desc id="cmLoopDesc">An AI agent generates a commentable HTML report; you review it and leave inline comments; you Copy all the comments back to the agent; the agent returns the updated file and you repeat until every comment is resolved.</desc>' +
            '<defs><marker id="cmLoopAh" markerWidth="10" markerHeight="10" refX="7.5" refY="4.5" orient="auto" markerUnits="userSpaceOnUse"><path class="cm-loop-head" d="M1,1 L8,4.5 L1,8 Z" /></marker></defs>' +
            '<rect class="cm-loop-bg" x="1" y="1" width="638" height="248" rx="16" />' +
            '<rect class="cm-loop-node" x="60" y="96" width="170" height="64" rx="12" />' +
            '<text class="cm-loop-title" x="145" y="133" text-anchor="middle" font-size="17" font-weight="600">AI agent</text>' +
            '<rect class="cm-loop-node" x="410" y="96" width="170" height="64" rx="12" />' +
            '<text class="cm-loop-title" x="495" y="133" text-anchor="middle" font-size="17" font-weight="600">You</text>' +
            '<text class="cm-loop-sub" x="320" y="106" text-anchor="middle" font-size="12.5">1. Generates HTML</text>' +
            '<line class="cm-loop-arrow" x1="236" y1="116" x2="402" y2="116" marker-end="url(#cmLoopAh)" />' +
            '<text class="cm-loop-sub" x="495" y="52" text-anchor="middle" font-size="12.5">2. Comment inline</text>' +
            '<path class="cm-loop-arrow" d="M468,95 C 456,60 534,60 522,95" marker-end="url(#cmLoopAh)" />' +
            '<line class="cm-loop-arrow" x1="404" y1="142" x2="238" y2="142" marker-end="url(#cmLoopAh)" />' +
            '<text class="cm-loop-sub" x="320" y="160" text-anchor="middle" font-size="12.5">3. Copy all back to the agent</text>' +
            '<path class="cm-loop-arrow" d="M160,175 C 250,235 380,235 470,161" marker-end="url(#cmLoopAh)" />' +
            '<text class="cm-loop-sub" x="320" y="242" text-anchor="middle" font-size="12.5">4. Reload and repeat</text>' +
          '</svg>' +
          '<figcaption>The self-review loop: an agent generates the file, you comment inline, Copy all hands the notes back, and you reload the updated file until none remain.</figcaption>' +
        '</figure>' +
        '<p><strong>Just want to leave a comment?</strong> If someone shared this file with you to review, you do not need an agent or an account - everything you need is in the file itself. Select any text and an <em>Add Comment</em> popup appears; type a note and Save. Your comments live in the panel on the right and persist in this browser. Hand your review back with <strong>Copy all</strong> (paste it to an agent) or <strong>Export as Portable</strong> (one file to send to a person, with your comments baked in).</p>' +
        '<p>Every topic below is collapsible; use the search box above to jump straight to an answer.</p>', true) +
      T('Leaving a comment',
        '<ul>' +
          '<li><strong>Text and code:</strong> select the words to comment on; the <em>Add Comment</em> popup appears (right-click a selection also works). Re-selecting the exact same range re-opens that comment; a different range starts a new one. Triple-click and block selections that spill onto section chrome still anchor to the real text.</li>' +
          '<li><strong>Headings:</strong> hover a heading and click the <em>Add Comment</em> button that appears just after the title.</li>' +
          '<li><strong>Tables:</strong> select text inside any cell like normal prose.</li>' +
          '<li><strong>Images:</strong> hover an image (or focus it and press <kbd>Enter</kbd>) and click <em>Add Comment</em> at its corner.</li>' +
          '<li><strong>Charts:</strong> a Chart.js canvas is commentable like an image.</li>' +
          '<li><strong>Mermaid diagrams:</strong> hover a node, edge label, gantt bar or sequence message and click <em>Add Comment</em>; hover an empty part of the diagram to comment on the whole diagram.</li>' +
          '<li><strong>Code-review diffs:</strong> select text inside a diff line for that snippet, or hover a line and click <em>Add Comment</em> to comment the whole line.</li>' +
          '<li><strong>Widgets and SVG nodes:</strong> in a document that marks parts with <code>data-cm-part</code> (a triage card, a diagram node), hover the part (or focus it and press <kbd>Enter</kbd>) and click <em>Add Comment</em>.</li>' +
          '<li><strong>Whole document:</strong> right-click an empty area and choose <em>Comment on document</em> for a note not tied to any element.</li>' +
        '</ul>') +
      T('Managing comments',
        '<ul>' +
          '<li><strong>Edit</strong> or <strong>Delete</strong> a comment from its card in the panel.</li>' +
          '<li><strong>Jump</strong> from a card to its highlight (collapsed sections auto-expand first).</li>' +
          '<li><strong>Sort</strong> the cards oldest-first or newest-first with the arrows, or click again for document order.</li>' +
          '<li><strong>Clear</strong> deletes every comment and always asks for confirmation first (Cancel is the default).</li>' +
        '</ul>') +
      T('Threads, replies and author names',
        '<ul>' +
          '<li><strong>Set your name:</strong> the <strong>Commenting as</strong> line in the panel shows the name attached to your comments. Click <em>set name</em> (or <em>change</em>) to enter a display name; it is remembered in this browser and applies to your future comments only - it never rewrites comments you already made. An author who generated the file can pre-fill it with <code>data-cm-author</code>.</li>' +
          '<li><strong>Author pills:</strong> each attributed comment and reply shows a colored author pill at the start of its note, so it is clear who wrote what; an unattributed comment shows no pill.</li>' +
          '<li><strong>Reply in a thread:</strong> click <strong>Reply</strong> on a comment card to open an empty editor <em>inline</em> in that card (Word-style, not a floating popup) - it is never prefilled with the quoted text. Your reply stacks under the original comment, oldest first. <kbd>Ctrl/Cmd</kbd>+<kbd>Enter</kbd> saves and <kbd>Esc</kbd> cancels. Replying for the first time without a name prompts you to set one.</li>' +
          '<li><strong>Edit or delete a reply</strong> from its own controls. Deleting the original comment removes the whole thread; deleting a single reply removes only that reply.</li>' +
          '<li><strong>Threads travel together:</strong> <strong>Copy all</strong>, the Markdown export, and the print appendix emit each thread as an initial comment followed by its labelled replies, so the agent reads the refinements in context.</li>' +
        '</ul>') +
      T('The panel and toolbar',
        '<ul>' +
          '<li><strong>Copy all</strong> copies every comment as a Markdown bundle to paste back to the agent.</li>' +
          '<li>The <strong>count bubble</strong> shows how many items still need attention: open comment threads plus any unresolved review-note and checklist changes (each top-level thread counts once, not its individual replies).</li>' +
          '<li><strong>Hide</strong> collapses the panel; a small floating toolbar stays to bring it back. The overflow <kbd>...</kbd> menu holds the export actions and <strong>Help &amp; About</strong>.</li>' +
          '<li>The <strong>Help &amp; About</strong> and <strong>Hide</strong> controls sit together at the top of the panel; <strong>Help &amp; About</strong> opens this dialog.</li>' +
        '</ul>') +
      T('Portable or Not portable',
        '<p>A bubble at the top of the panel shows whether this file is safe to share as-is:</p>' +
        '<ul>' +
          '<li><strong>Portable</strong> - self-contained: assets are embedded and every comment is embedded in the file, so a recipient sees exactly what you see.</li>' +
          '<li><strong>Offline</strong> - portable plus vendored mermaid and Chart.js embedded on demand, with remote loaders removed for zero-network review.</li>' +
          '<li><strong>Not portable</strong> - the file references external companion resources, or has comments that are not embedded yet, or has embedded comments you deleted this session that are still in the file until you re-export. Hover the bubble for the exact reason.</li>' +
        '</ul>' +
          '<p>Use <em>Export as Portable</em> to produce a portable copy. Use <em>Export Offline</em> when rendered mermaid diagrams and charts must also work with no network.</p>') +
      T('Exporting and sharing',
        '<ul>' +
          '<li><strong>Export as Portable</strong> downloads one self-contained HTML (named with a <code>-portable</code> suffix) with the comments, and any external assets, embedded so the review travels with the file.</li>' +
          '<li><strong>Export Offline</strong> downloads a <code>-offline</code> HTML copy that first builds the portable file, then inlines the vendored mermaid and Chart.js bundles only when the document uses them, with remote loaders removed.</li>' +
          '<li><strong>Export to Plain HTML</strong> downloads a copy with the commenting layer removed but all of your content and styling intact.</li>' +
          '<li><strong>Export to Markdown</strong> downloads a <code>.md</code> file; each block maps to a fixed Markdown form and your comments are appended as a section.</li>' +
          '<li><strong>Save as PDF</strong> opens the browser&#x27;s own print dialog (choose "Save as PDF", or print to paper). The printout hides the review UI, prints on a clean light theme, expands collapsed sections, and appends your current comments at the end. <kbd>Ctrl/Cmd+P</kbd> does the same thing.</li>' +
          '<li>In <strong>NonPortable mode</strong> the layer loads from companion files; <em>Export as Portable</em> rebuilds a single combined file.</li>' +
          '</ul>') +
      T('Sending comments to an agent',
        '<ul>' +
          '<li><strong>Copy all</strong> emits an ordered Markdown bundle with each comment\'s location, quoted text, and note, ending in a machine-readable <code>HANDLED_IDS_JSON</code> line.</li>' +
          '<li>Drag-and-drop changes to a commentable widget are captured as a <em>Widget layout changes</em> section in the bundle, so the agent can reformat the source to match.</li>' +
          '<li>On a triage board, click <strong>Reset moves</strong> on the board to undo every drag move at once, or click <strong>Reset changes</strong> on the board-moves comment card to revert to the layout as of that comment.</li>' +
          '<li>The agent addresses the comments and marks them handled in this same file; handled comments are pruned on the next load and never reappear in the bundle.</li>' +
        '</ul>') +
      T('Formatting your comment',
        '<p>Comment notes support lightweight rich text (WhatsApp / Office style). Type the markers, or select text and use the composer toolbar or a shortcut:</p>' +
        '<ul>' +
          '<li><code>**bold**</code> or <kbd>Ctrl</kbd>+<kbd>B</kbd> for <strong>bold</strong>.</li>' +
          '<li><code>*italic*</code> or <kbd>Ctrl</kbd>+<kbd>I</kbd> for <em>italic</em>.</li>' +
          '<li><code>__underline__</code> or <kbd>Ctrl</kbd>+<kbd>U</kbd> for <u>underline</u>.</li>' +
          '<li><code>~~strike~~</code> for <s>strikethrough</s>, and <code>`code`</code> for inline code.</li>' +
          '<li>Start a line with <code>- </code> for a bullet list.</li>' +
          '<li><code>[text](https://example.com)</code> or <kbd>Ctrl</kbd>+<kbd>K</kbd> makes a link; bare <code>http(s)://</code> links become clickable on their own.</li>' +
        '</ul>' +
        '<p>Only <code>http</code>, <code>https</code>, and <code>mailto</code> links are clickable; everything else is shown as plain text. Characters like <code>*</code>, <code>_</code>, <code>~</code>, and <code>`</code> may be read as formatting - the note is stored as the exact text you typed, so <strong>Copy all</strong> always hands the agent the raw markers.</p>') +
      T('Navigation',
        '<ul>' +
          '<li>On wide screens a <strong>section menu</strong> appears on the left, highlights the section you are reading, and collapses to <em>Navigation &raquo;</em>.</li>' +
          '<li>Every section title has a caret to <strong>collapse or expand</strong> that section; <strong>Expand All</strong> / <strong>Collapse All</strong> act on every section at once.</li>' +
          '<li><strong>Scroll to Top</strong> / <strong>Scroll to Bottom</strong> jump the document, and a small bubble shows your scroll position.</li>' +
        '</ul>') +
      T('Reading aids',
        '<ul>' +
          '<li><strong>Sortable tables:</strong> click a column header to sort (numeric-aware), cycling ascending, descending, original.</li>' +
          '<li><strong>Code, KQL and charts</strong> are framed for readability; every code block has an always-visible <em>Copy</em> button, and a KQL caption title copies the cluster name.</li>' +
          '<li><strong>Diffs</strong> are syntax-highlighted with a per-document <em>Syntax</em> toggle (green when on, red when off).</li>' +
          '<li>Long content wraps inside its box and never overflows.</li>' +
        '</ul>') +
      T('Tips and shortcuts',
        '<p>Faster ways to work once you know the basics:</p>' +
        '<ul>' +
          '<li><strong>Right-click</strong> a selection to add a comment without waiting for the popup.</li>' +
          '<li><strong>Re-select the exact same text</strong> to reopen its comment; select a different range to start a new one.</li>' +
          '<li><strong>Comment on several things at once:</strong> each <em>Add Comment</em> opens its own composer, so you can leave notes side by side. Drag a composer by its grip if it covers the text.</li>' +
          '<li><strong>Sort</strong> the panel oldest- or newest-first with the arrows; click the active arrow again to return to document order.</li>' +
          '<li><strong>Expand All</strong> / <strong>Collapse All</strong> open or close every section at once, and the per-document <em>Syntax</em> toggle turns diff highlighting on or off.</li>' +
          '<li><strong>Diffs</strong> switch between side-by-side and inline from the header button; your comments stay attached either way.</li>' +
          '<li>See <strong>Keyboard and accessibility</strong> for the keyboard shortcuts (<kbd>Ctrl</kbd>+<kbd>Enter</kbd> to save, <kbd>Esc</kbd> to close).</li>' +
        '</ul>') +
      T('Keyboard and accessibility',
        '<ul>' +
          '<li><kbd>Ctrl</kbd>+<kbd>Enter</kbd> saves a comment in the composer; <kbd>Esc</kbd> cancels a composer or dialog.</li>' +
          '<li>Images and diff lines are focusable with <kbd>Tab</kbd>; press <kbd>Enter</kbd> to reveal their <em>Add Comment</em> button.</li>' +
          '<li>Controls carry hover and focus tooltips; this dialog traps focus and restores it to the control that opened it.</li>' +
        '</ul>') +
      T('Managing storage',
        '<p>Everything you review is saved in this browser&#39;s storage, which every commentable-html document you open shares. If you review many documents from your file system, that space can fill up.</p>' +
        '<ul>' +
          '<li><strong>Manage storage</strong> (in the overflow <kbd>...</kbd> menu, or the sidebar&#39;s <em>Export</em> menu) lists every document&#39;s stored data with its size, and lets you delete another document&#39;s data to free space. Your own comments are never uploaded - this only clears local browser storage.</li>' +
          '<li>The window shows a <strong>pie chart</strong> of how the browser storage is used - <em>This document</em>, <em>Other commentable-html documents</em>, <em>Other</em> site data, and the <em>Free</em> headroom - above a per-document <strong>table</strong> (Document, Comments, Size, Share, Actions) whose <em>Share</em> column is each document&#39;s percentage of commentable-html storage. Expand a row&#39;s <strong>Show comments</strong> to browse and delete individual comments.</li>' +
          '<li>If a comment cannot be saved because storage is full, the <strong>Manage storage</strong> window opens automatically; delete another document&#39;s data and your comment is saved.</li>' +
          '<li>Comments are stored compressed, so far more reviews fit before the space runs out.</li>' +
        '</ul>') +
      T('Self-contained and privacy',
        '<p>Your comments are stored in this browser&#39;s <strong>localStorage</strong>, private to you: nothing is uploaded, there is no account, and no server ever sees them. They persist across reloads until you clear them, and they leave this browser only when you choose to - when you click <strong>Copy all</strong> or run an export.</p>' +
        '<p>Whether the review layer itself travels inside the file depends on the mode shown in the panel bubble: a <strong>Portable</strong> file has the review layer and your comments embedded, so it is safe to send as-is; a <strong>Not portable</strong> file references small companion resources instead. Use <em>Export as Portable</em> to bundle everything into one file. Optional host features (mermaid, Chart.js) can load from a CDN; if they cannot, mermaid stays readable source text and charts stay a blank canvas. Use <em>Export Offline</em> to inline the vendored rich-content libraries into a zero-network file.</p>') +
      '<div class="cm-help-about"><h3>About</h3>' +
        '<p>' + CMH_ICON_SVG + ' Commentable HTML <strong>v' + CMH_VERSION + '</strong>, authored by <a class="cm-brand-link" href="https://github.com/urikanonov" target="_blank" rel="noopener noreferrer">Uri Kanonov</a>.</p>' +
        '<ul>' +
          '<li><a href="https://urikanonov.github.io/ai-marketplace/commentable-html/" target="_blank" rel="noopener noreferrer">Website and live demo</a></li>' +
          '<li><a href="https://github.com/urikanonov/ai-marketplace" target="_blank" rel="noopener noreferrer">Source on GitHub</a></li>' +
          '<li><a href="https://github.com/urikanonov/ai-marketplace/blob/main/plugins/commentable-html/CHANGELOG.md" target="_blank" rel="noopener noreferrer">Changelog</a></li>' +
          '<li><a href="https://github.com/urikanonov/ai-marketplace/issues/new?template=plugin-issue.yml" target="_blank" rel="noopener noreferrer">Report an issue</a></li>' +
          '<li><a href="https://github.com/urikanonov/ai-marketplace/issues/new?template=feature-request.yml" target="_blank" rel="noopener noreferrer">Request a feature</a></li>' +
          '<li><a href="https://github.com/urikanonov/ai-marketplace/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener noreferrer">Contribute</a></li>' +
        '</ul>' +
      '</div>' +
      '<p class="cm-help-noresults" hidden>No help matches that search. Try another word.</p>' +
    '</div>';
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  function close() {
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    if (prevFocus && typeof prevFocus.focus === "function") prevFocus.focus();
  }
  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); return; }
    // Trap Tab inside the modal, cycling through its focusable elements (close button
    // and the About links) so focus cannot reach the page behind it.
    if (e.key === "Tab") {
      const f = Array.prototype.slice.call(box.querySelectorAll('button, a[href], input, summary'))
        .filter(function (el) { return el.offsetParent !== null || el === document.activeElement; });
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1], active = document.activeElement;
      if (e.shiftKey) {
        if (active === first || !box.contains(active)) { e.preventDefault(); last.focus(); }
      } else {
        if (active === last || !box.contains(active)) { e.preventDefault(); first.focus(); }
      }
    }
  }
  box.querySelector(".cm-help-close").addEventListener("click", close);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", onKey, true);
  // Live search: filter topics and their entries; open matches, hide the rest, and
  // reset to the default (first topic open) when the query is cleared.
  const search = box.querySelector(".cm-help-search-input");
  function helpFilter(q) {
    q = (q || "").trim().toLowerCase();
    let anyVisible = false;
    box.querySelectorAll(".cm-help-topic").forEach(function (t) {
      const entries = t.querySelectorAll(".cm-help-topic-body li, .cm-help-topic-body p");
      if (!q) {
        t.style.display = ""; t.open = t.classList.contains("cm-help-default-open");
        entries.forEach(function (el) { el.style.display = ""; });
        anyVisible = true; return;
      }
      const summaryMatch = (t.querySelector("summary").textContent || "").toLowerCase().indexOf(q) !== -1;
      let entryMatch = false;
      entries.forEach(function (el) {
        const hit = (el.textContent || "").toLowerCase().indexOf(q) !== -1;
        el.style.display = (summaryMatch || hit) ? "" : "none";
        if (hit) entryMatch = true;
      });
      const show = summaryMatch || entryMatch;
      t.style.display = show ? "" : "none";
      if (show) { t.open = true; anyVisible = true; }
    });
    const nores = box.querySelector(".cm-help-noresults");
    if (nores) nores.hidden = anyVisible;
  }
  if (search) search.addEventListener("input", function () { helpFilter(search.value); });
  (search || box.querySelector(".cm-help-close")).focus();
}
["btnHelp", "btnHelpTop"].forEach(function (id) {
  const b = document.getElementById(id);
  if (b) b.addEventListener("click", function () {
    const menu = document.getElementById("toolbarMenu");
    // The overflow menu (and btnHelpTop) is hidden before the modal opens, so restore
    // focus to the still-visible menu button rather than the now-hidden item.
    const restore = (id === "btnHelpTop") ? document.getElementById("btnToolbarMenu") : b;
    if (menu) menu.hidden = true;
    showHelp(restore);
  });
});
