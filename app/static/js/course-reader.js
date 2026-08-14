/* Bloom Anyway — on-site course reader (PDF one-page, H5P, media). */
(function () {
  "use strict";

  var root = document.querySelector(".course-reader-page");
  if (!root) return;

  var kind = root.getAttribute("data-asset-kind") || "";
  var fileUrl = root.getAttribute("data-file-url") || "";
  var progressUrl = root.getAttribute("data-progress-url") || "";
  var startPage = parseInt(root.getAttribute("data-start-page") || "1", 10) || 1;
  var startPercent = parseInt(root.getAttribute("data-start-percent") || "0", 10) || 0;
  var csrf = (document.body && document.body.getAttribute("data-csrf")) || "";

  var pill = document.getElementById("reader-progress-label");
  var pageInput = document.getElementById("reader-page");
  var totalEl = document.getElementById("reader-total");
  var statusEl = document.getElementById("reader-pdf-status");
  var canvas = document.getElementById("reader-pdf-canvas");

  var state = {
    page: Math.max(1, startPage),
    total: 0,
    percent: startPercent,
    saving: false,
    pdf: null,
    renderToken: 0,
  };

  function setPill() {
    if (!pill) return;
    pill.textContent = state.percent + "% complete";
  }

  function computePercent() {
    if (state.total > 0) {
      state.percent = Math.max(
        0,
        Math.min(100, Math.round((100 * state.page) / state.total))
      );
    }
    setPill();
  }

  function saveProgress(opts) {
    if (!progressUrl || !csrf) return;
    var body = {
      page: state.page,
      total: state.total,
      percent: state.percent,
    };
    if (opts && typeof opts.percent === "number") {
      body.percent = opts.percent;
      state.percent = opts.percent;
      setPill();
    }
    // fire-and-forget; keep UI snappy
    try {
      navigator.sendBeacon && false; // prefer fetch with keepalive
    } catch (e) {}
    fetch(progressUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
        "X-Requested-With": "fetch",
      },
      body: JSON.stringify(body),
      credentials: "same-origin",
      keepalive: true,
    }).catch(function () {});
  }

  function saveSoon() {
    if (state.saving) return;
    state.saving = true;
    window.setTimeout(function () {
      state.saving = false;
      saveProgress();
    }, 250);
  }

  window.addEventListener("pagehide", function () {
    saveProgress();
  });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") saveProgress();
  });

  /* ---- PDF (pdf.js, one page at a time) ---- */
  function bootPdf() {
    if (!canvas || !fileUrl || !window.pdfjsLib) {
      if (statusEl) statusEl.textContent = "PDF viewer failed to load.";
      return;
    }
    var pdfjsLib = window.pdfjsLib;
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";

    pdfjsLib
      .getDocument({ url: fileUrl, withCredentials: true })
      .promise.then(function (pdf) {
        state.pdf = pdf;
        state.total = pdf.numPages || 0;
        if (totalEl) totalEl.textContent = String(state.total || "—");
        if (state.page > state.total && state.total > 0) state.page = state.total;
        if (pageInput) {
          pageInput.max = String(state.total || 1);
          pageInput.value = String(state.page);
        }
        computePercent();
        return renderPage(state.page);
      })
      .then(function () {
        saveProgress();
      })
      .catch(function () {
        if (statusEl) statusEl.textContent = "Could not open this PDF.";
      });

    function renderPage(num) {
      if (!state.pdf) return Promise.resolve();
      var token = ++state.renderToken;
      if (statusEl) statusEl.textContent = "Loading page " + num + "…";
      return state.pdf.getPage(num).then(function (page) {
        if (token !== state.renderToken) return;
        var wrap = canvas.parentElement;
        var maxWidth = Math.min((wrap && wrap.clientWidth) || 800, 920);
        var unscaled = page.getViewport({ scale: 1 });
        var scale = maxWidth / unscaled.width;
        var viewport = page.getViewport({ scale: scale });
        var outputScale = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = Math.floor(viewport.width) + "px";
        canvas.style.height = Math.floor(viewport.height) + "px";
        var ctx = canvas.getContext("2d");
        var transform =
          outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null;
        return page
          .render({ canvasContext: ctx, viewport: viewport, transform: transform })
          .promise.then(function () {
            if (statusEl) statusEl.textContent = "";
          });
      });
    }

    function go(to) {
      if (!state.total) return;
      var next = Math.max(1, Math.min(state.total, to));
      state.page = next;
      if (pageInput) pageInput.value = String(state.page);
      computePercent();
      renderPage(state.page).then(saveSoon);
    }

    var prev = document.getElementById("reader-prev");
    var nextBtn = document.getElementById("reader-next");
    if (prev) prev.addEventListener("click", function () { go(state.page - 1); });
    if (nextBtn) nextBtn.addEventListener("click", function () { go(state.page + 1); });
    if (pageInput) {
      pageInput.addEventListener("change", function () {
        go(parseInt(pageInput.value, 10) || 1);
      });
    }
  }

  /* ---- Text / HTML ---- */
  function bootText() {
    var el = document.getElementById("reader-text");
    if (!el || !fileUrl) return;
    fetch(fileUrl, { credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (text) {
        if (kind === "html") {
          el.innerHTML = text;
        } else {
          el.textContent = text;
          el.style.whiteSpace = "pre-wrap";
        }
        state.total = 1;
        state.page = 1;
        if (state.percent < 5) state.percent = 5;
        computePercent();
        saveProgress();
      })
      .catch(function () {
        el.textContent = "Could not load this file.";
      });
  }

  /* ---- H5P ---- */
  function bootH5p() {
    var mount = document.getElementById("reader-h5p");
    var base = (root.getAttribute("data-h5p-path") || "").replace(/\/?$/, "/");
    if (!mount || !base || !window.H5PStandalone) {
      if (mount) mount.innerHTML = "<p class=\"field-help\">Could not load H5P player.</p>";
      return;
    }
    mount.innerHTML = "";
    var options = {
      h5pJsonPath: base,
      frameJs:
        "https://cdn.jsdelivr.net/npm/h5p-standalone@3.7.0/dist/frame.bundle.js",
      frameCss:
        "https://cdn.jsdelivr.net/npm/h5p-standalone@3.7.0/dist/styles/h5p.css",
    };
    Promise.resolve(new window.H5PStandalone.H5P(mount, options))
      .then(function () {
        state.total = 1;
        state.page = 1;
        if (state.percent < 8) {
          state.percent = Math.max(state.percent, 8);
        }
        setPill();
        saveProgress();
      })
      .catch(function () {
        mount.innerHTML = "<p class=\"field-help\">Could not open this H5P package.</p>";
      });
  }

  /* ---- Media / mark complete ---- */
  function bootSimpleMedia() {
    state.total = 1;
    state.page = 1;
    if (state.percent < 5) state.percent = 5;
    setPill();
    saveProgress();
  }

  var markBtn = document.getElementById("reader-mark-done");
  if (markBtn) {
    markBtn.addEventListener("click", function () {
      state.page = Math.max(state.page, state.total || 1);
      state.total = Math.max(state.total, 1);
      saveProgress({ percent: 100 });
      markBtn.textContent = "Completed";
      markBtn.disabled = true;
    });
  }

  setPill();

  if (kind === "pdf") {
    function waitPdf() {
      if (window.pdfjsLib) bootPdf();
      else window.setTimeout(waitPdf, 40);
    }
    waitPdf();
  } else if (kind === "h5p") {
    function waitH5p() {
      if (window.H5PStandalone) bootH5p();
      else window.setTimeout(waitH5p, 40);
    }
    waitH5p();
  } else if (kind === "text" || kind === "html") {
    bootText();
  } else if (kind === "image" || kind === "video" || kind === "audio") {
    bootSimpleMedia();
  }
})();
