"""Chart-data helpers specific to the explore mirror (ADR-0011).

Aggregations over the explore event tables into the month/3month/all range
shape the templates render. The generic chart plumbing (``_ranges_for_series``,
the palettes, ``chart_config``) stays shared in ``core.queries``; only these
two explore-specific aggregations live here.
"""

from core.queries import COLD_COLOR, TEST_TYPE_PALETTE, _ranges_for_series

from .models import HwdbComponentEvent, HwdbTestEvent


def component_type_progress(part_type_id):
    """Tests-recorded-per-month for one component type from ``HwdbTestEvent``.

    One series per ``test_type_name`` (dynamic — read from the data, no
    hard-coded consortium knowledge), counted by HWDB ``created`` timestamp.
    Returns the month/3month/all ranges; no 1-year projection (the "recorded"
    timeline is often bulk-loaded, so a steady-rate projection would mislead).
    """
    rows = HwdbTestEvent.objects.filter(part_type_id=part_type_id).values_list(
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


def component_update_progress(part_type_id):
    """Components-updated-per-month for one component type from
    ``HwdbComponentEvent``. A single series binned by each component's HWDB
    ``updated`` (last-modified) date — the activity view (status changes, QC
    uploads, etc. bump ``updated``), which tracks real work better than the
    mint date. Falls back to ``created`` for any row missing ``updated``.
    """
    dates = [
        u or c for u, c in
        HwdbComponentEvent.objects.filter(part_type_id=part_type_id)
        .values_list("updated", "created")
        if (u or c) is not None
    ]
    series = [("Components updated", COLD_COLOR, dates)]
    return _ranges_for_series(series)
