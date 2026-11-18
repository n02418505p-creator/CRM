(function () {
  "use strict";

  // Clickable table rows
  document.querySelectorAll("tr[data-href]").forEach(function (row) {
    row.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, select")) { return; }
      window.location = row.getAttribute("data-href");
    });
  });

  // Light / dark theme
  var themeBtn = document.getElementById("themeBtn");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("mmc-theme", next); } catch (e) {}
    });
  }

  // Notification bell
  var btn = document.getElementById("bellBtn");
  var menu = document.getElementById("bellMenu");
  if (btn && menu) {
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = menu.hidden;
      menu.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", function (e) {
      if (!menu.hidden && !menu.contains(e.target)) {
        menu.hidden = true;
        btn.setAttribute("aria-expanded", "false");
      }
    });
  }

  // Desktop alerts (optional, per browser)
  var deskBtn = document.getElementById("desktopAlerts");
  function deskState() {
    if (!deskBtn) { return; }
    if (!("Notification" in window)) { deskBtn.hidden = true; return; }
    deskBtn.textContent = Notification.permission === "granted" ? "Desktop alerts on" : "Turn on desktop alerts";
    deskBtn.disabled = Notification.permission === "granted";
  }
  if (deskBtn) {
    deskState();
    deskBtn.addEventListener("click", function () {
      Notification.requestPermission().then(deskState);
    });
  }

  // Poll for new notifications
  var script = document.currentScript || document.querySelector("script[data-feed]");
  var feed = script && script.getAttribute("data-feed");
  if (!feed) { return; }
  var lastId = parseInt(script.getAttribute("data-latest") || "0", 10);
  var baseTitle = document.title.replace(/^\(\d+\)\s*/, "");
  var badge = document.getElementById("bellCount");
  var navCount = document.getElementById("navCount");
  var toast = document.getElementById("toast");

  function setCount(n) {
    [badge, navCount].forEach(function (el) {
      if (!el) { return; }
      el.textContent = n > 99 ? "99+" : String(n);
      el.hidden = n === 0;
    });
    document.title = (n ? "(" + n + ") " : "") + baseTitle;
  }

  function showToast(item) {
    if (!toast) { return; }
    toast.innerHTML = "";
    var eyebrow = document.createElement("p");
    eyebrow.className = "eyebrow";
    eyebrow.textContent = "Notification";
    var link = document.createElement("a");
    link.href = item.url;
    link.textContent = item.message;
    toast.appendChild(eyebrow);
    toast.appendChild(link);
    toast.hidden = false;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(function () { toast.hidden = true; }, 9000);
  }

  function desktop(item) {
    if (!("Notification" in window) || Notification.permission !== "granted") { return; }
    var n = new Notification("MMC Complaints", { body: item.message, tag: "mmc-" + item.id });
    n.onclick = function () { window.focus(); window.location = item.url; };
  }

  function poll() {
    fetch(feed + "?since=" + lastId, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) { return; }
        setCount(data.unread);
        if (data.items && data.items.length) {
          showToast(data.items[0]);
          data.items.forEach(desktop);
        }
        lastId = Math.max(lastId, data.latest_id || 0);
      })
      .catch(function () {});
  }
  setInterval(poll, 45000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { poll(); } });
})();
