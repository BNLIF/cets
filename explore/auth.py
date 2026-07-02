"""Explore-zone authentication: FNAL login *is* the login (ADR-0011).

Two pieces:

- ``provision_and_login`` turns a completed FNAL device flow into a Django
  user keyed on the ``credkey`` (the lowercase Fermilab services username) and
  logs them in — the password-less, auto-provisioned identity the explore site
  runs on. This mirrors dunecat's ``upsert_user(oidc_sub)`` on Django's user
  system.
- ``fnal_login_required`` is the explore-zone gate. Explore views opt out of
  the project-wide ``LoginRequiredMiddleware`` (``@login_not_required``) and
  wear this instead, so an unauthenticated visitor is sent to the FNAL login
  rather than CETS's username/password form.
"""

from __future__ import annotations

from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth import get_user_model, login
from django.shortcuts import redirect
from django.urls import reverse

# We provision the user ourselves (no authenticate() call), so login() needs an
# explicit backend. The default ModelBackend is the only one configured.
_BACKEND = "django.contrib.auth.backends.ModelBackend"

# FNAL-provisioned users live in their own username namespace: the Django
# username is ``fnal:<credkey>``, never the bare credkey. This keeps the FNAL
# identity space disjoint from local accounts — a FNAL credkey can never resolve
# to a pre-existing privileged account (e.g. ``admin``), and signing in via FNAL
# is always a distinct, explore-only identity. The colon is rejected by Django's
# username validator, so no hand-created account can ever collide with it.
# (ADR-0011.) CETS staff reach CETS via their password login, not this door.
FNAL_USERNAME_PREFIX = "fnal:"


def fnal_username(credkey: str) -> str:
    return f"{FNAL_USERNAME_PREFIX}{credkey}"


def provision_and_login(request, login_result):
    """Map a completed FNAL device flow to a Django user and log them in.

    The ``credkey`` is the stable identity; we key the Django user on
    ``fnal:<credkey>`` (a namespace disjoint from local accounts — see
    ``FNAL_USERNAME_PREFIX``), auto-creating a password-less, group-less (hence
    explore-only) account the first time someone signs in via FNAL. Returns the
    user. The real credkey for display lives in the session link (surfaced by
    ``hwdb.context_processors.fnal_link``).
    """
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=fnal_username(login_result.credkey),
        defaults={"first_name": login_result.credkey},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    login(request, user, backend=_BACKEND)
    return user


def fnal_login_required(view):
    """Explore-zone gate: unauthenticated → FNAL login (not the password page).

    Pair with ``@login_not_required`` so the project-wide middleware defers to
    this redirect target.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            # current_app (set by ExploreInstanceMiddleware) keeps a /hw/dev/
            # visitor on the dev-prefixed login page (#47).
            login_url = reverse("explore:login",
                                current_app=getattr(request, "current_app", None))
            return redirect(f"{login_url}?{urlencode({'next': request.get_full_path()})}")
        return view(request, *args, **kwargs)

    return wrapper
