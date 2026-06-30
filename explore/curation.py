"""Load and query the curated taxonomy (`curation.yaml`, ADR-0012).

The YAML is the source of truth for what's browsable. A **family** is browsable
when it isn't marked ``curated: false`` and lists ≥1 system; a **region** is
browsable unless marked ``curated: false``. Browsable families' system ids are
exactly what the refresh walks and the tree shows; non-browsable
families/regions are declared placeholders rendered dimmed.
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


def regions() -> list[dict]:
    return load_curation().get("regions", []) or []


def _family_is_browsable(fam: dict) -> bool:
    return fam.get("curated", True) is not False and bool(fam.get("systems"))


def _region_is_browsable(region: dict) -> bool:
    return region.get("curated", True) is not False


def find_region(key: str) -> dict | None:
    return next((r for r in regions() if r.get("key") == key), None)


def find_family(region: dict, key: str) -> dict | None:
    return next((f for f in region.get("families", []) or [] if f.get("key") == key), None)


def family_is_browsable(fam: dict) -> bool:
    return _family_is_browsable(fam)


def region_is_browsable(region: dict) -> bool:
    return _region_is_browsable(region)


def family_is_flat(fam: dict) -> bool:
    """A family that owns exactly one system collapses the system tier."""
    return len(fam.get("systems") or []) == 1


def curated_system_ids() -> set[int]:
    """All system ids the explorer browses/syncs — the union across browsable
    families in browsable regions."""
    ids: set[int] = set()
    for region in regions():
        if not _region_is_browsable(region):
            continue
        for fam in region.get("families", []) or []:
            if _family_is_browsable(fam):
                ids.update(fam.get("systems") or [])
    return ids
