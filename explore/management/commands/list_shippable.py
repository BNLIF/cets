"""Audit which curated component types are shipping boxes (#46).

Read-only, **mirror-only** (no HWDB calls, no bearer). The broad spike of
ADR-0013, settled by the live #46 runs: neither "has a location" (everything in
HWDB does) nor "has subcomponents" (assemblies do too, and empty boxes don't)
discriminates a shipping box. The reliable signal is HWDB's own structure — a
shipping box lives under a **"Shipping" subsystem** (e.g. "CE Shipping Box",
"Shipping"). So this lists curated component-type leaves whose subsystem name
matches, with their box count, flagging which are already in ``shipping_types``
and which are **new candidates** to curate. Same audit→curate loop as
``list_systems``.

Reads the local hierarchy mirror, so run "Refresh hierarchy" first if it's
stale. Component counts come from the mirror.

    python manage.py list_shippable
    python manage.py list_shippable --system 57
    python manage.py list_shippable --match crate
"""
from django.core.management.base import BaseCommand

from explore import curation
from explore.models import HierarchyNode


class Command(BaseCommand):
    help = "Audit curated component types under a Shipping subsystem (mirror-only, read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--match", default="shipping",
            help="Subsystem-name substring marking a shipping subsystem (default: shipping).",
        )
        parser.add_argument(
            "--system", type=int,
            help="Restrict to one system id (default: all curated systems).",
        )

    def handle(self, *args, **opts):
        match = opts["match"].lower()
        qs = HierarchyNode.objects.filter(level=HierarchyNode.LEVEL_TYPE)
        if opts.get("system") is not None:
            qs = qs.filter(system_id=opts["system"])
        else:
            qs = qs.filter(system_id__in=curation.curated_system_ids())
        leaves = [
            n for n in qs.order_by("system_id", "subsystem_id", "name")
            if match in (n.subsystem_name or "").lower()
        ]

        if not leaves:
            self.stdout.write(
                f"No curated component types under a '{match}' subsystem in the mirror. "
                "Run 'Refresh hierarchy' first, or try --match / --system."
            )
            return

        self.stdout.write(
            f"Curated component types under a '{match}' subsystem "
            f"({len(leaves)} found):\n"
        )
        self.stdout.write(f"{'boxes':>6}  {'curated':<8}  {'part type':<14}  name")
        self.stdout.write("-" * 76)

        candidates = []
        for leaf in leaves:
            is_curated = curation.is_shipping_type(leaf.part_type_id)
            if not is_curated:
                candidates.append(leaf)
            self.stdout.write(
                f"{leaf.n_components:>6}  {'yes' if is_curated else 'NO':<8}  "
                f"{leaf.part_type_id:<14}  "
                f"{leaf.system_name} › {leaf.subsystem_name} › {leaf.name}"
            )

        self.stdout.write("-" * 76)
        active = [c for c in candidates if c.n_components > 0]
        self.stdout.write(
            f"{len(leaves)} shipping-subsystem type(s) · "
            f"{len(leaves) - len(candidates)} curated · {len(candidates)} not curated "
            f"({len(active)} with boxes today)"
        )
        if candidates:
            self.stdout.write("")
            self.stdout.write(
                "Candidates — add the real shipping boxes to shipping_types in "
                "curation.yaml (those with 0 boxes are registered but empty):"
            )
            for c in candidates:
                self.stdout.write(
                    f"  - {c.part_type_id}   # {c.system_name} › {c.name} ({c.n_components} boxes)"
                )
        else:
            self.stdout.write("No new candidates — shipping_types looks complete for this scope.")
