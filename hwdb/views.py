import logging
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

from decouple import config as env_config
from django.conf import settings
from django.db.models import Count, Max, Q
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.models import LArASIC, FEMB, FembTest

from .api_client import FnalDbApiClient
from .fnal import flow
from .fnal import session as fnal_session
from .fnal.bearer import FnalLinkRequired, FnalUnavailable, mint_for
from .fnal.session import LINK_KEY
from .instance import SESSION_KEY, active_instance, active_profile
from .models import LarasicSyncState
from .upload import larasic as upload_lib

logger = logging.getLogger(__name__)
GENERIC_ERROR = "Failed to fetch data from the Hardware Database."
FNAL_UNAVAILABLE = "FNAL authentication service is unavailable. Please try again later."

# How long a started device flow stays valid before the user must reload.
DEVICE_FLOW_LIFETIME = timedelta(minutes=10)


def home(request):
    """HWDB section landing: a card per component type.

    Static (no HWDB API call), so it is not FNAL-gated — a logged-in user can
    see what the section offers; the per-type Display view does the gating.
    Only LArASIC is wired up; its part type follows the configured instance.
    The rest are "coming soon" and get an instance-resolved id when activated.
    """
    profile = active_profile(request)
    component_types = [
        {
            "name": "LArASIC",
            "description": "16-ch cold front-end ASIC",
            "part_type_id": profile["larasic_part_type"],
            "active": True,
            "url": reverse("hwdb:larasic"),
        },
        {"name": "ColdADC", "description": "12-bit cold ADC", "part_type_id": None, "active": False},
        {"name": "COLDATA", "description": "Serializer / control", "part_type_id": None, "active": False},
        {"name": "FEMB", "description": "Frontend Motherboard", "part_type_id": None, "active": False},
        {"name": "Cable", "description": "Cold flex cable", "part_type_id": None, "active": False},
    ]
    return render(
        request,
        "hwdb/home.html",
        {
            "component_types": component_types,
            "active_instance": active_instance(request),
            "instances": list(settings.HWDB_PROFILES),
            "page": "hwdb",
        },
    )


def set_instance(request):
    """Set the per-session HWDB instance override and return to where you were."""
    if request.method == "POST":
        choice = request.POST.get("instance")
        if choice in settings.HWDB_PROFILES:
            request.session[SESSION_KEY] = choice
    return redirect(_safe_next(request, reverse("hwdb:home")))


def larasic_view(request):
    """Browse local LArASIC chips against HWDB. Same grouped tray/FEMB layout as
    the general /larasic/ page plus an extra "In HWDB" column and sync stats.

    The is_in_hwdb flag is local-only, so the page itself is not FNAL-gated.
    Only the Sync button hits the API.
    """
    from core.views import _grouped_chip_response

    qs = LArASIC.objects.all()
    total = qs.count()
    in_hwdb = qs.filter(is_in_hwdb=True).count()
    last_synced = qs.aggregate(Max("hwdb_checked_at"))["hwdb_checked_at__max"]
    hwdb_only = LarasicSyncState.get().hwdb_only_count

    return _grouped_chip_response(
        request,
        model=LArASIC,
        family_label="LArASIC",
        family_title="LArASIC · HWDB sync",
        family_subtitle="Local chips vs HWDB",
        chips_per_femb=8,
        has_tray_view=True,
        page_id="hwdb",
        include_to_upload=True,
        tray_drill_url_name="hwdb:upload_tray",
        full_template="hwdb/larasic.html",
        extra_context={
            "total": total,
            "in_hwdb": in_hwdb,
            "to_upload": total - in_hwdb,
            "hwdb_only": hwdb_only,
            "last_synced": last_synced,
            "larasic_part_type": active_profile(request)["larasic_part_type"],
            "active_instance": active_instance(request),
            "instances": list(settings.HWDB_PROFILES),
        },
    )


