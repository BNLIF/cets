"""LArASIC HWDB upload — pure functions, no Django views.

The whole upload flow lives here so it's testable without spinning up
StreamingHttpResponse. Views layer streaming + UX on top.

Two upload modes (Q6/Q7 decisions):

- **Detailed** — when an analysis CSV exists for this chip's RTS run. We parse
  the CSV (``csv_parser.parse_csv``) and build a ~67-field datasheet matching
  Karla's. CSV is attached to the test record by default.
- **Simple** — when no CSV exists. 6-field datasheet from cets-resident fields
  only: Test Date, Test Time, LArASIC Serial Number, Test Location ("BNL"),
  Environment ("RT"/"LN"), Tray ID. Unknown fields are omitted, not faked
  (Operator Name, Test Result, Test Item, Configuration, power, channels).

The orchestrator (``upload_chip``) iterates warm + cold tests for one chip and
returns a ``ChipResult`` summarizing what happened. Callers loop over chips
themselves so they can stream per-chip progress.
"""

from __future__ import annotations

import logging
import os
import stat as _stat
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import local as _thread_local_cls
from typing import Callable, Iterable, Iterator, Optional

from django.conf import settings
from django.utils import timezone

from . import csv_parser

logger = logging.getLogger(__name__)

# Karla's date / time format on the wire — same in detailed and simple modes.
_DATE_FMT = "%Y/%m/%d"
_TIME_FMT = "%H:%M:%S"


# ---- Errors ---------------------------------------------------------------


class UploadError(Exception):
    """Per-chip upload failure that the orchestrator catches and reports.

    The streaming UI shows the message verbatim, so write it for humans.
    """


# ---- Result shapes --------------------------------------------------------


@dataclass(frozen=True)
class TestResult:
    env: str                # "RT" or "LN"
    mode: str               # "detailed", "simple", or "skipped" (already in HWDB)
    test_id: int | None     # HWDB test_id, or None if skipped/failed before POST
    csv_attached: bool      # True if attach_csv succeeded
    error: str | None       # human-readable per-test error, or None on ok
    skipped: bool = False   # True if we found an existing matching test, didn't repost


@dataclass(frozen=True)
class ChipResult:
    serial_number: str
    part_id: str | None     # HWDB part_id (existing or newly created), or None on hard failure
    created: bool           # True if we created the item this run (vs found existing)
    tests: list[TestResult] = field(default_factory=list)
    error: str | None = None  # set when the whole chip aborts (e.g. create failed)

    @property
    def ok(self) -> bool:
        return self.error is None and all(t.error is None for t in self.tests)


# ---- Settings helpers -----------------------------------------------------


def _larasic_defaults(instance: str) -> dict:
    """Return the LArASIC defaults resolved for ``instance`` ("prod" or "dev").

    Most fields are shared across HWDB instances; the ones that aren't (e.g.
    TSMC's ``manufacturer_id`` — confirmed via ``.idea/spike/hwdb_id_compare.py``)
    are stored as ``{"prod": ..., "dev": ...}`` dicts in settings, and this
    function picks the right value for the active instance.
    """
    raw = settings.HWDB_COMPONENT_DEFAULTS["larasic"]
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict) and set(v.keys()) <= {"prod", "dev"}:
            if instance not in v:
                raise UploadError(
                    f"larasic default {k!r} has no value for instance {instance!r}"
                )
            out[k] = v[instance]
        else:
            out[k] = v
    return out


def resolve_test_type_id(api, part_type_id: str, name: str) -> int:
    """Look up the test-type id by name on the active instance.

    Dev and prod use different ids (Dev ``RoomT QC Test`` = 863, ``CryoT`` = 864
    at time of writing). Cache externally if you call this in a loop.
    """
    body = api.get_test_types(part_type_id)
    for tt in body.get("data") or []:
        if tt.get("name") == name:
            return int(tt["id"])
    raise UploadError(
        f"test type {name!r} not found on part type {part_type_id}"
    )


# ---- HWDB primitive wrappers ---------------------------------------------


