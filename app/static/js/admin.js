/* Bloom Anyway — admin panel JS */
(function () {
  "use strict";

  /* ---- in-page confirm dialogs (no browser popups) ---- */
  (function () {
    var dialog = document.getElementById("site-confirm");
    if (!dialog) {
      dialog = document.createElement("dialog");
      dialog.id = "site-confirm";
      dialog.className = "site-confirm";
      dialog.setAttribute("aria-labelledby", "site-confirm-title");
      dialog.innerHTML =
        '<div class="site-confirm__panel">' +
        '<h2 id="site-confirm-title" data-confirm-title>Are you sure?</h2>' +
        '<p class="site-confirm__body" data-confirm-body></p>' +
        '<div class="site-confirm__actions">' +
        '<button type="button" class="btn btn--secondary btn--sm" data-confirm-cancel>Cancel</button>' +
        '<button type="button" class="btn btn--danger btn--sm" data-confirm-ok>Confirm</button>' +
        "</div></div>";
      document.body.appendChild(dialog);
    }

    var titleEl = dialog.querySelector("[data-confirm-title]");
    var bodyEl = dialog.querySelector("[data-confirm-body]");
    var okBtn = dialog.querySelector("[data-confirm-ok]");
    var cancelBtn = dialog.querySelector("[data-confirm-cancel]");
    var pendingForm = null;

    function openDialog(form) {
      pendingForm = form;
      titleEl.textContent = form.getAttribute("data-confirm-title") || "Are you sure?";
      bodyEl.textContent = form.getAttribute("data-confirm") || "Please confirm to continue.";
      okBtn.textContent = form.getAttribute("data-confirm-ok") || "Confirm";
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }

    function closeDialog() {
      pendingForm = null;
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }

    function dismissConfirm() {
      closeDialog();
      document.dispatchEvent(new CustomEvent("site-confirm-dismiss"));
    }

    cancelBtn.addEventListener("click", dismissConfirm);
    dialog.addEventListener("cancel", function () {
      pendingForm = null;
      document.dispatchEvent(new CustomEvent("site-confirm-dismiss"));
    });
    okBtn.addEventListener("click", function () {
      var form = pendingForm;
      closeDialog();
      if (!form) return;
      form.dataset.confirmAccepted = "1";
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else form.submit();
    });

    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        if (form.dataset.confirmAccepted === "1") {
          delete form.dataset.confirmAccepted;
          return;
        }
        e.preventDefault();
        openDialog(form);
      });
    });
  })();

  /* ---- product modules: start with 2, add more (optional) ---- */
  (function () {
    var root = document.querySelector("[data-studio-modules]");
    if (!root) return;
    var list = root.querySelector("[data-modules-list]");
    var addBtn = root.querySelector("[data-modules-add]");
    if (!list || !addBtn) return;
    var max = parseInt(root.getAttribute("data-modules-max") || "12", 10) || 12;

    function renumber() {
      var rows = list.querySelectorAll("[data-module-row]");
      rows.forEach(function (row, i) {
        var n = i + 1;
        row.querySelectorAll("label").forEach(function (lab) {
          var html = lab.innerHTML;
          lab.innerHTML = html.replace(/Module\s+\d+/i, "Module " + n);
        });
        row.querySelectorAll("input").forEach(function (inp) {
          var name = inp.getAttribute("name") || "";
          if (/^mod\d+_title$/.test(name)) {
            inp.name = "mod" + n + "_title";
            inp.id = "mod" + n + "_title";
          } else if (/^mod\d+_desc$/.test(name)) {
            inp.name = "mod" + n + "_desc";
            inp.id = "mod" + n + "_desc";
          }
        });
        row.querySelectorAll("label[for]").forEach(function (lab) {
          var f = lab.getAttribute("for") || "";
          if (/^mod\d+_title$/.test(f)) lab.setAttribute("for", "mod" + n + "_title");
          if (/^mod\d+_desc$/.test(f)) lab.setAttribute("for", "mod" + n + "_desc");
        });
      });
      addBtn.hidden = rows.length >= max;
    }

    addBtn.addEventListener("click", function () {
      var rows = list.querySelectorAll("[data-module-row]");
      if (rows.length >= max) return;
      var n = rows.length + 1;
      var row = document.createElement("div");
      row.className = "form-row studio-modules__row";
      row.setAttribute("data-module-row", "");
      row.innerHTML =
        '<div class="field">' +
        '<label for="mod' + n + '_title">Module ' + n + " title</label>" +
        '<input type="text" id="mod' + n + '_title" name="mod' + n +
        '_title" maxlength="160" value="">' +
        "</div>" +
        '<div class="field" style="flex:2;">' +
        '<label for="mod' + n + '_desc">Short note</label>' +
        '<input type="text" id="mod' + n + '_desc" name="mod' + n +
        '_desc" maxlength="500" value="">' +
        "</div>";
      list.appendChild(row);
      renumber();
    });

    renumber();
  })();

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
    var gold = "#c79a41";

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

    var purchasesCtx = document.getElementById("chart-purchases");
    if (purchasesCtx && data.purchases) {
      var purchaseChart = new Chart(purchasesCtx, {
        type: "line",
        data: {
          labels: data.purchases.labels || [],
          datasets: [
            {
              label: "All products",
              data: data.purchases.all || [],
              borderColor: plum,
              backgroundColor: "rgba(122, 46, 98, 0.12)",
              tension: 0.3,
              fill: true,
              borderWidth: 2,
              pointRadius: 0,
            }
          ]
        },
        options: {
          plugins: { legend: { display: false } },
          scales: {
            x: {
              ticks: {
                maxTicksLimit: 8,
                callback: function (val, i) {
                  var lab = this.getLabelForValue(val);
                  if (!lab) return "";
                  // Show month-day for readability
                  return String(lab).slice(5);
                }
              }
            },
            y: {
              beginAtZero: true,
              ticks: { precision: 0 }
            }
          }
        }
      });

      var filters = document.getElementById("purchase-filters");
      if (filters) {
        filters.addEventListener("click", function (e) {
          var btn = e.target.closest("[data-product]");
          if (!btn) return;
          filters.querySelectorAll(".studio-purchase-filter").forEach(function (b) {
            b.classList.toggle("is-active", b === btn);
          });
          var key = btn.getAttribute("data-product") || "all";
          var series = key === "all"
            ? (data.purchases.all || [])
            : ((data.purchases.by_product || {})[key] || []);
          var label = key === "all" ? "All products" : (btn.textContent || "Product");
          purchaseChart.data.datasets[0].data = series;
          purchaseChart.data.datasets[0].label = label;
          purchaseChart.data.datasets[0].borderColor = key === "all" ? plum : gold;
          purchaseChart.data.datasets[0].backgroundColor =
            key === "all" ? "rgba(122, 46, 98, 0.12)" : "rgba(199, 154, 65, 0.15)";
          purchaseChart.update();
        });
      }
    }
  }
})();
