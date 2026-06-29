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

from django.conf import settings
from django.utils import timezone

from .api_client import FnalDbApiClient
from .models import ComponentTypeNode, HwdbComponentEvent, HwdbTestEvent
from .sync import _parse_test_date  # reuse the dashboard's YYYY/MM/DD parser

logger = logging.getLogger(__name__)

_DEFAULT_WORKERS = 20


def physics_date_field(part_type_id: str) -> str | None:
    """The ``test_data`` field holding the real (physics) test date for this
    component type, or ``None`` if we don't know one (→ fall back to the HWDB
    record ``created`` stamp). The deferred refinement of ADR-0010: only the CE
    chip families are mapped today; other consortia stay on ``created`` until
    their datasheet date field is validated.
    """
    prod = settings.HWDB_PROFILES["prod"]
    ce_chip_types = {
        prod["larasic_part_type"],
        prod["coldadc_part_type"],
        prod["coldata_part_type"],
    }
    return "Test Date" if part_type_id in ce_chip_types else None


def _resolve_test_types(api, part_type_id: str) -> dict[str, int]:
    """{test_type_name: id} for a component type (one call, reused per sweep)."""
    body = api.get_test_types(part_type_id)
    return {
        tt["name"]: tt["id"]
        for tt in (body.get("data") or [])
        if tt.get("name") and tt.get("id") is not None
    }


def _parse_created(created_s) -> datetime | None:
    if not created_s:
        return None
    try:
        return datetime.fromisoformat(created_s)
    except (ValueError, TypeError):
        return None


def _list_part_ids(api, part_type_id: str) -> Iterator[str]:
    """Paginate the component listing, yielding each component's part_id.

    The listing carries ``created`` but NOT ``updated``; the per-component
    detail fetch is what gives us ``updated``.
    """
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


def _fetch_component(api, part_id: str, date_field: str | None,
                     test_type_ids: dict[str, int], *,
                     need_detail: bool, need_tests: bool) -> dict:
    """Per-component fetch; the caller decides which halves to pull.

    - ``need_detail`` → one ``components/{pid}`` call for ``created``/``updated``
      (the cheap component-level refresh that keeps the ``updated`` chart fresh).
    - ``need_tests`` → the test events. With ``date_field`` unset (all-consortia
      default) that's one summary call; with it set (CE) it's one *detailed*
      call per defined test type, reading the physics ``test_data[date_field]``
      with a ``created`` fallback.
    """
    tests = []
    if need_tests:
        if date_field is None:
            for t in (api.get_tests(part_id).get("data") or []):
                dt = _parse_created(t.get("created"))
                if dt is None:
                    continue
                name = ((t.get("test_type") or {}).get("name") or "").strip() or "(unnamed)"
                tests.append((name, dt))
        else:
            for name, ttid in test_type_ids.items():
                for t in (api.get_tests(part_id, test_type_id=ttid).get("data") or []):
                    dt = (_parse_test_date(t.get("test_data") or {})
                          or _parse_created(t.get("created")))
                    if dt is not None:
                        tests.append((name, dt))

    created = updated = None
    if need_detail:
        detail = api._make_request("GET", f"components/{part_id}")
        d = detail.get("data") if isinstance(detail.get("data"), dict) else {}
        created = _parse_created(d.get("created"))
        updated = _parse_created(d.get("updated"))

    return {
        "part_id": part_id, "created": created, "updated": updated,
        "tests": tests, "has_detail": need_detail, "has_tests": need_tests,
    }


