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


def provision_and_login(request, login_result):
    """Map a completed FNAL device flow to a Django user and log them in.

    The ``credkey`` is the stable identity; we key the Django user on it,
    auto-creating a password-less account the first time someone signs in via
    FNAL (subsequent logins reuse it). Returns the user.
    """
    User = get_user_model()
    user, created = User.objects.get_or_create(username=login_result.credkey)
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
            login_url = reverse("explore:login")
            return redirect(f"{login_url}?{urlencode({'next': request.get_full_path()})}")
        return view(request, *args, **kwargs)

    return wrapper
