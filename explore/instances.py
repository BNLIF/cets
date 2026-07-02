"""URL-carried HWDB instance selection for the explorer (#47).

The explorer serves both HWDB instances from one deployment: prod at ``/hw/``
and dev at ``/hw/dev/`` (the same URLconf included twice, under the instance
namespaces below). The instance lives in the URL — not the session — so links
are shareable and a PID is unambiguous. Distinct from ``hwdb.instance``, the
internal app's per-session toggle.
"""

from __future__ import annotations

NAMESPACE_BY_INSTANCE = {"prod": "explore", "dev": "explore_dev"}
INSTANCE_BY_NAMESPACE = {v: k for k, v in NAMESPACE_BY_INSTANCE.items()}


def instance_of(request) -> str:
    """The HWDB instance this request's URL addresses ("prod" | "dev")."""
    rm = getattr(request, "resolver_match", None)
    return INSTANCE_BY_NAMESPACE.get(rm.namespace if rm else None, "prod")


def namespace_of(instance: str) -> str:
    """The URL instance namespace for reversing explore URLs on an instance."""
    return NAMESPACE_BY_INSTANCE[instance]
