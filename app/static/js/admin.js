/* Bloom Anyway — admin panel JS */
(function () {
  "use strict";

  /* ---- confirm destructive actions ---- */
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  /* ---- CSP-safe auto-submit selects ---- */
  document.querySelectorAll("select[data-autosubmit]").forEach(function (sel) {
    sel.addEventListener("change", function () {
      if (sel.form) sel.form.submit();
    });
  });

  /* ---- collapsible long tables (show a few rows, expand on demand) ---- */
  document.querySelectorAll("table[data-collapsible]").forEach(function (table) {
    var limit = parseInt(table.getAttribute("data-collapsible"), 10) || 10;
    var body = table.tBodies[0];
    if (!body) return;
    var rows = Array.prototype.slice.call(body.rows);
    if (rows.length <= limit) return;

    var hidden = rows.slice(limit);
    var collapse = function () {
      hidden.forEach(function (r) { r.hidden = true; });
    };
    collapse();

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn--secondary btn--sm show-all-btn";
    var setLabel = function (expanded) {
      btn.textContent = expanded
        ? "Show fewer"
        : "Show all " + rows.length;
    };
    setLabel(false);
    btn.addEventListener("click", function () {
      var expanded = hidden[0] && hidden[0].hidden;
      hidden.forEach(function (r) { r.hidden = !expanded; });
      setLabel(expanded);
    });
    table.insertAdjacentElement("afterend", btn);
  });

  /* ---- dashboard charts (Chart.js from CDN) ---- */
  var dataEl = document.getElementById("dashboard-data");
  if (dataEl && window.Chart) {
    var data = JSON.parse(dataEl.textContent);
    var plum = "#7A2E62";

    var signupsCtx = document.getElementById("chart-signups");
    if (signupsCtx && data.signups) {
      new Chart(signupsCtx, {
        type: "line",
        data: {
          labels: data.signups.labels,
          datasets: [
            { label: "Accounts", data: data.signups.users, borderColor: plum, tension: 0.3, borderWidth: 2 }
          ]
        },
        options: { plugins: { legend: { display: false } } }
      });
    }
  }
})();
