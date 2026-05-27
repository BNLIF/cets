"""Per-session HWDB instance selection.

The env `HWDB_INSTANCE` (settings) is the baseline default. A user can override
it for their own session via the toggle on the HWDB landing — without a server
restart, and without affecting anyone else. Read-only today; once upload lands
this is the switch between writing to dev vs prod, so it's deliberately
per-session rather than global.
"""

from __future__ import annotations

from django.conf import settings

SESSION_KEY = "hwdb_instance"


def active_instance(request) -> str:
    """The instance for this request: session override if valid, else the
    configured default."""
    choice = request.session.get(SESSION_KEY)
    if choice in settings.HWDB_PROFILES:
        return choice
    return settings.HWDB_INSTANCE


def active_profile(request) -> dict:
    """The {api, ui, larasic_part_type} profile for this request's instance."""
    return settings.HWDB_PROFILES[active_instance(request)]