def _sync_larasic(api_client, part_type_id):
    """Page the HWDB LArASIC components and mark each local chip in/out of
    HWDB by serial number. Also records the count of HWDB serials with no
    local record. Returns (total, in_hwdb, to_upload, hwdb_only)."""
    hwdb_serials = set()
    page = 1
    while True:
        resp = api_client._make_request(
            "GET", f"component-types/{part_type_id}/components?page={page}&size=500"
        )
        rows = resp.get("data", [])
        for row in rows:
            sn = row.get("serial_number")
            if sn:
                hwdb_serials.add(sn)
        pages = resp.get("pagination", {}).get("pages", 1)
        if page >= pages or not rows:
            break
        page += 1

    now = timezone.now()
    chips = list(LArASIC.objects.all())
    local_serials = set()
    for chip in chips:
        local_serials.add(chip.serial_number)
        chip.is_in_hwdb = chip.serial_number in hwdb_serials
        chip.hwdb_checked_at = now
        # If a chip leaves HWDB, its QC tests left with it — clear the flag so
        # the next upload run walks it again.
        if not chip.is_in_hwdb:
            chip.qc_tests_uploaded = False
    LArASIC.objects.bulk_update(
        chips, ["is_in_hwdb", "hwdb_checked_at", "qc_tests_uploaded"], batch_size=500
    )
    in_hwdb = sum(1 for c in chips if c.is_in_hwdb)
    hwdb_only = len(hwdb_serials - local_serials)

    state = LarasicSyncState.get()
    state.hwdb_only_count = hwdb_only
    state.synced_at = now
    state.save(update_fields=["hwdb_only_count", "synced_at"])

    return len(chips), in_hwdb, len(chips) - in_hwdb, hwdb_only


