"""Queries that span multiple models — kept out of views to make them reusable.

The activity feed is the prime example: it unifies FembTest, FembRepair, and
CableTest into one timeline without a dedicated audit-log table.
"""
from collections import Counter
from django.db.models import Max
from django.urls import reverse

from .models import CableTest, FembRepair, FembTest, LArASIC


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


def _continuous_months(present):
    if not present:
        return []
    parsed = sorted(tuple(int(p) for p in m.split("-")) for m in present)
    start_y, start_m = parsed[0]
    end_y, end_m = parsed[-1]
    out = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def _bucket_by_month(dates):
    return Counter(f"{d.year:04d}-{d.month:02d}" for d in dates if d is not None)


def _cumulate(values):
    s = 0
    out = []
    for v in values:
        s += v
        out.append(s)
    return out


# Color tokens used by progress charts. Matches the standalone RTS report.
WARM_COLOR = "#f59e0b"   # amber
COLD_COLOR = "#1d4ed8"   # dark blue


def larasic_progress_monthly():
    """Monthly + cumulative LArASIC warm/cold RTS test counts."""
    warm_dates = LArASIC.objects.filter(
        warm_tested_at__isnull=False
    ).values_list("warm_tested_at", flat=True)
    cold_dates = LArASIC.objects.filter(
        cold_tested_at__isnull=False
    ).values_list("cold_tested_at", flat=True)
    warm_by_month = _bucket_by_month(warm_dates)
    cold_by_month = _bucket_by_month(cold_dates)
    months = _continuous_months(set(warm_by_month) | set(cold_by_month))
    warm = [warm_by_month.get(m, 0) for m in months]
    cold = [cold_by_month.get(m, 0) for m in months]
    return {
        "months": months,
        "series": [
            {"name": "Warm+Cold", "color": WARM_COLOR,
             "monthly": warm, "cumulative": _cumulate(warm)},
            {"name": "Cold", "color": COLD_COLOR,
             "monthly": cold, "cumulative": _cumulate(cold)},
        ],
    }


def _unique_units_progress(test_model, fk_field):
    """Generic: count unique units (FEMBs / Cables) that completed testing each month.

    A unit "completes" in the month of its latest test event. Returns the
    same shape as larasic_progress_monthly but with a single series.
    """
    rows = test_model.objects.values(fk_field).annotate(last=Max("timestamp"))
    last_dates = [r["last"] for r in rows]
    by_month = _bucket_by_month(last_dates)
    months = _continuous_months(set(by_month))
    counts = [by_month.get(m, 0) for m in months]
    return {
        "months": months,
        "series": [
            {"name": "Tested", "color": WARM_COLOR,
             "monthly": counts, "cumulative": _cumulate(counts)},
        ],
    }


def femb_progress_monthly():
    return _unique_units_progress(FembTest, "femb")


def cable_progress_monthly():
    return _unique_units_progress(CableTest, "cable")
