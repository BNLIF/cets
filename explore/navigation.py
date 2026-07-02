"""Drill-in navigation: resolve a URL trail to a node, build child cards and
deep-link URLs (ADR-0012, issue #40).

A node's URL is ``/hw/<region>/<family>/[<system_id>/]<subsystem_id>/<part_type_id>``
— a family that owns one system (FD CE) omits the ``<system_id>`` segment
(``family_is_flat``). Region/Family come from ``curation.yaml``; System /
Subsystem / Component Type come from the ``HierarchyNode`` mirror. Resolution is
position + flatten driven, all segments stable HWDB ids, so links survive
re-syncs. Everything is per HWDB instance (#47): mirror reads are scoped and
the built URLs land on the instance's own prefix (/hw/ vs /hw/dev/).
"""

from __future__ import annotations

from django.db.models import Sum
from django.http import Http404
from django.urls import reverse

from . import curation
from .instances import namespace_of
from .models import HierarchyNode as H

HOME_LABEL = "All systems"

OVERFLOW_KEY = "UNC"


def overflow_region(instance: str) -> dict | None:
    """The synthetic "Uncurated" region for an overflow-enabled instance (#49):
    one flattened single-system family per mirrored-but-uncurated system,
    built from the mirror at render time (no yaml). Same dict shape as a
    curation region, so the card/crumb/tree machinery treats it like any
    other region. None when the instance has no overflow (prod) or nothing
    uncurated is mirrored yet."""
    if not curation.has_overflow(instance):
        return None
    curated = curation.curated_system_ids(instance)
    systems = (H.for_instance(instance).filter(level=H.LEVEL_SYSTEM)
               .exclude(system_id__in=curated).order_by("system_id"))
    families = [{"name": s.system_name, "key": str(s.system_id),
                 "sub": f"system {s.system_id}", "systems": [s.system_id]}
                for s in systems]
    if not families:
        return None
    return {"name": "Uncurated", "key": OVERFLOW_KEY, "overflow": True,
            "note": "not in curation.yaml · each system loads on first visit",
            "families": families}


def all_regions(instance: str) -> list[dict]:
    """Curated regions plus the synthetic overflow region (when present)."""
    out = list(curation.regions(instance))
    extra = overflow_region(instance)
    if extra:
        out.append(extra)
    return out


def node_path(instance, region_key=None, family_key=None, system_id=None,
              subsystem_id=None, part_type_id=None) -> str:
    """Build a node's URL. Callers omit ``system_id`` for flattened families."""
    ns = namespace_of(instance)
    if region_key is None:
        return reverse("explore:home", current_app=ns)
    parts = [region_key]
    if family_key is not None:
        parts.append(family_key)
    if system_id is not None:
        parts.append(str(system_id))
    if subsystem_id is not None:
        parts.append(str(subsystem_id))
    if part_type_id:
        parts.append(part_type_id)
    return reverse("explore:node", kwargs={"trail": "/".join(parts)}, current_app=ns)


def _rollup(instance, **filters) -> tuple[int, int]:
    agg = (H.for_instance(instance).filter(level=H.LEVEL_TYPE, **filters)
           .aggregate(c=Sum("n_components"), t=Sum("n_tests")))
    return agg["c"] or 0, agg["t"] or 0


def _region_cards(instance):
    cards = []
    for r in all_regions(instance):
        browsable = curation.region_is_browsable(r)
        cards.append({
            "level": "Region", "name": r["name"], "sub": "", "ident": "",
            "url": node_path(instance, r["key"]) if browsable else None,
            "locked": not browsable, "note": r.get("note", ""),
            "child_label": "families",
            "child_count": len([f for f in r.get("families", []) or []]) if browsable else None,
            "n_components": None,
        })
    return cards


