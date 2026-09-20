/**
 * Swipe notifications (salon + bannière Coulisses).
 * Droite = marquer lue · gauche = archiver.
 * Utilise touch + pointer ; le contenu n’est plus un <a> (évite de bloquer le geste).
 */
(function () {
  const THRESHOLD = 56;
  const MAX_DRAG = 180;
  const ANGLE_LOCK = 1.2; // |dx| > |dy| * ANGLE_LOCK

  function csrfToken(el) {
    const root = el.closest("[data-csrf]") || document.querySelector("[data-csrf]");
    if (root && root.getAttribute("data-csrf")) return root.getAttribute("data-csrf");
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function postAction(url, csrf) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "X-CSRFToken": csrf || "",
        "X-Requested-With": "XMLHttpRequest",
      },
    }).then(function (r) {
      if (!r.ok) throw new Error("action_failed");
      return r.json().catch(function () {
        return { ok: true };
      });
    });
  }

  function postMany(urls, csrf) {
    const list = (urls || []).filter(Boolean);
    if (!list.length) return Promise.resolve();
    return Promise.all(list.map(function (u) {
      return postAction(u, csrf);
    }));
  }

  function parseUrlList(row, attr) {
    const raw = row.getAttribute(attr) || "";
    if (!raw) return [];
    if (raw.charAt(0) === "[") {
      try {
        return JSON.parse(raw);
      } catch (_) {
        return [];
      }
    }
    return raw.split(/\s+/).filter(Boolean);
  }

  function dismissRow(row, direction) {
    row.classList.add(direction === "right" ? "is-leaving-right" : "is-leaving-left");
    const card = row.querySelector("[data-notif-card]");
    if (card) {
      card.style.transform =
        direction === "right" ? "translateX(110%)" : "translateX(-110%)";
      card.style.opacity = "0";
    }
    window.setTimeout(function () {
      row.classList.add("is-gone");
      const parent = row.parentElement;
      row.remove();
      if (!parent) return;
      const left = parent.querySelector("[data-notif-swipe]");
      if (!left) {
        const banner = parent.closest("[data-notif-banner]");
        if (banner) {
          banner.remove();
          return;
        }
        window.location.reload();
      }
    }, 200);
  }

  function runAction(row, action) {
    if (row.dataset.busy === "1") return;
    row.dataset.busy = "1";
    const csrf = csrfToken(row);
    let urls = [];
    if (action === "mark_read") {
      urls = parseUrlList(row, "data-mark-read-urls");
      if (!urls.length) {
        const one = row.getAttribute("data-mark-read-url");
        if (one) urls = [one];
      }
    } else if (action === "archive") {
      urls = parseUrlList(row, "data-archive-urls");
      if (!urls.length) {
        const one = row.getAttribute("data-archive-url");
        if (one) urls = [one];
      }
    } else {
      const one = row.getAttribute("data-unarchive-url");
      if (one) urls = [one];
    }
    if (!urls.length) {
      row.dataset.busy = "0";
      return;
    }

    const card = row.querySelector("[data-notif-card]");
    const stays =
      action === "mark_read" && card && card.classList.contains("is-unanswered");

    if (stays) {
      postMany(urls, csrf)
        .then(function () {
          card.classList.remove("is-unread");
          row.dataset.busy = "0";
          resetCard(row, card);
        })
        .catch(function () {
          window.location.reload();
        });
      return;
    }

    dismissRow(row, action === "mark_read" ? "right" : "left");
    postMany(urls, csrf).catch(function () {
      window.location.reload();
    });
  }

  function resetCard(row, card) {
    row.classList.remove("is-dragging", "is-swiping-right", "is-swiping-left");
    if (card) {
      card.style.transform = "";
      card.style.opacity = "";
    }
  }

  function bindSwipe(row) {
    if (row.getAttribute("data-archived") === "1") return;
    if (row.dataset.swipeBound === "1") return;
    row.dataset.swipeBound = "1";

    const card = row.querySelector("[data-notif-card]");
    if (!card) return;

    let startX = 0;
    let startY = 0;
    let dx = 0;
    let tracking = false;
    let locked = null; // null | "h" | "v"
    let moved = false;

    function setOffset(x) {
      dx = Math.max(-MAX_DRAG, Math.min(MAX_DRAG, x));
      card.style.transform = "translate3d(" + dx + "px,0,0)";
      row.classList.toggle("is-swiping-right", dx > 10);
      row.classList.toggle("is-swiping-left", dx < -10);
    }

    function start(x, y) {
      tracking = true;
      locked = null;
      moved = false;
      startX = x;
      startY = y;
      dx = 0;
      row.classList.add("is-dragging");
    }

    function move(x, y, evt) {
      if (!tracking) return;
      const mx = x - startX;
      const my = y - startY;
      if (locked === null) {
        if (Math.abs(mx) < 8 && Math.abs(my) < 8) return;
        locked = Math.abs(mx) > Math.abs(my) * ANGLE_LOCK ? "h" : "v";
        if (locked === "v") {
          tracking = false;
          resetCard(row, card);
          return;
        }
      }
      if (locked !== "h") return;
      if (evt && evt.cancelable) evt.preventDefault();
      moved = true;
      setOffset(mx);
    }

    function end() {
      if (!tracking && locked !== "h") {
        resetCard(row, card);
        return false;
      }
      tracking = false;
      row.classList.remove("is-dragging");
      if (locked === "h") {
        if (dx >= THRESHOLD) {
          runAction(row, "mark_read");
          return true;
        }
        if (dx <= -THRESHOLD) {
          runAction(row, "archive");
          return true;
        }
      }
      resetCard(row, card);
      dx = 0;
      locked = null;
      return false;
    }

    // Touch (mobile) — prioritaire
    card.addEventListener(
      "touchstart",
      function (e) {
        if (e.target.closest("button, input, label, textarea, select")) return;
        if (e.target.closest(".notif-item__actions")) return;
        if (e.touches.length !== 1) return;
        start(e.touches[0].clientX, e.touches[0].clientY);
      },
      { passive: true }
    );
    card.addEventListener(
      "touchmove",
      function (e) {
        if (!tracking) return;
        if (e.touches.length !== 1) return;
        move(e.touches[0].clientX, e.touches[0].clientY, e);
      },
      { passive: false }
    );
    card.addEventListener("touchend", function () {
      const swiped = end();
      if (swiped) moved = true;
    });
    card.addEventListener("touchcancel", function () {
      tracking = false;
      resetCard(row, card);
    });

    // Pointer / souris (desktop)
    card.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "touch") return; // déjà géré
      if (e.pointerType === "mouse" && e.button !== 0) return;
      if (e.target.closest("button, input, label, textarea, select")) return;
      if (e.target.closest(".notif-item__actions")) return;
      start(e.clientX, e.clientY);
      try {
        card.setPointerCapture(e.pointerId);
      } catch (_) {}
    });
    card.addEventListener(
      "pointermove",
      function (e) {
        if (e.pointerType === "touch") return;
        move(e.clientX, e.clientY, e);
      },
      { passive: false }
    );
    card.addEventListener("pointerup", function (e) {
      if (e.pointerType === "touch") return;
      end();
    });
    card.addEventListener("pointercancel", function (e) {
      if (e.pointerType === "touch") return;
      tracking = false;
      resetCard(row, card);
    });

    // Tap → ouvrir le lien (si pas de swipe)
    card.addEventListener(
      "click",
      function (e) {
        if (e.target.closest("button, form, input, label")) return;
        if (moved) {
          e.preventDefault();
          e.stopPropagation();
          moved = false;
          return;
        }
        const href = card.getAttribute("data-href");
        if (href) {
          e.preventDefault();
          window.location.href = href;
        }
      },
      true
    );
  }

  function init() {
    document.querySelectorAll("[data-notif-swipe]").forEach(bindSwipe);

    document.querySelectorAll("[data-notif-form]").forEach(function (form) {
      if (form.dataset.bound === "1") return;
      form.dataset.bound = "1";
      form.addEventListener("submit", function (e) {
        const action = form.getAttribute("data-notif-form");
        if (!action || action === "mark_responded") return;
        e.preventDefault();
        const row = form.closest("[data-notif-swipe]");
        if (!row) {
          form.submit();
          return;
        }
        runAction(row, action);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
