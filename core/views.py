import re
from datetime import timedelta
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
from django.db.models import Subquery, OuterRef
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


def larasic(request):
    # Common search functionality
    search_query = request.GET.get("q", "")
    search_by = request.GET.get("by", "sn")

    # Queryset for LArASICs with status 'on-femb'
    on_femb_queryset = LArASIC.objects.filter(status="on-femb")
    if search_query:
        if search_by == "sn":
            on_femb_queryset = on_femb_queryset.filter(
                serial_number__icontains=search_query
            )
        elif search_by == "femb":
            on_femb_queryset = on_femb_queryset.filter(
                femb__serial_number__icontains=search_query
            )

    # Sorting for 'on-femb' table
    sort_on_femb = request.GET.get("sort_on_femb", "serial_number")
    order_on_femb = request.GET.get("order_on_femb", "asc")
    if order_on_femb == "desc":
        sort_on_femb = f"-{sort_on_femb}"
    on_femb_queryset = on_femb_queryset.order_by(sort_on_femb)

    # Pagination for 'on-femb' table
    paginator_on_femb = Paginator(on_femb_queryset, 100)
    page_on_femb_number = request.GET.get("page_on_femb")
    page_on_femb_obj = paginator_on_femb.get_page(page_on_femb_number)
    total_on_femb_count = on_femb_queryset.count()

    # Queryset for LArASICs with an RTS tray ID
    rts_queryset = LArASIC.objects.exclude(tray_id__isnull=True).exclude(tray_id__exact="")
    if search_query:
        if search_by == "sn":
            rts_queryset = rts_queryset.filter(serial_number__icontains=search_query)
        elif search_by == "tray":
            rts_queryset = rts_queryset.filter(tray_id__icontains=search_query)

    # Sorting for 'rts' table
    sort_rts = request.GET.get("sort_rts", "serial_number")
    order_rts = request.GET.get("order_rts", "asc")
    if order_rts == "desc":
        sort_rts = f"-{sort_rts}"
    rts_queryset = rts_queryset.order_by(sort_rts)

    # Pagination for 'rts' table
    paginator_rts = Paginator(rts_queryset, 100)
    page_rts_number = request.GET.get("page_rts")
    page_rts_obj = paginator_rts.get_page(page_rts_number)
    total_rts_count = rts_queryset.count()

    context = {
        "page_on_femb_obj": page_on_femb_obj,
        "total_on_femb_count": total_on_femb_count,
        "sort_on_femb": request.GET.get("sort_on_femb", "serial_number"),
        "order_on_femb": order_on_femb,
        "page_rts_obj": page_rts_obj,
        "total_rts_count": total_rts_count,
        "sort_rts": request.GET.get("sort_rts", "serial_number"),
        "order_rts": order_rts,
        "page": "larasic",
        "search_query": search_query,
        "search_by": search_by,
    }
    return render(request, "core/larasic.html", context)


def coldadc(request):
    queryset = ColdADC.objects.all()
    q = request.GET.get("q", "")
    by = request.GET.get("by", "sn")
    if q and by == "sn":
        return redirect("coldadc_detail", serial_number=q)
    if q and by == "femb":
        queryset = queryset.filter(femb__serial_number__icontains=q)
    return _render_paginated_list(request, queryset, "core/coldadc.html", "coldadc", "serial_number")


def coldata(request):
    queryset = COLDATA.objects.all()
    q = request.GET.get("q", "")
    by = request.GET.get("by", "sn")
    if q and by == "sn":
        return redirect("coldata_detail", serial_number=q)
    if q and by == "femb":
        queryset = queryset.filter(femb__serial_number__icontains=q)
    return _render_paginated_list(request, queryset, "core/coldata.html", "coldata", "serial_number")


def femb(request):
    latest_test = FembTest.objects.filter(femb=OuterRef("pk")).order_by("-timestamp")
    queryset = FEMB.objects.annotate(
        latest_test_timestamp=Subquery(latest_test.values("timestamp")[:1])
    )
    q = request.GET.get("q", "")
    by = request.GET.get("by", "sn")
    if q and by == "sn":
        try:
            f = FEMB.objects.get(serial_number=q)
            return redirect("femb_detail", version=f.version, serial_number=f.serial_number)
        except FEMB.DoesNotExist:
            queryset = queryset.filter(serial_number__icontains=q)
    return _render_paginated_list(request, queryset, "core/femb.html", "femb", "latest_test_timestamp", default_order="desc")


def cable(request):
    latest_test = CableTest.objects.filter(cable=OuterRef("pk")).order_by("-timestamp")
    queryset = CABLE.objects.annotate(
        latest_test_timestamp=Subquery(latest_test.values("timestamp")[:1])
    )
    q = request.GET.get("q", "")
    by = request.GET.get("by", "sn")
    if q and by == "sn":
        try:
            c = CABLE.objects.get(serial_number=q)
            return redirect("cable_detail", serial_number=c.serial_number)
        except CABLE.DoesNotExist:
            queryset = queryset.filter(serial_number__icontains=q)
    elif q and by == "batch":
        queryset = queryset.filter(batch_number__icontains=q)
    return _render_paginated_list(request, queryset, "core/cable.html", "cable", "latest_test_timestamp", default_order="desc")


def cable_detail(request, serial_number):
    cable = get_object_or_404(CABLE, serial_number=serial_number)
    cable_tests = CableTest.objects.filter(cable=cable).order_by("-timestamp")
    context = {
        "cable": cable,
        "cable_tests": cable_tests,
        "page": "cable",
    }
    return render(request, "core/cable_detail.html", context)


def wiec(request):
    return render(request, "core/wiec.html", {"page": "wiec"})


def wib(request):
    return render(request, "core/wib.html", {"page": "wib"})


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
