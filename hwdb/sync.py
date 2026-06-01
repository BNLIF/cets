"""HwdbChip mirror sync — pure engine, no views.

One ``sync_family(family, ...)`` orchestrator does the full sync for a chip
family (LArASIC / ColdADC / COLDATA). The skip-known-serials policy from
ADR-0008 lives here: once a serial has a row in ``HwdbChip``, its tests are
never re-fetched unless ``force_full=True``.

The orchestrator yields plain-text progress lines so views can layer a
``StreamingHttpResponse`` on top without changing the engine.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from threading import local as _thread_local_cls
from typing import Callable, Iterator

from django.utils import timezone

from core.models import LArASIC

from .api_client import FnalDbApiClient
from .models import HwdbChip, HwdbSyncState, LarasicSyncState

logger = logging.getLogger(__name__)

# HWDB test-type names per env discriminator. Same vocabulary as the upload
# code (``resolve_test_type_id`` in ``hwdb/upload/larasic.py``).
_ENV_TO_TEST_TYPE_NAME = {
    "RT": "RoomT QC Test",
    "LN": "CryoT QC Test",
}

# Reads tolerate more concurrency than uploads — no body, idempotent, no DB
# write on HWDB's side. ADR-0005's 10-worker rule was set against uploads.
# Sync is 2 GETs/chip, so we bump to 20 to cut wall-clock in half on
# backfills (~3 min → ~1.5 min for a 1.5k-chip family).
_DEFAULT_WORKERS = 20


@dataclass
class _ChipFetch:
    """Result of fetching one chip's tests."""
    serial_number: str
    part_id: str
    latest_rt_test_at: datetime | None = None
    latest_ln_test_at: datetime | None = None
    error: str = ""


def _parse_test_date(test_data: dict) -> datetime | None:
    """Parse the lab date from a deep-endpoint test record. Chart bins are
    daily or monthly, so the time-of-day component is decorative — we keep
    ``Test Date`` (YYYY/MM/DD or YYYY-MM-DD) and ignore ``Test Time`` so we
    accept both ``HH:MM`` and ``HH:MM:SS`` upstream formats.
    """
    date_s = test_data.get("Test Date")
    if not date_s:
        return None
    try:
        naive = datetime.strptime(date_s.replace("-", "/"), "%Y/%m/%d")
    except (ValueError, TypeError, AttributeError):
        return None
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _parse_created(created_s) -> datetime | None:
    """Parse HWDB's top-level ``created`` ISO timestamp. Fallback when the
    deep endpoint returns a record without ``test_data["Test Date"]``.
    """
    if not created_s:
        return None
    try:
        return datetime.fromisoformat(created_s)
    except (ValueError, TypeError):
        return None


def _test_record_dt(test_record: dict) -> datetime | None:
    """Best available datetime for a deep-endpoint test record: lab date if
    ``test_data["Test Date"]`` is present, else HWDB's ``created`` stamp.
    See ADR-0009.
    """
    return (
        _parse_test_date(test_record.get("test_data") or {})
        or _parse_created(test_record.get("created"))
    )


def _resolve_env_test_type_ids(api, part_type_id: str) -> dict[str, int]:
    """Look up the HWDB ``test_type_id`` for ``RoomT QC Test`` and
    ``CryoT QC Test`` on this part type. IDs vary by instance and family;
    cache externally if you call this in a loop.
    """
    body = api.get_test_types(part_type_id)
    by_name = {
        tt.get("name"): tt.get("id")
        for tt in (body.get("data") or [])
        if tt.get("name") and tt.get("id") is not None
    }
    out = {}
    for env, name in _ENV_TO_TEST_TYPE_NAME.items():
        if name in by_name:
            out[env] = int(by_name[name])
    return out


