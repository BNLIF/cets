import re
from datetime import datetime, timedelta
from pathlib import Path

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseNotFound
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from .models import LArASIC, ColdADC, COLDATA, FEMB, FembRepair, FembTest, CABLE, CableTest
from . import queries
from decouple import config
from django.db.models import Subquery, OuterRef, Q, Count, Max
from rest_framework.permissions import IsAdminUser, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from .serializers import FEMBSerializer
from rest_framework import viewsets

RTS_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.csv$")


def _render_paginated_list(request, queryset, template, page_id, default_sort, default_order="asc", per_page=100):
    """
    Apply sort + paginate + render to a queryset. Caller is responsible for
    building the queryset (including any annotations and search filters)
    and for handling search-by-SN redirects to detail pages.
    """
    sort = request.GET.get("sort", default_sort)
    order = request.GET.get("order", default_order)
    total_count = queryset.count()

    sort_field = f"-{sort}" if order == "desc" else sort
    page_obj = Paginator(queryset.order_by(sort_field), per_page).get_page(request.GET.get("page"))

    return render(request, template, {
        "page_obj": page_obj,
        "page": page_id,
        "sort": sort,
        "order": order,
        "total_count": total_count,
        "search_query": request.GET.get("q", ""),
        "search_by": request.GET.get("by", "sn"),
    })


def home(request):
    now = timezone.now()
    month_ago = now - timedelta(days=30)

    femb_qs = FEMB.objects.all()
    larasic_qs = LArASIC.objects.all()
    coldadc_qs = ColdADC.objects.all()
    coldata_qs = COLDATA.objects.all()
    cable_qs = CABLE.objects.all()

    femb_total = femb_qs.count()
    qc_run = FembTest.objects.count()
    larasic_warm = larasic_qs.filter(warm_tested_at__isnull=False).count()
    larasic_cold = larasic_qs.filter(cold_tested_at__isnull=False).count()
    # ColdADC / COLDATA have no per-chip test dates yet; keep the FEMB-LN
    # derivation until a future per-chip ingest replaces it.
    coldadc_cold = coldadc_qs.filter(femb__fembtest__test_env="LN").distinct().count()
    coldata_cold = coldata_qs.filter(femb__fembtest__test_env="LN").distinct().count()

    stat_cards = [
        {
            "name": "FEMB", "description": "Frontend Motherboard",
            "href": reverse("femb"),
            "this_month": FEMB.objects.filter(last_update__gte=month_ago).count(),
            "numbers": [
                {"value": femb_total, "label": "FEMBs tracked"},
                {"value": qc_run, "label": "QC tests run", "accent": True},
            ],
        },
        {
            "name": "LArASIC", "description": "16-ch front-end ASIC",
            "href": reverse("larasic"),
            "this_month": larasic_qs.filter(warm_tested_at__gte=month_ago).count(),
            "numbers": [
                {"value": larasic_warm, "label": "RTS warm-tested"},
                {"value": larasic_cold, "label": "RTS cold-tested", "cold": True},
            ],
        },
        {
            "name": "ColdADC", "description": "12-bit cold ADC",
            "href": reverse("coldadc"),
            "this_month": coldadc_qs.filter(last_update__gte=month_ago).count(),
            "numbers": [
                {"value": coldadc_qs.count(), "label": "Total tracked"},
                {"value": coldadc_cold, "label": "Cold tested · LN", "cold": True},
            ],
        },
        {
            "name": "COLDATA", "description": "Serializer / control",
            "href": reverse("coldata"),
            "this_month": coldata_qs.filter(last_update__gte=month_ago).count(),
            "numbers": [
                {"value": coldata_qs.count(), "label": "Total tracked"},
                {"value": coldata_cold, "label": "Cold tested · LN", "cold": True},
            ],
        },
    ]

    def _to_rgba(hex_color, a):
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{a})"

    def _datasets(series):
        bar_ds, line_ds = [], []
        for s in series:
            color = s["color"]
            bar_ds.append({
                "label": s["name"], "data": s["counts"],
                "backgroundColor": _to_rgba(color, 0.85),
            })
            line_ds.append({
                "label": s["name"], "data": s["cumulative"],
                "borderColor": color, "backgroundColor": _to_rgba(color, 0.18),
                "tension": 0.2, "fill": True, "pointRadius": 0,
            })
        return bar_ds, line_ds

    def _chart_config(slug, name, href, ranges):
        out_ranges = {}
        has_data = False
        for key, r in ranges.items():
            bar_ds, line_ds = _datasets(r["series"])
            out_ranges[key] = {
                "labels": r["labels"],
                "bar_datasets": bar_ds,
                "line_datasets": line_ds,
            }
            if any(any(d["data"]) for d in bar_ds):
                has_data = True
        return {
            "slug": slug, "name": name, "href": href,
            "ranges": out_ranges,
            "empty": not has_data,
        }

    progress_charts = [
        _chart_config("larasic", "LArASIC", reverse("larasic"), queries.larasic_progress()),
        _chart_config("femb", "FEMB", reverse("femb"), queries.femb_progress()),
        _chart_config("cable", "Cable", reverse("cable"), queries.cable_progress()),
    ]

    context = {
        "page": "home",
        "stat_cards": stat_cards,
        "progress_charts": progress_charts,
    }
    return render(request, "core/index.html", context)


