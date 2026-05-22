from django.contrib import admin
from django.http import HttpResponsePermanentRedirect
from django.urls import path, include, re_path, reverse
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from core import views
from django.views.generic.base import RedirectView
from django.templatetags.static import static
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r"api/femb", views.FEMBViewSet, basename="femb")


def _legacy_redirect(name):
    """Redirect /fe/<rest> → /larasic/<rest> (etc.) honoring FORCE_SCRIPT_NAME."""
    def view(request, rest=""):
        base = reverse(name)  # includes FORCE_SCRIPT_NAME prefix and trailing slash
        return HttpResponsePermanentRedirect(f"{base}{rest}")
    return view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api-auth/", include("rest_framework.urls")),
    path("", views.home, name="home"),
    path("reference/", views.reference, name="reference"),
    path("search/typeahead/", views.search_typeahead, name="search_typeahead"),
    path("hwdb/", include("hwdb.urls")),
    path("larasic/", views.larasic, name="larasic"),
    path("larasic/<str:serial_number>/", views.larasic_detail, name="larasic_detail"),
    path("coldadc/", views.coldadc, name="coldadc"),
    path("coldadc/<str:serial_number>/", views.coldadc_detail, name="coldadc_detail"),
    path("coldata/", views.coldata, name="coldata"),
    path("coldata/<str:serial_number>/", views.coldata_detail, name="coldata_detail"),
    path("femb/", views.femb, name="femb"),
    path(
        "femb/<str:version>/<str:serial_number>/", views.femb_detail, name="femb_detail"
    ),
    path("cable/", views.cable, name="cable"),
    path("cable/<str:serial_number>/", views.cable_detail, name="cable_detail"),
    path(
        "larasic/<str:serial_number>/rts/<str:filename>/",
        views.rts_file_content,
        name="rts_file_content",
    ),
    # Backward-compat redirects from pre-rename URL paths. Safe to drop after
    # the team has had a chance to update bookmarks.
    re_path(r"^fe/(?P<rest>.*)$", _legacy_redirect("larasic")),
    re_path(r"^adc/(?P<rest>.*)$", _legacy_redirect("coldadc")),
    path(
        "favicon.ico",
        RedirectView.as_view(url=static("core/images/favicon.png"), permanent=True),
        name="favicon",
    ),
    path("", include(router.urls)),
]

urlpatterns += staticfiles_urlpatterns()
