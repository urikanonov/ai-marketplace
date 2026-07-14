/* ---------- Copy all + Clear all ---------- */
function buildCopyText() {
  const liveComments = withoutHandled(comments);
  const stateChanges = (typeof widgetStateChanges === "function") ? widgetStateChanges() : [];
  const clChanges = (typeof checklistChanges === "function") ? checklistChanges() : [];
  if (!liveComments.length && !stateChanges.length && !clChanges.length) return "";
  const sortKey = (c) => (c.anchorType === "document")
    ? -1
    : (c.anchorType === "mermaid")
    ? (1e12 + (c.diagramIndex || 0) * 1000)
    : (c.anchorType === "diff")
    ? (2e12 + (c.diffIndex || 0) * 1e6 + (parseInt(c.lineKey, 10) || 0))
    : (c.anchorType === "image")
    ? (3e12 + (c.imageIndex || 0))
    : (c.anchorType === "widget")
    ? (4e12 + _widgetOrderKey(c))
    : (typeof c.start === "number" ? c.start : 0);
  const sorted = [...liveComments].sort((a, b) => sortKey(a) - sortKey(b));
  const lines = [];
  // Structured one-line metadata fields must not carry newlines/tabs, or a poisoned
  // persisted comment could inject an extra line (e.g. a fake HANDLED_IDS_JSON:) into
  // the copied bundle. The free-text note and the fenced quote are emitted in their
  // own sections; the handled-id contract is anchored to the LAST HANDLED_IDS line.
  const oneLine = (s) => String(s == null ? "" : s).replace(/[\r\n\t]+/g, " ").trim();
  lines.push(`# ${oneLine(DOC_LABEL)} review (${sorted.length} comment${sorted.length === 1 ? "" : "s"})`);
  lines.push(`Source: ${oneLine(DOC_SOURCE)}`);
  lines.push("");
  sorted.forEach((c, i) => {
    const isMermaid = c.anchorType === "mermaid";
    const isDiff = c.anchorType === "diff";
    const isImage = c.anchorType === "image";
    const isWidget = c.anchorType === "widget";
    const isDocument = c.anchorType === "document";
    lines.push(`## Comment ${i + 1}${isMermaid ? " (mermaid)" : isDiff ? " (diff)" : isImage ? " (image)" : isWidget ? " (widget)" : isDocument ? " (document)" : ""}`);
    lines.push(`Id: ${c.id}`);
    lines.push(`When: ${formatTime(c.createdAt)}${c.updatedAt ? " (edited " + formatTime(c.updatedAt) + ")" : ""}`);
    if (c.headingPath && c.headingPath.length) {
      const path = c.headingPath.map(h => `H${Number(h.level) || 0} "${oneLine(h.text)}"`).join(" > ");
      lines.push(`Where: ${path}`);
    } else if (c.section) {
      lines.push(`Section: ${oneLine(c.section)}`);
    }
    if (isMermaid) {
      if (c.nodeKey === "__diagram__") {
        lines.push(`Anchor: mermaid diagram #${(c.diagramIndex || 0) + 1} (whole diagram)`);
      } else {
        lines.push(`Anchor: mermaid diagram #${(c.diagramIndex || 0) + 1}, node "${oneLine(c.nodeKey)}"`);
      }
      if (c.nodeLabel && c.nodeLabel !== c.nodeKey) {
        lines.push(`Node label: ${oneLine(c.nodeLabel)}`);
      }
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else if (isDiff) {
      const loc = c.lineType === "add" ? "added line " + (c.newNo != null ? c.newNo : "?")
        : c.lineType === "del" ? "removed line " + (c.oldNo != null ? c.oldNo : "?")
        : "context line " + (c.newNo != null ? c.newNo : (c.oldNo != null ? c.oldNo : "?"));
      lines.push(`Anchor: diff${c.diffLabel ? " " + oneLine(c.diffLabel) : ""}, ${loc}`);
      lines.push("");
      lines.push("Diff line:");
      // Fence longer than any backtick run in the line so a diff line that itself
      // contains ``` cannot break out of the fenced block into the copied bundle.
      let dMaxRun = 0;
      const dRunRe = /`+/g;
      let dm;
      while ((dm = dRunRe.exec(c.quote)) !== null) {
        if (dm[0].length > dMaxRun) dMaxRun = dm[0].length;
      }
      const dFence = "`".repeat(Math.max(3, dMaxRun + 1));
      lines.push(dFence + "diff");
      c.quote.split(/\r?\n/).forEach(l => lines.push(l));
      lines.push(dFence);
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else if (isImage) {
      const rawSrc = oneLine(c.imageSrc);
      const sSrc = rawSrc.length > 100 ? rawSrc.slice(0, 100) + "..." : rawSrc;
      const mediaWord = c.imageKind === "chart" ? "chart" : "image";
      lines.push(`Anchor: ${mediaWord} #${(c.imageIndex || 0) + 1}${sSrc ? " (" + sSrc + ")" : ""}`);
      if (c.imageAlt) lines.push(`Alt: ${oneLine(c.imageAlt)}`);
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else if (isWidget) {
      lines.push(`Anchor: widget "${oneLine(c.widget)}", part "${oneLine(c.partLabel || c.part)}"${c.slot ? " (in " + oneLine(c.slot) + ")" : ""}`);
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else if (isDocument) {
      lines.push("Anchor: document-wide (not tied to a specific element)");
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else {
      const pin = [];
      if (c.isCode) {
        pin.push(c.codeLanguage ? `code (${oneLine(c.codeLanguage)})` : "code block");
      } else if (c.blockTag) {
        pin.push(`<${oneLine(c.blockTag)}>`);
      }
      if (Number(c.occurrenceTotal) > 1) pin.push(`match ${Number(c.occurrence) || 0} of ${Number(c.occurrenceTotal) || 0} in section`);
      else if (Number(c.occurrenceTotal) === 1) pin.push("unique match in section");
      if (pin.length) lines.push(`Pinpoint: ${pin.join(" - ")}`);
      lines.push(`Offsets: [${Number(c.start) || 0}, ${Number(c.end) || 0}]`);
      lines.push("");
      lines.push("Quoted text:");
      if (c.isCode) {
        // Emit a fenced code block so newlines and indentation survive paste-back into
        // markdown-aware editors (ADO PR comments, GitHub issues, etc.). Choose a fence
        // longer than any backtick run in the quote so a literal ``` line inside the
        // selection cannot prematurely close the block.
        let maxRun = 0;
        const runRe = /`+/g;
        let mm;
        while ((mm = runRe.exec(c.quote)) !== null) {
          if (mm[0].length > maxRun) maxRun = mm[0].length;
        }
        const fenceLen = Math.max(3, maxRun + 1);
        const fenceBar = "`".repeat(fenceLen);
        lines.push(fenceBar + oneLine(c.codeLanguage));
        c.quote.split(/\r?\n/).forEach(line => lines.push(line));
        lines.push(fenceBar);
      } else {
        c.quote.split(/\r?\n/).forEach(line => lines.push("> " + line));
      }
      // "In context" only makes sense for prose. Skip it for code blocks - the fenced
      // quote already preserves the structure that matters.
      if (!c.isCode && (c.before || c.after)) {
        lines.push("");
        lines.push("In context:");
        const ctxLine = (c.before || "") + '"' + c.quote.replace(/\s+/g, " ") + '"' + (c.after || "");
        ctxLine.split(/\r?\n/).forEach(line => lines.push("> " + line));
      }
      if (c.blockText && !c.isCode) {
        lines.push("");
        lines.push(`Containing <${oneLine(c.blockTag) || "block"}>:`);
        c.blockText.split(/\r?\n/).forEach(line => lines.push("> " + line));
      }
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    }
    lines.push("");
    lines.push("---");
    lines.push("");
  });
  if (stateChanges.length) {
    lines.push("## Widget layout changes");
    lines.push("Drag/drop moves not yet saved into the file. Reformat the source to match this layout, then re-export.");
    lines.push("");
    stateChanges.forEach((ch) => lines.push(`- widget "${oneLine(ch.widget)}": "${oneLine(ch.label || ch.part)}" moved from ${oneLine(ch.from)} to ${oneLine(ch.to)}`));
  }
  if (clChanges.length) {
    const byCl = new Map();
    clChanges.forEach((ch) => {
      if (!byCl.has(ch.checklist)) byCl.set(ch.checklist, { label: ch.checklistLabel, items: [] });
      byCl.get(ch.checklist).items.push(ch);
    });
    const stateMap = {};
    byCl.forEach((info, cid) => {
      const label = (info.label && info.label !== cid) ? ` (${oneLine(info.label)})` : "";
      lines.push(`## Checklist "${oneLine(cid)}"${label}`);
      lines.push("Apply with tools/checklist_apply.py, or set data-cmh-state on each item.");
      lines.push("");
      info.items.forEach((ch) => {
        lines.push(`- [${oneLine(ch.key)}] "${oneLine(ch.label || ch.key)}": ${oneLine(ch.from)} -> ${oneLine(ch.to)}`);
        if (!stateMap[cid]) stateMap[cid] = {};
        stateMap[cid][ch.key] = ch.to;
      });
      lines.push("");
    });
    lines.push("CHECKLIST_STATE_JSON: " + JSON.stringify(stateMap));
  }
  lines.push("");
  lines.push("---");
  lines.push("");
  lines.push("AGENT INSTRUCTIONS:");
  lines.push("After acting on the comments above, append every processed id");
  lines.push("to the JSON array inside the `<script id=\"handledCommentIds\">`");
  lines.push(`block of \`${DOC_SOURCE}\`. Existing entries must be preserved.`);
  lines.push("On the next page load those comments are pruned from");
  lines.push("localStorage and their highlights are dropped.");
  lines.push("");
  lines.push("HANDLED_IDS_JSON: " + JSON.stringify(sorted.map(c => c.id)));
  return lines.join("\n").trim() + "\n";
}
const CMH_COPY_ALL_TITLES = {
  btnCopyAll: "Copy all comments to the clipboard as a Markdown bundle for pasting back to the agent",
  btnCopyAllTop: "Copy all comments to the clipboard for pasting back to the agent",
};
function _copyAllState() {
  const live = withoutHandled(comments);
  const changes = (typeof widgetStateChanges === "function") ? widgetStateChanges() : [];
  const clCh = (typeof checklistChanges === "function") ? checklistChanges() : [];
  return { live, changes, clCh, hasContent: !!(live.length || changes.length || clCh.length) };
}
function _setCopyAllTip(btn, text) {
  if (btn.hasAttribute("title") || !btn.hasAttribute("data-cmh-tip")) btn.setAttribute("title", text);
  else btn.setAttribute("data-cmh-tip", text);
}
function updateCopyAllState() {
  const disabled = !_copyAllState().hasContent;
  Object.keys(CMH_COPY_ALL_TITLES).forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.setAttribute("aria-disabled", disabled ? "true" : "false");
    btn.classList.toggle("cm-copy-disabled", disabled);
    _setCopyAllTip(btn, disabled ? "No comments to copy" : CMH_COPY_ALL_TITLES[id]);
  });
}
const _cmRenderCommentsForCopyAll = renderComments;
renderComments = function () {
  const result = _cmRenderCommentsForCopyAll.apply(this, arguments);
  updateCopyAllState();
  return result;
};
async function copyAll() {
  const state = _copyAllState();
  if (!state.hasContent) { updateCopyAllState(); showToast("No comments to copy."); return; }
  const live = state.live;
  const changes = state.changes;
  const n = live.length;
  const text = buildCopyText();
  let copied = false;
  try { await navigator.clipboard.writeText(text); copied = true; }
  catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.left = "-9999px";
    document.body.appendChild(ta); ta.select();
    try { copied = document.execCommand("copy"); } catch (err) { copied = false; }
    document.body.removeChild(ta);
    if (!copied) {
      window.prompt("Automatic copy was blocked. Copy the text below manually, then dismiss:", text);
      // Do NOT claim success: the reviewer may have cancelled the prompt without copying.
      showToast("Automatic copy was blocked - the bundle was shown for manual copy.",
        { alert: true, duration: 6000 });
      return;
    }
  }
  if (copied) {
    const extra = changes.length ? ` plus ${changes.length} layout change${changes.length === 1 ? "" : "s"}` : "";
    showToast(`Copied ${n} comment${n === 1 ? "" : "s"}${extra}. They stay here until the agent marks them handled in the HTML.`);
  }
}
document.getElementById("btnCopyAll").addEventListener("click", copyAll);
document.getElementById("btnCopyAllTop").addEventListener("click", copyAll);
