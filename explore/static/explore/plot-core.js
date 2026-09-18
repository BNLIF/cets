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
    var EXPR_PREC = { "||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, "<=": 4, ">": 4, ">=": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6 };
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
    // Tokens: numbers; identifiers = segments (bare, or "quoted" for other
    // characters) joined by ".", each with optional [i] / [] pins; a bare name
    // before "(" is a function; operators. Positions are 1-based in messages.
    function exprTokens(text) {
        var out = [], i = 0, n = text.length, OPS2 = ["&&", "||", "==", "!=", "<=", ">=", ">>"], OPS1 = "+-*/%^(),<>!";
        while (i < n) {
            var ch = text[i];
            if (/\s/.test(ch)) { i++; continue; }
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
            if (op === ">>") throw new Error("binning (>>) is not supported yet");
            out.push({ t: "op", v: op, at: i }); i += op.length;
        }
        return out;
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
            if (t.t === "num") { var v = t.v; return function () { return v; }; }
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
                return function (env) { return f.apply(null, args.map(function (a) { return a(env); })); };
            }
            if (isOp(t, "(")) { var e = expr(0); expectOp(")"); return e; }
            if (isOp(t, "-")) { var u = unary(); return function (env) { return -u(env); }; }
            if (isOp(t, "!")) { var u2 = unary(); return function (env) { return u2(env) ? 0 : 1; }; }
            throw new Error("unexpected “" + t.v + "” at " + (t.at + 1));
        }
        function unary() {
            var base = primary();
            if (isOp(peek(), "^")) { take(); var ex = unary(), b0 = base; base = function (env) { return Math.pow(b0(env), ex(env)); }; }
            return base;
        }
        function expr(minPrec) {
            var left = unary();
            for (;;) {
                var t = peek(); if (!t || t.t !== "op" || !Object.prototype.hasOwnProperty.call(EXPR_PREC, t.v) || EXPR_PREC[t.v] < minPrec) break;
                take();
                left = (function (op, l, r) { return function (env) {
                    var a = l(env), b = r(env);
                    switch (op) {
                        case "+": return a + b; case "-": return a - b; case "*": return a * b; case "/": return a / b; case "%": return a % b;
                        case "<": return a < b ? 1 : 0; case "<=": return a <= b ? 1 : 0; case ">": return a > b ? 1 : 0; case ">=": return a >= b ? 1 : 0;
                        case "==": return a === b ? 1 : 0; case "!=": return a !== b ? 1 : 0; case "&&": return a && b ? 1 : 0; default: return a || b ? 1 : 0;
                    }
                }; })(t.v, left, expr(EXPR_PREC[t.v] + 1));
            }
            return left;
        }
        var fn = expr(0);
        if (pos < toks.length) throw new Error("unexpected “" + toks[pos].v + "” at " + (toks[pos].at + 1));
        return { fn: fn, ids: ids };
    }
    // A name → one key. keys: [{ p, segs, dims() }]. The name's segments match
    // the key's trailing segments; case and space/underscore are ignored unless
    // that leaves several keys — then the exact spelling decides. Pins: [i] on
    // a segment that names a list level pins that level; on the leaf, the
    // levels in order from the first (ROOT: a[i][j]); [] skips one.
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
            var name = tail(k, i), named = dims.map(function (d, j) { return d.seg === name ? j : -1; }).filter(function (j) { return j >= 0; });
            var levels = named.length ? named : (i === n - 1 ? dims.map(function (d, j) { return j; }) : []);
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
    // nothing; a non-numeric or non-finite entry drops out. out.src keeps each
    // result's source position (tooltips, and X–Y pairing by entry).
    function exprEval(fn, arrays) {
        var n = Infinity;
        arrays.forEach(function (a) { if (!a.length) n = 0; else if (a.length > 1) n = Math.min(n, a.length); });
        if (n === Infinity) n = 1;
        var out = [], src = [], env = new Array(arrays.length);
        for (var j = 0; j < n; j++) {
            var ok = true;
            for (var k = 0; k < arrays.length; k++) { var v = exprNum(arrays[k].length > 1 ? arrays[k][j] : arrays[k][0]); if (v === null) { ok = false; break; } env[k] = v; }
            if (!ok) continue;
            var r = fn(env);
            if (typeof r === "number" && isFinite(r)) { out.push(r); src.push(j); }
        }
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
        nums.forEach(function (v) { var b = Math.min(nb - 1, Math.floor((v - lo) / w)); counts[b]++; });
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

    var PlotCore = { nestedAt: nestedAt, dimsOf: dimsOf, dimLabels: dimLabels, selectAt: selectAt, isExpr: isExpr, exprText: exprText, exprSplit: exprSplit, exprTokens: exprTokens, exprCompile: exprCompile, exprNorm: exprNorm, exprResolve: exprResolve, exprEval: exprEval, normSn: normSn, pidAlternation: pidAlternation, pidRange: pidRange, toNum: toNum, fmt: fmt, histCounts: histCounts, isNumeric: isNumeric, catKey: catKey, topCats: topCats, meanSd: meanSd };
    if (typeof module !== "undefined" && module.exports) module.exports = PlotCore; else root.PlotCore = PlotCore;
})(typeof window !== "undefined" ? window : this);
