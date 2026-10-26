/* ---------- Discussions: questions by default, explicit edit commands ---------- */
const CMH_REQUEST_VERSION_RE = /^r[a-f0-9]{32}$/;
let _cmhDiscussionBefore = null;

function cmhRandomReviewId(prefix) {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return prefix + Array.from(bytes, function (b) { return b.toString(16).padStart(2, "0"); }).join("");
}
function cmhDiscussionRoot(c, arr) {
  if (!c) return null;
  const parent = c.parentId ? (arr || comments).find(function (r) { return r.id === c.parentId && !r.parentId; }) : c;
  return parent && parent.threadType === "discussion" ? parent : null;
}
function cmhDiscussionIntent(c) {
  return c && c.intent === "command" ? "command" : "question";
}
function cmhDiscussionSignature(c) {
  return JSON.stringify([c.note, cmhDiscussionIntent(c), c.role || "human"]);
}
function cmhInitDiscussionTracking() {
  _cmhDiscussionBefore = new Map();
  comments.forEach(function (c) {
    if (!cmhDiscussionRoot(c) || c.role === "assistant") return;
    c.intent = cmhDiscussionIntent(c);
    if (!CMH_REQUEST_VERSION_RE.test(c.requestVersion || "")) c.requestVersion = cmhRandomReviewId("r");
    _cmhDiscussionBefore.set(c.id, cmhDiscussionSignature(c));
  });
}
function cmhPrepareDiscussionSave() {
  if (!_cmhDiscussionBefore) return;
  const next = new Map();
  comments.forEach(function (c) {
    if (!cmhDiscussionRoot(c) || c.role === "assistant") return;
    c.intent = cmhDiscussionIntent(c);
    const signature = cmhDiscussionSignature(c);
    if (!CMH_REQUEST_VERSION_RE.test(c.requestVersion || "")
        || (_cmhDiscussionBefore.has(c.id) && _cmhDiscussionBefore.get(c.id) !== signature)) {
      c.requestVersion = cmhRandomReviewId("r");
    }
    next.set(c.id, signature);
  });
  _cmhDiscussionBefore = next;
}
function cmhStampDiscussion(c, purpose) {
  if (!c || !purpose) return;
  if (!c.parentId) {
    if (purpose === "discussion") {
      c.threadType = "discussion";
      c.intent = "question";
    }
  } else if (cmhDiscussionRoot(c)) {
    c.intent = purpose === "command" ? "command" : "question";
  }
}
function cmhPendingDiscussion(root, arr) {
  if (!root || root.threadType !== "discussion") return [];
  const messages = [root].concat(repliesOf(root.id, arr || comments));
  const latestCommand = messages.slice().reverse().find(function (m) {
    return m.role !== "assistant" && cmhDiscussionIntent(m) === "command";
  });
  const done = new Set();
  messages.forEach(function (m) {
    if (m.role !== "assistant" || (m.intent !== "answer" && m.intent !== "applied")) return;
    if (!Array.isArray(m.respondsTo)) return;
    m.respondsTo.forEach(function (ref) {
      if (!ref || !SAFE_ID_RE.test(ref.id || "") || !CMH_REQUEST_VERSION_RE.test(ref.version || "")) return;
      done.add(ref.id + "@" + ref.version + ":" + (m.intent === "applied" ? "command" : "question"));
    });
  });
  return messages.filter(function (m) {
    if (m.role === "assistant") return false;
    const intent = cmhDiscussionIntent(m);
    if (intent === "command" && latestCommand && latestCommand.id !== m.id) return false;
    return !done.has(m.id + "@" + m.requestVersion + ":" + intent);
  }).map(function (m) {
    return { threadId: root.id, id: m.id, intent: cmhDiscussionIntent(m), version: m.requestVersion };
  });
}
function cmhLatestHumanDiscussionIntent(root, arr) {
  if (!root || root.threadType !== "discussion") return "question";
  const messages = [root].concat(repliesOf(root.id, arr || comments));
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role !== "assistant") return cmhDiscussionIntent(messages[i]);
  }
  return "question";
}
function cmhDiscussionDocumentMetadata(roots) {
  const selected = new Set(roots.map(function (c) { return c.id; }));
  const embedded = getEmbeddedComments();
  const baseRoots = new Set(embedded.filter(function (c) {
    return c && !c.parentId && c.threadType === "discussion" && selected.has(c.id);
  }).map(function (c) { return c.id; }));
  const rows = embedded.filter(function (c) {
    return c && (baseRoots.has(c.id) || baseRoots.has(c.parentId));
  }).map(function (c) {
    return [c.id, c.parentId || "", c.requestVersion || "", c.updatedAt || c.createdAt,
      c.role || "", c.intent || ""];
  }).sort(function (a, b) { return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0; });
  const block = cmhReadLayerBlock("embeddedComments");
  return { key: COMMENT_KEY, baseRevision: block ? block.getAttribute("data-cmh-review-revision") || "" : "",
    baseSnapshot: rows };
}
function cmhDiscussionStatusHtml(c) {
  if (c.threadType !== "discussion") return "";
  const pending = cmhPendingDiscussion(c);
  const status = pending.some(function (r) { return r.intent === "command"; })
    ? { label: "Edit requested", icon: "&#x270f;&#xfe0f;" }
    : pending.length ? { label: "Awaiting answer", icon: "&#x23f3;" }
      : { label: "Answered", icon: "&#x2705;" };
  const handoff = pending.some(function (r) { return r.intent === "question"; })
    ? '<div class="cm-discussion-handoff" title="Paste Copy all to the AI or send an exported HTML with the discussion embedded. Copy and export are not an AI read receipt; a matching answer clears this indicator."><span class="cm-discussion-handoff-icon" aria-hidden="true">&#x1f4e4;</span> <span class="cm-discussion-handoff-label">Needs owner handoff / AI reply</span></div>'
    : "";
  return '<div class="cm-discussion-status"><span class="cm-discussion-status-icon" aria-hidden="true">'
    + status.icon + '</span> <span class="cm-discussion-status-label">' + status.label + '</span></div>' + handoff;
}
function cmhMessageKind(c, root) {
  if (!root || root.threadType !== "discussion") return "";
  if (c.role === "assistant") return c.intent === "applied" ? "AI edit acknowledgement" : "AI answer";
  return cmhDiscussionIntent(c) === "command" ? "Edit command" : "Question";
}
function cmhMessageKindHtml(c, root) {
  const kind = cmhMessageKind(c, root);
  return kind ? '<span class="cm-message-kind">' + kind + '</span>' : "";
}
function cmhPurposeControl(label, value, reply) {
  const wrap = document.createElement("label");
  wrap.className = "cm-purpose-control";
  const caption = document.createElement("span");
  caption.textContent = label;
  const select = document.createElement("select");
  select.setAttribute("aria-label", label);
  if (reply) {
    select.add(new Option("Ask AI", "question"));
    select.add(new Option("Request edit", "command"));
  } else {
    select.add(new Option("Request edit", "edit"));
    select.add(new Option("Ask AI", "discussion"));
  }
  select.value = value;
  wrap.append(caption, select);
  return wrap;
}
function cmhConfigureComposerPurpose(el, mode, c) {
  const root = cmhDiscussionRoot(c);
  let control;
  if (mode === "new-reply" && root) {
    control = cmhPurposeControl("Reply purpose", cmhLatestHumanDiscussionIntent(root), true);
  } else if (mode === "edit" && c && c.parentId && root && c.role !== "assistant") {
    control = cmhPurposeControl("Reply purpose", cmhDiscussionIntent(c), true);
  } else if (String(mode || "").indexOf("new") === 0 && mode !== "new-reply") {
    control = cmhPurposeControl("Comment purpose", "edit", false);
  }
  if (control) el.querySelector(".quote").insertAdjacentElement("afterend", control);
}
