from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseNotFound
from django.core.paginator import Paginator
from .models import FE, ADC, COLDATA, FEMB, FEMB_TEST
from decouple import config
import os
from django.db.models import Subquery, OuterRef
from rest_framework.permissions import IsAdminUser, AllowAny
from django_filters.rest_framework import DjangoFilterBackend


def home(request):
    return render(request, "core/index.html", {"items": range(5), "page": "home"})


def fe(request):
    sort_by = request.GET.get("sort", "serial_number")
    order = request.GET.get("order", "asc")
    queryset = FE.objects.all()

    search_query = request.GET.get("q", "")
    search_by = request.GET.get("by", "sn")

    if search_query:
        if search_by == "sn":
            return redirect("fe_detail", serial_number=search_query)
        elif search_by == "tray":
            queryset = queryset.filter(tray_id__icontains=search_query)
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
        "page": "fe",
        "search_query": search_query,
        "search_by": search_by,
        "sort": request.GET.get("sort", "serial_number"),
        "order": order,
        "total_count": total_count,
    }
    return render(request, "core/fe.html", context)


def adc(request):
    sort_by = request.GET.get("sort", "serial_number")
    order = request.GET.get("order", "asc")
    queryset = ADC.objects.all()

    search_query = request.GET.get("q", "")
    search_by = request.GET.get("by", "sn")

    if search_query:
        if search_by == "sn":
            return redirect("adc_detail", serial_number=search_query)
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
        "page": "adc",
        "search_query": search_query,
        "search_by": search_by,
        "sort": request.GET.get("sort", "serial_number"),
        "order": order,
        "total_count": total_count,
    }
    return render(request, "core/adc.html", context)


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
    sort_by = request.GET.get("sort", "serial_number")
    order = request.GET.get("order", "asc")

    latest_test = FEMB_TEST.objects.filter(femb=OuterRef("pk")).order_by("-timestamp")
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
        "sort": request.GET.get("sort", "serial_number"),
        "order": order,
        "total_count": total_count,
    }
    return render(request, "core/femb.html", context)


def cable(request):
    return render(request, "core/cable.html", {"page": "cable"})


def wiec(request):
    return render(request, "core/wiec.html", {"page": "wiec"})


def wib(request):
    return render(request, "core/wib.html", {"page": "wib"})


def load_more(request):
    return HttpResponse("".join([f"<p>Item {i}</p>" for i in range(5, 10)]))


from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import ItemSerializer, FEMBSerializer
from rest_framework import viewsets


class ItemAPIView(APIView):
    def get(self, request):
        items = [{"id": i, "name": f"Item {i}"} for i in range(5)]
        serializer = ItemSerializer(items, many=True)
        return Response(serializer.data)


def fe_detail(request, serial_number):
    fe = get_object_or_404(FE, serial_number=serial_number)
    rts_data = fe.rts()

    headers = []
    if rts_data:
        headers = [key for key in rts_data[0].keys() if key != "filename"]

    context = {
        "fe": fe,
        "rts_data": rts_data,
        "headers": headers,
        "page": "fe",
    }
    return render(request, "core/fe_detail.html", context)


def adc_detail(request, serial_number):
    adc = get_object_or_404(ADC, serial_number=serial_number)
    context = {
        "adc": adc,
        "page": "adc",
    }
    return render(request, "core/adc_detail.html", context)


def coldata_detail(request, serial_number):
    coldata = get_object_or_404(COLDATA, serial_number=serial_number)
    context = {
        "coldata": coldata,
        "page": "coldata",
    }
    return render(request, "core/coldata_detail.html", context)


def femb_detail(request, version, serial_number):
    femb = get_object_or_404(FEMB, version=version, serial_number=serial_number)
    femb_tests = FEMB_TEST.objects.filter(femb=femb).order_by("-timestamp")
    context = {
        "femb": femb,
        "femb_tests": femb_tests,
        "page": "femb",
    }
    return render(request, "core/femb_detail.html", context)


def rts_file_content(request, serial_number, filename):
    fe = get_object_or_404(FE, serial_number=serial_number)
    tray_id = fe.tray_id

    rts_dir = config("RTS_DIR")
    file_path = os.path.join(rts_dir, tray_id, "results", filename)

    try:
        with open(file_path, "r") as f:
            content = f.read()
        return HttpResponse(f"<pre>{content}</pre>")
    except FileNotFoundError:
        return HttpResponseNotFound("<h1>File not found</h1>")
    except Exception as e:
        return HttpResponse(f"<h1>Error reading file</h1><p>{e}</p>", status=500)

class FEMBViewSet(viewsets.ModelViewSet):
    queryset = FEMB.objects.all()
    serializer_class = FEMBSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['version', 'serial_number']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            self.permission_classes = [IsAdminUser]
        else:
            self.permission_classes = [AllowAny]
        return super().get_permissions()