def find_item(api, part_type_id: str, serial_number: str) -> Optional[dict]:
    """Return the existing component dict (``part_id``, ``qaqc_uploaded``,
    ``status``, …) if a chip with this serial already exists, else ``None``.

    Returning the full dict (not just the part_id) lets the upload orchestrator
    see the chip's current flags so it can skip redundant PATCHes — important
    because HWDB records a specifications-history snapshot on every PATCH.
    """
    return api.find_component_by_serial(part_type_id, serial_number) or None


def _create_payload(chip, part_type_id: str, defaults: dict) -> dict:
    """Build the create-item JSON. See Karla's ItemToUploadJSON.

    Takes ``defaults`` (already resolved for the current instance) — see
    ``_larasic_defaults``. We include ``status`` in the create payload —
    probe 1 confirmed HWDB accepts it silently (not flagged as "extra fields
    not permitted"). This saves one PATCH per fresh chip and avoids a second
    specifications history entry that the separate ``set_status`` PATCH
    would create (HWDB's PATCH replaces specs, so we'd have to re-send LOT N).
    """
    d = defaults
    return {
        "component_type": {"part_type_id": part_type_id},
        "serial_number": chip.serial_number,
        "country_code": d["country_code"],
        "comments": "",
        "institution": {"id": d["institution_id"]},
        "manufacturer": {"id": d["manufacturer_id"]},
        "specifications": {"DATA": {"LOT N": chip.tray_id or ""}},
        "status": {"id": d["initial_status_id"]},
    }


def create_item(api, chip, part_type_id: str, defaults: dict) -> str:
    """POST a new component. Returns the HWDB ``part_id``.

    ``defaults`` is the per-instance-resolved dict from ``_larasic_defaults``.
    """
    payload = _create_payload(chip, part_type_id, defaults)
    body = api.create_component(part_type_id, payload)
    if body.get("status") != "OK":
        raise UploadError(
            f"create failed for {chip.serial_number}: {body.get('data') or body}"
        )
    part_id = body.get("part_id")
    if not part_id:
        raise UploadError(
            f"create OK but no part_id in response for {chip.serial_number}: {body}"
        )
    return part_id


def set_status(api, part_id: str, status_id: int) -> None:
    """PATCH the item to set its status.

    Kept around for future enrichment workflows (the fresh-chip create path
    embeds ``status`` directly in the create payload). Body includes
    ``part_id`` (HWDB rejected it without on first try) and only the field
    being changed — we deliberately omit ``specifications`` so HWDB doesn't
    record a spurious specifications history entry on every status flip.
    """
    body = api.patch_component(
        part_id,
        {"part_id": part_id, "status": {"id": status_id}},
    )
    if body.get("status") == "ERROR":
        raise UploadError(f"status patch failed for {part_id}: {body.get('data')}")


def set_qaqc_uploaded(api, part_id: str) -> None:
    """PATCH the item to set ``qaqc_uploaded=True``.

    Specifications history should reflect actual hardware-spec changes, not
    every PATCH — so we omit ``specifications`` from this PATCH body. If HWDB
    rejects with 422 because the field is required, the surfaced error
    (api_client now includes the body) will tell us exactly and we'll add it
    back. If it accepts: one spec history entry per chip (from create), and
    qaqc patches don't add new ones.
    """
    body = api.patch_component(
        part_id,
        {"part_id": part_id, "qaqc_uploaded": True},
    )
    if body.get("status") == "ERROR":
        raise UploadError(
            f"qaqc_uploaded patch failed for {part_id}: {body.get('data')}"
        )


def set_location(api, part_id: str, institution_id: int, arrived: datetime) -> None:
    payload = {
        "arrived": arrived.strftime("%Y-%m-%d %H:%M:%S"),
        "comments": "",
        "location": {"id": institution_id},
    }
    body = api.post_location(part_id, payload)
    if body.get("status") not in ("OK", None):
        raise UploadError(f"location post failed for {part_id}: {body.get('data')}")


# ---- Datasheets -----------------------------------------------------------


def _fmt_dt(dt: datetime) -> tuple[str, str]:
    """``datetime`` → (``YYYY/MM/DD``, ``HH:MM:SS``) — matches earlier HWDB records."""
    return dt.strftime(_DATE_FMT), dt.strftime(_TIME_FMT)