def reference(request):
    """Catch-all reference page: planning targets, diagrams, datasheets, documents.

    Lives here so the dashboard can stay focused; the old home page content
    moved here when the dashboard was redesigned.
    """
    return render(request, "core/reference.html", {"page": "reference"})


_TYPEAHEAD_PER_FAMILY = 6


def search_typeahead(request):
    """HTMX live-search across all component families.

    Empty `q` returns an empty fragment so the dropdown stays hidden.
    Otherwise: substring-match `serial_number` on FEMB, LArASIC, ColdADC,
    COLDATA, CABLE — up to ~6 per family. The dropdown groups results by
    family and each row links to that detail page.
    """
    q = (request.GET.get("q") or "").strip()
    if not q:
        return render(request, "core/_search_typeahead.html", {"groups": [], "q": q})

    n = _TYPEAHEAD_PER_FAMILY
    groups = [
        {
            "family": "FEMB",
            "items": [
                {"serial": f"{f.version}/{f.serial_number}",
                 "url": reverse("femb_detail", args=[f.version, f.serial_number])}
                for f in FEMB.objects.filter(
                    Q(serial_number__icontains=q) | Q(version__icontains=q)
                ).order_by("version", "serial_number")[:n]
            ],
        },
        {
            "family": "LArASIC",
            "items": [
                {"serial": c.serial_number,
                 "url": reverse("larasic_detail", args=[c.serial_number])}
                for c in LArASIC.objects.filter(serial_number__icontains=q).order_by("serial_number")[:n]
            ],
        },
        {
            "family": "ColdADC",
            "items": [
                {"serial": c.serial_number,
                 "url": reverse("coldadc_detail", args=[c.serial_number])}
                for c in ColdADC.objects.filter(serial_number__icontains=q).order_by("serial_number")[:n]
            ],
        },
        {
            "family": "COLDATA",
            "items": [
                {"serial": c.serial_number,
                 "url": reverse("coldata_detail", args=[c.serial_number])}
                for c in COLDATA.objects.filter(serial_number__icontains=q).order_by("serial_number")[:n]
            ],
        },
        {
            "family": "Cable",
            "items": [
                {"serial": c.serial_number,
                 "url": reverse("cable_detail", args=[c.serial_number])}
                for c in CABLE.objects.filter(serial_number__icontains=q).order_by("serial_number")[:n]
            ],
        },
    ]
    groups = [g for g in groups if g["items"]]
    return render(request, "core/_search_typeahead.html", {"groups": groups, "q": q})


_CHIP_SORT_KEYS = {"serial_number", "femb__serial_number", "femb_pos", "tray_id", "last_update"}


