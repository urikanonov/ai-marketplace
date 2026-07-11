// Progressive enhancement only. All content is static (generated at build time),
// so this script never fetches or injects remote data - it just wires up the
// copy-to-clipboard buttons and the footer year.
(function () {
  "use strict";

  function initCopyButtons() {
    var buttons = document.querySelectorAll(".copy-btn[data-copy]");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var text = btn.getAttribute("data-copy") || "";
        var done = function () {
          var original = btn.textContent;
          btn.classList.add("copied");
          btn.textContent = "copied";
          window.setTimeout(function () {
            btn.classList.remove("copied");
            btn.textContent = original;
          }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, fallbackCopy.bind(null, text, done));
        } else {
          fallbackCopy(text, done);
        }
      });
    });
  }

  function fallbackCopy(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      done();
    } catch (e) {
      /* clipboard unavailable; leave the command visible for manual copy */
    }
    document.body.removeChild(ta);
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
    var filename = document.getElementById("demo-filename");
    var fullscreen = document.getElementById("demo-fullscreen");
    if (!tabs.length || !frame) {
      return;
    }
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var src = tab.getAttribute("data-demo");
        var file = tab.getAttribute("data-file") || src;
        tabs.forEach(function (t) {
          var active = t === tab;
          t.classList.toggle("active", active);
          t.setAttribute("aria-selected", active ? "true" : "false");
        });
        if (frame.getAttribute("src") !== src) {
          frame.setAttribute("src", src);
        }
        if (filename) {
          filename.textContent = file;
        }
        if (fullscreen) {
          fullscreen.setAttribute("href", src);
        }
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
