/* Sunflower page loader — shows while navigating / submitting forms. */
(function () {
  "use strict";

  var el = document.getElementById("page-loader");
  if (!el) return;

  var hideTimer = null;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function show() {
    if (hideTimer) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
    el.hidden = false;
    el.setAttribute("aria-hidden", "false");
    document.documentElement.classList.add("is-page-loading");
  }

  function hide() {
    el.hidden = true;
    el.setAttribute("aria-hidden", "true");
    document.documentElement.classList.remove("is-page-loading");
  }

  function softHide() {
    // Brief linger so fast navigations still feel intentional.
    hideTimer = setTimeout(hide, reduced ? 0 : 120);
  }

  // Initial page load
  if (document.readyState !== "complete") {
    show();
    window.addEventListener("load", softHide);
  }
  window.addEventListener("pageshow", function () {
    hide();
  });

  function sameOrigin(href) {
    try {
      var u = new URL(href, window.location.href);
      return u.origin === window.location.origin;
    } catch (err) {
      return false;
    }
  }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    if (a.target && a.target !== "_self") return;
    if (a.hasAttribute("download")) return;
    var href = a.getAttribute("href") || "";
    if (!href || href.charAt(0) === "#") return;
    if (href.indexOf("javascript:") === 0 || href.indexOf("mailto:") === 0
        || href.indexOf("tel:") === 0) return;
    if (!sameOrigin(href)) return;
    // Same-page hash-only after path
    try {
      var next = new URL(href, window.location.href);
      if (next.pathname === window.location.pathname
          && next.search === window.location.search
          && next.hash) return;
    } catch (err) {}
    show();
  }, true);

  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;
    var form = e.target;
    if (!form || form.tagName !== "FORM") return;
    if (form.getAttribute("data-no-loader") != null) return;
    if (form.target && form.target !== "_self") return;
    // Confirm dialogs intercept submit in the bubble phase. Skip the loader until
    // the user accepts (dataset.confirmAccepted), or Cancel leaves it spinning forever.
    if (form.hasAttribute("data-confirm") && form.dataset.confirmAccepted !== "1") return;
    show();
  }, true);

  document.addEventListener("site-confirm-dismiss", hide);
})();
