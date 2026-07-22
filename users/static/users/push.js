/**
 * JOY Web Push — abonnement navigateur + détection iOS PWA.
 * Expose window.JoyPush
 */
(function () {
  "use strict";

  function csrfToken() {
    const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function isIos() {
    const ua = navigator.userAgent || "";
    if (/iPad|iPhone|iPod/.test(ua)) return true;
    return navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
  }

  function isStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true
    );
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function fetchPublicKey() {
    const r = await fetch("/compte/push/vapid-key/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!r.ok) throw new Error("vapid_unavailable");
    const data = await r.json();
    if (!data.publicKey) throw new Error("vapid_unavailable");
    return data.publicKey;
  }

  async function ensureServiceWorker() {
    if (!("serviceWorker" in navigator)) {
      throw new Error("sw_unsupported");
    }
    const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    await navigator.serviceWorker.ready;
    return reg;
  }

  async function postSubscription(sub) {
    const raw = sub.toJSON();
    const r = await fetch("/compte/push/subscribe/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify({
        endpoint: raw.endpoint,
        keys: raw.keys,
      }),
    });
    if (!r.ok) throw new Error("subscribe_failed");
    return r.json();
  }

  async function deleteSubscription(endpoint) {
    await fetch("/compte/push/subscribe/", {
      method: "DELETE",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify({ endpoint }),
    });
  }

  async function enable() {
    if (isIos() && !isStandalone()) {
      return { ok: false, reason: "ios_install_required" };
    }
    if (!("Notification" in window) || !("PushManager" in window)) {
      return { ok: false, reason: "unsupported" };
    }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      return { ok: false, reason: "denied" };
    }
    const reg = await ensureServiceWorker();
    const key = await fetchPublicKey();
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
    }
    await postSubscription(sub);
    return { ok: true };
  }

  async function disable() {
    if (!("serviceWorker" in navigator)) return { ok: true };
    const reg = await navigator.serviceWorker.getRegistration("/");
    if (!reg) return { ok: true };
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await deleteSubscription(sub.endpoint);
      await sub.unsubscribe();
    }
    return { ok: true };
  }

  async function localSubscription() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      return null;
    }
    const reg = await navigator.serviceWorker.getRegistration("/");
    if (!reg) return null;
    return reg.pushManager.getSubscription();
  }

  async function status() {
    const r = await fetch("/compte/push/status/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const data = r.ok
      ? await r.json()
      : { ok: false, configured: false, subscriptions: 0 };
    let thisDevice = false;
    try {
      thisDevice = !!(await localSubscription());
    } catch (_e) {
      thisDevice = false;
    }
    return {
      ok: !!data.ok,
      configured: !!data.configured,
      subscriptions: data.subscriptions || 0,
      thisDevice,
    };
  }

  window.JoyPush = {
    isIos,
    isStandalone,
    enable,
    disable,
    status,
    ensureServiceWorker,
  };
})();
