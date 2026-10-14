// Drag and drop: SortableJS moves the card in the browser, HTMX tells the server.
// The server answers with fresh counters and the card face (out-of-band), or the whole
// board if it refused the move, so the screen always ends up matching the database.

function updateColumnCounts() {
  document.querySelectorAll(".column").forEach((col) => {
    const count = col.querySelector(".column-count");
    if (count) count.textContent = col.querySelectorAll(".column-cards > .card").length;
  });
}

function initSortable(root) {
  root.querySelectorAll(".column-cards").forEach((list) => {
    if (list._sortable) return; // htmx.onLoad also fires for swapped-in content
    list._sortable = new Sortable(list, {
      group: "board",
      draggable: ".card",
      animation: 150,
      ghostClass: "card-ghost",
      onStart: () => document.body.classList.add("dragging"),
      onEnd: (e) => {
        document.body.classList.remove("dragging");
        updateColumnCounts();
        if (e.from === e.to && e.oldIndex === e.newIndex) return;
        htmx.ajax("POST", `/card/${e.item.dataset.id}/move/`, {
          source: e.item,
          target: "#board-counters",
          swap: "outerHTML",
          values: { column: e.to.dataset.column, position: e.newIndex },
        });
      },
    });
  });
}

function closeDrawer() {
  const drawer = document.getElementById("drawer");
  if (drawer) drawer.innerHTML = "";
  const url = new URL(window.location);
  if (url.searchParams.has("card")) {
    url.searchParams.delete("card");
    history.replaceState(null, "", url);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  htmx.onLoad((root) => {
    initSortable(root);
    updateColumnCounts();
  });
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-close-drawer]")) closeDrawer();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });
});
