/* Bloom Anyway — table rows become labelled cards on narrow screens.
   Copies each column heading onto its cells so CSS can stack them. Without
   this the table still works, it just scrolls sideways instead. */
(function () {
  "use strict";

  function headings(table) {
    var head = table.tHead && table.tHead.rows.length
      ? table.tHead.rows[table.tHead.rows.length - 1]
      : null;
    if (!head) return null;
    var out = [];
    for (var i = 0; i < head.cells.length; i++) {
      var cell = head.cells[i];
      var span = cell.colSpan || 1;
      var text = (cell.textContent || "").replace(/\s+/g, " ").trim();
      // A heading that only exists for screen readers isn't a card label.
      if (cell.querySelector(".visually-hidden, .sr-only")) text = "";
      while (span--) out.push(text);
    }
    return out;
  }

  function isBlank(cell) {
    if (cell.children.length) return false;
    return !(cell.textContent || "").trim();
  }

  function enhance(table) {
    if (table.dataset.stacked === "1") return;
    var labels = headings(table);
    if (!labels || !labels.length) return;

    var body = table.tBodies.length ? table.tBodies[0] : null;
    if (!body) return;

    for (var r = 0; r < body.rows.length; r++) {
      var row = body.rows[r];
      // "Nothing here yet" rows already span the width — leave them be.
      if (row.cells.length === 1 && row.cells[0].colSpan > 1) continue;
      var shown = [];
      for (var c = 0; c < row.cells.length; c++) {
        var cell = row.cells[c];
        if (cell.hasAttribute("data-label")) continue;
        cell.setAttribute("data-label", labels[c] || "");
        if (isBlank(cell)) cell.classList.add("is-empty");
        else shown.push(cell);
      }
      // Empty cells are hidden on phones, so the dividers have to follow the
      // cells that actually render.
      if (shown.length) {
        shown[0].classList.add("is-first-visible");
        shown[shown.length - 1].classList.add("is-last-visible");
      }
    }
    table.dataset.stacked = "1";
    table.classList.add("is-stacked");
  }

  document.querySelectorAll("table.admin-table").forEach(enhance);
})();
