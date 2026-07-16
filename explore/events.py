"""Per-component-type test-event sync — pure engine, no views.

``sync_test_events(api_base_url, bearer, part_type_id)`` walks every component
of one component type and mirrors each test record into ``HwdbTestEvent`` using
the uniform summary endpoint (``components/{part_id}/tests`` → ``created`` +
``test_type.name``). Read-only against HWDB; additive locally (ADR-0010).

Lazy and per-type: the explorer calls this on first visit to a leaf. Rows for
the part type are rewritten wholesale each run. Like ``hwdb.sync.sync_family``
it fetches in parallel (reads are idempotent) and yields plain-text progress
lines for a ``StreamingHttpResponse`` to wrap.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import local as _thread_local_cls
from typing import Iterator

from django.conf import settings
from django.utils import timezone

from hwdb.api_client import FnalDbApiClient

from .models import HierarchyNode, HwdbComponentEvent, HwdbTestEvent

logger = logging.getLogger(__name__)

_DEFAULT_WORKERS = 20


# Where each mapped component type keeps its physics test date inside
# ``test_data``, and how to read it (issue #70). The registry IS the record —
# add a type here (with spike evidence in docs/knowledge/test-date-registry.md)
# and its chart bins by physics date after a full re-sync. Fields:
# - "path": dict keys / list indices from test_data down to the raw value.
# - "style": how the raw string is parsed —
#     "ymd":      YYYY/MM/DD or YYYY-MM-DD (the CE chip "Test Date" shape).
#     "dm-or-md": DD-MM-YYYY-HH:MM or MM-DD-YYYY-HH:MM. Both orderings exist
#                 on the SAME types (upload batches differ; HWDB is append-only
#                 so old records never change), so each record disambiguates
#                 itself via day > 12, ambiguous days deferring to "day_first".
# - "label": names the field in the chart caption.
# CE chips aren't listed — their per-instance type ids come from the HWDB
# profile (see test_date_spec).
TEST_DATE_SPECS = {
    # SiPM board — verified 2026-07-16 (.idea/spike/hwdb_sipm_test_date.py):
    # the 2025-12 upload batch wrote MM-DD, later batches DD-MM.
    "D00400100003": {
        "label": "Test Results → Date",
        "path": ["Test Results", 0, "Date"],
        "style": "dm-or-md",
        "day_first": True,
    },
}

_CE_CHIP_SPEC = {"label": "Test Date", "path": ["Test Date"], "style": "ymd"}


def test_date_spec(instance: str, part_type_id: str) -> dict | None:
    """The registry entry for this component type, or ``None`` (→ the type's
    chart bins on the HWDB record ``created`` stamp and syncs via the cheap
    summary endpoint). The deferred refinement of ADR-0010."""
    profile = settings.HWDB_PROFILES[instance]
    ce_chip_types = {
        profile["larasic_part_type"],
        profile["coldadc_part_type"],
        profile["coldata_part_type"],
    }
    if part_type_id in ce_chip_types:
        return _CE_CHIP_SPEC
    return TEST_DATE_SPECS.get(part_type_id)


def physics_date_field(instance: str, part_type_id: str) -> str | None:
    """The display name of the ``test_data`` field holding the real (physics)
    test date for this component type, or ``None`` if the type isn't in the
    registry (→ fall back to the HWDB record ``created`` stamp)."""
    spec = test_date_spec(instance, part_type_id)
    return spec["label"] if spec else None


def _walk(data, path):
    """Follow a registry path (dict keys / int list indices) into test_data;
    ``None`` on any miss or shape mismatch."""
    cur = data
    for step in path:
        if isinstance(step, int):
            cur = cur[step] if isinstance(cur, list) and 0 <= step < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(step)
        else:
            cur = None
        if cur is None:
            return None
    return cur


_DMY_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})")


def _aware_date(year: int, month: int, day: int) -> datetime | None:
    try:
        naive = datetime(year, month, day)
    except ValueError:
        return None
    return timezone.make_aware(naive, timezone.get_current_timezone())


def extract_test_date(test_data: dict, spec: dict) -> datetime | None:
    """The physics test date out of one detailed test record, per the spec;
    ``None`` when missing or unparseable (callers fall back to the record's
    ``created``, ADR-0009). Chart bins are daily/monthly, so any time-of-day
    component is ignored."""
    raw = _walk(test_data or {}, spec["path"])
    if not isinstance(raw, str):
        return None
    if spec["style"] == "ymd":
        try:
            naive = datetime.strptime(raw.replace("-", "/"), "%Y/%m/%d")
        except ValueError:
            return None
        return timezone.make_aware(naive, timezone.get_current_timezone())
    # "dm-or-md": day > 12 settles the ordering; ambiguous days (both parse)
    # defer to the type's declared default. Worst case an old ambiguous record
    # lands day/month-swapped inside the same year — invisible at monthly bins.
    m = _DMY_RE.match(raw)
    if not m:
        return None
    a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    as_dm = _aware_date(year, b, a)  # a=day,   b=month
    as_md = _aware_date(year, a, b)  # a=month, b=day
    if as_dm and as_md:
        return as_dm if spec.get("day_first", True) else as_md
    return as_dm or as_md


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


def _list_part_ids(api, part_type_id: str, extra_params: dict | None = None) -> Iterator[str]:
    """Paginate the component listing, yielding each component's part_id.

    The listing carries ``created`` but NOT ``updated``; the per-component
    detail fetch is what gives us ``updated``.
    """
    page = 1
    while True:
        body = api._make_request(
            "GET",
            f"component-types/{part_type_id}/components",
            params={"page": page, "size": 500, **(extra_params or {})},
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


def _flag(v) -> bool | None:
    """A raw boolean flag off the detail record; ``None`` when absent."""
    return bool(v) if v is not None else None


def _ref_name(v) -> str:
    """HWDB nested ``{id, name}`` ref (or plain scalar) → its display name as a
    string; ``""`` when missing. Used for the categorical facets (creator,
    status, manufacturer, institution)."""
    if isinstance(v, dict):
        v = v.get("name")
    return str(v) if v else ""


def _fetch_component(api, part_id: str, date_spec: dict | None,
                     test_type_ids: dict[str, int], *,
                     need_detail: bool, need_tests: bool) -> dict:
    """Per-component fetch; the caller decides which halves to pull.

    - ``need_detail`` → one ``components/{pid}`` call for ``created``/``updated``
      (the cheap component-level refresh that keeps the ``updated`` chart fresh).
    - ``need_tests`` → the test events. With ``date_spec`` unset (all-consortia
      default) that's one summary call; with it set (a registry type) it's one
      *detailed* call per defined test type, reading the physics date out of
      ``test_data`` per the spec, with a ``created`` fallback.
    """
    tests = []
    if need_tests:
        if date_spec is None:
            for t in (api.get_tests(part_id).get("data") or []):
                dt = _parse_created(t.get("created"))
                if dt is None:
                    continue
                name = ((t.get("test_type") or {}).get("name") or "").strip() or "(unnamed)"
                tests.append((name, dt))
        else:
            for name, ttid in test_type_ids.items():
                for t in (api.get_tests(part_id, test_type_id=ttid).get("data") or []):
                    dt = (extract_test_date(t.get("test_data") or {}, date_spec)
                          or _parse_created(t.get("created")))
                    if dt is not None:
                        tests.append((name, dt))

    created = updated = None
    serial = created_by = status = manufacturer = institution = parent = ""
    installed = uploaded = certified = None
    if need_detail:
        detail = api._make_request("GET", f"components/{part_id}")
        d = detail.get("data") if isinstance(detail.get("data"), dict) else {}
        created = _parse_created(d.get("created"))
        updated = _parse_created(d.get("updated"))
        serial = d.get("serial_number") or ""
        created_by = _ref_name(d.get("creator"))
        status = _ref_name(d.get("status"))
        manufacturer = _ref_name(d.get("manufacturer"))
        institution = _ref_name(d.get("institution"))
        # Binary QC flags — top-level booleans on the detail record (#51);
        # None when the field is absent (kept NULL in the mirror).
        installed = _flag(d.get("is_installed"))
        uploaded = _flag(d.get("qaqc_uploaded"))
        certified = _flag(d.get("certified_qaqc"))
        # The box/assembly currently holding this item (#63); "" when free.
        parent = d.get("parent_part_id") or ""

    return {
        "part_id": part_id, "created": created, "updated": updated,
        "serial_number": serial, "created_by": created_by, "status": status,
        "manufacturer": manufacturer, "institution": institution,
        "is_installed": installed, "qaqc_uploaded": uploaded,
        "certified_qaqc": certified, "parent_part_id": parent,
        "tests": tests, "has_detail": need_detail, "has_tests": need_tests,
    }


def sync_test_events(
    api_base_url: str,
    bearer: str,
    part_type_id: str,
    *,
    instance: str = "prod",
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
        node = HierarchyNode.for_instance(instance).get(
            level=HierarchyNode.LEVEL_TYPE, part_type_id=part_type_id
        )
    except HierarchyNode.DoesNotExist:
        yield f"sync tests: unknown component type {part_type_id}\n"
        return

    node.tests_sync_error = ""
    node.save(update_fields=["tests_sync_error"])

    bootstrap = FnalDbApiClient(api_base_url, bearer)
    try:
        date_spec = test_date_spec(instance, part_type_id)
        test_type_ids = (
            _resolve_test_types(bootstrap, part_type_id) if date_spec else {}
        )
        if date_spec:
            yield (
                f"sync tests: using physics date '{date_spec['label']}' from "
                f"{len(test_type_ids)} test type(s)\n"
            )

        yield f"sync tests ({mode}): listing components for {part_type_id}\n"
        part_ids = list(_list_part_ids(bootstrap, part_type_id))
        listing_set = set(part_ids)
        known = set(
            HwdbComponentEvent.for_instance(instance).filter(part_type_id=part_type_id)
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
                                tls.client, p, date_spec, test_type_ids,
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
            HwdbTestEvent.for_instance(instance).filter(part_type_id=part_type_id).delete()
        else:
            # append for the (new) components we fetched tests for; clear any
            # stale rows for exactly those first so a retry can't double-insert.
            fetched_test_pids = [r["part_id"] for r in results if r["has_tests"]]
            HwdbTestEvent.for_instance(instance).filter(
                part_type_id=part_type_id, part_id__in=fetched_test_pids
            ).delete()
        new_test_rows = [
            HwdbTestEvent(instance=instance, part_type_id=part_type_id,
                          part_id=r["part_id"], test_type_name=name, created=dt)
            for r in results if r["has_tests"]
            for name, dt in r["tests"]
        ]
        if new_test_rows:
            HwdbTestEvent.objects.bulk_create(new_test_rows, batch_size=1000)

        # --- Component events ---
        # full/components fetch detail for ALL → rewrite wholesale; incremental
        # keeps existing rows and appends only the new components.
        if mode in ("full", "components"):
            HwdbComponentEvent.for_instance(instance).filter(part_type_id=part_type_id).delete()
        HwdbComponentEvent.objects.bulk_create(
            [
                HwdbComponentEvent(
                    instance=instance,
                    part_type_id=part_type_id, part_id=r["part_id"],
                    created=r["created"], updated=r["updated"],
                    serial_number=r.get("serial_number", ""),
                    created_by=r.get("created_by", ""),
                    status=r.get("status", ""),
                    manufacturer=r.get("manufacturer", ""),
                    institution=r.get("institution", ""),
                    is_installed=r.get("is_installed"),
                    qaqc_uploaded=r.get("qaqc_uploaded"),
                    certified_qaqc=r.get("certified_qaqc"),
                    parent_part_id=r.get("parent_part_id", ""),
                )
                for r in results if r["has_detail"]
            ],
            batch_size=1000,
        )

        # --- Availability sweep (issue #63) ---
        # The detail record doesn't carry HWDB's approval flag, but the
        # listing can filter on it: one enabled=false sweep marks the
        # "not yet available" items. Runs in every mode (it's ~1 call per
        # 500 such items) so known rows stay fresh too; a failing sweep
        # just leaves ``enabled`` as-is (NULL = unknown passes the picker).
        try:
            disabled = set(_list_part_ids(bootstrap, part_type_id,
                                          extra_params={"enabled": "false"}))
        except Exception as e:
            logger.warning("sync tests: enabled sweep for %s failed: %s",
                           part_type_id, e)
            disabled = None
        if disabled is not None:
            base = HwdbComponentEvent.for_instance(instance).filter(
                part_type_id=part_type_id)
            base.filter(part_id__in=disabled).update(enabled=False)
            base.exclude(part_id__in=disabled).update(enabled=True)
            yield f"sync tests: {len(disabled)} item(s) not yet enabled\n"

        n_tests = HwdbTestEvent.for_instance(instance).filter(part_type_id=part_type_id).count()
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