def sync_test_events(
    api_base_url: str,
    bearer: str,
    part_type_id: str,
    *,
    mode: str = "incremental",
    workers: int = _DEFAULT_WORKERS,
) -> Iterator[str]:
    """Sync events for one component type. Generator yielding progress lines.

    Three modes (cost-tiered, mirroring the dashboard's skip-known policy,
    ADR-0008/0010):

    - ``incremental`` (default): fetch only components not yet mirrored — their
      detail + tests. Cheapest; misses re-tests / ``updated`` changes on known
      components.
    - ``components``: re-fetch *detail* for all components (refresh the
      ``updated`` inventory chart), but tests only for new components. Cheap
      (~1 GET/component) and keeps ``updated`` current.
    - ``full``: re-fetch everything — detail + all tests — for all components.
    """
    try:
        node = ComponentTypeNode.objects.get(part_type_id=part_type_id)
    except ComponentTypeNode.DoesNotExist:
        yield f"sync tests: unknown component type {part_type_id}\n"
        return

    node.tests_sync_error = ""
    node.save(update_fields=["tests_sync_error"])

    bootstrap = FnalDbApiClient(api_base_url, bearer)
    try:
        date_field = physics_date_field(part_type_id)
        test_type_ids = (
            _resolve_test_types(bootstrap, part_type_id) if date_field else {}
        )
        if date_field:
            yield (
                f"sync tests: using physics date '{date_field}' from "
                f"{len(test_type_ids)} test type(s)\n"
            )

        yield f"sync tests ({mode}): listing components for {part_type_id}\n"
        part_ids = list(_list_part_ids(bootstrap, part_type_id))
        listing_set = set(part_ids)
        known = set(
            HwdbComponentEvent.objects.filter(part_type_id=part_type_id)
            .values_list("part_id", flat=True)
        )
        new = listing_set - known

        if mode == "full":
            detail_set, tests_set = listing_set, listing_set
        elif mode == "components":
            detail_set, tests_set = listing_set, new   # refresh all detail; tests for new only
        else:  # incremental
            detail_set, tests_set = new, new

        process = sorted(detail_set | tests_set)
        yield (
            f"sync tests ({mode}): {len(part_ids)} in HWDB · {len(new)} new · "
            f"fetching detail×{len(detail_set)} + tests×{len(tests_set)}\n"
        )

        results: list[dict] = []
        if process:
            tls = _thread_local_cls()

            def _init():
                tls.client = FnalDbApiClient(api_base_url, bearer)

            done = 0
            with ThreadPoolExecutor(max_workers=workers, initializer=_init) as pool:
                # Each worker uses its own thread-local client (requests.Session
                # is not thread-safe — same rule as sync_family).
                futs = {pool.submit(
                            lambda p=pid: _fetch_component(
                                tls.client, p, date_field, test_type_ids,
                                need_detail=p in detail_set,
                                need_tests=p in tests_set)): pid
                        for pid in process}
                for fut in as_completed(futs):
                    try:
                        results.append(fut.result())
                    except Exception as e:
                        logger.warning("sync tests: %s failed: %s", futs[fut], e)
                    done += 1
                    if done % 200 == 0 or done == len(process):
                        yield f"sync tests ({mode}): fetched {done}/{len(process)}\n"

        # --- Test events ---
        if mode == "full":
            HwdbTestEvent.objects.filter(part_type_id=part_type_id).delete()
        else:
            # append for the (new) components we fetched tests for; clear any
            # stale rows for exactly those first so a retry can't double-insert.
            fetched_test_pids = [r["part_id"] for r in results if r["has_tests"]]
            HwdbTestEvent.objects.filter(
                part_type_id=part_type_id, part_id__in=fetched_test_pids
            ).delete()
        new_test_rows = [
            HwdbTestEvent(part_type_id=part_type_id, part_id=r["part_id"],
                          test_type_name=name, created=dt)
            for r in results if r["has_tests"]
            for name, dt in r["tests"]
        ]
        if new_test_rows:
            HwdbTestEvent.objects.bulk_create(new_test_rows, batch_size=1000)

        # --- Component events ---
        # full/components fetch detail for ALL → rewrite wholesale; incremental
        # keeps existing rows and appends only the new components.
        if mode in ("full", "components"):
            HwdbComponentEvent.objects.filter(part_type_id=part_type_id).delete()
        HwdbComponentEvent.objects.bulk_create(
            [
                HwdbComponentEvent(
                    part_type_id=part_type_id, part_id=r["part_id"],
                    created=r["created"], updated=r["updated"],
                )
                for r in results if r["has_detail"]
            ],
            batch_size=1000,
        )

        n_tests = HwdbTestEvent.objects.filter(part_type_id=part_type_id).count()
        node.tests_synced_at = timezone.now()
        node.n_tests = n_tests
        node.n_components = len(part_ids) or node.n_components
        node.save(update_fields=["tests_synced_at", "n_tests", "n_components"])
        yield (
            f"done ({mode}): {len(new_test_rows)} new test event(s), "
            f"{n_tests} total · {len(part_ids)} component(s)\n"
        )
    except Exception as e:
        logger.exception("sync_test_events(%s) crashed", part_type_id)
        node.tests_sync_error = str(e)
        node.save(update_fields=["tests_sync_error"])
        raise
