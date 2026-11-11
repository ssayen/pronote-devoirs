// Service worker : réseau d'abord, dernier état connu hors ligne (page + fichiers statiques).
const CACHE = "devoirs-v3";
const SHELL = ["/", "/static/views.js", "/static/results.js", "/static/timetable.js", "/static/objectifs.js", "/static/packfx.js", "/static/packfx.css", "/static/perso.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== "GET" || u.origin !== location.origin) return;
  const page = r.mode === "navigate" && u.pathname === "/";
  if (!page && !u.pathname.startsWith("/static/") && u.pathname !== "/manifest.webmanifest") return;
  e.respondWith(
    fetch(r).then((res) => {
      if (res.ok && !res.redirected) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(page ? "/" : r, copy)); }
      return res;
    }).catch(() => caches.match(page ? "/" : r).then((m) => m || Response.error()))
  );
});
