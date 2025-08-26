from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseNotFound
from django.core.paginator import Paginator
from .models import FE
from decouple import config
import os


def home(request):
    return render(request, "core/index.html", {"items": range(5), "page": "home"})


def fe(request):
    queryset = FE.objects.all().order_by("serial_number")

    search_query = request.GET.get("q", "")
    search_by = request.GET.get("by", "sn")

    if search_query:
        if search_by == "sn":
            return redirect("fe_detail", serial_number=search_query)
        elif search_by == "tray":
            queryset = queryset.filter(tray_id__icontains=search_query)

    paginator = Paginator(queryset, 100)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "page": "fe",
        "search_query": search_query,
        "search_by": search_by,
    }
    return render(request, "core/fe.html", context)


def adc(request):
    return render(request, "core/adc.html", {"page": "adc"})


def coldata(request):
    return render(request, "core/coldata.html", {"page": "coldata"})


def femb(request):
    return render(request, "core/femb.html", {"page": "femb"})


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
from .serializers import ItemSerializer


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
