/* ---------- Sort comments by time ---------- */
// A single 3-state cycle button: document (anchor position) order -> newest first (time-desc)
// -> oldest first (time-asc) -> back to document order. The choice persists.
(function () {
  const b = document.getElementById("btnSort");
  if (!b) return;
  const NEXT = { "pos": "time-desc", "time-desc": "time-asc", "time-asc": "pos" };
  b.addEventListener("click", function () {
    commentSort = NEXT[commentSort] || "time-desc";
    try { localStorage.setItem(COMMENT_KEY + "::commentSort", commentSort); } catch (e) { /* private mode */ }
    renderComments();
  });
})();