def _femb_options():
    """Dropdown options for the FEMB filter chip on chip-family lists.

    Returns one entry per (version, serial_number) pair so a chip installed
    on a colliding-serial FEMB is unambiguous when filtered.
    """
    return [
        {"value": f.serial_number, "label": f"{f.version}/{f.serial_number}"}
        for f in FEMB.objects.order_by("version", "serial_number")
    ]


def _tray_options(model):
    """Dropdown options for the Tray filter chip; one entry per non-empty tray_id."""
    trays = (
        model.objects
        .exclude(tray_id__isnull=True)
        .exclude(tray_id__exact="")
        .values_list("tray_id", flat=True)
        .distinct()
        .order_by("tray_id")
    )
    return [{"value": t, "label": t} for t in trays]


def _grouped_chip_response(
    request, *, model, family_label, family_title, family_subtitle,
    chips_per_femb, has_tray_view, page_id,
):
    """Shared scaffolding for chip-family grouped list pages (LArASIC,
    ColdADC, COLDATA). LArASIC carries both a tray and a FEMB view; the
    others are FEMB-only (no RTS trays yet).

    Supports ?q= search, ?sort=&dir= sort, and ?page= pagination on the
    aggregated rows. The two views have disjoint sort-key sets — switching
    `view` re-defaults sort to "last activity" for that schema.
    """
    if has_tray_view:
        view = request.GET.get("view", "tray")
        if view not in {"tray", "femb"}:
            view = "tray"
    else:
        view = "femb"

    q = (request.GET.get("q") or "").strip()
    direction = request.GET.get("dir") or "desc"
    if direction not in {"asc", "desc"}:
        direction = "desc"

    if view == "tray":
        sort_keys = {"tray_id", "chip_count", "rt_tested", "ln_tested", "last_activity"}
        default_sort = "last_activity"
    else:
        sort_keys = {"femb", "chip_count", "qc", "chk", "latest_test"}
        default_sort = "latest_test"
    sort = request.GET.get("sort") or default_sort
    if sort not in sort_keys:
        sort = default_sort

    rows = []
    if view == "tray":
        rows = list(
            model.objects
            .exclude(tray_id__isnull=True).exclude(tray_id="")
            .values("tray_id").annotate(
                chip_count=Count("id"),
                rt_tested=Count("id", filter=Q(warm_tested_at__isnull=False)),
                ln_tested=Count("id", filter=Q(cold_tested_at__isnull=False)),
                latest_warm=Max("warm_tested_at"),
                latest_cold=Max("cold_tested_at"),
            )
        )
        # Flag trays with offline analysis CSVs — sourced from the persistent
        # TrayCsvCache the upload page maintains. One DB query, no SMB stats.
        from hwdb.upload import larasic as upload_lib
        with_csvs = upload_lib.trays_with_analysis([r["tray_id"] for r in rows])
        for r in rows:
            w, c = r["latest_warm"], r["latest_cold"]
            r["last_activity"] = max(w, c) if w and c else (w or c)
            r["has_csv"] = r["tray_id"] in with_csvs
        total_groups = len(rows)
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in (r["tray_id"] or "").lower()]
        rows.sort(
            key=lambda r: (r.get(sort) is None, r.get(sort) or ""),
            reverse=(direction == "desc"),
        )
    else:
        chip_counts = dict(
            model.objects.filter(removed_at_repair__isnull=True, femb__isnull=False)
            .values("femb").annotate(n=Count("id")).values_list("femb", "n")
        )
        qc_counts = dict(
            FembTest.objects.filter(test_type="QC").values("femb")
            .annotate(n=Count("id")).values_list("femb", "n")
        )
        chk_counts = dict(
            FembTest.objects.filter(test_type="CHK").values("femb")
            .annotate(n=Count("id")).values_list("femb", "n")
        )
        latest_test = dict(
            FembTest.objects.values("femb").annotate(t=Max("timestamp"))
            .values_list("femb", "t")
        )
        fembs = FEMB.objects.filter(pk__in=chip_counts.keys())
        total_groups = fembs.count()
        if q:
            fembs = fembs.filter(serial_number__icontains=q)
        for f in fembs:
            rows.append({
                "femb": f,
                "chip_count": chip_counts.get(f.pk, 0),
                "latest_test": latest_test.get(f.pk),
                "qc": qc_counts.get(f.pk, 0),
                "chk": chk_counts.get(f.pk, 0),
            })

        def _key(r):
            if sort == "femb":
                f = r["femb"]
                return (False, (f.version, f.serial_number))
            v = r.get(sort)
            return (v is None, v or 0)
        rows.sort(key=_key, reverse=(direction == "desc"))

    page_size = FAMILY_PAGE_SIZE
    page_obj = Paginator(rows, page_size).get_page(request.GET.get("page"))

    context = {
        "view": view,
        "q": q,
        "sort": sort,
        "dir": direction,
        "page_obj": page_obj,
        "page_size": page_size,
        "total_count": model.objects.count(),
        "total_groups": total_groups,
        "page": page_id,
        "family_label": family_label,
        "family_title": family_title,
        "family_subtitle": family_subtitle,
        "chips_per_femb": chips_per_femb,
        "has_tray_view": has_tray_view,
    }
    template = (
        "core/_chip_family_fragment.html"
        if getattr(request, "htmx", False)
        else "core/chip_family.html"
    )
    return render(request, template, context)


