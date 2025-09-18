from django.urls import path

from . import views

app_name = "hwdb"

urlpatterns = [
    path("", views.home, name="home"),
]
