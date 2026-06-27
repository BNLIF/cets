"""FD-VD hierarchy (skeleton) sync — pure engine, no views.

``sync_hierarchy(api)`` walks the live production HWDB tree for the FD-VD
whitelist (``systems/D`` → ``subsystems/D/{sys}`` → ``component-types/D/{sys}/{subsys}``)
and mirrors each component type into ``ComponentTypeNode`` with a true
component count. Read-only against HWDB; additive locally (ADR-0010).

Like ``sync.sync_family``, the orchestrator yields plain-text progress lines so
a view can wrap a ``StreamingHttpResponse`` on top without changing the engine.
"""

from __future__ import annotations

import logging
from typing import Iterator

from django.utils import timezone

from .models import ComponentTypeNode, HierarchySyncState

logger = logging.getLogger(__name__)


def is_fdvd_system(name: str) -> bool:
    """The v1 whitelist (ADR-0010): systems named ``FD-VD *`` plus ``FD CE``
    (which holds the FD-VD chips, FEMB and cables). Adding another system is a
    one-line edit here.
    """
    name = (name or "").strip()
    return name.startswith("FD-VD") or name == "FD CE"


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
    """Walk the whitelisted FD-VD systems into the ``ComponentTypeNode`` mirror.

    Upserts every component type found and prunes nodes that have disappeared
    (only after a clean full walk). Yields progress lines.
    """
    state = HierarchySyncState.get()
    state.started_at = timezone.now()
    state.finished_at = None
    state.last_error = ""
    state.save()

    seen: set[str] = set()
    systems_done = 0
    nodes = 0
    try:
        sys_body = api.get_systems(project)
        systems = [
            s for s in (sys_body.get("data") or [])
            if is_fdvd_system(s.get("name") or "")
        ]
        systems.sort(key=lambda s: s.get("id") or 0)
        yield f"hierarchy: {len(systems)} FD-VD systems to walk\n"

        for s in systems:
            sid = s.get("id")
            sname = s.get("name") or ""
            sub_body = api.get_subsystems(project, f"{sid:03d}")
            subs = sorted(
                sub_body.get("data") or [],
                key=lambda x: x.get("subsystem_id") or 0,
            )
            yield f"  [{sid:03d}] {sname}: {len(subs)} subsystems\n"

            for ss in subs:
                ssid = ss.get("subsystem_id")
                ssname = ss.get("subsystem_name") or ""
                ct_body = api.get_part_types_for_subsystem(project, f"{sid:03d}", ssid)
                cts = ct_body.get("data") or []
                for ct in cts:
                    ptid = ct.get("part_type_id")
                    if not ptid:
                        continue
                    full = ct.get("full_name") or ""
                    leaf = full.split(".")[-1].strip() if full else ptid
                    n = _count_components(api, ptid)
                    ComponentTypeNode.objects.update_or_create(
                        part_type_id=ptid,
                        defaults={
                            "project": project,
                            "system_id": sid,
                            "system_name": sname,
                            "subsystem_id": ssid,
                            "subsystem_name": ssname,
                            "component_type_name": leaf,
                            "full_name": full,
                            "n_components": n,
                        },
                    )
                    seen.add(ptid)
                    nodes += 1
                if cts:
                    yield f"    {ssname}: {len(cts)} component types\n"
            systems_done += 1

        stale = ComponentTypeNode.objects.exclude(part_type_id__in=seen)
        n_stale = stale.count()
        stale.delete()

        state.finished_at = timezone.now()
        state.systems_count = systems_done
        state.nodes_count = nodes
        state.save()
        yield (
            f"done: {nodes} component types across {systems_done} systems"
            f"{f' ({n_stale} stale removed)' if n_stale else ''}\n"
        )
    except Exception as e:
        logger.exception("sync_hierarchy crashed")
        state.last_error = str(e)
        state.finished_at = timezone.now()
        state.save()
        raise
