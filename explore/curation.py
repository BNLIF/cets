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
from pathlib import Path

import yaml

CURATION_PATH = Path(__file__).parent / "curation.yaml"


@functools.lru_cache(maxsize=1)
def load_curation() -> dict:
    with open(CURATION_PATH) as f:
        return yaml.safe_load(f) or {}


def _block(instance: str) -> dict:
    return (load_curation().get("instances") or {}).get(instance) or {}


def regions(instance: str) -> list[dict]:
    return _block(instance).get("regions", []) or []


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


def shipping_types(instance: str) -> set[str]:
    """Component-type ids whose items are shipping boxes (ADR-0013)."""
    return set(_block(instance).get("shipping_types") or [])


def is_shipping_type(instance: str, part_type_id: str) -> bool:
    return part_type_id in shipping_types(instance)


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
