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
from typing import Iterator

from django.utils import timezone

from . import curation
from .models import HierarchyNode, HierarchySyncState

logger = logging.getLogger(__name__)


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


def sync_hierarchy(api, project: str = "D") -> Iterator[str]:
    """Walk the curated systems into the ``HierarchyNode`` structure mirror.

    Records a node for every System, Subsystem, and Component Type — including
    empty systems/subsystems (so a system registered upstream with no component
    types is still navigable, ADR-0012). Leaf test-sync state
    (``tests_synced_at``/``n_tests``) is preserved across re-syncs. Prunes nodes
    that have disappeared after a clean full walk. Yields progress lines.
    """
    state = HierarchySyncState.get()
    state.started_at = timezone.now()
    state.finished_at = None
    state.last_error = ""
    state.save()

    seen: set[int] = set()
    systems_done = 0
    leaves = 0
    try:
        sys_body = api.get_systems(project)
        curated = curation.curated_system_ids()
        systems = [
            s for s in (sys_body.get("data") or [])
            if s.get("id") in curated
        ]
        systems.sort(key=lambda s: s.get("id") or 0)
        yield f"hierarchy: {len(systems)} curated systems to walk\n"

        for s in systems:
            sid = s.get("id")
            sname = s.get("name") or ""
            sys_node, _ = HierarchyNode.objects.update_or_create(
                level=HierarchyNode.LEVEL_SYSTEM, system_id=sid, subsystem_id=None,
                part_type_id="",
                defaults={"project": project, "system_name": sname, "name": sname},
            )
            seen.add(sys_node.pk)

            sub_body = api.get_subsystems(project, f"{sid:03d}")
            subs = sorted(
                sub_body.get("data") or [],
                key=lambda x: x.get("subsystem_id") or 0,
            )
            yield f"  [{sid:03d}] {sname}: {len(subs)} subsystems\n"

            for ss in subs:
                ssid = ss.get("subsystem_id")
                ssname = ss.get("subsystem_name") or ""
                sub_node, _ = HierarchyNode.objects.update_or_create(
                    level=HierarchyNode.LEVEL_SUBSYSTEM, system_id=sid,
                    subsystem_id=ssid, part_type_id="",
                    defaults={
                        "parent": sys_node, "project": project,
                        "system_name": sname, "subsystem_name": ssname, "name": ssname,
                    },
                )
                seen.add(sub_node.pk)

                ct_body = api.get_part_types_for_subsystem(project, f"{sid:03d}", ssid)
                cts = ct_body.get("data") or []
                for ct in cts:
                    ptid = ct.get("part_type_id")
                    if not ptid:
                        continue
                    full = ct.get("full_name") or ""
                    leaf = full.split(".")[-1].strip() if full else ptid
                    n = _count_components(api, ptid)
                    # defaults exclude the test-sync fields so they survive re-sync.
                    type_node, _ = HierarchyNode.objects.update_or_create(
                        level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid,
                        defaults={
                            "parent": sub_node, "project": project,
                            "system_id": sid, "system_name": sname,
                            "subsystem_id": ssid, "subsystem_name": ssname,
                            "name": leaf, "full_name": full, "n_components": n,
                        },
                    )
                    seen.add(type_node.pk)
                    leaves += 1
                if cts:
                    yield f"    {ssname}: {len(cts)} component types\n"
            systems_done += 1

        stale = HierarchyNode.objects.exclude(pk__in=seen)
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
