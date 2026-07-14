/* ---------- Sort comments by time ---------- */
// The two arrow buttons toggle time-ascending / time-descending order; clicking the
// active one again returns to document (anchor position) order. The choice persists.
["btnSortAsc", "btnSortDesc"].forEach(function (id) {
  const b = document.getElementById(id);
  if (!b) return;
  b.addEventListener("click", function () {
    const mode = (id === "btnSortAsc") ? "time-asc" : "time-desc";
    commentSort = (commentSort === mode) ? "pos" : mode;
    try { localStorage.setItem(COMMENT_KEY + "::commentSort", commentSort); } catch (e) { /* private mode */ }
    renderComments();
  });
});

