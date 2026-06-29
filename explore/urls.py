from django.urls import path

from . import views

app_name = "explore"

urlpatterns = [
    path("", views.explore_view, name="home"),
    path("sync/", views.explore_sync_view, name="sync"),
    path("sync-tests/<str:part_type_id>/", views.explore_node_sync_view, name="node_sync"),
]
