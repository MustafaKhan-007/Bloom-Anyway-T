/* Bloom Anyway — branded file pickers (replaces native "Choose file") */
(function () {
  "use strict";

  function formatBytes(n) {
    if (!n && n !== 0) return "";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(n < 10 * 1024 ? 1 : 0) + " KB";
    return (n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + " MB";
  }

  function labelFor(input, files) {
    if (!files || !files.length) {
      return input.multiple ? "No files chosen" : "No file chosen";
    }
    if (files.length === 1) {
      var one = files[0];
      var size = formatBytes(one.size);
      return size ? one.name + " · " + size : one.name;
    }
    var total = 0;
    for (var i = 0; i < files.length; i++) total += files[i].size || 0;
    return files.length + " files · " + formatBytes(total);
  }

  function enhance(input) {
    if (!input || input.dataset.filePick === "1") return;
    if (input.classList.contains("sr-only")) return;
    if (input.closest(".avatar-edit") || input.closest(".file-pick")) return;

    input.dataset.filePick = "1";
    var wrap = document.createElement("div");
    wrap.className = "file-pick";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "file-pick__btn";
    btn.textContent = input.multiple ? "Choose files" : "Choose file";

    var name = document.createElement("span");
    name.className = "file-pick__name";
    name.textContent = labelFor(input, input.files);

    var clear = document.createElement("button");
    clear.type = "button";
    clear.className = "file-pick__clear";
    clear.textContent = "Clear";
    clear.hidden = !(input.files && input.files.length);
    if (input.required) clear.hidden = true;

    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(btn);
    wrap.appendChild(name);
    wrap.appendChild(clear);
    wrap.appendChild(input);
    input.classList.add("file-pick__input");

    function sync() {
      var files = input.files;
      var has = !!(files && files.length);
      wrap.classList.toggle("has-file", has);
      name.textContent = labelFor(input, files);
      clear.hidden = !has || input.required;
      btn.textContent = has
        ? (input.multiple ? "Change files" : "Change file")
        : (input.multiple ? "Choose files" : "Choose file");
    }

    btn.addEventListener("click", function () { input.click(); });
    clear.addEventListener("click", function () {
      input.value = "";
      sync();
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    input.addEventListener("change", sync);
    sync();
  }

  document.querySelectorAll('input[type="file"]').forEach(enhance);
})();
