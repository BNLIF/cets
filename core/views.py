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
from django.db.models import Subquery, OuterRef, Q
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
    # "Cold tested · LN": components installed on a FEMB that has at least one LN test.
    larasic_cold = larasic_qs.filter(femb__fembtest__test_env="LN").distinct().count()
    coldadc_cold = coldadc_qs.filter(femb__fembtest__test_env="LN").distinct().count()
    coldata_cold = coldata_qs.filter(femb__fembtest__test_env="LN").distinct().count()
    cable_tested = cable_qs.filter(cabletest__isnull=False).distinct().count()

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
            "this_month": larasic_qs.filter(last_update__gte=month_ago).count(),
            "numbers": [
                {"value": larasic_qs.count(), "label": "Total tracked"},
                {"value": larasic_cold, "label": "Cold tested · LN", "cold": True},
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

    families = [
        {"name": "LArASIC", "kind": "16-ch front-end ASIC",
         "total": larasic_qs.count(), "tested": larasic_cold, "href": reverse("larasic")},
        {"name": "ColdADC", "kind": "12-bit cold ADC",
         "total": coldadc_qs.count(), "tested": coldadc_cold, "href": reverse("coldadc")},
        {"name": "COLDATA", "kind": "Serializer / control",
         "total": coldata_qs.count(), "tested": coldata_cold, "href": reverse("coldata")},
        {"name": "FEMB", "kind": "Frontend Motherboard",
         "total": femb_total, "tested": FembTest.objects.values("femb").distinct().count(),
         "href": reverse("femb")},
        {"name": "Cable", "kind": "Cold flex cabling",
         "total": cable_qs.count(), "tested": cable_tested, "href": reverse("cable")},
    ]

    context = {
        "page": "home",
        "femb_total": femb_total,
        "stat_cards": stat_cards,
        "families": families,
        "tests_per_day": queries.tests_per_day(days=90),
        "activity": queries.recent_activity(limit=10),
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


def larasic(request):
    return _family_list_response(
        request,
        queryset=LArASIC.objects.select_related("femb"),
        sort_keys=_CHIP_SORT_KEYS,
        page_id="larasic",
        full_template="core/_chip_list_page.html",
        fragment_template="core/_chip_list_fragment.html",
        default_sort="serial_number",
        search_fields=("serial_number", "femb__serial_number", "tray_id"),
        filter_specs=(("femb", "femb__serial_number"), ("tray", "tray_id")),
        date_range_field="last_update",
        extra_context={
            "family_label": "LArASIC",
            "family_title": "Frontend ASICs",
            "family_subtitle": "16-channel cold front-end ASICs",
            "total_count": LArASIC.objects.count(),
            "femb_options": _femb_options(),
            "tray_options": _tray_options(LArASIC),
            "detail_url_name": "larasic_detail",
        },
    )


def coldadc(request):
    return _family_list_response(
        request,
        queryset=ColdADC.objects.select_related("femb"),
        sort_keys=_CHIP_SORT_KEYS,
        page_id="coldadc",
        full_template="core/_chip_list_page.html",
        fragment_template="core/_chip_list_fragment.html",
        default_sort="serial_number",
        search_fields=("serial_number", "femb__serial_number", "tray_id"),
        filter_specs=(("femb", "femb__serial_number"), ("tray", "tray_id")),
        date_range_field="last_update",
        extra_context={
            "family_label": "ColdADC",
            "family_title": "Cold ADCs",
            "family_subtitle": "12-bit cold ADCs",
            "total_count": ColdADC.objects.count(),
            "femb_options": _femb_options(),
            "tray_options": _tray_options(ColdADC),
            "detail_url_name": "coldadc_detail",
        },
    )


def coldata(request):
    return _family_list_response(
        request,
        queryset=COLDATA.objects.select_related("femb"),
        sort_keys=_CHIP_SORT_KEYS,
        page_id="coldata",
        full_template="core/_chip_list_page.html",
        fragment_template="core/_chip_list_fragment.html",
        default_sort="serial_number",
        search_fields=("serial_number", "femb__serial_number", "tray_id"),
        filter_specs=(("femb", "femb__serial_number"), ("tray", "tray_id")),
        date_range_field="last_update",
        extra_context={
            "family_label": "COLDATA",
            "family_title": "COLDATA",
            "family_subtitle": "Serializer / control chips",
            "total_count": COLDATA.objects.count(),
            "femb_options": _femb_options(),
            "tray_options": _tray_options(COLDATA),
            "detail_url_name": "coldata_detail",
        },
    )


FEMB_SORT_KEYS = {"serial_number", "version", "latest_test_timestamp"}
FEMB_PAGE_SIZE = 12
FAMILY_PAGE_SIZE = 25


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
    activity_prefix=None,
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
    context["activity"] = queries.recent_activity(limit=10, target_prefix=activity_prefix)
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
    sort = request.GET.get("sort") or "serial_number"
    direction = request.GET.get("dir") or "asc"

    if sort not in FEMB_SORT_KEYS:
        sort = "serial_number"
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
        "activity": queries.recent_activity(limit=10, target_prefix="FEMB"),
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
        default_sort="serial_number",
        search_fields=("serial_number",),
        filter_specs=(("batch", "batch_number"),),
        date_range_field="latest_test_timestamp",
        activity_prefix="Cable",
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
    info_cells = [
        {"label": "VERSION", "value": femb.version, "is_pill": False},
        {"label": "STATUS", "value": femb.status, "is_pill": True},
        {"label": "LAST UPDATE", "value": femb.last_update.strftime("%Y-%m-%d %H:%M:%S"), "is_pill": False},
    ]
    context = {
        "femb": femb,
        "femb_tests": femb_tests,
        "repairs": repairs,
        "larasics": larasics,
        "coldadcs": coldadcs,
        "coldatas": coldatas,
        "info_cells": info_cells,
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
