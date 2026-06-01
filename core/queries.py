"""Queries that span multiple models — kept out of views to make them reusable."""
from calendar import monthrange
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


def _project_1year(series_specs):
    """3 past months (actual) + 12 future months (projected at the last-90-day
    daily rate), monthly bins.

    Each series projects independently from its own 90-day rate. `projection_start`
    is the index of the first projected month — the JS uses it to dim the
    projected bars and dash the projected line segment.
    """
    now = timezone.localtime()
    today = now.date()
    past_start = today - timedelta(days=89)

    # Monthly labels: from past_start's month through (today + 365 days)'s month.
    end = today + timedelta(days=365)
    labels = []
    y, m = past_start.year, past_start.month
    while (y, m) <= (end.year, end.month):
        labels.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1

    # Projected months are everything strictly after the current month.
    current_key = f"{today.year:04d}-{today.month:02d}"
    projection_start = labels.index(current_key) + 1 if current_key in labels else len(labels)

    first_y, first_m = int(labels[0][:4]), int(labels[0][5:7])

    out_series = []
    for name, color, dates in series_specs:
        counts_by_key = Counter(
            f"{d.year:04d}-{d.month:02d}" for d in dates if d is not None
        )
        # Daily rate = count of tests with timestamps in the last 90 days / 90.
        last_90 = sum(
            1 for d in dates
            if d is not None and d.date() >= past_start and d.date() <= today
        )
        daily_rate = last_90 / 90.0

        # Baseline cumulative: every test stamped BEFORE the first label's month.
        baseline = sum(
            1 for d in dates
            if d is not None and (d.year, d.month) < (first_y, first_m)
        )

        counts = []
        for i, lbl in enumerate(labels):
            if i < projection_start:
                counts.append(counts_by_key.get(lbl, 0))
            else:
                ly, lm = int(lbl[:4]), int(lbl[5:7])
                days_in_month = monthrange(ly, lm)[1]
                counts.append(round(daily_rate * days_in_month))

        cumulative = []
        running = baseline
        for c in counts:
            running += c
            cumulative.append(running)

        out_series.append({
            "name": name, "color": color,
            "counts": counts, "cumulative": cumulative,
        })

    return {
        "labels": labels,
        "series": out_series,
        "projection_start": projection_start,
    }


def _to_rgba(hex_color, a):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


def _datasets(series, projection_start=None):
    bar_ds, line_ds = [], []
    for s in series:
        color = s["color"]
        if projection_start is not None:
            bg = [
                _to_rgba(color, 0.85 if i < projection_start else 0.30)
                for i in range(len(s["counts"]))
            ]
        else:
            bg = _to_rgba(color, 0.85)
        bar_ds.append({
            "label": s["name"], "data": s["counts"],
            "backgroundColor": bg,
        })
        line_ds.append({
            "label": s["name"], "data": s["cumulative"],
            "borderColor": color, "backgroundColor": _to_rgba(color, 0.18),
            "tension": 0.2, "fill": True, "pointRadius": 0,
        })
    return bar_ds, line_ds


def chart_config(slug, name, href, ranges):
    """Wrap a ``_ranges_for_series`` result into the shape ``core/index.html``
    and ``hwdb/dashboard.html`` expect for Chart.js rendering.
    """
    out_ranges = {}
    has_data = False
    for key, r in ranges.items():
        bar_ds, line_ds = _datasets(r["series"], r.get("projection_start"))
        out_ranges[key] = {
            "labels": r["labels"],
            "bar_datasets": bar_ds,
            "line_datasets": line_ds,
            "projection_start": r.get("projection_start"),
        }
        if any(any(d["data"]) for d in bar_ds):
            has_data = True
    return {
        "slug": slug, "name": name, "href": href,
        "ranges": out_ranges,
        "empty": not has_data,
        "show_projection": "1year" in ranges,
    }


def hwdb_family_progress(family):
    """Progress for one family from the ``HwdbChip`` mirror table.

    Two series — RT-tested (warm) and LN-tested (cold) — counted by their
    latest test datetime per env, with the same range bucketing as the
    core dashboard. Includes the 1-year projection range so the chart
    matches LArASIC's shape.
    """
    from hwdb.models import HwdbChip
    rows = HwdbChip.objects.filter(family=family).values_list(
        "latest_rt_test_at", "latest_ln_test_at"
    )
    rt_dates = [a for a, _ in rows if a is not None]
    ln_dates = [b for _, b in rows if b is not None]
    series = [
        ("RT-tested", WARM_COLOR, rt_dates),
        ("LN-tested", COLD_COLOR, ln_dates),
    ]
    out = _ranges_for_series(series)
    out["1year"] = _project_1year(series)
    return out


def larasic_progress():
    warm_dates = list(LArASIC.objects.filter(
        warm_tested_at__isnull=False
    ).values_list("warm_tested_at", flat=True))
    cold_dates = list(LArASIC.objects.filter(
        cold_tested_at__isnull=False
    ).values_list("cold_tested_at", flat=True))
    series = [
        ("Warm+Cold", WARM_COLOR, warm_dates),
        ("Cold", COLD_COLOR, cold_dates),
    ]
    out = _ranges_for_series(series)
    out["1year"] = _project_1year(series)
    return out


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
