"""
URL configuration for cets project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from core import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("fe/", views.fe, name="fe"),
    path("fe/<str:serial_number>/", views.fe_detail, name="fe_detail"),
    path("adc/", views.adc, name="adc"),
    path("coldata/", views.coldata, name="coldata"),
    path("femb/", views.femb, name="femb"),
    path("cable/", views.cable, name="cable"),
    path("wiec/", views.wiec, name="wiec"),
    path("wib/", views.wib, name="wib"),
    path("load-more/", views.load_more, name="load-more"),
    path("api/items/", views.ItemAPIView.as_view(), name="item-api"),
    path('fe/<str:serial_number>/rts/<str:filename>/', views.rts_file_content, name='rts_file_content'),
]

urlpatterns += staticfiles_urlpatterns()
