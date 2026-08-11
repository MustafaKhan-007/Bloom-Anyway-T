/* Post-signup product tour — vignette + bubble walkthrough (CSP-safe). */
(function () {
  "use strict";

  var body = document.body;
  if (!body || body.getAttribute("data-product-tour") !== "1") return;

  var STEP_KEY = "ba_tour_step";
  var ACTIVE_KEY = "ba_tour_active";

  var STEPS = [
    {
      id: "welcome",
      path: "/account",
      title: "Welcome to Bloom Anyway",
      body: "You're in. This short walkthrough shows you the main places you'll use — then you're free to bloom at your own pace.",
      mode: "next",
      nextLabel: "Let's begin"
    },
    {
      id: "nav-courses",
      path: null,
      title: "Courses & Guides",
      body: "Tap Courses & Guides in the menu. This is where Ayesha and Saman's healing and building resources live.",
      mode: "click",
      target: "nav-courses",
      go: "/courses"
    },
    {
      id: "page-courses",
      path: "/courses",
      title: "Learn at your pace",
      body: "Two lanes: Healing (divorce, custody, rebuilding) and Building (business, content, digital products). Browse free, buy what you need, and keep purchases in My space.",
      mode: "next",
      target: "courses",
      surface: true
    },
    {
      id: "nav-watch",
      path: null,
      title: "Content Hub",
      body: "Next — open Content Hub. Tips, videos, and the weekly reel challenge live here.",
      mode: "click",
      target: "nav-watch",
      go: "/watch"
    },
    {
      id: "page-watch",
      path: "/watch",
      title: "Watch & grow",
      body: "Browse Content Tips, watch free picks, and (as a Creator) unlock full playback plus the daily reel review draw. Show up, share your work, get seen.",
      mode: "next",
      target: "watch",
      surface: true
    },
    {
      id: "nav-showcase",
      path: null,
      title: "Showcase",
      body: "Open Showcase — the community visibility board for products, services, and businesses.",
      mode: "click",
      target: "nav-showcase",
      go: "/showcase"
    },
    {
      id: "page-showcase",
      path: "/showcase",
      title: "Get discovered",
      body: "List what you're building so others can find you. Purchases happen on your own site — Bloom helps with visibility. Healing members get 1 listing; Creators get 5.",
      mode: "next",
      target: "showcase",
      surface: true
    },
    {
      id: "nav-support",
      path: null,
      title: "Support Groups",
      body: "Open Support Groups — peer circles and coaching when you want company on the path.",
      mode: "click",
      target: "nav-support",
      go: "/support-groups"
    },
    {
      id: "page-support",
      path: "/support-groups",
      title: "Show up together",
      body: "Healing circles for divorce, co-parenting, and starting over. Creator accountability for builders. Facilitator sessions and optional 1:1 with Ayesha or Saman when you want a guide.",
      mode: "next",
      target: "support",
      surface: true
    },
    {
      id: "nav-myspace",
      path: null,
      title: "My space",
      body: "Head to My space — your home base for check-ins, journal, activity, and courses you've kept.",
      mode: "click",
      target: "nav-myspace",
      go: "/account"
    },
    {
      id: "page-myspace",
      path: "/account",
      title: "Your quiet corner",
      body: "Check in with how you feel, keep a private journal, track streaks and participation, and revisit quotes and courses you've saved. This is for you — not the feed.",
      mode: "next",
      target: "myspace",
      surface: true
    },
    {
      id: "nav-settings",
      path: "/account",
      title: "Settings",
      body: "Open Settings to shape how you show up — photo, name, @handle, bio, badges, and privacy.",
      mode: "click",
      target: "nav-settings",
      go: "/account/settings"
    },
    {
      id: "page-settings",
      path: "/account/settings",
      title: "Make it yours",
      body: "Add an avatar, choose badges to feature, set profile links, and decide whether new community posts default to anonymous. You can change these any time.",
      mode: "next",
      target: "settings",
      surface: true
    },
    {
      id: "nav-home",
      path: null,
      title: "Home & Spotlight",
      body: "Tap the Bloom Anyway logo to visit the home page — where community spotlight lives.",
      mode: "click",
      target: "nav-home",
      go: "/"
    },
    {
      id: "page-spotlight",
      path: "/",
      title: "In the spotlight",
      body: "Creator of the Month and Reel of the Week celebrate members who show up. Join Creator Membership later if you want a shot at the spotlight — for now, just know it's here.",
      mode: "next",
      target: "spotlight",
      surface: true
    },
    {
      id: "finish",
      path: null,
      title: "You're ready",
      body: "That's the map. Start with a check-in in My space, join a circle when you feel ready, or wander Courses & Guides. Bloom anyway — one honest day at a time.",
      mode: "done",
      nextLabel: "Begin my journey"
    }
  ];

  var stepIndex = 0;
  var spot = null;
  var dim = null;
  var ui = null;
  var bubble = null;
  var resizeTimer = null;
  var activeEl = null;

  function pathMatches(step) {
    if (!step.path) return true;
    var path = window.location.pathname.replace(/\/$/, "") || "/";
    var want = step.path.replace(/\/$/, "") || "/";
    if (want === "/account") return path === "/account";
    if (want === "/") return path === "/";
    return path === want || path.indexOf(want + "/") === 0;
  }

  function findTarget(name, asSurface) {
    if (!name) return null;
    var sel = asSurface
      ? '[data-tour-surface="' + name + '"]'
      : '[data-tour-target="' + name + '"]';
    var nodes = document.querySelectorAll(sel);
    var i, el, style;
    for (i = 0; i < nodes.length; i++) {
      el = nodes[i];
      style = window.getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (el.getClientRects().length) return el;
    }
    return nodes[0] || null;
  }

  function openMobileNavIfNeeded(el) {
    if (!el) return;
    var drawer = document.getElementById("nav-drawer");
    var toggle = document.querySelector(".nav-toggle");
    if (!drawer || !toggle) return;
    if (drawer.contains(el) && !drawer.classList.contains("is-open")) {
      toggle.click();
    }
  }

  function clearHot() {
    document.querySelectorAll(".is-tour-hot").forEach(function (el) {
      el.classList.remove("is-tour-hot");
    });
    activeEl = null;
  }

  function targetRect(el) {
    var r = el.getBoundingClientRect();
    var padX = el.closest(".nav-links, .nav-drawer, .myspace-tabs") ? 12 : 10;
    var padY = el.closest(".nav-links, .nav-drawer, .myspace-tabs") ? 8 : 10;
    var top = Math.round(r.top - padY);
    var left = Math.round(r.left - padX);
    var width = Math.max(44, Math.round(r.width + padX * 2));
    var height = Math.max(32, Math.round(r.height + padY * 2));
    return {
      top: top,
      left: left,
      width: width,
      height: height,
      right: left + width,
      bottom: top + height,
      midY: r.top + r.height / 2,
      midX: r.left + r.width / 2
    };
  }

  function placeSpot(el) {
    if (!spot || !dim) return;
    if (!el) {
      spot.hidden = true;
      dim.hidden = false;
      return;
    }
    dim.hidden = true;
    spot.hidden = false;
    var box = targetRect(el);
    spot.style.top = box.top + "px";
    spot.style.left = box.left + "px";
    spot.style.width = box.width + "px";
    spot.style.height = box.height + "px";
    // Exact pill: radius is half the height so border matches the clear cutout
    spot.style.borderRadius = Math.round(box.height / 2) + "px";
  }

  function fillActions(step) {
    var actions = bubble.querySelector("[data-tour-actions]");
    actions.innerHTML = "";

    if (stepIndex > 0) {
      var back = document.createElement("button");
      back.type = "button";
      back.className = "btn btn--secondary btn--sm";
      back.textContent = "Back";
      back.addEventListener("click", goBack);
      actions.appendChild(back);
    }

    if (step.mode === "next" || step.mode === "done") {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn--primary btn--sm";
      btn.textContent = step.nextLabel || (step.mode === "done" ? "Begin my journey" : "Next");
      btn.addEventListener("click", function () {
        if (step.mode === "done") finishTour();
        else advance(1);
      });
      actions.appendChild(btn);
    } else {
      var hint = document.createElement("p");
      hint.className = "tour-bubble__hint";
      hint.textContent = "Click the highlighted control to continue";
      actions.appendChild(hint);
      if (step.go) {
        var goBtn = document.createElement("button");
        goBtn.type = "button";
        goBtn.className = "btn btn--primary btn--sm";
        goBtn.textContent = "Open it";
        goBtn.addEventListener("click", function () {
          try {
            sessionStorage.setItem(STEP_KEY, String(stepIndex + 1));
            sessionStorage.setItem(ACTIVE_KEY, "1");
          } catch (err) {}
          window.location.href = step.go;
        });
        actions.appendChild(goBtn);
      }
    }
  }

  function placeBubble(el, step) {
    if (!bubble) return;
    bubble.querySelector("[data-tour-title]").textContent = step.title;
    bubble.querySelector("[data-tour-body]").textContent = step.body;
    fillActions(step);
    bubble.hidden = false;

    if (!el || step.id === "welcome" || step.id === "finish") {
      bubble.classList.add("tour-bubble--center");
      bubble.style.top = "";
      bubble.style.left = "";
      bubble.style.right = "";
      bubble.style.transform = "";
      placeSpot(null);
      return;
    }

    bubble.classList.remove("tour-bubble--center");
    bubble.style.transform = "none";
    var bw = Math.min(340, window.innerWidth - 28);
    bubble.style.width = bw + "px";
    var bh = bubble.offsetHeight || 180;
    var box = targetRect(el);
    var gap = 14;
    var top;
    var left;
    var inHeader = !!(el.closest && el.closest(".site-header, .nav, .nav-drawer, .myspace-tabs"));

    // Keep tip clear of the sticky header so the title never sits under the nav
    var headerEl = document.querySelector(".site-header");
    var headerBottom = headerEl ? Math.ceil(headerEl.getBoundingClientRect().bottom) + 8 : 12;
    var minTop = Math.max(12, inHeader ? headerBottom : 12);

    if (inHeader && box.right + gap + bw <= window.innerWidth - 12) {
      left = box.right + gap;
      top = Math.min(Math.max(minTop, box.bottom + 6), window.innerHeight - bh - 12);
    } else if (box.bottom + gap + bh <= window.innerHeight - 12) {
      top = Math.max(minTop, box.bottom + gap);
      left = box.midX - bw / 2;
    } else if (box.left - gap - bw >= 12) {
      left = box.left - gap - bw;
      top = Math.min(Math.max(minTop, box.top), window.innerHeight - bh - 12);
    } else {
      top = Math.max(minTop, box.top - bh - gap);
      left = box.midX - bw / 2;
    }
    left = Math.max(12, Math.min(left, window.innerWidth - bw - 12));
    top = Math.max(12, Math.min(top, window.innerHeight - bh - 12));
    bubble.style.top = top + "px";
    bubble.style.left = left + "px";
    bubble.style.right = "auto";
  }

  function layoutSpotlight(el, step) {
    if (el && step && (step.mode === "click" || step.surface)) {
      placeSpot(el);
    } else if (step && (step.id === "welcome" || step.id === "finish")) {
      placeSpot(null);
    } else if (el) {
      placeSpot(el);
    } else {
      placeSpot(null);
    }
    placeBubble(el, step);
  }

  function renderStep() {
    var step = STEPS[stepIndex];
    if (!step) {
      finishTour();
      return;
    }
    try {
      sessionStorage.setItem(STEP_KEY, String(stepIndex));
      sessionStorage.setItem(ACTIVE_KEY, "1");
    } catch (e) {}

    if (step.path && !pathMatches(step)) {
      window.location.href = step.path + (step.path.indexOf("?") >= 0 ? "&" : "?") + "tour=1";
      return;
    }

    document.documentElement.classList.add("is-touring");
    clearHot();

    var el = null;
    if (step.surface) el = findTarget(step.target, true);
    else if (step.target) el = findTarget(step.target, false);

    if (el) {
      openMobileNavIfNeeded(el);
      el.classList.add("is-tour-hot");
      activeEl = el;
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    window.setTimeout(function () {
      layoutSpotlight(el, step);
    }, 120);
  }

  function advance(delta) {
    stepIndex = Math.max(0, Math.min(STEPS.length - 1, stepIndex + delta));
    renderStep();
  }

  function goBack() {
    if (stepIndex <= 0) return;
    stepIndex -= 1;
    renderStep();
  }

  function finishTour() {
    clearHot();
    document.documentElement.classList.remove("is-touring");
    if (ui) ui.hidden = true;
    try {
      sessionStorage.removeItem(STEP_KEY);
      sessionStorage.removeItem(ACTIVE_KEY);
    } catch (e) {}
    var url = body.getAttribute("data-tour-complete");
    var csrf = body.getAttribute("data-csrf") || "";
    if (!url) return;
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "fetch",
        "X-CSRFToken": csrf,
        Accept: "application/json"
      },
      body: "{}"
    }).catch(function () {});
  }

  function buildUI() {
    ui = document.createElement("div");
    ui.className = "tour-ui";
    ui.setAttribute("aria-live", "polite");
    ui.innerHTML =
      '<div class="tour-skip-wrap">' +
      '<button type="button" class="tour-skip" data-tour-skip>Skip tour</button>' +
      "</div>" +
      '<div class="tour-dim" data-tour-dim hidden></div>' +
      '<div class="tour-spot" data-tour-spot hidden></div>' +
      '<div class="tour-bubble" data-tour-bubble hidden role="dialog" aria-modal="true">' +
      '<p class="tour-bubble__eyebrow">Quick tour</p>' +
      "<h3 data-tour-title></h3>" +
      "<p data-tour-body></p>" +
      '<div class="tour-bubble__actions" data-tour-actions></div>' +
      "</div>";
    document.body.appendChild(ui);
    dim = ui.querySelector("[data-tour-dim]");
    spot = ui.querySelector("[data-tour-spot]");
    bubble = ui.querySelector("[data-tour-bubble]");
    ui.querySelector("[data-tour-skip]").addEventListener("click", finishTour);

    document.addEventListener(
      "click",
      function (e) {
        if (!document.documentElement.classList.contains("is-touring")) return;
        var step = STEPS[stepIndex];
        if (!step || step.mode !== "click") {
          if (e.target.closest && e.target.closest(".tour-ui")) return;
          if (step && (step.mode === "next" || step.mode === "done")) {
            e.preventDefault();
            e.stopPropagation();
          }
          return;
        }
        var hot = e.target && e.target.closest ? e.target.closest(".is-tour-hot") : null;
        if (!hot) {
          if (e.target.closest && e.target.closest(".tour-ui")) return;
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        try {
          sessionStorage.setItem(STEP_KEY, String(stepIndex + 1));
          sessionStorage.setItem(ACTIVE_KEY, "1");
        } catch (err) {}
      },
      true
    );

    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () {
        if (!document.documentElement.classList.contains("is-touring")) return;
        var step = STEPS[stepIndex];
        if (!step) return;
        layoutSpotlight(activeEl, step);
      }, 120);
    });
    window.addEventListener(
      "scroll",
      function () {
        if (!document.documentElement.classList.contains("is-touring")) return;
        var step = STEPS[stepIndex];
        if (!step) return;
        layoutSpotlight(activeEl, step);
      },
      { passive: true }
    );
  }

  function start() {
    buildUI();
    var active = false;
    var saved = 0;
    try {
      active = sessionStorage.getItem(ACTIVE_KEY) === "1";
      saved = parseInt(sessionStorage.getItem(STEP_KEY) || "0", 10) || 0;
    } catch (e) {}

    var path = window.location.pathname.replace(/\/$/, "") || "/";
    var onAccount = path === "/account";
    var forced = /(?:\?|&)tour=1(?:&|$)/.test(window.location.search);

    if (!active && !forced && !onAccount) return;

    if (!active && onAccount) stepIndex = 0;
    else stepIndex = Math.max(0, Math.min(STEPS.length - 1, saved));

    if (active || forced) {
      for (var i = stepIndex; i < STEPS.length; i++) {
        if (STEPS[i].path && pathMatches(STEPS[i])) {
          stepIndex = i;
          break;
        }
      }
    }
    renderStep();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
