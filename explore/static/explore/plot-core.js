// HWDB Explorer — Plots page, pure core: no DOM, no page state. Loaded before
// plot.js (window.PlotCore); the test suite require()s it in node.
(function (root) {
    // ---- Nested records (#154) ---------------------------------------------
    // The specs source keeps records in the browser, so the server's nested /
    // dims / dim_labels / select (plotting.py) are mirrored here.
    function nestedAt(node, segs, i) {
        if (Array.isArray(node)) {
            var out = [];
            node.forEach(function (e) { var r = nestedAt(e, segs, i); if (r !== null && !(Array.isArray(r) && !r.length)) out.push(r); });
            return out;
        }
        if (i === segs.length) return (node !== null && node !== undefined && typeof node !== "object") ? node : null;
        if (node && typeof node === "object" && Object.prototype.hasOwnProperty.call(node, segs[i])) return nestedAt(node[segs[i]], segs, i + 1);
        return null;
    }
    function dimsOf(v) {
        if (!Array.isArray(v)) return [];
        var sub = [];
        v.forEach(function (e) { dimsOf(e).forEach(function (n, k) { sub[k] = Math.max(sub[k] || 0, n); }); });
        return [v.length].concat(sub);
    }
    function dimLabels(node, segs) {
        var out = [], i = 0;
        for (;;) {
            if (Array.isArray(node)) {
                out.push(i ? segs[i - 1] : "");
                var nxt = null;
                for (var k = 0; k < node.length; k++) { var r = nestedAt(node[k], segs, i); if (r !== null && !(Array.isArray(r) && !r.length)) { nxt = node[k]; break; } }
                if (nxt === null) return out;
                node = nxt; continue;
            }
            if (i === segs.length) return out;
            if (node && typeof node === "object" && Object.prototype.hasOwnProperty.call(node, segs[i])) { node = node[segs[i]]; i++; continue; }
            return out;
        }
    }
    function selectAt(v, idx, d) {
        d = d || 0;
        if (!Array.isArray(v)) return [v];
        var i = d < idx.length ? idx[d] : null;
        if (i === null || i === undefined) { var out = []; v.forEach(function (e) { out = out.concat(selectAt(e, idx, d + 1)); }); return out; }
        return (i >= 0 && i < v.length) ? selectAt(v[i], idx, d + 1) : [];
    }

    // ---- ROOT-style Draw expressions (#162, TTree::Draw) ---------------------
    // Tokenizer, parser (precedence climbing), compiler to a closure over an identifier
    // environment, the key-name resolver and the position-wise evaluator.
    // No DOM in this block — test_plotting runs it in node.
    var EXPR_FUNCS = { sqrt: Math.sqrt, abs: Math.abs, log: Math.log, log10: Math.log10, exp: Math.exp, pow: Math.pow, sin: Math.sin, cos: Math.cos, tan: Math.tan,
                       atan: Math.atan, atan2: Math.atan2, min: Math.min, max: Math.max, floor: Math.floor, ceil: Math.ceil, round: Math.round };
    var EXPR_CONSTS = { pi: Math.PI, e: Math.E };
    var EXPR_PREC = { "||": 1, "&&": 2, "==": 3, "!=": 3, "=~": 3, "<": 4, "<=": 4, ">": 4, ">=": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6 };
    var EXPR_ATTRS = ["pid", "serial", "status", "creator", "institution", "manufacturer"];   // $pid … : the item's own fields (#163)
    function isExpr(p) { return typeof p === "string" && p.charAt(0) === "="; }     // a series' x / y: "=expr", else a JSON key path
    function exprText(p) { return isExpr(p) ? p.slice(1) : p; }
    function exprNum(v) {
        if (typeof v === "number") return isFinite(v) ? v : null;
        if (typeof v === "string" && v.trim() !== "") { var n = Number(v); return isFinite(n) ? n : null; }
        return null;
    }
    // "y : x" at the top level (outside brackets and quotes) → [y, x]; no colon → [x]
    function exprSplit(text) {
        var parts = [], depth = 0, q = false, cur = "";
        for (var i = 0; i < text.length; i++) {
            var ch = text[i];
            if (ch === '"') q = !q;
            if (!q) {
                if (ch === "(" || ch === "[") depth++; else if (ch === ")" || ch === "]") depth--;
                else if (ch === ":" && !depth) { parts.push(cur); cur = ""; continue; }
            }
            cur += ch;
        }
        parts.push(cur);
        return parts.map(function (s) { return s.trim(); });
    }
    // Tokens: numbers; 'strings' (single quotes — double quotes name keys);
    // $attr = an item field; identifiers = segments (bare, or "quoted" for
    // other characters) joined by ".", each with optional [i] / [] pins; a bare
    // name before "(" is a function; operators. Positions are 1-based in messages.
    function exprTokens(text) {
        var out = [], i = 0, n = text.length, OPS2 = ["&&", "||", "==", "!=", "=~", "<=", ">=", ">>"], OPS1 = "+-*/%^(),<>!";
        while (i < n) {
            var ch = text[i];
            if (/\s/.test(ch)) { i++; continue; }
            if (ch === "'") {
                var qe = text.indexOf("'", i + 1); if (qe < 0) throw new Error("unclosed quote at " + (i + 1));
                out.push({ t: "str", v: text.slice(i + 1, qe), at: i }); i = qe + 1; continue;
            }
            if (ch === "$") {
                var ma = /^\$([A-Za-z_]+)/.exec(text.slice(i)); if (!ma) throw new Error("bad name at " + (i + 1));
                if (EXPR_ATTRS.indexOf(ma[1].toLowerCase()) < 0) throw new Error("no item field “" + ma[0] + "” — one of $" + EXPR_ATTRS.join(" $"));
                out.push({ t: "attr", v: ma[1].toLowerCase(), text: ma[0], at: i }); i += ma[0].length; continue;
            }
            if (/[0-9.]/.test(ch)) {
                var m = /^(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?/.exec(text.slice(i));
                if (!m) throw new Error("bad number at " + (i + 1));
                out.push({ t: "num", v: +m[0], at: i }); i += m[0].length; continue;
            }
            if (/[A-Za-z_"]/.test(ch)) {
                var start = i, segs = [];
                for (;;) {
                    var seg;
                    if (text[i] === '"') {
                        var e = text.indexOf('"', i + 1); if (e < 0) throw new Error("unclosed quote at " + (i + 1));
                        seg = { name: text.slice(i + 1, e), pins: [] }; i = e + 1;
                    } else {
                        var mm = /^[A-Za-z_][A-Za-z0-9_]*/.exec(text.slice(i)); if (!mm) throw new Error("bad name at " + (i + 1));
                        seg = { name: mm[0], pins: [] }; i += mm[0].length;
                    }
                    while (text[i] === "[") {
                        var mb = /^\[\s*(\d*|\*)\s*\]/.exec(text.slice(i)); if (!mb) throw new Error("bad index at " + (i + 1));
                        seg.pins.push(mb[1] === "" || mb[1] === "*" ? null : +mb[1]); i += mb[0].length;
                    }
                    segs.push(seg);
                    if (text[i] === ".") { i++; continue; }
                    break;
                }
                var ws = i; while (ws < n && /\s/.test(text[ws])) ws++;
                if (segs.length === 1 && !segs[0].pins.length && text[ws] === "(") { out.push({ t: "fn", v: segs[0].name, at: start }); i = ws; continue; }
                out.push({ t: "id", v: segs, text: text.slice(start, i), at: start }); continue;
            }
            var op = OPS2.find(function (o) { return text.substr(i, 2) === o; }) || (OPS1.indexOf(ch) >= 0 ? ch : null);
            if (!op) throw new Error("unexpected “" + ch + "” at " + (i + 1));
            if (op === ">>") throw new Error("binning goes at the end: expr >> (nx,lo,hi)");
            out.push({ t: "op", v: op, at: i }); i += op.length;
        }
        return out;
    }
    // Values are raw in the environment: arithmetic coerces to a number (NaN
    // when it cannot, so the entry drops); comparisons are numeric when both
    // sides read as numbers, else on the text; truth = a non-zero number or a
    // non-empty string.
    function exprNv(x) { var n = exprNum(x); return n === null ? NaN : n; }
    function exprTruthy(x) { return typeof x === "string" ? x !== "" : !!exprNum(x); }
    function exprCmp(a, b) {
        var na = exprNum(a), nb = exprNum(b);
        if (na !== null && nb !== null) return na < nb ? -1 : na > nb ? 1 : 0;
        var sa = a === null || a === undefined ? "" : String(a), sb = b === null || b === undefined ? "" : String(b);
        return sa < sb ? -1 : sa > sb ? 1 : 0;
    }
    // Compile: resolve(idToken) returns the identifier's slot in the value
    // environment (or throws). Result: { fn(env) → number, ids: [idToken] }.
    // ^ binds tighter than unary minus (-x^2 = -(x^2)) and is right-associative.
    function exprCompile(text, resolve) {
        var toks = exprTokens(text), pos = 0, ids = [];
        if (!toks.length) throw new Error("empty expression");
        function peek() { return toks[pos]; }
        function take() { return toks[pos++]; }
        function isOp(t, v) { return t && t.t === "op" && t.v === v; }
        function expectOp(v) { var t = take(); if (!isOp(t, v)) throw new Error("expected “" + v + "”" + (t ? " at " + (t.at + 1) : " at the end")); }
        function primary() {
            var t = take();
            if (!t) throw new Error("unexpected end");
            if (t.t === "num" || t.t === "str") { var v = t.v; return function () { return v; }; }
            if (t.t === "attr") { var ka = resolve(t); ids.push(t); return function (env) { return env[ka]; }; }
            if (t.t === "id") {
                var k;
                try { k = resolve(t); }
                catch (err) {
                    var nm = t.v[0].name.toLowerCase();
                    if (t.v.length === 1 && !t.v[0].pins.length && Object.prototype.hasOwnProperty.call(EXPR_CONSTS, nm)) { var c = EXPR_CONSTS[nm]; return function () { return c; }; }
                    throw err;
                }
                ids.push(t);
                return function (env) { return env[k]; };
            }
            if (t.t === "fn") {
                var f = EXPR_FUNCS[t.v.toLowerCase()]; if (!f) throw new Error("unknown function " + t.v);
                expectOp("("); var args = [];
                if (!isOp(peek(), ")")) { args.push(expr(0)); while (isOp(peek(), ",")) { take(); args.push(expr(0)); } }
                expectOp(")");
                return function (env) { return f.apply(null, args.map(function (a) { return exprNv(a(env)); })); };
            }
            if (isOp(t, "(")) { var e = expr(0); expectOp(")"); return e; }
            if (isOp(t, "-")) { var u = unary(); return function (env) { return -exprNv(u(env)); }; }
            if (isOp(t, "!")) { var u2 = unary(); return function (env) { return exprTruthy(u2(env)) ? 0 : 1; }; }
            throw new Error("unexpected “" + t.v + "” at " + (t.at + 1));
        }
        function unary() {
            var base = primary();
            if (isOp(peek(), "^")) { take(); var ex = unary(), b0 = base; base = function (env) { return Math.pow(exprNv(b0(env)), exprNv(ex(env))); }; }
            return base;
        }
        function expr(minPrec) {
            var left = unary();
            for (;;) {
                var t = peek(); if (!t || t.t !== "op" || !Object.prototype.hasOwnProperty.call(EXPR_PREC, t.v) || EXPR_PREC[t.v] < minPrec) break;
                take();
                var rt = peek(), right = expr(EXPR_PREC[t.v] + 1);
                if (t.v === "=~") {          // regex, case-insensitive; a literal pattern compiles once
                    var lit = rt && rt.t === "str" && toks[pos - 1] === rt ? rt.v : null, re0 = null;
                    if (lit !== null) { try { re0 = new RegExp(lit, "i"); } catch (e) { throw new Error("bad pattern “" + lit + "”"); } }
                    left = (function (l, r, re0) { return function (env) {
                        var a = l(env); if (a === null || a === undefined) return 0;
                        var re = re0; if (!re) { try { re = new RegExp(String(r(env)), "i"); } catch (e) { return 0; } }
                        return re.test(String(a)) ? 1 : 0;
                    }; })(left, right, re0);
                    continue;
                }
                left = (function (op, l, r) { return function (env) {
                    var a = l(env), b = r(env);
                    switch (op) {
                        case "&&": return exprTruthy(a) && exprTruthy(b) ? 1 : 0; case "||": return exprTruthy(a) || exprTruthy(b) ? 1 : 0;
                        case "==": return exprCmp(a, b) === 0 ? 1 : 0; case "!=": return exprCmp(a, b) !== 0 ? 1 : 0;
                        case "<": return exprCmp(a, b) < 0 ? 1 : 0; case "<=": return exprCmp(a, b) <= 0 ? 1 : 0; case ">": return exprCmp(a, b) > 0 ? 1 : 0; case ">=": return exprCmp(a, b) >= 0 ? 1 : 0;
                    }
                    a = exprNv(a); b = exprNv(b);
                    switch (op) { case "+": return a + b; case "-": return a - b; case "*": return a * b; case "/": return a / b; default: return a % b; }
                }; })(t.v, left, right);
            }
            return left;
        }
        var fn = expr(0);
        if (pos < toks.length) throw new Error("unexpected “" + toks[pos].v + "” at " + (toks[pos].at + 1));
        return { fn: fn, ids: ids };
    }
    // ROOT's "expr >> name(nx,lo,hi)" (#164): the trailing binning off a Draw
    // line → { expr, name, bins }. bins: null, or { nx, lo, hi, ny, lo2, hi2 }
    // from (nx) · (nx,lo,hi) · (nx,lo,hi,ny) · (nx,lo,hi,ny,lo2,hi2); a blank
    // bound stays automatic.
    function exprBinning(text) {
        var m = /^([\s\S]*?)\s*>>\s*([A-Za-z_][A-Za-z0-9_]*)?\s*(?:\(([^()]*)\))?\s*$/.exec(text);
        if (!m) return { expr: text.trim(), name: "", bins: null };
        var out = { expr: m[1].trim(), name: m[2] || "", bins: null };
        if (m[3] === undefined) return out;
        var a = m[3].split(",").map(function (v) { return v.trim(); }), num = function (v) { return v === "" ? null : (isFinite(+v) ? +v : NaN); };
        if ([1, 3, 4, 6].indexOf(a.length) < 0) throw new Error("binning: (nx), (nx,lo,hi), (nx,lo,hi,ny) or (nx,lo,hi,ny,lo2,hi2)");
        var v = a.map(num);
        if (v.some(function (x) { return x !== null && isNaN(x); })) throw new Error("binning: numbers only — " + m[3]);
        if (!(v[0] >= 2) || (a.length >= 4 && !(v[3] >= 2))) throw new Error("binning: at least 2 bins");
        out.bins = { nx: Math.floor(v[0]), lo: v[1] === undefined ? null : v[1], hi: v[2] === undefined ? null : v[2],
                     ny: a.length >= 4 ? Math.floor(v[3]) : null, lo2: v[4] === undefined ? null : v[4], hi2: v[5] === undefined ? null : v[5] };
        if (out.bins.lo !== null && out.bins.hi !== null && out.bins.lo >= out.bins.hi) throw new Error("binning: lo must be below hi");
        if (out.bins.lo2 !== null && out.bins.hi2 !== null && out.bins.lo2 >= out.bins.hi2) throw new Error("binning: lo2 must be below hi2");
        return out;
    }
    // ROOT's third argument: the plot type and switches → { m1, m2, logy, stats }
    // (only what the text names); an unknown word throws.
    var EXPR_OPTS = { hist: { m1: "hist" }, cum: { m1: "cum" }, cumulative: { m1: "cum" }, line: { m1: "line", m2: "line" }, l: { m1: "line", m2: "line" },
                      scat: { m2: "scatter" }, scatter: { m2: "scatter" }, p: { m2: "scatter" }, colz: { m2: "heat" }, col: { m2: "heat" }, box: { m2: "heat" },
                      logy: { logy: true }, liny: { logy: false }, nostats: { stats: false }, nostat: { stats: false }, stats: { stats: true } };
    function exprOption(text) {
        var out = {};
        String(text || "").toLowerCase().split(/[\s,;]+/).filter(Boolean).forEach(function (w) {
            if (!Object.prototype.hasOwnProperty.call(EXPR_OPTS, w)) throw new Error("unknown option “" + w + "” — hist cum line · scat line colz · logy liny nostats stats");
            var o = EXPR_OPTS[w]; Object.keys(o).forEach(function (f) { out[f] = o[f]; });
        });
        return out;
    }
    // A name → one key. keys: [{ p, segs, dims() }]. The name's segments match
    // the key's trailing segments; case and space/underscore are ignored unless
    // that leaves several keys — then the exact spelling decides. Pins: [i] on
    // an inner segment that names a list level pins that level; on the leaf,
    // the levels in order from the first (ROOT: a[i][j]); [] skips one.
    function exprNorm(s) { return String(s).toLowerCase().replace(/[\s_]+/g, "_"); }
    function exprResolve(idTok, keys) {
        var segs = idTok.v, n = segs.length;
        function tail(k, i) { return k.segs[k.segs.length - n + i]; }
        var loose = keys.filter(function (k) { return k.segs.length >= n && segs.every(function (sg, i) { return exprNorm(tail(k, i)) === exprNorm(sg.name); }); });
        var hits = loose;
        if (loose.length > 1) {
            var exact = loose.filter(function (k) { return segs.every(function (sg, i) { return tail(k, i) === sg.name || tail(k, i) === sg.name.replace(/_/g, " "); }); });
            if (exact.length === 1) hits = exact;
            else throw new Error("“" + idTok.text + "” matches " + loose.length + " keys: " + loose.slice(0, 5).map(function (k) { return k.segs.join("."); }).join(", ") + (loose.length > 5 ? ", …" : ""));
        }
        if (!hits.length) throw new Error("no key named “" + idTok.text + "”");
        var k = hits[0], dims = k.dims() || [], ix = null;
        segs.forEach(function (sg, i) {
            if (!sg.pins.length) return;
            // the leaf's brackets count dimensions from the first (ROOT: a[i][j]) even when the leaf itself names the innermost
            // list (V[0][1] on Test Results › SiPM › V pins Test Results and SiPM); brackets on an inner segment pin the level it names
            var name = tail(k, i), named = dims.map(function (d, j) { return d.seg === name ? j : -1; }).filter(function (j) { return j >= 0; });
            var levels = i === n - 1 ? dims.map(function (d, j) { return j; }) : named;
            if (!levels.length) throw new Error("“" + name + "” is not a list");
            if (sg.pins.length > levels.length) throw new Error("“" + name + "” has " + levels.length + " index" + (levels.length > 1 ? "es" : "") + ", not " + sg.pins.length);
            ix = ix || dims.map(function () { return null; });
            sg.pins.forEach(function (pin, q) {
                var lv = levels[q]; if (pin === null) return;
                if (pin >= dims[lv].n) throw new Error("index " + pin + " is past the end of " + (dims[lv].seg || "level " + (lv + 1)) + " (" + dims[lv].n + " entries)");
                ix[lv] = pin;
            });
        });
        if (ix && !ix.some(function (v) { return v !== null; })) ix = null;
        return { p: k.p, ix: ix };
    }
    // Evaluate over one item: arrays run together position by position up to the
    // shortest, a single value repeats, an identifier with no values gives
    // nothing; an entry whose result is not a finite number drops out. out.src
    // keeps each result's source position (tooltips, X–Y pairing, selection);
    // out.n is the entry count the arrays ran over (1 = only single values).
    function exprEval(fn, arrays) {
        var n = Infinity;
        arrays.forEach(function (a) { if (!a.length) n = 0; else if (a.length > 1) n = Math.min(n, a.length); });
        if (n === Infinity) n = 1;
        var out = [], src = [], env = new Array(arrays.length);
        for (var j = 0; j < n; j++) {
            for (var k = 0; k < arrays.length; k++) env[k] = arrays[k].length > 1 ? arrays[k][j] : arrays[k][0];
            var r = fn(env);
            if (typeof r === "number" && isFinite(r)) { out.push(r); src.push(j); }
        }
        out.src = src; out.n = n;
        return out;
    }
    // A selection (#163) over an item's entries: the mask's kept positions
    // filter arr by source position; all-scalar masks keep or drop the whole item.
    function exprSelect(arr, mask) {
        var out = [], src = [];
        if (mask.n === 1) { if (mask.length && mask[0]) return arr; out.src = []; return out; }
        var keep = {}; mask.forEach(function (v, j) { if (v) keep[mask.src[j]] = true; });
        arr.forEach(function (v, j) { var q = arr.src ? arr.src[j] : j; if (keep[q]) { out.push(v); src.push(q); } });
        out.src = src;
        return out;
    }

    // ---- Small helpers shared by the page ----------------------------------
    function normSn(v) { return String(v).toLowerCase().replace(/\d+/g, function (d) { return d.replace(/^0+(?=\d)/, ""); }); }
    function pidAlternation(pids) { return "^(" + (pids.length ? pids.join("|") : "-") + ")$"; }
    // "00120..06000" / "D00400300001-00120..06000" / open ends → [lo, hi] on the numeric suffix, else null
    function pidRange(str) {
        var m = /^\s*(?:[A-Za-z]\d{11}-)?(\d*)\s*\.\.\s*(\d*)\s*$/.exec(str || "");
        if (!m || !(m[1] || m[2])) return null;
        return [m[1] ? +m[1] : -Infinity, m[2] ? +m[2] : Infinity];
    }
    function toNum(v) {
        if (typeof v === "number") return isFinite(v) ? v : null;
        if (typeof v === "string" && v.trim() !== "") { var n = Number(v); return isFinite(n) ? n : null; }
        return null;
    }
    function fmt(n) { return Math.abs(n) >= 1000 || Number.isInteger(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : n.toPrecision(4); }
    function histCounts(nums, lo, hi, nb) {
        var w = (hi - lo) / nb || 1, counts = new Array(nb).fill(0);
        nums.forEach(function (v) { if (v < lo || v > hi) return; var b = Math.min(nb - 1, Math.floor((v - lo) / w)); counts[b]++; });   // outside the edges: no bin
        return counts;
    }
    function isNumeric(vals) {
        var nums = vals.map(toNum).filter(function (v) { return v !== null; });
        return vals.length > 0 && nums.length > 0.8 * vals.length;
    }
    function catKey(v) { return v === true ? "True" : v === false ? "False" : String(v); }
    function topCats(vals, n) {
        var counts = {}; vals.forEach(function (v) { var k = catKey(v); counts[k] = (counts[k] || 0) + 1; });
        return { keys: Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; }).slice(0, n), counts: counts, unique: Object.keys(counts).length };
    }
    function meanSd(nums) {
        var n = nums.length, mean = nums.reduce(function (a, c) { return a + c; }, 0) / n;
        var sd = Math.sqrt(nums.reduce(function (a, c) { return a + (c - mean) * (c - mean); }, 0) / n);
        return { n: n, mean: mean, sd: sd };
    }

    var PlotCore = { exprOption: exprOption, exprBinning: exprBinning, exprSelect: exprSelect, EXPR_ATTRS: EXPR_ATTRS, nestedAt: nestedAt, dimsOf: dimsOf, dimLabels: dimLabels, selectAt: selectAt, isExpr: isExpr, exprText: exprText, exprSplit: exprSplit, exprTokens: exprTokens, exprCompile: exprCompile, exprNorm: exprNorm, exprResolve: exprResolve, exprEval: exprEval, normSn: normSn, pidAlternation: pidAlternation, pidRange: pidRange, toNum: toNum, fmt: fmt, histCounts: histCounts, isNumeric: isNumeric, catKey: catKey, topCats: topCats, meanSd: meanSd };
    if (typeof module !== "undefined" && module.exports) module.exports = PlotCore; else root.PlotCore = PlotCore;
})(typeof window !== "undefined" ? window : this);
