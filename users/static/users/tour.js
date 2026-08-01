/**
 * Guides première connexion (coach marks) — Driver.js
 * Une étape à la fois (multi-pages).
 * Config : #joy-tour-config (json_script).
 */
(function () {
  "use strict";

  var STORAGE_KEY = "joy_product_tour";
  var activeDriver = null;
  var finishing = false;
  var advancing = false;

  function getConfig() {
    var el = document.getElementById("joy-tour-config");
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function csrfToken(config) {
    if (config && config.csrf_token) return config.csrf_token;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var input = document.querySelector("[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function normalizePath(p) {
    if (!p) return "";
    var path = String(p).split("?")[0].split("#")[0];
    if (path.length > 1 && path.endsWith("/")) path = path.slice(0, -1);
    return path || "/";
  }

  function pathMatches(wanted) {
    if (!wanted) return true;
    return normalizePath(wanted) === normalizePath(location.pathname);
  }

  function readState() {
    try {
      return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    } catch (e) {
      return null;
    }
  }

  function writeState(state) {
    if (!state) {
      sessionStorage.removeItem(STORAGE_KEY);
      return;
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function isMobileNav() {
    return window.matchMedia("(max-width: 768px)").matches;
  }

  function openMobileNav() {
    if (!isMobileNav()) return;
    var links = document.getElementById("nav-links");
    var burger = document.querySelector(".nav-burger");
    if (links && !links.classList.contains("open") && burger) {
      burger.click();
    }
  }

  function closeMobileNav() {
    if (!isMobileNav()) return;
    var links = document.getElementById("nav-links");
    var burger = document.querySelector(".nav-burger");
    if (links && links.classList.contains("open") && burger) {
      burger.click();
    }
  }

  function prepareStep(step) {
    if (step.open_mobile_nav) openMobileNav();
    else closeMobileNav();
    if (step.scroll_footer) {
      var foot = document.querySelector("[data-tour='footer-admin']");
      if (foot) foot.scrollIntoView({ behavior: "smooth", block: "center" });
      else window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    }
  }

  function resolveElement(anchor) {
    if (!anchor) return undefined;
    return document.querySelector('[data-tour="' + anchor + '"]') || undefined;
  }

  function ensurePin() {
    var el = document.getElementById("joy-tour-pin");
    if (el) return el;
    el = document.createElement("div");
    el.id = "joy-tour-pin";
    el.setAttribute("aria-hidden", "true");
    el.style.cssText =
      "position:fixed;left:0;top:0;width:1px;height:1px;margin:0;padding:0;opacity:0;pointer-events:none;z-index:0;";
    document.body.appendChild(el);
    return el;
  }

  function markComplete(config, audience, version) {
    return fetch(config.complete_url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(config),
      },
      body: JSON.stringify({ audience: audience, version: version }),
    }).catch(function () {});
  }

  function destroyQuiet() {
    if (!activeDriver) return;
    var d = activeDriver;
    advancing = true;
    activeDriver = null;
    try {
      d.destroy();
    } catch (e) {}
    advancing = false;
  }

  function finishTour(config, audience, version, queue) {
    if (finishing) return;
    finishing = true;
    destroyQuiet();
    writeState(null);
    closeMobileNav();
    markComplete(config, audience, version).then(function () {
      finishing = false;
      var nextQueue = (queue || []).filter(function (a) {
        return a !== audience;
      });
      if (nextQueue.length) {
        config._queue = nextQueue;
        showStep(config, nextQueue[0], 0);
      }
    });
  }

  function goNext(config, audience, tour, queue, i) {
    if (i >= tour.steps.length - 1) {
      finishTour(config, audience, tour.version, queue);
      return;
    }
    destroyQuiet();
    showStep(config, audience, i + 1);
  }

  function goPrev(config, audience, queue, i) {
    if (i <= 0) return;
    destroyQuiet();
    showStep(config, audience, i - 1);
  }

  function showStep(config, audience, idx) {
    var tour = config.tours[audience];
    if (!tour || !tour.steps || !tour.steps.length) return;
    if (typeof window.driver === "undefined" || !window.driver.js) {
      console.warn("Driver.js indisponible");
      return;
    }

    var steps = tour.steps;
    var queue = config._queue || [];
    var i = Math.max(0, Math.min(idx || 0, steps.length - 1));
    var step = steps[i];
    var isFirst = i === 0;
    var isLast = i === steps.length - 1;

    if (step.page_path && !pathMatches(step.page_path)) {
      writeState({ audience: audience, step: i, queue: queue });
      location.assign(step.page_path);
      return;
    }

    writeState({ audience: audience, step: i, queue: queue });
    destroyQuiet();
    prepareStep(step);

    var el = resolveElement(step.anchor) || ensurePin();
    var popoverClass = step.anchor
      ? "joy-tour-popover"
      : "joy-tour-popover joy-tour-popover--center";

    var stepDef = {
      element: el,
      popover: {
        title: step.title,
        description: step.body,
        side: step.anchor ? "bottom" : "over",
        align: "center",
        showButtons: ["next", "previous", "close"],
        disableButtons: isFirst ? ["previous"] : [],
        nextBtnText: isLast ? "Terminer" : "Suivant",
        prevBtnText: "Retour",
        progressText: i + 1 + " / " + steps.length,
      },
    };

    // allowClose:false — le SVG overlay ne doit pas avaler Suivant (overlayClick).
    activeDriver = window.driver.js.driver({
      animate: true,
      allowClose: false,
      overlayClickBehavior: "close",
      overlayOpacity: 0.55,
      stagePadding: step.anchor ? 6 : 0,
      stageRadius: step.anchor ? 4 : 0,
      popoverClass: popoverClass,
      showProgress: true,
      nextBtnText: isLast ? "Terminer" : "Suivant",
      prevBtnText: "Retour",
      doneBtnText: "Terminer",
      progressText: i + 1 + " / " + steps.length,
      steps: [stepDef],
      onNextClick: function () {
        goNext(config, audience, tour, queue, i);
      },
      onPrevClick: function () {
        goPrev(config, audience, queue, i);
      },
      onCloseClick: function () {
        finishTour(config, audience, tour.version, queue);
      },
      onPopoverRender: function (popover) {
        if (!popover || !popover.nextButton) return;
        popover.nextButton.addEventListener(
          "click",
          function (ev) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            goNext(config, audience, tour, queue, i);
          },
          true
        );
        if (popover.closeButton) {
          popover.closeButton.addEventListener(
            "click",
            function (ev) {
              ev.preventDefault();
              ev.stopImmediatePropagation();
              finishTour(config, audience, tour.version, queue);
            },
            true
          );
        }
      },
      onDestroyStarted: function (_el, _step, opts) {
        if (advancing || finishing || !activeDriver) {
          opts.driver.destroy();
          return;
        }
        finishTour(config, audience, tour.version, queue);
      },
    });

    try {
      activeDriver.drive(0);
    } catch (err) {
      console.warn("Guide : impossible de démarrer l’étape", err);
    }
  }

  function stripTourQuery() {
    try {
      var u = new URL(location.href);
      if (u.searchParams.has("tour")) {
        u.searchParams.delete("tour");
        var cleaned =
          u.pathname +
          (u.searchParams.toString() ? "?" + u.searchParams.toString() : "") +
          u.hash;
        history.replaceState({}, "", cleaned);
      }
    } catch (e) {}
  }

  function boot() {
    var config = getConfig();
    if (!config || !config.tours) return;

    if (config.force && config.tours[config.force]) {
      writeState(null);
      config._queue = (config.pending || []).filter(function (a) {
        return a !== config.force;
      });
      stripTourQuery();
      showStep(config, config.force, 0);
      return;
    }

    var state = readState();
    if (state && state.audience && config.tours[state.audience]) {
      config._queue = state.queue || [];
      showStep(config, state.audience, state.step || 0);
      return;
    }

    if (config.pending && config.pending.length) {
      config._queue = config.pending.slice(1);
      showStep(config, config.pending[0], 0);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
