/* Cable-end diagram (#72): the cable body in the middle, its ENDs fanning out
   left/right (like Hajime's cabling slides), one dot per connector. Reads the
   ends from the #cable-ends-data json_script ([{name, connectors}, …]) and
   the hub label from #cable-diagram's data-label. Shared by the part page
   (live detail) and the component-type leaf page (mirror). */
(function () {
  var host = document.getElementById("cable-diagram");
  var data = document.getElementById("cable-ends-data");
  if (!host || !data) return;
  var ends = JSON.parse(data.textContent) || [];
  if (!ends.length) return;
  // Occupancy (item pages only): the item's connected slots as "END:n"
  // strings. Absent (type page) → no occupancy info, draw all dots solid.
  var usedEl = document.getElementById("cable-used-data");
  var used = usedEl ? JSON.parse(usedEl.textContent).reduce(
    function (s, k) { s[k] = true; return s; }, {}) : null;
  function esc(s) { var d = document.createElement("div"); d.textContent = (s == null ? "" : s); return d.innerHTML; }

  function meta(e) {
    var n = e.connectors, inUse = 0;
    for (var i = 1; i <= n; i++) if (used && used[e.name + ":" + i]) inUse++;
    return used ? inUse + " / " + n + " in use"
                : n + " connector" + (n === 1 ? "" : "s");
  }

  // Past ~12 ends the fan-out becomes a very tall spider — fall back to a
  // compact chip grid (per Hajime: a list is fine when the picture is hard).
  if (ends.length > 12) {
    host.innerHTML = "<div class='cbl-end-grid'>" + ends.map(function (e) {
      return "<div class='cbl-end'><span class='cbl-end-name' title='" + esc(e.name) +
             "'>" + esc(e.name) + "</span><span class='cbl-end-meta'>" +
             meta(e) + "</span></div>";
    }).join("") + "</div>";
    return;
  }

  var W = 720, rowH = 50, boxW = 216, boxH = 38, pad = 10;
  var left = ends.slice(0, Math.ceil(ends.length / 2)), right = ends.slice(left.length);
  var rows = Math.max(left.length, right.length, 1);
  var H = rows * rowH + 2 * pad;
  var hubW = 176, hubH = 34, hubX = (W - hubW) / 2, midY = H / 2;
  var parts = [];

  function endBox(e, x, y) {
    var n = e.connectors, name = e.name.length > 26 ? e.name.slice(0, 25) + "…" : e.name;
    parts.push("<rect x='" + x + "' y='" + y + "' width='" + boxW + "' height='" + boxH +
               "' rx='6' style='fill:var(--surface);stroke:var(--rule-hard)'/>");
    parts.push("<text x='" + (x + 9) + "' y='" + (y + 15) + "' font-size='11' font-weight='600' style='fill:var(--ink)'>" + esc(name) + "</text>");
    var dots = Math.min(n, 12), dx = x + 12;
    for (var i = 0; i < dots; i++) {
      // Connectors are numbered 1..n; hollow = free, solid = connected.
      var solid = !used || used[e.name + ":" + (i + 1)];
      parts.push("<circle cx='" + (dx + i * 9) + "' cy='" + (y + 28) + "' r='2.6' style='" +
                 (solid ? "fill:var(--accent-ink)"
                        : "fill:none;stroke:var(--faint);stroke-width:1") + "'/>");
    }
    parts.push("<text x='" + (dx + dots * 9 + 4) + "' y='" + (y + 31) + "' font-size='10' style='fill:var(--faint)'>" +
               meta(e) + "</text>");
  }

  function side(list, isLeft) {
    var x = isLeft ? pad : W - pad - boxW;
    var top = pad + ((rows - list.length) * rowH) / 2;
    list.forEach(function (e, i) {
      var y = top + i * rowH + (rowH - boxH) / 2, yc = y + boxH / 2;
      var x1 = isLeft ? x + boxW : hubX + hubW, x2 = isLeft ? hubX : x;
      var w = 1.5 + 0.5 * Math.min(e.connectors - 1, 6);
      parts.push("<path d='M" + x1 + " " + yc + " C " + (x1 + 44) + " " + yc + ", " +
                 (x2 - 44) + " " + midY + ", " + x2 + " " + midY +
                 "' style='fill:none;stroke:var(--rule-hard)' stroke-width='" + w + "'/>");
      endBox(e, x, y);
    });
  }

  side(left, true);
  side(right, false);
  parts.push("<rect x='" + hubX + "' y='" + (midY - hubH / 2) + "' width='" + hubW + "' height='" + hubH +
             "' rx='6' style='fill:var(--surface);stroke:var(--accent-ink)'/>");
  parts.push("<text x='" + (W / 2) + "' y='" + (midY + 4) + "' text-anchor='middle' font-size='11' " +
             "style='fill:var(--accent-ink);font-family:var(--font-mono)'>" + esc(host.dataset.label) + "</text>");
  host.innerHTML = "<svg viewBox='0 0 " + W + " " + H + "' role='img' " +
                   "aria-label='Cable ends and connectors'>" + parts.join("") + "</svg>";
})();
