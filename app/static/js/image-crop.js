/* Shared image crop dialog: drag to reposition, zoom, aspect-aware export. */
(function () {
  "use strict";

  function parseAspect(raw, fallbackW, fallbackH) {
    var text = String(raw || "").trim();
    var m = text.match(/^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/);
    if (!m) return { w: fallbackW, h: fallbackH };
    var w = parseFloat(m[1]);
    var h = parseFloat(m[2]);
    if (!(w > 0) || !(h > 0)) return { w: fallbackW, h: fallbackH };
    return { w: w, h: h };
  }

  function isImageFile(file) {
    if (!file) return false;
    if (file.type && file.type.indexOf("image/") === 0) return true;
    return /\.(jpe?g|png|gif|webp|bmp|heic|heif)$/i.test(file.name || "");
  }

  function bindCropper(dialog) {
    if (!dialog || dialog._cropBound) return;
    dialog._cropBound = true;

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
    var title = dialog.querySelector("[data-crop-title]");
    if (!stage || !img || !zoom || !applyBtn || !cancelBtn) return;

    var objectUrl = null;
    var natural = { w: 0, h: 0 };
    var aspect = { w: 1, h: 1 };
    var state = { scale: 1, x: 0, y: 0, dragging: false, lastX: 0, lastY: 0 };
    var activeInput = null;
    var previewEl = null;
    var outMax = 1200;
    var filename = "crop.jpg";

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

    function stageBox() {
      var maxW = Math.min(320, stage.parentElement ? stage.parentElement.clientWidth - 8 : 320);
      if (!(maxW > 40)) maxW = 280;
      var ratio = aspect.w / aspect.h;
      var w = maxW;
      var h = Math.round(w / ratio);
      var maxH = Math.min(360, window.innerHeight * 0.45);
      if (h > maxH) {
        h = maxH;
        w = Math.round(h * ratio);
      }
      stage.style.width = w + "px";
      stage.style.height = h + "px";
      return { w: w, h: h };
    }

    function fitScale() {
      var box = stageBox();
      if (!natural.w || !natural.h) return 1;
      return Math.max(box.w / natural.w, box.h / natural.h);
    }

    function render() {
      if (!natural.w || !natural.h) return;
      var box = stageBox();
      var min = fitScale();
      var scale = Math.max(min, state.scale || min);
      state.scale = scale;
      var w = natural.w * scale;
      var h = natural.h * scale;
      var maxX = Math.max(0, (w - box.w) / 2);
      var maxY = Math.max(0, (h - box.h) / 2);
      state.x = Math.max(-maxX, Math.min(maxX, state.x));
      state.y = Math.max(-maxY, Math.min(maxY, state.y));
      img.style.width = w + "px";
      img.style.height = h + "px";
      img.style.transform =
        "translate(calc(-50% + " + state.x + "px), calc(-50% + " + state.y + "px))";
      var zoomPct = Math.round((scale / min) * 100);
      zoom.value = String(Math.max(100, Math.min(300, zoomPct)));
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
      setHelp("Drag to reposition. Use the slider to zoom. The frame is exactly what visitors will see.");
      render();
      requestAnimationFrame(render);
    }

    function loadFile(file) {
      setHelp("Loading your picture…");
      openDialog();
      revokePreview();
      img.onload = onImageReady;
      img.onerror = function () {
        setHelp("That image couldn't be previewed. Try a JPG, PNG, or WEBP.");
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
          setHelp("That image couldn't be read. Try a JPG or PNG.");
        };
        reader.readAsDataURL(file);
      }
    }

    function closeCrop(clearInput) {
      closeDialog();
      revokePreview();
      img.removeAttribute("src");
      natural.w = 0;
      natural.h = 0;
      if (clearInput && activeInput) {
        activeInput.value = "";
      }
      activeInput = null;
      previewEl = null;
    }

    function finishPreview(url) {
      if (!previewEl) return;
      if (previewEl.tagName === "IMG") {
        previewEl.src = url;
        previewEl.hidden = false;
      } else {
        previewEl.style.backgroundImage = "url('" + url + "')";
      }
      var wrap = previewEl.closest("[data-crop-preview-wrap]");
      if (wrap) wrap.removeAttribute("data-empty");
    }

    cancelBtn.addEventListener("click", function (e) {
      e.preventDefault();
      closeCrop(true);
    });
    dialog.addEventListener("cancel", function (e) {
      e.preventDefault();
      closeCrop(true);
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

    applyBtn.addEventListener("click", function (e) {
      e.preventDefault();
      if (!natural.w || !natural.h || !activeInput) return;
      var box = stageBox();
      var min = fitScale();
      var scale = Math.max(min, state.scale);
      var outW = outMax;
      var outH = Math.round(outMax * (aspect.h / aspect.w));
      if (aspect.h > aspect.w) {
        outH = outMax;
        outW = Math.round(outMax * (aspect.w / aspect.h));
      }
      var canvas = document.createElement("canvas");
      canvas.width = outW;
      canvas.height = outH;
      var ctx = canvas.getContext("2d");
      if (!ctx) return;
      var srcW = box.w / scale;
      var srcH = box.h / scale;
      var srcX = (natural.w / 2) - (srcW / 2) - (state.x / scale);
      var srcY = (natural.h / 2) - (srcH / 2) - (state.y / scale);
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, outW, outH);
      try {
        ctx.drawImage(img, srcX, srcY, srcW, srcH, 0, 0, outW, outH);
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
          var cropped = new File([blob], filename, { type: "image/jpeg" });
          var dt = new DataTransfer();
          dt.items.add(cropped);
          activeInput.files = dt.files;
        } catch (err) {}
        finishPreview(URL.createObjectURL(blob));
        var clearName = activeInput.getAttribute("data-clear-checkbox");
        if (clearName) {
          var clearBox = document.querySelector("input[name='" + clearName + "']");
          if (clearBox) clearBox.checked = false;
        }
        closeCrop(false);
      }, "image/jpeg", 0.92);
    });

    window.addEventListener("resize", function () {
      if ((dialog.open || dialog.hasAttribute("open")) && natural.w) render();
    });

    dialog._openCrop = function (input, file) {
      activeInput = input;
      aspect = parseAspect(input.getAttribute("data-crop-aspect"), 1, 1);
      outMax = parseInt(input.getAttribute("data-crop-size"), 10) || 1200;
      filename = input.getAttribute("data-crop-filename") || "crop.jpg";
      var previewSel = input.getAttribute("data-crop-preview");
      previewEl = previewSel ? document.querySelector(previewSel) : null;
      stage.classList.toggle("avatar-crop__stage--circle",
        input.getAttribute("data-crop-shape") === "circle");
      stage.classList.toggle("avatar-crop__stage--rect",
        input.getAttribute("data-crop-shape") !== "circle");
      if (title) {
        title.textContent = input.getAttribute("data-crop-title") || "Crop image";
      }
      loadFile(file);
    };
  }

  function init() {
    var dialog = document.getElementById("site-image-crop");
    if (!dialog) return;
    bindCropper(dialog);

    document.querySelectorAll("input[type='file'][data-site-crop]").forEach(function (input) {
      if (input._siteCropBound) return;
      input._siteCropBound = true;
      input.addEventListener("change", function () {
        var file = input.files && input.files[0];
        if (!file) return;
        if (!isImageFile(file)) {
          input.value = "";
          window.alert("Please choose an image file (JPG, PNG, or WEBP).");
          return;
        }
        if (dialog._openCrop) dialog._openCrop(input, file);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
