"""Chart-data helpers specific to the explore mirror (ADR-0011).

Aggregations over the explore event tables into the month/3month/all range
shape the templates render. The generic chart plumbing (``_ranges_for_series``,
the palettes, ``chart_config``) stays shared in ``core.queries``; only these
two explore-specific aggregations live here.
"""

from django.db.models import Count

from core.queries import COLD_COLOR, TEST_TYPE_PALETTE, _ranges_for_series

from .models import HwdbComponentEvent, HwdbTestEvent

# Categorical component facets the breakdown panel charts (mirror-only).
COMPONENT_FACETS = (("status", "Status"), ("manufacturer", "Manufacturer"),
                    ("institution", "Institution"))


def component_type_progress(instance, part_type_id):
    """Tests-recorded-per-month for one component type from ``HwdbTestEvent``.

    One series per ``test_type_name`` (dynamic — read from the data, no
    hard-coded consortium knowledge), counted by HWDB ``created`` timestamp.
    Returns the month/3month/all ranges; no 1-year projection (the "recorded"
    timeline is often bulk-loaded, so a steady-rate projection would mislead).
    """
    rows = HwdbTestEvent.for_instance(instance).filter(part_type_id=part_type_id).values_list(
        "test_type_name", "created"
    )
    dates_by_type = {}
    for name, created in rows:
        dates_by_type.setdefault(name or "(unnamed)", []).append(created)
    series = [
        (name, TEST_TYPE_PALETTE[i % len(TEST_TYPE_PALETTE)], dates_by_type[name])
        for i, name in enumerate(sorted(dates_by_type))
    ]
    return _ranges_for_series(series)


def component_update_progress(instance, part_type_id):
    """Components-updated-per-month for one component type from
    ``HwdbComponentEvent``. A single series binned by each component's HWDB
    ``updated`` (last-modified) date — the activity view (status changes, QC
    uploads, etc. bump ``updated``), which tracks real work better than the
    mint date. Falls back to ``created`` for any row missing ``updated``.
    """
    dates = [
        u or c for u, c in
        HwdbComponentEvent.for_instance(instance).filter(part_type_id=part_type_id)
        .values_list("updated", "created")
        if (u or c) is not None
    ]
    series = [("Components updated", COLD_COLOR, dates)]
    return _ranges_for_series(series)


def component_breakdowns(instance, part_type_id):
    """Count of components per category value for each facet (status,
    manufacturer, institution), straight from ``HwdbComponentEvent`` — the
    mirror-only bar charts. Blank values fold into an "(unset)" bucket so a
    not-yet-resynced type still reads honestly. Returns one entry per facet that
    has any non-blank value; facets that are entirely blank are skipped."""
    out = []
    qs = HwdbComponentEvent.for_instance(instance).filter(part_type_id=part_type_id)
    for field, label in COMPONENT_FACETS:
        counts = (qs.values(field).annotate(n=Count("id")).order_by("-n"))
        rows = [{"value": c[field] or "(unset)", "n": c["n"]} for c in counts]
        if any(c[field] for c in counts):       # at least one real value
            out.append({"field": field, "label": label, "total": qs.count(),
                        "rows": rows})
    return out
