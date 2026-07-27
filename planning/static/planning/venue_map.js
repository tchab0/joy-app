/**
 * Carte OpenStreetMap (Leaflet) — précise l’adresse (optionnel).
 * La ville sert à centrer ; le marqueur n’est pas obligatoire.
 */
window.PlVenueMap = (function () {
  const DEFAULT_CENTER = [46.67, -1.43];
  const DEFAULT_ZOOM = 9;
  const CITY_ZOOM = 13;
  const MARKER_ZOOM = 16;
  const instances = new Map();
  let leafletPromise = null;

  function loadLeaflet() {
    if (typeof window.L !== 'undefined') return Promise.resolve(window.L);
    if (leafletPromise) return leafletPromise;
    leafletPromise = new Promise((resolve, reject) => {
      const cssHref = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      if (!document.querySelector('link[href="' + cssHref + '"]')) {
        const css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = cssHref;
        document.head.appendChild(css);
      }
      const script = document.createElement('script');
      script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
      script.onload = () => resolve(window.L);
      script.onerror = () => {
        leafletPromise = null;
        reject(new Error('Leaflet unavailable'));
      };
      document.head.appendChild(script);
    });
    return leafletPromise;
  }

  function els(root) {
    const prefix = root.getAttribute('data-pl-venue-map');
    return {
      prefix,
      root,
      mapEl: root.querySelector('.pl-venue-map'),
      lat: root.querySelector('input[name="venue_latitude"]'),
      lng: root.querySelector('input[name="venue_longitude"]'),
      coords: root.querySelector('[data-pl-venue-map-coords]'),
      hint: root.querySelector('[data-pl-venue-map-hint]'),
      clearBtn: root.querySelector('[data-pl-venue-map-clear]'),
      nom: document.getElementById(prefix + '_venue_nom'),
      ville: document.getElementById(prefix + '_venue_ville'),
      adresse: document.getElementById(prefix + '_venue_adresse'),
      select: document.getElementById(prefix + '_venue'),
    };
  }

  function modeOf(root) {
    const form = root.closest('form');
    const modeInput = form && form.querySelector('input[name="venue_mode"]');
    return modeInput ? modeInput.value : 'new';
  }

  function setCoords(ui, lat, lng) {
    if (!ui.lat || !ui.lng) return;
    ui.lat.value = Number(lat).toFixed(6);
    ui.lng.value = Number(lng).toFixed(6);
    if (ui.coords) {
      ui.coords.textContent = '📍 Précision : ' + ui.lat.value + ', ' + ui.lng.value;
    }
    if (ui.clearBtn) ui.clearBtn.style.display = '';
  }

  function clearCoords(ui) {
    if (ui.lat) ui.lat.value = '';
    if (ui.lng) ui.lng.value = '';
    if (ui.coords) ui.coords.textContent = 'Précision non renseignée (optionnel)';
    if (ui.clearBtn) ui.clearBtn.style.display = 'none';
  }

  function cityQuery(ui, mode) {
    if (mode === 'existing' && ui.select && ui.select.selectedOptions[0]) {
      const opt = ui.select.selectedOptions[0];
      const ville = (opt.getAttribute('data-ville') || '').trim();
      if (ville) return ville;
      const label = opt.textContent || '';
      const parts = label.split('—').map((s) => s.trim()).filter(Boolean);
      return parts.length > 1 ? parts[parts.length - 1] : parts[0] || '';
    }
    return ((ui.ville && ui.ville.value) || '').trim();
  }

  function precisionQuery(ui, mode) {
    const ville = cityQuery(ui, mode);
    if (!ville) return '';
    if (mode === 'existing' && ui.select && ui.select.selectedOptions[0]) {
      const label = (ui.select.selectedOptions[0].textContent || '').trim();
      return label ? label + ', France' : ville + ', France';
    }
    const parts = [
      ui.adresse && ui.adresse.value,
      ui.nom && ui.nom.value,
      ville,
    ]
      .map((s) => (s || '').trim())
      .filter(Boolean);
    return parts.join(', ') + ', France';
  }

  function nominatim(q) {
    return fetch(
      'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' +
        encodeURIComponent(q),
      { headers: { Accept: 'application/json' } }
    ).then((r) => r.json());
  }

  function ensure(root) {
    if (typeof L === 'undefined' || !root) return null;
    const key = root.getAttribute('data-pl-venue-map');
    let inst = instances.get(key);
    if (inst) {
      setTimeout(() => inst.map.invalidateSize(), 50);
      return inst;
    }
    const ui = els(root);
    if (!ui.mapEl) return null;

    const map = L.map(ui.mapEl).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(map);

    let marker = null;

    function place(lat, lng, zoom) {
      const ll = [lat, lng];
      if (marker) {
        marker.setLatLng(ll);
      } else {
        marker = L.marker(ll, { draggable: true }).addTo(map);
        marker.on('dragend', (e) => {
          const p = e.target.getLatLng();
          setCoords(ui, p.lat, p.lng);
        });
      }
      map.setView(ll, zoom == null ? MARKER_ZOOM : zoom);
      setCoords(ui, lat, lng);
    }

    function centerView(lat, lng, zoom) {
      map.setView([lat, lng], zoom == null ? CITY_ZOOM : zoom);
    }

    function clearMarkerOnly() {
      if (marker) {
        map.removeLayer(marker);
        marker = null;
      }
      clearCoords(ui);
    }

    function clear() {
      clearMarkerOnly();
      map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    }

    map.on('click', (e) => place(e.latlng.lat, e.latlng.lng));

    inst = { map, ui, place, centerView, clear, clearMarkerOnly };
    instances.set(key, inst);
    if (ui.clearBtn) ui.clearBtn.style.display = 'none';
    setTimeout(() => map.invalidateSize(), 80);
    return inst;
  }

  function sync(root, mode) {
    if (typeof L === 'undefined') {
      loadLeaflet()
        .then(() => sync(root, mode))
        .catch(() => {
          const ui = els(root);
          if (ui.hint) ui.hint.textContent = 'Carte indisponible pour le moment.';
        });
      return;
    }
    const inst = ensure(root);
    if (!inst) return;
    setTimeout(() => inst.map.invalidateSize(), 60);

    if (inst.ui.hint) {
      inst.ui.hint.textContent =
        'La ville est obligatoire. Cliquez la carte pour préciser l’adresse (optionnel).';
    }
    if (mode === 'existing' && inst.ui.select) {
      onSelect(root, inst.ui.select);
    }
  }

  function onSelect(root, selectEl) {
    if (typeof L === 'undefined') {
      loadLeaflet().then(() => onSelect(root, selectEl)).catch(() => {});
      return;
    }
    const inst = ensure(root);
    if (!inst || !selectEl) return;
    const opt = selectEl.selectedOptions && selectEl.selectedOptions[0];
    if (!opt || !opt.value) {
      inst.clear();
      return;
    }
    const lat = parseFloat(opt.getAttribute('data-lat') || '');
    const lng = parseFloat(opt.getAttribute('data-lng') || '');
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      inst.place(lat, lng);
      return;
    }
    // Pas de précision enregistrée : centrer sur la ville sans imposer de coords.
    inst.clearMarkerOnly();
    const ville = (opt.getAttribute('data-ville') || '').trim();
    if (ville) {
      if (inst.ui.coords) {
        inst.ui.coords.textContent = 'Centrage sur « ' + ville + ' »…';
      }
      nominatim(ville + ', France')
        .then((data) => {
          if (!data || !data.length) {
            if (inst.ui.coords) {
              inst.ui.coords.textContent = 'Précision non renseignée (optionnel)';
            }
            return;
          }
          inst.centerView(parseFloat(data[0].lat), parseFloat(data[0].lon), CITY_ZOOM);
          if (inst.ui.coords) {
            inst.ui.coords.textContent = 'Précision non renseignée (optionnel)';
          }
        })
        .catch(() => {
          if (inst.ui.coords) {
            inst.ui.coords.textContent = 'Précision non renseignée (optionnel)';
          }
        });
    }
  }

  /** Centre la carte sur la ville — n’enregistre pas de précision. */
  function centerOnCity(root) {
    if (typeof L === 'undefined') {
      loadLeaflet().then(() => centerOnCity(root)).catch(() => {});
      return;
    }
    const inst = ensure(root);
    if (!inst) return;
    const ui = inst.ui;
    const mode = modeOf(root);
    const ville = cityQuery(ui, mode);
    if (!ville) {
      if (ui.coords) {
        ui.coords.textContent = 'Indiquez une ville pour centrer la carte.';
      }
      if (ui.ville && mode === 'new') ui.ville.focus();
      return;
    }
    if (ui.coords) ui.coords.textContent = 'Centrage sur « ' + ville + ' »…';
    nominatim(ville + ', France')
      .then((data) => {
        if (!data || !data.length) {
          if (ui.coords) {
            ui.coords.textContent = 'Ville introuvable — vérifiez l’orthographe.';
          }
          return;
        }
        // Centrer sans poser de marqueur ni écrire lat/lng
        // (sauf si une précision était déjà saisie : on la garde).
        const hadPrecision = !!(ui.lat && ui.lat.value && ui.lng && ui.lng.value);
        inst.centerView(parseFloat(data[0].lat), parseFloat(data[0].lon), CITY_ZOOM);
        if (!hadPrecision) {
          if (ui.coords) {
            ui.coords.textContent =
              'Carte centrée sur « ' + ville + ' » — cliquez pour préciser (optionnel).';
          }
        } else if (ui.coords) {
          ui.coords.textContent =
            '📍 Précision : ' + ui.lat.value + ', ' + ui.lng.value;
        }
      })
      .catch(() => {
        if (ui.coords) ui.coords.textContent = 'Erreur de géocodage.';
      });
  }

  /** Place un marqueur via adresse/nom+ville (précision optionnelle). */
  function geocode(root) {
    if (typeof L === 'undefined') {
      loadLeaflet().then(() => geocode(root)).catch(() => {});
      return;
    }
    const inst = ensure(root);
    if (!inst) return;
    const ui = inst.ui;
    const mode = modeOf(root);
    const ville = cityQuery(ui, mode);
    if (!ville) {
      if (ui.coords) {
        ui.coords.textContent = 'Indiquez une ville avant de localiser.';
      }
      return;
    }
    const q = precisionQuery(ui, mode);
    if (ui.coords) ui.coords.textContent = 'Recherche…';
    nominatim(q)
      .then((data) => {
        if (!data || !data.length) {
          if (ui.coords) {
            ui.coords.textContent = 'Adresse introuvable — cliquez sur la carte.';
          }
          return;
        }
        inst.place(parseFloat(data[0].lat), parseFloat(data[0].lon), 15);
      })
      .catch(() => {
        if (ui.coords) ui.coords.textContent = 'Erreur de géocodage — cliquez sur la carte.';
      });
  }

  function clearPrecision(root) {
    if (typeof L === 'undefined') {
      loadLeaflet().then(() => clearPrecision(root)).catch(() => {});
      return;
    }
    const inst = ensure(root);
    if (!inst) return;
    inst.clearMarkerOnly();
  }

  return { sync, onSelect, centerOnCity, geocode, clearPrecision, ensure, loadLeaflet };
})();
