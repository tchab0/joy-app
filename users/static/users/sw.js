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

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("focus" in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(target);
      }
    })
  );
});
