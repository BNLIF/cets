"""FD-VD hierarchy (skeleton) sync — pure engine, no views.

``sync_hierarchy(api)`` walks the live production HWDB tree for the FD-VD
whitelist (``systems/D`` → ``subsystems/D/{sys}`` → ``component-types/D/{sys}/{subsys}``)
and mirrors each component type into ``ComponentTypeNode`` with a true
component count. Read-only against HWDB; additive locally (ADR-0010).

Like ``hwdb.sync.sync_family``, the orchestrator yields plain-text progress
lines so a view can wrap a ``StreamingHttpResponse`` on top without changing
the engine.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import local as _thread_local_cls
from typing import Iterator

from django.utils import timezone

from hwdb.api_client import FnalDbApiClient

from . import curation
from .models import HierarchyNode, HierarchySyncState

logger = logging.getLogger(__name__)

_WORKERS = 10
_RETRIES = 3


def _with_retry(fn, item):
    """Call ``fn(item)`` with a few backoff retries for transient HWDB blips
    (timeouts, 429/503 under burst). Re-raises the last error if all fail."""
    last = None
    for attempt in range(_RETRIES):
        try:
            return fn(item)
        except Exception as e:  # noqa: BLE001 — transient HTTP/network
            last = e
            time.sleep(0.4 * (attempt + 1))
    raise last


def _pool_map(fn, items, collect_errors=False):
    """Run ``fn(item)`` over ``items`` across the worker pool (with retries);
    return ``[(item, result), …]``. If **any** item still fails after retries,
    raise — so the caller aborts before pruning rather than overwriting good
    data with a partial walk (the serial walk's all-or-nothing safety). With
    ``collect_errors=True`` return ``(results, [(item, error), …])`` instead of
    raising — for phases whose per-item result is cosmetic (component counts)
    and mustn't let one upstream bug fail the whole walk. ORM writes stay on
    the main thread (SQLite-safe), as in ``events``."""
    out, errors = [], []
    if items:
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            futs = {pool.submit(_with_retry, fn, it): it for it in items}
            for fut in as_completed(futs):
                try:
                    out.append((futs[fut], fut.result()))
                except Exception as e:  # noqa: BLE001
                    errors.append((futs[fut], e))
    if collect_errors:
        return out, errors
    if errors:
        raise RuntimeError(
            f"{len(errors)}/{len(items)} hierarchy fetch(es) failed after retries "
            f"(e.g. {errors[0][0]!r}: {errors[0][1]}); aborting so the prune step "
            f"can't delete un-refetched nodes"
        )
    return out


def _count_components(api, part_type_id: str) -> int:
    """True component count for a part type, read cheaply from the paginated
    ``total`` (one ``size=1`` request) rather than fetching every component.
    """
    body = api._make_request(
        "GET",
        f"component-types/{part_type_id}/components",
        params={"page": 1, "size": 1},
    )
    pagination = body.get("pagination") or {}
    total = pagination.get("total")
    if total is not None:
        return int(total)
    return len(body.get("data") or [])


def sync_hierarchy(api, instance: str = "prod", project: str = "D") -> Iterator[str]:
    """Walk one instance's curated systems into the ``HierarchyNode`` mirror.
    The caller's ``api`` client must point at the same instance (#47).

    Records a node for every System, Subsystem, and Component Type — including
    empty systems/subsystems (so a system registered upstream with no component
    types is still navigable, ADR-0012). Leaf test-sync state
    (``tests_synced_at``/``n_tests``) is preserved across re-syncs. Prunes nodes
    that have disappeared after a clean full walk — within this instance only.
    Yields progress lines.
    """
    state = HierarchySyncState.get(instance)
    state.started_at = timezone.now()
    state.finished_at = None
    state.last_error = ""
    state.save()

    # Per-thread clients for the parallel read phases (a Session isn't fully
    # thread-safe — same rule as events.sync_test_events). Derived from the
    # passed client; tests patch ``FnalDbApiClient`` to return their mock.
    base_url = api.base_url
    auth = api.session.headers.get("Authorization", "")
    bearer = auth[len("Bearer "):] if isinstance(auth, str) and auth.startswith("Bearer ") else ""
    tls = _thread_local_cls()

    def _client():
        c = getattr(tls, "client", None)
        if c is None:
            c = tls.client = FnalDbApiClient(base_url, bearer)
        return c

    seen: set[int] = set()
    systems_done = 0
    leaves = 0
    try:
        sys_body = api.get_systems(project)
        curated = curation.curated_system_ids(instance)
        systems = [
            s for s in (sys_body.get("data") or [])
            if s.get("id") in curated
        ]
        systems.sort(key=lambda s: s.get("id") or 0)
        yield f"hierarchy: {len(systems)} curated systems to walk\n"

        # --- Parallel read phases (no ORM here) ---
        # Phase 1: subsystems per system.
        def _fetch_subs(s):
            return _client().get_subsystems(project, f"{s['id']:03d}").get("data") or []
        subs_by_sys = {}
        for s, subs in _pool_map(_fetch_subs, systems):
            subs_by_sys[s["id"]] = sorted(subs, key=lambda x: x.get("subsystem_id") or 0)
        yield f"  subsystems fetched for {len(systems)} systems\n"

        # Phase 2: component types per (system, subsystem).
        sub_tasks = [(s, ss) for s in systems for ss in subs_by_sys.get(s["id"], [])]

        def _fetch_cts(task):
            s, ss = task
            return (_client().get_part_types_for_subsystem(
                project, f"{s['id']:03d}", ss.get("subsystem_id")).get("data") or [])
        cts_by_sub = {}
        for (s, ss), cts in _pool_map(_fetch_cts, sub_tasks):
            cts_by_sub[(s["id"], ss.get("subsystem_id"))] = cts
        all_ptids = [ct["part_type_id"] for cts in cts_by_sub.values()
                     for ct in cts if ct.get("part_type_id")]
        yield f"  {len(all_ptids)} component types across {len(sub_tasks)} subsystems\n"

        # Phase 3: true component count per leaf (the bulk of the calls).
        # Tolerant: a count that still fails after retries (e.g. the dev HWDB's
        # own response-validation 500s on category "box" rows) keeps the leaf
        # with its previous count instead of aborting the walk — the leaf's
        # identity came from phase 2, so prune safety is unaffected.
        count_pairs, count_errors = _pool_map(
            lambda p: _count_components(_client(), p), all_ptids, collect_errors=True)
        counts = {p: n for p, n in count_pairs}
        yield f"  counted components for {len(counts)}/{len(all_ptids)} types\n"
        for p, e in count_errors:
            logger.warning("hierarchy: component count failed for %s: %s", p, e)
            yield f"  WARNING: count failed for {p} (leaf kept, previous count retained)\n"

        # --- Serial write phase (main thread — SQLite-safe) ---
        for s in systems:
            sid = s.get("id")
            sname = s.get("name") or ""
            sys_node, _ = HierarchyNode.objects.update_or_create(
                instance=instance,
                level=HierarchyNode.LEVEL_SYSTEM, system_id=sid, subsystem_id=None,
                part_type_id="",
                defaults={"project": project, "system_name": sname, "name": sname},
            )
            seen.add(sys_node.pk)

            for ss in subs_by_sys.get(sid, []):
                ssid = ss.get("subsystem_id")
                ssname = ss.get("subsystem_name") or ""
                sub_node, _ = HierarchyNode.objects.update_or_create(
                    instance=instance,
                    level=HierarchyNode.LEVEL_SUBSYSTEM, system_id=sid,
                    subsystem_id=ssid, part_type_id="",
                    defaults={
                        "parent": sys_node, "project": project,
                        "system_name": sname, "subsystem_name": ssname, "name": ssname,
                    },
                )
                seen.add(sub_node.pk)

                cts = cts_by_sub.get((sid, ssid), [])
                for ct in cts:
                    ptid = ct.get("part_type_id")
                    if not ptid:
                        continue
                    full = ct.get("full_name") or ""
                    leaf = full.split(".")[-1].strip() if full else ptid
                    # defaults exclude the test-sync fields so they survive re-sync.
                    defaults = {
                        "parent": sub_node, "project": project,
                        "system_id": sid, "system_name": sname,
                        "subsystem_id": ssid, "subsystem_name": ssname,
                        "name": leaf, "full_name": full,
                    }
                    if ptid in counts:  # a failed count keeps the previous value
                        defaults["n_components"] = counts[ptid]
                    type_node, _ = HierarchyNode.objects.update_or_create(
                        instance=instance,
                        level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid,
                        defaults=defaults,
                    )
                    seen.add(type_node.pk)
                    leaves += 1
                if cts:
                    yield f"    {ssname}: {len(cts)} component types\n"
            systems_done += 1

        stale = HierarchyNode.for_instance(instance).exclude(pk__in=seen)
        n_stale = stale.count()
        stale.delete()

        state.finished_at = timezone.now()
        state.systems_count = systems_done
        state.nodes_count = leaves
        state.save()
        yield (
            f"done: {leaves} component types across {systems_done} systems"
            f"{f' ({n_stale} stale removed)' if n_stale else ''}\n"
        )
    except Exception as e:
        logger.exception("sync_hierarchy crashed")
        state.last_error = str(e)
        state.finished_at = timezone.now()
        state.save()
        raise
