"""Drill-in navigation: resolve a URL trail to a node, build child cards and
deep-link URLs (ADR-0012, issue #40).

A node's URL is ``/explore/<region>/<family>/[<system_id>/]<subsystem_id>/<part_type_id>``
— a family that owns one system (FD CE) omits the ``<system_id>`` segment
(``family_is_flat``). Region/Family come from ``curation.yaml``; System /
Subsystem / Component Type come from the ``HierarchyNode`` mirror. Resolution is
position + flatten driven, all segments stable HWDB ids, so links survive
re-syncs.
"""

from __future__ import annotations

from django.db.models import Sum
from django.http import Http404
from django.urls import reverse

from . import curation
from .models import HierarchyNode as H

HOME_LABEL = "All systems"


def node_path(region_key=None, family_key=None, system_id=None,
              subsystem_id=None, part_type_id=None) -> str:
    """Build a node's URL. Callers omit ``system_id`` for flattened families."""
    if region_key is None:
        return reverse("explore:home")
    parts = [region_key]
    if family_key is not None:
        parts.append(family_key)
    if system_id is not None:
        parts.append(str(system_id))
    if subsystem_id is not None:
        parts.append(str(subsystem_id))
    if part_type_id:
        parts.append(part_type_id)
    return reverse("explore:node", kwargs={"trail": "/".join(parts)})


def _rollup(**filters) -> tuple[int, int]:
    agg = (H.objects.filter(level=H.LEVEL_TYPE, **filters)
           .aggregate(c=Sum("n_components"), t=Sum("n_tests")))
    return agg["c"] or 0, agg["t"] or 0


def _region_cards():
    cards = []
    for r in curation.regions():
        browsable = curation.region_is_browsable(r)
        cards.append({
            "level": "Region", "name": r["name"], "sub": "", "ident": "",
            "url": node_path(r["key"]) if browsable else None,
            "locked": not browsable, "note": r.get("note", ""),
            "child_label": "families",
            "child_count": len([f for f in r.get("families", []) or []]) if browsable else None,
            "n_components": None,
        })
    return cards


def _family_cards(region):
    cards = []
    for f in region.get("families", []) or []:
        browsable = curation.family_is_browsable(f)
        sys_ids = f.get("systems") or []
        comps = sum(_rollup(system_id=i)[0] for i in sys_ids) if browsable else None
        cards.append({
            "level": "Family", "name": f["name"], "sub": f.get("sub", ""), "ident": "",
            "url": node_path(region["key"], f["key"]) if browsable else None,
            "locked": not browsable, "note": f.get("note", ""),
            "child_label": "systems", "child_count": len(sys_ids) if browsable else None,
            "n_components": comps,
        })
    return cards


def _system_cards(region, family):
    cards = []
    for sid in family.get("systems") or []:
        node = H.objects.filter(level=H.LEVEL_SYSTEM, system_id=sid).first()
        if not node:
            continue
        comps, tests = _rollup(system_id=sid)
        nsubs = H.objects.filter(level=H.LEVEL_SUBSYSTEM, system_id=sid).count()
        cards.append({
            "level": "System", "name": node.system_name, "sub": "", "ident": str(sid),
            "url": node_path(region["key"], family["key"], system_id=sid),
            "locked": False, "note": "", "child_label": "subsystems",
            "child_count": nsubs, "n_components": comps, "n_tests": tests,
            "empty": comps == 0 and nsubs == 0,
        })
    return cards


def _subsystem_cards(region, family, system, flat):
    cards = []
    sid = system.system_id
    for sub in H.objects.filter(level=H.LEVEL_SUBSYSTEM, system_id=sid):
        comps, tests = _rollup(system_id=sid, subsystem_id=sub.subsystem_id)
        nleaves = H.objects.filter(level=H.LEVEL_TYPE, system_id=sid,
                                   subsystem_id=sub.subsystem_id).count()
        cards.append({
            "level": "Subsystem", "name": sub.subsystem_name, "sub": "", "ident": "",
            "url": node_path(region["key"], family["key"],
                             system_id=None if flat else sid,
                             subsystem_id=sub.subsystem_id),
            "locked": False, "note": "", "child_label": "component types",
            "child_count": nleaves, "n_components": comps, "n_tests": tests,
            "empty": nleaves == 0,
        })
    return cards


def _leaf_cards(region, family, system, subsystem, flat):
    cards = []
    leaves = H.objects.filter(level=H.LEVEL_TYPE, system_id=system.system_id,
                              subsystem_id=subsystem.subsystem_id)
    for leaf in leaves:
        cards.append({
            "level": "Component type", "name": leaf.name, "sub": "",
            "ident": leaf.part_type_id, "is_leaf": True,
            "url": node_path(region["key"], family["key"],
                             system_id=None if flat else system.system_id,
                             subsystem_id=subsystem.subsystem_id,
                             part_type_id=leaf.part_type_id),
            "locked": False, "note": "",
            "n_components": leaf.n_components, "n_tests": leaf.n_tests,
            "synced": leaf.tests_synced_at is not None, "empty": leaf.n_components == 0,
        })
    return cards


