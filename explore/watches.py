"""Watch/notify (#90): subscriptions over the Activities feed.

A watch targets a component type (``part_type_id``, ``part_id`` empty) or a
single part — box or item (``part_id`` set). Notifications are derived at
read time from ``ActivityEvent`` rows matching the user's watches; nothing is
fanned out or stored per notification, so storage stays flat and the 30-day
activity retention bounds everything. A part-level watch matches events on
that exact part; a type-level watch matches every event carrying the type
(including part-level events of parts of that type).
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from .models import ActivityEvent, WatchSubscription


def subs_for(instance: str, username: str):
    return WatchSubscription.for_instance(instance).filter(username=username)


def is_watched(instance: str, username: str, *,
               part_id: str = "", part_type_id: str = "") -> bool:
    return subs_for(instance, username).filter(
        part_id=part_id, part_type_id=part_type_id).exists()


def toggle(instance: str, username: str, *, part_id: str = "",
           part_type_id: str = "", label: str = "") -> bool:
    """Create the watch, or remove it if it already exists.
    Returns True when now watching."""
    existing = subs_for(instance, username).filter(
        part_id=part_id, part_type_id=part_type_id)
    if existing.exists():
        existing.delete()
        return False
    WatchSubscription.objects.create(
        instance=instance, username=username,
        part_id=part_id, part_type_id=part_type_id, label=label)
    return True


def _match_q(subs, unread_only: bool = False) -> Q | None:
    """OR of one clause per watch; None when the user watches nothing."""
    q = None
    for s in subs:
        clause = (Q(part_id=s.part_id) if s.part_id
                  else Q(part_type_id=s.part_type_id))
        if unread_only:
            clause &= Q(created_at__gt=s.seen_at)
        q = clause if q is None else q | clause
    return q


def watched_events(instance: str, username: str):
    """All feed events matching the user's watches (newest first)."""
    q = _match_q(subs_for(instance, username))
    if q is None:
        return ActivityEvent.objects.none()
    return ActivityEvent.for_instance(instance).filter(q)


def unread_events(instance: str, username: str):
    """Matching events newer than each watch's last-seen mark (newest first) —
    the badge count and the profile's "new on your watches" list."""
    q = _match_q(subs_for(instance, username), unread_only=True)
    if q is None:
        return ActivityEvent.objects.none()
    return ActivityEvent.for_instance(instance).filter(q)


def unread_count(instance: str, username: str) -> int:
    return unread_events(instance, username).count()


def mark_seen(instance: str, username: str) -> None:
    subs_for(instance, username).update(seen_at=timezone.now())
