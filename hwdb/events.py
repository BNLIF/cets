"""Per-component-type test-event sync — pure engine, no views.

``sync_test_events(api_base_url, bearer, part_type_id)`` walks every component
of one component type and mirrors each test record into ``HwdbTestEvent`` using
the uniform summary endpoint (``components/{part_id}/tests`` → ``created`` +
``test_type.name``). Read-only against HWDB; additive locally (ADR-0010).

Lazy and per-type: the explorer calls this on first visit to a leaf. Rows for
the part type are rewritten wholesale each run. Like ``sync.sync_family`` it
fetches in parallel (reads are idempotent) and yields plain-text progress
lines for a ``StreamingHttpResponse`` to wrap.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import local as _thread_local_cls
from typing import Iterator

from django.utils import timezone

from .api_client import FnalDbApiClient
from .models import ComponentTypeNode, HwdbTestEvent

logger = logging.getLogger(__name__)

_DEFAULT_WORKERS = 20


def _parse_created(created_s) -> datetime | None:
    if not created_s:
        return None
    try:
        return datetime.fromisoformat(created_s)
    except (ValueError, TypeError):
        return None


def _list_part_ids(api, part_type_id: str) -> Iterator[str]:
    """Paginate the component listing, yielding each component's part_id."""
    page = 1
    while True:
        body = api._make_request(
            "GET",
            f"component-types/{part_type_id}/components",
            params={"page": page, "size": 500},
        )
        rows = body.get("data") or []
        for row in rows:
            pid = row.get("part_id")
            if pid:
                yield pid
        pages = (body.get("pagination") or {}).get("pages", 1)
        if page >= pages or not rows:
            return
        page += 1


def _fetch_events(api, part_id: str) -> list[tuple[str, datetime]]:
    """One component's tests as (test_type_name, created) pairs.

    Uses the summary endpoint — uniform across consortia, no ``test_data``.
    """
    body = api.get_tests(part_id)
    out = []
    for t in body.get("data") or []:
        dt = _parse_created(t.get("created"))
        if dt is None:
            continue
        name = ((t.get("test_type") or {}).get("name") or "").strip() or "(unnamed)"
        out.append((name, dt))
    return out


def sync_test_events(
    api_base_url: str,
    bearer: str,
    part_type_id: str,
    *,
    workers: int = _DEFAULT_WORKERS,
) -> Iterator[str]:
    """Rebuild ``HwdbTestEvent`` rows for one component type. Generator."""
    try:
        node = ComponentTypeNode.objects.get(part_type_id=part_type_id)
    except ComponentTypeNode.DoesNotExist:
        yield f"sync tests: unknown component type {part_type_id}\n"
        return

    node.tests_sync_error = ""
    node.save(update_fields=["tests_sync_error"])

    bootstrap = FnalDbApiClient(api_base_url, bearer)
    try:
        yield f"sync tests: listing components for {part_type_id}\n"
        part_ids = list(_list_part_ids(bootstrap, part_type_id))
        yield f"sync tests: {len(part_ids)} component(s) to scan\n"

        collected: list[tuple[str, datetime]] = []
        if part_ids:
            tls = _thread_local_cls()

            def _init():
                tls.client = FnalDbApiClient(api_base_url, bearer)

            done = 0
            with ThreadPoolExecutor(max_workers=workers, initializer=_init) as pool:
                # Each worker uses its own thread-local client (requests.Session
                # is not thread-safe — same rule as sync_family).
                futs = {pool.submit(lambda p=pid: _fetch_events(tls.client, p)): pid
                        for pid in part_ids}
                for fut in as_completed(futs):
                    try:
                        collected.extend(fut.result())
                    except Exception as e:
                        logger.warning("sync tests: %s failed: %s", futs[fut], e)
                    done += 1
                    if done % 200 == 0 or done == len(part_ids):
                        yield (
                            f"sync tests: scanned {done}/{len(part_ids)} · "
                            f"{len(collected)} test(s) so far\n"
                        )

        # Rewrite this part type's events wholesale.
        HwdbTestEvent.objects.filter(part_type_id=part_type_id).delete()
        if collected:
            HwdbTestEvent.objects.bulk_create(
                [
                    HwdbTestEvent(part_type_id=part_type_id, part_id="",
                                  test_type_name=name, created=dt)
                    for name, dt in collected
                ],
                batch_size=1000,
            )

        node.tests_synced_at = timezone.now()
        node.n_tests = len(collected)
        node.n_components = len(part_ids) or node.n_components
        node.save(update_fields=["tests_synced_at", "n_tests", "n_components"])
        yield f"done: {len(collected)} test event(s) across {len(part_ids)} component(s)\n"
    except Exception as e:
        logger.exception("sync_test_events(%s) crashed", part_type_id)
        node.tests_sync_error = str(e)
        node.save(update_fields=["tests_sync_error"])
        raise
