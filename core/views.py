from django.shortcuts import render
from django.http import HttpResponse


def home(request):
    return render(request, "core/index.html", {"items": range(5), "page": "home"})

def fe(request):
    return render(request, "core/fe.html", {"page": "fe"})

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