def build_datasheet_simple(chip, env: str, *, operator_name: str = "") -> dict:
    """Simple-mode datasheet — chips without analysis CSVs (Q6).

    HWDB's RoomT/CryoT QC Test schema (verified 2026-05-28 against D08100100004
    test types 873/874) requires four fields: ``Test Date``, ``Test Time``,
    ``Test Location``, ``Operator Name``. Missing any of them returns 400
    ``"The test specifications do not match the test type definition!"``.
    Extras are tolerated (Karla's 67-field detailed shape works fine).

    We send the four required fields plus a few extras (``LArASIC Serial
    Number``, ``Environment``, ``Tray ID``) so the record stays
    self-identifying when queried.
    """
    if env == "RT":
        ts = chip.warm_tested_at
    elif env == "LN":
        ts = chip.cold_tested_at
    else:
        raise ValueError(f"bad env: {env}")
    if ts is None:
        raise UploadError(
            f"no {env} timestamp on chip {chip.serial_number}; cannot build datasheet"
        )
    date_s, time_s = _fmt_dt(ts)
    return {
        # Schema-required (D08100100004 RoomT/CryoT QC Test):
        "Test Date": date_s,
        "Test Time": time_s,
        "Test Location": "BNL",
        "Operator Name": operator_name or "N/A",
        # Extras for traceability — HWDB accepts them:
        "LArASIC Serial Number": chip.serial_number,
        "Environment": env,
        "Tray ID": chip.tray_id or "",
    }


def build_datasheet_detailed(chip, csv_path: Path) -> dict:
    """Karla-shape datasheet from a parsed CSV. ~67 fields including channels."""
    parsed = csv_parser.parse_csv(csv_path)
    power = parsed["power"]
    channels = parsed["channels"]
    total_power = power["vdda_P"] + power["vddo_P"] + power["vddp_P"]

    sheet: dict = {
        "Test Date": parsed["test_date"],
        "Test Time": parsed["test_time"],
        "LArASIC Serial Number": parsed["serial_hwdb"],
        "Test Location": parsed["test_location"],
        "Operator Name": parsed["operator_name"],
        "Environment": parsed["env"],
        "RTS ID": parsed["rts_id"],
        "Tray ID": parsed["tray_id"],
        "Position on Tray": parsed["fe_in_tray"],
        "DAT SN": parsed["dat_sn"],
        "FE in Tray": parsed["fe_in_tray"],
        "Socket #": parsed["socket"],
        "Test Item": csv_parser.TARGET_TEST_ITEM,
        "Configuration": csv_parser.TARGET_CONFIG,
        "vdda_P": power["vdda_P"],
        "vddo_P": power["vddo_P"],
        "vddp_P": power["vddp_P"],
        "Power Consumption": total_power,
        "Test Result": "PASS",  # Karla's default; ocr_results.bin enrichment is post-MVP
    }
    for ch in range(16):
        v = channels[ch]
        sheet[f"CH{ch} Pedestal"] = v["ped"]
        sheet[f"CH{ch} Pulse Amplitude"] = v["pulse_amplitude"]
        sheet[f"CH{ch} RMS"] = v["rms"]
    return sheet


# ---- Test post + attach --------------------------------------------------


def _is_detailed_record(test_data: dict) -> bool:
    """Detailed records carry per-channel readings; simple-mode records don't.
    ``CH0 Pedestal`` is the cheapest signature field to check.
    """
    return "CH0 Pedestal" in test_data


