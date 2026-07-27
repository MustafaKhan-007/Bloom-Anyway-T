/* Bloom Anyway — public site JS (vanilla, no dependencies) */
(function () {
  "use strict";

  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- hero load-in (one page-load moment only) ---- */
  var hero = document.querySelector(".hero");
  if (hero) {
    if (reducedMotion) {
      hero.classList.add("loaded");
    } else {
      requestAnimationFrame(function () { hero.classList.add("loaded"); });
    }
  }

  /* ---- scroll-triggered reveal ---- */
  var revealEls = document.querySelectorAll(".reveal");
  if (revealEls.length && !reducedMotion && "IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15 });
    revealEls.forEach(function (el) { observer.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add("visible"); });
  }

  /* ---- mobile nav drawer (accessible, focus-trapped) ---- */
  var toggle = document.querySelector(".nav-toggle");
  var drawer = document.getElementById("nav-drawer");
  if (toggle && drawer) {
    var focusables = function () {
      return drawer.querySelectorAll("a[href], button:not([disabled])");
    };
    var close = function () {
      drawer.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    };
    toggle.addEventListener("click", function () {
      var open = drawer.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        var first = focusables()[0];
        if (first) first.focus();
      }
    });
    document.addEventListener("keydown", function (e) {
      if (!drawer.classList.contains("open")) return;
      if (e.key === "Escape") { close(); return; }
      if (e.key !== "Tab") return;
      var items = focusables();
      if (!items.length) return;
      var first = items[0];
      var last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        toggle.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        toggle.focus();
      } else if (!e.shiftKey && document.activeElement === toggle) {
        e.preventDefault();
        first.focus();
      }
    });
  }

  /* ---- password show/hide toggles ---- */
  document.querySelectorAll(".password-toggle").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = document.getElementById(btn.dataset.toggles);
      if (!input) return;
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "Hide" : "Show";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  /* Clear auth passwords when navigating back to login/register */
  if (document.querySelector(".auth-card")) {
    var clearAuthPasswords = function () {
      document.querySelectorAll(".auth-card input[type='password']").forEach(function (input) {
        input.value = "";
      });
    };
    clearAuthPasswords();
    window.addEventListener("pageshow", clearAuthPasswords);
  }

  /* ---- confirm dialogs (delete account etc.) ---- */
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  /* ---- live preview when picking a new avatar ---- */
  document.querySelectorAll("[data-avatar-preview]").forEach(function (input) {
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      var pick = input.closest(".avatar-edit") &&
                 input.closest(".avatar-edit").querySelector(".avatar");
      if (!pick) return;
      var url = URL.createObjectURL(file);
      pick.style.backgroundImage = "url('" + url + "')";
      pick.textContent = "";
      // untick "remove" if the person just chose a new picture
      var remove = document.querySelector("input[name='remove_avatar']");
      if (remove) remove.checked = false;
    });
  });

  /* ---- marketplace listing form: show location box for services ---- */
  var listingForm = document.getElementById("listing-form");
  if (listingForm) {
    var locBox = listingForm.querySelector("[data-location-box]");
    var locInput = listingForm.querySelector("#location");
    var syncKind = function () {
      var picked = listingForm.querySelector('input[name="kind"]:checked');
      var isService = !!(picked && picked.value === "service");
      listingForm.classList.toggle("is-service", isService);
      listingForm.classList.toggle("is-product", !isService);
      if (locBox) {
        if (isService) locBox.removeAttribute("hidden");
        else locBox.setAttribute("hidden", "");
      }
      if (locInput) {
        locInput.required = isService;
        if (!isService) locInput.value = locInput.value; // keep typed text if they toggle back
      }
    };
    listingForm.querySelectorAll('input[name="kind"]').forEach(function (r) {
      r.addEventListener("change", syncKind);
      // also catch clicks on the visible label chip
      var label = r.closest("label");
      if (label) label.addEventListener("click", function () {
        // let the radio update, then sync on next tick
        setTimeout(syncKind, 0);
      });
    });
    syncKind();

    var max = parseInt(listingForm.getAttribute("data-tag-max") || "24", 10);
    var boxes = listingForm.querySelectorAll('input[name="tags"]');
    var countEl = listingForm.querySelector("[data-tag-count]");
    var syncTags = function () {
      var n = 0;
      boxes.forEach(function (b) { if (b.checked) n++; });
      if (countEl) countEl.textContent = n + " / " + max + " selected";
      boxes.forEach(function (b) {
        if (!b.checked) b.disabled = n >= max;
      });
    };
    boxes.forEach(function (b) { b.addEventListener("change", syncTags); });
    syncTags();
  }

  /* ---- Lemon Squeezy overlay (re-init if lemon.js loaded after us) ---- */
  if (window.createLemonSqueezy) {
    window.createLemonSqueezy();
  } else {
    document.querySelectorAll("script[src*='lemon.js']").forEach(function (s) {
      s.addEventListener("load", function () {
        if (window.createLemonSqueezy) window.createLemonSqueezy();
      });
    });
  }

  /* ---- notification bell: click-outside + Escape close ---- */
  document.querySelectorAll("details.note-bell").forEach(function (bell) {
    document.addEventListener("click", function (e) {
      if (!bell.open) return;
      if (bell.contains(e.target)) return;
      bell.removeAttribute("open");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && bell.open) {
        bell.removeAttribute("open");
      }
    });
  });

  /* ---- Coaching fold: smooth expand on My space ---- */
  document.querySelectorAll("[data-coaching-toggle]").forEach(function (btn) {
    var panel = document.getElementById(btn.getAttribute("aria-controls"));
    if (!panel) return;
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", open ? "false" : "true");
      btn.classList.toggle("is-open", !open);
      panel.setAttribute("aria-hidden", open ? "true" : "false");
      if (open) {
        panel.style.maxHeight = panel.scrollHeight + "px";
        requestAnimationFrame(function () {
          panel.style.maxHeight = "0px";
          panel.classList.remove("is-open");
        });
      } else {
        panel.classList.add("is-open");
        panel.style.maxHeight = "0px";
        requestAnimationFrame(function () {
          panel.style.maxHeight = panel.scrollHeight + "px";
        });
      }
    });
  });

  /* ---- Showcase listing gallery: thumbnails swap the hero image ---- */
  document.querySelectorAll("[data-listing-gallery]").forEach(function (gallery) {
    var hero = gallery.querySelector("#listing-hero") ||
               gallery.querySelector(".listing-detail__hero");
    if (!hero) return;
    gallery.querySelectorAll("[data-listing-thumb]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var src = btn.getAttribute("data-src");
        if (!src) return;
        hero.src = src;
        gallery.querySelectorAll("[data-listing-thumb]").forEach(function (other) {
          other.classList.toggle("is-active", other === btn);
          other.setAttribute("aria-pressed", other === btn ? "true" : "false");
        });
      });
    });
  });

  /* ---- @username mention autocomplete ---- */
  (function setupMentions() {
    var suggestUrl = document.body.getAttribute("data-mention-suggest");
    if (!suggestUrl) return;

    var menu = document.createElement("div");
    menu.className = "mention-menu";
    menu.hidden = true;
    menu.setAttribute("role", "listbox");
    document.body.appendChild(menu);

    var active = null;
    var items = [];
    var highlight = 0;
    var tokenStart = -1;
    var debounce = null;
    var reqId = 0;

    function hide() {
      menu.hidden = true;
      menu.innerHTML = "";
      items = [];
    }

    function placeMenu(textarea) {
      if (!textarea) return;
      var rect = textarea.getBoundingClientRect();
      var width = Math.min(300, Math.max(200, rect.width));
      var left = Math.min(
        Math.max(8, rect.left),
        Math.max(8, window.innerWidth - width - 8)
      );
      menu.style.position = "fixed";
      menu.style.left = left + "px";
      menu.style.top = (rect.bottom + 6) + "px";
      menu.style.minWidth = width + "px";
      menu.style.zIndex = "200";
    }

    function applyChoice(username) {
      if (!active || tokenStart < 0) return;
      var val = active.value;
      var caret = active.selectionStart;
      var before = val.slice(0, tokenStart);
      var after = val.slice(caret);
      active.value = before + "@" + username + " " + after;
      var pos = before.length + username.length + 2;
      active.focus();
      active.setSelectionRange(pos, pos);
      hide();
      active = null;
    }

    function render() {
      menu.innerHTML = "";
      if (!items.length || !active) {
        hide();
        return;
      }
      items.forEach(function (row, i) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "mention-menu__item" + (i === highlight ? " is-active" : "");
        btn.setAttribute("role", "option");
        var handle = document.createElement("strong");
        handle.textContent = "@" + row.username;
        btn.appendChild(handle);
        if (row.name) {
          var name = document.createElement("span");
          name.textContent = row.name;
          btn.appendChild(name);
        }
        btn.addEventListener("mousedown", function (e) {
          e.preventDefault();
          applyChoice(row.username);
        });
        menu.appendChild(btn);
      });
      menu.hidden = false;
      placeMenu(active);
    }

    function fetchSuggestions(q) {
      var myReq = ++reqId;
      var url = suggestUrl + (suggestUrl.indexOf("?") >= 0 ? "&" : "?") +
                "q=" + encodeURIComponent(q);
      fetch(url, {
        headers: { "Accept": "application/json" },
        credentials: "same-origin",
        redirect: "follow"
      })
        .then(function (r) {
          var ct = (r.headers.get("content-type") || "").toLowerCase();
          if (!r.ok || ct.indexOf("application/json") === -1) return [];
          return r.json();
        })
        .then(function (data) {
          if (myReq !== reqId) return;
          items = Array.isArray(data) ? data : [];
          highlight = 0;
          render();
        })
        .catch(function () {
          if (myReq === reqId) hide();
        });
    }

    function mentionQuery(textarea) {
      var caret = typeof textarea.selectionStart === "number"
        ? textarea.selectionStart
        : textarea.value.length;
      var upto = textarea.value.slice(0, caret);
      // Allow bare "@" (empty query) and partial handles; require a boundary
      // before @ so emails like name@host are ignored.
      var match = upto.match(/(?:^|[^\w@])@([a-zA-Z0-9_]{0,30})$/);
      if (!match) return null;
      var handle = match[1] || "";
      return {
        q: handle,
        tokenStart: caret - handle.length - 1
      };
    }

    function onInput(textarea) {
      active = textarea;
      var hit = mentionQuery(textarea);
      if (!hit) {
        hide();
        return;
      }
      tokenStart = hit.tokenStart;
      clearTimeout(debounce);
      debounce = setTimeout(function () { fetchSuggestions(hit.q); }, 80);
    }

    function isMentionField(el) {
      return el && el.tagName === "TEXTAREA" && el.hasAttribute("data-mentions");
    }

    document.addEventListener("input", function (e) {
      if (isMentionField(e.target)) onInput(e.target);
    });
    document.addEventListener("keydown", function (e) {
      if (!isMentionField(e.target)) return;
      if (menu.hidden || !items.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        highlight = (highlight + 1) % items.length;
        render();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        highlight = (highlight - 1 + items.length) % items.length;
        render();
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        applyChoice(items[highlight].username);
      } else if (e.key === "Escape") {
        hide();
      }
    });
    document.addEventListener("blur", function (e) {
      if (isMentionField(e.target)) setTimeout(hide, 180);
    }, true);

    window.addEventListener("scroll", function () {
      if (!menu.hidden && active) placeMenu(active);
    }, true);
    window.addEventListener("resize", function () {
      if (!menu.hidden && active) placeMenu(active);
    });
  })();
})();
