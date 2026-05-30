"""Template context processors for the hwdb app.

Currently exposes the active FNAL credkey (lowercase Fermilab services username)
when the user has a live link in their session, so the top-nav user menu can
show whose FNAL identity is in use without re-implementing the session lookup
in every view.
"""
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .fnal.session import LINK_KEY


def fnal_link(request):
    link = getattr(request, "session", {}).get(LINK_KEY)
    if not link:
        return {"fnal_credkey": None}
    expires_at = parse_datetime(link.get("vault_expires_at") or "")
    if expires_at and expires_at <= timezone.now():
        return {"fnal_credkey": None}
    return {"fnal_credkey": link.get("credkey")}