def find_existing_test(
    api, part_id: str, test_type_id: int, test_date: str, test_time: str,
    *, posting_mode: str = "simple", force_csv_attach: bool = False,
) -> int | None:
    """Return the ``test_id`` that would shadow this new post, else ``None``.

    HWDB does NOT dedup test POSTs server-side (probe 3, 2026-05-28): the
    same ``(type, date, time)`` POSTed twice creates two records. So every
    upload must check before posting — Karla's ``isTestInHWDB`` flow.

    Shape-aware matching: simple and detailed-mode records share the same
    ``(type, date, time)`` (both derive from the chip's warm/cold timestamp).
    So matching on those three alone would block the "simple now, detailed
    when CSV arrives" upgrade. Rules:

    - Posting **simple**: any existing record (simple or detailed) shadows
      the new post — detailed already supersedes simple.
    - Posting **detailed** over a **simple** existing record: not a match;
      the detailed upload should go through (upgrades the chip's QA/QC story).
      HWDB will hold both records in history; queries return the latest.
    - Posting **detailed** over a **detailed** existing record: dedup as
      before — unless ``force_csv_attach=True``, in which case we re-post
      to retry the CSV attachment (useful when a prior detailed upload
      posted the test but the CSV attach silently failed).
    """
    body = api.get_tests(part_id, test_type_id=test_type_id, history=True)
    for t in body.get("data") or []:
        td = t.get("test_data") or {}
        if td.get("Test Date") != test_date or td.get("Test Time") != test_time:
            continue
        existing_detailed = _is_detailed_record(td)
        if posting_mode == "simple":
            return int(t["id"])
        # posting_mode == "detailed":
        if not existing_detailed:
            # Existing is simple, we're upgrading to detailed → don't dedup.
            continue
        if force_csv_attach:
            # User wants to re-post detailed to retry CSV attach → don't dedup.
            continue
        return int(t["id"])
    return None


def post_test(api, part_id: str, test_type_name: str, datasheet: dict, comments: str) -> int:
    payload = {
        "test_type": test_type_name,
        "comments": comments,
        "test_data": datasheet,
    }
    body = api.post_test(part_id, payload)
    if body.get("status") != "OK":
        raise UploadError(
            f"test post failed for {part_id}: {body.get('data') or body}"
        )
    test_id = body.get("test_id")
    if test_id is None:
        raise UploadError(f"test post OK but no test_id: {body}")
    return int(test_id)


def attach_csv(api, test_id: int, csv_path: Path) -> bool:
    try:
        body = api.attach_test_image(test_id, str(csv_path))
    except Exception as e:
        logger.warning("attach_csv to test %s failed: %s", test_id, e)
        return False
    if body.get("status") == "ERROR":
        logger.warning("attach_csv to test %s ERROR: %s", test_id, body.get("data"))
        return False
    return True


# ---- CSV discovery -------------------------------------------------------


def _find_csv(rts_root: Path, chip, env: str) -> Optional[Path]:
    """Locate Karla-format CSV for this chip/env, if one exists.

    Looks under ``RTS_DIR/<tray_id>/results/`` (which may not exist; per
    cets's RTS layout the analysis step is manual). The CSV filename starts
    with the chip's serial in underscored form and ends in ``_RT.csv`` or
    ``_LN.csv``.
    """
    if not chip.tray_id:
        return None
    results_dir = rts_root / chip.tray_id / "results"
    if not results_dir.is_dir():
        return None
    suffix = f"_{env}.csv"
    sn_us = chip.serial_number.replace("-", "_")
    matches = sorted(
        p for p in results_dir.glob(f"{sn_us}_*{suffix}") if p.is_file()
    )
    return matches[-1] if matches else None  # latest by sorted name


# ---- Tray-level CSV discovery (for the upload UI) -----------------------


# Per-process L1 cache: ``{tray_id: (results_dir_mtime, {(serial, env): Path})}``.
# Avoids the DB round-trip for L2 (TrayCsvCache) inside the same gunicorn
# worker. Each worker has its own L1; that's fine, L2 catches misses.
_csv_cache: dict[str, tuple[float, dict[tuple[str, str], Path]]] = {}


def _scan_results_dir(results_dir: Path) -> dict[tuple[str, str], Path]:
    out: dict[tuple[str, str], Path] = {}
    for p in sorted(results_dir.glob("*.csv")):
        if not p.is_file():
            continue
        try:
            info = csv_parser.parse_filename(p)
        except Exception:
            continue
        env = (info.get("env") or "").upper()
        serial = info.get("serial")
        if env in ("RT", "LN") and serial:
            out[(serial, env)] = p
    return out


def _csvs_to_json(csvs: dict[tuple[str, str], Path]) -> dict[str, str]:
    """Serialize for the L2 model: ``{"sn|env": filename}`` (basename only)."""
    return {f"{sn}|{env}": p.name for (sn, env), p in csvs.items()}


