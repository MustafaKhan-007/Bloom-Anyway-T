/* Support session waiting room — countdown + live seat poll (CSP-safe). */
(function () {
  function boot() {
    var root = document.querySelector("[data-sg-wait]");
    if (!root) return;

    function parseTime(raw) {
      if (!raw) return NaN;
      var n = Number(raw);
      if (isFinite(n) && n > 1e11) return n; // epoch ms
      if (isFinite(n) && n > 1e9) return n * 1000; // epoch sec
      var parsed = Date.parse(String(raw).trim());
      return parsed;
    }

    var startsAt = parseTime(root.getAttribute("data-starts-ms") || root.getAttribute("data-starts-at"));
    var serverNow = parseTime(root.getAttribute("data-server-ms") || root.getAttribute("data-server-now"));
    var skew = (isFinite(serverNow) ? serverNow : Date.now()) - Date.now();
    var roomUrl = root.getAttribute("data-room-url") || "";
    var statusUrl = root.getAttribute("data-status-url") || "";
    var capacity = parseInt(root.getAttribute("data-capacity") || "8", 10) || 8;
    var countdownEl = root.querySelector("[data-sg-countdown]");
    var subEl = root.querySelector("[data-sg-subcount]");
    var seatCountEl = root.querySelector("[data-sg-seat-count]");
    var membersEl = root.querySelector("[data-sg-members]");
    var redirected = false;
    var pollTimer = null;
    var tickTimer = null;

    function nowMs() { return Date.now() + skew; }

    function pad(n) { return String(n).padStart(2, "0"); }

    function formatLeft(ms) {
      var totalSec = Math.max(0, Math.floor(ms / 1000));
      var d = Math.floor(totalSec / 86400);
      var h = Math.floor((totalSec % 86400) / 3600);
      var m = Math.floor((totalSec % 3600) / 60);
      var s = totalSec % 60;
      if (d > 0) return d + "d " + pad(h) + ":" + pad(m) + ":" + pad(s);
      if (h > 0) return pad(h) + ":" + pad(m) + ":" + pad(s);
      return pad(m) + ":" + pad(s);
    }

    function go(url) {
      if (redirected || !url) return;
      redirected = true;
      if (pollTimer) clearInterval(pollTimer);
      if (tickTimer) clearTimeout(tickTimer);
      if (countdownEl) countdownEl.textContent = "Opening…";
      if (subEl) subEl.textContent = "Taking you into the room";
      window.location.href = url;
    }

    function renderMembers(members) {
      if (!membersEl) return;
      members = members || [];
      if (!members.length) {
        membersEl.innerHTML = '<li class="sg-wait__member sg-wait__member--empty">No one seated yet</li>';
        return;
      }
      membersEl.innerHTML = members.map(function (m) {
        var cls = "sg-wait__member"
          + (m.is_you ? " is-you" : "")
          + (m.is_host ? " is-host" : "");
        var tags = "";
        if (m.is_host) tags += '<span class="sg-wait__tag">Host</span>';
        if (m.is_you) tags += '<span class="sg-wait__tag sg-wait__tag--you">You</span>';
        var name = (m.name || "Member").replace(/[<>&"]/g, function (c) {
          return ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" })[c];
        });
        return '<li class="' + cls + '"><span class="sg-wait__member-name">' + name
          + "</span>" + tags + "</li>";
      }).join("");
    }

    function applyStatus(data) {
      if (!data) return;
      if (data.server_now) {
        var sn = parseTime(data.server_now);
        if (isFinite(sn)) skew = sn - Date.now();
      }
      if (data.server_ms != null) {
        var sm = parseTime(data.server_ms);
        if (isFinite(sm)) skew = sm - Date.now();
      }
      if (data.starts_at) {
        var sa = parseTime(data.starts_at);
        if (isFinite(sa)) startsAt = sa;
      }
      if (data.starts_ms != null) {
        var st = parseTime(data.starts_ms);
        if (isFinite(st)) startsAt = st;
      }
      if (typeof data.capacity === "number" && data.capacity > 0) capacity = data.capacity;
      if (typeof data.seats === "number" && seatCountEl) {
        seatCountEl.textContent = data.seats + " / " + capacity + " seats";
      }
      if (data.members) renderMembers(data.members);

      if (data.phase === "live") {
        go(data.room_url || roomUrl);
        return;
      }
      if (data.phase === "ended") {
        go(data.wrap_url || "/support-groups");
        return;
      }
      if (data.phase === "unavailable" || data.phase === "forbidden") {
        if (subEl) subEl.textContent = "This session is no longer available.";
        redirected = true;
        if (pollTimer) clearInterval(pollTimer);
      }
    }

    function tick() {
      if (redirected) return;
      if (!isFinite(startsAt)) {
        if (countdownEl) countdownEl.textContent = "--:--";
        if (subEl) subEl.textContent = "Session time unavailable — try refreshing";
        return;
      }
      var left = startsAt - nowMs();
      if (left <= 0) {
        if (countdownEl) countdownEl.textContent = "00:00";
        if (subEl) subEl.textContent = "Checking with the server…";
        pollOnce();
        tickTimer = window.setTimeout(tick, 1000);
        return;
      }
      if (countdownEl) countdownEl.textContent = formatLeft(left);
      if (subEl) {
        if (left < 60000) subEl.textContent = "Almost time — hang tight";
        else subEl.textContent = "Updates live — no need to refresh";
      }
      tickTimer = window.setTimeout(tick, 250);
    }

    function pollOnce() {
      if (!statusUrl || redirected) return;
      fetch(statusUrl, {
        headers: { "Accept": "application/json" },
        credentials: "same-origin"
      })
        .then(function (r) {
          if (r.status === 403) return { phase: "forbidden" };
          if (!r.ok) throw new Error("status " + r.status);
          return r.json();
        })
        .then(applyStatus)
        .catch(function () {
          if (subEl && !redirected) subEl.textContent = "Reconnecting…";
        });
    }

    tick();
    pollOnce();
    pollTimer = window.setInterval(pollOnce, 2500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
