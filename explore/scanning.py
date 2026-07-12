"""PID extraction for the phone-as-scanner flow (issue #68).

The regexes and precedence are the Dashboard's ``utils/scanner.py`` verbatim,
so both tools accept the same label formats: an HWDB component URL, a bare
PID, or a PID with a barcode-label suffix (e.g. ``…-07039-US186``).
"""

from __future__ import annotations

import re

from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing

# Matches core PID like Z00100300001-07039 (Project + 3 + 3 + 5 + "-" + 5)
_PID_RE = re.compile(r"\b([A-Z]\d{11}-\d{5})\b")

# Also allow suffixes after PID, e.g. Z...-07039-US186 (barcode label)
_PID_WITH_SUFFIX_RE = re.compile(r"\b([A-Z]\d{11}-\d{5})(?:-[A-Za-z0-9]+)*\b")

# https://dbweb0.fnal.gov/cdbdev/view/component/<PID>
# https://dbweb0.fnal.gov/cdb/view/component/<PID>
_HWDB_URL_RE = re.compile(
    r"https?://[^/\s]+/(?:cdbdev|cdb)/view/component/([A-Z]\d{11}-\d{5})",
    re.IGNORECASE)


def extract_pid(text: str) -> str:
    """Extract a PID from an HWDB URL, a bare PID, or a PID with a label
    suffix. Returns "" if not found."""
    t = (text or "").strip()
    if not t:
        return ""
    m = _HWDB_URL_RE.search(t)
    if m:
        return (m.group(1) or "").strip()
    m = _PID_RE.search(t)
    if m:
        return (m.group(1) or "").strip()
    m = _PID_WITH_SUFFIX_RE.search(t)
    if m:
        return (m.group(1) or "").strip()
    return ""


def qr_svg(text: str, size: int = 160) -> str:
    """The scan page's URL as an inline-SVG QR code (renderPM would need a
    cairo backend; SVG is pure python). Returns just the ``<svg>…`` element,
    ready to drop into a template."""
    widget = qr.QrCodeWidget(text, barBorder=1)
    b = widget.getBounds()
    d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0,
                                       size / (b[3] - b[1]), 0, 0])
    d.add(widget)
    svg = renderSVG.drawToString(d)
    return svg[svg.index("<svg"):]