def _fetch_chip_tests(
    api, serial_number: str, part_id: str, test_type_ids: dict[str, int]
) -> _ChipFetch:
    """Fetch this chip's latest RT and LN tests using the **deep** endpoint
    (``/components/{part_id}/tests/{test_type_id}``).

    The summary endpoint (``/components/{part_id}/tests``) returns test-type
    metadata only — ``test_data`` is stripped. The deep endpoint is what
    Karla's ``GetItemTests`` in ``dune_ce_hwdb.py`` uses, and is the only
    way to get ``Test Date``. Two API calls per chip (one per env) when both
    test types are defined on the part type.
    """
    out = _ChipFetch(serial_number=serial_number, part_id=part_id)
    for env in ("RT", "LN"):
        tt_id = test_type_ids.get(env)
        if tt_id is None:
            continue
        try:
            body = api.get_tests(part_id, test_type_id=tt_id)
        except Exception as e:
            out.error = f"get_tests({env}) failed: {e}"
            continue
        latest = None
        for t in body.get("data") or []:
            dt = _test_record_dt(t)
            if dt is not None and (latest is None or dt > latest):
                latest = dt
        if env == "RT":
            out.latest_rt_test_at = latest
        else:
            out.latest_ln_test_at = latest
    return out


def _list_components(api, part_type_id: str) -> Iterator[dict]:
    """Paginate the component listing for a part_type. Yields one dict per
    chip: ``{"serial_number": ..., "part_id": ...}``.
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
            sn = row.get("serial_number")
            if not sn:
                continue
            yield {"serial_number": sn, "part_id": row.get("part_id")}
        pages = (body.get("pagination") or {}).get("pages", 1)
        if page >= pages or not rows:
            return
        page += 1


def _stamp_larasic_legacy_flags(hwdb_serials: dict) -> Iterator[str]:
    """Preserve the pre-HwdbChip behavior of the LArASIC sync: stamp
    ``is_in_hwdb`` on every local row, persist the ``hwdb_only_count`` on
    ``LarasicSyncState``, and clear ``qc_tests_uploaded`` on chips that
    left HWDB. Same logic as the original ``_sync_larasic`` in
    ``hwdb/views.py`` — extracted so the unified ``sync_family`` engine
    owns it.
    """
    now = timezone.now()
    chips = list(LArASIC.objects.all())
    local_serials = set()
    for chip in chips:
        local_serials.add(chip.serial_number)
        chip.is_in_hwdb = chip.serial_number in hwdb_serials
        chip.hwdb_checked_at = now
        if not chip.is_in_hwdb:
            chip.qc_tests_uploaded = False
    LArASIC.objects.bulk_update(
        chips, ["is_in_hwdb", "hwdb_checked_at", "qc_tests_uploaded"],
        batch_size=500,
    )
    in_hwdb = sum(1 for c in chips if c.is_in_hwdb)
    hwdb_only = len(set(hwdb_serials) - local_serials)
    state = LarasicSyncState.get()
    state.hwdb_only_count = hwdb_only
    state.synced_at = now
    state.save(update_fields=["hwdb_only_count", "synced_at"])
    yield (
        f"sync larasic: stamped is_in_hwdb on {len(chips)} local row(s) · "
        f"{in_hwdb} in HWDB · {hwdb_only} in HWDB only\n"
    )


def sync_family(
    family: str,
    *,
    part_type_id: str,
    api_base_url: str,
    bearer: str,
    force_full: bool = False,
    workers: int = _DEFAULT_WORKERS,
) -> Iterator[str]:
    """Sync ``HwdbChip`` rows for one family. Generator yielding progress lines.

    Algorithm (ADR-0008):
    1. List HWDB components for ``part_type_id``.
    2. Diff against existing ``HwdbChip(family=family)`` rows by serial.
    3. Parallel-fetch ``get_tests`` for new serials (or all serials if
       ``force_full``).
    4. Upsert ``HwdbChip`` rows; stamp ``last_seen_at`` on every listed chip.
    5. Persist ``HwdbSyncState(family)`` with counts.
    """
    state = HwdbSyncState.for_family(family)
    state.started_at = timezone.now()
    state.finished_at = None
    state.last_error = ""
    state.save()

    bootstrap_api = FnalDbApiClient(api_base_url, bearer)

    try:
        test_type_ids = _resolve_env_test_type_ids(bootstrap_api, part_type_id)
        if not test_type_ids:
            yield (
                f"sync {family}: no RT/LN test types defined on {part_type_id} "
                f"— aborting\n"
            )
            state.last_error = "no RT/LN test types on this part type"
            state.finished_at = timezone.now()
            state.save()
            return
        yield (
            f"sync {family}: test types resolved · "
            f"{', '.join(f'{k}={v}' for k, v in test_type_ids.items())}\n"
        )

        yield f"sync {family}: listing components for {part_type_id}\n"
        listing = list(_list_components(bootstrap_api, part_type_id))
        hwdb_serials = {row["serial_number"]: row["part_id"] for row in listing}
        yield f"sync {family}: {len(hwdb_serials)} chips in HWDB listing\n"

        existing = {
            r.serial_number: r
            for r in HwdbChip.objects.filter(family=family).only(
                "id", "serial_number", "part_id"
            )
        }
        if force_full:
            to_fetch = list(hwdb_serials.items())
            yield f"sync {family}: force full re-sync, {len(to_fetch)} chip(s) queued\n"
        else:
            to_fetch = [
                (sn, pid) for sn, pid in hwdb_serials.items() if sn not in existing
            ]
            yield f"sync {family}: {len(to_fetch)} new chip(s) to fetch\n"

        fetched: list[_ChipFetch] = []
        if to_fetch:
            tls = _thread_local_cls()

            def _init():
                tls.client = FnalDbApiClient(api_base_url, bearer)

            def _work(item):
                sn, pid = item
                return _fetch_chip_tests(tls.client, sn, pid, test_type_ids)

            done = 0
            with ThreadPoolExecutor(max_workers=workers, initializer=_init) as pool:
                futs = {pool.submit(_work, item): item for item in to_fetch}
                for fut in as_completed(futs):
                    result = fut.result()
                    fetched.append(result)
                    done += 1
                    if done % 50 == 0 or done == len(to_fetch):
                        yield f"sync {family}: fetched {done}/{len(to_fetch)} chip(s)\n"

        now = timezone.now()
        new_rows = []
        update_rows = []
        for f in fetched:
            existing_row = existing.get(f.serial_number)
            if existing_row is None:
                new_rows.append(
                    HwdbChip(
                        family=family,
                        serial_number=f.serial_number,
                        part_id=f.part_id or "",
                        part_type_id=part_type_id,
                        latest_rt_test_at=f.latest_rt_test_at,
                        latest_ln_test_at=f.latest_ln_test_at,
                        last_seen_at=now,
                    )
                )
            else:
                # force_full path: re-stamp test timestamps on an existing row.
                existing_row.part_id = f.part_id or existing_row.part_id
                existing_row.part_type_id = part_type_id
                existing_row.latest_rt_test_at = f.latest_rt_test_at
                existing_row.latest_ln_test_at = f.latest_ln_test_at
                existing_row.last_seen_at = now
                update_rows.append(existing_row)

        if new_rows:
            HwdbChip.objects.bulk_create(new_rows, batch_size=500)
        if update_rows:
            HwdbChip.objects.bulk_update(
                update_rows,
                ["part_id", "part_type_id", "latest_rt_test_at",
                 "latest_ln_test_at", "last_seen_at"],
                batch_size=500,
            )

        # Stamp last_seen_at on the *known* serials we didn't refetch.
        seen_known = [sn for sn in hwdb_serials if sn in existing and sn not in {f.serial_number for f in fetched}]
        if seen_known:
            HwdbChip.objects.filter(
                family=family, serial_number__in=seen_known
            ).update(last_seen_at=now)

        disappeared = HwdbChip.objects.filter(family=family).exclude(
            serial_number__in=hwdb_serials.keys()
        ).count()

        # LArASIC has a pre-HwdbChip ``is_in_hwdb`` flag on the per-chip
        # model (ADR-0003). Keep it in sync — the legacy /hwdb/larasic/ UI
        # still reads it, and downstream code may too. The same sync run
        # also persists the LarasicSyncState.hwdb_only_count surfaced on
        # /hwdb/larasic/'s summary card. Other families have no analog.
        if family == "larasic":
            yield from _stamp_larasic_legacy_flags(hwdb_serials)

        state.chips_total = len(hwdb_serials)
        state.chips_new = len(new_rows)
        state.chips_disappeared = disappeared
        state.finished_at = timezone.now()
        state.save()

        yield (
            f"sync {family}: done · "
            f"total={state.chips_total} new={state.chips_new} "
            f"disappeared={state.chips_disappeared}\n"
        )
    except Exception as e:
        logger.exception("sync_family(%s) failed", family)
        state.last_error = str(e)[:500]
        state.finished_at = timezone.now()
        state.save()
        yield f"sync {family}: ERROR · {e}\n"
        raise
