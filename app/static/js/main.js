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

  /* ---- avatar crop / resize before upload ---- */
  (function () {
    var input = document.querySelector("[data-avatar-crop]");
    var dialog = document.getElementById("avatar-crop");
    if (!input || !dialog) return;

    // Keep the modal at the document root so stacking/CSP ancestors can't hide it.
    if (dialog.parentElement !== document.body) {
      document.body.appendChild(dialog);
    }

    var canModal = typeof dialog.showModal === "function";
    var stage = dialog.querySelector("[data-crop-stage]");
    var img = dialog.querySelector("[data-crop-image]");
    var zoom = dialog.querySelector("[data-crop-zoom]");
    var applyBtn = dialog.querySelector("[data-crop-apply]");
    var cancelBtn = dialog.querySelector("[data-crop-cancel]");
    var help = dialog.querySelector("[data-crop-help]");
    var pick = input.closest(".avatar-edit") &&
               input.closest(".avatar-edit").querySelector(".avatar");
    if (!stage || !img || !zoom || !applyBtn || !cancelBtn) return;

    var objectUrl = null;
    var natural = { w: 0, h: 0 };
    var state = { scale: 1, x: 0, y: 0, dragging: false, lastX: 0, lastY: 0 };
    var pendingFile = null;
    var pendingIsGif = false;

    function isImageFile(file) {
      if (!file) return false;
      if (file.type && file.type.indexOf("image/") === 0) return true;
      return /\.(jpe?g|png|gif|webp|bmp|heic|heif)$/i.test(file.name || "");
    }

    function isGifFile(file) {
      if (!file) return false;
      var type = (file.type || "").toLowerCase();
      if (type === "image/gif" || type.indexOf("gif") !== -1) return true;
      return /\.gif$/i.test(file.name || "");
    }

    function stageSize() {
      return Math.min(stage.clientWidth, stage.clientHeight) || 280;
    }

    function fitScale() {
      var s = stageSize();
      if (!natural.w || !natural.h) return 1;
      return Math.max(s / natural.w, s / natural.h);
    }

    function render() {
      if (!natural.w || !natural.h) return;
      var s = stageSize();
      var min = fitScale();
      var scale = Math.max(min, state.scale || min);
      state.scale = scale;
      var w = natural.w * scale;
      var h = natural.h * scale;
      var maxX = Math.max(0, (w - s) / 2);
      var maxY = Math.max(0, (h - s) / 2);
      state.x = Math.max(-maxX, Math.min(maxX, state.x));
      state.y = Math.max(-maxY, Math.min(maxY, state.y));
      img.style.width = w + "px";
      img.style.height = h + "px";
      img.style.transform = "translate(calc(-50% + " + state.x + "px), calc(-50% + " + state.y + "px))";
      var zoomPct = Math.round((scale / min) * 100);
      zoom.value = String(Math.max(100, Math.min(300, zoomPct)));
    }

    function setHelp(text) {
      if (help) help.textContent = text;
    }

    function openDialog() {
      if (canModal) {
        if (!dialog.open) dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
        dialog.classList.add("avatar-crop--fallback");
      }
    }

    function closeDialog() {
      if (canModal) {
        if (dialog.open) dialog.close();
      } else {
        dialog.removeAttribute("open");
        dialog.classList.remove("avatar-crop--fallback");
      }
    }

    function revokePreview() {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
    }

    function onImageReady() {
      natural.w = img.naturalWidth || 0;
      natural.h = img.naturalHeight || 0;
      if (!natural.w || !natural.h) {
        setHelp("That image couldn't be read. Try a JPG or PNG.");
        return;
      }
      state.scale = fitScale();
      state.x = 0;
      state.y = 0;
      if (pendingIsGif) {
        setHelp("Animated GIFs keep their motion. Preview below, then use this GIF — it plays on your profile and in Settings.");
      } else {
        setHelp("Drag to reposition. Use the slider to zoom. The circle is what people will see.");
      }
      render();
      requestAnimationFrame(render);
    }

    function loadFile(file) {
      pendingFile = file;
      pendingIsGif = isGifFile(file);
      setHelp("Loading your picture…");
      openDialog();
      revokePreview();
      img.onload = onImageReady;
      img.onerror = function () {
        setHelp("That image couldn't be previewed. Try a JPG, PNG, or GIF.");
      };

      try {
        objectUrl = URL.createObjectURL(file);
        img.src = objectUrl;
      } catch (err) {
        var reader = new FileReader();
        reader.onload = function () {
          img.src = String(reader.result || "");
        };
        reader.onerror = function () {
          setHelp("That image couldn't be read. Try a JPG, PNG, or GIF.");
        };
        reader.readAsDataURL(file);
      }
    }

    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      if (!isImageFile(file)) {
        input.value = "";
        pendingFile = null;
        pendingIsGif = false;
        window.alert("Please choose an image file (JPG, PNG, WEBP, or GIF).");
        return;
      }
      loadFile(file);
    });

    zoom.addEventListener("input", function () {
      var min = fitScale();
      state.scale = min * (Math.max(100, parseInt(zoom.value, 10) || 100) / 100);
      render();
    });

    stage.addEventListener("pointerdown", function (e) {
      if (!natural.w) return;
      state.dragging = true;
      state.lastX = e.clientX;
      state.lastY = e.clientY;
      try { stage.setPointerCapture(e.pointerId); } catch (err) {}
    });
    stage.addEventListener("pointermove", function (e) {
      if (!state.dragging) return;
      state.x += e.clientX - state.lastX;
      state.y += e.clientY - state.lastY;
      state.lastX = e.clientX;
      state.lastY = e.clientY;
      render();
    });
    function endDrag() { state.dragging = false; }
    stage.addEventListener("pointerup", endDrag);
    stage.addEventListener("pointercancel", endDrag);

    function closeCrop(clearInput) {
      closeDialog();
      revokePreview();
      img.removeAttribute("src");
      natural.w = 0;
      natural.h = 0;
      if (clearInput) {
        pendingFile = null;
        pendingIsGif = false;
        input.value = "";
      }
    }

    cancelBtn.addEventListener("click", function (e) {
      e.preventDefault();
      closeCrop(true);
    });
    dialog.addEventListener("cancel", function (e) {
      e.preventDefault();
      closeCrop(true);
    });

    applyBtn.addEventListener("click", function (e) {
      e.preventDefault();
      if (!natural.w || !natural.h) return;

      function finishPreview(url) {
        if (!pick) return;
        if (pick.tagName === "IMG") {
          pick.src = url;
        } else {
          pick.style.backgroundImage = "url('" + url + "')";
          pick.textContent = "";
        }
      }

      var file = pendingFile || (input.files && input.files[0]);
      var keepGif = pendingIsGif || isGifFile(file);

      // Never canvas-flatten GIFs — that kills the animation.
      if (keepGif && file) {
        try {
          var dtGif = new DataTransfer();
          dtGif.items.add(file);
          input.files = dtGif.files;
        } catch (err) {}
        finishPreview(URL.createObjectURL(file));
        var removeGif = document.querySelector("input[name='remove_avatar']");
        if (removeGif) removeGif.checked = false;
        closeCrop(false);
        return;
      }

      var s = stageSize();
      var min = fitScale();
      var scale = Math.max(min, state.scale);
      var out = 400;
      var canvas = document.createElement("canvas");
      canvas.width = out;
      canvas.height = out;
      var ctx = canvas.getContext("2d");
      if (!ctx) return;
      var srcSize = s / scale;
      var srcX = (natural.w / 2) - (srcSize / 2) - (state.x / scale);
      var srcY = (natural.h / 2) - (srcSize / 2) - (state.y / scale);
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, out, out);
      try {
        ctx.drawImage(img, srcX, srcY, srcSize, srcSize, 0, 0, out, out);
      } catch (err) {
        closeCrop(false);
        return;
      }
      canvas.toBlob(function (blob) {
        if (!blob) {
          closeCrop(false);
          return;
        }
        try {
          var cropped = new File([blob], "avatar.jpg", { type: "image/jpeg" });
          var dt = new DataTransfer();
          dt.items.add(cropped);
          input.files = dt.files;
        } catch (err) {}
        finishPreview(URL.createObjectURL(blob));
        var remove = document.querySelector("input[name='remove_avatar']");
        if (remove) remove.checked = false;
        closeCrop(false);
      }, "image/jpeg", 0.92);
    });

    window.addEventListener("resize", function () {
      if ((dialog.open || dialog.hasAttribute("open")) && natural.w) render();
    });
  })();

  /* ---- CSP-safe auto-submit selects ---- */
  document.querySelectorAll("select[data-autosubmit]").forEach(function (sel) {
    sel.addEventListener("change", function () {
      if (sel.form) sel.form.submit();
    });
  });

  /* ---- CSP-safe: block context menu on protected media ---- */
  document.querySelectorAll("[data-no-contextmenu]").forEach(function (el) {
    el.addEventListener("contextmenu", function (e) { e.preventDefault(); });
  });

  /* ---- remember browser timezone for local timestamps ---- */
  (function () {
    var tz = "";
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) {}
    if (!tz) return;
    document.cookie = "tz=" + encodeURIComponent(tz) + ";path=/;max-age=31536000;SameSite=Lax";
    var url = document.body.getAttribute("data-tz-sync");
    var csrf = document.body.getAttribute("data-csrf");
    if (!url || !csrf) return;
    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
        "X-Requested-With": "fetch",
        "Accept": "application/json"
      },
      credentials: "same-origin",
      body: JSON.stringify({ timezone: tz })
    }).catch(function () {});
  })();

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

  /* ---- notification bell: click-outside, Escape, mark-as-read ---- */
  document.querySelectorAll("details.note-bell").forEach(function (bell) {
    var marked = false;

    function clearUnreadUi() {
      var count = bell.querySelector(".note-bell__count");
      if (count) count.remove();
      bell.querySelectorAll(".note-bell__item.is-unread").forEach(function (el) {
        el.classList.remove("is-unread");
      });
      var markBtn = bell.querySelector("[data-mark-read]");
      if (markBtn) markBtn.remove();
      var summary = bell.querySelector(".note-bell__btn");
      if (summary) summary.setAttribute("aria-label", "Notifications");
      document.querySelectorAll(".myspace-tabs__dot").forEach(function (dot) {
        dot.remove();
      });
    }

    function markRead() {
      if (marked) return;
      var url = bell.getAttribute("data-mark-read-url");
      var csrf = bell.getAttribute("data-csrf");
      if (!url || !csrf) return;
      marked = true;
      clearUnreadUi();
      fetch(url, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrf,
          "X-Requested-With": "fetch",
          "Accept": "application/json"
        },
        credentials: "same-origin"
      }).catch(function () {
        marked = false;
      });
    }

    bell.addEventListener("toggle", function () {
      if (bell.open) markRead();
    });

    var markBtn = bell.querySelector("[data-mark-read]");
    if (markBtn) {
      markBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        markRead();
      });
    }

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

  /* ---- reply textarea: full width, grow with lines (no horizontal resize) ---- */
  function autosizeTextarea(el) {
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }
  document.querySelectorAll(".comment-form--reply textarea").forEach(function (ta) {
    autosizeTextarea(ta);
    ta.addEventListener("input", function () { autosizeTextarea(ta); });
  });
  document.querySelectorAll("details.reply-toggle").forEach(function (d) {
    d.addEventListener("toggle", function () {
      if (!d.open) return;
      var ta = d.querySelector("textarea");
      if (ta) {
        autosizeTextarea(ta);
        ta.focus();
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

  /* ---- site feedback dialog (stars / complaint / error) ---- */
  (function () {
    var dialog = document.getElementById("feedback-dialog");
    if (!dialog) return;
    var kindInput = dialog.querySelector("[data-feedback-kind-input]");
    var starsBox = dialog.querySelector("[data-feedback-stars]");
    var tabs = dialog.querySelectorAll("[data-feedback-tab]");

    function setKind(kind) {
      if (kindInput) kindInput.value = kind;
      tabs.forEach(function (btn) {
        btn.classList.toggle("is-active", btn.getAttribute("data-feedback-tab") === kind);
      });
      if (starsBox) {
        if (kind === "feedback") starsBox.removeAttribute("hidden");
        else starsBox.setAttribute("hidden", "");
      }
    }

    function openDialog(pref) {
      setKind(pref || "feedback");
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }

    function closeDialog() {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }

    document.querySelectorAll("[data-feedback-open]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openDialog(btn.getAttribute("data-feedback-pref") || "feedback");
      });
    });
    dialog.querySelectorAll("[data-feedback-close]").forEach(function (btn) {
      btn.addEventListener("click", closeDialog);
    });
    tabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        setKind(btn.getAttribute("data-feedback-tab") || "feedback");
      });
    });
    setKind("feedback");
  })();
})();
