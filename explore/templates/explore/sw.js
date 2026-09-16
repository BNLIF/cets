// HWDB Explorer — checklist offline cache (#152, #157). Keeps the pages a
// checklist needs when the network is gone: fill pages already visited, each
// checklist's PID chooser and its blank form (a fill page with no item, which
// reads the PID from the URL it is served at — so any item of a bookmarked
// checklist opens offline), and the profile with its bookmarks. Every other
// request passes straight through. Submitting stays online-only — the page
// itself disables Submit while offline.
var CACHE = "cl-offline-v3";
var FILL = /\/part\/([A-Za-z]\d{11})-(?:\d{5}|blank\d*)\/checklist\/([^\/]+)\/$/;   // <type>-blank, -blank2…: the blank form, no item yet
var PAGES = [FILL, /\/checklist\/[A-Za-z]\d{11}\/[^\/]+\/(?:blank\/)?$/, /\/profile\/$/];

self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf("cl-offline-") === 0 && k !== CACHE; })
                           .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  if (req.mode === "navigate") {
    if (!PAGES.some(function (re) { return re.test(url.pathname); })) return;   // any other page: untouched
    // the network first (fresh item card, draft banner), the last online
    // copy when the network is gone — never a half-render. The query
    // (?clear=1, ?page=2) is dropped from the cache key.
    var key = new Request(url.origin + url.pathname);
    e.respondWith(fetch(req).then(function (res) {
      if (res.ok) {
        var copy = res.clone();   // clone NOW — the body is handed to the page as soon as we return
        e.waitUntil(caches.open(CACHE).then(function (c) { return c.put(key, copy); }));
      }
      return res;
    }).catch(function (err) {
      return caches.match(key).then(function (hit) {
        if (hit) return hit;
        // #157: a fill page never opened on this device — the checklist's
        // blank form, cached when the chooser or the profile was visited
        var m = FILL.exec(url.pathname);
        if (!m) throw err;
        var blank = url.origin + url.pathname.slice(0, m.index) + "/checklist/" + m[1] + "/" + m[2] + "/blank/";
        return caches.match(blank).then(function (b) { if (b) return b; throw err; });
      });
    }));
    return;
  }
  var d = req.destination;
  if (d !== "script" && d !== "style" && d !== "font" && d !== "image") return;
  // assets (own static, htmx, fonts, reference drawings and thumbnails via
  // the image proxy): the cached copy at once, refreshed in the background
  e.respondWith(caches.open(CACHE).then(function (c) {
    return c.match(req).then(function (hit) {
      var net = fetch(req).then(function (res) {
        if (res.ok || res.type === "opaque") c.put(req, res.clone());
        return res;
      });
      if (hit) { net.catch(function () {}); return hit; }
      return net;
    });
  }));
});