def _csvs_from_json(data: dict[str, str], results_dir: Path) -> dict[tuple[str, str], Path]:
    out: dict[tuple[str, str], Path] = {}
    for k, fname in data.items():
        sn, _, env = k.partition("|")
        if sn and env:
            out[(sn, env)] = results_dir / fname
    return out


def scan_tray_csvs(rts_root: Optional[Path], tray_id: str) -> dict[tuple[str, str], Path]:
    """Return every analysis CSV under ``RTS_DIR/<tray_id>/results/``, keyed
    by ``(serial_number, env)``. Empty dict if the results dir doesn't exist.

    Two-tier cache:

    - **L1** (in-process dict) — zero overhead within a worker.
    - **L2** (``hwdb.models.TrayCsvCache``) — persists across restarts and is
      shared across gunicorn workers. After a deploy each tray pays its full
      rescan cost at most once, *not* once-per-worker-per-restart.

    Both tiers key on the results dir's mtime: when the analysis step writes
    a new CSV, Linux bumps the dir mtime, the cache misses, and a single
    rescan rewrites both tiers atomically.
    """
    if not rts_root or not tray_id:
        return {}
    results_dir = rts_root / tray_id / "results"

    # Single os.stat — one SMB round-trip — that gives us both "does the dir
    # exist?" and "what's its mtime?". On a fast filesystem this is trivial;
    # on the SMB-mounted RTS_DIR each stat costs 50–200ms, so halving the
    # syscall count is meaningful for a cache-hit path.
    try:
        st = os.stat(results_dir)
    except FileNotFoundError:
        _csv_cache.pop(tray_id, None)
        from ..models import TrayCsvCache
        TrayCsvCache.objects.filter(tray_id=tray_id).delete()
        return {}
    except OSError:
        return {}
    if not _stat.S_ISDIR(st.st_mode):
        return {}
    mtime = st.st_mtime

    # L1
    cached = _csv_cache.get(tray_id)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    # L2
    from ..models import TrayCsvCache
    row = TrayCsvCache.objects.filter(tray_id=tray_id).first()
    if row is not None and row.dir_mtime == mtime:
        out = _csvs_from_json(row.csvs, results_dir)
        _csv_cache[tray_id] = (mtime, out)
        return out

    # Miss: rescan and write both tiers.
    out = _scan_results_dir(results_dir)
    _csv_cache[tray_id] = (mtime, out)
    TrayCsvCache.objects.update_or_create(
        tray_id=tray_id,
        defaults={"dir_mtime": mtime, "csvs": _csvs_to_json(out)},
    )
    return out


def csv_attach_pending(chip, csvs: dict[tuple[str, str], Path]) -> bool:
    """True if an analysis CSV now exists for this chip but isn't attached yet.

    ``csvs`` is the ``{(serial_number, env): Path}`` dict from
    ``scan_tray_csvs``. A chip is CSV-pending when an RT (resp. LN) CSV is
    available and its ``warm_csv_attached_at`` (resp. ``cold_csv_attached_at``)
    is still NULL. This mirrors the index page's ``_annotate_to_upload`` so the
    tray detail view, the bulk-upload filter, and the worklist all agree on
    what "done" means: tests uploaded *and* no waiting CSV to attach.
    """
    sn = chip.serial_number
    if (sn, "RT") in csvs and chip.warm_csv_attached_at is None:
        return True
    if (sn, "LN") in csvs and chip.cold_csv_attached_at is None:
        return True
    return False


def clear_csv_cache() -> None:
    """Drop the in-process L1 cache. Tests call this between runs.

    Does NOT touch the DB-backed L2 — use ``TrayCsvCache.objects.all().delete()``
    if you need to flush that too.
    """
    _csv_cache.clear()


def tray_has_analysis(rts_root: Optional[Path], tray_id: str) -> bool:
    """Live check — stats the SMB-mounted directory. Use ``trays_with_analysis``
    for batch queries (e.g. the upload index) so we don't pay one SMB round-trip
    per tray.
    """
    if not rts_root or not tray_id:
        return False
    return (rts_root / tray_id / "results").is_dir()


