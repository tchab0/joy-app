/* Service worker JOY — Web Push + badge icône (iOS/Android PWA) */

async function setHomeBadge(count) {
  if (!("setAppBadge" in self.navigator)) return;
  try {
    const n = Math.max(0, Number(count) || 0);
    if (n > 0) {
      await self.navigator.setAppBadge(n);
    } else {
      await self.navigator.clearAppBadge();
    }
  } catch (_) {
    /* ignore — API absente / permission / contexte non installé */
  }
}

async function clearHomeBadge() {
  if (!("clearAppBadge" in self.navigator)) return;
  try {
    await self.navigator.clearAppBadge();
  } catch (_) {
    /* ignore */
  }
}

self.addEventListener("push", (event) => {
  let data = { title: "JOY", body: "", url: "/" };
  try {
    if (event.data) {
      data = { ...data, ...event.data.json() };
    }
  } catch (e) {
    try {
      data.body = event.data ? event.data.text() : "";
    } catch (_) {
      /* ignore */
    }
  }
  const title = data.title || "JOY";
  const defaultIcon =
    "/static/users/icons/icon-192.png?v=__JOY_ICON_VERSION__";
  const options = {
    body: data.body || "",
    icon: data.icon || defaultIcon,
    badge: data.badge || data.icon || defaultIcon,
    data: { url: data.url || "/" },
  };
  event.waitUntil(
    (async () => {
      await self.registration.showNotification(title, options);
      let count = Number(data.badgeCount);
      if (!Number.isFinite(count) || count < 1) {
        try {
          const notes = await self.registration.getNotifications();
          count = Math.max(1, notes.length);
        } catch (_) {
          count = 1;
        }
      }
      await setHomeBadge(count);
    })()
  );
});

function normalizeNotifUrl(raw) {
  let target = (raw || "/").trim() || "/";
  try {
    if (target.startsWith("http://") || target.startsWith("https://")) {
      const u = new URL(target);
      if (u.origin === self.location.origin) {
        target = u.pathname + u.search + u.hash;
      }
    }
  } catch (_) {
    target = "/";
  }
  if (!target.startsWith("/")) {
    target = "/" + target;
  }
  return target;
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = normalizeNotifUrl(
    event.notification.data && event.notification.data.url
  );
  event.waitUntil(
    (async () => {
      await clearHomeBadge();
      const list = await clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      for (const client of list) {
        if (!client.url || !client.url.startsWith(self.location.origin)) {
          continue;
        }
        if ("navigate" in client && "focus" in client) {
          try {
            const page = await client.navigate(target);
            if (page) {
              await page.focus();
              return;
            }
          } catch (_) {
            /* openWindow ci-dessous */
          }
        }
      }
      if (clients.openWindow) {
        await clients.openWindow(target);
      }
    })()
  );
});
