// Progressive enhancement only. All content is static (generated at build time),
// so this script never fetches or injects remote data - it just wires up the
// copy-to-clipboard buttons and the footer year.
(function () {
  "use strict";

  function initCopyButtons() {
    var buttons = document.querySelectorAll(".copy-btn[data-copy]");
    buttons.forEach(function (btn) {
      var original = btn.textContent;
      var timer = null;
      var restore = function () {
        btn.classList.remove("copied", "copy-failed");
        btn.textContent = original;
      };
      btn.addEventListener("click", function () {
        var text = btn.getAttribute("data-copy") || "";
        if (timer) {
          window.clearTimeout(timer);
        }
        var done = function () {
          btn.classList.remove("copy-failed");
          btn.classList.add("copied");
          btn.textContent = "copied";
          timer = window.setTimeout(restore, 1500);
        };
        var fail = function () {
          btn.classList.remove("copied");
          btn.classList.add("copy-failed");
          btn.textContent = "press Ctrl+C";
          timer = window.setTimeout(restore, 2000);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () {
            fallbackCopy(text, done, fail);
          });
        } else {
          fallbackCopy(text, done, fail);
        }
      });
    });
  }

  function fallbackCopy(text, done, fail) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(ta);
    if (ok) {
      done();
    } else if (fail) {
      fail();
    }
  }

  function initYear() {
    var el = document.getElementById("year");
    if (el) {
      el.textContent = String(new Date().getFullYear());
    }
  }

  function initDemoSwitch() {
    var tabs = document.querySelectorAll(".demo-tab");
    var frame = document.getElementById("demo-iframe");
    var panel = document.getElementById("demo-panel");
    var filename = document.getElementById("demo-filename");
    var fullscreen = document.getElementById("demo-fullscreen");
    if (!tabs.length || !frame) {
      return;
    }
    var tabList = Array.prototype.slice.call(tabs);

    function activate(tab, focusIt) {
      var src = tab.getAttribute("data-demo");
      var file = tab.getAttribute("data-file") || src;
      tabList.forEach(function (t) {
        var active = t === tab;
        t.classList.toggle("active", active);
        t.setAttribute("aria-selected", active ? "true" : "false");
        t.setAttribute("tabindex", active ? "0" : "-1");
      });
      if (frame.getAttribute("src") !== src) {
        frame.setAttribute("src", src);
      }
      frame.setAttribute("title", "Live commentable-html demo: " + file);
      if (panel && tab.id) {
        panel.setAttribute("aria-labelledby", tab.id);
      }
      if (filename) {
        filename.textContent = file;
      }
      if (fullscreen) {
        fullscreen.setAttribute("href", src);
      }
      if (focusIt) {
        tab.focus();
      }
    }

    tabList.forEach(function (tab, i) {
      tab.addEventListener("click", function () {
        activate(tab, false);
      });
      tab.addEventListener("keydown", function (e) {
        var last = tabList.length - 1;
        var next = null;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") {
          next = i >= last ? 0 : i + 1;
        } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
          next = i <= 0 ? last : i - 1;
        } else if (e.key === "Home") {
          next = 0;
        } else if (e.key === "End") {
          next = last;
        }
        if (next === null) {
          return;
        }
        e.preventDefault();
        activate(tabList[next], true);
      });
    });
  }

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  ready(function () {
    initCopyButtons();
    initYear();
    initDemoSwitch();
  });
})();