def _int(seg):
    try:
        return int(seg)
    except (TypeError, ValueError):
        raise Http404("bad path segment")


def resolve(trail: str | None) -> dict:
    """Resolve a URL trail to a view spec: crumbs + the current node's children
    (folder) or the leaf node (detail). Raises Http404 on an unknown path."""
    crumbs = [{"name": HOME_LABEL, "url": node_path()}]
    segs = [s for s in (trail or "").split("/") if s]

    if not segs:
        return {"kind": "root", "name": HOME_LABEL, "sub": "Curated DUNE hardware",
                "crumbs": crumbs, "cards": _region_cards()}

    region = curation.find_region(segs[0])
    if not region or not curation.region_is_browsable(region):
        raise Http404("unknown region")
    rk = region["key"]
    crumbs.append({"name": region["name"], "url": node_path(rk)})
    if len(segs) == 1:
        return {"kind": "region", "name": region["name"], "sub": "",
                "crumbs": crumbs, "cards": _family_cards(region)}

    family = curation.find_family(region, segs[1])
    if not family or not curation.family_is_browsable(family):
        raise Http404("unknown family")
    fk = family["key"]
    flat = curation.family_is_flat(family)
    crumbs.append({"name": family["name"], "url": node_path(rk, fk)})
    rest = segs[2:]

    # Resolve the system (implicit for flattened families).
    if flat:
        system = H.objects.filter(level=H.LEVEL_SYSTEM,
                                  system_id=family["systems"][0]).first()
    else:
        if not rest:
            return {"kind": "family", "name": family["name"], "sub": family.get("sub", ""),
                    "crumbs": crumbs, "cards": _system_cards(region, family)}
        sid = _int(rest[0])
        if sid not in (family.get("systems") or []):
            raise Http404("system not in family")
        system = H.objects.filter(level=H.LEVEL_SYSTEM, system_id=sid).first()
        if not system:
            raise Http404("system not mirrored")
        crumbs.append({"name": system.system_name, "url": node_path(rk, fk, system_id=sid)})
        rest = rest[1:]

    if system is None:
        raise Http404("system not mirrored")

    if not rest:
        return {"kind": "family" if flat else "system",
                "name": family["name"] if flat else system.system_name,
                "sub": family.get("sub", "") if flat else "",
                "crumbs": crumbs,
                "cards": _subsystem_cards(region, family, system, flat)}

    ssid = _int(rest[0])
    subsystem = H.objects.filter(level=H.LEVEL_SUBSYSTEM, system_id=system.system_id,
                                 subsystem_id=ssid).first()
    if not subsystem:
        raise Http404("unknown subsystem")
    crumbs.append({"name": subsystem.subsystem_name,
                   "url": node_path(rk, fk, system_id=None if flat else system.system_id,
                                    subsystem_id=ssid)})
    rest = rest[1:]

    if not rest:
        return {"kind": "subsystem", "name": subsystem.subsystem_name, "sub": "",
                "crumbs": crumbs,
                "cards": _leaf_cards(region, family, system, subsystem, flat)}

    leaf = H.objects.filter(level=H.LEVEL_TYPE, part_type_id=rest[0]).first()
    if not leaf:
        raise Http404("unknown component type")
    crumbs.append({"name": leaf.name,
                   "url": node_path(rk, fk, system_id=None if flat else system.system_id,
                                    subsystem_id=ssid, part_type_id=leaf.part_type_id)})
    return {"kind": "leaf", "name": leaf.name, "sub": "", "crumbs": crumbs, "leaf": leaf}


def leaf_path_for(part_type_id: str) -> str | None:
    """The deep-link URL for a leaf by part_type_id (for the ?node= redirect).
    Resolves the leaf's region/family from the mirror + curation; None if the
    leaf or its curated family can't be found."""
    leaf = H.objects.filter(level=H.LEVEL_TYPE, part_type_id=part_type_id).first()
    if not leaf:
        return None
    for region in curation.regions():
        if not curation.region_is_browsable(region):
            continue
        for family in region.get("families", []) or []:
            if not curation.family_is_browsable(family):
                continue
            if leaf.system_id in (family.get("systems") or []):
                flat = curation.family_is_flat(family)
                return node_path(region["key"], family["key"],
                                 system_id=None if flat else leaf.system_id,
                                 subsystem_id=leaf.subsystem_id,
                                 part_type_id=leaf.part_type_id)
    return None
