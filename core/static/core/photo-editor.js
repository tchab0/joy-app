/* JOY Photo Editor — mobile-first, Canvas (pas de WASM) */
(function (global) {
  "use strict";

  const MAX_EDGE = 1920;
  const JPEG_QUALITY = 0.85;
  const PREVIEW_MAX = 1200;

  const BUILTIN_PRESETS = {
    none: {
      label: "Aucun",
      exposure: 0,
      contrast: 1,
      temperature: 0,
      tint: 0,
      saturation: 1,
      vignette: 0,
      localContrast: 0,
    },
    "blue-note": {
      label: "Blue Note",
      exposure: 0,
      contrast: 1.14,
      temperature: -18,
      tint: 6,
      saturation: 0.82,
      vignette: 0.22,
      localContrast: 0.25,
    },
    "smoke-brass": {
      label: "Smoke & Brass",
      exposure: 0,
      contrast: 1.08,
      temperature: 28,
      tint: 10,
      saturation: 1.12,
      vignette: 0.18,
      localContrast: 0.15,
    },
    "stage-spot": {
      label: "Stage Spot",
      exposure: 0,
      contrast: 1.22,
      temperature: 14,
      tint: -4,
      saturation: 1.05,
      vignette: 0.42,
      localContrast: 0.45,
    },
  };

  // Clés pilotées par les thèmes (pas le débouchage — réglage manuel seul)
  const COLOR_KEYS = [
    "exposure",
    "contrast",
    "temperature",
    "tint",
    "saturation",
    "vignette",
    "localContrast",
  ];

  const DEFAULTS = {
    exposure: 0,
    contrast: 1,
    temperature: 0,
    tint: 0,
    saturation: 1,
    shadows: 0,
    vignette: 0,
    localContrast: 0,
    presetStrength: 100,
    rotate: 0,
    straighten: 0,
    crop: null,
    aspect: "free",
  };

  /** Réglages reportés d’une photo à la suivante (hors recadrage / rotation). */
  const GRADE_KEYS = [
    "exposure",
    "contrast",
    "temperature",
    "tint",
    "saturation",
    "shadows",
    "vignette",
    "localContrast",
    "presetStrength",
  ];

  const GRADE_STORAGE_KEY = "joy-pe-last-grade";
  const CUSTOM_PRESETS_KEY = "joy-pe-custom-presets";
  let rememberedGrade = null;
  /** Cache mémoire : évite un décalage UI ↔ localStorage après save/delete. */
  let customPresetsCache = null;

  function parseCustomPresets(raw) {
    if (!raw) return {};
    const list = JSON.parse(raw);
    if (!Array.isArray(list)) return {};
    const map = {};
    list.forEach((item) => {
      if (!item || !item.id || !item.label) return;
      const entry = { label: String(item.label).slice(0, 40), custom: true };
      COLOR_KEYS.forEach((k) => {
        entry[k] = typeof item[k] === "number" ? item[k] : BUILTIN_PRESETS.none[k];
      });
      map[String(item.id)] = entry;
    });
    return map;
  }

  function loadCustomPresets() {
    if (customPresetsCache) return customPresetsCache;
    try {
      customPresetsCache = parseCustomPresets(localStorage.getItem(CUSTOM_PRESETS_KEY));
    } catch (e) {
      customPresetsCache = {};
    }
    return customPresetsCache;
  }

  function saveCustomPresets(map) {
    customPresetsCache = map;
    const list = Object.keys(map).map((id) => {
      const p = map[id];
      const row = { id, label: p.label };
      COLOR_KEYS.forEach((k) => {
        row[k] = p[k];
      });
      return row;
    });
    try {
      localStorage.setItem(CUSTOM_PRESETS_KEY, JSON.stringify(list));
      return true;
    } catch (e) {
      return false;
    }
  }

  function getPreset(key) {
    if (!key) return null;
    if (BUILTIN_PRESETS[key]) return BUILTIN_PRESETS[key];
    return loadCustomPresets()[key] || null;
  }

  function allPresetKeys() {
    return Object.keys(BUILTIN_PRESETS).concat(Object.keys(loadCustomPresets()));
  }

  function loadRememberedGrade() {
    if (rememberedGrade) return rememberedGrade;
    try {
      const raw = sessionStorage.getItem(GRADE_STORAGE_KEY);
      if (raw) rememberedGrade = JSON.parse(raw);
    } catch (e) {
      /* ignore */
    }
    return rememberedGrade;
  }

  function saveRememberedGrade(preset, state) {
    const data = { preset: getPreset(preset) ? preset : "none" };
    GRADE_KEYS.forEach((k) => {
      data[k] = state[k];
    });
    rememberedGrade = data;
    try {
      sessionStorage.setItem(GRADE_STORAGE_KEY, JSON.stringify(data));
    } catch (e) {
      /* ignore */
    }
  }

  function clamp(v, a, b) {
    return Math.max(a, Math.min(b, v));
  }

  function lerp(a, b, t) {
    return a + (b - a) * t;
  }

  function pixelLuma(r, g, b) {
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function blendPreset(presetKey, strengthPct) {
    const base = BUILTIN_PRESETS.none;
    const target = getPreset(presetKey) || base;
    const t = clamp(strengthPct, 0, 150) / 100;
    const out = {};
    COLOR_KEYS.forEach((k) => {
      out[k] = lerp(base[k], target[k], t);
    });
    return out;
  }

  function slugifyPresetId(label) {
    const base = String(label)
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 24) || "theme";
    return "custom-" + base + "-" + Date.now().toString(36);
  }

  function isIdentityGrade(p) {
    return (
      Math.abs(p.exposure || 0) < 1e-6 &&
      Math.abs((p.contrast || 1) - 1) < 1e-6 &&
      Math.abs(p.temperature || 0) < 1e-6 &&
      Math.abs(p.tint || 0) < 1e-6 &&
      Math.abs((p.saturation || 1) - 1) < 1e-6 &&
      Math.abs(p.shadows || 0) < 1e-6 &&
      Math.abs(p.vignette || 0) < 1e-6 &&
      Math.abs(p.localContrast || 0) < 1e-6
    );
  }

  /** Réglages couleur enregistrables en thème (hors ombres / géométrie). */
  function hasSavableColorGrade(p) {
    return COLOR_KEYS.some((k) => {
      const def = DEFAULTS[k];
      const cur = p[k] != null ? p[k] : def;
      return Math.abs(cur - def) > 1e-4;
    });
  }

  function colorSectionSnapshot(state, preset) {
    const snap = { preset: preset || "none" };
    GRADE_KEYS.forEach((k) => {
      snap[k] = state[k] != null ? state[k] : DEFAULTS[k];
    });
    return snap;
  }

  /** True si la section Couleur / thème a été modifiée depuis l’ouverture. */
  function colorSectionChanged(state, preset, baseline) {
    if (!baseline) return hasSavableColorGrade(state);
    if ((preset || "none") !== (baseline.preset || "none")) return true;
    return GRADE_KEYS.some((k) => {
      const cur = state[k] != null ? state[k] : DEFAULTS[k];
      const base = baseline[k] != null ? baseline[k] : DEFAULTS[k];
      return Math.abs(cur - base) > 1e-4;
    });
  }

  /**
   * Grade colorimétrique :
   * 1) contraste / WB / sat / débouchage ombres
   * 2) renormalisation de la luminosité moyenne (préserve le rendu global)
   * 3) exposition (réglage manuel, après match)
   * Intermédiaires en Float32 — jamais écrire des 0–1 dans ImageData (Uint8).
   */
  function applyGlobalColor(data, p) {
    const buf = data.data;
    const n = buf.length >> 2;
    const f = new Float32Array(n * 3);

    let meanBefore = 0;
    for (let i = 0, j = 0; i < buf.length; i += 4, j += 3) {
      const r = buf[i] / 255;
      const g = buf[i + 1] / 255;
      const b = buf[i + 2] / 255;
      f[j] = r;
      f[j + 1] = g;
      f[j + 2] = b;
      meanBefore += pixelLuma(r, g, b);
    }
    meanBefore /= n || 1;

    const contrast = p.contrast;
    const temp = p.temperature / 100;
    const tint = p.tint / 100;
    const sat = p.saturation;
    const shadows = clamp(p.shadows || 0, 0, 1);

    let meanAfter = 0;
    for (let j = 0; j < f.length; j += 3) {
      let r = f[j];
      let g = f[j + 1];
      let b = f[j + 2];

      r = (r - 0.5) * contrast + 0.5;
      g = (g - 0.5) * contrast + 0.5;
      b = (b - 0.5) * contrast + 0.5;

      r += temp * 0.15;
      b -= temp * 0.15;
      g += tint * 0.1;
      r -= tint * 0.05;
      b -= tint * 0.05;

      let luma = pixelLuma(r, g, b);
      r = luma + (r - luma) * sat;
      g = luma + (g - luma) * sat;
      b = luma + (b - luma) * sat;

      luma = pixelLuma(r, g, b);
      const lift = shadows * Math.pow(1 - clamp(luma, 0, 1), 2.2);
      r += lift;
      g += lift;
      b += lift;

      f[j] = r;
      f[j + 1] = g;
      f[j + 2] = b;
      meanAfter += pixelLuma(r, g, b);
    }
    meanAfter /= n || 1;

    const gain = meanAfter > 1e-6 ? meanBefore / meanAfter : 1;
    const exp = Math.pow(2, p.exposure || 0);
    const scale = gain * exp;

    for (let i = 0, j = 0; i < buf.length; i += 4, j += 3) {
      buf[i] = clamp(f[j] * scale, 0, 1) * 255;
      buf[i + 1] = clamp(f[j + 1] * scale, 0, 1) * 255;
      buf[i + 2] = clamp(f[j + 2] * scale, 0, 1) * 255;
    }
  }

  /** Contraste local (clarity) via high-pass sur flou downscalé — rapide sur mobile. */
  function applyLocalContrast(canvas, amount) {
    if (!amount) return;
    const w = canvas.width;
    const h = canvas.height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const orig = ctx.getImageData(0, 0, w, h);

    const sw = Math.max(1, Math.round(w / 8));
    const sh = Math.max(1, Math.round(h / 8));
    const small = document.createElement("canvas");
    small.width = sw;
    small.height = sh;
    small.getContext("2d").drawImage(canvas, 0, 0, sw, sh);
    const blurC = document.createElement("canvas");
    blurC.width = w;
    blurC.height = h;
    const bctx = blurC.getContext("2d");
    bctx.imageSmoothingEnabled = true;
    bctx.imageSmoothingQuality = "high";
    bctx.drawImage(small, 0, 0, w, h);
    const blurred = bctx.getImageData(0, 0, w, h);

    const a = clamp(amount, -1, 1.5);
    const o = orig.data;
    const b = blurred.data;
    for (let i = 0; i < o.length; i += 4) {
      o[i] = clamp(o[i] + a * (o[i] - b[i]), 0, 255);
      o[i + 1] = clamp(o[i + 1] + a * (o[i + 1] - b[i + 1]), 0, 255);
      o[i + 2] = clamp(o[i + 2] + a * (o[i + 2] - b[i + 2]), 0, 255);
    }
    ctx.putImageData(orig, 0, 0);
  }

  function applyVignette(data, amount, midpoint) {
    if (!amount) return;
    const w = data.width;
    const h = data.height;
    const buf = data.data;
    const mid = midpoint || 0.55;
    const strength = clamp(amount, 0, 1);
    const cx = (w - 1) / 2;
    const cy = (h - 1) / 2;
    const maxD = Math.sqrt(cx * cx + cy * cy) || 1;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        const dx = (x - cx) / maxD;
        const dy = (y - cy) / maxD;
        const d = Math.sqrt(dx * dx + dy * dy);
        const t = clamp((d - mid) / (1 - mid + 0.001), 0, 1);
        const vig = 1 - strength * (t * t);
        buf[i] *= vig;
        buf[i + 1] *= vig;
        buf[i + 2] *= vig;
      }
    }
  }

  /** Pipeline complet sur un canvas source (mutates). Neutre = no-op. */
  function applyPipeline(canvas, p) {
    if (isIdentityGrade(p)) return;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const id = ctx.getImageData(0, 0, canvas.width, canvas.height);
    applyGlobalColor(id, p);
    ctx.putImageData(id, 0, 0);
    applyLocalContrast(canvas, p.localContrast || 0);
    if (p.vignette) {
      const id2 = ctx.getImageData(0, 0, canvas.width, canvas.height);
      applyVignette(id2, p.vignette, 0.5);
      ctx.putImageData(id2, 0, 0);
    }
  }

  /** Drawable avec naturalWidth/Height, sans ré-encodage JPEG. */
  function bitmapToDrawable(bitmap) {
    const c = document.createElement("canvas");
    c.width = bitmap.width;
    c.height = bitmap.height;
    c.getContext("2d").drawImage(bitmap, 0, 0);
    if (bitmap.close) bitmap.close();
    Object.defineProperty(c, "naturalWidth", { get: () => c.width });
    Object.defineProperty(c, "naturalHeight", { get: () => c.height });
    return c;
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const fallbackUrl = (url) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        if (typeof url === "string" && !url.startsWith("blob:") && !url.startsWith("data:")) {
          img.crossOrigin = "anonymous";
        }
        img.src = url;
      };

      const asUrl = () => {
        if (typeof src === "string") return Promise.resolve(src);
        return Promise.resolve(URL.createObjectURL(src));
      };

      if (typeof createImageBitmap === "function") {
        const blobP =
          typeof src === "string"
            ? fetch(src).then((r) => r.blob())
            : Promise.resolve(src);
        blobP
          .then((blob) => createImageBitmap(blob, { imageOrientation: "from-image" }))
          .then((bitmap) => resolve(bitmapToDrawable(bitmap)))
          .catch(() => asUrl().then(fallbackUrl).catch(reject));
        return;
      }
      asUrl().then(fallbackUrl).catch(reject);
    });
  }

  function fileToUrl(fileOrUrl) {
    return Promise.resolve(fileOrUrl);
  }

  function totalRotation(state) {
    return state.rotate + state.straighten;
  }

  function rotatedSize(w, h, deg) {
    const rad = (deg * Math.PI) / 180;
    const c = Math.abs(Math.cos(rad));
    const s = Math.abs(Math.sin(rad));
    return {
      w: Math.ceil(w * c + h * s),
      h: Math.ceil(w * s + h * c),
    };
  }

  /** Dessine l'image source pivotée dans un canvas (plein cadre). */
  function drawRotated(img, deg, maxEdge) {
    const scale =
      maxEdge && Math.max(img.naturalWidth, img.naturalHeight) > maxEdge
        ? maxEdge / Math.max(img.naturalWidth, img.naturalHeight)
        : 1;
    const sw = Math.round(img.naturalWidth * scale);
    const sh = Math.round(img.naturalHeight * scale);
    const size = rotatedSize(sw, sh, deg);
    const c = document.createElement("canvas");
    c.width = size.w;
    c.height = size.h;
    const ctx = c.getContext("2d");
    ctx.translate(size.w / 2, size.h / 2);
    ctx.rotate((deg * Math.PI) / 180);
    ctx.drawImage(img, -sw / 2, -sh / 2, sw, sh);
    return c;
  }

  function cropCanvas(srcCanvas, crop) {
    const x = Math.round(clamp(crop.x, 0, srcCanvas.width - 1));
    const y = Math.round(clamp(crop.y, 0, srcCanvas.height - 1));
    const w = Math.round(clamp(crop.w, 1, srcCanvas.width - x));
    const h = Math.round(clamp(crop.h, 1, srcCanvas.height - y));
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    c.getContext("2d").drawImage(srcCanvas, x, y, w, h, 0, 0, w, h);
    return c;
  }

  function fitMaxEdge(canvas, maxEdge) {
    const m = Math.max(canvas.width, canvas.height);
    if (m <= maxEdge) return canvas;
    const s = maxEdge / m;
    const c = document.createElement("canvas");
    c.width = Math.round(canvas.width * s);
    c.height = Math.round(canvas.height * s);
    c.getContext("2d").drawImage(canvas, 0, 0, c.width, c.height);
    return c;
  }

  function buildUI() {
    const root = document.createElement("div");
    root.className = "joy-pe";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-label", "Éditeur photo");
    root.innerHTML = `
      <div class="joy-pe-sheet">
        <header class="joy-pe-header">
          <button type="button" class="joy-pe-btn joy-pe-cancel" data-act="cancel">Annuler</button>
          <span class="joy-pe-title">Améliorer</span>
          <button type="button" class="joy-pe-btn joy-pe-save" data-act="save">Comparer</button>
        </header>
        <div class="joy-pe-editor">
          <div class="joy-pe-stage">
            <canvas class="joy-pe-canvas"></canvas>
            <div class="joy-pe-crop" hidden>
              <div class="joy-pe-crop-box">
                <span class="joy-pe-handle nw" data-h="nw"></span>
                <span class="joy-pe-handle ne" data-h="ne"></span>
                <span class="joy-pe-handle sw" data-h="sw"></span>
                <span class="joy-pe-handle se" data-h="se"></span>
              </div>
            </div>
          </div>
          <div class="joy-pe-controls-wrap">
          <div class="joy-pe-controls" data-controls>
          <div class="joy-pe-presets" role="list"></div>
          <div class="joy-pe-preset-actions">
            <button type="button" class="joy-pe-chip" data-act="save-preset">Enregistrer thème…</button>
            <button type="button" class="joy-pe-chip joy-pe-chip-danger" data-act="delete-preset" hidden>Supprimer le thème</button>
          </div>
          <div class="joy-pe-preset-form" hidden>
            <label class="joy-pe-preset-form-label">Nom du thème</label>
            <div class="joy-pe-preset-form-row">
              <input type="text" class="joy-pe-preset-name" maxlength="40" placeholder="Ex. Salle Jazz" autocomplete="off">
              <button type="button" class="joy-pe-btn joy-pe-save" data-act="confirm-preset">OK</button>
              <button type="button" class="joy-pe-btn" data-act="cancel-preset">Annuler</button>
            </div>
          </div>
          <div class="joy-pe-row joy-pe-preset-strength">
            <label>Puissance du thème <span data-val="presetStrength">100%</span></label>
            <input type="range" min="0" max="150" step="1" value="100" data-key="presetStrength" disabled>
          </div>
          <div class="joy-pe-tabs">
            <button type="button" class="joy-pe-tab active" data-tab="crop">Recadrer</button>
            <button type="button" class="joy-pe-tab" data-tab="color">Couleur</button>
          </div>
          <div class="joy-pe-panel" data-panel="crop">
            <div class="joy-pe-row">
              <label>Horizon <span data-val="straighten">0°</span></label>
              <input type="range" min="-15" max="15" step="0.5" value="0" data-key="straighten">
            </div>
            <div class="joy-pe-row joy-pe-actions">
              <button type="button" class="joy-pe-chip" data-act="rot-ccw">↺ 90°</button>
              <button type="button" class="joy-pe-chip" data-act="rot-cw">↻ 90°</button>
              <button type="button" class="joy-pe-chip" data-act="aspect-free">Libre</button>
              <button type="button" class="joy-pe-chip" data-act="aspect-4-3">4:3</button>
              <button type="button" class="joy-pe-chip" data-act="aspect-16-9">16:9</button>
              <button type="button" class="joy-pe-chip" data-act="reset-crop">Reset cadre</button>
            </div>
          </div>
          <div class="joy-pe-panel" data-panel="color" hidden>
            <div class="joy-pe-row">
              <label>Exposition <span data-val="exposure">0</span></label>
              <input type="range" min="-1" max="1" step="0.01" value="0" data-key="exposure">
            </div>
            <div class="joy-pe-row">
              <label>Contraste <span data-val="contrast">1</span></label>
              <input type="range" min="0.5" max="1.8" step="0.01" value="1" data-key="contrast">
            </div>
            <div class="joy-pe-row">
              <label>Ombres (débouchage) <span data-val="shadows">0</span></label>
              <input type="range" min="0" max="1" step="0.01" value="0" data-key="shadows">
            </div>
            <div class="joy-pe-row">
              <label>Contraste local <span data-val="localContrast">0</span></label>
              <input type="range" min="0" max="1" step="0.01" value="0" data-key="localContrast">
            </div>
            <div class="joy-pe-row">
              <label>Température <span data-val="temperature">0</span></label>
              <input type="range" min="-50" max="50" step="1" value="0" data-key="temperature">
            </div>
            <div class="joy-pe-row">
              <label>Teinte <span data-val="tint">0</span></label>
              <input type="range" min="-50" max="50" step="1" value="0" data-key="tint">
            </div>
            <div class="joy-pe-row">
              <label>Saturation <span data-val="saturation">1</span></label>
              <input type="range" min="0" max="2" step="0.01" value="1" data-key="saturation">
            </div>
            <div class="joy-pe-row">
              <label>Vignettage <span data-val="vignette">0</span></label>
              <input type="range" min="0" max="1" step="0.01" value="0" data-key="vignette">
            </div>
          </div>
          </div>
          <div class="joy-pe-controls-nav" aria-label="Défiler les réglages">
            <button type="button" class="joy-pe-scroll-btn" data-act="scroll-up" aria-label="Monter dans les réglages">▲</button>
            <button type="button" class="joy-pe-scroll-btn" data-act="scroll-down" aria-label="Descendre dans les réglages">▼</button>
          </div>
          </div>
        </div>
        <div class="joy-pe-compare" hidden>
          <p class="joy-pe-compare-hint">Glissez pour comparer avant / après (même cadrage)</p>
          <div class="joy-pe-compare-stage">
            <img class="joy-pe-compare-before" alt="Avant">
            <div class="joy-pe-compare-after-clip">
              <img class="joy-pe-compare-after" alt="Après">
            </div>
            <div class="joy-pe-compare-divider" aria-hidden="true"></div>
            <input type="range" class="joy-pe-compare-slider" min="0" max="100" value="50" aria-label="Comparaison avant après">
            <span class="joy-pe-compare-label joy-pe-compare-label-before">Avant</span>
            <span class="joy-pe-compare-label joy-pe-compare-label-after">Après</span>
          </div>
          <div class="joy-pe-compare-actions">
            <button type="button" class="joy-pe-btn" data-act="back-edit">Retoucher</button>
            <button type="button" class="joy-pe-btn joy-pe-save" data-act="confirm">Valider</button>
          </div>
        </div>
      </div>
    `;

    return root;
  }

  class PhotoEditor {
    constructor() {
      this.root = null;
      this.state = { ...DEFAULTS };
      this.img = null;
      this.objectUrl = null;
      this.onSave = null;
      this.onCancel = null;
      this._raf = 0;
      this._dirty = true;
      this._view = { scale: 1, ox: 0, oy: 0, cw: 0, ch: 0 };
      this._drag = null;
      this._preset = "none";
      this._pendingFile = null;
      this._afterObjectUrl = null;
      this._beforeCompareUrl = null;
      this._beforePreviewUrl = null;
      this._gradeAtOpen = null;
    }

    open({ source, onSave, onCancel }) {
      this.close(true);
      this.onSave = onSave;
      this.onCancel = onCancel;
      this._pendingFile = null;

      // Géométrie toujours neuve ; colorimétrie = dernier réglage validé
      this.state = { ...DEFAULTS };
      this._preset = "none";
      const mem = loadRememberedGrade();
      if (mem) {
        this._preset = getPreset(mem.preset) ? mem.preset : "none";
        GRADE_KEYS.forEach((k) => {
          if (mem[k] != null) this.state[k] = mem[k];
        });
      }
      this._gradeAtOpen = colorSectionSnapshot(this.state, this._preset);

      this.root = buildUI();
      document.body.appendChild(this.root);
      document.body.classList.add("joy-pe-open");

      this.canvas = this.root.querySelector(".joy-pe-canvas");
      this.ctx = this.canvas.getContext("2d", { willReadFrequently: true });
      this.cropOverlay = this.root.querySelector(".joy-pe-crop");
      this.cropBox = this.root.querySelector(".joy-pe-crop-box");
      this.editorPane = this.root.querySelector(".joy-pe-editor");
      this.comparePane = this.root.querySelector(".joy-pe-compare");

      this._bind();
      this._renderPresetButtons();
      this._setTab("crop");
      this._showCompare(false);
      this._syncUiFromState();

      fileToUrl(source).then(async (urlOrFile) => {
        this.objectUrl = null;
        this.img = await loadImage(urlOrFile);
        this._beforePreviewUrl = this._makeBeforePreview(this.img);
        this._resetCropFull();
        this._scheduleRender();
      }).catch(() => {
        alert("Impossible de charger l'image.");
        this.close();
      });
    }

    close(silent) {
      if (this._raf) cancelAnimationFrame(this._raf);
      if (this.objectUrl) {
        URL.revokeObjectURL(this.objectUrl);
        this.objectUrl = null;
      }
      if (this._afterObjectUrl) {
        URL.revokeObjectURL(this._afterObjectUrl);
        this._afterObjectUrl = null;
      }
      if (this._beforeCompareUrl) {
        URL.revokeObjectURL(this._beforeCompareUrl);
        this._beforeCompareUrl = null;
      }
      this._pendingFile = null;
      this._beforePreviewUrl = null;
      if (this.root) {
        this.root.remove();
        this.root = null;
      }
      document.body.classList.remove("joy-pe-open");
      if (!silent && this.onCancel) this.onCancel();
    }

    _makeBeforePreview(img) {
      const max = 1200;
      const scale =
        Math.max(img.naturalWidth, img.naturalHeight) > max
          ? max / Math.max(img.naturalWidth, img.naturalHeight)
          : 1;
      const c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * scale);
      c.height = Math.round(img.naturalHeight * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      return c.toDataURL("image/jpeg", 0.85);
    }

    _showCompare(on) {
      if (!this.root) return;
      this.editorPane.hidden = !!on;
      this.comparePane.hidden = !on;
      const title = this.root.querySelector(".joy-pe-title");
      const saveBtn = this.root.querySelector('[data-act="save"]');
      if (on) {
        title.textContent = "Comparer";
        saveBtn.hidden = true;
      } else {
        title.textContent = "Améliorer";
        saveBtn.hidden = false;
        saveBtn.disabled = false;
        saveBtn.textContent = "Comparer";
      }
    }

    _setCompareSplit(pct) {
      const clip = this.root.querySelector(".joy-pe-compare-after-clip");
      const divider = this.root.querySelector(".joy-pe-compare-divider");
      const afterImg = this.root.querySelector(".joy-pe-compare-after");
      const stage = this.root.querySelector(".joy-pe-compare-stage");
      if (!clip || !stage) return;
      const p = clamp(pct, 0, 100);
      clip.style.width = p + "%";
      if (divider) divider.style.left = p + "%";
      // Keep after image full-width of stage so crop reveal works
      if (afterImg && stage.clientWidth) {
        afterImg.style.width = stage.clientWidth + "px";
      }
    }

    _bind() {
      const root = this.root;
      root.querySelector('[data-act="cancel"]').addEventListener("click", () => this.close());
      root.querySelector('[data-act="save"]').addEventListener("click", () => this._prepareCompare());
      root.querySelector('[data-act="back-edit"]').addEventListener("click", () => {
        if (this._afterObjectUrl) {
          URL.revokeObjectURL(this._afterObjectUrl);
          this._afterObjectUrl = null;
        }
        if (this._beforeCompareUrl) {
          URL.revokeObjectURL(this._beforeCompareUrl);
          this._beforeCompareUrl = null;
        }
        this._pendingFile = null;
        this._showCompare(false);
        this._scheduleRender();
      });
      root.querySelector('[data-act="confirm"]').addEventListener("click", () => this._confirmSave());

      const slider = root.querySelector(".joy-pe-compare-slider");
      slider.addEventListener("input", () => this._setCompareSplit(parseFloat(slider.value)));

      root.querySelectorAll(".joy-pe-tab").forEach((btn) => {
        btn.addEventListener("click", () => this._setTab(btn.dataset.tab));
      });

      // Presets : délégation (boutons reconstruits dynamiquement)
      root.querySelector(".joy-pe-presets").addEventListener("click", (e) => {
        const delBtn = e.target.closest(".joy-pe-preset-del");
        if (delBtn) {
          e.preventDefault();
          e.stopPropagation();
          this._deletePresetById(delBtn.dataset.del);
          return;
        }
        const btn = e.target.closest(".joy-pe-preset");
        if (btn) this._applyPreset(btn.dataset.preset);
      });

      root.querySelector('[data-act="save-preset"]').addEventListener("click", () => {
        this._togglePresetForm(true);
      });
      root.querySelector('[data-act="cancel-preset"]').addEventListener("click", () => {
        this._togglePresetForm(false);
      });
      root.querySelector('[data-act="confirm-preset"]').addEventListener("click", () => {
        this._saveCurrentAsPreset();
      });
      root.querySelector('[data-act="delete-preset"]').addEventListener("click", () => {
        this._deletePresetById(this._preset);
      });
      const nameInput = root.querySelector(".joy-pe-preset-name");
      nameInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          this._saveCurrentAsPreset();
        }
      });

      root.querySelector('[data-act="scroll-up"]').addEventListener("click", () => {
        this._scrollControls(-1);
      });
      root.querySelector('[data-act="scroll-down"]').addEventListener("click", () => {
        this._scrollControls(1);
      });

      this._bindScrollFriendlyRanges(root.querySelector("[data-controls]"));

      root.querySelectorAll("input[type=range][data-key]").forEach((input) => {
        input.addEventListener("input", () => {
          const key = input.dataset.key;
          let v = parseFloat(input.value);
          if (key === "presetStrength") {
            this.state.presetStrength = v;
            this._reapplyPresetStrength();
            return;
          }
          this.state[key] = v;
          this._syncLabels();
          if (key === "straighten") {
            this._resetCropFull();
          }
          this._scheduleRender();
        });
      });

      root.querySelector('[data-act="rot-ccw"]').addEventListener("click", () => {
        this.state.rotate = (this.state.rotate - 90) % 360;
        this._resetCropFull();
        this._scheduleRender();
      });
      root.querySelector('[data-act="rot-cw"]').addEventListener("click", () => {
        this.state.rotate = (this.state.rotate + 90) % 360;
        this._resetCropFull();
        this._scheduleRender();
      });
      root.querySelector('[data-act="aspect-free"]').addEventListener("click", () => {
        this.state.aspect = "free";
      });
      root.querySelector('[data-act="aspect-4-3"]').addEventListener("click", () => {
        this.state.aspect = "4:3";
        this._enforceAspect();
        this._updateCropDom();
        this._scheduleRender();
      });
      root.querySelector('[data-act="aspect-16-9"]').addEventListener("click", () => {
        this.state.aspect = "16:9";
        this._enforceAspect();
        this._updateCropDom();
        this._scheduleRender();
      });
      root.querySelector('[data-act="reset-crop"]').addEventListener("click", () => {
        this._resetCropFull();
        this._scheduleRender();
      });

      const stage = root.querySelector(".joy-pe-stage");
      stage.addEventListener("pointerdown", (e) => this._onPointerDown(e));
      stage.addEventListener("pointermove", (e) => this._onPointerMove(e));
      stage.addEventListener("pointerup", (e) => this._onPointerUp(e));
      stage.addEventListener("pointercancel", (e) => this._onPointerUp(e));

      window.addEventListener("resize", this._onResize = () => {
        if (!this.comparePane.hidden) {
          const sl = this.root.querySelector(".joy-pe-compare-slider");
          this._setCompareSplit(parseFloat(sl.value));
        } else {
          this._scheduleRender();
        }
      });
    }

    _renderPresetButtons() {
      const presetsEl = this.root.querySelector(".joy-pe-presets");
      if (!presetsEl) return;
      presetsEl.innerHTML = "";
      allPresetKeys().forEach((key) => {
        const p = getPreset(key);
        if (!p) return;
        if (p.custom) {
          const wrap = document.createElement("div");
          wrap.className = "joy-pe-preset-wrap";
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "joy-pe-preset joy-pe-preset-custom" + (key === this._preset ? " active" : "");
          btn.dataset.preset = key;
          btn.textContent = p.label;
          const del = document.createElement("button");
          del.type = "button";
          del.className = "joy-pe-preset-del";
          del.dataset.del = key;
          del.setAttribute("aria-label", "Supprimer « " + p.label + " »");
          del.textContent = "×";
          wrap.appendChild(btn);
          wrap.appendChild(del);
          presetsEl.appendChild(wrap);
        } else {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "joy-pe-preset" + (key === this._preset ? " active" : "");
          btn.dataset.preset = key;
          btn.textContent = p.label;
          presetsEl.appendChild(btn);
        }
      });
      this._updatePresetActionVisibility();
      const active = presetsEl.querySelector(".joy-pe-preset.active");
      if (active && typeof active.scrollIntoView === "function") {
        active.scrollIntoView({ inline: "nearest", block: "nearest", behavior: "smooth" });
      }
    }

    _updatePresetActionVisibility() {
      const del = this.root.querySelector('[data-act="delete-preset"]');
      if (!del) return;
      const p = getPreset(this._preset);
      del.hidden = !(p && p.custom);
    }

    _togglePresetForm(show) {
      const form = this.root.querySelector(".joy-pe-preset-form");
      const input = this.root.querySelector(".joy-pe-preset-name");
      form.hidden = !show;
      if (show) {
        input.value = "";
        input.focus();
        form.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    }

    _saveCurrentAsPreset() {
      const input = this.root.querySelector(".joy-pe-preset-name");
      const label = (input.value || "").trim();
      if (!label) {
        input.focus();
        return false;
      }
      if (!this._persistPresetLabel(label)) return false;
      this._togglePresetForm(false);
      return true;
    }

    _persistPresetLabel(label) {
      const id = slugifyPresetId(label);
      const map = Object.assign({}, loadCustomPresets());
      const entry = { label, custom: true };
      COLOR_KEYS.forEach((k) => {
        entry[k] = this.state[k];
      });
      map[id] = entry;
      if (!saveCustomPresets(map)) {
        alert("Impossible d’enregistrer le thème (stockage navigateur indisponible).");
        return false;
      }
      this._preset = id;
      this.state.presetStrength = 100;
      if (this.root) {
        this._renderPresetButtons();
        this._syncUiFromState();
        this._scheduleRender();
      }
      return true;
    }

    _offerSavePresetOnConfirm() {
      if (!hasSavableColorGrade(this.state)) return "no_grade";
      if (!colorSectionChanged(this.state, this._preset, this._gradeAtOpen)) {
        return "unchanged";
      }
      // Annuler = pas de thème ; la photo est quand même enregistrée juste après.
      if (!confirm("La photo va être enregistrée.\n\nEnregistrer aussi ces réglages couleur comme nouveau thème ?")) {
        return "declined";
      }
      const label = (window.prompt("Nom du thème :", "") || "").trim();
      if (!label) return "empty_label";
      this._persistPresetLabel(label);
      return "saved";
    }

    _deletePresetById(id) {
      const p = getPreset(id);
      if (!p || !p.custom) return;
      if (!confirm('Supprimer le thème « ' + p.label + ' » ?')) return;
      const map = Object.assign({}, loadCustomPresets());
      delete map[id];
      if (!saveCustomPresets(map)) {
        alert("Impossible de supprimer le thème.");
        return;
      }
      if (this._preset === id) {
        this._applyPreset("none");
      }
      this._renderPresetButtons();
    }

    _scrollControls(dir) {
      const el = this.root && this.root.querySelector("[data-controls]");
      if (!el) return;
      const step = Math.max(72, Math.round(el.clientHeight * 0.45));
      el.scrollBy({ top: dir * step, behavior: "smooth" });
    }

    /** Glisser verticalement sur un curseur = défile le panneau, sans changer la valeur. */
    _bindScrollFriendlyRanges(scrollEl) {
      if (!scrollEl) return;
      scrollEl.querySelectorAll("input[type=range]").forEach((input) => {
        let sx = 0;
        let sy = 0;
        let lastY = 0;
        let mode = null; // null | "slide" | "scroll"
        let frozen = null;

        input.addEventListener(
          "touchstart",
          (e) => {
            if (!e.touches[0]) return;
            sx = e.touches[0].clientX;
            sy = e.touches[0].clientY;
            lastY = sy;
            mode = null;
            frozen = input.value;
          },
          { passive: true }
        );

        input.addEventListener(
          "touchmove",
          (e) => {
            if (!e.touches[0]) return;
            const t = e.touches[0];
            const dx = Math.abs(t.clientX - sx);
            const dy = Math.abs(t.clientY - sy);
            if (mode == null && (dx > 8 || dy > 8)) {
              mode = dy > dx ? "scroll" : "slide";
            }
            if (mode === "scroll") {
              e.preventDefault();
              if (frozen != null) input.value = frozen;
              scrollEl.scrollTop += lastY - t.clientY;
              lastY = t.clientY;
            }
          },
          { passive: false }
        );

        const end = () => {
          if (mode === "scroll" && frozen != null) input.value = frozen;
          mode = null;
          frozen = null;
        };
        input.addEventListener("touchend", end);
        input.addEventListener("touchcancel", end);
      });
    }

    _syncUiFromState() {
      if (!this.root) return;
      this.root.querySelectorAll(".joy-pe-preset").forEach((b) => {
        b.classList.toggle("active", b.dataset.preset === this._preset);
      });
      const strengthInput = this.root.querySelector('input[data-key="presetStrength"]');
      if (strengthInput) {
        strengthInput.disabled = this._preset === "none";
        strengthInput.value = this.state.presetStrength;
      }
      GRADE_KEYS.concat(["straighten"]).forEach((k) => {
        const input = this.root.querySelector(`input[data-key="${k}"]`);
        if (input && this.state[k] != null) input.value = this.state[k];
      });
      this._updatePresetActionVisibility();
      this._syncLabels();
    }

    _setTab(tab) {
      this.root.classList.toggle("joy-pe-mode-color", tab === "color");
      this.root.querySelectorAll(".joy-pe-tab").forEach((b) => {
        b.classList.toggle("active", b.dataset.tab === tab);
      });
      this.root.querySelectorAll(".joy-pe-panel").forEach((p) => {
        p.hidden = p.dataset.panel !== tab;
      });
      this.cropOverlay.hidden = tab !== "crop";
      if (tab === "crop") this._updateCropDom();
      this._scheduleRender();
    }

    _applyPreset(key) {
      if (!getPreset(key)) return;
      this._preset = key;
      if (key !== "none") {
        this.state.presetStrength = 100;
      }
      this.root.querySelectorAll(".joy-pe-preset").forEach((b) => {
        b.classList.toggle("active", b.dataset.preset === key);
      });
      const strengthInput = this.root.querySelector('input[data-key="presetStrength"]');
      if (strengthInput) {
        strengthInput.disabled = key === "none";
        strengthInput.value = this.state.presetStrength;
      }
      this._updatePresetActionVisibility();
      this._reapplyPresetStrength();
    }

    _reapplyPresetStrength() {
      const blended = blendPreset(this._preset, this.state.presetStrength);
      COLOR_KEYS.forEach((k) => {
        this.state[k] = blended[k];
        const input = this.root.querySelector(`input[data-key="${k}"]`);
        if (input) input.value = blended[k];
      });
      const strengthInput = this.root.querySelector('input[data-key="presetStrength"]');
      if (strengthInput) strengthInput.value = this.state.presetStrength;
      this._syncLabels();
      this._scheduleRender();
    }

    _syncLabels() {
      const fmt = {
        exposure: (v) => v.toFixed(2),
        contrast: (v) => v.toFixed(2),
        temperature: (v) => String(Math.round(v)),
        tint: (v) => String(Math.round(v)),
        saturation: (v) => v.toFixed(2),
        straighten: (v) => `${v}°`,
        shadows: (v) => v.toFixed(2),
        vignette: (v) => v.toFixed(2),
        localContrast: (v) => v.toFixed(2),
        presetStrength: (v) => `${Math.round(v)}%`,
      };
      Object.keys(fmt).forEach((k) => {
        const el = this.root.querySelector(`[data-val="${k}"]`);
        if (el) el.textContent = fmt[k](this.state[k]);
      });
    }

    _rotatedBase(maxEdge) {
      return drawRotated(this.img, totalRotation(this.state), maxEdge);
    }

    _resetCropFull() {
      if (!this.img) return;
      const base = this._rotatedBase(PREVIEW_MAX);
      this.state.crop = { x: 0, y: 0, w: base.width, h: base.height };
      this._previewBaseSize = { w: base.width, h: base.height };
    }

    _enforceAspect() {
      const crop = this.state.crop;
      if (!crop || this.state.aspect === "free") return;
      const [aw, ah] = this.state.aspect.split(":").map(Number);
      const target = aw / ah;
      let { x, y, w, h } = crop;
      const cx = x + w / 2;
      const cy = y + h / 2;
      if (w / h > target) {
        w = h * target;
      } else {
        h = w / target;
      }
      const bw = this._previewBaseSize.w;
      const bh = this._previewBaseSize.h;
      x = clamp(cx - w / 2, 0, bw - w);
      y = clamp(cy - h / 2, 0, bh - h);
      this.state.crop = { x, y, w, h };
    }

    _scheduleRender() {
      this._dirty = true;
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => {
        this._raf = 0;
        if (this._dirty) this._render();
      });
    }

    _render() {
      if (!this.img || !this.canvas) return;
      this._dirty = false;
      const stage = this.root.querySelector(".joy-pe-stage");
      const maxW = stage.clientWidth;
      const maxH = stage.clientHeight;

      let base = this._rotatedBase(PREVIEW_MAX);
      if (
        this._previewBaseSize &&
        (this._previewBaseSize.w !== base.width || this._previewBaseSize.h !== base.height)
      ) {
        const sx = base.width / this._previewBaseSize.w;
        const sy = base.height / this._previewBaseSize.h;
        const c = this.state.crop;
        this.state.crop = {
          x: c.x * sx,
          y: c.y * sy,
          w: c.w * sx,
          h: c.h * sy,
        };
        this._previewBaseSize = { w: base.width, h: base.height };
      }

      // Aperçu = image entière (filtres) ; le cadre de crop est en overlay
      const work = document.createElement("canvas");
      work.width = base.width;
      work.height = base.height;
      const wctx = work.getContext("2d");
      wctx.drawImage(base, 0, 0);
      applyPipeline(work, this.state);

      const fit = Math.min(maxW / work.width, maxH / work.height, 1);
      const dw = Math.round(work.width * fit);
      const dh = Math.round(work.height * fit);
      this.canvas.width = dw;
      this.canvas.height = dh;
      this.ctx.drawImage(work, 0, 0, dw, dh);

      const rect = this.canvas.getBoundingClientRect();
      const stageRect = stage.getBoundingClientRect();
      this._view = {
        scale: fit,
        ox: rect.left - stageRect.left,
        oy: rect.top - stageRect.top,
        bw: base.width,
        bh: base.height,
      };
      this._updateCropDom();
    }

    _updateCropDom() {
      if (!this.state.crop || this.cropOverlay.hidden) return;
      const v = this._view;
      const c = this.state.crop;
      const left = v.ox + c.x * v.scale;
      const top = v.oy + c.y * v.scale;
      const w = c.w * v.scale;
      const h = c.h * v.scale;
      Object.assign(this.cropBox.style, {
        left: `${left}px`,
        top: `${top}px`,
        width: `${w}px`,
        height: `${h}px`,
      });
    }

    _onPointerDown(e) {
      if (this.cropOverlay.hidden) return;
      const handle = e.target.closest(".joy-pe-handle");
      const onBox = e.target.closest(".joy-pe-crop-box");
      if (!handle && !onBox) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      this._drag = {
        mode: handle ? handle.dataset.h : "move",
        x0: e.clientX,
        y0: e.clientY,
        crop0: { ...this.state.crop },
      };
    }

    _onPointerMove(e) {
      if (!this._drag) return;
      const dx = (e.clientX - this._drag.x0) / this._view.scale;
      const dy = (e.clientY - this._drag.y0) / this._view.scale;
      let { x, y, w, h } = this._drag.crop0;
      const bw = this._view.bw;
      const bh = this._view.bh;
      const mode = this._drag.mode;

      if (mode === "move") {
        x = clamp(x + dx, 0, bw - w);
        y = clamp(y + dy, 0, bh - h);
      } else {
        if (mode.includes("w")) {
          const nx = clamp(x + dx, 0, x + w - 20);
          w = w - (nx - x);
          x = nx;
        }
        if (mode.includes("e")) {
          w = clamp(w + dx, 20, bw - x);
        }
        if (mode.includes("n")) {
          const ny = clamp(y + dy, 0, y + h - 20);
          h = h - (ny - y);
          y = ny;
        }
        if (mode.includes("s")) {
          h = clamp(h + dy, 20, bh - y);
        }
      }
      this.state.crop = { x, y, w, h };
      if (this.state.aspect !== "free") this._enforceAspect();
      this._updateCropDom();
      this._scheduleRender();
    }

    _onPointerUp() {
      this._drag = null;
    }

    async _prepareCompare() {
      if (!this.img) return;
      const btn = this.root.querySelector('[data-act="save"]');
      btn.disabled = true;
      btn.textContent = "…";

      try {
        const full = drawRotated(this.img, totalRotation(this.state), null);
        const sx = full.width / this._previewBaseSize.w;
        const sy = full.height / this._previewBaseSize.h;
        const c = this.state.crop;
        const crop = {
          x: c.x * sx,
          y: c.y * sy,
          w: c.w * sx,
          h: c.h * sy,
        };

        // Avant = même cadrage / rotation, sans grade couleur
        let before = cropCanvas(full, crop);
        before = fitMaxEdge(before, MAX_EDGE);

        // Après = même surface + pipeline
        let after = document.createElement("canvas");
        after.width = before.width;
        after.height = before.height;
        after.getContext("2d").drawImage(before, 0, 0);
        applyPipeline(after, this.state);

        const beforeBlob = await new Promise((resolve) =>
          before.toBlob(resolve, "image/jpeg", JPEG_QUALITY)
        );
        const afterBlob = await new Promise((resolve) =>
          after.toBlob(resolve, "image/jpeg", JPEG_QUALITY)
        );
        if (!beforeBlob || !afterBlob) throw new Error("export failed");
        this._pendingFile = new File([afterBlob], "photo-editee.jpg", { type: "image/jpeg" });

        if (this._afterObjectUrl) URL.revokeObjectURL(this._afterObjectUrl);
        if (this._beforeCompareUrl) URL.revokeObjectURL(this._beforeCompareUrl);
        this._afterObjectUrl = URL.createObjectURL(afterBlob);
        this._beforeCompareUrl = URL.createObjectURL(beforeBlob);

        const beforeImg = this.root.querySelector(".joy-pe-compare-before");
        const afterImg = this.root.querySelector(".joy-pe-compare-after");
        beforeImg.src = this._beforeCompareUrl;
        afterImg.src = this._afterObjectUrl;

        const slider = this.root.querySelector(".joy-pe-compare-slider");
        slider.value = "50";
        this._showCompare(true);

        const ready = () => {
          this._setCompareSplit(50);
        };
        if (afterImg.complete && beforeImg.complete) ready();
        else {
          afterImg.onload = ready;
          beforeImg.onload = ready;
        }
      } catch (err) {
        console.error(err);
        alert("Échec de la préparation.");
        btn.disabled = false;
        btn.textContent = "Comparer";
      }
    }

    _confirmSave() {
      if (!this._pendingFile) return;
      const confirmBtn = this.root.querySelector('[data-act="confirm"]');
      confirmBtn.disabled = true;
      confirmBtn.textContent = "…";
      try {
        this._offerSavePresetOnConfirm();
      } catch (e) {
        /* ignore */
      }
      saveRememberedGrade(this._preset, this.state);
      const file = this._pendingFile;
      const cb = this.onSave;
      this.close(true);
      if (cb) cb(file);
    }
  }

  function previewUrlForSource(src) {
    if (!src) return { url: "", revoke: false };
    if (typeof src === "string") return { url: src, revoke: false };
    if (typeof Blob !== "undefined" && src instanceof Blob) {
      return { url: URL.createObjectURL(src), revoke: true };
    }
    return { url: "", revoke: false };
  }

  function chooseSource({ original, edited, title, hint } = {}) {
    return new Promise((resolve) => {
      if (!original || !edited) {
        resolve(edited || original || null);
        return;
      }
      const existing = document.querySelector(".joy-pe-chooser");
      if (existing) existing.remove();

      const editedPreview = previewUrlForSource(edited);
      const originalPreview = previewUrlForSource(original);

      const root = document.createElement("div");
      root.className = "joy-pe-chooser";
      root.setAttribute("role", "dialog");
      root.setAttribute("aria-modal", "true");
      root.setAttribute("aria-label", title || "Choisir la source");
      root.innerHTML = `
        <div class="joy-pe-chooser-sheet">
          <h2 class="joy-pe-chooser-title"></h2>
          <p class="joy-pe-chooser-hint"></p>
          <div class="joy-pe-chooser-previews">
            <button type="button" class="joy-pe-chooser-option joy-pe-chooser-option--original" data-choice="original">
              <span class="joy-pe-chooser-preview">
                <img alt="Aperçu original" decoding="async">
              </span>
              <span class="joy-pe-chooser-option-label">Original</span>
            </button>
            <button type="button" class="joy-pe-chooser-option joy-pe-chooser-option--edited" data-choice="edited">
              <span class="joy-pe-chooser-preview">
                <img alt="Aperçu version éditée" decoding="async">
              </span>
              <span class="joy-pe-chooser-option-label">Version éditée</span>
            </button>
          </div>
          <button type="button" class="joy-pe-btn joy-pe-chooser-cancel" data-choice="cancel">Annuler</button>
        </div>
      `;
      root.querySelector(".joy-pe-chooser-title").textContent = title || "Quelle version ouvrir ?";
      root.querySelector(".joy-pe-chooser-hint").textContent =
        hint || "Une version éditée existe encore avec l’original.";
      root.querySelector('[data-choice="edited"] img').src = editedPreview.url;
      root.querySelector('[data-choice="original"] img').src = originalPreview.url;

      const finish = (value) => {
        if (editedPreview.revoke) URL.revokeObjectURL(editedPreview.url);
        if (originalPreview.revoke) URL.revokeObjectURL(originalPreview.url);
        root.remove();
        document.removeEventListener("keydown", onKey);
        resolve(value);
      };
      const onKey = (e) => {
        if (e.key === "Escape") finish(null);
      };
      root.addEventListener("click", (e) => {
        if (e.target === root) finish(null);
      });
      root.querySelector('[data-choice="edited"]').addEventListener("click", () => finish(edited));
      root.querySelector('[data-choice="original"]').addEventListener("click", () => finish(original));
      root.querySelector('[data-choice="cancel"]').addEventListener("click", () => finish(null));
      document.addEventListener("keydown", onKey);
      document.body.appendChild(root);
      root.querySelector('[data-choice="edited"]').focus();
    });
  }

  const editor = new PhotoEditor();

  global.JoyPhotoEditor = {
    open(opts) {
      editor.open(opts);
    },
    chooseSource,
    presets: BUILTIN_PRESETS,
    getCustomPresets: loadCustomPresets,
    MAX_EDGE,
    JPEG_QUALITY,
  };
})(window);
