import re
from pathlib import Path

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseNotFound
from django.core.paginator import Paginator
from django.utils.html import escape
from .models import LArASIC, ColdADC, COLDATA, FEMB, FembRepair, FembTest, CABLE, CableTest
from decouple import config
from django.db.models import Subquery, OuterRef
from rest_framework.permissions import IsAdminUser, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from .serializers import FEMBSerializer
from rest_framework import viewsets

RTS_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.csv$")


def home(request):
    return render(request, "core/index.html", {"page": "home"})


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
    sort_by = request.GET.get("sort", "serial_number")
    order = request.GET.get("order", "asc")
    queryset = ColdADC.objects.all()

    search_query = request.GET.get("q", "")
    search_by = request.GET.get("by", "sn")

    if search_query:
        if search_by == "sn":
            return redirect("coldadc_detail", serial_number=search_query)
        elif search_by == "femb":
            queryset = queryset.filter(femb__serial_number__icontains=search_query)

    total_count = queryset.count()

    if order == "desc":
        sort_by = f"-{sort_by}"
    queryset = queryset.order_by(sort_by)

    paginator = Paginator(queryset, 100)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "page": "coldadc",
        "search_query": search_query,
        "search_by": search_by,
        "sort": request.GET.get("sort", "serial_number"),
        "order": order,
        "total_count": total_count,
    }
    return render(request, "core/coldadc.html", context)


def coldata(request):
    sort_by = request.GET.get("sort", "serial_number")
    order = request.GET.get("order", "asc")
    queryset = COLDATA.objects.all()

    search_query = request.GET.get("q", "")
    search_by = request.GET.get("by", "sn")

    if search_query:
        if search_by == "sn":
            return redirect("coldata_detail", serial_number=search_query)
        elif search_by == "femb":
            queryset = queryset.filter(femb__serial_number__icontains=search_query)

    total_count = queryset.count()

    if order == "desc":
        sort_by = f"-{sort_by}"
    queryset = queryset.order_by(sort_by)

    paginator = Paginator(queryset, 100)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "page": "coldata",
        "search_query": search_query,
        "search_by": search_by,
        "sort": request.GET.get("sort", "serial_number"),
        "order": order,
        "total_count": total_count,
    }
    return render(request, "core/coldata.html", context)


def femb(request):
    sort_by = request.GET.get("sort", "latest_test_timestamp")
    order = request.GET.get("order", "desc")

    latest_test = FembTest.objects.filter(femb=OuterRef("pk")).order_by("-timestamp")
    queryset = FEMB.objects.annotate(
        latest_test_timestamp=Subquery(latest_test.values("timestamp")[:1])
    )

    search_query = request.GET.get("q", "")
    search_by = request.GET.get("by", "sn")

    if search_query:
        if search_by == "sn":
            try:
                femb = FEMB.objects.get(serial_number=search_query)
                return redirect(
                    "femb_detail",
                    version=femb.version,
                    serial_number=femb.serial_number,
                )
            except FEMB.DoesNotExist:
                queryset = queryset.filter(serial_number__icontains=search_query)

    total_count = queryset.count()

    if order == "desc":
        sort_by = f"-{sort_by}"
    queryset = queryset.order_by(sort_by)

    paginator = Paginator(queryset, 100)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "page": "femb",
        "search_query": search_query,
        "search_by": search_by,
        "sort": request.GET.get("sort", "latest_test_timestamp"),
        "order": order,
        "total_count": total_count,
    }
    return render(request, "core/femb.html", context)


def cable(request):
    sort_by = request.GET.get("sort", "latest_test_timestamp")
    order = request.GET.get("order", "desc")

    latest_test = CableTest.objects.filter(cable=OuterRef("pk")).order_by("-timestamp")
    queryset = CABLE.objects.annotate(
        latest_test_timestamp=Subquery(latest_test.values("timestamp")[:1])
    )

    search_query = request.GET.get("q", "")
    search_by = request.GET.get("by", "sn")

    if search_query:
        if search_by == "sn":
            try:
                cable = CABLE.objects.get(serial_number=search_query)
                return redirect(
                    "cable_detail",
                    serial_number=cable.serial_number,
                )
            except CABLE.DoesNotExist:
                queryset = queryset.filter(serial_number__icontains=search_query)
        elif search_by == "batch":
            queryset = queryset.filter(batch_number__icontains=search_query)

    total_count = queryset.count()

    if order == "desc":
        sort_by = f"-{sort_by}"
    queryset = queryset.order_by(sort_by)

    paginator = Paginator(queryset, 100)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "page": "cable",
        "search_query": search_query,
        "search_by": search_by,
        "sort": request.GET.get("sort", "serial_number"),
        "order": order,
        "total_count": total_count,
    }
    return render(request, "core/cable.html", context)


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
    context = {
        "femb": femb,
        "femb_tests": femb_tests,
        "repairs": repairs,
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
