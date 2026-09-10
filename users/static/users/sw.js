/* Service worker JOY — Web Push */
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
  const options = {
    body: data.body || "",
    icon: "/static/users/icons/icon-192.png",
    badge: "/static/users/icons/icon-192.png",
    data: { url: data.url || "/" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
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
