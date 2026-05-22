"""Queries that span multiple models — kept out of views to make them reusable.

The activity feed is the prime example: it unifies FembTest, FembRepair, and
CableTest into one timeline without a dedicated audit-log table.
"""
from datetime import timedelta
from django.db.models import Count, Max
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from .models import CableTest, FembRepair, FembTest


# Ordered shortest → longest so smart-default picks the tightest window
# containing data. "all" is a sentinel resolved to the range from the
# earliest test to today.
CHART_WINDOWS = [
    ("7d", 7),
    ("30d", 30),
    ("90d", 90),
    ("1y", 365),
    ("all", None),
]


def chart_window_days(window_key):
    """Resolve a window key (e.g. '30d', 'all') to a number of days.

    For 'all', this is the span from the earliest test to today (with a
    floor of 30 days so the chart isn't degenerate when data is sparse).
    Unknown keys fall back to 90.
    """
    by_key = dict(CHART_WINDOWS)
    if window_key not in by_key:
        return 90
    days = by_key[window_key]
    if days is not None:
        return days
    earliest_femb = FembTest.objects.order_by("timestamp").values_list("timestamp", flat=True).first()
    earliest_cable = CableTest.objects.order_by("timestamp").values_list("timestamp", flat=True).first()
    candidates = [t for t in (earliest_femb, earliest_cable) if t]
    if not candidates:
        return 30
    span = (timezone.now() - min(candidates)).days + 1
    return max(30, span)


def default_chart_window():
    """Smallest window in CHART_WINDOWS containing the most recent test.

    Falls back to '90d' if there are no tests anywhere.
    """
    latest_femb = FembTest.objects.aggregate(m=Max("timestamp"))["m"]
    latest_cable = CableTest.objects.aggregate(m=Max("timestamp"))["m"]
    candidates = [t for t in (latest_femb, latest_cable) if t]
    if not candidates:
        return "90d"
    age_days = (timezone.now() - max(candidates)).days
    for key, days in CHART_WINDOWS:
        if days is None or age_days <= days:
            return key
    return "all"


def _kind_from_status(status):
    """Map a test's free-text status to one of the four activity icon kinds.

    The status field is sometimes empty in real data, so default to 'test'.
    """
    s = (status or "").strip().lower()
    if s in {"pass", "passed", "ok", "good"}:
        return "pass"
    if s in {"fail", "failed", "bad", "error"}:
        return "fail"
    return "test"


def recent_activity(limit=20, target_prefix=None):
    """Unified activity timeline across FembTest, FembRepair, and CableTest.

    Returns a list of dicts (newest first) with this shape:
        {
            "verb":          "Test completed" | "Test passed" | ... ,
            "target_family": "FEMB" | "Cable",
            "target_label":  "FEMB IO-1865-1L/00039" | "Cable 01234",
            "target_url":    "/femb/IO-1865-1L/00039/",
            "timestamp":     datetime,
            "kind":          "pass" | "fail" | "test" | "new",
            "note":          str | None,
        }

    `target_prefix` (case-insensitive) filters by `target_family` — pass
    "FEMB" to get only FEMB-targeted activity for the FEMB list sidebar.
    """
    items = []

    fetch = limit * 3  # pull extra so the merged window still fills `limit`
    femb_test_qs = FembTest.objects.select_related("femb").order_by("-timestamp")[:fetch]
    for t in femb_test_qs:
        kind = _kind_from_status(t.status)
        verb = {"pass": "Test passed", "fail": "Test failed"}.get(kind, "Test completed")
        items.append({
            "verb": verb,
            "target_family": "FEMB",
            "target_label": f"FEMB {t.femb.version}/{t.femb.serial_number}",
            "target_url": reverse("femb_detail", args=[t.femb.version, t.femb.serial_number]),
            "timestamp": t.timestamp,
            "kind": kind,
            "note": f"{t.test_type} · {t.test_env}" + (f" · {t.site}" if t.site else ""),
        })

    repair_qs = FembRepair.objects.select_related("femb").order_by("-date")[:fetch]
    for r in repair_qs:
        items.append({
            "verb": f"Repair #{r.iteration_number} logged",
            "target_family": "FEMB",
            "target_label": f"FEMB {r.femb.version}/{r.femb.serial_number}",
            "target_url": reverse("femb_detail", args=[r.femb.version, r.femb.serial_number]),
            "timestamp": r.date,
            "kind": "new",
            "note": r.what_was_fixed or None,
        })

    cable_test_qs = CableTest.objects.select_related("cable").order_by("-timestamp")[:fetch]
    for t in cable_test_qs:
        kind = _kind_from_status(t.status)
        verb = {"pass": "Test passed", "fail": "Test failed"}.get(kind, "Test completed")
        items.append({
            "verb": verb,
            "target_family": "Cable",
            "target_label": f"Cable {t.cable.serial_number}",
            "target_url": reverse("cable_detail", args=[t.cable.serial_number]),
            "timestamp": t.timestamp,
            "kind": kind,
            "note": f"{t.test_type} · {t.test_env}" + (f" · {t.site}" if t.site else ""),
        })

    if target_prefix:
        prefix = target_prefix.lower()
        items = [a for a in items if a["target_family"].lower().startswith(prefix)]

    items.sort(key=lambda a: a["timestamp"], reverse=True)
    return items[:limit]


def tests_per_day(days=90):
    """Counts of FEMB + Cable tests per day for the last `days` days.

    Returns a list of length `days`, oldest-first, each entry:
        {"date": date, "count": int}
    Days with zero tests are included so the chart has stable x positions.
    """
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)

    femb_counts = (
        FembTest.objects.filter(timestamp__date__gte=start)
        .annotate(d=TruncDate("timestamp"))
        .values("d").annotate(c=Count("id"))
    )
    cable_counts = (
        CableTest.objects.filter(timestamp__date__gte=start)
        .annotate(d=TruncDate("timestamp"))
        .values("d").annotate(c=Count("id"))
    )

    by_date = {}
    for row in femb_counts:
        by_date[row["d"]] = by_date.get(row["d"], 0) + row["c"]
    for row in cable_counts:
        by_date[row["d"]] = by_date.get(row["d"], 0) + row["c"]

    return [
        {"date": start + timedelta(days=i), "count": by_date.get(start + timedelta(days=i), 0)}
        for i in range(days)
    ]
