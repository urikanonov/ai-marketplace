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

  function initNavOffset() {
    // Keep the anchor-jump scroll offset equal to the actual sticky navbar height so a
    // nav/hash jump is never hidden behind it, even when the navbar wraps taller on narrow
    // viewports (SITE-NAV-03). CSS carries a static 76px fallback for the no-JS case.
    var navbar = document.querySelector(".navbar");
    if (!navbar) return;
    var apply = function () {
      var h = Math.round(navbar.getBoundingClientRect().height);
      if (h > 0) document.documentElement.style.setProperty("--nav-offset", h + "px");
    };
    apply();
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(apply).observe(navbar);
    } else {
      window.addEventListener("resize", apply);
    }
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

  // Demo clips open in an overlay and play at their native size. The thumbnail is a real button
  // carrying the clip's source, so nothing but a poster image is fetched until it is pressed - a
  // page that embedded three multi-megabyte videos would otherwise pay for them on every visit.
  function initVideoLightbox() {
    var triggers = document.querySelectorAll("[data-video]");
    if (!triggers.length) {
      return;
    }
    var overlay = document.createElement("div");
    overlay.className = "lightbox lightbox-video";
    overlay.setAttribute("hidden", "");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Demo video");
    var video = document.createElement("video");
    video.setAttribute("controls", "");
    video.setAttribute("playsinline", "");
    video.setAttribute("preload", "none");
    // Picture-in-picture would pop the clip out of the overlay the lightbox controls, leaving a
    // floating window the close button and Escape no longer govern. Note this deliberately does
    // NOT restrict playback rate: the browser's own speed menu stays available alongside the
    // explicit 1x/1.5x/2x buttons.
    video.setAttribute("disablePictureInPicture", "");
    video.setAttribute("controlsList", "nodownload noremoteplayback");
    var close = document.createElement("button");
    close.type = "button";
    close.className = "lightbox-close";
    close.setAttribute("aria-label", "Close demo video");
    close.innerHTML = "&times;";
    // A demo clip is something you skim: the native seek bar covers scrubbing, but browsers hide
    // playback speed behind different menus (or omit it), so the rates are offered explicitly.
    var speeds = document.createElement("div");
    speeds.className = "lightbox-speeds";
    speeds.setAttribute("role", "group");
    speeds.setAttribute("aria-label", "Playback speed");
    var rates = [1, 1.5, 2];
    var rateButtons = rates.map(function (rate) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "lightbox-speed";
      b.setAttribute("data-rate", String(rate));
      b.setAttribute("aria-pressed", rate === 1 ? "true" : "false");
      b.textContent = rate + "x";
      b.addEventListener("click", function () {
        setRate(rate);
      });
      speeds.appendChild(b);
      return b;
    });

    var wantedRate = 1;

    function setRate(rate) {
      wantedRate = rate;
      // defaultPlaybackRate AND playbackRate: loading a source resets the live rate to the
      // default, so setting only the live one silently reverts to 1x the moment the clip loads -
      // the button would light up while the video kept playing at normal speed.
      video.defaultPlaybackRate = rate;
      video.playbackRate = rate;
      rateButtons.forEach(function (b) {
        b.setAttribute("aria-pressed", Number(b.getAttribute("data-rate")) === rate ? "true" : "false");
      });
    }

    // preload="none" means the media arrives well after the overlay opens, so re-assert the rate
    // once it does.
    video.addEventListener("loadedmetadata", function () {
      video.playbackRate = wantedRate;
    });
    video.addEventListener("ratechange", function () {
      rateButtons.forEach(function (b) {
        b.setAttribute("aria-pressed", Number(b.getAttribute("data-rate")) === video.playbackRate ? "true" : "false");
      });
    });

    overlay.appendChild(video);
    overlay.appendChild(speeds);
    overlay.appendChild(close);
    document.body.appendChild(overlay);

    var lastFocus = null;

    // Safari and iOS put a video into fullscreen through their own API, where
    // document.fullscreenElement stays null - so a standard-only check would tear the overlay
    // down on the very key the viewer pressed to come back out of fullscreen.
    function overlayIsFullscreen() {
      var el = document.fullscreenElement || document.webkitFullscreenElement || null;
      if (el && overlay.contains(el)) {
        return true;
      }
      return video.webkitDisplayingFullscreen === true;
    }

    function leaveFullscreen() {
      try {
        if (video.webkitDisplayingFullscreen === true && typeof video.webkitExitFullscreen === "function") {
          video.webkitExitFullscreen();
          return;
        }
        var exit = document.exitFullscreen || document.webkitExitFullscreen;
        if (typeof exit === "function") {
          var done = exit.call(document);
          if (done && typeof done.catch === "function") { done.catch(function () {}); }
        }
      } catch (err) {
        /* leaving fullscreen is best effort; never block the close */
      }
    }

    function open(trigger) {
      video.setAttribute("src", trigger.getAttribute("data-video"));
      var thumbPoster = trigger.querySelector("img");
      if (thumbPoster) {
        video.setAttribute("poster", thumbPoster.currentSrc || thumbPoster.src);
      }
      setRate(1);
      var label = trigger.getAttribute("data-video-label");
      overlay.setAttribute("aria-label", label ? label : "Demo video");
      lastFocus = trigger;
      overlay.removeAttribute("hidden");
      close.focus();
      // Autoplay is the point of pressing play, but a browser may refuse it; the controls are
      // there either way, so a rejected promise is not an error worth surfacing.
      var played = video.play();
      if (played && typeof played.catch === "function") {
        played.catch(function () {});
      }
    }

    function hide() {
      if (overlayIsFullscreen()) {
        leaveFullscreen();
      }
      // Pause AND drop the source: leaving it attached keeps the clip buffering behind a closed
      // overlay, and on some browsers keeps its audio alive.
      video.pause();
      overlay.setAttribute("hidden", "");
      video.removeAttribute("src");
      video.removeAttribute("poster");
      video.load();
      if (lastFocus && typeof lastFocus.focus === "function") {
        lastFocus.focus();
      }
    }

    triggers.forEach(function (trigger) {
      trigger.addEventListener("click", function () {
        open(trigger);
      });
    });
    // The close button is unambiguous, so it dismisses on ANY activation. It must not go through
    // the press/release pairing below: keyboard and assistive-technology activation produce a
    // click with no pointerdown at all, which would leave Enter unable to close the dialog.
    close.addEventListener("click", function (e) {
      e.stopPropagation();
      pressedOn = null;
      hide();
    });

    // The BACKDROP is different. A click is dispatched on the nearest common ancestor of press and
    // release, so a drag that starts on the video or a speed pill and ends on the backdrop reports
    // the overlay as its target - dismissing the clip on a 20px slip off a pill, or on a scrub
    // that leaves the video. Require both ends of the gesture on the backdrop itself.
    var pressedOn = null;
    overlay.addEventListener("pointerdown", function (e) {
      pressedOn = e.target;
    });
    // A press that never becomes a click must not leave its origin behind for the next one.
    overlay.addEventListener("pointercancel", function () {
      pressedOn = null;
    });
    overlay.addEventListener("contextmenu", function () {
      pressedOn = null;
    });
    overlay.addEventListener("click", function (e) {
      var from = pressedOn;
      pressedOn = null;
      if (e.target === overlay && from === overlay) {
        hide();
      }
    });
    document.addEventListener("keydown", function (e) {
      if (overlay.hasAttribute("hidden")) {
        return;
      }
      if (e.key === "Escape") {
        // Escape is ALSO the key that leaves fullscreen. Tearing the overlay down here would
        // destroy the clip instead, losing the position, so let the browser handle it first.
        if (overlayIsFullscreen()) {
          return;
        }
        e.preventDefault();
        e.stopPropagation();
        hide();
        return;
      }
      if (e.key === "Tab") {
        var focusable = Array.prototype.slice
          .call(overlay.querySelectorAll('button, video[controls], [tabindex]:not([tabindex="-1"])'));
        if (!focusable.length) {
          return;
        }
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        var active = document.activeElement;
        // Clicking dead space inside the overlay blurs to <body>, which is INSIDE no control - so
        // without this, Tab would walk into the page behind the modal.
        if (!overlay.contains(active)) {
          e.preventDefault();
          (e.shiftKey ? last : first).focus();
        } else if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
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
      full.setAttribute("alt", img.getAttribute("alt") || "Enlarged image");
      // Restore focus to the triggering image itself (not document.activeElement),
      // since a click does not always move focus there (e.g. Firefox/Safari on a
      // non-natively-focusable element).
      lastFocus = img;
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
      if (!img.hasAttribute("tabindex")) {
        img.setAttribute("tabindex", "0");
      }
      if (!img.hasAttribute("role")) {
        img.setAttribute("role", "button");
      }
      if (!(img.getAttribute("aria-label") || "").trim()) {
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
        e.preventDefault();
        e.stopPropagation();
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
    }, true);
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
    initNavOffset();
    initPluginCards();
    initInstallTabs();
    initDemoSwitch();
    initLightbox();
    initVideoLightbox();
  });
})();
