"""Reusable visual primitives, rendered as inclusion tags.

Each tag pairs with a partial under `core/templates/core/components/`.
Specs come from `.idea/design/handoff_1/`.
"""
from datetime import timedelta

from django import template
from django.utils import timezone

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


@register.inclusion_tag("core/components/stat_card.html")
def stat_card(name, description, numbers, this_month=None, href=None):
    """Family stat card for the dashboard 4-up row.

    `numbers` is a list of {"value", "label", "accent": bool, "cold": bool}.
    `cold` numbers use the LN blue treatment with a ❄ glyph; `accent` uses
    the accent color (e.g. the QC tests count on the FEMB card).
    """
    return {
        "name": name,
        "description": description,
        "numbers": numbers,
        "this_month": this_month,
        "href": href,
    }


@register.inclusion_tag("core/components/activity_panel.html")
def activity_panel(items, compact=False):
    """Recent-activity panel: title + list of activity rows.

    `items` is the output of queries.recent_activity(). `compact=True`
    hides the per-row note (used by list-page sidebars per the spec).
    """
    now = timezone.now()
    enriched = [
        {**a, "relative": _relative_time(now - a["timestamp"])}
        for a in items
    ]
    return {"items": enriched, "compact": compact}


@register.inclusion_tag("core/components/sortable_th.html", takes_context=True)
def sortable_th(context, key, label, current_sort, current_dir, width=None):
    """Sortable table header cell. Clicking flips dir; switching key starts at desc.

    Renders as a link that points at the current URL with sort/dir params updated.
    Active key shows the ↑/↓ indicator. Designed to be used inside the `_femb_list_fragment.html`
    pattern — the link's hx-* attributes pull the fragment in place.
    """
    is_active = key == current_sort
    if is_active:
        next_dir = "desc" if current_dir == "asc" else "asc"
    else:
        next_dir = "desc"
    arrow = "↑" if is_active and current_dir == "asc" else "↓" if is_active else ""
    request = context["request"]
    params = request.GET.copy()
    params["sort"] = key
    params["dir"] = next_dir
    params["page"] = "1"
    href = f"{request.path}?{params.urlencode()}"
    return {
        "key": key,
        "label": label,
        "href": href,
        "is_active": is_active,
        "arrow": arrow,
        "width": width,
    }


@register.inclusion_tag("core/components/filter_chip.html", takes_context=True)
def filter_chip(context, label, param, value=None, options=None):
    """A filter chip. `options` is a list of dicts {value, label} for a dropdown.

    Active when the URL already has `?<param>=<value>`. Clicking an option
    updates the URL and resets page=1. Clicking × on an active chip clears
    the param.
    """
    request = context["request"]
    current = request.GET.get(param, "")

    def url_with(p, v):
        params = request.GET.copy()
        if v:
            params[p] = v
        else:
            params.pop(p, None)
        params["page"] = "1"
        qs = params.urlencode()
        return f"{request.path}?{qs}" if qs else request.path

    return {
        "label": label,
        "param": param,
        "current": current,
        "active": bool(current),
        "options": [
            {"value": o["value"], "label": o["label"], "href": url_with(param, o["value"]), "is_current": o["value"] == current}
            for o in (options or [])
        ],
        "clear_href": url_with(param, ""),
    }


@register.inclusion_tag("core/components/date_range_chip.html", takes_context=True)
def date_range_chip(context, since, until, label="Date range"):
    """Date range filter chip with two <input type="date"> fields.

    URL params: ?since=YYYY-MM-DD&until=YYYY-MM-DD. The chip renders as
    an active pill (with × clear) when either bound is set, or a
    <details> dropdown containing a small form when neither is set.
    The dropdown's form fires hx-get to the current path so the swap
    target picks it up.
    """
    request = context["request"]
    active = bool(since or until)

    params = request.GET.copy()
    params.pop("since", None)
    params.pop("until", None)
    params["page"] = "1"
    clear_qs = params.urlencode()
    clear_href = f"{request.path}?{clear_qs}" if clear_qs else request.path

    if since and until:
        display = f"{since} → {until}"
    elif since:
        display = f"since {since}"
    else:
        display = f"until {until}" if until else ""

    return {
        "label": label,
        "active": active,
        "since": since,
        "until": until,
        "display": display,
        "clear_href": clear_href,
        "form_path": request.path,
    }


@register.inclusion_tag("core/components/pagination.html", takes_context=True)
def pagination(context, page_obj, page_size):
    """Mono pager + 'Showing X–Y of Z' counter.

    Buttons preserve the current querystring and only flip `page`. Used as
    HTMX targets via the surrounding fragment's `hx-*` attributes.
    """
    request = context["request"]
    total = page_obj.paginator.count
    num_pages = page_obj.paginator.num_pages
    page_num = page_obj.number
    start = (page_num - 1) * page_size + 1 if total else 0
    end = min(page_num * page_size, total)

    def page_url(n):
        params = request.GET.copy()
        params["page"] = str(n)
        return f"{request.path}?{params.urlencode()}"

    return {
        "start": start,
        "end": end,
        "total": total,
        "num_pages": num_pages,
        "page_num": page_num,
        "has_prev": page_obj.has_previous(),
        "has_next": page_obj.has_next(),
        "first_url": page_url(1),
        "prev_url": page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "next_url": page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
        "last_url": page_url(num_pages),
    }


def _relative_time(delta):
    """Compact relative-time string in the mono style the design uses."""
    if delta < timedelta(0):
        return "just now"
    sec = int(delta.total_seconds())
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    if sec < 86400:
        return f"{sec // 3600}h"
    if sec < 86400 * 7:
        return f"{sec // 86400}d"
    if sec < 86400 * 30:
        return f"{sec // (86400 * 7)}w"
    if sec < 86400 * 365:
        return f"{sec // (86400 * 30)}mo"
    return f"{sec // (86400 * 365)}y"
