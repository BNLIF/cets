"""Shared test helpers.

``make_cets_user`` creates a user that belongs to the ``cets`` group — i.e. a
CETS-zone member, as every real interactive account is (the data migration
enrolls them; FNAL-provisioned explore users are the only non-members). Tests
that exercise CETS/CE pages should log in such a user so the two-zone guard
(ADR-0011, ``explore.middleware.CetsZoneMiddleware``) lets them through.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group


def make_cets_user(username="guest", *, password="x", **kw):
    user = get_user_model().objects.create_user(username, password=password, **kw)
    group, _ = Group.objects.get_or_create(name="cets")
    user.groups.add(group)
    return user
