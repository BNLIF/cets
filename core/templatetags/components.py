"""Reusable visual primitives, rendered as inclusion tags.

Each tag pairs with a partial under `core/templates/core/components/`.
Specs come from `.idea/design/handoff_1/`.
"""
from django import template

register = template.Library()


@register.inclusion_tag("core/components/pill.html")
def pill(status, label=None):
    """Status pill: lowercase mono text + colored dot.

    Known statuses (drive both color + dot pulsing for `testing`):
    pass · ready · fail · testing · new · archived · retired. Unknown
    values render as a neutral pill so unexpected statuses still display.
    """
    return {"status": status or "", "label": label or status or ""}


@register.inclusion_tag("core/components/position_tag.html")
def position_tag(pos):
    """FEMB chip-position label: 6px dot + mono text.

    Front positions (F1–F4) get the accent color, back (B1–B4) get muted.
    """
    pos = pos or ""
    return {
        "pos": pos,
        "is_front": pos.startswith("F"),
        "empty": not pos,
    }


@register.inclusion_tag("core/components/type_badge.html")
def type_badge(test_type):
    """Small mono badge for test types. QC = accent, anything else neutral."""
    return {"type": test_type or "", "is_qc": (test_type or "").upper() == "QC"}


@register.inclusion_tag("core/components/temp_badge.html")
def temp_badge(temp):
    """Temperature chip: glyph square + label + Kelvin annotation.

    LN = liquid nitrogen (cold, 77 K), anything else = room temperature
    (warm, 295 K). The current data uses LN/RT but we tolerate variations.
    """
    temp = (temp or "").upper()
    is_cold = temp == "LN"
    return {
        "temp": temp,
        "is_cold": is_cold,
        "kelvin": "77 K" if is_cold else "295 K",
    }


@register.inclusion_tag("core/components/crumbs.html")
def crumbs(*items):
    """Breadcrumbs. Pass alternating label/href; last item with no href is the current page.

    Example: `{% crumbs "CETS" home_url "FEMB" femb_url "IO-1865-1L/00039" %}`
    """
    pairs = []
    i = 0
    while i < len(items):
        label = items[i]
        href = items[i + 1] if i + 1 < len(items) and not _looks_like_label(items[i + 1]) else None
        pairs.append({"label": label, "href": href})
        i += 2 if href else 1
    return {"items": pairs}


def _looks_like_label(s):
    """Heuristic so we can pass a final bare label without a trailing href.

    A real URL starts with `/` or `http`; anything else is treated as the
    next breadcrumb label.
    """
    if not isinstance(s, str):
        return True
    return not (s.startswith("/") or s.startswith("http"))


@register.inclusion_tag("core/components/info_card.html")
def info_card(cells):
    """3-cell info card with mono uppercase labels and vertical dividers.

    `cells` is a list of dicts: `{"label": "VERSION", "value": "...", "is_pill": False}`.
    When `is_pill` is true, `value` is a status string and renders via the pill component.
    """
    return {"cells": cells}


@register.inclusion_tag("core/components/repair_card.html")
def repair_card(repair):
    """A single FembRepair entry: meta head + what-was-fixed + removed/installed tables.

    Expects a FembRepair instance with prefetched removed/installed_{larasics,coldadcs,coldatas}.
    """
    removed = (
        [("LArASIC", c) for c in repair.removed_larasics.all()]
        + [("ColdADC", c) for c in repair.removed_coldadcs.all()]
        + [("COLDATA", c) for c in repair.removed_coldatas.all()]
    )
    installed = (
        [("LArASIC", c) for c in repair.installed_larasics.all()]
        + [("ColdADC", c) for c in repair.installed_coldadcs.all()]
        + [("COLDATA", c) for c in repair.installed_coldatas.all()]
    )
    return {"repair": repair, "removed": removed, "installed": installed}