def larasic(request):
    return _grouped_chip_response(
        request,
        model=LArASIC,
        family_label="LArASIC",
        family_title="Frontend ASICs",
        family_subtitle="16-channel cold front-end ASICs",
        chips_per_femb=8,
        has_tray_view=True,
        page_id="larasic",
    )


def larasic_tray(request, tray_id):
    """Per-tray chip list — general browse, no HWDB exposure. Reached from
    the tray rows on /larasic/.
    """
    chips = LArASIC.objects.filter(tray_id=tray_id).order_by("serial_number")
    rt_tested = chips.filter(warm_tested_at__isnull=False).count()
    ln_tested = chips.filter(cold_tested_at__isnull=False).count()
    return render(request, "core/larasic_tray.html", {
        "tray_id": tray_id,
        "chips": chips,
        "chip_count": chips.count(),
        "rt_tested": rt_tested,
        "ln_tested": ln_tested,
        "page": "larasic",
    })


def coldadc(request):
    return _grouped_chip_response(
        request,
        model=ColdADC,
        family_label="ColdADC",
        family_title="Cold ADCs",
        family_subtitle="12-bit cold ADCs",
        chips_per_femb=8,
        has_tray_view=False,
        page_id="coldadc",
    )


def coldata(request):
    return _grouped_chip_response(
        request,
        model=COLDATA,
        family_label="COLDATA",
        family_title="COLDATA",
        family_subtitle="Serializer / control chips",
        chips_per_femb=2,
        has_tray_view=False,
        page_id="coldata",
    )


FEMB_SORT_KEYS = {"serial_number", "version", "latest_test_timestamp"}
FEMB_PAGE_SIZE = 100
FAMILY_PAGE_SIZE = 100


