/**
 * Init Leaflet maps for .event-map[data-lat][data-lng].
 * "Y aller" → sheet de choix (app par défaut / Google Maps / Waze / Apple Plans).
 *
 * Android PWA : intent:// / geo: sont bloqués en standalone — on ouvre des
 * liens https cross-origin en target=_blank ; l’OS / App Links peut lancer
 * l’app native (sinon le navigateur).
 * Requires Leaflet CSS/JS already loaded.
 */
(function () {
  var PREF_KEY = "joy-maps-pref";

  function pinIcon() {
    return L.divIcon({
      className: "event-map-pin",
      html:
        '<svg width="28" height="38" viewBox="0 0 28 38" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
        '<path d="M14 0C6.27 0 0 6.27 0 14c0 9.75 14 24 14 24s14-14.25 14-24C28 6.27 21.73 0 14 0z" fill="#c94f3a"/>' +
        '<circle cx="14" cy="14" r="6" fill="white"/>' +
        "</svg>",
      iconSize: [28, 38],
      iconAnchor: [14, 38],
    });
  }

  function initOne(el) {
    if (!el || el.dataset.mapReady === "1" || typeof L === "undefined") return;
    var lat = parseFloat(el.getAttribute("data-lat"));
    var lng = parseFloat(el.getAttribute("data-lng"));
    if (!isFinite(lat) || !isFinite(lng)) return;
    var zoom = parseInt(el.getAttribute("data-zoom") || "15", 10) || 15;

    var map = L.map(el, {
      scrollWheelZoom: false,
      zoomControl: true,
      attributionControl: true,
    }).setView([lat, lng], zoom);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
      maxZoom: 19,
      minZoom: 3,
    }).addTo(map);

    L.marker([lat, lng], { icon: pinIcon(), keyboard: false }).addTo(map);
    el.dataset.mapReady = "1";

    requestAnimationFrame(function () {
      map.invalidateSize();
    });
    window.setTimeout(function () {
      map.invalidateSize();
    }, 200);
  }

  function initAll() {
    document.querySelectorAll(".event-map[data-lat][data-lng]").forEach(initOne);
  }

  function getPref() {
    try {
      return localStorage.getItem(PREF_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  function setPref(id) {
    try {
      localStorage.setItem(PREF_KEY, id);
    } catch (e) {
      /* ignore */
    }
  }

  function isIOS() {
    var ua = navigator.userAgent || "";
    return (
      /iPad|iPhone|iPod/.test(ua) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
    );
  }

  function isAndroid() {
    return /Android/i.test(navigator.userAgent || "");
  }

  function isStandalone() {
    return (
      (window.matchMedia &&
        window.matchMedia("(display-mode: standalone)").matches) ||
      !!navigator.standalone
    );
  }

  function httpsGmaps(lat, lng) {
    return (
      "https://maps.google.com/maps?daddr=" +
      encodeURIComponent(lat + "," + lng) +
      "&directionsmode=driving"
    );
  }

  function httpsWaze(lat, lng) {
    return "https://waze.com/ul?ll=" + lat + "," + lng + "&navigate=yes";
  }

  function optionsFor(btn) {
    var lat = btn.getAttribute("data-lat") || "";
    var lng = btn.getAttribute("data-lng") || "";
    var dest = lat + "," + lng;
    var android = isAndroid();
    var ios = isIOS();
    var pwaAndroid = android && isStandalone();
    var geo = btn.getAttribute("data-geo") || "";
    var webGmaps = btn.getAttribute("data-gmaps") || httpsGmaps(lat, lng);
    var webWaze = btn.getAttribute("data-waze") || httpsWaze(lat, lng);
    var webApple =
      btn.getAttribute("data-apple") ||
      "https://maps.apple.com/?daddr=" + dest;

    var gmapsHref;
    var gmapsBlank;
    if (pwaAndroid) {
      gmapsHref = httpsGmaps(lat, lng);
      gmapsBlank = true;
    } else if (android) {
      gmapsHref =
        "intent://maps.google.com/maps?daddr=" +
        dest +
        "&directionsmode=driving#Intent;scheme=https;package=com.google.android.apps.maps;" +
        "S.browser_fallback_url=" +
        encodeURIComponent(httpsGmaps(lat, lng)) +
        ";end";
      gmapsBlank = false;
    } else if (ios) {
      gmapsHref =
        "comgooglemaps://?daddr=" +
        encodeURIComponent(dest) +
        "&directionsmode=driving";
      gmapsBlank = false;
    } else {
      gmapsHref = webGmaps;
      gmapsBlank = true;
    }

    var defaultHref;
    var defaultBlank;
    if (pwaAndroid) {
      defaultHref = httpsGmaps(lat, lng);
      defaultBlank = true;
    } else {
      defaultHref = geo || gmapsHref;
      defaultBlank = false;
    }

    var wazeHref;
    var wazeBlank;
    if (pwaAndroid) {
      wazeHref = httpsWaze(lat, lng);
      wazeBlank = true;
    } else if (android || ios) {
      wazeHref = "waze://?ll=" + dest + "&navigate=yes";
      wazeBlank = false;
    } else {
      wazeHref = webWaze;
      wazeBlank = true;
    }

    return [
      {
        id: "default",
        label: "App par défaut",
        hint: pwaAndroid
          ? "Via le système (ou Maps web si l’app est bloquée)"
          : "Ouvre l’app cartes du téléphone",
        href: defaultHref,
        blank: defaultBlank,
      },
      {
        id: "gmaps",
        label: "Google Maps",
        hint: pwaAndroid ? "Quitte JOY vers Maps / navigateur" : "",
        href: gmapsHref,
        blank: gmapsBlank,
      },
      {
        id: "waze",
        label: "Waze",
        hint: pwaAndroid ? "Quitte JOY vers Waze / navigateur" : "",
        href: wazeHref,
        blank: wazeBlank,
      },
      {
        id: "apple",
        label: "Apple Plans",
        hint: "iPhone / iPad",
        href: ios ? "maps://?daddr=" + dest : webApple,
        blank: !ios,
      },
    ].filter(function (o) {
      return !!o.href;
    });
  }

  var sheet = null;
  var sheetList = null;
  var lastFocus = null;
  var activeBtn = null;

  function ensureSheet() {
    if (sheet) return sheet;
    sheet = document.createElement("div");
    sheet.className = "event-map-nav";
    sheet.hidden = true;
    sheet.innerHTML =
      '<div class="event-map-nav__backdrop" data-close></div>' +
      '<div class="event-map-nav__panel" role="dialog" aria-modal="true" aria-labelledby="event-map-nav-title">' +
      '<header class="event-map-nav__head">' +
      '<h2 id="event-map-nav-title">Itinéraire</h2>' +
      '<button type="button" class="event-map-nav__close" data-close aria-label="Fermer">×</button>' +
      "</header>" +
      '<p class="event-map-nav__lead">Choisissez votre application de navigation.</p>' +
      '<ul class="event-map-nav__list"></ul>' +
      "</div>";
    sheetList = sheet.querySelector(".event-map-nav__list");
    document.body.appendChild(sheet);

    sheet.addEventListener("click", function (e) {
      if (e.target.closest("[data-close]")) {
        closeSheet();
        return;
      }
      var opt = e.target.closest("a[data-pref]");
      if (!opt) return;
      var id = opt.getAttribute("data-pref");
      if (id) setPref(id);
      window.setTimeout(closeSheet, 400);
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && sheet && !sheet.hidden) {
        e.preventDefault();
        closeSheet();
      }
    });

    return sheet;
  }

  function openSheet(btn) {
    ensureSheet();
    activeBtn = btn;
    var pref = getPref();
    var opts = optionsFor(btn);
    opts.sort(function (a, b) {
      if (a.id === pref) return -1;
      if (b.id === pref) return 1;
      return 0;
    });

    sheetList.innerHTML = "";
    opts.forEach(function (o) {
      var isPref = o.id === pref;
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.className = "event-map-nav__opt" + (isPref ? " is-pref" : "");
      a.href = o.href;
      a.setAttribute("data-pref", o.id);
      if (o.blank) {
        a.target = "_blank";
        a.rel = "noopener";
      }
      var labelEl = document.createElement("span");
      labelEl.className = "event-map-nav__opt-label";
      labelEl.appendChild(document.createTextNode(o.label + " "));
      if (isPref) {
        var badge = document.createElement("span");
        badge.className = "event-map-nav__badge";
        badge.textContent = "préférée";
        labelEl.appendChild(badge);
      }
      a.appendChild(labelEl);
      if (o.hint) {
        var hint = document.createElement("span");
        hint.className = "event-map-nav__opt-hint";
        hint.textContent = o.hint;
        a.appendChild(hint);
      }
      li.appendChild(a);
      sheetList.appendChild(li);
    });

    lastFocus = document.activeElement;
    sheet.hidden = false;
    document.body.classList.add("event-map-nav-open");
    var first = sheetList.querySelector("[data-pref]");
    if (first) first.focus();
  }

  function closeSheet() {
    if (!sheet || sheet.hidden) return;
    sheet.hidden = true;
    document.body.classList.remove("event-map-nav-open");
    activeBtn = null;
    if (lastFocus && typeof lastFocus.focus === "function") {
      lastFocus.focus();
    }
    lastFocus = null;
  }

  function onGoClick(e) {
    var btn = e.target.closest(".event-map__go");
    if (!btn) return;
    e.preventDefault();
    openSheet(btn);
  }

  function initGo() {
    document.addEventListener("click", onGoClick);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initAll();
      initGo();
    });
  } else {
    initAll();
    initGo();
  }
})();
