from django.urls import path

from . import views

app_name = "hwdb"

urlpatterns = [
    path("", views.home, name="home"),
    path("components/<str:component_type_id>/", views.component_list_view, name="component_list"),
    path("components/", views.component_list_view, name="component_list_default"), # Keep a default without ID
    path("subsystems/<str:part1>/<str:part2>/", views.subsystem_list_view, name="subsystem_list_by_id"),
    path("subsystems/", views.subsystem_list_view, name="subsystem_list"), # Default without ID
    path("part-types/<str:part1>/<str:part2>/<int:subsystem_id>/", views.part_type_list_view, name="part_type_list"),
]