def trays_with_analysis(tray_ids: Iterable[str]) -> set[str]:
    """Return the subset of ``tray_ids`` that have a populated TrayCsvCache
    row — i.e. a prior scan saw at least one CSV in their ``results/``.

    Used by the upload index so it stays one DB query instead of N SMB stats.
    Slightly stale: a tray whose ``results/`` was deleted after the last scan
    still shows here until someone hits its detail page (which re-runs
    ``scan_tray_csvs`` and drops the L2 row). For an index hint, acceptable.
    """
    from ..models import TrayCsvCache
    ids = list(tray_ids)
    if not ids:
        return set()
    return set(
        TrayCsvCache.objects
        .filter(tray_id__in=ids)
        .exclude(csvs={})  # empty results/ ≠ "has analysis"
        .values_list("tray_id", flat=True)
    )


# ---- Orchestrator --------------------------------------------------------


def upload_chip(
    api,
    chip,
    *,
    part_type_id: str,
    instance: str,
    rts_root: Optional[Path] = None,
    attach_csvs: bool = True,
    test_type_ids: Optional[dict[str, int]] = None,
    operator_name: str = "",
    force_csv_attach: bool = False,
) -> ChipResult:
    """Upload one chip end-to-end: find-or-create + status + location + tests.

    ``instance`` is "prod" or "dev" — used to resolve per-instance defaults
    (currently the TSMC manufacturer_id; other ids are shared).
    ``test_type_ids`` is ``{"RT": <id>, "LN": <id>}``; pass it in so a batch
    caller resolves names→ids once and reuses across chips. If omitted we
    resolve per call (one extra GET per chip).
    """
    d = _larasic_defaults(instance)

    # Resolve test type ids if the caller didn't pre-resolve them.
    if test_type_ids is None:
        test_type_ids = {
            "RT": resolve_test_type_id(api, part_type_id, d["warm_test_name"]),
            "LN": resolve_test_type_id(api, part_type_id, d["cold_test_name"]),
        }

    try:
        existing = find_item(api, part_type_id, chip.serial_number)
        created = False
        # Read the current qaqc_uploaded so we don't re-PATCH it later if it's
        # already True (HWDB writes a spec-history snapshot on every PATCH).
        # Freshly-created chips default to qaqc_uploaded=False.
        qaqc_already_true = False
        if existing is None:
            # status is now embedded in the create payload (probe 1, 2026-05-28),
            # so no separate set_status PATCH — one fewer call, one fewer
            # specifications history entry.
            part_id = create_item(api, chip, part_type_id, d)
            created = True
            arrived = chip.warm_tested_at or chip.cold_tested_at or timezone.now()
            set_location(api, part_id, d["institution_id"], arrived)
        else:
            part_id = existing["part_id"]
            qaqc_already_true = bool(existing.get("qaqc_uploaded"))
    except UploadError as e:
        return ChipResult(serial_number=chip.serial_number, part_id=None, created=False, error=str(e))
    except Exception as e:
        logger.exception("create-flow crashed for %s", chip.serial_number)
        return ChipResult(serial_number=chip.serial_number, part_id=None, created=False, error=f"create crashed: {e}")

    tests: list[TestResult] = []
    for env in ("RT", "LN"):
        ts = chip.warm_tested_at if env == "RT" else chip.cold_tested_at
        if ts is None:
            continue
        csv_path = _find_csv(rts_root, chip, env) if rts_root else None
        mode = "detailed" if csv_path else "simple"
        try:
            if mode == "detailed":
                sheet = build_datasheet_detailed(chip, csv_path)
                comments = (
                    "Warm QC Test results" if env == "RT" else "Cold QC Test results"
                )
            else:
                sheet = build_datasheet_simple(chip, env, operator_name=operator_name)
                comments = (
                    "Warm QC test (simple mode — no CSV)"
                    if env == "RT"
                    else "Cold QC test (simple mode — no CSV)"
                )
            test_type_name = d["warm_test_name"] if env == "RT" else d["cold_test_name"]

            # HWDB doesn't dedup (probe 3, 2026-05-28). Skip if an existing
            # record of this type would shadow this one. Shape-aware: detailed
            # uploads can supersede simple ones (see find_existing_test).
            # Freshly-created chips can't have prior tests, so skip the GET.
            existing_id = (
                None if created else find_existing_test(
                    api, part_id, test_type_ids[env],
                    sheet["Test Date"], sheet["Test Time"],
                    posting_mode=mode,
                    force_csv_attach=force_csv_attach,
                )
            )
            if existing_id is not None:
                tests.append(
                    TestResult(
                        env=env, mode="skipped", test_id=existing_id,
                        csv_attached=False, error=None, skipped=True,
                    )
                )
                continue

            test_id = post_test(api, part_id, test_type_name, sheet, comments)
            attached = False
            if csv_path and attach_csvs:
                attached = attach_csv(api, test_id, csv_path)
            tests.append(
                TestResult(
                    env=env, mode=mode, test_id=test_id,
                    csv_attached=attached, error=None,
                )
            )
        except UploadError as e:
            tests.append(
                TestResult(env=env, mode=mode, test_id=None, csv_attached=False, error=str(e))
            )
        except Exception as e:
            logger.exception("test post crashed for %s %s", chip.serial_number, env)
            tests.append(
                TestResult(
                    env=env, mode=mode, test_id=None, csv_attached=False,
                    error=f"crashed: {e}",
                )
            )

    # qaqc_uploaded means "the real QA/QC analysis (CSV-backed detailed record)
    # is in HWDB" — so we only flip it True after a successful detailed-mode
    # POST. Simple-mode records are placeholders; the flag stays False.
    # Also: HWDB writes a new spec history snapshot on every component PATCH,
    # so this stays as a one-time event tied to real enrichment, not every
    # upload run.
    any_detailed_test_posted = any(
        t.mode == "detailed" and t.test_id is not None and not t.skipped and t.error is None
        for t in tests
    )
    if any_detailed_test_posted and not qaqc_already_true:
        try:
            set_qaqc_uploaded(api, part_id)
        except Exception as e:
            logger.warning("set_qaqc_uploaded failed for %s: %s", part_id, e)

    return ChipResult(
        serial_number=chip.serial_number, part_id=part_id, created=created, tests=tests
    )


