// HWDB Explorer — Plots page (explore/templates/explore/plot.html): data, series, chart, panels.
(function () {
    var root = document.getElementById("pl"), TYPE_KEY = root.dataset.key, DATA_URL = root.dataset.url, N_ITEMS = +root.dataset.n;
    var SOURCES_URL = root.dataset.sourcesUrl, TESTS_BASE = root.dataset.testsBaseUrl, TESTS_SYNC_URL = root.dataset.testsSyncUrl;
    var csrf = document.querySelector("input[name=csrfmiddlewaretoken]").value;
    var $ = function (id) { return document.getElementById(id); };
    var FACETS = ["status", "creator", "manufacturer", "institution"];
    var OPS = ["=", "≠", "<", "≤", ">", "≥", "contains"];
    // pure helpers from plot-core.js (expressions, nested arrays, ranges, binning)
    var PC = window.PlotCore, exprSelect = PC.exprSelect, nestedAt = PC.nestedAt, dimsOf = PC.dimsOf, dimLabels = PC.dimLabels, selectAt = PC.selectAt, isExpr = PC.isExpr, exprText = PC.exprText, exprSplit = PC.exprSplit, exprTokens = PC.exprTokens, exprCompile = PC.exprCompile, exprNorm = PC.exprNorm, exprResolve = PC.exprResolve, exprEval = PC.exprEval, normSn = PC.normSn, pidAlternation = PC.pidAlternation, pidRange = PC.pidRange, toNum = PC.toNum, fmt = PC.fmt, histCounts = PC.histCounts, isNumeric = PC.isNumeric, catKey = PC.catKey, topCats = PC.topCats, meanSd = PC.meanSd;

    // ---- State -------------------------------------------------------------
    // source: "specs" (whole dataset, values walked from item.data) or a test
    // type id (values fetched per key from the mirror into item.vals[path]).
    // series (#156): each carries its own keys, index pins, selection and
    // cuts; source, mode, bins, log y, Y scale and the reference are shared.
    // The Axes / Select / Cuts panes edit series[cur].
    var source = "specs", items = [], paths = [], pathCounts = {}, chart = null;
    var series = [], cur = 0;
    // #160: entries (PIDs or serial numbers) handed over by a checklist's plot
    // field in the hash — they select the items of every series while set
    var EMBED = !!document.getElementById("pl").getAttribute("data-embed"), IDS = null;
    var testCache = null;          // the IndexedDB record for the current test source
    var busy = false;              // a key fetch is in flight
    function isTest() { return source !== "specs"; }
    function S() { return series[cur]; }
    function blankSeries() { return { name: "", color: "", x: "", y: "", xi: [], yi: [], item: "", pid: "", sn: "", sel: "", f: {}, cuts: [], logic: "and" }; }
    function copySeries(s) { return JSON.parse(JSON.stringify(s)); }
    function nextName() { var n = series.length + 1; while (series.some(function (s) { return s.name === "Series " + n; })) n++; return "Series " + n; }
    // The effective PID filter of a series: its Item box (exactly one PID) wins over the regex box.
    function pidFilter(s) { if (IDS) return idsFilter(); var it = (s.item || "").trim(); return it ? "^" + it.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "$" : (s.pid || "").trim(); }
    // #160: an entry matches an item by PID, or by serial number — case-insensitive, leading zeros in a digit run ignored (HPK19843 = HPK019843)
    function resolveIds(list) {
        var byPid = {}, bySn = {}, pids = [], missing = [];
        items.forEach(function (it) { byPid[it.pid.toLowerCase()] = it.pid; if (it.serial) bySn[normSn(it.serial)] = it.pid; });
        (list || []).forEach(function (id) {
            var p = byPid[String(id).toLowerCase()] || bySn[normSn(id)];
            if (!p) missing.push(id); else if (pids.indexOf(p) < 0) pids.push(p);
        });
        return { pids: pids, missing: missing };
    }
    // Tooltips name a value's item as "PID · serial" and its place in the
    // item's array as [i, j] — the series' pins filled in, the free level
    // counted (one free level), or the flat index when several are free.
    function who(pid) { var it = itemByPid[pid]; return pid + (it && it.serial ? " · " + it.serial : ""); }
    function idxLabel(p, s, j) {
        var d, ix;
        if (isExpr(p)) { var m = exprMeta(p), id0 = m.err ? null : m.ids.filter(function (id) { return !id.attr; })[0]; if (!id0) return ""; d = keyDims(id0.p) || []; ix = id0.ix || []; }
        else { d = keyDims(p) || []; ix = idxOf(p, s) || []; }
        if (!d.length) return "";
        // values arrive flattened row-major over the free levels (selectAt /
        // plotting.leaves) — undo that with the key's dims; an unknown size
        // leaves the flat position
        var levels = d.map(function (dim, l) { return { pin: l < ix.length && ix[l] !== null && ix[l] !== undefined ? ix[l] : null, n: dim && dim.n }; });
        var free = levels.filter(function (x) { return x.pin === null; });
        function show(f) { return levels.map(function (x, l) { return (d[l].seg || "level " + (l + 1)) + "[" + f(x) + "]"; }).join(" › "); }
        if (free.some(function (x) { return !(x.n > 0); })) return show(function (x) { return x.pin === null ? "·" : x.pin; }) + " #" + j;
        var rest = j;
        for (var k = free.length - 1; k >= 0; k--) { free[k].at = rest % free[k].n; rest = Math.floor(rest / free[k].n); }
        return show(function (x) { return x.pin === null ? x.at : x.pin; });
    }
    function tipLines(q) { return q.ix ? [q.t, q.ix] : [q.t]; }   // tooltip title: the item, then its array position
    function srcIdx(arr, j) { return arr.src ? arr.src[j] : j; }   // an expression's result → the entry it came from
    var itemByPid = {};
    function idsFilter() { return pidAlternation(resolveIds(IDS).pids); }
    function cacheKey() { return TYPE_KEY + "/" + (isTest() ? "test:" + source : "specs"); }

    // ---- IndexedDB cache: one record per instance/type/source -----------
    function idb() {
        return new Promise(function (res, rej) {
            var r = indexedDB.open("cets-plot", 1);
            r.onupgradeneeded = function () { r.result.createObjectStore("datasets"); };
            r.onsuccess = function () { res(r.result); }; r.onerror = function () { rej(r.error); };
        });
    }
    function idbGet(key) {
        return idb().then(function (db) { return new Promise(function (res, rej) {
            var q = db.transaction("datasets").objectStore("datasets").get(key);
            q.onsuccess = function () { res(q.result); }; q.onerror = function () { rej(q.error); }; }); });
    }
    function idbPut(key, val) {
        return idb().then(function (db) { return new Promise(function (res, rej) {
            var tx = db.transaction("datasets", "readwrite"); tx.objectStore("datasets").put(val, key);
            tx.oncomplete = res; tx.onerror = function () { rej(tx.error); }; }); }).catch(function () {});
    }
    function idbDel(key) {
        return idb().then(function (db) { return new Promise(function (res) {
            var tx = db.transaction("datasets", "readwrite"); tx.objectStore("datasets").delete(key); tx.oncomplete = res; tx.onerror = res; }); }).catch(function () {});
    }

    // ---- Streams ---------------------------------------------------------
    async function postStream(url, extra, onLine) {
        var fd = new FormData(); fd.append("csrfmiddlewaretoken", csrf);
        Object.keys(extra || {}).forEach(function (k) { fd.append(k, extra[k]); });
        var resp = await fetch(url, { method: "POST", body: fd });
        if (resp.redirected) { window.location = resp.url; return false; }
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        var reader = resp.body.getReader(), dec = new TextDecoder(), buf = "";
        while (true) {
            var r = await reader.read(); if (r.done) break;
            buf += dec.decode(r.value, { stream: true });
            var nl; while ((nl = buf.indexOf("\n")) >= 0) { onLine(buf.slice(0, nl)); buf = buf.slice(nl + 1); }
        }
        if (buf) onLine(buf);
        return true;
    }

    // Specifications: the NDJSON sweep, whole type in one go.
    async function fetchSpecs() {
        var btn = $("fetch-btn"), prog = $("fetch-progress"), err = $("fetch-error");
        btn.disabled = true; err.textContent = ""; prog.textContent = "starting…";
        var rows = [], pages = "?", failed = null;
        try {
            var ok = await postStream(DATA_URL, {}, function (line) {
                if (!line.trim()) return;
                var o = JSON.parse(line);
                if (o.pages) pages = o.pages;
                else if (o.page) prog.textContent = "page " + o.page + " / " + pages + " · " + rows.length + " items";
                else if (o.error) failed = o.error;
                else if (o.done === undefined) rows.push(o);
            });
            if (!ok) return;
        } catch (e) { err.textContent = String(e); btn.disabled = false; prog.textContent = ""; return; }
        btn.disabled = false; prog.textContent = "";
        if (failed) { err.textContent = failed; return; }
        var rec = { fetched_at: new Date().toISOString(), items: rows };
        await idbPut(TYPE_KEY + "/specs", rec);
        loadSpecs(rec);
    }

    // Test data: the HWDB sweep into the server mirror (progress log), then reload.
    async function fetchTestData(mode) {
        var log = $("td-log"), err = $("fetch-error");
        $("fetch-btn").disabled = $("fetch-full-btn").disabled = true; err.textContent = "";
        log.hidden = false; log.textContent = "Fetching test data (" + mode + ")…\n";
        try {
            var ok = await postStream(TESTS_SYNC_URL, { mode: mode }, function (line) { log.textContent += line + "\n"; log.scrollTop = log.scrollHeight; });
            if (!ok) return;
        } catch (e) { err.textContent = String(e); }
        $("fetch-btn").disabled = $("fetch-full-btn").disabled = false;
        // The mirror changed: drop every cached test source of this type, then reload.
        var srcs = await loadSources();
        await Promise.all(srcs.map(function (t) { return idbDel(TYPE_KEY + "/test:" + t.id); }));
        if (isTest() && !srcs.some(function (t) { return String(t.id) === String(source); })) source = srcs.length ? String(srcs[0].id) : "specs";
        if (!isTest() && srcs.length) source = String(srcs[0].id);
        $("src").value = source;
        await switchSource();
    }

    async function loadSources() {
        var srcs = [];
        try { srcs = (await (await fetch(SOURCES_URL)).json()).tests || []; } catch (e) { srcs = []; }
        var sel = $("src"), curv = sel.value; sel.textContent = "";
        var o = document.createElement("option"); o.value = "specs"; o.textContent = "Item Specifications"; sel.appendChild(o);
        srcs.forEach(function (t) { var x = document.createElement("option"); x.value = String(t.id); x.textContent = t.name + " (" + t.n + " items)"; sel.appendChild(x); });
        var g = document.createElement("option"); g.value = "__fetch__"; g.textContent = srcs.length ? "fetch test data for new items…" : "fetch test data from HWDB…"; sel.appendChild(g);
        sel.value = Array.prototype.some.call(sel.options, function (op) { return op.value === curv; }) ? curv : "specs";
        return srcs;
    }

    // ---- Keys and values ---------------------------------------------------
    function walk(node, prefix, acc) {
        if (Array.isArray(node)) {
            if (node.some(function (e) { return e && typeof e === "object" && !Array.isArray(e); })) {
                node.forEach(function (e) { if (e && typeof e === "object") walk(e, prefix, acc); });
            } else if (prefix.length) acc.add(JSON.stringify(prefix));
            return;
        }
        if (node && typeof node === "object") {
            Object.keys(node).forEach(function (k) { walk(node[k], prefix.concat([k]), acc); });
            return;
        }
        if (prefix.length) acc.add(JSON.stringify(prefix));
    }
    // #154: an array key's shape ([{seg, n}] per list level, test source only)
    // and a series' per-axis index pins — one entry per level, null = every
    // element. Pinned values live in their own cache slot (key@[…]).
    function keyDims(p) {
        if (!p || isExpr(p)) return [];
        if (!isTest()) return specKeyDims(p);
        var k = testCache ? testCache.keys.find(function (x) { return JSON.stringify(x.path) === p; }) : null;
        return k && k.dims ? k.dims : [];
    }
    function idxOf(p, s) {
        var a = p && p === s.x ? s.xi : p && p === s.y ? s.yi : null;
        return a && a.some(function (i) { return i !== null && i !== undefined; }) ? a.map(function (i) { return i === undefined ? null : i; }) : null;
    }
    function slotOf(p, ix) { return ix ? p + "@" + JSON.stringify(ix) : p; }
    function slotBase(p, s) { return slotOf(p, idxOf(p, s)); }
    function idxScaleOf(p, ix) { var d = keyDims(p), sc = 1; if (ix) ix.forEach(function (i, j) { if (i !== null && d[j] && d[j].n > 1) sc *= d[j].n; }); return sc; }
    function idxNote(s) {
        return ["x", "y"].map(function (ax) { var p = s[ax], ix = idxOf(p, s); return ix ? " · " + showPath(p) + " [" + ix.map(function (i) { return i === null ? "·" : i; }).join(", ") + "]" : ""; }).join("")
               + (s.sel ? " · select: " + s.sel : "");
    }
    // The index-pin inputs, for series[cur].
    function drawIdx() {
        var s = S();
        ["x", "y"].forEach(function (ax) {
            var p = s[ax], dims = keyDims(p), box = $(ax + "idx"), arr = s[ax + "i"];
            if (s[ax + "k"] !== p) {
                s[ax + "k"] = p; arr.length = 0;
                if (ax === "y") s.xi.forEach(function (v, j) { if (v !== null && dims[j] && dims[j].n > 1) arr[j] = v; });   // Y follows X
            }
            for (var q = 0; q < dims.length; q++) if (arr[q] === undefined) arr[q] = null;      // no holes: a sparse array maps badly
            if (box.getAttribute("data-key") !== p + "#" + cur) {       // rebuild only on a key / series change — typing keeps focus
                box.setAttribute("data-key", p + "#" + cur); box.textContent = "";
                dims.forEach(function (d, j) {
                    if (d.n <= 1) return;
                    var lab = document.createElement("label"); lab.className = "l";
                    var cap = document.createElement("span"); cap.textContent = d.seg || (j === dims.length - 1 ? "point" : "level " + (j + 1)); cap.title = cap.textContent + " · " + d.n + " entries"; lab.appendChild(cap);
                    var inp, cur0 = arr[j] === null || arr[j] === undefined ? "" : String(arr[j]);
                    if (d.n <= 24) {          // small level: a menu of every index
                        inp = document.createElement("select");
                        var all = document.createElement("option"); all.value = ""; all.textContent = "all " + d.n; inp.appendChild(all);
                        for (var k = 0; k < d.n; k++) { var o = document.createElement("option"); o.value = String(k); o.textContent = String(k); inp.appendChild(o); }
                    } else {                  // long level (curve points): a number box, blank = all
                        inp = document.createElement("input"); inp.type = "number"; inp.min = 0; inp.max = d.n - 1; inp.placeholder = "all " + d.n; inp.title = "0 – " + (d.n - 1) + ", blank = all";
                    }
                    inp.value = cur0; inp.setAttribute("data-level", j);
                    inp.addEventListener(inp.tagName === "SELECT" ? "change" : "input", function () {
                        var v = inp.value.trim(); arr[j] = v === "" ? null : Math.max(0, Math.floor(+v));
                        if (ax === "x") {                       // Y follows X at the same level; Y stays editable
                            var yd = keyDims(s.y), yin = $("yidx").querySelector('[data-level="' + j + '"]');
                            if (yd[j] && yd[j].n > 1 && yin) { while (s.yi.length <= j) s.yi.push(null); s.yi[j] = arr[j]; yin.value = inp.value; }
                        }
                        changed();
                    });
                    lab.appendChild(inp); box.appendChild(lab);
                });
            }
            $(ax + "idx-l").hidden = !box.children.length;
        });
        $("idx-row").hidden = $("xidx-l").hidden && $("yidx-l").hidden;
        $("idx-follow").hidden = $("xidx-l").hidden || $("yidx-l").hidden;
    }
    // Specs: a key's shape from up to 200 items holding it (reset with the dataset).
    var specDims = {};
    function specKeyDims(p) {
        if (p in specDims) return specDims[p];
        var segs = JSON.parse(p), d = [], labels = null, seen = 0;
        for (var k = 0; k < items.length && seen < 200; k++) {
            var v = nestedAt(items[k].data, segs, 0);
            if (v === null || (Array.isArray(v) && !v.length)) continue;
            seen++;
            if (!labels) labels = dimLabels(items[k].data, segs);
            dimsOf(v).forEach(function (n, j) { d[j] = Math.max(d[j] || 0, n); });
        }
        specDims[p] = Math.max.apply(null, d.concat([0])) > 1 ? d.map(function (n, j) { return { seg: (labels && labels[j]) || "", n: n }; }) : [];
        return specDims[p];
    }
    // The one accessor both sources share: a key (with the series' pins), or
    // a Draw expression over keys (#162).
    function slotValues(item, p, ix, s) {
        if (isTest()) { var b = slotOf(p, ix); return item.vals[b] || item.vals[b + "|" + pidFilter(s)] || []; }
        var v = nestedAt(item.data, JSON.parse(p), 0);
        return v === null ? [] : selectAt(v, ix || []);
    }
    // an identifier's values on one item: a key slot, or an item field ($serial …) as one value
    function idValues(item, id, s) { return id.attr ? [item[id.attr] === null || item[id.attr] === undefined ? "" : item[id.attr]] : slotValues(item, id.p, id.ix, s); }
    function exprValues(item, text, s) { var m = exprMeta(text); return m.err ? [] : exprEval(m.fn, m.ids.map(function (id) { return idValues(item, id, s); })); }
    function valuesFor(item, p, s) {
        if (!p) return [];
        var arr = isExpr(p) ? exprValues(item, p, s) : slotValues(item, p, idxOf(p, s), s);
        // #163: the series' selection keeps entries one by one (ROOT's second argument)
        if (s.sel && !exprMeta(s.sel).err) arr = exprSelect(arr, exprValues(item, s.sel, s));
        return arr;
    }
    // Compiled expressions for this dataset: text → { fn, ids: [{ p, ix, text } | { attr, text }] } or { err }
    var exprCache = {};
    function exprMeta(p) {
        var text = exprText(p);
        if (exprCache[text]) return exprCache[text];
        var keys = paths.map(function (k) { return { p: k, segs: JSON.parse(k), dims: function () { return keyDims(k); } }; }), meta;
        try {
            var res = [], c = exprCompile(text, function (tok) {
                var r = tok.t === "attr" ? { attr: tok.v } : exprResolve(tok, keys), slot = r.attr ? "$" + r.attr : slotOf(r.p, r.ix);
                for (var i = 0; i < res.length; i++) if ((res[i].attr ? "$" + res[i].attr : slotOf(res[i].p, res[i].ix)) === slot) return i;     // the same name twice: one slot
                r.text = tok.text; res.push(r); return res.length - 1;
            });
            meta = { fn: c.fn, ids: res };
        } catch (e) { meta = { err: e.message }; }
        return (exprCache[text] = meta);
    }
    function drawErr(s) { return ["x", "y"].map(function (ax) { return isExpr(s[ax]) ? exprMeta(s[ax]).err : null; }).filter(Boolean)[0] || null; }
    function selErr(s) { return s.sel && exprMeta(s.sel).err ? "selection: " + exprMeta(s.sel).err : null; }
    function exprErr(s) { return drawErr(s) || selErr(s); }
    // X and Y of one item paired by entry: by position for keys, by source
    // position when an expression dropped entries (an entry fails as a whole)
    function pairValues(it, s) {
        var xa = valuesFor(it, s.x, s), yb = valuesFor(it, s.y, s), out = [];
        if (!xa.src && !yb.src) { var n = Math.min(xa.length, yb.length); for (var i = 0; i < n; i++) out.push({ x: xa[i], y: yb[i], i: i }); return out; }
        var ym = {}; yb.forEach(function (v, j) { ym[srcIdx(yb, j)] = v; });
        xa.forEach(function (v, j) { var k = srcIdx(xa, j); if (k in ym) out.push({ x: v, y: ym[k], i: k }); });
        return out;
    }
    // Test source: is this slot loaded for the series' PID filter? (a whole-type
    // fetch, stored under the bare key, serves any filter)
    function haveSlot(p, ix, s) { var b = slotOf(p, ix); return (b in testCache.values) || ((b + "|" + pidFilter(s)) in testCache.values); }
    function keyNV(p) { var k = testCache.keys.find(function (x) { return JSON.stringify(x.path) === p; }); return k ? (k.nv || k.n) : 0; }
    function showPath(p) { return isExpr(p) ? exprText(p) : JSON.parse(p).join(" › "); }
    function lastSeg(p) { if (isExpr(p)) return exprText(p); try { var a = JSON.parse(p); return a[a.length - 1]; } catch (e) { return ""; } }

    // Test source: make sure every key a series' plot needs is in item.vals.
    // With a PID filter set, only the matching items' values are fetched —
    // that is how a 2000-point-per-item array key stays plottable for one item.
    async function ensureKeys(specs, s) {         // specs: [{ p, ix }] — a key and the pins to fetch it with
        var pidf = pidFilter(s), need = specs.filter(function (sp) { return sp.p && !haveSlot(sp.p, sp.ix, s); });
        if (!need.length) return true;
        var max = testCache.max_values || 2000000;
        var big = need.filter(function (sp) { return !pidf && keyNV(sp.p) / idxScaleOf(sp.p, sp.ix) > max; });
        if (big.length) {
            var levels = keyDims(big[0].p).filter(function (d) { return d.n > 1; }).map(function (d) { return d.seg || "array"; });
            clear((series.length > 1 ? s.name + ": " : "") + showPath(big[0].p) + " holds " + keyNV(big[0].p).toLocaleString() + " values across the type, over the "
                  + max.toLocaleString() + " limit. Pick one item in the grid below or set a PID filter"
                  + (levels.length ? ", or pin the " + levels.join(" and ") + " index to plot every item" : "") + ".");
            return false;
        }
        busy = true; $("stats").textContent = "loading " + need.map(function (sp) { return showPath(sp.p); }).join(", ") + (series.length > 1 ? " for " + s.name : "") + "…";
        try {
            for (var i = 0; i < need.length; i++) {
                var ix = need[i].ix;
                var url = TESTS_BASE + "/" + source + "/values/?key=" + encodeURIComponent(need[i].p) + (pidf ? "&pid=" + encodeURIComponent(pidf) : "")
                        + (ix ? "&idx=" + encodeURIComponent(JSON.stringify(ix)) : "");
                var resp = await fetch(url), j = await resp.json();
                if (!resp.ok) { clear(j.error || ("HTTP " + resp.status)); return false; }
                var slot = pidf ? slotOf(need[i].p, ix) + "|" + pidf : slotOf(need[i].p, ix);
                testCache.values[slot] = j.values || {};
                items.forEach(function (it) { if (j.values && j.values[it.pid]) it.vals[slot] = j.values[it.pid]; });
            }
        } finally { busy = false; }
        await idbPut(cacheKey(), testCache);
        return true;
    }
    // Every slot a series reads: its X / Y keys with their pins, an expression's
    // identifiers with theirs, the cut keys (a cut on the X key shares X's pins)
    function seriesSpecs(s) {
        var out = [];
        ["x", "y"].forEach(function (ax) {
            var p = s[ax]; if (!p) return;
            if (isExpr(p)) { var m = exprMeta(p); if (!m.err) m.ids.forEach(function (id) { if (!id.attr) out.push({ p: id.p, ix: id.ix }); }); }
            else out.push({ p: p, ix: idxOf(p, s) });
        });
        if (s.sel) { var ms = exprMeta(s.sel); if (!ms.err) ms.ids.forEach(function (id) { if (!id.attr) out.push({ p: id.p, ix: id.ix }); }); }
        s.cuts.forEach(function (c) { if (c.p) out.push({ p: c.p, ix: idxOf(c.p, s) }); });
        return out;
    }
    async function ensureAll(list) {           // [series, …] → every series' slots, one series at a time
        for (var i = 0; i < list.length; i++) { if (!(await ensureKeys(seriesSpecs(list[i]), list[i]))) return false; }
        return true;
    }

    // ---- Filters -----------------------------------------------------------
    function passCut(item, c, s) {
        if (!c.p) return true;
        var vals = valuesFor(item, c.p, s), want = toNum(c.v);
        return vals.some(function (v) {
            var n = toNum(v);
            if (c.o === "contains") return String(v).toLowerCase().indexOf(String(c.v).toLowerCase()) >= 0;
            if (n !== null && want !== null) {
                return c.o === "=" ? n === want : c.o === "≠" ? n !== want : c.o === "<" ? n < want :
                       c.o === "≤" ? n <= want : c.o === ">" ? n > want : n >= want;
            }
            var str = String(v), t = String(c.v);
            return c.o === "=" ? str === t : c.o === "≠" ? str !== t : c.o === "<" ? str < t : c.o === "≤" ? str <= t : c.o === ">" ? str > t : str >= t;
        });
    }
    function filtered(s) {
        var pidf = pidFilter(s), re = null, rng = pidRange(pidf);
        if (pidf && !rng) { try { re = new RegExp(pidf, "i"); } catch (e) { re = null; } }
        var snf = (s.sn || "").trim(), snre = null;     // serial number: regex, else substring
        if (snf) { try { snre = new RegExp(snf, "i"); } catch (e) { snre = null; } }
        var any = s.logic === "or", live = s.cuts.filter(function (c) { return c.p && c.v !== ""; });
        return items.filter(function (it) {
            if (pidf && !(rng ? (function (n) { return n >= rng[0] && n <= rng[1]; })(+it.pid.split("-")[1])
                          : re ? re.test(it.pid) : it.pid.toLowerCase().indexOf(pidf.toLowerCase()) >= 0)) return false;
            if (snf && !(snre ? snre.test(it.serial || "") : (it.serial || "").toLowerCase().indexOf(snf.toLowerCase()) >= 0)) return false;
            for (var i = 0; i < FACETS.length; i++) { var f = s.f[FACETS[i]]; if (f && it[FACETS[i]] !== f) return false; }
            if (!live.length) return true;
            return any ? live.some(function (c) { return passCut(it, c, s); }) : live.every(function (c) { return passCut(it, c, s); });
        });
    }

    // ---- Chart -------------------------------------------------------------
    // Series colours: Tableau 10 without its pale members, blue first — hues far apart and dark
    // enough on the cream page. Categories (stacked / grouped bars) keep their own palette.
    var SERIES_COLORS = ["#4e79a7", "#e15759", "#59a14f", "#f28e2b", "#b07aa1", "#76b7b2", "#9c755f", "#d37295"];
    var OVER = "#c2410c";
    var PALETTE = ["#1d4ed8", "#c2410c", "#15803d", "#9333ea", "#dc2626", "#0891b2", "#ca8a04", "#4f46e5", "#db2777", "#65a30d", "#0d9488", "#7c3aed"];
    function color(i) { return (series[i] && series[i].color) || SERIES_COLORS[i % SERIES_COLORS.length]; }
    // The first palette colour no series shows right now (custom picks included); cycles when all are taken.
    function freeColor() {
        var used = series.map(function (s, i) { return color(i).toLowerCase(); });
        return SERIES_COLORS.find(function (c) { return used.indexOf(c) < 0; }) || SERIES_COLORS[series.length % SERIES_COLORS.length];
    }
    // Axis titles come from the plot; the Labels inputs in the Series pane override them.
    function opts(xTitle, yTitle) {
        var t = $("ptitle").value.trim(); xTitle = $("xlab").value.trim() || xTitle; yTitle = $("ylab").value.trim() || yTitle;
        return { responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { title: { display: !!t, text: t, font: { size: 14, weight: "600" }, color: "#1c1812", padding: { top: 4, bottom: 10 } },
                       legend: { labels: { boxWidth: 12, font: { size: 12 } } }, tooltip: { intersect: false },
                       zoom: { zoom: { wheel: { enabled: false }, drag: { enabled: true, backgroundColor: "rgba(78,121,167,.12)" }, mode: "xy" },
                               pan: { enabled: true, modifierKey: "shift", mode: "xy" } } },
            scales: { x: { title: { display: true, text: xTitle }, ticks: { maxRotation: 45, autoSkipPadding: 12, font: { size: 11 } } },
                      y: { title: { display: true, text: yTitle }, beginAtZero: true, ticks: { precision: 0 } } } };
    }
    // ROOT-style stats box, one per drawn numeric series: Entries / Mean / Std Dev.
    var statsBox = { id: "statsBox", afterDatasetsDraw: function (ch) {
        var rows = (ch.options.plugins.statsBox || {}).rows; if (!rows || !rows.length) return;
        var ctx = ch.ctx, a = ch.chartArea, w = 168, h = 58, x = a.right - w - 6, y = a.top + 6 + (EMBED ? 26 : 0);   // embed: below the floating buttons
        if (a.right - a.left < (EMBED ? 240 : 480)) return;   // a narrow plot keeps its area; the status strip has the numbers (an embed is narrow by nature)
        ctx.save();
        rows.forEach(function (r) {
            ctx.fillStyle = "rgba(254,252,247,.92)"; ctx.strokeStyle = r.color; ctx.lineWidth = 1;
            ctx.fillRect(x, y, w, h); ctx.strokeRect(x, y, w, h);
            ctx.textBaseline = "middle"; ctx.textAlign = "left";
            ctx.font = "600 11px 'IBM Plex Mono', ui-monospace, monospace"; ctx.fillStyle = r.color; ctx.fillText(r.name, x + 8, y + 12);
            ctx.font = "11px 'IBM Plex Mono', ui-monospace, monospace"; ctx.fillStyle = "#2a241b";
            [["Entries", r.n.toLocaleString()], ["Mean", fmt(r.mean)], ["Std Dev", fmt(r.sd)]].forEach(function (row, k) {
                ctx.textAlign = "left"; ctx.fillText(row[0], x + 8, y + 26 + k * 13);
                ctx.textAlign = "right"; ctx.fillText(row[1], x + w - 8, y + 26 + k * 13);
            });
            y += h + 6;
        });
        ctx.restore();
    } };
    // Axis range boxes (Series pane): [min, max] with null for auto; applied to numeric scales only.
    function rangeOf(ax) {
        var lo = $(ax + "min").value.trim(), hi = $(ax + "max").value.trim();
        if (lo === "" && hi === "") return null;
        return [lo === "" ? null : +lo, hi === "" ? null : +hi];
    }
    function applyRanges(scales) {
        ["x", "y"].forEach(function (ax) {
            var sc = scales && scales[ax], r = rangeOf(ax); if (!sc || !r) return;
            if (ax === "x" && !(sc.type === "linear" || sc.type === "logarithmic")) return;     // category axes have no numeric range
            if (r[0] !== null) sc.min = r[0]; if (r[1] !== null) sc.max = r[1];
            if (ax === "y" && (r[0] !== null)) delete sc.beginAtZero;
        });
    }
    function draw(cfg) { if (chart) chart.destroy(); cfg.plugins = [statsBox]; applyRanges(cfg.options.scales); chart = new Chart($("plot"), cfg); $("plot-msg").hidden = true; }
    function binSetup(nums) {
        var lo = Math.min.apply(null, nums), hi = Math.max.apply(null, nums), nb = Math.max(2, Math.min(500, +$("bins").value || 40));
        if (lo === hi) { lo -= 0.5; hi += 0.5; }
        var w = (hi - lo) / nb, labels = [];
        for (var i = 0; i < nb; i++) labels.push(fmt(lo + i * w));
        return { lo: lo, hi: hi, nb: nb, w: w, labels: labels };
    }
    // No plot: the message goes to the status strip and, large, into the empty plot area.
    function clear(msg) { $("stats").textContent = msg; $("plot-msg").textContent = msg; $("plot-msg").hidden = false; if (chart) { chart.destroy(); chart = null; } }
    // Which side controls apply to the plot being drawn: bins only to
    // histograms; the reference overlay to single-key plots (x, y points over
    // a histogram, "label, count" lines over category bars).
    function controls(bins, overlay) {
        $("bins").disabled = !bins; $("bins-l").classList.toggle("pl-off", !bins);
        $("bins-l").title = bins ? "" : "Bins apply to histograms only";
        $("ov").disabled = !overlay; $("ovn").disabled = !overlay;
        $("ov-l").classList.toggle("pl-off", !overlay); $("ovn").classList.toggle("pl-off", !overlay);
        $("ov").placeholder = overlay === "cat" ? "label, count — one per line" : "x, y — one per line";
        $("ov-l").title = overlay ? "" : "Reference applies to single-key plots only";
    }
    function overlayCats() {
        var out = {};
        $("ov").value.split(/\n/).forEach(function (line) {
            var m = line.match(/^\s*(.+?)\s*[,;:\t]\s*(-?[\d.]+)\s*$/);
            if (m && isFinite(+m[2])) out[m[1]] = +m[2];
        });
        return out;
    }
    function overlayXY() {
        var out = [];
        $("ov").value.split(/\n/).forEach(function (line) {
            var m = line.match(/^\s*(-?[\d.eE+-]+)\s*[,;:\t ]\s*(-?[\d.eE+-]+)\s*$/);
            if (m && isFinite(+m[1]) && isFinite(+m[2])) out.push({ x: +m[1], y: +m[2] });
        });
        return out.sort(function (a, b) { return a.x - b.x; });
    }
    // Which series the plot draws: every series with an X key when the active
    // series' plot family overlays (one key, or a numeric scatter); otherwise
    // the active series alone — heat maps and category breakdowns stay single.
    function drawnSeries() {
        var a = S();
        if (a.y && $("mode2d").value === "heat") return [a];
        return series.filter(function (s) { return s.x && !exprErr(s); });
    }
    function seriesLabel(s) { return series.length > 1 ? s.name : "Items"; }

    function render() {
        var a = S(), xp = a.x, yp = a.y;
        if (!xp) { clear("Pick an X key, or type a Draw expression."); return; }
        if (exprErr(a)) { clear("Draw: " + exprErr(a)); return; }
        var drawn = drawnSeries();
        if (isTest()) {
            var need = drawn.filter(function (s) { return seriesSpecs(s).some(function (sp) { return !haveSlot(sp.p, sp.ix, s); }); });
            if (need.length) { if (!busy) ensureAll(need).then(function (ok) { if (ok) { render(); drawItems(); } }); return; }
        }
        var stats = $("stats");
        var sels = drawn.map(function (s) { return filtered(s); });
        var head = drawn.map(function (s, i) { return (series.length > 1 ? s.name + " " : "") + sels[i].length + " / " + items.length + " items" + idxNote(s); }).join(" · ");
        stats.title = "";
        if (IDS) {   // #160: what the checklist handed over, and what found no item
            var rid = resolveIds(IDS), hit = IDS.length - rid.missing.length;
            head = hit + " of " + IDS.length + " entr" + (IDS.length === 1 ? "y" : "ies") + " matched an item" + (rid.pids.length < hit ? " (" + rid.pids.length + " distinct)" : "")
                 + (rid.missing.length ? " · no item: " + rid.missing.slice(0, 6).join(", ") + (rid.missing.length > 6 ? ", …" : "") : "") + " · " + head;
            stats.title = rid.missing.length ? "No item of this type has PID or serial: " + rid.missing.join(", ") : "";
        }
        var skipped = [];       // series not drawn in this family
        function noteSkipped() { return skipped.length ? " · not drawn: " + skipped.join(", ") : ""; }
        $("mode2d-l").hidden = true; $("mode1d-l").hidden = true; $("logy-l").hidden = true; $("stats-l").hidden = true;
        if (yp) {
            // Two keys: values paired by position within each item (the
            // Dashboard's explode-two-lists rule); pairs missing either side drop.
            var pairsOf = function (s, sel) {
                var pairs = [];
                sel.forEach(function (it) {
                    pairValues(it, s).forEach(function (q) { pairs.push({ x: q.x, y: q.y, pid: it.pid, t: who(it.pid), ix: idxLabel(s.x, s, q.i) }); });
                });
                return pairs;
            };
            var pairs = pairsOf(a, sels[drawn.indexOf(a)]);
            if (!pairs.length) { clear(head + " · 0 (x, y) pairs — no item has values for both keys"); controls(false, null); return; }
            var xNum = isNumeric(pairs.map(function (q) { return q.x; })), yNum = isNumeric(pairs.map(function (q) { return q.y; }));
            if (xNum && yNum) {
                var numPts = function (ps) {
                    return ps.map(function (q) { return { x: toNum(q.x), y: toNum(q.y), pid: q.pid, t: q.t, ix: q.ix }; }).filter(function (q) { return q.x !== null && q.y !== null; });
                };
                var pts = numPts(pairs);
                $("mode2d-l").hidden = false;
                var o = opts(showPath(xp), showPath(yp)); o.scales.x.type = "linear"; o.scales.y.beginAtZero = false; o.scales.y.ticks = {};
                if ($("mode2d").value === "heat") {
                    // 2D histogram: Bins × Bins cells, colour depth = count. Active series only.
                    var ACCENT = color(cur);
                    var bx = binSetup(pts.map(function (q) { return q.x; })), by = binSetup(pts.map(function (q) { return q.y; })), cells = {}, vmax = 0;
                    pts.forEach(function (q) {
                        var i = Math.min(bx.nb - 1, Math.floor((q.x - bx.lo) / bx.w)), j = Math.min(by.nb - 1, Math.floor((q.y - by.lo) / by.w)), k = i + "," + j;
                        cells[k] = (cells[k] || 0) + 1; if (cells[k] > vmax) vmax = cells[k];
                    });
                    var data = Object.keys(cells).map(function (k) {
                        var ij = k.split(","), i = +ij[0], j = +ij[1];
                        return { x: bx.lo + (i + 0.5) * bx.w, y: by.lo + (j + 0.5) * by.w, v: cells[k], x0: bx.lo + i * bx.w, y0: by.lo + j * by.w };
                    });
                    stats.textContent = head + " · " + pts.length + " (x, y) pairs · " + data.length + " occupied cells · max " + vmax + (series.length > 1 ? " · 2D histogram draws one series" : "");
                    o.scales.x.min = bx.lo; o.scales.x.max = bx.hi; o.scales.x.offset = false; o.scales.x.grid = { offset: false };
                    // The matrix controller reverses y by default (table layout); a histogram's y goes up.
                    o.scales.y.min = by.lo; o.scales.y.max = by.hi; o.scales.y.offset = false; o.scales.y.grid = { offset: false }; o.scales.y.reverse = false;
                    o.plugins.legend.display = false;
                    o.plugins.tooltip = { callbacks: {
                        title: function (cs) { var q = cs[0].raw; return fmt(q.x0) + " – " + fmt(q.x0 + bx.w) + " , " + fmt(q.y0) + " – " + fmt(q.y0 + by.w); },
                        label: function (c) { return c.raw.v + " pair" + (c.raw.v > 1 ? "s" : ""); } } };
                    draw({ type: "matrix", data: { datasets: [{ label: "Pairs", data: data,
                        backgroundColor: function (c) { var v = c.raw ? c.raw.v : 0; return ACCENT + Math.round(40 + 215 * v / vmax).toString(16).padStart(2, "0"); },
                        width: function (c) { var ar = c.chart.chartArea; return ar ? Math.max(1, ar.width / bx.nb - 1) : 1; },
                        height: function (c) { var ar = c.chart.chartArea; return ar ? Math.max(1, ar.height / by.nb - 1) : 1; } }] }, options: o });
                    controls(true, null);
                } else if ($("mode2d").value === "line") {
                    // Line: (x, y) pairs joined in order — items by PID, then array order within an
                    // item — with a break between items, so one item's I–V curve is one trace.
                    var dsLn = [], infoL = [];
                    drawn.forEach(function (s, si) {
                        var seq = [], nItems = 0, c = color(series.indexOf(s));
                        sels[si].slice().sort(function (p1, q1) { return p1.pid < q1.pid ? -1 : 1; }).forEach(function (it) {
                            var got = 0;
                            pairValues(it, s).forEach(function (q) { var xv = toNum(q.x), yv = toNum(q.y); if (xv !== null && yv !== null) { seq.push({ x: xv, y: yv, pid: it.pid, i: q.i, t: who(it.pid), ix: idxLabel(s.x, s, q.i) }); got++; } });
                            if (got) { nItems++; seq.push({ x: null, y: null }); }     // gap before the next item
                        });
                        if (seq.length) seq.pop();
                        if (!seq.length) { if (s !== a) skipped.push(s.name); return; }
                        infoL.push((series.length > 1 ? s.name + ": " : "") + (seq.length - nItems + 1) + " points · " + nItems + " item" + (nItems > 1 ? "s" : ""));
                        dsLn.push({ label: seriesLabel(s), data: seq, borderColor: c, backgroundColor: c, borderWidth: 1.5, pointRadius: seq.length > 400 ? 0 : 2.5, tension: 0, spanGaps: false });
                    });
                    stats.textContent = head + " · " + infoL.join(" · ") + noteSkipped();
                    o.plugins.legend.display = series.length > 1;
                    o.plugins.tooltip = { callbacks: { title: function (cs) { return tipLines(cs[0].raw); }, label: function (c1) { return fmt(c1.raw.x) + ", " + fmt(c1.raw.y); } } };
                    draw({ type: "line", data: { datasets: dsLn }, options: o });
                    controls(false, null);
                } else {
                    // Scatter, one dataset per series: identical (x, y) pairs merge into one marker sized by multiplicity.
                    var dsS = [], info = [];
                    drawn.forEach(function (s, si) {
                        var sp = s === a ? pts : numPts(pairsOf(s, sels[si]));
                        if (s !== a && !sp.length) { skipped.push(s.name); return; }
                        var groups = {};
                        sp.forEach(function (q) { var k = q.x + "," + q.y; (groups[k] = groups[k] || { x: q.x, y: q.y, n: 0, pids: [] }).n++; if (groups[k].pids.length < 8) groups[k].pids.push(q.t ? q.t + (q.ix ? "  " + q.ix : "") : q.pid); });
                        var marks = Object.keys(groups).map(function (k) { var g = groups[k]; g.r = Math.min(20, 3 + 3 * Math.sqrt(g.n - 1)); return g; });
                        var nmax = marks.reduce(function (m, g) { return Math.max(m, g.n); }, 0), c = color(series.indexOf(s));
                        info.push((series.length > 1 ? s.name + ": " : "") + sp.length + " pairs · " + marks.length + " distinct" + (nmax > 1 ? " · max multiplicity " + nmax : ""));
                        dsS.push({ label: seriesLabel(s), data: marks, backgroundColor: c + "88", borderColor: c, borderWidth: 1 });
                    });
                    stats.textContent = head + " · " + info.join(" · ") + noteSkipped();
                    o.plugins.legend.display = series.length > 1;
                    o.plugins.tooltip = { callbacks: {
                        title: function (cs) { var g = cs[0].raw; return fmt(g.x) + ", " + fmt(g.y) + (g.n > 1 ? "  × " + g.n : ""); },
                        label: function (c) { var g = c.raw; return g.pids.concat(g.n > g.pids.length ? ["…"] : []); } } };
                    draw({ type: "bubble", data: { datasets: dsS }, options: o });
                    controls(false, null);
                }
            } else if (xNum || yNum) {
                // One numeric side: its histogram, one stacked series per category of the other.
                var numKey = xNum ? "x" : "y", catK = xNum ? "y" : "x", numPath = xNum ? xp : yp, catPath = xNum ? yp : xp;
                var good = pairs.filter(function (q) { return toNum(q[numKey]) !== null; });
                var cats = topCats(good.map(function (q) { return q[catK]; }), 12);
                var b = binSetup(good.map(function (q) { return toNum(q[numKey]); }));
                var ds = cats.keys.map(function (k, i) {
                    return { label: k, data: histCounts(good.filter(function (q) { return catKey(q[catK]) === k; }).map(function (q) { return toNum(q[numKey]); }), b.lo, b.hi, b.nb),
                             backgroundColor: PALETTE[i % PALETTE.length] + "aa", barPercentage: 1, categoryPercentage: 1 };
                });
                stats.textContent = head + " · N=" + good.length + " · " + cats.unique + " " + showPath(catPath) + " categories" + (cats.unique > 12 ? " (top 12 shown)" : "");
                var o2 = opts(showPath(numPath) + "  (bin width " + fmt(b.w) + ")", "count"); o2.scales.x.stacked = true; o2.scales.y.stacked = true;
                o2.plugins.legend.title = { display: true, text: showPath(catPath) };
                draw({ type: "bar", data: { labels: b.labels, datasets: ds }, options: o2 });
                controls(true, null);
            } else {
                // Both categorical: counts of Y category per X category, grouped bars.
                var cx = topCats(pairs.map(function (q) { return q.x; }), 40), cy = topCats(pairs.map(function (q) { return q.y; }), 12);
                var grid = {}; pairs.forEach(function (q) { var k = JSON.stringify([catKey(q.x), catKey(q.y)]); grid[k] = (grid[k] || 0) + 1; });
                var ds2 = cy.keys.map(function (yk, i) {
                    return { label: yk, data: cx.keys.map(function (xk) { return grid[JSON.stringify([xk, yk])] || 0; }), backgroundColor: PALETTE[i % PALETTE.length] + "cc" };
                });
                stats.textContent = head + " · N=" + pairs.length + " · " + cx.unique + " × " + cy.unique + " categories" + (cx.unique > 40 || cy.unique > 12 ? " (top 40 × 12 shown)" : "");
                var o3 = opts(showPath(xp), "count"); o3.plugins.legend.title = { display: true, text: showPath(yp) };
                draw({ type: "bar", data: { labels: cx.keys, datasets: ds2 }, options: o3 });
                controls(false, null);
            }
            return;
        }
        // One key per series. The active series decides the family (numeric
        // or categorical); other series join when their values fit it.
        var tagsOf = [];      // per series, one "PID · serial [index]" per value, in valsOf order
        var valsOf = drawn.map(function (s, i) { var v = [], t = []; sels[i].forEach(function (it) { var arr = valuesFor(it, s.x, s); arr.forEach(function (x, j) { v.push(x); t.push({ t: who(it.pid), ix: idxLabel(s.x, s, srcIdx(arr, j)) }); }); }); tagsOf.push(t); return v; });
        var ai = drawn.indexOf(a), vals = valsOf[ai];
        if (!vals.length) { clear(head + " · no values for this key on the selected items"); controls(false, null); return; }
        if (isNumeric(vals)) {
            $("mode1d-l").hidden = false; $("logy-l").hidden = false;
            var m1 = $("mode1d").value, logy = $("logy").checked, ov = overlayXY();
            var numsOf = [], used = [], numTags = [];
            drawn.forEach(function (s, i) {
                if (i !== ai && !isNumeric(valsOf[i])) { if (valsOf[i].length) skipped.push(s.name); return; }
                var nums = [], tags = [];
                valsOf[i].forEach(function (v, j) { var n = toNum(v); if (n !== null) { nums.push(n); tags.push(tagsOf[i][j]); } });
                if (!nums.length) { if (i !== ai) skipped.push(s.name); return; }
                used.push(s); numsOf.push(nums); numTags.push(tags);
            });
            var rows = used.map(function (s, i) { var ms = meanSd(numsOf[i]); ms.name = s.name; ms.color = color(series.indexOf(s)); return ms; });
            stats.textContent = head + " · " + used.map(function (s, i) {
                var nums = numsOf[i]; return (used.length > 1 ? s.name + " " : "") + "N=" + nums.length + " mean=" + fmt(rows[i].mean) + " min=" + fmt(Math.min.apply(null, nums)) + " max=" + fmt(Math.max.apply(null, nums));
            }).join(" · ") + noteSkipped();
            var ovDs = ov.length ? [{ label: $("ovn").value || "Reference", data: ov, type: "line", borderColor: OVER, borderDash: [6, 4], borderWidth: 2, pointRadius: 3, pointBackgroundColor: OVER, tension: 0 }] : [];
            if (m1 === "line") {
                // Values in item order (PID ascending), then array order within an
                // item — the Dashboard's "Line": a waveform / curve for one item.
                var dsL = used.map(function (s, i) {
                    var seq = [], c = color(series.indexOf(s));
                    sels[drawn.indexOf(s)].slice().sort(function (p, q) { return p.pid < q.pid ? -1 : 1; }).forEach(function (it) {
                        var arr = valuesFor(it, s.x, s); arr.forEach(function (v, j) { var n = toNum(v); if (n !== null) seq.push({ x: seq.length, y: n, pid: it.pid, t: who(it.pid), ix: idxLabel(s.x, s, srcIdx(arr, j)) }); });
                    });
                    return { label: seriesLabel(s), data: seq, borderColor: c, backgroundColor: c, borderWidth: 1.5, pointRadius: seq.length > 400 ? 0 : 2, tension: 0 };
                });
                var oL = opts("index", used.length > 1 ? "value" : showPath(xp)); oL.scales.x.type = "linear"; oL.scales.y.beginAtZero = false; oL.scales.y.ticks = {};
                if (logy) oL.scales.y.type = "logarithmic";
                oL.plugins.legend.display = used.length > 1;
                oL.plugins.tooltip.callbacks = { title: function (cs) { var q = cs[0].raw; return q.t ? tipLines(q) : fmt(q.x); } };
                draw({ type: "line", data: { datasets: dsL.concat(ovDs) }, options: oL });
                controls(false, "num");
                return;
            }
            // Histogram / cumulative: one bin grid over every drawn series so the overlays line up.
            var all = [].concat.apply([], numsOf), b1 = binSetup(all);
            var ds1 = used.map(function (s, i) {
                var counts1 = histCounts(numsOf[i], b1.lo, b1.hi, b1.nb), c = color(series.indexOf(s));
                if (m1 === "cum") { var run = 0; counts1 = counts1.map(function (k) { run += k; return run; }); }
                // Bars at bin centres on a linear axis so reference points land at their true x.
                var bars = counts1.map(function (k, j) { return { x: b1.lo + (j + 0.5) * b1.w, y: k }; });
                if (m1 === "cum") return { label: seriesLabel(s) + " (cumulative)", data: bars, type: "line", borderColor: c, backgroundColor: c + "22", fill: used.length === 1, stepped: "middle", pointRadius: 0, borderWidth: 2 };
                if (used.length > 1) {
                    // Overlaid histograms: stepped outlines on the bin edges, so a series hiding behind another still shows.
                    var edges = counts1.map(function (k, j) { return { x: b1.lo + j * b1.w, y: k }; }); edges.push({ x: b1.hi, y: counts1[counts1.length - 1] });
                    return { label: seriesLabel(s), data: edges, type: "line", borderColor: c, backgroundColor: c + "22", fill: true, stepped: "after", pointRadius: 0, borderWidth: 2 };
                }
                return { label: seriesLabel(s), data: bars, backgroundColor: c + "cc", barPercentage: 1, categoryPercentage: 1 };
            });
            var yT = (m1 === "cum" ? "cumulative " : "") + "count";
            var xKeys = used.map(function (s) { return s.x; }).filter(function (k, i, arr) { return arr.indexOf(k) === i; });
            var o1 = opts((xKeys.length > 1 ? xKeys.map(lastSeg).join(" · ") : showPath(xp)) + "  (bin width " + fmt(b1.w) + ")", yT);
            var xmin = Math.min.apply(null, [b1.lo].concat(ov.map(function (q) { return q.x; }))), xmax = Math.max.apply(null, [b1.hi].concat(ov.map(function (q) { return q.x; })));
            o1.scales.x = { type: "linear", min: xmin, max: xmax, offset: false, grid: { offset: false }, title: o1.scales.x.title,
                            ticks: { maxRotation: 45, autoSkipPadding: 12, font: { size: 11 }, callback: function (v) { return fmt(v); } } };
            if (logy) { o1.scales.y.type = "logarithmic"; delete o1.scales.y.beginAtZero; }
            var showStats = $("showstats").checked; $("stats-l").hidden = false;
            o1.plugins.legend.display = !showStats && used.length > 1;   // stats boxes name the series; without them, a legend does
            o1.plugins.statsBox = { rows: showStats ? rows : [] };
            o1.plugins.tooltip.callbacks = { title: function (cs) { var q = cs[0].raw, d = cs[0].dataset; return d.label === ($("ovn").value || "Reference") ? fmt(q.x) : d.stepped === "after" ? fmt(q.x) + " – " + fmt(q.x + b1.w) : fmt(q.x - b1.w / 2) + " – " + fmt(q.x + b1.w / 2); },
                                             label: function (c) { return c.dataset.label + ": " + c.raw.y; },
                                             // which values sit in the hovered bin — the item, its serial, the array index
                                             afterBody: function (cs) {
                                                 var c = cs[0], si = used.indexOf(used.filter(function (s) { return seriesLabel(s) === c.dataset.label; })[0]);
                                                 if (si < 0 || m1 === "cum" || c.dataset.stepped) return [];
                                                 var lines = [], more = 0;
                                                 numsOf[si].forEach(function (v, j) { if (Math.min(b1.nb - 1, Math.floor((v - b1.lo) / b1.w)) === c.dataIndex) { if (lines.length < 10) lines.push(numTags[si][j].t + (numTags[si][j].ix ? "  " + numTags[si][j].ix : "") + " = " + fmt(v)); else more++; } });
                                                 return more ? lines.concat(["… " + more + " more"]) : lines;
                                             } };
            draw({ type: "bar", data: { datasets: ds1.concat(ovDs) }, options: o1 });
            controls(true, "num");
            return;
        }
        // Categorical: bars per label, one dataset per series; the active series' top 40 labels lead.
        var c1 = topCats(vals, 40), oc = overlayCats(), ocKeys = Object.keys(oc);
        var labels1 = c1.keys.concat(ocKeys.filter(function (k) { return !(k in c1.counts); }));   // reference-only labels get a slot too
        var dsc = [];
        drawn.forEach(function (s, i) {
            if (i !== ai && (isNumeric(valsOf[i]) || !valsOf[i].length)) { if (valsOf[i].length) skipped.push(s.name); return; }
            var tc = i === ai ? c1 : topCats(valsOf[i], 1e9);
            dsc.push({ label: seriesLabel(s), data: labels1.map(function (k) { return tc.counts[k] || 0; }), backgroundColor: color(series.indexOf(s)) + "cc" });
        });
        stats.textContent = head + " · N=" + vals.length + "  unique=" + c1.unique + (c1.unique > 40 ? " (top 40 shown)" : "") + noteSkipped();
        if (ocKeys.length) dsc.push({ label: $("ovn").value || "Reference", data: labels1.map(function (c) { return c in oc ? oc[c] : null; }), type: "line", borderColor: OVER, borderDash: [6, 4], borderWidth: 2, pointRadius: 4, pointBackgroundColor: OVER, spanGaps: true });
        var oc1 = opts(showPath(xp), "count"); oc1.plugins.legend.display = dsc.length > 1;
        draw({ type: "bar", data: { labels: labels1, datasets: dsc }, options: oc1 });
        controls(false, "cat");
    }

    // ---- Controls ----------------------------------------------------------
    function fillSelect(sel, values, keep, blank) {
        var curv = keep ? sel.value : ""; sel.textContent = "";
        if (blank !== undefined) { var o0 = document.createElement("option"); o0.value = ""; o0.textContent = blank; sel.appendChild(o0); }
        values.forEach(function (v) { var o = document.createElement("option"); o.value = v.value; o.textContent = v.text; sel.appendChild(o); });
        if (values.some(function (v) { return v.value === curv; })) sel.value = curv;
    }
    // Rare = on fewer than 5% of items (and not all of a tiny type); hidden
    // from the key pickers unless the toggle is on or the key is in use.
    function isRare(p) { return pathCounts[p] < Math.max(2, 0.05 * items.length); }
    function keyOptions(keep) {
        var show = $("rare").checked;
        return paths.filter(function (p) { return show || !isRare(p) || keep.indexOf(p) >= 0; })
                    .map(function (p) {
                        var nv = isTest() ? keyNV(p) : pathCounts[p];
                        var shape = keyDims(p).filter(function (d) { return d.n > 1; }).map(function (d) { return d.n.toLocaleString(); });
                        return { value: p, text: showPath(p) + " (" + pathCounts[p] + (nv > pathCounts[p] ? " · " + nv.toLocaleString() + " values" : "") + ")"
                                                + (shape.length ? " [" + shape.join(" × ") + "]" : "") };
                    });
    }
    // The key tree: one folder per path segment, X / Y pick targets on every
    // leaf. Rare keys hide unless the toggle is on or the key is in use; the
    // search box keeps matching leaves and opens their folders.
    var closedFolders = {};             // folder path → the user closed it
    // List length per path segment of a key (0 = not a list there): dims name the
    // segment they belong to, so "Test Results › SiPM › I" → [6, 6, 300].
    function segDims(p) {
        var segs = JSON.parse(p), out = segs.map(function () { return 0; });
        keyDims(p).forEach(function (d) { var i = segs.indexOf(d.seg); if (i >= 0 && d.n > 1) out[i] = Math.max(out[i], d.n); });
        return out;
    }
    function dimBadge(n) { var b = document.createElement("span"); b.className = "shape"; b.textContent = n.toLocaleString(); b.title = "a list of " + n.toLocaleString() + " at this level"; return b; }
    var popAx = "x";                    // the axis the popover is choosing for
    function drawFields() {
        var s = S();
        ["x", "y"].forEach(function (ax) {
            var f = $(ax + "field"), p = s[ax]; f.textContent = ""; f.classList.toggle("empty", !p);
            var crumb = document.createElement("span"); crumb.className = "crumb";
            if (isExpr(p)) {
                var ex = document.createElement("span"); ex.textContent = exprText(p); ex.className = "leaf"; ex.style.fontFamily = "var(--font-mono)"; ex.style.fontWeight = "400"; ex.style.overflow = "hidden"; ex.style.textOverflow = "ellipsis"; ex.style.flex = "0 1 auto"; crumb.appendChild(ex);
                f.title = exprText(p) + " · Draw expression";
            } else if (p) {
                var segs = JSON.parse(p), sd = segDims(p);
                segs.forEach(function (seg, i) {
                    if (i) { var sp = document.createElement("span"); sp.className = "sep"; sp.textContent = "›"; crumb.appendChild(sp); }
                    var e = document.createElement("span"); e.textContent = seg; e.className = i === segs.length - 1 ? "leaf" : "par"; e.title = seg; crumb.appendChild(e);
                    if (sd[i]) crumb.appendChild(dimBadge(sd[i]));
                });
                f.title = showPath(p) + " · " + pathCounts[p] + " items";
            } else { var e0 = document.createElement("span"); e0.textContent = ax === "x" ? "choose a key…" : "— none —"; crumb.appendChild(e0); }
            f.appendChild(crumb);
            var car = document.createElement("span"); car.className = "car"; car.textContent = "▾"; f.appendChild(car);
        });
    }
    function openPop(ax) {
        popAx = ax; var pop = $("kpop"), f = $(ax + "field"), r = f.getBoundingClientRect(), vw = window.innerWidth, vh = window.innerHeight;
        $("xfield").classList.toggle("open", ax === "x"); $("yfield").classList.toggle("open", ax === "y");
        $("kpop-ax").textContent = ax.toUpperCase(); $("kpop-clear").hidden = ax === "x" && !S().x;
        pop.hidden = false;
        var w = Math.min(460, vw - 24), left = r.right + 10, top = Math.max(8, r.top - 44);
        if (left + w > vw - 12) { left = Math.max(12, Math.min(r.left, vw - w - 12)); top = r.bottom + 6; }   // no room to the right: drop below
        pop.style.left = left + "px"; pop.style.top = top + "px"; pop.style.width = w + "px"; pop.style.maxHeight = (vh - top - 12) + "px";
        $("kq").value = ""; drawTree(); $("kq").focus();
    }
    function closePop() { $("kpop").hidden = true; $("xfield").classList.remove("open"); $("yfield").classList.remove("open"); }
    function pickKey(p) { var s = S(); s[popAx] = p; closePop(); drawFields(); changed(); }
    $("xfield").addEventListener("click", function () { openPop("x"); });
    $("yfield").addEventListener("click", function () { openPop("y"); });
    ["xfield", "yfield"].forEach(function (id) { $(id).addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPop(id[0]); } }); });
    $("kpop-clear").addEventListener("click", function () { pickKey(""); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !$("kpop").hidden) closePop(); });
    document.addEventListener("mousedown", function (e) { if (!$("kpop").hidden && !$("kpop").contains(e.target) && !$("xfield").contains(e.target) && !$("yfield").contains(e.target)) closePop(); });
    window.addEventListener("resize", function () { if (!$("kpop").hidden) openPop(popAx); });
    function drawTree() {
        var s = S(), box = $("ktree"), q = $("kq").value.trim().toLowerCase(), show = $("rare").checked, other = popAx === "x" ? "y" : "x";
        var keep = seriesSpecs(s).map(function (sp) { return sp.p; });
        var root = { kids: {}, leaf: null, dim: 0 };
        paths.forEach(function (p) {
            if (!show && isRare(p) && keep.indexOf(p) < 0) return;
            if (q && showPath(p).toLowerCase().indexOf(q) < 0) return;
            var segs = JSON.parse(p), node = root, sd = segDims(p);
            segs.forEach(function (seg, i) { node = node.kids[seg] = node.kids[seg] || { kids: {}, leaf: null, dim: 0 }; node.dim = Math.max(node.dim, sd[i]); });
            node.leaf = p;
        });
        box.textContent = "";
        function leafRow(name, p, dim) {
            var row = document.createElement("div"); row.className = "kr" + (isRare(p) ? " rare" : "") + (p === s[popAx] ? " picked" : "") + (p === s[other] ? " other" : "");
            var nm = document.createElement("span"); nm.className = "nm"; nm.title = showPath(p) + " · " + pathCounts[p] + " items"; nm.setAttribute("data-other", other.toUpperCase());
            var tx = document.createElement("span"); tx.className = "t"; tx.textContent = name; nm.appendChild(tx);
            if (dim) nm.appendChild(dimBadge(dim));
            row.appendChild(nm);
            var c = document.createElement("span"); c.className = "cnt"; c.textContent = pathCounts[p].toLocaleString() + " items"; row.appendChild(c);
            row.addEventListener("click", function () { pickKey(p); });
            return row;
        }
        function folder(name, node, path) {
            var det = document.createElement("details"); det.open = q ? true : !closedFolders[path];
            var sum = document.createElement("summary"); sum.title = name;
            var st = document.createElement("span"); st.className = "t"; st.textContent = name; sum.appendChild(st);
            if (node.dim) sum.appendChild(dimBadge(node.dim));
            var leaves = 0, rare = true; (function count(n) { if (n.leaf) { leaves++; if (!isRare(n.leaf)) rare = false; } Object.keys(n.kids).forEach(function (k) { count(n.kids[k]); }); })(node);
            if (rare) sum.className = "rare";
            var c = document.createElement("span"); c.className = "cnt"; c.textContent = leaves + " key" + (leaves > 1 ? "s" : ""); sum.appendChild(c);
            det.appendChild(sum);
            det.addEventListener("toggle", function () { if (!q) closedFolders[path] = !det.open; });
            var kids = document.createElement("div"); kids.className = "kids";
            if (node.leaf) kids.appendChild(leafRow("(value)", node.leaf, 0));
            children(node, kids, path);
            det.appendChild(kids);
            return det;
        }
        function children(node, into, path) {
            Object.keys(node.kids).sort(function (a, b) {
                var A = node.kids[a], B = node.kids[b], fa = Object.keys(A.kids).length > 0, fb = Object.keys(B.kids).length > 0, ua = a[0] === "_", ub = b[0] === "_";
                if (ua !== ub) return ua ? 1 : -1;                                                   // _meta-style keys last
                return fa !== fb ? (fa ? 1 : -1) : a.toLowerCase() < b.toLowerCase() ? -1 : 1;      // leaves first, then folders, each alphabetical
            }).forEach(function (k) {
                var n = node.kids[k], sub = path + "/" + k;
                into.appendChild(Object.keys(n.kids).length ? folder(k, n, sub) : leafRow(k, n.leaf, n.dim));
            });
        }
        children(root, box, "");
        if (!Object.keys(root.kids).length) { var none = document.createElement("div"); none.className = "none"; none.textContent = q ? "no key matches" : "no keys"; box.appendChild(none); }
    }
    function cutRow(c, s) {
        var row = document.createElement("span"); row.className = "pl-cut";
        var ps = document.createElement("select"); fillSelect(ps, keyOptions([c.p]), false, "key…"); ps.value = c.p || "";
        var os = document.createElement("select"); fillSelect(os, OPS.map(function (o) { return { value: o, text: o }; })); os.value = c.o || "=";
        var vi = document.createElement("input"); vi.type = "text"; vi.placeholder = "value"; vi.value = c.v || "";
        var x = document.createElement("a"); x.href = "#"; x.textContent = "×"; x.title = "Remove";
        ps.addEventListener("change", function () { c.p = ps.value; changed(); });
        os.addEventListener("change", function () { c.o = os.value; changed(); });
        vi.addEventListener("input", function () { c.v = vi.value; changed(); });
        x.addEventListener("click", function (e) { e.preventDefault(); s.cuts.splice(s.cuts.indexOf(c), 1); drawCuts(); changed(); });
        row.appendChild(ps); row.appendChild(os); row.appendChild(vi); row.appendChild(x);
        return row;
    }
    function drawCuts() { var el = $("cuts"), s = S(); el.textContent = ""; s.cuts.forEach(function (c) { el.appendChild(cutRow(c, s)); }); }

    // Facet menus: the values present in the dataset, the active series' pick selected.
    var facetVals = {};
    function drawFacets() {
        var s = S();
        FACETS.forEach(function (k) {
            var vals = facetVals[k] || {}, keys = Object.keys(vals).sort(function (a, b) { return vals[b] - vals[a]; });
            $("f-" + k + "-l").hidden = keys.length < 2;
            fillSelect($("f-" + k), keys.map(function (v) { return { value: v, text: v + " (" + vals[v] + ")" }; }), false, "all");
            if (s.f[k] && vals[s.f[k]]) $("f-" + k).value = s.f[k]; else delete s.f[k];
        });
    }
    // The X / Y and Cuts controls show series[cur].
    function syncPanel() {
        var s = S();
        drawFields(); if (!$("kpop").hidden) drawTree(); syncDraw();
        $("item").value = s.item || ""; $("pidf").value = s.pid || ""; $("snf").value = s.sn || ""; $("logic").value = s.logic || "and";
        drawFacets(); drawCuts();
        Array.prototype.forEach.call(document.querySelectorAll(".pl-for"), function (el) {
            el.textContent = ""; if (series.length > 1) { el.appendChild(document.createTextNode("for ")); var b = document.createElement("b"); b.style.color = color(cur); b.textContent = s.name; el.appendChild(b); }
        });
    }
    function drawChips() {
        var box = $("chips"); box.textContent = "";
        var drawn = drawnSeries();
        series.forEach(function (s, i) {
            var chip = document.createElement("span"); chip.className = "pl-chip" + (i === cur ? " on" : "") + (drawn.indexOf(s) < 0 ? " dim" : "");
            chip.title = drawn.indexOf(s) < 0 ? "not drawn in this mode — click to edit" : "click to edit this series";
            var dot = document.createElement("span"); dot.className = "dot"; dot.style.background = color(i); chip.appendChild(dot);
            chip.appendChild(document.createTextNode(s.name));
            if (s.x) { var k = document.createElement("span"); k.className = "k"; k.textContent = lastSeg(s.x) + (s.y ? " × " + lastSeg(s.y) : ""); k.title = showPath(s.x) + (s.y ? " × " + showPath(s.y) : "") + (s.sel ? "\nselect: " + s.sel : ""); chip.appendChild(k); }
            if (series.length > 1) {
                var x = document.createElement("a"); x.className = "x"; x.href = "#"; x.textContent = "×"; x.title = "Remove this series";
                x.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); removeSeries(i); });
                chip.appendChild(x);
            }
            chip.addEventListener("click", function () { if (i !== cur) { cur = i; syncPanel(); changed(); } });
            box.appendChild(chip);
        });
        $("chip-add").hidden = !items.length;
        drawSeriesList();
    }
    function drawSeriesList() {
        var el = $("ser-list"); el.textContent = "";
        series.forEach(function (s, i) {
            var row = document.createElement("div"); row.className = "pl-ser" + (i === cur ? " on" : "");
            var dot = document.createElement("input"); dot.type = "color"; dot.className = "dot"; dot.value = color(i); dot.title = "Colour";
            dot.addEventListener("change", function () { s.color = dot.value; changed(); });
            var name = document.createElement("input"); name.type = "text"; name.value = s.name; name.title = "Rename";
            name.addEventListener("input", function () { s.name = name.value.trim() || ("Series " + (i + 1)); drawChipsOnly(); writeHash(); });
            name.addEventListener("blur", function () { name.value = s.name; syncPanel(); render(); drawItems(); });
            var x = document.createElement("a"); x.href = "#"; x.textContent = series.length > 1 ? "×" : ""; x.title = "Remove this series";
            x.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); if (series.length > 1) removeSeries(i); });
            var k = document.createElement("span"); k.className = "k"; k.textContent = s.x ? showPath(s.x) + (s.y ? " × " + showPath(s.y) : "") : "no key yet";
            row.appendChild(dot); row.appendChild(name); row.appendChild(x); row.appendChild(k);
            row.addEventListener("click", function (e) { if (e.target === name || e.target === dot) return; if (i !== cur) { cur = i; syncPanel(); changed(); } });
            el.appendChild(row);
        });
    }
    function drawChipsOnly() {      // a rename in flight: repaint chips without rebuilding the list the user is typing in
        var chips = $("chips").children;
        series.forEach(function (s, i) { if (chips[i]) chips[i].childNodes[1].nodeValue = s.name; });
    }
    function addSeries() {
        var s = copySeries(S()); s.name = nextName();       // an exact copy: same keys, pins, selection and cuts
        s.color = freeColor();                              // …but its own colour: the first one no series is using
        series.push(s); cur = series.length - 1;
        syncPanel(); changed(); showTab("data");
    }
    function removeSeries(i) {
        if (series.length < 2) return;
        series.splice(i, 1); if (cur >= series.length) cur = series.length - 1; else if (i < cur) cur--;
        syncPanel(); changed();
    }

    // Plot config lives in the URL hash so a plot is bookmarkable/shareable.
    function readHash() { try { return JSON.parse(decodeURIComponent(location.hash.slice(1)) || "{}"); } catch (e) { return {}; } }
    // Pre-#156 hashes (and the part page's #{"item": …} link) describe one series at the top level.
    function hashSeries(cfg) {
        if (Array.isArray(cfg.series) && cfg.series.length) return cfg.series;
        var s = { x: cfg.x, y: cfg.y, xi: cfg.xi, yi: cfg.yi, item: cfg.item, pid: cfg.pid, sn: cfg.sn, sel: cfg.sel, f: cfg.f, cuts: cfg.cuts, logic: cfg.logic };
        return [s];
    }
    function packSeries(s) {
        var f = {}; FACETS.forEach(function (k) { if (s.f[k]) f[k] = s.f[k]; });
        return { name: s.name, color: s.color || undefined, x: s.x, y: s.y || undefined, item: (s.item || "").trim() || undefined, pid: s.pid || undefined, sn: s.sn || undefined, sel: s.sel || undefined, f: Object.keys(f).length ? f : undefined,
                 xi: idxOf(s.x, s) || undefined, yi: idxOf(s.y, s) || undefined,
                 cuts: s.cuts.filter(function (c) { return c.p; }), logic: s.logic === "or" ? "or" : undefined };
    }
    function writeHash() {
        var cfg = { src: source, series: series.map(packSeries), cur: cur || undefined, bins: +$("bins").value,
                    ov: $("ov").value || undefined, ovn: $("ovn").value || undefined, xr: rangeOf("x") || undefined, yr: rangeOf("y") || undefined,
                    title: $("ptitle").value.trim() || undefined, xl: $("xlab").value.trim() || undefined, yl: $("ylab").value.trim() || undefined, sp: savedId || undefined,
                    rare: $("rare").checked ? undefined : false, m2: $("mode2d").value, m1: $("mode1d").value, logy: $("logy").checked || undefined, st: $("showstats").checked ? undefined : false,
                    ids: IDS || undefined };
        history.replaceState(null, "", "#" + encodeURIComponent(JSON.stringify(cfg)));
    }
    // #160: the checklist changes the frame's hash as PIDs are entered — same document, new entries
    window.addEventListener("hashchange", function () {
        var h = readHash();
        if (!Array.isArray(h.ids)) return;
        IDS = h.ids.map(String);
        if (items.length) { render(); drawItems(); }
    });
    function changed() { drawIdx(); syncDraw(); writeHash(); drawChips(); render(); drawItems(); drawSaved(); }

    // ---- Tabs ----------------------------------------------------------------
    var tabs = document.querySelectorAll(".pl-tab"), panes = document.querySelectorAll(".pl-panel [data-pane]");
    function showTab(name) {
        Array.prototype.forEach.call(tabs, function (t) { t.classList.toggle("on", t.dataset.tab === name); });
        Array.prototype.forEach.call(panes, function (p) { p.hidden = p.dataset.pane !== name; });
    }
    Array.prototype.forEach.call(tabs, function (t) { t.addEventListener("click", function () { if (!t.disabled) showTab(t.dataset.tab); }); });
    function enableTabs(on) { Array.prototype.forEach.call(tabs, function (t) { if (t.dataset.tab !== "data") t.disabled = !on; }); }

    // ---- Items grid: pick one item to plot (its arrays), or browse ----------
    // One value column per series with an X key: what that item contributes.
    var ITEMS_PER = 25, itemsPage = 0;
    function onePid() { var s = S(); return s && (s.item || "").trim() || null; }
    function cellValue(it, s) {
        var v = valuesFor(it, s.x, s);
        if (!v.length) return "";
        if (v.length === 1) { var n = toNum(v[0]); return n === null ? String(v[0]) : fmt(n); }
        return v.length.toLocaleString() + " values";
    }
    function drawItems() {
        var q = $("items-q").value.trim().toLowerCase();
        var list = (q ? items.filter(function (it) {
            return [it.pid, it.serial, it.status, it.creator, it.institution].join(" ").toLowerCase().indexOf(q) >= 0; }) : items.slice())
            .sort(function (a, b) { return a.pid < b.pid ? 1 : a.pid > b.pid ? -1 : 0; });     // newest (highest PID) first
        var pages = Math.max(1, Math.ceil(list.length / ITEMS_PER)); itemsPage = Math.min(itemsPage, pages - 1);
        $("items-n").textContent = "(" + list.length.toLocaleString() + ")";
        $("items-page").textContent = list.length ? (itemsPage + 1) + " / " + pages : "";
        $("items-prev").disabled = $("items-first").disabled = itemsPage === 0;
        $("items-next").disabled = $("items-last").disabled = itemsPage >= pages - 1;
        var one = onePid(); $("items-all").hidden = !one;
        var vcols = series.filter(function (s) { return s.x; });
        var head = $("items-head"); head.textContent = "";
        ["PID", "Serial", "Status", "Creator", "Institution", "Updated"].forEach(function (h) { var th = document.createElement("th"); th.textContent = h; head.appendChild(th); });
        vcols.forEach(function (s) {
            var th = document.createElement("th"); th.className = "v";
            var sw = document.createElement("span"); sw.className = "sw"; sw.style.background = color(series.indexOf(s)); th.appendChild(sw);
            th.appendChild(document.createTextNode((series.length > 1 ? s.name + " · " : "") + lastSeg(s.x))); th.title = showPath(s.x);
            head.appendChild(th);
        });
        var body = $("items-body"); body.textContent = "";
        list.slice(itemsPage * ITEMS_PER, (itemsPage + 1) * ITEMS_PER).forEach(function (it) {
            var tr = document.createElement("tr"); if (it.pid === one) tr.className = "is-on";
            [["mono", it.pid], ["", it.serial], ["", it.status], ["", it.creator], ["", it.institution], ["mono", it.updated || it.tested || ""]].forEach(function (c) {
                var td = document.createElement("td"); td.className = c[0]; td.textContent = c[1] || ""; td.title = c[1] || ""; tr.appendChild(td);
            });
            vcols.forEach(function (s) { var td = document.createElement("td"); td.className = "v"; td.textContent = cellValue(it, s); tr.appendChild(td); });
            tr.addEventListener("click", function () {
                if (String(window.getSelection && window.getSelection()).length) return;   // selecting text to copy, not picking
                S().item = it.pid === one ? "" : it.pid;     // click again to release
                $("item").value = S().item;
                changed();
            });
            body.appendChild(tr);
        });
    }
    $("items-q").addEventListener("input", function () { itemsPage = 0; drawItems(); });
    $("items-first").addEventListener("click", function () { itemsPage = 0; drawItems(); });
    $("items-prev").addEventListener("click", function () { itemsPage--; drawItems(); });
    $("items-next").addEventListener("click", function () { itemsPage++; drawItems(); });
    $("items-last").addEventListener("click", function () { itemsPage = 1e9; drawItems(); });
    $("items-all").addEventListener("click", function (e) { e.preventDefault(); S().item = ""; $("item").value = ""; changed(); });

    // Both sources land here: the item list + the key inventory → series → controls → plot.
    function setDataset(newItems, counts, statusText) {
        items = newItems; pathCounts = counts; specDims = {}; exprCache = {};
        itemByPid = {}; items.forEach(function (it) { itemByPid[it.pid] = it; });
        paths = Object.keys(counts).sort(function (a, b) { return (counts[b] - counts[a]) || (a < b ? -1 : 1); });
        $("data-status").textContent = statusText;
        var cfg = readHash(), acc = new Set(paths);
        $("rare").checked = cfg.rare !== false;    // shown by default; the hash remembers an opt-out
        $("rare-l").hidden = !paths.some(isRare);
        FACETS.forEach(function (k) { var vals = {}; items.forEach(function (it) { if (it[k]) vals[it[k]] = (vals[it[k]] || 0) + 1; }); facetVals[k] = vals; });
        series = hashSeries(cfg).map(function (h, i) {
            var s = blankSeries();
            s.name = (h.name || "").trim() || "Series " + (i + 1);
            s.color = /^#[0-9a-f]{6}$/i.test(h.color || "") ? h.color : "";
            s.x = h.x && (isExpr(h.x) || acc.has(h.x)) ? h.x : ""; s.y = h.y && (isExpr(h.y) || acc.has(h.y)) ? h.y : "";
            s.item = h.item || ""; s.pid = h.pid || ""; s.sn = h.sn || ""; s.sel = typeof h.sel === "string" ? h.sel : ""; s.f = h.f || {}; s.logic = h.logic === "or" ? "or" : "and";
            s.cuts = (h.cuts || []).filter(function (c) { return c && acc.has(c.p); });
            // #154: index pins from the hash belong to the keys it names
            s.xi = Array.isArray(h.xi) ? h.xi.map(function (j) { return j === null ? null : +j; }) : []; s.xk = s.x;
            s.yi = Array.isArray(h.yi) ? h.yi.map(function (j) { return j === null ? null : +j; }) : []; s.yk = s.y;
            return s;
        });
        cur = Math.min(+cfg.cur || 0, series.length - 1);
        // #160: entries from a checklist. Embedded, they stay live (the frame's
        // hash changes as the form is filled); on the full page they become
        // each series' PID filter, editable like any other.
        IDS = Array.isArray(cfg.ids) ? cfg.ids.map(String) : null;
        if (IDS && !EMBED) { var pf = idsFilter(); series.forEach(function (s) { s.item = ""; s.pid = pf; }); IDS = null; }
        savedId = typeof cfg.sp === "string" ? cfg.sp : null;
        if (!series[0].x && paths.length) series[0].x = paths[0];
        $("bins").value = cfg.bins || 40;
        $("ov").value = cfg.ov || ""; $("ovn").value = cfg.ovn || "";
        ["x", "y"].forEach(function (ax) { var r = Array.isArray(cfg[ax + "r"]) ? cfg[ax + "r"] : [null, null]; $(ax + "min").value = r[0] === null || r[0] === undefined ? "" : r[0]; $(ax + "max").value = r[1] === null || r[1] === undefined ? "" : r[1]; });
        $("ptitle").value = cfg.title || ""; $("xlab").value = cfg.xl || ""; $("ylab").value = cfg.yl || "";
        $("mode2d").value = ["scatter", "line", "heat"].indexOf(cfg.m2) >= 0 ? cfg.m2 : "scatter";
        $("mode1d").value = ["hist", "cum", "line"].indexOf(cfg.m1) >= 0 ? cfg.m1 : "hist"; $("logy").checked = !!cfg.logy; $("showstats").checked = cfg.st !== false;
        $("xidx").removeAttribute("data-key"); $("yidx").removeAttribute("data-key");
        syncPanel();
        enableTabs(true);
        $("items-card").hidden = !items.length;
        $("axes-grp").hidden = false;
        itemsPage = 0;
        $("stats").textContent = paths.length ? "" : "No keys on these items.";
        changed();
    }

    function loadSpecs(rec) {
        var rows = rec.items || [], counts = {};
        rows.forEach(function (it) { var s = new Set(); walk(it.data, [], s); s.forEach(function (p) { counts[p] = (counts[p] || 0) + 1; }); });
        $("fetch-btn").textContent = "Refresh"; $("fetch-full-btn").hidden = true;
        setDataset(rows, counts, rows.length.toLocaleString() + " items · fetched " + new Date(rec.fetched_at).toLocaleString());
    }

    async function loadTest(ttid) {
        var key = TYPE_KEY + "/test:" + ttid, rec = null;
        try { rec = await idbGet(key); } catch (e) { rec = null; }
        if (!rec || rec.v !== 2) {          // v2 (#154): keys carry dims, value slots may carry index pins
            var base = TESTS_BASE + "/" + ttid;
            var kj = await (await fetch(base + "/keys/")).json(), ij = await (await fetch(base + "/items/")).json();
            rec = { v: 2, fetched_at: new Date().toISOString(), keys: kj.keys || [], items: ij.items || [], values: {}, max_values: kj.max_values };
            await idbPut(key, rec);
        }
        testCache = rec;
        var counts = {}; rec.keys.forEach(function (k) { counts[JSON.stringify(k.path)] = k.n; });
        var rows = rec.items.map(function (it) {
            var o = Object.assign({}, it, { vals: {} });
            Object.keys(rec.values).forEach(function (slot) { if (rec.values[slot][it.pid]) o.vals[slot] = rec.values[slot][it.pid]; });
            return o;
        });
        $("fetch-btn").textContent = "Fetch new"; $("fetch-full-btn").hidden = false;
        setDataset(rows, counts, rows.length.toLocaleString() + " items with this test in the mirror");
    }

    async function switchSource() {
        var v = $("src").value;
        if (v === "__fetch__") { $("src").value = source; showTab("data"); await fetchTestData("incremental"); return; }
        source = v;
        enableTabs(false); showTab("data"); $("axes-grp").hidden = true; $("items-card").hidden = true; $("td-log").hidden = true; $("fetch-error").textContent = "";
        $("chips").textContent = ""; $("chip-add").hidden = true; if (chart) { chart.destroy(); chart = null; } $("stats").textContent = "";
        if (isTest()) { await loadTest(source); return; }
        var rec = null;
        try { rec = await idbGet(TYPE_KEY + "/specs"); } catch (e) { rec = null; }
        if (rec && rec.items) loadSpecs(rec);
        else {
            $("fetch-btn").textContent = "Fetch specifications"; $("fetch-full-btn").hidden = true;
            $("data-status").textContent = "No data in this browser yet.";
            var pages = Math.max(1, Math.ceil(N_ITEMS / 500));
            $("fetch-btn").title = N_ITEMS.toLocaleString() + " items · " + pages + " page" + (pages > 1 ? "s" : "") + " from HWDB";
            if (N_ITEMS <= 1000) fetchSpecs();
            else $("fetch-progress").textContent = "~" + pages + " pages from HWDB — may take a while";
        }
    }

    // ---- Draw box (#162): the active series as a ROOT-style line, and back --
    // A key is written as the fewest trailing segments that name it alone,
    // its pins as [i] on the leaf (ROOT order, [] for a free level).
    function keyAsName(p, ix) {
        var segs = JSON.parse(p), n = 1;
        for (; n < segs.length; n++) {
            var tl = segs.slice(segs.length - n);
            if (paths.filter(function (q) { var qs = JSON.parse(q); return qs.length >= n && qs.slice(qs.length - n).every(function (t, i) { return exprNorm(t) === exprNorm(tl[i]); }); }).length === 1) break;
        }
        var name = segs.slice(segs.length - n).map(function (t) { return /^[A-Za-z_][A-Za-z0-9_ ]*$/.test(t) ? t.replace(/ /g, "_") : JSON.stringify(t); }).join(".");
        if (ix && ix.some(function (i) { return i !== null; })) {
            var last = ix.length - 1; while (last >= 0 && ix[last] === null) last--;
            for (var l = 0; l <= last; l++) name += "[" + (ix[l] === null ? "" : ix[l]) + "]";
        }
        return name;
    }
    function drawText(s) {
        var parts = ["y", "x"].map(function (ax) { return s[ax] ? (isExpr(s[ax]) ? exprText(s[ax]) : keyAsName(s[ax], idxOf(s[ax], s))) : ""; });
        return parts[0] ? parts[0] + " : " + parts[1] : parts[1];
    }
    function syncDraw() {
        var s = S(); if (!s) return;
        if (document.activeElement !== $("draw")) $("draw").value = drawText(s);
        if (document.activeElement !== $("dsel")) $("dsel").value = s.sel || "";
        var err = drawErr(s); $("draw-err").textContent = err ? err : ""; $("draw-err").hidden = !err;
        var se = s.sel ? exprMeta(s.sel).err : null; $("sel-err").textContent = se ? se : ""; $("sel-err").hidden = !se;
    }
    function applySel() {           // #163: the selection is kept as typed; it compiles against the dataset like a Draw expression
        var s = S(); if (!s) return;
        var text = $("dsel").value.trim();
        if (text === (s.sel || "")) return;
        s.sel = text; changed(); $("dsel").blur();
    }
    $("dsel").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); applySel(); } if (e.key === "Escape") { $("dsel").blur(); syncDraw(); } });
    $("dsel").addEventListener("blur", applySel);
    function applyDraw() {
        var s = S(), text = $("draw").value.trim(), err = $("draw-err");
        function fail(msg) { err.textContent = msg; err.hidden = false; }
        if (!s) return;
        var parts = exprSplit(text);
        if (parts.length > 2) return fail("one “:” at most — y : x");
        var side = { x: parts[parts.length - 1], y: parts.length === 2 ? parts[0] : "" }, got = {};
        if (!side.x) return fail("write an expression for X" + (side.y ? " after the colon" : ""));
        for (var ax in side) {
            if (!side[ax]) { got[ax] = { p: "", ix: null }; continue; }
            var m = exprMeta("=" + side[ax]); if (m.err) return fail(m.err);
            var toks; try { toks = exprTokens(side[ax]); } catch (e) { return fail(e.message); }
            // a bare key name (pins included) is the key itself, so the index row and the picker stay in step
            got[ax] = toks.length === 1 && toks[0].t === "id" && m.ids.length === 1 ? { p: m.ids[0].p, ix: m.ids[0].ix } : { p: "=" + side[ax], ix: null };
        }
        s.x = got.x.p; s.xk = s.x; s.xi = got.x.ix ? got.x.ix.slice() : [];
        s.y = got.y.p; s.yk = s.y; s.yi = got.y.ix ? got.y.ix.slice() : [];
        err.hidden = true; $("xidx").removeAttribute("data-key"); $("yidx").removeAttribute("data-key");
        drawFields(); changed(); $("draw").blur();
    }
    $("draw").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); applyDraw(); } if (e.key === "Escape") { $("draw").blur(); syncDraw(); } });
    $("draw").addEventListener("blur", function () { if ($("draw").value.trim() !== drawText(S() || blankSeries())) applyDraw(); });
    $("draw-help").addEventListener("click", function () {
        var pop = $("dpop"), r = $("draw-help").getBoundingClientRect(), vw = window.innerWidth;
        if (!pop.hidden) { pop.hidden = true; return; }
        pop.hidden = false; var w = Math.min(520, vw - 24), left = r.right + 10;
        if (left + w > vw - 12) left = Math.max(12, vw - w - 12);
        pop.style.left = left + "px"; pop.style.top = Math.max(8, r.top - 8) + "px"; pop.style.width = w + "px"; pop.style.maxHeight = (window.innerHeight - Math.max(8, r.top - 8) - 12) + "px";
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") $("dpop").hidden = true; });
    document.addEventListener("mousedown", function (e) { if (!$("dpop").hidden && !$("dpop").contains(e.target) && e.target !== $("draw-help")) $("dpop").hidden = true; });

    // Per-series controls write into series[cur]; shared ones just redraw.
    $("kq").addEventListener("input", drawTree);
    $("pidf").addEventListener("input", function () { S().pid = $("pidf").value; changed(); });
    $("snf").addEventListener("input", function () { S().sn = $("snf").value; changed(); });
    // a pasted list of PIDs / serial numbers → an exact PID filter (the same
    // alternation a checklist's plot field hands over); unmatched entries are named
    var ldlg = $("list-dlg"), lta = $("list-ta"), lnote = $("list-note");
    function listEntries() { return lta.value.split(/[\s,;]+/).filter(Boolean); }
    function listNote() {
        var list = listEntries(), r = resolveIds(list);
        lnote.textContent = !list.length ? "" : r.pids.length + " item" + (r.pids.length === 1 ? "" : "s") + " of " + list.length + " entr" + (list.length === 1 ? "y" : "ies") +
                            (r.missing.length ? " · no item: " + r.missing.join(", ") : "");
        return r;
    }
    $("list-btn").addEventListener("click", function () {
        var m = /^\^\((.*)\)\$$/.exec(S().pid || "");          // the current exact filter, one PID per line
        lta.value = m && m[1] !== "-" ? m[1].split("|").join("\n") : "";
        listNote(); ldlg.showModal(); lta.focus();
    });
    lta.addEventListener("input", listNote);
    $("list-cancel").addEventListener("click", function () { ldlg.close(); });
    $("list-apply").addEventListener("click", function () {
        var r = listNote(), s = S();
        s.pid = listEntries().length ? pidAlternation(r.pids) : ""; s.item = "";
        $("pidf").value = s.pid; $("item").value = "";
        ldlg.close(); changed();
    });
    $("item").addEventListener("input", function () { S().item = $("item").value; changed(); });
    $("logic").addEventListener("change", function () { S().logic = $("logic").value; changed(); });
    FACETS.forEach(function (k) { $("f-" + k).addEventListener("change", function () { if ($("f-" + k).value) S().f[k] = $("f-" + k).value; else delete S().f[k]; changed(); }); });
    ["bins", "mode2d", "mode1d", "logy", "showstats"].forEach(function (id) { $(id).addEventListener("change", changed); });
    ["xmin", "xmax", "ymin", "ymax"].forEach(function (id) { $(id).addEventListener("change", changed); });
    ["ov", "ovn", "ptitle", "xlab", "ylab"].forEach(function (id) { $(id).addEventListener("input", changed); });
    $("zoom-reset").addEventListener("click", function () { if (chart && chart.resetZoom) chart.resetZoom(); });
    $("plot").addEventListener("dblclick", function () { if (chart && chart.resetZoom) chart.resetZoom(); });
    $("cut-add").addEventListener("click", function () { S().cuts.push({ p: "", o: "=", v: "" }); drawCuts(); });
    $("rare").addEventListener("change", function () { drawTree(); drawCuts(); writeHash(); });
    $("src").addEventListener("change", switchSource);
    $("fetch-btn").addEventListener("click", function () { if (isTest()) fetchTestData("incremental"); else fetchSpecs(); });
    $("fetch-full-btn").addEventListener("click", function () { fetchTestData("full"); });
    $("ser-add").addEventListener("click", addSeries);
    $("chip-add").addEventListener("click", addSeries);
    $("png-btn").addEventListener("click", function () {
        if (!chart) return;
        var c = chart.canvas, out = document.createElement("canvas"); out.width = c.width; out.height = c.height;
        var ctx = out.getContext("2d"); ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, out.width, out.height); ctx.drawImage(c, 0, 0);
        var a = document.createElement("a"); a.href = out.toDataURL("image/png");
        a.download = (cacheKey().replace(/[\/:]/g, "_") + "_" + showPath(S().x)).replace(/[^\w.-]+/g, "_") + ".png"; a.click();
    });

    // ---- Saved plots (#156): named URL hashes in this browser, per instance ----
    // A saved plot IS its hash; the list is what the Plots page shows too.
    var SAVED_KEY = "cets-plot-saved:" + TYPE_KEY.split("/")[0], savedId = null;
    var TYPE_NAME = document.querySelector(".pl-head h1").firstChild.nodeValue.trim(), PTID = TYPE_KEY.split("/")[1];
    function savedAll() { try { var a = JSON.parse(localStorage.getItem(SAVED_KEY) || "[]"); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
    function savedMine() { return savedAll().filter(function (r) { return r.ptid === PTID; }).sort(function (a, b) { return a.at < b.at ? 1 : -1; }); }
    function savedWrite(all) { try { localStorage.setItem(SAVED_KEY, JSON.stringify(all)); } catch (e) { alert("Could not save in this browser (storage blocked or full)."); } }
    function savedCurrent() { return savedAll().find(function (r) { return r.id === savedId; }) || null; }
    function drawSaved() {
        var rec = savedCurrent(), el = $("saved-name");
        el.hidden = !rec; $("save-btn").hidden = !rec;
        if (rec) { el.textContent = ""; el.appendChild(document.createTextNode("saved as ")); var b = document.createElement("b"); b.textContent = rec.name; el.appendChild(b); el.classList.toggle("dirty", rec.hash !== location.hash.slice(1)); el.title = rec.hash !== location.hash.slice(1) ? "changed since saved — Save overwrites" : "as saved"; }
    }
    function saveAs() {
        var cur = savedCurrent(), name = prompt("Name for this plot", cur ? cur.name : (S().x ? lastSeg(S().x) + (S().y ? " vs " + lastSeg(S().y) : "") : "plot"));
        if (name === null) return; name = name.trim(); if (!name) return;
        var all = savedAll(), same = all.find(function (r) { return r.ptid === PTID && r.name === name; });
        if (same && !confirm("“" + name + "” exists for this type — overwrite?")) return;
        var rec = same || { id: "p" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), ptid: PTID, type: TYPE_NAME, name: name };
        if (!same) all.push(rec);
        savedId = rec.id; writeHash();                       // the hash now carries the saved id, so record it after
        rec.hash = location.hash.slice(1); rec.at = new Date().toISOString();
        savedWrite(all); drawSaved();
    }
    function saveOver() {
        var all = savedAll(), rec = all.find(function (r) { return r.id === savedId; });
        if (!rec) { saveAs(); return; }
        rec.hash = location.hash.slice(1); rec.at = new Date().toISOString(); savedWrite(all); drawSaved();
    }
    function applyHash(hashStr) {          // load a saved plot: same source → rebuild from the hash; else switch source
        history.replaceState(null, "", "#" + hashStr);
        var want = String(readHash().src || "specs");
        if (want === source && items.length) { setDataset(items, pathCounts, $("data-status").textContent); return; }
        if (!Array.prototype.some.call($("src").options, function (o) { return o.value === want; })) { $("stats").textContent = "That plot's data source is not in the mirror here."; return; }
        $("src").value = want; switchSource();
    }
    function newPlot() {                   // from scratch: this source, one default series, nothing saved
        $("lpop").hidden = true; savedId = null;
        applyHash(encodeURIComponent(JSON.stringify({ src: source })));
    }
    // Every saved plot in this browser, this type first, the rest grouped by type;
    // another type's plot opens that type's Plot page with the saved hash.
    function drawLoadMenu() {
        var box = $("llist"), all = savedAll(); box.textContent = "";
        var nw = document.createElement("div"); nw.className = "sv new"; nw.title = "Start over with one default series on this source";
        var nn = document.createElement("span"); nn.className = "nm"; nn.textContent = "+ New plot"; nw.appendChild(nn);
        nw.addEventListener("click", newPlot); box.appendChild(nw);
        if (!all.length) { var none = document.createElement("div"); none.className = "none"; none.textContent = "Nothing saved in this browser yet — Save as… keeps the current plot."; box.appendChild(none); return; }
        var groups = {}; all.forEach(function (r) { (groups[r.ptid] = groups[r.ptid] || []).push(r); });
        var order = Object.keys(groups).sort(function (a, b) { return a === PTID ? -1 : b === PTID ? 1 : (groups[a][0].type || a).toLowerCase() < (groups[b][0].type || b).toLowerCase() ? -1 : 1; });
        order.forEach(function (ptid) {
            var mine = ptid === PTID, gh = document.createElement("div"); gh.className = "gh" + (mine ? " mine" : "");
            gh.textContent = mine ? "this type" : (groups[ptid][0].type || ptid); gh.title = ptid; box.appendChild(gh);
            groups[ptid].sort(function (a, b) { return a.at < b.at ? 1 : -1; }).forEach(function (r) {
                var row = document.createElement("div"); row.className = "sv" + (mine ? "" : " away");
                var nm = document.createElement("span"); nm.className = "nm" + (r.id === savedId ? " on" : ""); nm.textContent = r.name; nm.title = mine ? r.name : r.name + " — opens the " + (r.type || ptid) + " plot page";
                var when = document.createElement("span"); when.className = "when"; when.textContent = new Date(r.at).toLocaleDateString();
                var del = document.createElement("a"); del.className = "del"; del.href = "#"; del.textContent = "×"; del.title = "Forget this saved plot";
                del.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); if (!confirm("Forget “" + r.name + "”?")) return; savedWrite(savedAll().filter(function (x) { return x.id !== r.id; })); if (savedId === r.id) { savedId = null; writeHash(); drawSaved(); } drawLoadMenu(); });
                row.appendChild(nm);
                if (!mine) { var go = document.createElement("span"); go.className = "go"; go.textContent = "opens ↗"; row.appendChild(go); }
                row.appendChild(when); row.appendChild(del);
                row.addEventListener("click", function () {
                    $("lpop").hidden = true;
                    if (mine) { savedId = r.id; applyHash(r.hash); }
                    else location.href = location.pathname.replace(/\/plot\/[^\/]+\/$/, "/plot/" + r.ptid + "/") + "#" + r.hash;
                });
                box.appendChild(row);
            });
        });
    }
    $("load-btn").addEventListener("click", function () {
        var pop = $("lpop"), r = $("load-btn").getBoundingClientRect(), w = Math.min(360, window.innerWidth - 24);
        pop.hidden = false; pop.style.width = w + "px"; pop.style.left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12)) + "px"; pop.style.top = (r.bottom + 6) + "px"; pop.style.maxHeight = (window.innerHeight - r.bottom - 18) + "px";
        drawLoadMenu();
    });
    $("save-btn").addEventListener("click", saveOver);
    $("saveas-btn").addEventListener("click", saveAs);
    $("link-btn").addEventListener("click", function () {
        var url = location.href, btn = $("link-btn");
        (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(function () { btn.textContent = "Copied"; }, function () { prompt("Copy this link", url); })
            .then(function () { setTimeout(function () { btn.textContent = "Copy link"; }, 1200); });
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") $("lpop").hidden = true; });
    document.addEventListener("mousedown", function (e) { if (!$("lpop").hidden && !$("lpop").contains(e.target) && e.target !== $("load-btn")) $("lpop").hidden = true; });

    // Panel width: drag the separator; remembered per browser.
    (function () {
        var wb = document.querySelector(".pl-wb"), KEY = "cets-plot-pw";
        try { var w = +localStorage.getItem(KEY); if (w >= 240 && w <= 640) wb.style.setProperty("--pw", w + "px"); } catch (e) {}
        $("vsplit").addEventListener("mousedown", function (e) {
            e.preventDefault(); $("vsplit").classList.add("on");
            var x0 = e.clientX, w0 = document.querySelector(".pl-panel").getBoundingClientRect().width;
            function move(ev) { wb.style.setProperty("--pw", Math.max(240, Math.min(640, w0 + ev.clientX - x0)) + "px"); }
            function up() { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); $("vsplit").classList.remove("on");
                            try { localStorage.setItem(KEY, String(Math.round(document.querySelector(".pl-panel").getBoundingClientRect().width))); } catch (er) {} }
            document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
        });
    })();
    // Plot height: drag the handle; remembered per browser.
    (function () {
        var wrap = $("plot-card"), KEY = "cets-plot-h";
        try { var h = +localStorage.getItem(KEY); if (h >= 240 && h <= 1200) wrap.style.height = h + "px"; } catch (e) {}
        $("split").addEventListener("mousedown", function (e) {
            e.preventDefault();
            var y0 = e.clientY, h0 = wrap.getBoundingClientRect().height;
            function move(ev) { wrap.style.height = Math.max(240, Math.min(1200, h0 + ev.clientY - y0)) + "px"; }
            function up() { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); try { localStorage.setItem(KEY, String(Math.round(wrap.getBoundingClientRect().height))); } catch (er) {} }
            document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
        });
    })();

    // Boot: sources first (mirror-only), then the hash's source or specs.
    loadSources().then(function (srcs) {
        var want = String(readHash().src || "specs");
        if (want !== "specs" && !srcs.some(function (t) { return String(t.id) === want; })) want = "specs";
        $("src").value = want;
        return switchSource();
    });
})();
