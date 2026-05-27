from django.urls import path

from . import views

app_name = "hwdb"

urlpatterns = [
    path("", views.home, name="home"),
    path("instance/", views.set_instance, name="set_instance"),
    path("larasic/", views.larasic_view, name="larasic"),
    path("larasic/sync/", views.larasic_sync_view, name="larasic_sync"),
    path("link/", views.fnal_link_view, name="link"),
    path("link/poll/", views.fnal_link_poll_view, name="link_poll"),
    path("components/<str:component_type_id>/", views.component_list_view, name="component_list"),
    path("components/", views.component_list_view, name="component_list_default"), # Keep a default without ID
    # Generic tree browse, reached via the landing's "More" card.
    path("subsystems/<str:part1>/<str:part2>/", views.subsystem_list_view, name="subsystem_list_by_id"),
    path("subsystems/", views.subsystem_list_view, name="subsystem_list"),
    path("part-types/<str:part1>/<str:part2>/<int:subsystem_id>/", views.part_type_list_view, name="part_type_list"),
]