@require_POST
def larasic_sync_view(request):
    """Run the HWDB sync, then return to the LArASIC summary.

    ``is_in_hwdb`` means "exists in the PRODUCTION HWDB" (the upload target),
    so this only acts on the prod instance — a dev session is a no-op, leaving
    the prod worklist intact. FNAL-gated; an unlinked user is redirected to
    link (returning to the summary, not here)."""
    if active_instance(request) != "prod":
        return redirect(reverse("hwdb:larasic"))
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': reverse('hwdb:larasic')})}")
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    prod = settings.HWDB_PROFILES["prod"]
    api_client = FnalDbApiClient(prod["api"], bearer)
    try:
        _sync_larasic(api_client, prod["larasic_part_type"])
    except Exception:
        logger.exception("HWDB LArASIC sync failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})
    return redirect(reverse("hwdb:larasic"))


def _safe_next(request, default):
    """Return the next= target (GET or POST) if it's a safe internal URL."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return default


def fnal_link_view(request):
    """Start a FNAL device flow and render the polling page.

    Stashes the in-progress flow (and where to return) in the session; the
    page polls fnal_link_poll_view until vault completes the login.
    """
    next_url = _safe_next(request, reverse("hwdb:home"))
    try:
        start = flow.start()
    except Exception:
        logger.exception("FNAL device-flow start failed")
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    fnal_session.set_flow(
        request, start.poll_body, timezone.now() + DEVICE_FLOW_LIFETIME, next_url
    )
    return render(
        request,
        "hwdb/link.html",
        {
            "auth_url": start.auth_url,
            "user_code": start.user_code,
            "poll_url": reverse("hwdb:link_poll"),
        },
    )


def fnal_link_poll_view(request):
    """One poll tick. Returns JSON: pending / ok (+next) / error."""
    state = fnal_session.get_flow(request)
    if not state:
        return JsonResponse(
            {"status": "error", "detail": "no link in progress; reload to start"},
            status=404,
        )
    if datetime.fromisoformat(state["expires_at"]) <= timezone.now():
        fnal_session.clear_flow(request)
        return JsonResponse(
            {"status": "error", "detail": "link timed out; reload to start again"},
            status=410,
        )

    try:
        result = flow.poll(state["poll_body"])
    except Exception:
        logger.exception("FNAL device-flow poll failed")
        return JsonResponse({"status": "error", "detail": FNAL_UNAVAILABLE}, status=502)

    if result.outcome in ("pending", "slow_down"):
        return JsonResponse({"status": "pending"})

    try:
        login = flow.complete(result.auth or {})
    except Exception:
        logger.exception("FNAL device-flow completion failed")
        return JsonResponse({"status": "error", "detail": FNAL_UNAVAILABLE}, status=502)

    fnal_session.store_link(request, login)
    next_url = state.get("next") or reverse("hwdb:home")
    fnal_session.clear_flow(request)
    return JsonResponse({"status": "ok", "next": next_url})


def with_fnal_bearer(view):
    """Mint a per-request FNAL bearer and pass it to the view.

    Owns the Q9 failure surface in one place:
    - no/expired/undecryptable/rejected token -> redirect to the link page
      with a ?next back to here.
    - vault unreachable / transient -> the generic hwdb error page (re-linking
      wouldn't help).
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            bearer = mint_for(request)
        except FnalLinkRequired:
            link = reverse("hwdb:link")
            return redirect(f"{link}?{urlencode({'next': request.get_full_path()})}")
        except FnalUnavailable:
            return render(
                request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE}
            )
        return view(request, bearer, *args, **kwargs)

    return wrapper


@with_fnal_bearer
def component_list_view(request, bearer, component_type_id=None):
    profile = active_profile(request)
    api_client = FnalDbApiClient(profile["api"], bearer)

    # If component_type_id is not provided in the URL, use a default or raise an error
    if not component_type_id:
        component_type_id = "D08100400001"  # Default component type ID

    # Get page number from request, default to 1
    page = int(request.GET.get("page", 1))
    size = int(request.GET.get("size", 100))

    # Construct the endpoint with pagination parameters
    endpoint = f"component-types/{component_type_id}/components?page={page}&size={size}"

    try:
        raw_response = api_client._make_request("GET", endpoint)

        component_type_name = raw_response.get("component_type", {}).get(
            "name", "Unknown Component Type"
        )
        components = raw_response.get("data", [])

        # Convert 'created' string to datetime object
        for component in components:
            if "created" in component and component["created"]:
                # Handle ISO 8601 format with microseconds and timezone offset
                component["created"] = datetime.fromisoformat(component["created"])

        pagination_data = raw_response.get("pagination", {})
        current_page = pagination_data.get("page", 1)
        page_size = pagination_data.get("page_size", 100)
        total_pages = pagination_data.get("pages", 1)

        next_page = current_page + 1 if current_page < total_pages else None
        prev_page = current_page - 1 if current_page > 1 else None
        first_page = 1
        last_page = total_pages

        context = {
            "component_type_name": component_type_name,
            "components": components,
            "current_page": current_page,
            "next_page": next_page,
            "prev_page": prev_page,
            "first_page": first_page,
            "last_page": last_page,
            "page_size": page_size,
            "current_component_type_id": component_type_id,
            "hwdb_ui_base": profile["ui"],
            "active_instance": active_instance(request),
            "page": "hwdb",
        }
        return render(request, "hwdb/component_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})


# Generic HWDB tree browse (subsystems -> part types -> components). Demoted
# from primary nav to the landing's "More" card in #13, but still useful for
# poking around the raw HWDB structure.
@with_fnal_bearer
def subsystem_list_view(request, bearer, part1=None, part2=None):
    api_client = FnalDbApiClient(active_profile(request)["api"], bearer)
    part1 = part1 or "D"
    part2 = part2 or "081"
    try:
        raw_response = api_client.get_subsystems(part1, part2)
        subsystems = raw_response.get("data", [])
        for subsystem in subsystems:
            if subsystem.get("created"):
                subsystem["created"] = datetime.fromisoformat(subsystem["created"])
        subsystems.sort(key=lambda x: x.get("subsystem_id", 0))
        context = {
            "subsystems": subsystems,
            "current_part1": part1,
            "current_part2": part2,
            "active_instance": active_instance(request),
            "page": "hwdb",
        }
        return render(request, "hwdb/subsystem_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})


# ---- Upload (Phase-3, issues #19/#20/#21) --------------------------------


def upload_index_view(request):
    """Legacy URL — the tray worklist is now merged into /hwdb/larasic/.

    Old bookmarks land here and bounce; the merged page surfaces the same
    To-upload count and CSV-availability signals as table columns.
    """
    return redirect("hwdb:larasic")


def _rts_root() -> Path | None:
    """Resolve RTS_DIR from env. Returns None if unconfigured."""
    try:
        return Path(env_config("RTS_DIR"))
    except Exception:
        return None


@require_POST
def upload_refresh_csv_cache_view(request):
    """Walk every known tray and refresh its CSV cache (L1 + L2).

    The index page reads ``TrayCsvCache`` rows directly to avoid one SMB
    ``stat()`` per tray on every render — that's deliberately fast and
    deliberately stale: a tray that just gained CSVs but was never visited
    has no row yet, so the badge won't light up until someone clicks through
    to its detail page. This view forces the catch-up: one full scan across
    all known trays, then redirect back to the index.

    Synchronous; for a few dozen trays this takes a handful of seconds even
    on SMB. We don't need a FNAL bearer (reads filesystem + writes local DB).
    """
    rts_root = _rts_root()
    if rts_root is None:
        return render(
            request,
            "hwdb/error.html",
            {"error_message": "RTS_DIR is not configured."},
            status=500,
        )
    tray_ids = list(
        LArASIC.objects.exclude(tray_id__isnull=True)
        .exclude(tray_id="")
        .values_list("tray_id", flat=True)
        .distinct()
    )
    for tid in tray_ids:
        upload_lib.scan_tray_csvs(rts_root, tid)
    return redirect("hwdb:larasic")


def upload_tray_view(request, tray_id):
    """Per-tray chip list with per-row + global upload buttons.

    Scans ``RTS_DIR/<tray_id>/results/`` once and badges each chip row with
    whether its RT and LN CSVs are available — so the user sees up front
    whether the upload will be detailed (CSV → 67 fields) or simple (no CSV
    → 7 fields).
    """
    chips = LArASIC.objects.filter(tray_id=tray_id).order_by("serial_number")
    chip_count = chips.count()
    # Three states. "new" = chip not in HWDB → create + post tests. "enrich" =
    # in HWDB (likely from FEMB workflow) but our QC tests haven't been
    # confirmed there yet → reuse part_id + post any missing tests. "done" =
    # in HWDB and qc_tests_uploaded already True → skip unless Force re-upload.
    new_count = chips.filter(is_in_hwdb=False).count()
    done_count = chips.filter(is_in_hwdb=True, qc_tests_uploaded=True).count()
    enrich_count = chip_count - new_count - done_count
    upload_count = new_count + enrich_count
    instance = active_instance(request)

    rts_root = _rts_root()
    csvs = upload_lib.scan_tray_csvs(rts_root, tray_id)
    chip_rows = []
    for chip in chips:
        if not chip.is_in_hwdb:
            state = "new"
        elif chip.qc_tests_uploaded:
            state = "done"
        else:
            state = "enrich"
        chip_rows.append({
            "chip": chip,
            "state": state,
            "has_rt_csv": (chip.serial_number, "RT") in csvs,
            "has_ln_csv": (chip.serial_number, "LN") in csvs,
        })
    has_analysis = bool(csvs)

    return render(
        request,
        "hwdb/upload_tray.html",
        {
            "tray_id": tray_id,
            "chip_rows": chip_rows,
            "chip_count": chip_count,
            "new_count": new_count,
            "enrich_count": enrich_count,
            "done_count": done_count,
            "upload_count": upload_count,
            "has_analysis": has_analysis,
            "csv_count": len(csvs),
            "active_instance": instance,
            "instances": list(settings.HWDB_PROFILES),
            "is_dev": instance == "dev",
            "page": "hwdb",
        },
    )


def _stream_upload(api, chips, *, part_type_id, rts_root, attach_csvs, instance, tray_id, operator_name, force_csv_attach=False):
    """Generator that yields per-chip progress lines for ``upload_run_view``.

    Per Q9 error policy: continue past per-chip errors with a clear line, no
    retries. End with a tally line. Bearer is already minted by the caller.
    """
    total = len(chips)
    yield f"Starting upload of {total} chip(s) on tray {tray_id} to {instance}.\n"
    if total == 0:
        yield "No chips to upload.\n"
        return

    try:
        test_type_ids = {
            "RT": upload_lib.resolve_test_type_id(api, part_type_id, "RoomT QC Test"),
            "LN": upload_lib.resolve_test_type_id(api, part_type_id, "CryoT QC Test"),
        }
    except Exception as e:
        yield f"*** cannot resolve HWDB test types: {e} ***\n"
        return

    ok = failed = 0
    promoted = []  # chips whose is_in_hwdb we should flip True on prod
    csv_warm = []  # chip pks whose RT CSV was attached in this run
    csv_cold = []  # chip pks whose LN CSV was attached in this run

    for i, chip in enumerate(chips, 1):
        yield f"[{i}/{total}] {chip.serial_number}: "
        try:
            result = upload_lib.upload_chip(
                api,
                chip,
                part_type_id=part_type_id,
                instance=instance,
                rts_root=rts_root,
                attach_csvs=attach_csvs,
                test_type_ids=test_type_ids,
                operator_name=operator_name,
                force_csv_attach=force_csv_attach,
            )
        except Exception as e:
            failed += 1
            logger.exception("upload_chip crashed for %s", chip.serial_number)
            yield f"CRASH — {e}\n"
            continue

        if result.error:
            failed += 1
            yield f"FAIL — {result.error}\n"
            continue

        bits = [f"created {result.part_id}" if result.created else f"exists ({result.part_id})"]
        for t in result.tests:
            if t.error:
                bits.append(f"{t.env} FAIL: {t.error}")
            elif t.skipped:
                bits.append(f"{t.env} skipped (already test_id={t.test_id})")
            else:
                atch = " +csv" if t.csv_attached else ""
                bits.append(f"{t.env}={t.test_id} ({t.mode}{atch})")
        if all(t.error is None for t in result.tests):
            ok += 1
            if instance == "prod":
                promoted.append((chip.pk, result.part_id))
                for t in result.tests:
                    if t.csv_attached and t.env == "RT":
                        csv_warm.append(chip.pk)
                    elif t.csv_attached and t.env == "LN":
                        csv_cold.append(chip.pk)
        else:
            failed += 1
        yield ", ".join(bits) + "\n"

    yield from _commit_prod_stamps(instance, promoted, csv_warm, csv_cold)
    yield f"\nDone. ok={ok} failed={failed}\n"


def _commit_prod_stamps(instance, promoted, csv_warm, csv_cold):
    """Flip is_in_hwdb / qc_tests_uploaded for promoted chips, and stamp the
    per-env csv_attached_at timestamps for chips whose CSVs we actually attached
    in this run. Prod-only — dev runs leave the local state alone, same as the
    existing is_in_hwdb policy ([[0003-prod-scoped-is-in-hwdb-flag]])."""
    if instance != "prod":
        return
    now = timezone.now()
    if promoted:
        ids = [pk for pk, _ in promoted]
        LArASIC.objects.filter(pk__in=ids).update(
            is_in_hwdb=True,
            qc_tests_uploaded=True,
            hwdb_checked_at=now,
        )
        yield f"(updated is_in_hwdb=True, qc_tests_uploaded=True on {len(ids)} local row(s))\n"
    if csv_warm:
        LArASIC.objects.filter(pk__in=csv_warm).update(warm_csv_attached_at=now)
    if csv_cold:
        LArASIC.objects.filter(pk__in=csv_cold).update(cold_csv_attached_at=now)
    if csv_warm or csv_cold:
        yield f"(stamped csv_attached_at on {len(csv_warm)} RT + {len(csv_cold)} LN row(s))\n"


def _stream_upload_parallel(
    *, base_url, bearer, chips, part_type_id, rts_root, attach_csvs,
    instance, tray_id, operator_name, workers, force_csv_attach=False,
):
    """Parallel sibling of ``_stream_upload``. Same UX (per-chip line +
    final tally) but lines arrive in completion order with a monotonic
    ``[done k/total]`` counter instead of input-order ``[i/total]``.
    See ADR-0005.
    """
    total = len(chips)
    yield f"Starting parallel upload of {total} chip(s) on tray {tray_id} to {instance} ({workers} workers).\n"
    if total == 0:
        yield "No chips to upload.\n"
        return

    # Resolve test types once with a short-lived client; worker threads will
    # build their own clients.
    bootstrap = FnalDbApiClient(base_url, bearer)
    try:
        test_type_ids = {
            "RT": upload_lib.resolve_test_type_id(bootstrap, part_type_id, "RoomT QC Test"),
            "LN": upload_lib.resolve_test_type_id(bootstrap, part_type_id, "CryoT QC Test"),
        }
    except Exception as e:
        yield f"*** cannot resolve HWDB test types: {e} ***\n"
        return

    def make_client():
        return FnalDbApiClient(base_url, bearer)

    ok = failed = 0
    promoted = []
    csv_warm = []
    csv_cold = []
    done = 0
    for chip, result in upload_lib.iter_upload_chips_parallel(
        chips,
        client_factory=make_client,
        part_type_id=part_type_id,
        instance=instance,
        rts_root=rts_root,
        attach_csvs=attach_csvs,
        test_type_ids=test_type_ids,
        operator_name=operator_name,
        workers=workers,
        force_csv_attach=force_csv_attach,
    ):
        done += 1
        prefix = f"[done {done}/{total}] {chip.serial_number}: "
        if result.error:
            failed += 1
            yield prefix + f"FAIL — {result.error}\n"
            continue
        bits = [f"created {result.part_id}" if result.created else f"exists ({result.part_id})"]
        for t in result.tests:
            if t.error:
                bits.append(f"{t.env} FAIL: {t.error}")
            elif t.skipped:
                bits.append(f"{t.env} skipped (already test_id={t.test_id})")
            else:
                atch = " +csv" if t.csv_attached else ""
                bits.append(f"{t.env}={t.test_id} ({t.mode}{atch})")
        if all(t.error is None for t in result.tests):
            ok += 1
            if instance == "prod":
                promoted.append((chip.pk, result.part_id))
                for t in result.tests:
                    if t.csv_attached and t.env == "RT":
                        csv_warm.append(chip.pk)
                    elif t.csv_attached and t.env == "LN":
                        csv_cold.append(chip.pk)
        else:
            failed += 1
        yield prefix + ", ".join(bits) + "\n"

    yield from _commit_prod_stamps(instance, promoted, csv_warm, csv_cold)
    yield f"\nDone. ok={ok} failed={failed}\n"


@require_POST
def upload_run_view(request, tray_id):
    """Stream per-chip upload progress as text/plain.

    Issues #19/#20 land the DEV path; #21 adds the PROD gauntlet (a
    type-to-confirm modal on the client — see ``upload_tray.html``). The
    server-side gate is the FNAL writer role: HWDB returns 403 without it,
    we surface the error per-chip. Per Q8 we do not duplicate the gauntlet
    server-side.
    """
    instance = active_instance(request)

    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(
            f"{link}?{urlencode({'next': reverse('hwdb:upload_tray', args=[tray_id])})}"
        )
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    profile = active_profile(request)
    api = FnalDbApiClient(profile["api"], bearer)
    part_type_id = profile["larasic_part_type"]
    # credkey is the FNAL services username — most honest "Operator Name" we have.
    operator_name = (request.session.get(LINK_KEY) or {}).get("credkey") or ""

    chips_qs = LArASIC.objects.filter(tray_id=tray_id).order_by("serial_number")
    chip_filter = request.POST.get("chip")
    if chip_filter:
        chips_qs = chips_qs.filter(serial_number=chip_filter)

    # On PROD, default behavior skips chips whose QC tests we've already
    # confirmed in HWDB. "Force re-upload" walks them anyway — the per-test
    # find_existing_test dedup still protects HWDB from duplicates. Per-chip
    # button presses bypass this filter (the user opted in explicitly). Dev
    # always walks everything (qc_tests_uploaded reflects PROD state).
    force = request.POST.get("force") == "on"
    if instance == "prod" and not force and not chip_filter:
        chips_qs = chips_qs.exclude(qc_tests_uploaded=True)

    if request.POST.get("random_5") == "on" and instance == "dev":
        # Dev-only quick-feasibility sample. order_by("?") picks a fresh random
        # subset per click — useful for repeatedly exercising the full pipeline
        # without burning a whole tray.
        chips = list(chips_qs.order_by("?")[:5])
    else:
        chips = list(chips_qs)

    attach_csvs = request.POST.get("attach_csvs", "on") == "on"
    # Re-post detailed-mode tests even if a detailed record already exists.
    # Used to retry CSV attachment when a prior detailed upload's attach
    # silently failed. Posts a duplicate test record by design (probe 3:
    # HWDB doesn't dedup, and PATCH on tests isn't supported).
    force_csv_attach = request.POST.get("force_csv_attach") == "on"
    rts_root = _rts_root()

    mode = "parallel" if request.POST.get("mode") == "parallel" else "serial"
    if mode == "parallel":
        try:
            workers = int(request.GET.get("workers", "10"))
        except (TypeError, ValueError):
            workers = 10
        workers = max(1, min(32, workers))
        stream = _stream_upload_parallel(
            base_url=profile["api"],
            bearer=bearer,
            chips=chips,
            part_type_id=part_type_id,
            rts_root=rts_root,
            attach_csvs=attach_csvs,
            instance=instance,
            tray_id=tray_id,
            operator_name=operator_name,
            workers=workers,
            force_csv_attach=force_csv_attach,
        )
    else:
        stream = _stream_upload(
            api,
            chips,
            part_type_id=part_type_id,
            rts_root=rts_root,
            attach_csvs=attach_csvs,
            instance=instance,
            tray_id=tray_id,
            operator_name=operator_name,
            force_csv_attach=force_csv_attach,
        )

    response = StreamingHttpResponse(
        stream,
        content_type="text/plain; charset=utf-8",
    )
    # Hint reverse proxies not to buffer; supported by nginx, ignored by Apache.
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@with_fnal_bearer
def part_type_list_view(request, bearer, part1, part2, subsystem_id):
    profile = active_profile(request)
    api_client = FnalDbApiClient(profile["api"], bearer)
    try:
        raw_response = api_client.get_part_types_for_subsystem(part1, part2, subsystem_id)
        part_types = raw_response.get("data", [])
        for part_type in part_types:
            if part_type.get("created"):
                part_type["created"] = datetime.fromisoformat(part_type["created"])
        context = {
            "part_types": part_types,
            "current_part1": part1,
            "current_part2": part2,
            "current_subsystem_id": subsystem_id,
            "hwdb_ui_base": profile["ui"],
            "active_instance": active_instance(request),
            "page": "hwdb",
        }
        return render(request, "hwdb/part_type_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})
