/* ---------- Comment search / filter ---------- */
// A single search field in the sidebar header filters the rendered comment cards to only
// those whose text matches the query case-insensitively, and shows a "shown / total" count.
// The query is module-level so it survives re-renders: renderComments() re-applies it at the
// end of every render, so adding, editing, or sorting comments keeps the active filter.
let commentSearchQuery = "";

function _normalizeCommentSearchText(value) {
  return String(value == null ? "" : value).normalize("NFC").toLocaleLowerCase();
}

// The reviewer's own note text - what THEY wrote - is the only thing the search filters on. The
// quoted anchor content, section path, and pin are deliberately excluded so a query matches by the
// comment text, not the surrounding quote; chrome (action-button labels, the meta line) is likewise
// never matched.
function _commentCardHaystack(card) {
  let text = "";
  // Prefer the hidden raw-source element(s) so the search matches the note's markdown markers and
  // link URLs (the visible .note renders those away). A threaded card has one per entry (root +
  // replies); fall back to .note for any card without a raw element.
  const raws = card.querySelectorAll(".cmh-note-raw");
  if (raws.length) {
    raws.forEach((el) => { text += " " + (el.textContent || ""); });
  } else {
    card.querySelectorAll(".note").forEach((el) => {
      text += " " + (el.textContent || "");
    });
  }
  return _normalizeCommentSearchText(text);
}

function _toggleSearchEmptyNote(show) {
  if (!listEl) return;
  let note = listEl.querySelector(".cm-search-empty");
  if (show) {
    if (!note) {
      note = document.createElement("div");
      note.className = "cm-empty cm-search-empty";
      note.innerHTML = "<p>No comments match your search.</p>";
      listEl.appendChild(note);
    }
    note.hidden = false;
  } else if (note) {
    note.hidden = true;
  }
}

// Re-apply the active query to the currently-rendered cards. Called by the input handler and
// at the end of renderComments(). With no comments the whole row is hidden (nothing to search).
function applyCommentSearch() {
  const row = document.querySelector(".head-search");
  const countEl = document.getElementById("cmSearchCount");
  const clearBtn = document.getElementById("cmSearchClear");
  const total = (typeof threadRoots === "function")
    ? threadRoots(comments).length
    : (Array.isArray(comments) ? comments.length : 0);
  const noteCards = listEl ? listEl.querySelectorAll(".cm-card-note") : [];
  if (row) row.hidden = total === 0 && noteCards.length === 0;
  if (total === 0 && noteCards.length === 0) {
    _toggleSearchEmptyNote(false);
    return;
  }
  const q = _normalizeCommentSearchText(commentSearchQuery.trim());
  if (clearBtn) clearBtn.hidden = q === "";
  const cards = listEl ? listEl.querySelectorAll(".cm-card[data-cid]") : [];
  let shown = 0;
  cards.forEach((card) => {
    const match = q === "" || _commentCardHaystack(card).indexOf(q) !== -1;
    card.classList.toggle("cm-hidden", !match);
    if (match) shown++;
  });
  // A widget layout-change card and a checklist card are not comments; while a search is
  // active they would be noise, so hide them. An empty query restores them. Notes ARE
  // searchable: a note card filters by its label and text like a comment card.
  let noteShown = 0;
  if (listEl) {
    listEl.querySelectorAll(".cm-card-state, .cm-card-checklist").forEach((c) => {
      c.classList.toggle("cm-hidden", q !== "");
    });
    noteCards.forEach((c) => {
      const hay = _normalizeCommentSearchText((c.querySelector(".cmh-note-search") || {}).textContent || "");
      const match = q === "" || hay.indexOf(q) !== -1;
      c.classList.toggle("cm-hidden", !match);
      if (q !== "" && match) noteShown++;
    });
  }
  if (countEl) {
    const totalItems = total + noteCards.length;
    countEl.textContent = (q === "" ? totalItems : (shown + noteShown)) + " / " + totalItems;
    countEl.hidden = false;
  }
  _toggleSearchEmptyNote(q !== "" && shown === 0 && noteShown === 0);
}

function setupCommentSearch() {
  const input = document.getElementById("cmSearchInput");
  const clearBtn = document.getElementById("cmSearchClear");
  if (!input) return;
  input.addEventListener("input", () => {
    commentSearchQuery = input.value || "";
    applyCommentSearch();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && input.value) {
      input.value = "";
      commentSearchQuery = "";
      applyCommentSearch();
      e.stopPropagation();
    }
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      input.value = "";
      commentSearchQuery = "";
      applyCommentSearch();
      input.focus();
    });
  }
  applyCommentSearch();
}