def _family_cards(instance, region):
    cards = []
    for f in region.get("families", []) or []:
        browsable = curation.family_is_browsable(f)
        sys_ids = f.get("systems") or []
        comps = sum(_rollup(instance, system_id=i)[0] for i in sys_ids) if browsable else None
        cards.append({
            "level": "Family", "name": f["name"], "sub": f.get("sub", ""), "ident": "",
            "url": node_path(instance, region["key"], f["key"]) if browsable else None,
            "locked": not browsable, "note": f.get("note", ""),
            "child_label": "systems", "child_count": len(sys_ids) if browsable else None,
            "n_components": comps,
        })
    return cards


def _system_cards(instance, region, family):
    cards = []
    for sid in family.get("systems") or []:
        node = H.for_instance(instance).filter(level=H.LEVEL_SYSTEM, system_id=sid).first()
        if not node:
            continue
        comps, tests = _rollup(instance, system_id=sid)
        nsubs = H.for_instance(instance).filter(level=H.LEVEL_SUBSYSTEM, system_id=sid).count()
        cards.append({
            "level": "System", "name": node.system_name, "sub": "", "ident": str(sid),
            "url": node_path(instance, region["key"], family["key"], system_id=sid),
            "locked": False, "note": "", "child_label": "subsystems",
            "child_count": nsubs, "n_components": comps, "n_tests": tests,
            "empty": comps == 0 and nsubs == 0,
        })
    return cards


def _subsystem_cards(instance, region, family, system, flat):
    cards = []
    sid = system.system_id
    for sub in H.for_instance(instance).filter(level=H.LEVEL_SUBSYSTEM, system_id=sid):
        comps, tests = _rollup(instance, system_id=sid, subsystem_id=sub.subsystem_id)
        nleaves = H.for_instance(instance).filter(level=H.LEVEL_TYPE, system_id=sid,
                                                  subsystem_id=sub.subsystem_id).count()
        cards.append({
            "level": "Subsystem", "name": sub.subsystem_name, "sub": "",
            "ident": f"{sid}.{sub.subsystem_id}",
            "url": node_path(instance, region["key"], family["key"],
                             system_id=None if flat else sid,
                             subsystem_id=sub.subsystem_id),
            "locked": False, "note": "", "child_label": "component types",
            "child_count": nleaves, "n_components": comps, "n_tests": tests,
            "empty": nleaves == 0,
        })
    return cards


