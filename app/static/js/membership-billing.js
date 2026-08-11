/* Membership page: Monthly / Annual (best value) toggle. */
(function () {
  "use strict";

  function init() {
    var root = document.querySelector("[data-billing-toggle]");
    var page = document.querySelector(".mem-page");
    if (!root || !page) return;

    var buttons = root.querySelectorAll("[data-billing]");

    function setBilling(mode) {
      mode = mode === "annual" ? "annual" : "monthly";
      buttons.forEach(function (b) {
        var on = b.getAttribute("data-billing") === mode;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      page.setAttribute("data-billing", mode);
      try {
        var url = new URL(window.location.href);
        url.searchParams.set("billing", mode);
        history.replaceState(null, "", url.pathname + url.search + url.hash);
      } catch (e) {}
    }

    buttons.forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        setBilling(btn.getAttribute("data-billing"));
      });
    });

    var start = "monthly";
    try {
      var q = new URLSearchParams(window.location.search).get("billing");
      if (q === "annual" || q === "yearly" || q === "year") start = "annual";
    } catch (e) {}
    setBilling(start);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
