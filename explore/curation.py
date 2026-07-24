"""Load and query the curated taxonomy (`curation.yaml`, ADR-0012).

The YAML is the source of truth for what's browsable, per HWDB instance (#47):
top-level ``instances.prod`` / ``instances.dev`` blocks each hold ``regions``
and ``shipping_types``. A **family** is browsable when it isn't marked
``curated: false`` and lists ≥1 system; a **region** is browsable unless marked
``curated: false``. Browsable families' system ids are exactly what the refresh
walks and the tree shows; non-browsable families/regions are declared
placeholders rendered dimmed. Every accessor takes the instance explicitly —
ids are per-instance and must never leak across.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml

CURATION_PATH = Path(__file__).parent / "curation.yaml"

_SUBSYS_SELECTOR = re.compile(r"^\d+\.\d+$")  # "86.990" = system 86, subsystem 990


@functools.lru_cache(maxsize=1)
def load_curation() -> dict:
    with open(CURATION_PATH) as f:
        return yaml.safe_load(f) or {}


def _block(instance: str) -> dict:
    return (load_curation().get("instances") or {}).get(instance) or {}


def regions(instance: str) -> list[dict]:
    return _block(instance).get("regions", []) or []


def extra_projects(instance: str) -> list[str]:
    """Ids of the extra HWDB projects (PID part1 letters) mirrored besides
    "D" (#71). YAML entries are ``{id: Z, name: Sandbox}`` (or bare letters).
    Each renders as its own synthetic region at the same tree level as DUNE;
    its systems are recorded by the full refresh (names only) and walked
    lazily on first visit, like the overflow section."""
    out = []
    for e in _block(instance).get("extra_projects") or []:
        out.append(str(e["id"]) if isinstance(e, dict) else str(e))
    return out


def project_is_test(instance: str, project_id: str) -> bool:
    """Whether an extra project is a test/sandbox one (``test: true`` in the
    yaml) — shown in the tree but excluded from the overview stats."""
    for e in _block(instance).get("extra_projects") or []:
        if isinstance(e, dict) and str(e.get("id")) == project_id:
            return bool(e.get("test"))
    return False


def project_label(instance: str, project_id: str) -> str:
    """Display label for a project — its upstream name plus the letter, e.g.
    ``Sandbox (Z)``. Names live in the yaml (audited from ``GET projects``,
    per instance); an id-only entry falls back to ``Project Z``."""
    if project_id == "D":
        return "DUNE (D)"
    for e in _block(instance).get("extra_projects") or []:
        if isinstance(e, dict) and str(e.get("id")) == project_id and e.get("name"):
            return f"{e['name']} ({project_id})"
    return f"Project {project_id}"


def _family_is_browsable(fam: dict) -> bool:
    return fam.get("curated", True) is not False and bool(fam.get("systems"))


def _region_is_browsable(region: dict) -> bool:
    return region.get("curated", True) is not False


def find_region(instance: str, key: str) -> dict | None:
    return next((r for r in regions(instance) if r.get("key") == key), None)


def find_family(region: dict, key: str) -> dict | None:
    return next((f for f in region.get("families", []) or [] if f.get("key") == key), None)


def family_is_browsable(fam: dict) -> bool:
    return _family_is_browsable(fam)


def region_is_browsable(region: dict) -> bool:
    return _region_is_browsable(region)


def family_is_flat(fam: dict) -> bool:
    """A family that owns exactly one system collapses the system tier."""
    return len(fam.get("systems") or []) == 1


def _split_shipping(instance: str) -> tuple[set[str], set[tuple[int, int]]]:
    """Parse ``shipping_types`` entries into (explicit part-type ids,
    whole-subsystem selectors). A selector is a quoted ``"system.subsystem"``
    string like ``"86.990"`` — every component type under that subsystem is a
    shipping box. Unquoted, YAML reads 86.990 as the float 86.99 (dropping the
    trailing zero), so numeric entries are rejected loudly."""
    ptids, subs = set(), set()
    for entry in _block(instance).get("shipping_types") or []:
        if isinstance(entry, (int, float)):
            raise ValueError(
                f"shipping_types entry {entry!r} ({instance}): quote subsystem "
                f'selectors (e.g. "86.990") — unquoted YAML floats lose digits.'
            )
        if _SUBSYS_SELECTOR.match(entry):
            sid, ssid = entry.split(".")
            subs.add((int(sid), int(ssid)))
        else:
            ptids.add(entry)
    return ptids, subs


def shipping_types(instance: str) -> set[str]:
    """Explicitly-listed component-type ids whose items are shipping boxes
    (ADR-0013). Whole-subsystem selectors are separate — see
    ``shipping_subsystems``."""
    return _split_shipping(instance)[0]


def shipping_subsystems(instance: str) -> set[tuple[int, int]]:
    """(system_id, subsystem_id) pairs whose every component type is a
    shipping box — the ``"86.990"``-style curation shorthand."""
    return _split_shipping(instance)[1]


def _ptid_coord(part_type_id: str) -> tuple[int, int] | None:
    """(system, subsystem) decoded from a part-type id — HWDB encodes them as
    D·SSS·PPP·NNNNN (e.g. D08699000012 → (86, 990)). None if it doesn't parse.
    Project-D only: system ids are per-project (#71), so the "86.990" selectors
    must not capture a Z/L type that happens to share coordinates — other
    projects' shipping types are listed as explicit part-type ids."""
    m = re.match(r"^D(\d{3})(\d{3})\d+$", part_type_id or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def is_shipping_type(instance: str, part_type_id: str) -> bool:
    if part_type_id in shipping_types(instance):
        return True
    subs = shipping_subsystems(instance)
    return bool(subs) and _ptid_coord(part_type_id) in subs


def has_overflow(instance: str) -> bool:
    """Whether uncurated systems on this instance render in an automatic
    "Uncurated" section (#49) instead of being invisible. Dev sets it; prod
    keeps its deliberate dimmed placeholders."""
    return bool(_block(instance).get("overflow"))


def curated_system_ids(instance: str) -> set[int]:
    """All system ids the explorer browses/syncs on an instance — the union
    across browsable families in browsable regions."""
    ids: set[int] = set()
    for region in regions(instance):
        if not _region_is_browsable(region):
            continue
        for fam in region.get("families", []) or []:
            if _family_is_browsable(fam):
                ids.update(fam.get("systems") or [])
    return ids
