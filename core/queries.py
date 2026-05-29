"""Queries that span multiple models — kept out of views to make them reusable."""
from collections import Counter
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from .models import CableTest, FembTest, LArASIC


# Color tokens for progress charts. Cold matches the Sky · Daylight accent.
WARM_COLOR = "#f0b455"   # warm gold
COLD_COLOR = "#0369a1"   # sky-700 — matches --accent body blue


def _cumulate(values):
    s = 0
    out = []
    for v in values:
        s += v
        out.append(s)
    return out


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


def _continuous_days(start_date, end_date):
    """Inclusive list of YYYY-MM-DD strings between start_date and end_date."""
    out = []
    d = start_date
    while d <= end_date:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _ranges_for_series(series_specs):
    """Build the three range buckets ({labels, series}) from a list of
    (series_name, color, [datetime, ...]) specs.

    Each series contributes its own warm/cold/test-count timeline, but the
    labels are aligned across series within a range.
    """
    now = timezone.localtime()
    today = now.date()
    month_start = today - timedelta(days=29)
    quarter_start = today - timedelta(days=89)

    month_labels = _continuous_days(month_start, today)
    quarter_labels = _continuous_days(quarter_start, today)

    all_months_present = set()
    for _, _, dates in series_specs:
        for d in dates:
            if d is not None:
                all_months_present.add(f"{d.year:04d}-{d.month:02d}")
    all_labels = _continuous_months(all_months_present)

    def _build_range(labels, key_fn):
        out_series = []
        for name, color, dates in series_specs:
            counts_by_key = Counter(key_fn(d) for d in dates if d is not None)
            counts = [counts_by_key.get(lbl, 0) for lbl in labels]
            out_series.append({
                "name": name, "color": color,
                "counts": counts, "cumulative": _cumulate(counts),
            })
        return {"labels": labels, "series": out_series}

    return {
        "month": _build_range(month_labels, lambda d: d.date().isoformat()),
        "3month": _build_range(quarter_labels, lambda d: d.date().isoformat()),
        "all": _build_range(all_labels, lambda d: f"{d.year:04d}-{d.month:02d}"),
    }


def larasic_progress():
    warm_dates = list(LArASIC.objects.filter(
        warm_tested_at__isnull=False
    ).values_list("warm_tested_at", flat=True))
    cold_dates = list(LArASIC.objects.filter(
        cold_tested_at__isnull=False
    ).values_list("cold_tested_at", flat=True))
    return _ranges_for_series([
        ("Warm+Cold", WARM_COLOR, warm_dates),
        ("Cold", COLD_COLOR, cold_dates),
    ])


def _unique_units_progress(test_model, fk_field):
    """Count unique units (FEMBs / Cables) by the date of their latest test."""
    rows = test_model.objects.values(fk_field).annotate(last=Max("timestamp"))
    last_dates = [r["last"] for r in rows]
    return _ranges_for_series([
        ("Tested", COLD_COLOR, last_dates),
    ])


def femb_progress():
    return _unique_units_progress(FembTest, "femb")


def cable_progress():
    return _unique_units_progress(CableTest, "cable")
