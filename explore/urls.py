from django.urls import path

from . import views

app_name = "explore"

urlpatterns = [
    path("", views.explore_view, name="home"),
    path("login/", views.login_view, name="login"),
    path("login/poll/", views.login_poll_view, name="login_poll"),
    path("sync/", views.explore_sync_view, name="sync"),
    path("sync-tests/<str:part_type_id>/", views.explore_node_sync_view, name="node_sync"),
    # Drill-in node deep links (kept last so the specific routes above win).
    path("<path:trail>/", views.explore_view, name="node"),
]
