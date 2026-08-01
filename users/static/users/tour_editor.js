/**
 * Éditeur timeline des guides (coach marks).
 * État local + enregistrement JSON vers admin_tours_save.
 */
(function () {
  "use strict";

  var cfgEl = document.getElementById("joy-tour-editor-config");
  var root = document.getElementById("tour-editor-root");
  if (!cfgEl || !root) return;

  var cfg;
  try {
    cfg = JSON.parse(cfgEl.textContent);
  } catch (e) {
    return;
  }

  var state = {
    audience: root.getAttribute("data-audience") || "musician",
    tours: JSON.parse(JSON.stringify(cfg.tours || {})),
    selected: 0,
    dirty: false,
  };

  var els = {
    tabs: root.querySelectorAll(".tour-ed__tab"),
    title: document.getElementById("tour-ed-title"),
    version: document.getElementById("tour-ed-version"),
    active: document.getElementById("tour-ed-active"),
    bump: document.getElementById("tour-ed-bump"),
    count: document.getElementById("tour-ed-count"),
    status: document.getElementById("tour-ed-status"),
    timeline: document.getElementById("tour-ed-timeline"),
    panel: document.getElementById("tour-ed-panel"),
    panelTitle: document.getElementById("tour-ed-panel-title"),
    bubbleTitle: document.getElementById("tour-ed-bubble-title"),
    bubbleBody: document.getElementById("tour-ed-bubble-body"),
    bubbleProgress: document.getElementById("tour-ed-bubble-progress"),
    stepTitle: document.getElementById("tour-ed-step-title"),
    stepBody: document.getElementById("tour-ed-step-body"),
    stepAnchor: document.getElementById("tour-ed-step-anchor"),
    stepPage: document.getElementById("tour-ed-step-page"),
    stepNav: document.getElementById("tour-ed-step-nav"),
    stepFooter: document.getElementById("tour-ed-step-footer"),
    stepActive: document.getElementById("tour-ed-step-active"),
    stepAnchorManual: document.getElementById("tour-ed-step-anchor-manual"),
    stepPageManual: document.getElementById("tour-ed-step-page-manual"),
    add: document.getElementById("tour-ed-add"),
    save: document.getElementById("tour-ed-save"),
    del: document.getElementById("tour-ed-delete"),
    prev: document.getElementById("tour-ed-prev"),
    next: document.getElementById("tour-ed-next"),
  };

  function tour() {
    return state.tours[state.audience];
  }

  function steps() {
    var t = tour();
    return t && t.steps ? t.steps : [];
  }

  function currentStep() {
    var list = steps();
    if (!list.length) return null;
    if (state.selected < 0) state.selected = 0;
    if (state.selected >= list.length) state.selected = list.length - 1;
    return list[state.selected];
  }

  function markDirty() {
    state.dirty = true;
  }

  function setStatus(msg, kind) {
    if (!msg) {
      els.status.hidden = true;
      els.status.textContent = "";
      els.status.className = "tour-ed__status";
      return;
    }
    els.status.hidden = false;
    els.status.textContent = msg;
    els.status.className =
      "tour-ed__status" + (kind ? " is-" + kind : "");
  }

  function fillSelect(select, options, value, allowCustom) {
    select.innerHTML = "";
    var found = false;
    options.forEach(function (opt) {
      var o = document.createElement("option");
      o.value = opt.value;
      o.textContent = opt.label;
      if (opt.value === value) {
        o.selected = true;
        found = true;
      }
      select.appendChild(o);
    });
    if (allowCustom && value && !found) {
      var custom = document.createElement("option");
      custom.value = value;
      custom.textContent = value + " (perso)";
      custom.selected = true;
      select.appendChild(custom);
    }
  }

  function anchorLabel(value) {
    var list = cfg.anchors || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].value === value) return list[i].label;
    }
    return value || "Plein écran";
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderTimeline() {
    var list = steps();
    els.count.textContent = list.length
      ? list.length + " diapo" + (list.length > 1 ? "s" : "")
      : "Aucune diapo — ajoutez-en une.";
    els.timeline.innerHTML = "";

    list.forEach(function (step, idx) {
      var li = document.createElement("li");
      li.className =
        "tour-ed__slide" +
        (idx === state.selected ? " is-selected" : "") +
        (step.is_active === false ? " is-inactive" : "");

      var meta = anchorLabel(step.anchor || "");
      if (step.page_path) meta += " · " + step.page_path;

      li.innerHTML =
        '<button type="button" class="tour-ed__slide-btn" data-idx="' +
        idx +
        '">' +
        '<span class="tour-ed__slide-num">' +
        (idx + 1) +
        "</span>" +
        '<span class="tour-ed__thumb">' +
        '<span class="tour-ed__thumb-title">' +
        escapeHtml(step.title || "Sans titre") +
        "</span>" +
        '<span class="tour-ed__thumb-body">' +
        escapeHtml(step.body || "") +
        "</span>" +
        '<span class="tour-ed__thumb-meta">' +
        escapeHtml(meta) +
        "</span>" +
        "</span>" +
        "</button>" +
        '<div class="tour-ed__slide-move">' +
        '<button type="button" data-move="up" data-idx="' +
        idx +
        '" aria-label="Monter"' +
        (idx === 0 ? " disabled" : "") +
        ">↑</button>" +
        '<button type="button" data-move="down" data-idx="' +
        idx +
        '" aria-label="Descendre"' +
        (idx === list.length - 1 ? " disabled" : "") +
        ">↓</button>" +
        "</div>";

      els.timeline.appendChild(li);
    });
  }

  function syncMetaForm() {
    var t = tour();
    if (!t) return;
    els.title.value = t.title || "";
    els.version.value = String(t.version || 1);
    els.active.checked = t.is_active !== false;
  }

  function syncStepForm() {
    var step = currentStep();
    var list = steps();
    if (!step) {
      els.panel.hidden = true;
      return;
    }
    els.panel.hidden = false;
    els.panelTitle.textContent = "Diapo " + (state.selected + 1) + " / " + list.length;

    els.stepTitle.value = step.title || "";
    els.stepBody.value = step.body || "";
    fillSelect(els.stepAnchor, cfg.anchors || [], step.anchor || "", true);
    fillSelect(els.stepPage, cfg.page_paths || [], step.page_path || "", true);
    els.stepNav.checked = !!step.open_mobile_nav;
    els.stepFooter.checked = !!step.scroll_footer;
    els.stepActive.checked = step.is_active !== false;
    els.stepAnchorManual.value = step.anchor || "";
    els.stepPageManual.value = step.page_path || "";

    els.bubbleTitle.textContent = step.title || "";
    els.bubbleBody.textContent = step.body || "";
    els.bubbleProgress.textContent =
      state.selected + 1 + " / " + list.length;

    els.prev.disabled = state.selected <= 0;
    els.next.disabled = state.selected >= list.length - 1;
  }

  function render() {
    els.tabs.forEach(function (tab) {
      var aud = tab.getAttribute("data-aud");
      tab.setAttribute(
        "aria-selected",
        aud === state.audience ? "true" : "false"
      );
    });
    syncMetaForm();
    renderTimeline();
    syncStepForm();
  }

  function selectStep(idx) {
    var list = steps();
    if (!list.length) {
      state.selected = 0;
      render();
      return;
    }
    state.selected = Math.max(0, Math.min(idx, list.length - 1));
    render();
    var selected = els.timeline.querySelector(".tour-ed__slide.is-selected");
    if (selected) {
      selected.scrollIntoView({
        behavior: "smooth",
        inline: "center",
        block: "nearest",
      });
    }
  }

  function applyStepFromForm() {
    var step = currentStep();
    if (!step) return;
    step.title = els.stepTitle.value;
    step.body = els.stepBody.value;
    var anchorManual = (els.stepAnchorManual.value || "").trim();
    var pageManual = (els.stepPageManual.value || "").trim();
    step.anchor = anchorManual || els.stepAnchor.value || "";
    step.page_path = pageManual || els.stepPage.value || "";
    step.open_mobile_nav = !!els.stepNav.checked;
    step.scroll_footer = !!els.stepFooter.checked;
    step.is_active = !!els.stepActive.checked;
  }

  function applyMetaFromForm() {
    var t = tour();
    if (!t) return;
    t.title = els.title.value;
    var v = parseInt(els.version.value, 10);
    t.version = isNaN(v) || v < 1 ? 1 : v;
    t.is_active = !!els.active.checked;
  }

  function moveStep(idx, dir) {
    var list = steps();
    var j = idx + dir;
    if (j < 0 || j >= list.length) return;
    var tmp = list[idx];
    list[idx] = list[j];
    list[j] = tmp;
    if (state.selected === idx) state.selected = j;
    else if (state.selected === j) state.selected = idx;
    markDirty();
    render();
  }

  function addStep() {
    applyStepFromForm();
    applyMetaFromForm();
    var list = steps();
    list.push({
      id: null,
      order: list.length + 1,
      anchor: "",
      title: "Nouvelle diapo",
      body: "Rédigez le texte de cette bulle d’aide.",
      page_path: "",
      open_mobile_nav: false,
      scroll_footer: false,
      is_active: true,
    });
    markDirty();
    selectStep(list.length - 1);
    setStatus("Diapo ajoutée — n’oubliez pas d’enregistrer.", null);
  }

  function deleteStep() {
    var list = steps();
    if (!list.length) return;
    if (
      !window.confirm(
        "Supprimer la diapo « " +
          (currentStep().title || "") +
          " » ? (effectif après Enregistrer)"
      )
    ) {
      return;
    }
    list.splice(state.selected, 1);
    if (state.selected >= list.length) {
      state.selected = Math.max(0, list.length - 1);
    }
    markDirty();
    render();
    setStatus("Diapo supprimée — n’oubliez pas d’enregistrer.", null);
  }

  function save() {
    applyStepFromForm();
    applyMetaFromForm();
    var t = tour();
    if (!t) return;

    els.save.disabled = true;
    setStatus("Enregistrement…", null);

    var payload = {
      audience: state.audience,
      title: t.title,
      version: t.version,
      is_active: t.is_active,
      bump_version: !!els.bump.checked,
      steps: t.steps,
    };

    fetch(cfg.save_url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": cfg.csrf_token,
      },
      body: JSON.stringify(payload),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        els.save.disabled = false;
        if (!result.ok || !result.data.ok) {
          setStatus(
            (result.data && result.data.error) || "Échec de l’enregistrement.",
            "err"
          );
          return;
        }
        state.tours[state.audience] = result.data.tour;
        state.dirty = false;
        els.bump.checked = false;
        render();
        setStatus(
          "Guide « " +
            result.data.tour.title +
            " » enregistré (v" +
            result.data.tour.version +
            ", " +
            result.data.tour.steps.length +
            " diapos).",
          "ok"
        );
      })
      .catch(function () {
        els.save.disabled = false;
        setStatus("Erreur réseau lors de l’enregistrement.", "err");
      });
  }

  function switchAudience(aud) {
    if (!state.tours[aud]) return;
    if (aud === state.audience) return;
    if (state.dirty) {
      if (
        !window.confirm(
          "Modifications non enregistrées. Changer de guide quand même ?"
        )
      ) {
        return;
      }
    }
    applyStepFromForm();
    applyMetaFromForm();
    state.audience = aud;
    state.selected = 0;
    state.dirty = false;
    setStatus("", null);
    var url = new URL(window.location.href);
    url.searchParams.set("audience", aud);
    window.history.replaceState({}, "", url.toString());
    render();
  }

  /* Events */
  els.tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      switchAudience(tab.getAttribute("data-aud"));
    });
  });

  els.timeline.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-idx]");
    if (!btn) return;
    var idx = parseInt(btn.getAttribute("data-idx"), 10);
    if (isNaN(idx)) return;
    var move = btn.getAttribute("data-move");
    if (move === "up") {
      applyStepFromForm();
      moveStep(idx, -1);
      return;
    }
    if (move === "down") {
      applyStepFromForm();
      moveStep(idx, 1);
      return;
    }
    applyStepFromForm();
    selectStep(idx);
  });

  function onStepFieldChange() {
    applyStepFromForm();
    markDirty();
    renderTimeline();
    var step = currentStep();
    if (!step) return;
    els.bubbleTitle.textContent = step.title || "";
    els.bubbleBody.textContent = step.body || "";
    els.bubbleProgress.textContent =
      state.selected + 1 + " / " + steps().length;
  }

  [
    els.stepTitle,
    els.stepBody,
    els.stepAnchor,
    els.stepPage,
    els.stepNav,
    els.stepFooter,
    els.stepActive,
    els.stepAnchorManual,
    els.stepPageManual,
  ].forEach(function (el) {
    if (!el) return;
    el.addEventListener("input", onStepFieldChange);
    el.addEventListener("change", onStepFieldChange);
  });

  els.stepAnchor.addEventListener("change", function () {
    els.stepAnchorManual.value = els.stepAnchor.value;
    onStepFieldChange();
  });
  els.stepPage.addEventListener("change", function () {
    els.stepPageManual.value = els.stepPage.value;
    onStepFieldChange();
  });

  [els.title, els.version, els.active].forEach(function (el) {
    el.addEventListener("input", function () {
      applyMetaFromForm();
      markDirty();
    });
    el.addEventListener("change", function () {
      applyMetaFromForm();
      markDirty();
    });
  });

  els.add.addEventListener("click", addStep);
  els.save.addEventListener("click", save);
  els.del.addEventListener("click", deleteStep);
  els.prev.addEventListener("click", function () {
    applyStepFromForm();
    selectStep(state.selected - 1);
  });
  els.next.addEventListener("click", function () {
    applyStepFromForm();
    selectStep(state.selected + 1);
  });

  window.addEventListener("beforeunload", function (ev) {
    if (!state.dirty) return;
    ev.preventDefault();
    ev.returnValue = "";
  });

  render();
})();
