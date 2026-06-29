from django.urls import path
from django.views.generic.base import RedirectView

from . import views

app_name = "hwdb"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("dashboard/sync/<str:family>/", views.dashboard_sync_view, name="dashboard_sync"),
    path("dashboard/probe/<str:family>/", views.dashboard_probe_view, name="dashboard_probe"),
    path("instance/", views.set_instance, name="set_instance"),
    path("larasic/", views.larasic_view, name="larasic"),
    path("larasic/sync/", views.larasic_sync_view, name="larasic_sync"),
    # Phase-3 upload (issues #19/#20/#21).
    path("larasic/upload/", views.upload_index_view, name="upload_index"),
    path("larasic/upload/refresh-cache/", views.upload_refresh_csv_cache_view, name="upload_refresh_csv_cache"),
    path("larasic/upload/<str:tray_id>/", views.upload_tray_view, name="upload_tray"),
    path("larasic/upload/<str:tray_id>/run/", views.upload_run_view, name="upload_run"),
    # The FD-VD explorer moved to its own app at /explore/ (ADR-0011, #32).
    # Permanent-redirect old bookmarks (the ?node= query string is preserved).
    path("explore/", RedirectView.as_view(pattern_name="explore:home",
                                           permanent=True, query_string=True)),
    path("link/", views.fnal_link_view, name="link"),
    path("link/poll/", views.fnal_link_poll_view, name="link_poll"),
    path("components/<str:component_type_id>/", views.component_list_view, name="component_list"),
    path("components/", views.component_list_view, name="component_list_default"), # Keep a default without ID
    # Generic tree browse, reached via the landing's "More" card.
    path("subsystems/<str:part1>/<str:part2>/", views.subsystem_list_view, name="subsystem_list_by_id"),
    path("subsystems/", views.subsystem_list_view, name="subsystem_list"),
    path("part-types/<str:part1>/<str:part2>/<int:subsystem_id>/", views.part_type_list_view, name="part_type_list"),
]
