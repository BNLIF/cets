"""Two-zone authorization guard (ADR-0011).

After FNAL login (#33) an auto-provisioned ``credkey`` user is a normal
authenticated Django user — which, under the project-wide
``LoginRequiredMiddleware``, would otherwise let them reach every CETS/CE page.
This middleware draws the line: an authenticated user who is **not** a CETS
member (``cets`` group) and **not** a superuser may touch only the explore
zone, the FNAL device flow, logout, admin, and static — every other path (the
CETS zone) returns 403.

Deny-by-default: anything not explicitly allowed counts as CETS zone, so a new
page added later is never silently exposed to explore-only users. Membership is
the ``cets`` group; ``is_staff`` alone does not grant CETS access, and
superusers bypass entirely.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

CETS_GROUP = "cets"

# View names an explore-only user may reach outside the explore app: the shared
# FNAL device flow (explore sync redirects here to relink) and the auth
# login/logout endpoints. Admin is allowed via namespace (it enforces its own
# staff check); static is allowed via path prefix.
_ALLOWED_VIEW_NAMES = frozenset({
    "hwdb:link",
    "hwdb:link_poll",
    "rest_framework:login",
    "rest_framework:logout",
    "favicon",
})

_FORBIDDEN_HTML = (
    "<!doctype html><meta charset='utf-8'><title>Not available</title>"
    "<div style='font-family:-apple-system,sans-serif;max-width:34rem;"
    "margin:5rem auto;padding:0 1rem;color:#1f2328;line-height:1.5'>"
    "<h1 style='font-size:1.3rem'>Not available</h1>"
    "<p>This page is part of the cold-electronics tracking system and isn’t "
    "available to your account.</p>"
    "<p>If you have a CETS account, <a href='{login}'>sign in with it</a> to "
    "continue. Otherwise, head <a href='{explore}'>back to HWDB Explorer</a>.</p>"
    "</div>"
)


def _is_cets_member(user) -> bool:
    return user.groups.filter(name=CETS_GROUP).exists()


def _static_prefix() -> str:
    url = settings.STATIC_URL or "static/"
    return url if url.startswith("/") else "/" + url


class ExploreInstanceMiddleware:
    """Pin template ``{% url %}`` reversing to the request's explore instance
    namespace (#47), so every link rendered on a /hw/dev/ page stays on
    /hw/dev/ without touching the templates."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        rm = request.resolver_match
        if rm is not None and rm.app_name == "explore":
            request.current_app = rm.namespace


class CetsZoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None  # anonymous access is handled by the login gates
        if user.is_superuser or _is_cets_member(user):
            return None  # CETS members and superusers see everything

        # Explore-only (FNAL-provisioned) user: allow the explore zone + a small
        # allow-list; deny everything else (the CETS zone).
        if request.path.startswith(_static_prefix()):
            return None
        rm = request.resolver_match
        if rm is None:
            return None
        if rm.app_name == "explore" or rm.namespace == "admin":
            return None
        if rm.view_name in _ALLOWED_VIEW_NAMES:
            return None

        # Offer a CETS sign-in path (the deny page is otherwise a dead end for a
        # FNAL user who actually has a CETS account). The DRF login form accepts
        # new credentials even while authenticated, swapping the session user;
        # ``next`` returns them to the page they wanted.
        login = (
            f"{reverse('rest_framework:login')}?"
            f"{urlencode({'next': request.get_full_path()})}"
        )
        return HttpResponseForbidden(
            _FORBIDDEN_HTML.format(explore=reverse("explore:home"), login=login)
        )


class UsageMiddleware:
    """Count the request on the user's ``UsageDay`` row (#194): one UPDATE
    per signed-in request, after the response is built so a slow or failing
    write never delays or sinks the page. Static files, the service worker's
    HEAD pings and anonymous requests are not counted."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._record(request)
        except Exception:
            logger.exception("usage record failed for %s", request.path)
        return response

    @staticmethod
    def _record(request):
        if request.method == "HEAD" or request.path.endswith("/sw.js") \
                or request.path.startswith(_static_prefix()):
            return
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        from .models import UsageDay
        now = timezone.now()
        row = UsageDay.objects.filter(username=user.get_username(), day=now.date())
        if row.update(requests=F("requests") + 1, last_seen=now):
            return
        try:
            with transaction.atomic():
                UsageDay.objects.create(username=user.get_username(), day=now.date(),
                                        requests=1, last_seen=now)
        except IntegrityError:      # another worker inserted the day's row first
            row.update(requests=F("requests") + 1, last_seen=now)
