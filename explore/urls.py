from django.urls import path
from django.views.generic.base import RedirectView

from . import views

app_name = "explore"

urlpatterns = [
    path("", views.explore_view, name="home"),
    path("shipments/", views.shipments_view, name="shipments"),
    path("login/", views.login_view, name="login"),
    path("login/poll/", views.login_poll_view, name="login_poll"),
    path("sync/", views.explore_sync_view, name="sync"),
    path("sync-tests/<str:part_type_id>/", views.explore_node_sync_view, name="node_sync"),
    path("sync-shipments/<str:part_type_id>/", views.explore_shipment_sync_view, name="shipment_sync"),
    path("shipment-image/<str:image_id>/", views.explore_shipment_image_view, name="shipment_image"),
    path("test-data/<str:part_id>/<str:test_type_id>/", views.explore_test_data_view, name="test_data"),
    path("part/<str:part_id>/", views.explore_part_view, name="part"),
    # The box page is now the generic part page (ADR-0014); keep old links working.
    path("shipment/<str:part_id>/",
         RedirectView.as_view(pattern_name="explore:part", permanent=True),
         name="shipment_detail"),
    # Drill-in node deep links (kept last so the specific routes above win).
    path("<path:trail>/", views.explore_view, name="node"),
]
