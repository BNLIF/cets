// #188: reading printed text with the camera — Tesseract.js over the strip
// inside a html5-qrcode box. Shared by the phone scan page and the fill
// page's Scan modal. Candidates are the tokens matching a pattern (or every
// line without one); `tally()` votes over the frames and names a winner
// once it is read twice and two reads ahead of the runner-up.
var TextRead = (function () {
  var worker = null, loading = null;

  // the Tesseract worker (PSM 6, English), loaded once per page from `base`
  // (the vendored tess/ directory); a failed load can be retried
  function load(base) {
    if (worker) return Promise.resolve(worker);
    if (loading) return loading;
    if (typeof Tesseract === "undefined") return Promise.reject(new Error("the text reader did not load"));
    var dir = base.replace(/\/$/, "");
    loading = Tesseract.createWorker("eng", 1, { workerPath: dir + "/worker.min.js", corePath: dir, langPath: dir })
      .then(function (w) { return w.setParameters({ tessedit_pageseg_mode: "6" }).then(function () { worker = w; return w; }); });
    loading.catch(function () { loading = null; });
    return loading;
  }

  // `re` = the field's pattern as a full-match RegExp (null = every line);
  // `pid` = a PID printed on a label counts too
  function candidates(text, re, pid) {
    var out = [], seen = {};
    function add(v) { if (v.length >= 2 && v.length <= 50 && !seen[v]) { seen[v] = 1; out.push(v); } }
    var toks = text.split(/\s+/).filter(Boolean);
    if (pid) toks.forEach(function (t) { if (/^[A-Z]\d{11}-\d{5}$/i.test(t)) add(t.toUpperCase()); });
    if (re) {
      toks.forEach(function (t) { if (re.test(t)) add(t); });
      if (!out.length) text.split(/\n/).forEach(function (l) { var v = l.replace(/\s+/g, ""); if (re.test(v)) add(v); });   // a space read inside the number
    } else {
      text.split(/\n/).forEach(function (l) { var v = l.trim(); if (/[A-Za-z0-9]/.test(v)) add(v); });
    }
    return out;
  }

  // the strip (`box` in CSS px, centred like html5-qrcode's) in video pixels,
  // with a margin so text at its edge is whole
  function grab(video, box) {
    if (!video || !video.videoWidth) return null;
    var k = video.videoWidth / (video.clientWidth || video.videoWidth);
    var w = Math.min(video.videoWidth, box.width * k * 1.1), h = Math.min(video.videoHeight, box.height * k * 1.3);
    var c = grab.c || (grab.c = document.createElement("canvas"));
    c.width = Math.round(w); c.height = Math.round(h);
    c.getContext("2d").drawImage(video, (video.videoWidth - w) / 2, (video.videoHeight - h) / 2, w, h, 0, 0, c.width, c.height);
    return c;
  }

  // the strip at twice the size (capped at 4096 px wide): small print from a
  // webcam or a phone held back reads "0111-" at 1× and "011-" at 2×, and
  // the other way round for big print — every frame is read at both
  function twice(c) {
    var k = Math.min(2, 4096 / c.width);
    var d = twice.c || (twice.c = document.createElement("canvas"));
    d.width = Math.round(c.width * k); d.height = Math.round(c.height * k);
    var g = d.getContext("2d"); g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
    g.drawImage(c, 0, 0, d.width, d.height);
    return d;
  }

  // reads about once a second until stopped: o = { video: () => <video>,
  // box: () => {width, height}, re, pid, onCands(list, text) } — `text` is
  // what was read, for the user to see why nothing matched; load() first
  function loop(o) {
    var on = true, t = null;
    function tick() {
      if (!on) return;
      var c = grab(o.video(), o.box());
      if (!c || !worker) { t = setTimeout(tick, 300); return; }
      Promise.all([worker.recognize(c), worker.recognize(twice(c))])
        .then(function (rs) {
          if (!on) return;
          var texts = rs.map(function (r) { return r.data.text || ""; }), seen = {}, cands = [];
          texts.forEach(function (tx) { candidates(tx, o.re, o.pid).forEach(function (v) { if (!seen[v]) { seen[v] = 1; cands.push(v); } }); });
          o.onCands(cands, texts[0].replace(/\s+/g, " ").trim());
        }, function () {})
        .then(function () { if (on) t = setTimeout(tick, 250); });
    }
    tick();
    return { stop: function () { on = false; clearTimeout(t); } };
  }

  var PID = /^[A-Z]\d{11}-\d{5}$/i;

  // votes over the frames: a string read once is noise (a digit misread
  // still passes a pattern), so `seen()` lists what was read at least
  // twice, most often first, and `winner()` names the leader once it is
  // read twice and is two reads ahead of the runner-up
  function tally() {
    var n = {}, order = [];
    return {
      add: function (cands) { cands.forEach(function (v) { if (!n[v]) { n[v] = 0; order.push(v); } n[v]++; }); },
      seen: function () {
        return order.filter(function (v) { return n[v] >= 2; })
          .sort(function (a, b) { return n[b] - n[a] || order.indexOf(a) - order.indexOf(b); })
          .map(function (v) { return { v: v, n: n[v] }; });
      },
      winner: function (vouch) {
        var top = order.filter(vouch).sort(function (a, b) { return n[b] - n[a]; });
        if (!top.length || n[top[0]] < 2) return "";
        return (top.length === 1 || n[top[0]] >= n[top[1]] + 2) ? top[0] : "";
      },
      reset: function () { n = {}; order = []; }
    };
  }

  function fullMatch(pattern) {   // the field's pattern as a full-match RegExp, null when absent or broken
    if (!pattern) return null;
    try { return new RegExp("^(?:" + pattern + ")$"); } catch (e) { return null; }
  }

  // html5-qrcode wants the resolution in config.videoConstraints; small print needs 1080p
  var HD = { width: { ideal: 1920 }, height: { ideal: 1080 } };

  // what may fill a box by itself (the winner): with a pattern every
  // candidate; without one only a PID-shaped read — the other lines stay
  // chips to tap
  function voucher(re) { return re ? function () { return true; } : function (v) { return PID.test(v); }; }

  return { load: load, candidates: candidates, grab: grab, loop: loop, tally: tally, voucher: voucher, fullMatch: fullMatch, PID: PID, HD: HD };
})();
