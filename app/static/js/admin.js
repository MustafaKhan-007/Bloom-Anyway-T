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
      pendingForm = null;
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      if (!form) return;
      // Native submit skips the confirm interceptor (no submit event).
      // Show the page loader manually since submit listeners will not run.
      var loader = document.getElementById("page-loader");
      if (loader) {
        loader.hidden = false;
        loader.setAttribute("aria-hidden", "false");
        document.documentElement.classList.add("is-page-loading");
      }
      HTMLFormElement.prototype.submit.call(form);
    });

    document.addEventListener("submit", function (e) {
      var form = e.target;
      if (!form || form.tagName !== "FORM") return;
      if (!form.hasAttribute("data-confirm")) return;
      if (form.dataset.confirmAccepted === "1") {
        delete form.dataset.confirmAccepted;
        return;
      }
      e.preventDefault();
      openDialog(form);
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
  /* ---- bulk select + remove on Studio list pages ---- */
  (function () {
    function itemsFor(form) {
      var id = (form && form.id) || "";
      if (!id) return [];
      var out = [];
      var nodes = document.querySelectorAll("input[data-bulk-item]");
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        if (el.disabled) continue;
        // Prefer explicit form= association (items live outside the <form>).
        if (el.getAttribute("form") === id || form.contains(el)) {
          out.push(el);
        }
      }
      return out;
    }

    function refresh(form) {
      if (!form) return;
      var items = itemsFor(form);
      var checked = items.filter(function (el) { return el.checked; });
      var n = checked.length;
      var submit = form.querySelector("[data-bulk-submit]");
      var countEl = form.querySelector("[data-bulk-count]");
      var all = form.querySelector("[data-bulk-all]");
      if (submit) {
        submit.disabled = n === 0;
        var base = submit.getAttribute("data-label")
          || submit.textContent.replace(/\s*\(\d+\)\s*$/, "").trim()
          || "Remove selected";
        submit.setAttribute("data-label", base);
        submit.textContent = n ? base + " (" + n + ")" : base;
      }
      if (countEl) {
        countEl.hidden = n === 0;
        countEl.textContent = n + " selected";
      }
      if (all) {
        all.checked = items.length > 0 && n === items.length;
        all.indeterminate = n > 0 && n < items.length;
      }
      var tmpl = form.getAttribute("data-bulk-confirm")
        || "Remove {n} selected item(s)? This cannot be undone.";
      form.setAttribute("data-confirm", tmpl.replace(/\{n\}/g, String(n || 0)));
    }

    function formFor(el) {
      if (!el) return null;
      var host = el.closest ? el.closest("form[data-bulk]") : null;
      if (host) return host;
      var fid = el.getAttribute("form");
      if (fid) return document.getElementById(fid);
      return null;
    }

    function setAll(form, on) {
      itemsFor(form).forEach(function (el) { el.checked = !!on; });
      refresh(form);
    }

    // One delegated listener — survives any number of bulk forms on the page.
    document.addEventListener("change", function (e) {
      var t = e.target;
      if (!t || !t.matches) return;
      if (t.matches("input[data-bulk-all]")) {
        var form = formFor(t);
        if (!form) return;
        setAll(form, t.checked);
        return;
      }
      if (t.matches("input[data-bulk-item]")) {
        refresh(formFor(t));
      }
    });

    document.querySelectorAll("form[data-bulk]").forEach(function (form) {
      refresh(form);
      form.addEventListener("submit", function (e) {
        refresh(form);
        var selected = itemsFor(form).filter(function (el) { return el.checked; });
        if (selected.length === 0) {
          e.preventDefault();
          e.stopImmediatePropagation();
          return;
        }
        // Backup: some browsers are flaky with form= association across tables.
        // Mirror checked values as hidden inputs inside the bulk form.
        form.querySelectorAll("input[data-bulk-mirror]").forEach(function (n) {
          n.parentNode.removeChild(n);
        });
        selected.forEach(function (el) {
          var name = el.getAttribute("name") || "ids";
          var hidden = document.createElement("input");
          hidden.type = "hidden";
          hidden.name = name;
          hidden.value = el.value;
          hidden.setAttribute("data-bulk-mirror", "1");
          form.appendChild(hidden);
        });
      });
    });

    // FAQ summaries: clicking the checkbox must not toggle <details>.
    document.querySelectorAll("input.faq-item__bulk").forEach(function (cb) {
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
    });
  })();
})();

  (function () {
    document.querySelectorAll("[data-tz-picker]").forEach(function (root) {
      var hidden = root.querySelector('input[type="hidden"][name="timezone"]');
      var search = root.querySelector(".tz-picker__search");
      var list = root.querySelector(".tz-picker__list");
      var chosen = root.querySelector("[data-tz-chosen] strong");
      var empty = root.querySelector("[data-tz-empty]");
      if (!hidden || !search || !list) return;

      var opts = Array.prototype.slice.call(root.querySelectorAll(".tz-picker__opt"));
      var groups = Array.prototype.slice.call(root.querySelectorAll("[data-tz-group]"));

      function openList() {
        list.hidden = false;
        search.setAttribute("aria-expanded", "true");
        root.classList.add("is-open");
      }

      function closeList() {
        list.hidden = true;
        search.setAttribute("aria-expanded", "false");
        root.classList.remove("is-open");
      }

      function filter(q) {
        var needle = (q || "").trim().toLowerCase();
        var any = false;
        opts.forEach(function (btn) {
          var hay = btn.getAttribute("data-search") || "";
          var show = !needle || hay.indexOf(needle) !== -1;
          btn.hidden = !show;
          if (show) any = true;
        });
        groups.forEach(function (g) {
          var visible = g.querySelectorAll(".tz-picker__opt:not([hidden])");
          g.hidden = visible.length === 0;
        });
        if (empty) empty.hidden = any;
      }

      function selectOpt(btn) {
        if (!btn) return;
        opts.forEach(function (b) {
          b.classList.remove("is-selected");
          b.setAttribute("aria-selected", "false");
        });
        btn.classList.add("is-selected");
        btn.setAttribute("aria-selected", "true");
        hidden.value = btn.getAttribute("data-value") || "";
        if (chosen) chosen.textContent = btn.getAttribute("data-label") || hidden.value;
        search.value = "";
        filter("");
        closeList();
      }

      search.addEventListener("focus", function () {
        openList();
        filter(search.value);
      });
      search.addEventListener("input", function () {
        openList();
        filter(search.value);
      });
      search.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
          closeList();
          search.blur();
        } else if (e.key === "Enter") {
          e.preventDefault();
          var first = root.querySelector(".tz-picker__opt:not([hidden])");
          if (first) selectOpt(first);
        }
      });

      list.addEventListener("mousedown", function (e) {
        // Keep focus while clicking options (prevents blur-before-click).
        e.preventDefault();
      });
      list.addEventListener("click", function (e) {
        var btn = e.target && e.target.closest ? e.target.closest(".tz-picker__opt") : null;
        if (btn) selectOpt(btn);
      });

      document.addEventListener("click", function (e) {
        if (!root.contains(e.target)) closeList();
      });
    });
  })();