def _leaf_cards(instance, region, family, system, subsystem, flat):
    cards = []
    leaves = H.for_instance(instance).filter(level=H.LEVEL_TYPE, system_id=system.system_id,
                                             subsystem_id=subsystem.subsystem_id)
    for leaf in leaves:
        cards.append({
            "level": "Component type", "name": leaf.name, "sub": "",
            "ident": leaf.part_type_id, "is_leaf": True,
            "url": node_path(instance, region["key"], family["key"],
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


def _ctx(kind, region_key=None, family_key=None, flat=False,
         system_id=None, subsystem_id=None, part_type_id=None):
    return {"kind": kind, "region_key": region_key, "family_key": family_key,
            "flat": flat, "system_id": system_id, "subsystem_id": subsystem_id,
            "part_type_id": part_type_id}


def resolve(instance: str, trail: str | None) -> dict:
    """Resolve a URL trail to a view spec: crumbs + the current node's children
    (folder) or the leaf node (detail), plus a ``ctx`` describing the current
    node's place in the tree (for the sidebar). Raises Http404 on a bad path."""
    crumbs = [{"name": HOME_LABEL, "url": node_path(instance)}]
    segs = [s for s in (trail or "").split("/") if s]

    if not segs:
        return {"kind": "root", "name": HOME_LABEL, "sub": "Curated DUNE hardware",
                "crumbs": crumbs, "cards": _region_cards(instance), "ctx": _ctx("root")}

    region = next((r for r in all_regions(instance) if r.get("key") == segs[0]), None)
    if not region or not curation.region_is_browsable(region):
        raise Http404("unknown region")
    rk = region["key"]
    crumbs.append({"name": region["name"], "url": node_path(instance, rk)})
    if len(segs) == 1:
        return {"kind": "region", "name": region["name"], "sub": "",
                "crumbs": crumbs, "cards": _family_cards(instance, region),
                "ctx": _ctx("region", region_key=rk)}

    family = curation.find_family(region, segs[1])
    if not family or not curation.family_is_browsable(family):
        raise Http404("unknown family")
    fk = family["key"]
    flat = curation.family_is_flat(family)
    crumbs.append({"name": family["name"], "url": node_path(instance, rk, fk)})
    rest = segs[2:]

    # Resolve the system (implicit for flattened families).
    if flat:
        system = H.for_instance(instance).filter(level=H.LEVEL_SYSTEM,
                                                 system_id=family["systems"][0]).first()
    else:
        if not rest:
            return {"kind": "family", "name": family["name"], "sub": family.get("sub", ""),
                    "crumbs": crumbs, "cards": _system_cards(instance, region, family),
                    "ctx": _ctx("family", region_key=rk, family_key=fk, flat=flat)}
        sid = _int(rest[0])
        if sid not in (family.get("systems") or []):
            raise Http404("system not in family")
        system = H.for_instance(instance).filter(level=H.LEVEL_SYSTEM, system_id=sid).first()
        if not system:
            raise Http404("system not mirrored")
        crumbs.append({"name": system.system_name,
                       "url": node_path(instance, rk, fk, system_id=sid)})
        rest = rest[1:]

    if system is None:
        raise Http404("system not mirrored")
    sysid = system.system_id

    if not rest:
        out = {"kind": "family" if flat else "system",
               "name": family["name"] if flat else system.system_name,
               "sub": family.get("sub", "") if flat else "",
               "crumbs": crumbs,
               "cards": _subsystem_cards(instance, region, family, system, flat),
               "ctx": _ctx("family" if flat else "system", region_key=rk,
                           family_key=fk, flat=flat, system_id=sysid)}
        if region.get("overflow"):
            # Uncurated system page: the template auto-walks it on first visit.
            out["overflow_system"] = system
        return out

    ssid = _int(rest[0])
    subsystem = H.for_instance(instance).filter(level=H.LEVEL_SUBSYSTEM, system_id=sysid,
                                                subsystem_id=ssid).first()
    if not subsystem:
        raise Http404("unknown subsystem")
    crumbs.append({"name": subsystem.subsystem_name,
                   "url": node_path(instance, rk, fk, system_id=None if flat else sysid,
                                    subsystem_id=ssid)})
    rest = rest[1:]

    if not rest:
        return {"kind": "subsystem", "name": subsystem.subsystem_name, "sub": "",
                "crumbs": crumbs,
                "cards": _leaf_cards(instance, region, family, system, subsystem, flat),
                "ctx": _ctx("subsystem", region_key=rk, family_key=fk, flat=flat,
                            system_id=sysid, subsystem_id=ssid)}

    leaf = H.for_instance(instance).filter(level=H.LEVEL_TYPE, part_type_id=rest[0]).first()
    if not leaf:
        raise Http404("unknown component type")
    crumbs.append({"name": leaf.name,
                   "url": node_path(instance, rk, fk, system_id=None if flat else sysid,
                                    subsystem_id=ssid, part_type_id=leaf.part_type_id)})
    return {"kind": "leaf", "name": leaf.name, "sub": "", "crumbs": crumbs, "leaf": leaf,
            "ctx": _ctx("leaf", region_key=rk, family_key=fk, flat=flat,
                        system_id=sysid, subsystem_id=ssid, part_type_id=leaf.part_type_id)}


def _component_totals(instance):
    """({system_id: components}, {(system_id, subsystem_id): components}) in one
    grouped query — for the sidebar count badges."""
    by_sys, by_sub = {}, {}
    rows = (H.for_instance(instance).filter(level=H.LEVEL_TYPE)
            .values("system_id", "subsystem_id").annotate(c=Sum("n_components")))
    for r in rows:
        c = r["c"] or 0
        by_sys[r["system_id"]] = by_sys.get(r["system_id"], 0) + c
        by_sub[(r["system_id"], r["subsystem_id"])] = c
    return by_sys, by_sub


def _tnode(label, url, count, current, open_, dim=False, children=None, is_leaf=False,
           empty=False, synced=False, title=""):
    # ``title`` is the hover tooltip; systems/subsystems put their HWDB id
    # there (#50) — the sidebar is too narrow to show it inline.
    return {"label": label, "url": url, "count": count, "current": current,
            "open": open_, "dim": dim, "children": children or [], "is_leaf": is_leaf,
            "empty": empty, "synced": synced, "title": title or label}


def _leaf_synced(leaf) -> bool:
    """A component-type leaf counts as synced once its events have been pulled —
    test events, or (for shipping leaves) shipments."""
    return bool(leaf.tests_synced_at or leaf.shipments_synced_at)


def _state(n_with_comp: int, n_synced: int) -> tuple[bool, bool]:
    """(empty, synced) for a node from its subtree leaf counts: empty = no
    component-bearing leaves; synced = has some and *all* of them are synced."""
    if n_with_comp == 0:
        return True, False
    return False, n_synced == n_with_comp


def sidebar_tree(instance: str, ctx: dict) -> list[dict]:
    """The full curated tree as nested nodes for the sidebar. Every node is
    rendered (so any folder's chevron can expand/collapse it client-side); the
    branch to the current node (``ctx``) is flagged ``open`` so the tree opens to
    your location, and the current node is flagged for highlighting. Each node
    carries a component count."""
    by_sys, by_sub = _component_totals(instance)
    sys_by_id, subs_by_sys, leaves_by_sub = {}, {}, {}
    for n in H.for_instance(instance).order_by("system_id", "subsystem_id", "name"):
        if n.level == H.LEVEL_SYSTEM:
            sys_by_id[n.system_id] = n
        elif n.level == H.LEVEL_SUBSYSTEM:
            subs_by_sys.setdefault(n.system_id, []).append(n)
        else:
            leaves_by_sub.setdefault((n.system_id, n.subsystem_id), []).append(n)

    # Sync/empty stats per scope: (#leaves with components, #of those synced).
    sub_stats, sys_stats = {}, {}
    for (sid, ssid), leaves in leaves_by_sub.items():
        w = sum(1 for l in leaves if l.n_components > 0)
        s = sum(1 for l in leaves if l.n_components > 0 and _leaf_synced(l))
        sub_stats[(sid, ssid)] = (w, s)
        cw, cs = sys_stats.get(sid, (0, 0))
        sys_stats[sid] = (cw + w, cs + s)

    def _agg(system_ids):
        w = sum(sys_stats.get(i, (0, 0))[0] for i in system_ids)
        s = sum(sys_stats.get(i, (0, 0))[1] for i in system_ids)
        return w, s

    def subs_of(rk, fk, flat, sid):
        out = []
        for sub in subs_by_sys.get(sid, []):
            ssid = sub.subsystem_id
            on = ctx.get("system_id") == sid and ctx.get("subsystem_id") == ssid
            leaves = []
            for l in leaves_by_sub.get((sid, ssid), []):
                lempty = l.n_components == 0
                leaves.append(_tnode(
                    l.name,
                    node_path(instance, rk, fk, system_id=None if flat else sid,
                              subsystem_id=ssid, part_type_id=l.part_type_id),
                    l.n_components,
                    ctx.get("kind") == "leaf" and ctx.get("part_type_id") == l.part_type_id,
                    False, is_leaf=True,
                    empty=lempty, synced=not lempty and _leaf_synced(l)))
            sempty, ssynced = _state(*sub_stats.get((sid, ssid), (0, 0)))
            out.append(_tnode(sub.subsystem_name,
                              node_path(instance, rk, fk,
                                        system_id=None if flat else sid, subsystem_id=ssid),
                              by_sub.get((sid, ssid), 0),
                              ctx.get("kind") == "subsystem" and on, on, children=leaves,
                              empty=sempty, synced=ssynced,
                              title=f"{sub.subsystem_name} ({sid}.{ssid})"))
        return out

    tree = []
    for region in all_regions(instance):
        rbr = curation.region_is_browsable(region)
        rk = region["key"]
        fams, rcount = [], 0
        if rbr:
            for fam in region.get("families", []) or []:
                fbr = curation.family_is_browsable(fam)
                fk = fam["key"]
                fcount = sum(by_sys.get(i, 0) for i in fam.get("systems") or []) if fbr else None
                children = []
                if fbr:
                    rcount += fcount
                    flat = curation.family_is_flat(fam)
                    if flat:
                        sn = sys_by_id.get(fam["systems"][0])
                        if sn:
                            children = subs_of(rk, fk, True, sn.system_id)
                    else:
                        for sid in fam.get("systems") or []:
                            sn = sys_by_id.get(sid)
                            if not sn:
                                continue
                            sysempty, syssynced = _state(*sys_stats.get(sid, (0, 0)))
                            children.append(_tnode(
                                sn.system_name,
                                node_path(instance, rk, fk, system_id=sid),
                                by_sys.get(sid, 0),
                                ctx.get("kind") == "system" and ctx.get("system_id") == sid,
                                ctx.get("system_id") == sid,
                                children=subs_of(rk, fk, False, sid),
                                empty=sysempty, synced=syssynced,
                                title=f"{sn.system_name} ({sid})"))
                    fempty, fsynced = _state(*_agg(fam.get("systems") or []))
                else:
                    fempty, fsynced = False, False
                fams.append(_tnode(
                    fam["name"], node_path(instance, rk, fk) if fbr else None, fcount,
                    ctx.get("kind") == "family" and ctx.get("family_key") == fk,
                    ctx.get("family_key") == fk, dim=not fbr, children=children,
                    empty=fbr and fempty, synced=fsynced))
        rempty, rsynced = (False, False)
        if rbr:
            r_systems = [i for fam in region.get("families", []) or []
                         if curation.family_is_browsable(fam)
                         for i in fam.get("systems") or []]
            rempty, rsynced = _state(*_agg(r_systems))
        tree.append(_tnode(
            region["name"], node_path(instance, rk) if rbr else None, rcount if rbr else None,
            ctx.get("kind") == "region" and ctx.get("region_key") == rk,
            ctx.get("region_key") == rk, dim=not rbr, children=fams,
            empty=rbr and rempty, synced=rsynced))
    return tree


def _tree_subs(instance, region_key, family_key, sid, flat):
    """Subsystem nodes (+ their component-type leaves) for one system. Returns
    ``(nodes, n_with_components, n_synced)`` — the leaf tallies roll up so each
    node can carry the sidebar's ``empty``/``synced`` state. Leaves carry a
    ``url`` to their explorer page."""
    out, sys_w, sys_s = [], 0, 0
    for sub in (H.for_instance(instance).filter(level=H.LEVEL_SUBSYSTEM, system_id=sid)
                .order_by("subsystem_id")):
        types, w, s = [], 0, 0
        for leaf in (H.for_instance(instance)
                     .filter(level=H.LEVEL_TYPE, system_id=sid,
                             subsystem_id=sub.subsystem_id).order_by("name")):
            n = leaf.n_components or 0
            has, syn = n > 0, (leaf.n_components or 0) > 0 and _leaf_synced(leaf)
            w += 1 if has else 0
            s += 1 if syn else 0
            types.append({
                "kind": "type", "name": leaf.name, "ptid": leaf.part_type_id, "n": n,
                "empty": not has, "synced": syn,
                "url": node_path(instance, region_key, family_key,
                                 system_id=None if flat else sid,
                                 subsystem_id=sub.subsystem_id, part_type_id=leaf.part_type_id),
            })
        empty, synced = _state(w, s)
        out.append({"kind": "sub", "name": sub.subsystem_name or sub.name,
                    "id": sub.subsystem_id, "sys": sid,
                    "n": sum(t["n"] for t in types),
                    "empty": empty, "synced": synced, "children": types})
        sys_w += w
        sys_s += s
    return out, sys_w, sys_s


def curated_tree(instance: str) -> dict:
    """The whole curated Region → Family → System → Subsystem → type tree as
    nested dicts for the hierarchy homepage (#tree view).

    Mirrors ``curation.yaml``: single-system families are flattened (no system
    tier), non-browsable regions/families are ``locked`` placeholders. Every
    leaf carries ``url`` (its explorer page); ``n`` is components in HWDB; each
    node carries ``empty`` (no component-bearing leaves) and ``synced`` (all of
    them synced) — the same grey/green convention as the sidebar.
    """
    regions_out = []
    for r in all_regions(instance):
        browsable = curation.region_is_browsable(r)
        rnode = {"kind": "region", "name": r["name"], "key": r["key"],
                 "locked": not browsable, "note": r.get("note", ""), "children": []}
        rw = rs = 0
        if browsable:
            for f in r.get("families", []) or []:
                fkey = f["key"]
                if not curation.family_is_browsable(f):
                    rnode["children"].append({
                        "kind": "family", "name": f["name"], "key": fkey,
                        "sub": f.get("sub", ""), "locked": True,
                        "note": f.get("note", ""), "children": [], "n": 0,
                        "empty": True, "synced": False})
                    continue
                flat = curation.family_is_flat(f)
                sysids = f.get("systems") or []
                fam = {"kind": "family", "name": f["name"], "key": fkey,
                       "sub": f.get("sub", ""), "children": []}
                fw = fs = 0
                if flat:
                    fam["children"], fw, fs = _tree_subs(instance, r["key"], fkey,
                                                         sysids[0], flat=True)
                else:
                    for sid in sysids:
                        node = H.for_instance(instance).filter(
                            level=H.LEVEL_SYSTEM, system_id=sid).first()
                        if not node:
                            continue
                        subs, sw, ss = _tree_subs(instance, r["key"], fkey, sid, flat=False)
                        s_empty, s_synced = _state(sw, ss)
                        fam["children"].append({
                            "kind": "system", "name": node.system_name, "id": sid,
                            "n": sum(s["n"] for s in subs), "empty": s_empty,
                            "synced": s_synced, "children": subs})
                        fw += sw
                        fs += ss
                fam["n"] = sum(c["n"] for c in fam["children"])
                fam["empty"], fam["synced"] = _state(fw, fs)
                if r.get("overflow") and not fam["children"]:
                    # Unwalked overflow system: childless nodes only render as
                    # links when they carry a url — point it at its own page,
                    # which walks the system on first visit (#49).
                    fam["url"] = node_path(instance, r["key"], fkey)
                    fam["unwalked"] = True
                rnode["children"].append(fam)
                rw += fw
                rs += fs
        rnode["n"] = sum(c.get("n", 0) for c in rnode["children"])
        rnode["empty"], rnode["synced"] = _state(rw, rs)
        regions_out.append(rnode)
    return {"kind": "root", "name": "DUNE", "sub": "Project D",
            "children": regions_out, "n": sum(r["n"] for r in regions_out)}


def leaf_path_for(instance: str, part_type_id: str) -> str | None:
    """The deep-link URL for a leaf by part_type_id (for the ?node= redirect).
    Resolves the leaf's region/family from the mirror + curation; None if the
    leaf or its curated family can't be found."""
    leaf = H.for_instance(instance).filter(
        level=H.LEVEL_TYPE, part_type_id=part_type_id).first()
    if not leaf:
        return None
    for region in all_regions(instance):
        if not curation.region_is_browsable(region):
            continue
        for family in region.get("families", []) or []:
            if not curation.family_is_browsable(family):
                continue
            if leaf.system_id in (family.get("systems") or []):
                flat = curation.family_is_flat(family)
                return node_path(instance, region["key"], family["key"],
                                 system_id=None if flat else leaf.system_id,
                                 subsystem_id=leaf.subsystem_id,
                                 part_type_id=leaf.part_type_id)
    return None
