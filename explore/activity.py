"""The Activities feed's logging helper (#88).

Events are recorded as side effects of work already happening — a sync run or
an in-app write — so the feed itself never talks to HWDB (keep the mirror
light). Sync callers log ONE summary row per run, and only when something new
was mirrored; per-item events from a sync are deliberately impossible here.

The table is a rolling window: ``log()`` prunes rows older than
``RETENTION_DAYS`` on every write, and the feed view prunes on read so the
cap holds even on a quiet instance.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from .models import ActivityEvent

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30


def prune() -> None:
    """Drop feed rows older than the retention window (all instances)."""
    cutoff = timezone.now() - timedelta(days=RETENTION_DAYS)
    ActivityEvent.objects.filter(created_at__lt=cutoff).delete()


def log(instance: str, kind: str, summary: str, *,
        part_id: str = "", part_type_id: str = "", actor: str = "") -> None:
    """Record one feed row. Never raises — the feed must not sink the write
    or sync it rides on."""
    try:
        ActivityEvent.objects.create(
            instance=instance, kind=kind, summary=summary,
            part_id=part_id, part_type_id=part_type_id, actor=actor)
        prune()
    except Exception:
        logger.exception("activity log failed (%s: %s)", kind, summary)