# ---- Parallel orchestrator ----------------------------------------------


def iter_upload_chips_parallel(
    chips: list,
    *,
    client_factory: Callable[[], object],
    part_type_id: str,
    instance: str,
    rts_root: Optional[Path] = None,
    attach_csvs: bool = True,
    test_type_ids: dict[str, int],
    operator_name: str = "",
    workers: int = 10,
    force_csv_attach: bool = False,
) -> Iterator[tuple]:
    """Run ``upload_chip`` across ``chips`` in a thread pool. Yields
    ``(chip, ChipResult)`` tuples in **completion order**, not input order.

    Each worker thread builds its own API client via ``client_factory``
    (one ``requests.Session`` per thread — Sessions aren't fully
    thread-safe). The factory captures bearer + base_url so this module
    doesn't import the api_client class.

    ``test_type_ids`` is resolved once by the caller and reused across
    chips. Exceptions from ``upload_chip`` are caught and converted to a
    ``ChipResult`` with ``error`` set, matching the serial path's
    continue-on-error policy.
    """
    workers = max(1, min(32, workers))
    tls = _thread_local_cls()

    def _init():
        tls.client = client_factory()

    def _work(chip):
        return upload_chip(
            tls.client, chip,
            part_type_id=part_type_id,
            instance=instance,
            rts_root=rts_root,
            attach_csvs=attach_csvs,
            test_type_ids=test_type_ids,
            operator_name=operator_name,
            force_csv_attach=force_csv_attach,
        )

    with ThreadPoolExecutor(max_workers=workers, initializer=_init) as pool:
        futures = {pool.submit(_work, c): c for c in chips}
        for fut in as_completed(futures):
            chip = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                logger.exception("upload_chip crashed for %s", chip.serial_number)
                result = ChipResult(
                    serial_number=chip.serial_number,
                    part_id=None,
                    created=False,
                    error=f"crashed: {e}",
                )
            yield chip, result