def _parse_date_param(value):
    """Parse a YYYY-MM-DD URL param. Returns a date or None for empty/invalid."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _family_list_response(
    request,
    *,
    queryset,
    sort_keys,
    page_id,
    full_template,
    fragment_template,
    default_sort,
    default_dir="asc",
    search_fields=(),
    filter_specs=(),
    date_range_field=None,
    page_size=FAMILY_PAGE_SIZE,
    extra_context=None,
):
    """Shared scaffolding for family list pages (LArASIC, ColdADC, COLDATA, Cable).

    `search_fields`: tuple of model field paths that ?q= matches via icontains (OR).
    `filter_specs`: tuple of (param_name, model_field_path) — exact-match chips.
    Switches between fragment and full templates based on `request.htmx`.
    """
    q = (request.GET.get("q") or "").strip()
    sort = request.GET.get("sort") or default_sort
    direction = request.GET.get("dir") or default_dir

    if sort not in sort_keys:
        sort = default_sort
    if direction not in {"asc", "desc"}:
        direction = default_dir

    if q and search_fields:
        condition = Q()
        for field in search_fields:
            condition |= Q(**{f"{field}__icontains": q})
        queryset = queryset.filter(condition)

    active_filters = {}
    for param, field in filter_specs:
        value = (request.GET.get(param) or "").strip()
        if value:
            queryset = queryset.filter(**{field: value})
            active_filters[param] = value

    since = ""
    until = ""
    if date_range_field:
        since = _parse_date_param(request.GET.get("since"))
        until = _parse_date_param(request.GET.get("until"))
        if since:
            queryset = queryset.filter(**{f"{date_range_field}__date__gte": since})
        if until:
            queryset = queryset.filter(**{f"{date_range_field}__date__lte": until})

    sort_field = f"-{sort}" if direction == "desc" else sort
    queryset = queryset.order_by(sort_field, "serial_number")

    page_obj = Paginator(queryset, page_size).get_page(request.GET.get("page"))

    context = {
        "page": page_id,
        "page_obj": page_obj,
        "page_size": page_size,
        "sort": sort,
        "dir": direction,
        "q": q,
        "active_filters": active_filters,
        "since": since.isoformat() if since else "",
        "until": until.isoformat() if until else "",
    }
    if extra_context:
        context.update(extra_context)

    template = fragment_template if getattr(request, "htmx", False) else full_template
    return render(request, template, context)


def femb(request):
    latest_test = FembTest.objects.filter(femb=OuterRef("pk")).order_by("-timestamp")
    queryset = FEMB.objects.annotate(
        latest_test_timestamp=Subquery(latest_test.values("timestamp")[:1])
    )

    q = (request.GET.get("q") or "").strip()
    version = (request.GET.get("version") or "").strip()
    sort = request.GET.get("sort") or "latest_test_timestamp"
    direction = request.GET.get("dir") or "desc"

    if sort not in FEMB_SORT_KEYS:
        sort = "latest_test_timestamp"
    if direction not in {"asc", "desc"}:
        direction = "asc"

    if q:
        queryset = queryset.filter(
            Q(serial_number__icontains=q) | Q(version__icontains=q)
        )
    if version:
        queryset = queryset.filter(version=version)

    since = _parse_date_param(request.GET.get("since"))
    until = _parse_date_param(request.GET.get("until"))
    if since:
        queryset = queryset.filter(latest_test_timestamp__date__gte=since)
    if until:
        queryset = queryset.filter(latest_test_timestamp__date__lte=until)

    sort_field = f"-{sort}" if direction == "desc" else sort
    # Stable secondary sort so equal keys don't shuffle between pages.
    queryset = queryset.order_by(sort_field, "serial_number")

    page_obj = Paginator(queryset, FEMB_PAGE_SIZE).get_page(request.GET.get("page"))

    versions = list(FEMB.objects.values_list("version", flat=True).distinct().order_by("version"))

    context = {
        "page": "femb",
        "page_obj": page_obj,
        "page_size": FEMB_PAGE_SIZE,
        "sort": sort,
        "dir": direction,
        "q": q,
        "version": version,
        "since": since.isoformat() if since else "",
        "until": until.isoformat() if until else "",
        "version_options": [{"value": v, "label": v} for v in versions],
        "femb_total": FEMB.objects.count(),
    }
    template = "core/_femb_list_fragment.html" if getattr(request, "htmx", False) else "core/femb.html"
    return render(request, template, context)


_CABLE_SORT_KEYS = {"serial_number", "batch_number", "latest_test_timestamp"}


def cable(request):
    latest_test = CableTest.objects.filter(cable=OuterRef("pk")).order_by("-timestamp")
    queryset = CABLE.objects.annotate(
        latest_test_timestamp=Subquery(latest_test.values("timestamp")[:1])
    )
    batches = list(
        CABLE.objects.values_list("batch_number", flat=True).distinct().order_by("batch_number")
    )
    return _family_list_response(
        request,
        queryset=queryset,
        sort_keys=_CABLE_SORT_KEYS,
        page_id="cable",
        full_template="core/cable.html",
        fragment_template="core/_cable_list_fragment.html",
        default_sort="latest_test_timestamp",
        default_dir="desc",
        search_fields=("serial_number",),
        filter_specs=(("batch", "batch_number"),),
        date_range_field="latest_test_timestamp",
        extra_context={
            "family_label": "Cable",
            "family_title": "Cold cables",
            "family_subtitle": "Cold flex cabling",
            "total_count": CABLE.objects.count(),
            "batch_options": [{"value": str(b), "label": f"Batch {b}"} for b in batches],
        },
    )


def cable_detail(request, serial_number):
    cable = get_object_or_404(CABLE, serial_number=serial_number)
    cable_tests = CableTest.objects.filter(cable=cable).order_by("-timestamp")
    context = {
        "cable": cable,
        "cable_tests": cable_tests,
        "page": "cable",
    }
    return render(request, "core/cable_detail.html", context)


def larasic_detail(request, serial_number):
    larasic = get_object_or_404(LArASIC, serial_number=serial_number)
    rts_data = larasic.rts()

    headers = []
    if rts_data:
        headers = [key for key in rts_data[0].keys() if key != "filename"]

    context = {
        "larasic": larasic,
        "rts_data": rts_data,
        "headers": headers,
        "page": "larasic",
    }
    return render(request, "core/larasic_detail.html", context)


def coldadc_detail(request, serial_number):
    coldadc = get_object_or_404(ColdADC, serial_number=serial_number)
    context = {
        "coldadc": coldadc,
        "page": "coldadc",
    }
    return render(request, "core/coldadc_detail.html", context)


def coldata_detail(request, serial_number):
    coldata = get_object_or_404(COLDATA, serial_number=serial_number)
    context = {
        "coldata": coldata,
        "page": "coldata",
    }
    return render(request, "core/coldata_detail.html", context)


def femb_detail(request, version, serial_number):
    femb = get_object_or_404(FEMB, version=version, serial_number=serial_number)
    femb_tests = FembTest.objects.filter(femb=femb).order_by("-timestamp")
    repairs = FembRepair.objects.filter(femb=femb).prefetch_related(
        "removed_larasics", "removed_coldadcs", "removed_coldatas",
        "installed_larasics", "installed_coldadcs", "installed_coldatas",
    ).order_by("iteration_number")
    larasics = femb.larasic_set.filter(removed_at_repair__isnull=True).order_by("femb_pos")
    coldadcs = femb.coldadc_set.filter(removed_at_repair__isnull=True).order_by("femb_pos")
    coldatas = femb.coldata_set.filter(removed_at_repair__isnull=True).order_by("femb_pos")
    context = {
        "femb": femb,
        "femb_tests": femb_tests,
        "repairs": repairs,
        "larasics": larasics,
        "coldadcs": coldadcs,
        "coldatas": coldatas,
        "page": "femb",
    }
    return render(request, "core/femb_detail.html", context)


def rts_file_content(request, serial_number, filename):
    if not RTS_FILENAME_RE.match(filename):
        return HttpResponseNotFound("<h1>File not found</h1>")

    larasic = get_object_or_404(LArASIC, serial_number=serial_number)
    base = (Path(config("RTS_DIR")) / larasic.tray_id / "results").resolve()
    candidate = (base / filename).resolve()
    if not candidate.is_relative_to(base):
        return HttpResponseNotFound("<h1>File not found</h1>")

    try:
        content = candidate.read_text()
    except (FileNotFoundError, OSError):
        return HttpResponseNotFound("<h1>File not found</h1>")
    return HttpResponse(f"<pre>{escape(content)}</pre>")


class FEMBViewSet(viewsets.ModelViewSet):
    queryset = FEMB.objects.all()
    serializer_class = FEMBSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["version", "serial_number"]

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            self.permission_classes = [IsAdminUser]
        else:
            self.permission_classes = [AllowAny]
        return super().get_permissions()
