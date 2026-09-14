// HWDB Explorer — checklist offline cache (#152). Serves already-visited
// checklist fill pages, and the assets they load, when the network is gone;
// every other request passes straight through. Submitting stays online-only
// — the page itself disables Submit while offline.
var CACHE = "cl-offline-v2";
var PAGE = /\/part\/[A-Za-z]\d{11}-\d{5}\/checklist\/[^\/]+\/$/;

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
    if (!PAGE.test(url.pathname)) return;   // any other page: untouched
    // a fill page: the network first (fresh item card, draft banner), the
    // last online copy when the network is gone — never a half-render. The
    // query (?clear=1) is dropped from the cache key.
    var key = new Request(url.origin + url.pathname);
    e.respondWith(fetch(req).then(function (res) {
      if (res.ok) {
        var copy = res.clone();   // clone NOW — the body is handed to the page as soon as we return
        e.waitUntil(caches.open(CACHE).then(function (c) { return c.put(key, copy); }));
      }
      return res;
    }).catch(function (err) {
      return caches.match(key).then(function (hit) { if (hit) return hit; throw err; });
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
