/* ---------- Comment search / filter ---------- */
// A single search field in the sidebar header filters the rendered comment cards to only
// those whose text matches the query case-insensitively, and shows a "shown / total" count.
// The query is module-level so it survives re-renders: renderComments() re-applies it at the
// end of every render, so adding, editing, or sorting comments keeps the active filter.
let commentSearchQuery = "";

// The substantive, reader-facing text of a comment card: the reviewer's note plus the quoted
// content, section path, and pin. Action-button labels (jump/edit/delete) and the meta line
// are excluded so a query never matches chrome.
function _commentCardHaystack(card) {
  let text = "";
  card.querySelectorAll(".note, .quote, .section, .pin").forEach((el) => {
    text += " " + (el.textContent || "");
  });
  return text.toLowerCase();
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
  const total = Array.isArray(comments) ? comments.length : 0;
  if (row) row.hidden = total === 0;
  if (total === 0) {
    _toggleSearchEmptyNote(false);
    return;
  }
  const q = commentSearchQuery.trim().toLowerCase();
  if (clearBtn) clearBtn.hidden = q === "";
  const cards = listEl ? listEl.querySelectorAll(".cm-card[data-cid]") : [];
  let shown = 0;
  cards.forEach((card) => {
    const match = q === "" || _commentCardHaystack(card).indexOf(q) !== -1;
    card.classList.toggle("cm-hidden", !match);
    if (match) shown++;
  });
  // A widget layout-change card and a checklist card are not comments; while a search is
  // active they would be noise, so hide them. An empty query restores them.
  if (listEl) {
    listEl.querySelectorAll(".cm-card-state, .cm-card-checklist").forEach((c) => {
      c.classList.toggle("cm-hidden", q !== "");
    });
  }
  if (countEl) {
    countEl.textContent = shown + " / " + total;
    countEl.hidden = false;
  }
  _toggleSearchEmptyNote(q !== "" && shown === 0);
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
