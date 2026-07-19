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
      var status = document.createElement("span");
      status.className = "copy-status";
      status.setAttribute("aria-live", "polite");
      status.setAttribute("aria-atomic", "true");
      btn.parentNode.insertBefore(status, btn.nextSibling);
      var restore = function () {
        btn.classList.remove("copied", "copy-failed");
        btn.textContent = original;
        status.textContent = "";
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
          status.textContent = "Copied to clipboard.";
          timer = window.setTimeout(restore, 1500);
        };
        var fail = function () {
          btn.classList.remove("copied");
          btn.classList.add("copy-failed");
          btn.textContent = "copy manually";
          status.textContent = "Copy unavailable. Copy the command manually.";
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

  function wrapHeadingAsAnchor(title, targetId) {
    if (!title || !targetId || title.querySelector(".header-anchor")) {
      return;
    }
    // Skip a heading that already holds an interactive element: wrapping it would nest an <a> in an <a>.
    if (title.querySelector("a, button")) {
      return;
    }
    var link = document.createElement("a");
    link.className = "header-anchor";
    link.setAttribute("href", "#" + targetId);
    // Wrap the heading's own text so the whole header is clickable.
    while (title.firstChild) {
      link.appendChild(title.firstChild);
    }
    title.appendChild(link);
    link.addEventListener("click", function () {
      // Native navigation sets the fragment; also copy the full URL for sharing.
      // Use the anchor's resolved href so the URL is valid for any protocol/base (file:// included)
      // and keeps the current query string.
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(link.href).catch(function () {});
      }
    });
  }

  function initHeaderAnchors() {
    // Section headings link to their own section (SITE-NAV-01).
    document.querySelectorAll("section[id]").forEach(function (section) {
      wrapHeadingAsAnchor(section.querySelector(".section-title"), section.getAttribute("id"));
    });
    // Standalone sub-headings opt in with data-anchor and link to their own id (SITE-NAV-02).
    document.querySelectorAll("[data-anchor][id]").forEach(function (heading) {
      wrapHeadingAsAnchor(heading, heading.getAttribute("id"));
    });
  }

  function initPluginCards() {
    var cards = document.querySelectorAll(".plugin-card");
    cards.forEach(function (card) {
      var link = card.querySelector(".name a[href]");
      if (!link) {
        return;
      }
      var pointerDown = null;
      card.addEventListener("pointerdown", function (e) {
        if (e.button === 0) {
          pointerDown = { x: e.clientX, y: e.clientY };
        }
      });
      card.addEventListener("click", function (e) {
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
          return;
        }
        var moved = pointerDown &&
          (Math.abs(e.clientX - pointerDown.x) > 4 || Math.abs(e.clientY - pointerDown.y) > 4);
        pointerDown = null;
        if (moved) {
          e.preventDefault();
          return;
        }
        if (window.getSelection && window.getSelection().toString().trim()) {
          e.preventDefault();
          return;
        }
        var target = e.target;
        if (target && target.closest && target.closest(".install, .cmd, .foot, a, button, input, select, textarea, summary")) {
          return;
        }
        e.preventDefault();
        link.click();
      });
    });
  }

  function initDemoSwitch() {
    var tabs = document.querySelectorAll(".demo-tab");
    var frame = document.getElementById("demo-iframe");
    var panel = document.getElementById("demo-panel");
    var title = document.getElementById("demo-title");
    var fullscreen = document.getElementById("demo-fullscreen");
    if (!tabs.length || !frame) {
      return;
    }
    var tabList = Array.prototype.slice.call(tabs);

    function activate(tab, focusIt) {
      var src = tab.getAttribute("data-demo");
      var file = tab.getAttribute("data-file") || src;
      var label = tab.getAttribute("data-label") || file;
      tabList.forEach(function (t) {
        var active = t === tab;
        t.classList.toggle("active", active);
        t.setAttribute("aria-selected", active ? "true" : "false");
        t.setAttribute("tabindex", active ? "0" : "-1");
      });
      if (frame.getAttribute("src") !== src) {
        frame.setAttribute("src", src);
      }
      frame.setAttribute("title", "Live commentable-html demo: " + label);
      if (panel && tab.id) {
        panel.setAttribute("aria-labelledby", tab.id);
      }
      if (title) {
        title.textContent = label;
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

  function initLightbox() {
    // Content images (the tutorial screenshots) open at full size in an overlay.
    // Decorative chrome images (nav brand/hero logo) are excluded.
    var images = document.querySelectorAll(".tutorial img");
    if (!images.length) {
      return;
    }
    var overlay = document.createElement("div");
    overlay.className = "lightbox";
    overlay.setAttribute("hidden", "");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Image preview");
    var full = document.createElement("img");
    full.setAttribute("alt", "Enlarged image");
    var close = document.createElement("button");
    close.type = "button";
    close.className = "lightbox-close";
    close.setAttribute("aria-label", "Close image preview");
    close.innerHTML = "&times;";
    overlay.appendChild(full);
    overlay.appendChild(close);
    document.body.appendChild(overlay);

    var lastFocus = null;

    function open(img) {
      full.setAttribute("src", img.currentSrc || img.src);
      full.setAttribute("alt", img.getAttribute("alt") || "");
      lastFocus = document.activeElement;
      overlay.removeAttribute("hidden");
      close.focus();
    }

    function hide() {
      overlay.setAttribute("hidden", "");
      full.setAttribute("src", "");
      if (lastFocus && typeof lastFocus.focus === "function") {
        lastFocus.focus();
      }
    }

    images.forEach(function (img) {
      img.setAttribute("tabindex", "0");
      img.setAttribute("role", "button");
      if (!img.hasAttribute("aria-label")) {
        var name = img.getAttribute("alt");
        img.setAttribute("aria-label", name ? "View " + name + " enlarged" : "View image enlarged");
      }
      img.addEventListener("click", function () {
        open(img);
      });
      img.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault();
          open(img);
        }
      });
    });
    overlay.addEventListener("click", function (e) {
      // Click the backdrop or the close button to dismiss; clicks on the image itself stay open.
      if (e.target !== full) {
        hide();
      }
    });
    document.addEventListener("keydown", function (e) {
      if (overlay.hasAttribute("hidden")) {
        return;
      }
      if (e.key === "Escape") {
        hide();
        return;
      }
      if (e.key === "Tab") {
        // Trap Tab/Shift+Tab within the overlay so focus cannot escape into the page behind it.
        var focusable = Array.prototype.slice
          .call(overlay.querySelectorAll('button, a[href], [tabindex]:not([tabindex="-1"])'))
          .filter(function (el) {
            return el.offsetParent !== null || el === document.activeElement;
          });
        if (!focusable.length) {
          return;
        }
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        var active = document.activeElement;
        if (e.shiftKey) {
          if (active === first || !overlay.contains(active)) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (active === last || !overlay.contains(active)) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    });
  }

  function initInstallTabs() {
    var groups = document.querySelectorAll("[data-install-tabs]");
    groups.forEach(function (group) {
      var tabs = Array.prototype.slice.call(group.querySelectorAll(".install-tab"));
      if (!tabs.length) {
        return;
      }

      function activate(tab, focusIt) {
        tabs.forEach(function (t) {
          var active = t === tab;
          t.setAttribute("aria-selected", active ? "true" : "false");
          t.setAttribute("tabindex", active ? "0" : "-1");
          var panel = document.getElementById(t.getAttribute("data-install-target"));
          if (panel) {
            if (active) {
              panel.removeAttribute("hidden");
            } else {
              panel.setAttribute("hidden", "");
            }
          }
        });
        if (focusIt) {
          tab.focus();
        }
      }

      tabs.forEach(function (tab, i) {
        tab.addEventListener("click", function () {
          activate(tab, false);
        });
        tab.addEventListener("keydown", function (e) {
          var last = tabs.length - 1;
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
          activate(tabs[next], true);
        });
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
    initHeaderAnchors();
    initPluginCards();
    initInstallTabs();
    initDemoSwitch();
    initLightbox();
  });
})();
